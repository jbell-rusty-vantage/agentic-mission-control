"""Budget journal durability on the existing scoped execution row, with real runtime grants."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from mission_control.adapters.postgres.frames.repository import PostgresFrameRepository
from mission_control.adapters.postgres.lanes.execution_state import PostgresLaneExecutionStateStore
from mission_control.application.execution.harness.dispatch import StaleSessionOwner
from mission_control.application.execution.harness.state import LaneExecutionUpdate
from mission_control.domain.execution.budget_controls import BudgetControlRecord
from mission_control.domain.frames.contracts import LaneProfile
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.integration.postgres.frames_common import admit_unit_attempt
from tests.integration.postgres.runtime_common import common_db  # noqa: F401

pytestmark = pytest.mark.common_db
DIGEST = "sha256:" + "a" * 64


async def test_budget_intent_survives_new_store_and_is_owner_fenced_and_scoped(
    common_db: CommonDatabase,  # noqa: F811
):
    pool = await common_db.pool("mission_control_runtime")
    try:
        admitted = await admit_unit_attempt(pool, common_db)
        start = admitted.start(lane=LaneProfile.CURSOR_LOCAL, native_session_ref="session-1")
        await PostgresFrameRepository(pool).open_execution(start)
        states = PostgresLaneExecutionStateStore(pool)
        scope, heid = start.request_scope, start.harness_execution_id
        await states.record(scope, heid, LaneExecutionUpdate(native_session_ref="session-1"))
        now = datetime.now(UTC)
        owner = await states.claim_owner(
            scope, heid, owner_ref="worker-a", generation=1, now=now, lease=timedelta(seconds=10)
        )
        record = BudgetControlRecord(
            key="8:operatorhold-1",
            command_id="hold-1",
            command_issuer="operator",
            command_digest=DIGEST,
            command_sequence=1,
            operation_digest=DIGEST,
            request_scope=scope,
            run_id="run-1",
            harness_execution_id=heid,
            native_session_ref="session-1",
            generation=1,
            binding_digest=DIGEST,
            configuration_digest=DIGEST,
            action="hold",
            ceiling_minor_units=90,
            recorded_at=now,
        )
        duplicates = await asyncio.gather(
            states.enqueue_budget_control(record), states.enqueue_budget_control(record)
        )
        assert duplicates == [record, record]
        intended = record.model_copy(
            update={
                "phase": "intended",
                "revision": 2,
                "target_cap_minor_units": 4,
                "prior_cap_minor_units": 90,
            }
        )
        await states.update_budget_control(intended, expected_revision=1, owner=owner)
        restarted = PostgresLaneExecutionStateStore(pool)
        state = await restarted.load(scope, heid)
        assert (
            state.budget_controls[record.key] == intended
            and state.native_session_ref == "session-1"
        )
        assert await restarted.load(common_db.scope("tenant-2"), heid) is None
        successor = await restarted.claim_owner(
            scope,
            heid,
            owner_ref="worker-b",
            generation=1,
            now=now + timedelta(minutes=1),
            lease=timedelta(seconds=30),
        )
        changed = intended.model_copy(update={"phase": "in_doubt", "revision": 3})
        with pytest.raises(StaleSessionOwner):
            await restarted.update_budget_control(changed, expected_revision=2, owner=owner)
        await restarted.update_budget_control(changed, expected_revision=2, owner=successor)
        assert (await restarted.load(scope, heid)).budget_controls[record.key].phase == "in_doubt"
        with pytest.raises(ValueError, match="idempotency"):
            await restarted.enqueue_budget_control(
                record.model_copy(update={"ceiling_minor_units": 100})
            )
    finally:
        await pool.close()
