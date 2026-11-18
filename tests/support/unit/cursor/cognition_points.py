"""Builders, constants and fakes that other test files import.

Moved from tests/unit/cursor/test_cognition_points.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from mission_control.application.execution.cognition_points import InMemoryCognitionPointRepository
from mission_control.application.execution.harness.lane_turns import LaneExecutionIdentity
from mission_control.application.execution.operations.checkpoint_lineage import (
    CheckpointLineageService,
    InMemoryCheckpointLineageRepository,
)
from mission_control.domain.execution.cognition_points import (
    CognitionPointFilter,
    CognitionPointRecord,
)
from mission_control.domain.execution.contracts import (
    OperationAttemptIdentity,
    OperationExecutionRequest,
    OperationExecutionResult,
)
from mission_control.domain.execution.lane_turns import LaneTurnRequest
from tests.support.checkpoint_recovery import stage_recovery_unit
from tests.support.ids import SCOPE
from tests.support.lanes import ACTIVATION_UUID, RUN_UUID, RecordingSignals, lane_stack
from tests.support.unit.harness.lane_turn_points import _attempt

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


def unit_changes(operation: OperationExecutionRequest) -> dict[str, Any]:
    """The operation bound to one StageGraph unit of its run (the lineage needs a unit)."""

    unit = stage_recovery_unit(operation.identity.run_id, "implement", request_scope=SCOPE)
    return {
        "identity": OperationAttemptIdentity(
            run_id=operation.identity.run_id,
            operation_id=unit.semantic_operation_id,
            operation_attempt=unit.semantic_attempt,
        ),
        "runtime_unit": unit,
        "idempotency_key": f"points:{unit.unit_key}",
    }


async def settled_points(
    stack: Any, profile: str
) -> tuple[tuple[CognitionPointRecord, ...], LaneExecutionIdentity, Any]:
    points = InMemoryCognitionPointRepository()
    lineage = CheckpointLineageService(
        InMemoryCheckpointLineageRepository(points=points), clock=lambda: NOW
    )
    lanes = lane_stack(
        stack.harness,
        frames=getattr(stack, "frames", None),
        operation=stack.operation,
        lineage=lineage,
        points=points,
    )
    unit = stack.operation.runtime_unit
    assert unit is not None
    lanes.frames.register_run(
        SCOPE, stack.operation.identity.run_id, RUN_UUID, {unit.unit_key: ACTIVATION_UUID}
    )
    identity = LaneExecutionIdentity.of(stack.operation, profile, 1)
    request = LaneTurnRequest.model_validate(
        {"operation": stack.operation, "lane_profile": profile, "generation": 1}
    )
    result = await lanes.service.turn(
        request, RecordingSignals(lanes.frames, identity.harness_execution_id), attempt=_attempt()
    )
    assert result.done
    assert OperationExecutionResult.model_validate(result.operation_result).status == "completed"
    page = await points.list_points(
        SCOPE,
        stack.operation.identity.run_id,
        selection=CognitionPointFilter(),
        limit=100,
        cursor=None,
    )
    return page.entries, identity, lanes
