"""W1 native write on a disposable PostgreSQL 17: the newest built release plus
candidate ``scripts/release_1130/0072_native_plan_decisions.sql``.

The plan-level decision store (``PostgresUseDecisionStore``) records a decision's exact report
subject, deciding invocation and KS decision digest; ``for_invocation`` answers exactly that
invocation's decisions; the row stays immutable; a native column set must be complete; an
ordinary (pre-0072 shaped) decision still records; preview leaves the handle table operation
constraint unchanged.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio

from mission_control.adapters.postgres.knowledge.use_decisions import PostgresUseDecisionStore
from mission_control.application.ports.knowledge import RecordedUseDecision
from tests.fixtures.mission_control_common_db import (
    CommonDatabase,
    common_database,
    migration_paths_with,
)
from tests.integration.postgres.runtime_common import owner_rows
from tests.integration.postgres.test_output_contracts_postgres import access_for
from tests.unit.outputs.scenario import digest_of

pytestmark = [pytest.mark.asyncio, pytest.mark.common_db]
AT = datetime(2026, 10, 29, 9, tzinfo=UTC)
MIGRATION = (
    Path(__file__).resolve().parents[3] / "scripts/release_1130/0072_native_plan_decisions.sql"
)


@pytest_asyncio.fixture
async def native_db() -> AsyncIterator[CommonDatabase]:
    async with common_database(paths=migration_paths_with(MIGRATION)) as database:
        yield database


def decision(name: str, *, invocation: str | None) -> RecordedUseDecision:
    native = invocation is not None
    return RecordedUseDecision(
        handle=f"kh:aiengineer-postgres/decision/{name}@use-decision.v1",
        binding_id="aiengineer-postgres",
        tenant_id="00000000-0000-0000-0000-000000000000",
        use_decision_id=name,
        bound_effect_digest=digest_of("bound-" + name),
        processed_epoch=4,
        plan={"schemaVersion": "knowledge-ingestion-intent.v1", "intentId": f"mc-{name}"},
        normalized_values_digest=digest_of("values"),
        use="engineering_reference.model_facts",
        audience="official",
        subject_ref=("kh:aiengineer-postgres/report/r@research-report.v2#" + digest_of("r"))
        if native
        else None,
        invocation_ref=invocation,
        decision_digest=digest_of("decision-" + name) if native else None,
    )


async def test_native_plan_decisions_by_invocation_are_immutable_and_complete(
    native_db: CommonDatabase,
) -> None:
    pool = await native_db.pool()
    try:
        access = access_for(native_db)
        tenant = access.origin.tenant_id
        store = PostgresUseDecisionStore(pool)

        def mine(name: str, invocation: str | None) -> RecordedUseDecision:
            from dataclasses import replace

            return replace(decision(name, invocation=invocation), tenant_id=tenant)

        first = await store.record(
            access.scope, mine("ud-a", "mc-inv:one"), actor_ref="test", at=AT
        )
        assert (
            await store.record(access.scope, mine("ud-a", "mc-inv:one"), actor_ref="test", at=AT)
            == first
        )  # a replay is the same row
        await store.record(access.scope, mine("ud-b", "mc-inv:two"), actor_ref="test", at=AT)
        ordinary = await store.record(access.scope, mine("ud-c", None), actor_ref="test", at=AT)
        assert ordinary.invocation_ref is None and ordinary.decision_digest is None
        found = await store.for_invocation(access.scope, "mc-inv:one")
        assert [item.use_decision_id for item in found] == ["ud-a"]
        assert found[0] == first and found[0].subject_ref is not None
        assert await store.for_invocation(access.scope, "mc-inv:none") == ()
        async with pool.acquire() as connection:
            with pytest.raises(asyncpg.PostgresError):
                await connection.execute(
                    "UPDATE mission_control.knowledge_use_decision SET invocation_ref = 'x'"
                )
        # A native row names all three of its native columns (never a partial binding).
        with pytest.raises(asyncpg.PostgresError):
            await owner_rows(
                native_db,
                "INSERT INTO mission_control.knowledge_use_decision (installation_id, "
                "application_id, tenant_id, handle, binding_id, use_decision_id, decision_ref, "
                "bound_effect_digest, processed_epoch, plan, recorded_at, created_by_actor_ref, "
                "invocation_ref) SELECT installation_id, application_id, tenant_id, 'h-partial', "
                "binding_id, 'ud-p', jsonb_build_object('kind','use_decision','id','ud-p'), "
                "bound_effect_digest, 1, plan, recorded_at, 'test', 'mc-inv:p' FROM "
                "mission_control.knowledge_use_decision LIMIT 1",
            )
        checks = await owner_rows(
            native_db,
            "SELECT pg_get_constraintdef(oid) AS def FROM pg_constraint "
            "WHERE conname = 'knowledge_operation_handle_operation_check'",
        )
        # The preview answers in the call and records no handle: the check is unchanged.
        assert "knowledge.plan_preview" not in checks[0]["def"]
    finally:
        await pool.close()
