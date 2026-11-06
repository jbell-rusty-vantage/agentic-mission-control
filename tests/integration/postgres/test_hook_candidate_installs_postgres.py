"""WI-17 / OVE-180 install records on a disposable PostgreSQL 17 (restricted runtime login,
forced RLS): the built 1.7.0 release, whose ``0060_hook_candidate_installs`` migration carries the
install records.

- a same-path race between two workers installs one candidate (one claim, one outcome, one
  write); the loser refuses ``PATH_CLAIMED``;
- a crash after the write (before the outcome) is recovered by a fresh worker once, without a
  second write; a crash after the outcome is never installed again;
- the tables refuse host-state and sealed-input targets, an outcome whose digest is not the
  claimed one, a guard-event origin, and any update or delete; another tenant sees nothing.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import asyncpg
import pytest
import pytest_asyncio

from mission_control.adapters.postgres.context.candidate_installs import (
    PostgresCandidateInstallStore,
)
from mission_control.application.context.hook_contributions import (
    ContributionSession,
    ContributionTarget,
    HookContributionService,
    HookGrants,
    InstallOutcome,
)
from mission_control.contracts.hooks import HookResult
from mission_control.domain.capabilities.hooks import HookEvent
from mission_control.domain.context.contributions import (
    CandidateOrigin,
    StagedCandidate,
    StageGrant,
    content_digest,
)
from tests.fixtures.hook_contributions import Crash, MemoryWorkspace
from tests.fixtures.knowledge_binding import InMemoryStaging
from tests.fixtures.mission_control_common_db import (
    CommonDatabase,
    common_database,
    migration_paths,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.common_db]
GRANT = StageGrant(paths=("/prepared/**",))


@pytest_asyncio.fixture
async def db() -> AsyncIterator[CommonDatabase]:
    async with common_database(paths=migration_paths()) as database:
        yield database


@pytest_asyncio.fixture
async def pool(db: CommonDatabase) -> AsyncIterator[asyncpg.Pool]:
    created = await db.pool()
    try:
        yield created
    finally:
        await created.close()


class CrashingStore(PostgresCandidateInstallStore):
    """Dies once around the outcome insert (a worker killed at that instruction)."""

    def __init__(self, pool: asyncpg.Pool, *, before: bool) -> None:
        super().__init__(pool)
        self._before = before
        self._armed = True

    async def record_outcome(self, scope: str, outcome: InstallOutcome) -> InstallOutcome:
        if self._armed and self._before:
            self._armed = False
            raise Crash("killed after the write, before the outcome")
        stored = await super().record_outcome(scope, outcome)
        if self._armed:
            self._armed = False
            raise Crash("killed after the outcome")
        return stored


def origin(event: HookEvent = HookEvent.AFTER_TOOL, attempt: int = 1) -> CandidateOrigin:
    return CandidateOrigin(
        hook_id="hook.notes",
        event=event,
        run_id="run-1",
        operation_id="op-1",
        attempt_no=attempt,
        generation=1,
        harness_execution_id=f"exec-{attempt}",
        input_digest=content_digest(b"input"),
    )


def candidate(body: str, path: str = "/prepared/a.md") -> StagedCandidate:
    return StagedCandidate(path=path, content=body, digest=content_digest(body.encode()))


def session(  # type: ignore[no-untyped-def]
    db: CommonDatabase,
    store: PostgresCandidateInstallStore,
    staging: InMemoryStaging,
    attempt: int = 1,
):
    return ContributionSession(
        service=HookContributionService(
            store=store,
            staging=staging,  # type: ignore[arg-type]
            custody=staging,  # type: ignore[arg-type]
        ),
        target=ContributionTarget(
            scope=db.scope(), run_id="run-1", operation_ref="op-1", attempt=attempt
        ),
        grants={"hook.notes": HookGrants(stage=GRANT)},
    )


async def test_a_same_path_race_installs_one_candidate(db, pool) -> None:  # type: ignore[no-untyped-def]
    staging = InMemoryStaging()
    workspace = MemoryWorkspace()
    first = session(db, PostgresCandidateInstallStore(pool), staging)
    second = session(db, PostgresCandidateInstallStore(pool), staging)
    await first.collect(origin(), HookResult(staged_candidates=(candidate("first worker"),)))
    await second.collect(origin(), HookResult(staged_candidates=(candidate("second worker"),)))
    receipts = await asyncio.gather(
        first.boundary(workspace, "before_model_call"),
        second.boundary(workspace, "before_model_call"),
    )
    installed = [item for receipt in receipts for item in receipt.installed]
    refused = [item.code for receipt in receipts for item in receipt.refusals]
    assert len(installed) == 1
    assert refused in (["PATH_CLAIMED"], ["VERSION_CONFLICT"])
    assert workspace.writes == ["/prepared/a.md"]
    claims = await PostgresCandidateInstallStore(pool).claims_for(db.scope(), "run-1", "op-1", 1, 1)
    assert len(claims) == 1 and claims[0].candidate.digest == installed[0].digest


@pytest.mark.parametrize("before", [True, False], ids=["before-outcome", "after-outcome"])
async def test_a_crash_around_the_outcome_recovers_once(db, pool, before: bool) -> None:  # type: ignore[no-untyped-def]
    staging = InMemoryStaging()
    workspace = MemoryWorkspace()
    dying = session(db, CrashingStore(pool, before=before), staging)
    await dying.collect(origin(), HookResult(staged_candidates=(candidate("notes"),)))
    with pytest.raises(Crash):
        await dying.boundary(workspace, "before_model_call")

    fresh = session(db, PostgresCandidateInstallStore(pool), staging)
    await fresh.collect(origin(), HookResult(staged_candidates=(candidate("notes"),)))
    receipt = await fresh.boundary(workspace, "before_model_call")
    assert [(item.path, item.recovered) for item in receipt.installed] == [("/prepared/a.md", True)]
    assert workspace.writes == ["/prepared/a.md"]
    rows = await _owner(
        db, "SELECT recovered FROM mission_control.context_candidate_install_outcome"
    )
    assert [row["recovered"] for row in rows] == [before]


async def _owner(db: CommonDatabase, query: str, *args: object) -> list[asyncpg.Record]:
    connection = await asyncpg.connect(db.owner_dsn)
    try:
        return await connection.fetch(query, *args)
    finally:
        await connection.close()


async def test_the_tables_guard_targets_digests_events_mutation_and_scope(db, pool) -> None:  # type: ignore[no-untyped-def]
    store = PostgresCandidateInstallStore(pool)
    staging = InMemoryStaging()
    contrib = session(db, store, staging)
    await contrib.collect(origin(), HookResult(staged_candidates=(candidate("notes"),)))
    receipt = await contrib.boundary(MemoryWorkspace(), "before_model_call")
    (record,) = receipt.installed
    (claim,) = await store.claims_for(db.scope(), "run-1", "op-1", 1, 1)

    async def refused(sqlstate: str, statement: str, *args: object) -> None:
        async with pool.acquire() as connection:
            with pytest.raises(asyncpg.PostgresError) as caught:
                async with connection.transaction():
                    await connection.execute(
                        "SELECT set_config('mc.installation_id',$1,true), "
                        "set_config('mc.application_id',$2,true), "
                        "set_config('mc.tenant_id',$3,true)",
                        str(db.installation_id),
                        db.application_id,
                        str(db.tenants["tenant-1"]),
                    )
                    await connection.execute(statement, *args)
            assert caught.value.sqlstate == sqlstate, caught.value

    document = claim.candidate.model_dump(mode="json")

    def insert(path: str, event: str = "after_tool") -> tuple[str, tuple[object, ...]]:
        body = {**document, "path": path, "origin": {**document["origin"], "event": event}}
        return (
            "INSERT INTO mission_control.context_candidate_install (installation_id, "
            "application_id, tenant_id, install_id, run_id, receiver_operation_ref, "
            "receiver_attempt, target_path, candidate_id, candidate_digest, size_bytes, "
            "custody_ref, hook_id, hook_event, "
            "candidate, workspace_generation, boundary, claimed_at, created_at, "
            "created_by_actor_ref) VALUES ($1::uuid, $2, $3::uuid, gen_random_uuid(), 'run-1', "
            "'op-1', 1, $4, $5::uuid, $6, $7, 'mem://x', 'hook.notes', $8, $9::jsonb, 1, 'b', "
            "now(), now(), 'fixture:wi17')",
            (
                str(db.installation_id),
                db.application_id,
                str(db.tenants["tenant-1"]),
                path,
                document["candidate_id"],
                document["digest"],
                document["size_bytes"],
                event,
                json.dumps(body),
            ),
        )

    for path in (
        "/.mission/state.json",
        "/.MISSION/state.json",
        "/inputs/report/r7.md",
        "/Inputs/report/r7.md",
        "/prepared/../inputs/x",
    ):
        statement, args = insert(path)
        await refused("23514", statement, *args)
    statement, args = insert("/prepared/guard.md", event="before_tool")
    await refused("23514", statement, *args)
    await refused(
        "23514",
        "INSERT INTO mission_control.context_candidate_install_outcome (installation_id, "
        "application_id, tenant_id, install_id, candidate_id, candidate_digest, observed_digest, "
        "realized_backend, probe, recovered, installed_at, created_at, created_by_actor_ref) "
        "VALUES ($1::uuid, $2, $3::uuid, $4::uuid, $5::uuid, $6, $7, 'memory', 'backend_read', "
        "false, now(), now(), 'fixture:wi17')",
        str(db.installation_id),
        db.application_id,
        str(db.tenants["tenant-1"]),
        record.install_id,
        record.candidate_id,
        record.digest,
        content_digest(b"other bytes"),
    )
    owner = await asyncpg.connect(db.owner_dsn)
    try:
        for table in ("context_candidate_install", "context_candidate_install_outcome"):
            await refused("42501", f"DELETE FROM mission_control.{table}")
            await refused("42501", f"UPDATE mission_control.{table} SET created_by_actor_ref = 'x'")
            # Even the owner cannot rewrite an install record: the rows are immutable.
            with pytest.raises(asyncpg.PostgresError) as caught:
                async with owner.transaction():
                    await owner.execute(
                        "SELECT set_config('mc.installation_id',$1,true), "
                        "set_config('mc.application_id',$2,true), "
                        "set_config('mc.tenant_id',$3,true)",
                        str(db.installation_id),
                        db.application_id,
                        str(db.tenants["tenant-1"]),
                    )
                    await owner.execute(
                        f"UPDATE mission_control.{table} SET created_by_actor_ref = 'x'"
                    )
            assert caught.value.sqlstate == "23001", caught.value
    finally:
        await owner.close()
    other = db.scope("tenant-2")
    assert await store.claims_for(other, "run-1", "op-1", 1, 1) == ()
    assert await store.outcome(other, record.install_id) is None
    grants = await _owner(
        db,
        "SELECT table_name, privilege_type FROM information_schema.role_table_grants "
        "WHERE grantee = 'mission_control_runtime' AND table_name LIKE 'context_candidate%' "
        "ORDER BY 1, 2",
    )
    assert {(row["table_name"], row["privilege_type"]) for row in grants} == {
        ("context_candidate_install", "INSERT"),
        ("context_candidate_install", "SELECT"),
        ("context_candidate_install_outcome", "INSERT"),
        ("context_candidate_install_outcome", "SELECT"),
    }
    assert datetime.now(UTC) >= claim.claimed_at


async def test_a_retry_attempt_on_a_fresh_backend_is_a_new_receiver(db, pool) -> None:  # type: ignore[no-untyped-def]
    staging = InMemoryStaging()
    first_backend, fresh = MemoryWorkspace(), MemoryWorkspace()
    first = session(db, PostgresCandidateInstallStore(pool), staging)
    await first.collect(origin(), HookResult(staged_candidates=(candidate("attempt one"),)))
    assert len((await first.boundary(first_backend, "b")).installed) == 1

    retry = session(db, PostgresCandidateInstallStore(pool), staging, attempt=2)
    assert (await retry.boundary(fresh, "b")).records == () and fresh.writes == []
    await retry.collect(
        origin(attempt=2), HookResult(staged_candidates=(candidate("attempt two"),))
    )
    receipt = await retry.boundary(fresh, "b")
    assert [(item.state, item.recovered) for item in receipt.records] == [("installed", False)]
    assert fresh.files["/prepared/a.md"] == b"attempt two"
    rows = await _owner(
        db,
        "SELECT receiver_attempt FROM mission_control.context_candidate_install ORDER BY 1",
    )
    assert [row["receiver_attempt"] for row in rows] == [1, 2]
