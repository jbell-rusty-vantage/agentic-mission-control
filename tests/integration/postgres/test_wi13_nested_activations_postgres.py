"""WI-13 / OVE-176 on a disposable PostgreSQL 17: the newest built release plus
``scripts/release_1130/0071_nested_program_activations.sql``.

The runtime role (forced row security) records one nested activation per parent unit attempt,
idempotently; another child for the same attempt, or the same child for another attempt,
refuses; the export receipt settles exactly once (the trigger refuses every other change and
every delete); a fresh store over the same rows (a restarted worker) reads the same lineage; and
another tenant sees none of it.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio

from mission_control.adapters.postgres.orchestration.nested_activations import (
    PostgresNestedActivationStore,
)
from mission_control.adapters.postgres.run_control import canonical as mc
from mission_control.application.programs.nested_bodies import (
    NestedActivationConflict,
    NestedActivationRecord,
)
from mission_control.domain.authoring.canonical import sha256_digest
from tests.fixtures.mission_control_common_db import (
    CommonDatabase,
    common_database,
    migration_paths_with,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.common_db]
AT = datetime(2026, 10, 29, 12, tzinfo=UTC)
MIGRATION = (
    Path(__file__).resolve().parents[3] / "scripts/release_1130/0071_nested_program_activations.sql"
)


@pytest_asyncio.fixture
async def wi13_db() -> AsyncIterator[CommonDatabase]:
    async with common_database(paths=migration_paths_with(MIGRATION)) as database:
        yield database


def record(db: CommonDatabase, **changes: object) -> NestedActivationRecord:
    base = NestedActivationRecord(
        request_scope=db.scope("tenant-1"),
        parent_run_id="run-parent",
        host_id="research",
        semantic_attempt_id="run-parent:operation:stage:research:attempt:1",
        position="research",
        family="GoalDirected",
        depth=1,
        child_run_id="run-child-1",
        budget_ceiling={"tokens.total": 40},
        body_digest="sha256:" + "b" * 64,
        activated_at=AT,
    )
    return replace(base, **changes)  # type: ignore[arg-type]


def receipt(outcome: str = "accepted") -> dict[str, object]:
    body = {"schema": "mc.nested_export_receipt.v1", "outcome": outcome, "exports": []}
    return {**body, "receipt_digest": sha256_digest(body)}


async def test_activation_lineage_is_write_once_settle_once_and_scoped(
    wi13_db: CommonDatabase,
) -> None:
    pool = await wi13_db.pool()
    try:
        store = PostgresNestedActivationStore(pool)
        first = await store.record(record(wi13_db))
        assert first.child_run_id == "run-child-1" and first.receipt is None
        assert await store.record(record(wi13_db)) == first  # redelivered activation
        with pytest.raises(NestedActivationConflict):
            await store.record(record(wi13_db, child_run_id="run-child-2"))
        with pytest.raises(NestedActivationConflict):
            await store.record(record(wi13_db, semantic_attempt_id="other-attempt"))
        revisit = await store.record(
            record(
                wi13_db,
                semantic_attempt_id="run-parent:operation:stage:research:attempt:2",
                child_run_id="run-child-2",
                activated_at=AT + timedelta(minutes=5),
            )
        )
        settled = await store.settle(wi13_db.scope("tenant-1"), "run-child-1", receipt(), AT)
        assert settled.receipt == receipt() and settled.settled_at == AT
        again = await store.settle(
            wi13_db.scope("tenant-1"), "run-child-1", receipt(), AT + timedelta(hours=1)
        )
        assert again.settled_at == AT
        with pytest.raises(NestedActivationConflict):
            await store.settle(wi13_db.scope("tenant-1"), "run-child-1", receipt("x"), AT)
        with pytest.raises(LookupError):
            await store.settle(wi13_db.scope("tenant-1"), "unknown-child", receipt(), AT)

        # A restarted worker reads the same lineage through a fresh store.
        restarted = PostgresNestedActivationStore(pool)
        lineage = await restarted.for_parent(wi13_db.scope("tenant-1"), "run-parent")
        assert [item.child_run_id for item in lineage] == ["run-child-1", "run-child-2"]
        assert lineage[1] == revisit
        found = await restarted.get(
            wi13_db.scope("tenant-1"),
            "run-parent",
            "research",
            "run-parent:operation:stage:research:attempt:1",
        )
        assert found is not None and found.receipt == receipt()
        child = await restarted.by_child(wi13_db.scope("tenant-1"), "run-child-2")
        assert child is not None and child.semantic_attempt_id.endswith("attempt:2")
        assert await restarted.by_child(wi13_db.scope("tenant-1"), "unknown") is None
        # Another tenant sees nothing (forced row security).
        assert await restarted.for_parent(wi13_db.scope("tenant-2"), "run-parent") == ()

        # Only the receipt moves, once; nothing is rewritten or deleted.
        async with pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, wi13_db.scope("tenant-1"))
            with pytest.raises(asyncpg.CheckViolationError, match="only the export receipt"):
                await connection.execute(
                    "UPDATE mission_control.nested_activation SET depth = 2 "
                    "WHERE installation_id = $1 AND application_id = $2 AND tenant_id = $3 "
                    "AND child_run_key = 'run-child-2'",
                    *args,
                )
        async with pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, wi13_db.scope("tenant-1"))
            with pytest.raises(asyncpg.CheckViolationError, match="settles once"):
                await connection.execute(
                    "UPDATE mission_control.nested_activation SET receipt = '{}'::jsonb "
                    "WHERE installation_id = $1 AND application_id = $2 AND tenant_id = $3 "
                    "AND child_run_key = 'run-child-1'",
                    *args,
                )
        async with pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, wi13_db.scope("tenant-1"))
            with pytest.raises(asyncpg.PostgresError):
                await connection.execute(
                    "DELETE FROM mission_control.nested_activation "
                    "WHERE installation_id = $1 AND application_id = $2 AND tenant_id = $3",
                    *args,
                )
    finally:
        await pool.close()


async def test_the_schema_refuses_an_unbounded_or_self_parented_activation(
    wi13_db: CommonDatabase,
) -> None:
    pool = await wi13_db.pool()
    try:
        store = PostgresNestedActivationStore(pool)
        with pytest.raises(asyncpg.CheckViolationError):
            await store.record(record(wi13_db, depth=5))
        with pytest.raises(asyncpg.CheckViolationError):
            await store.record(record(wi13_db, child_run_id="run-parent"))
        with pytest.raises(asyncpg.CheckViolationError):
            await store.record(record(wi13_db, family="ParallelSwarm"))
    finally:
        await pool.close()


async def test_a_nested_child_is_admitted_once_into_the_parent_revision(
    wi13_db: CommonDatabase,
) -> None:
    """S-A: a redelivered nested admission (same request) returns the same child run: one
    admission receipt, one run attached to the parent's mission and revision, one lineage row
    that ``by_child`` finds; a conflicting request under the same identity refuses."""

    from mission_control.adapters.postgres.control_plane.nested_runs import (
        PostgresNestedRunAdmissions,
    )
    from mission_control.adapters.postgres.run_control.run_control_repository import (
        PostgresRunControlRepository,
    )
    from mission_control.application.programs.nested_bodies import NestedLaunchRefused
    from mission_control.domain.programs.nested import NESTED_ISSUER
    from tests.unit.run_control.test_run_control import request, service

    pool = await wi13_db.pool()
    try:
        scope = wi13_db.scope("tenant-1")
        run_control, _ = service(PostgresRunControlRepository(pool))  # type: ignore[arg-type]
        parent = await run_control.admit(request(request_scope=scope, request_id="parent"))
        assert parent.run_id is not None
        child_request = request(request_scope=scope, request_id="nested:child-1").model_copy(
            update={"idempotency_issuer": NESTED_ISSUER}
        )
        verified = await run_control.verify_admission(child_request)
        admissions = PostgresNestedRunAdmissions(pool)
        first, second = await asyncio.gather(
            admissions.admit(scope, parent.run_id, child_request, verified),
            admissions.admit(scope, parent.run_id, child_request, verified),
        )
        assert first == second
        assert await admissions.admit(scope, parent.run_id, child_request, verified) == first
        with pytest.raises(NestedLaunchRefused) as conflict:
            await admissions.admit(
                scope,
                parent.run_id,
                child_request.model_copy(update={"correlation_id": "another-request"}),
                verified,
            )
        assert conflict.value.code == "nested_admission_conflict"
        async with pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            runs = await connection.fetch(
                "SELECT run_key, mission_id, revision_id FROM mission_control.mission_run "
                f"WHERE {mc.SCOPE} AND run_key = ANY($4::text[])",
                *args,
                [parent.run_id, first],
            )
            receipts = await connection.fetchval(
                "SELECT count(*) FROM mission_control.request_receipt "
                f"WHERE {mc.SCOPE} AND actor_ref = $4 AND request_key = $5",
                *args,
                NESTED_ISSUER,
                "nested:child-1",
            )
        by_key = {row["run_key"]: row for row in runs}
        assert set(by_key) == {parent.run_id, first}
        assert by_key[first]["mission_id"] == by_key[parent.run_id]["mission_id"]
        assert by_key[first]["revision_id"] == by_key[parent.run_id]["revision_id"]
        assert receipts == 1
        store = PostgresNestedActivationStore(pool)
        await store.record(record(wi13_db, parent_run_id=parent.run_id, child_run_id=first))
        found = await store.by_child(scope, first)
        assert found is not None and found.parent_run_id == parent.run_id
    finally:
        await pool.close()
