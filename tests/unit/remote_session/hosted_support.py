"""Shared helpers of the hosted lanes' cognition-point and time-travel tests.

A settled turn is driven through the real `LaneTurnService` over the lane's FIXTURE API
(no provider is called), so the frames folded are exactly the ones the Native Event Store
holds; the records built here are what the settlement would have written for a point.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from mission_control.adapters.remote_session.time_travel import FramesOfExecution
from mission_control.application.execution.harness.lane_turns import (
    LaneExecutionIdentity,
    harness_scope,
)
from mission_control.application.execution.harness.points import TurnPointsRequest
from mission_control.application.frames.sink import InMemoryFrameStore
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.execution.cognition_points import (
    CognitionCoordinate,
    CognitionPointObservation,
    CognitionPointRecord,
    UnitLocationFacts,
    point_id_for,
)
from mission_control.domain.execution.contracts import OperationExecutionRequest
from mission_control.domain.execution.lane_turns import (
    ClosingFacts,
    LaneSegmentBounds,
    LaneTurnRequest,
    LaneTurnResult,
)
from mission_control.domain.frames.contracts import ProviderFrame
from tests.fixtures.lane_turns import SCOPE, LaneStack, RecordingSignals, lane_stack

UNIT_KEY = "bl-unit-v1:" + "ab" * 32
BOUNDS = LaneSegmentBounds(
    max_frames=500,
    max_duration_s=20,
    start_to_close_s=40,
    heartbeat_timeout_s=3,
    status_poll_limit=2,
    status_poll_interval_s=1,
    busy_wait_s=10,
)


class InMemoryFramesOf(FramesOfExecution):
    """`FramesOfExecution` over the in-memory frame store of a lane stack."""

    def __init__(self, store: InMemoryFrameStore, request_scope: str = SCOPE) -> None:
        self._store = store
        self._scope = request_scope

    async def frames_of(
        self, harness_execution_id: str, generation: int
    ) -> tuple[ProviderFrame, ...]:
        from uuid import UUID

        return await self._store.frames_for_execution(
            self._scope, UUID(harness_execution_id), generation, limit=10_000
        )


@dataclass
class SettledTurn:
    lanes: LaneStack
    result: LaneTurnResult
    frames: tuple[ProviderFrame, ...]
    identity: LaneExecutionIdentity
    operation: OperationExecutionRequest

    @property
    def harness_execution_id(self) -> str:
        return str(self.identity.harness_execution_id)

    @property
    def session_ref(self) -> str:
        assert self.result.native.session_ref is not None
        return self.result.native.session_ref

    @property
    def turn_ref(self) -> str:
        assert self.result.native.turn_ref is not None
        return self.result.native.turn_ref

    @property
    def facts(self) -> ClosingFacts:
        assert self.result.closing_facts is not None
        return self.result.closing_facts

    def points_request(self, **changes: Any) -> TurnPointsRequest:
        return TurnPointsRequest(
            **{
                "operation": self.operation,
                "lane_profile": self.identity.lane_profile,
                "harness_execution_id": self.harness_execution_id,
                "generation": 1,
                "native": self.result.native,
                "turn_no": 1,
                "frames": self.frames,
                "facts": self.facts,
                "attempt_ref": "activity-attempt:test",
                **changes,
            }
        )


async def settle_turn(
    harness: Any, operation: OperationExecutionRequest, profile: str
) -> SettledTurn:
    """One full turn through the real `LaneTurnService` over the fixture API."""

    lanes = lane_stack(harness, operation=operation)
    identity = LaneExecutionIdentity.of(operation, profile, 1)  # type: ignore[arg-type]
    request = LaneTurnRequest.model_validate(
        {"operation": operation, "lane_profile": profile, "generation": 1, "segment": BOUNDS}
    )
    result = await lanes.service.turn(
        request, RecordingSignals(lanes.frames, identity.harness_execution_id)
    )
    assert result.done, result
    frames = await lanes.frames.frames_for_execution(
        identity.request_scope, identity.harness_execution_id, 1, limit=1_000
    )
    return SettledTurn(lanes, result, frames, identity, operation)


def harness_fields(operation: OperationExecutionRequest, profile: str, key: str) -> dict[str, Any]:
    identity = LaneExecutionIdentity.of(operation, profile, 1)  # type: ignore[arg-type]
    binding = ProviderExecutionBinding.carried_by(operation)
    assert binding is not None
    return {
        "scope": harness_scope(identity.request_scope),
        "lane_profile": profile,
        "harness_execution_id": str(identity.harness_execution_id),
        "binding_digest": binding.binding_digest,
        "idempotency_key": f"{identity.harness_execution_id}:1:{key}",
        "generation": 1,
    }


def record_for(
    point: CognitionPointObservation,
    *,
    run_id: str,
    lane_profile: str,
    harness_execution_id: str,
    unit_key: str = UNIT_KEY,
) -> CognitionPointRecord:
    """The persisted row the settlement would have written for one observed point."""

    coordinate = CognitionCoordinate(
        run_id=run_id,
        unit_key=unit_key,
        execution_generation=1,
        harness_execution_id=harness_execution_id,
        turn_no=1,
        point=point.point,
    )
    return CognitionPointRecord(
        point_id=point_id_for(run_id, unit_key, 1, coordinate.kind, coordinate.locator),
        coordinate=coordinate,
        lane_profile=lane_profile,  # type: ignore[arg-type]
        location=UnitLocationFacts(family="stage_graph", node_key="s1", iteration=0, cycle=0),
        parent_locator=point.parent_locator,
        ordinal=point.ordinal,
        source=point.source,
        roles=point.roles,
        channel_facts=point.channel_facts,
        usage_delta=point.usage_delta,
        written_by="adapter",
        recorded_at=datetime.now(UTC),
    )


__all__ = [
    "BOUNDS",
    "UNIT_KEY",
    "InMemoryFramesOf",
    "SettledTurn",
    "harness_fields",
    "record_for",
    "settle_turn",
]
