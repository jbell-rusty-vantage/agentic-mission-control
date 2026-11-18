"""Builders, constants and fakes that other test files import.

Moved from tests/unit/harness/test_lane_turn_points.py.
"""

from __future__ import annotations

from dataclasses import dataclass

from mission_control.application.execution.harness.points import (
    TurnPointsRequest,
    frame_boundary_points,
)
from mission_control.domain.execution.checkpoint_lineage import OperationActivityAttempt
from mission_control.domain.execution.cognition_points import (
    CognitionPointObservation,
    SessionCursorPoint,
)
from mission_control.domain.execution.contracts import (
    OperationAttemptIdentity,
    OperationExecutionRequest,
)
from tests.fixtures.checkpoint_recovery import stage_recovery_unit
from tests.fixtures.lane_turns import SCOPE, ScriptedSessionLane, cursor_operation


@dataclass
class PointLane(ScriptedSessionLane):
    """The scripted lane as a `PointCollectingLane`: the shared fold with bridge-offset
    step refs (the `cursor_local` shape). `fail_fold` makes the fold raise."""

    fail_fold: bool = False
    requests: list[TurnPointsRequest] | None = None

    def turn_points(self, request: TurnPointsRequest) -> tuple[CognitionPointObservation, ...]:
        if self.requests is None:
            self.requests = []
        self.requests.append(request)
        if self.fail_fold:
            raise RuntimeError("fold broke")
        return frame_boundary_points(
            request.frames,
            session_ref=request.native.session_ref or "agent-fake-1",
            turn_ref=request.native.turn_ref or "run-fake-1",
            harness_execution_id=request.harness_execution_id,
            attempt_ref=request.attempt_ref,
            point_for=lambda frame: SessionCursorPoint(
                session_ref=request.native.session_ref or "agent-fake-1",
                turn_ref=request.native.turn_ref or "run-fake-1",
                step_ref=frame.provider_key.rsplit(":", 1)[-1],
            ),
            terminal=request.terminal,
            source_point=request.source_point,
            interrupted_turn_ref=request.interrupted_turn_ref,
            interrupted_leaf=request.interrupted,
        )


def _attempt(number: int = 1) -> OperationActivityAttempt:
    return OperationActivityAttempt(
        workflow_id="mc/run/operation/1",
        workflow_run_id="run-1",
        activity_id="1",
        attempt=number,
        worker_identity="worker-a",
        task_queue="lane-turn-conformance",
    )


def _unit_operation() -> OperationExecutionRequest:
    """The Cursor operation bound to one StageGraph unit of its run (lineage needs a unit)."""

    base = cursor_operation()
    unit = stage_recovery_unit(base.identity.run_id, "implement", request_scope=SCOPE)
    return OperationExecutionRequest.model_validate(
        {
            **base.model_dump(mode="python"),
            "identity": OperationAttemptIdentity(
                run_id=base.identity.run_id,
                operation_id=unit.semantic_operation_id,
                operation_attempt=unit.semantic_attempt,
            ),
            "runtime_unit": unit,
            "idempotency_key": f"k1:{unit.unit_key}",
        }
    )
