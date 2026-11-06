"""MO-16: the production worker composition holds the launch readiness gate over PostgreSQL.

`ProductionWorkerActivityCompositionFactory` builds the worker's `LaneTurnService` on a fresh
common-component PostgreSQL 17 (MISSION_CONTROL_TEST_ADMIN_DSN) and the local Temporal dev
server. Its gate is the PostgreSQL-backed `EnvironmentPreparationService`: an admitted
preparation is stored as a row under the worker's runtime role. Removing the composition line
fails this test; the lane turns that go through the gate are proven in
`test_environment_readiness_gate.py`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mission_control.application.environments import EnvironmentPreparationService
from mission_control.application.execution.harness.lane_turns import LaneExecutionIdentity
from mission_control.domain.execution.environment_preparation import ReadinessLevel
from mission_control.domain.execution.lanes import CursorExecutionBinding, PreparedSession
from tests.fixtures.lane_turns import DIGEST, cursor_operation
from tests.fixtures.mission_control_production_stack import open_postgres_production_stack
from tests.fixtures.rrm009_production_stack import SCOPE

pytestmark = pytest.mark.common_db


@pytest.mark.asyncio
async def test_the_production_worker_composes_the_gate_over_postgres(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with open_postgres_production_stack(root=tmp_path, monkeypatch=monkeypatch) as stack:
        assert stack.factory.operation is not None
        gate = stack.factory.operation.lane_turns.preparations
        assert isinstance(gate, EnvironmentPreparationService)
        operation = cursor_operation(request_scope=SCOPE)
        assert CursorExecutionBinding.carried_by(operation) is not None
        prepared = PreparedSession(
            lane_profile="cursor_local",
            harness_execution_id="hx",
            generation=1,
            workspace_ref="workspace_lease:lease-1",
            projection_digests={"rules_digest": DIGEST},
            materialization_ref=DIGEST,
        )
        identity = LaneExecutionIdentity.of(operation, "cursor_local", 1)
        record = await gate.admit_start(
            identity, CursorExecutionBinding.carried_by(operation), prepared
        )
        assert record.readiness is ReadinessLevel.PREPARED
        rows = await stack.owner_pool.fetch(
            "SELECT readiness, receipt_digest FROM mission_control.environment_preparation "
            "WHERE preparation_id = $1",
            record.preparation_id,
        )
        assert [(row["readiness"], row["receipt_digest"]) for row in rows] == [("prepared", DIGEST)]
