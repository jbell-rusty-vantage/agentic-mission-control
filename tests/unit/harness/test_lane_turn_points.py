"""K1 (cross-provider control, 2026-11-05): a Session Lane's cognition points at settlement.

A `PointCollectingLane` folds its persisted frames into points; `LaneTurnService._settle`
builds the `TurnPointsRequest`s (every native turn of the generation, chained), hands them to
`settle_lane_session(points=...)`, and the boundary writes them in the settlement transaction
(`written_by: adapter`). Cancelled turns write their points too. A fold that fails costs the
points, never the settlement. The pure fold (`fold_generation_points`) chains an interrupted
turn and its replacement (`interrupted`, `replacement_start`) from the dispatch journal.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest

from mission_control.application.execution.cognition_points import (
    InMemoryCognitionPointRepository,
)
from mission_control.application.execution.harness.lane_turns import LaneExecutionIdentity
from mission_control.application.execution.harness.points import (
    TurnPointsRequest,
    fold_generation_points,
    frame_boundary_points,
    generation_turns,
)
from mission_control.application.execution.operations.checkpoint_lineage import (
    CheckpointLineageService,
    InMemoryCheckpointLineageRepository,
)
from mission_control.domain.execution.checkpoint_lineage import OperationActivityAttempt
from mission_control.domain.execution.cognition_points import (
    CognitionPointFilter,
    CognitionPointObservation,
    SessionCursorPoint,
)
from mission_control.domain.execution.contracts import (
    OperationAttemptIdentity,
    OperationExecutionRequest,
    OperationExecutionResult,
)
from mission_control.domain.execution.lane_turns import (
    ClosingFacts,
    LaneCancelRequest,
    LaneTurnRequest,
)
from mission_control.domain.frames.contracts import FrameKind, LaneProfile
from tests.fixtures.checkpoint_recovery import stage_recovery_unit
from tests.fixtures.lane_turns import (
    ACTIVATION_UUID,
    RUN_UUID,
    SCOPE,
    RecordingSignals,
    ScriptedSessionLane,
    cursor_operation,
    lane_stack,
    scripted_frames,
)
from tests.fixtures.provider_frames import provider_frame

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


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


def _stack(lane: Any, operation: OperationExecutionRequest) -> Any:
    points = InMemoryCognitionPointRepository()
    lineage = CheckpointLineageService(
        InMemoryCheckpointLineageRepository(points=points), clock=lambda: NOW
    )
    stack = lane_stack(lane, operation=operation, lineage=lineage, points=points)
    unit = operation.runtime_unit
    assert unit is not None
    stack.frames.register_run(
        SCOPE, operation.identity.run_id, RUN_UUID, {unit.unit_key: ACTIVATION_UUID}
    )
    return stack, points


def _turn(operation: OperationExecutionRequest, **changes: object) -> LaneTurnRequest:
    return LaneTurnRequest.model_validate(
        {"operation": operation, "lane_profile": "cursor_local", "generation": 1, **changes}
    )


async def test_a_settled_turn_writes_one_point_per_step_boundary_as_adapter() -> None:
    operation = _unit_operation()
    lane = PointLane(frames=scripted_frames(tool_calls=2))
    stack, points = _stack(lane, operation)
    identity = LaneExecutionIdentity.of(operation, "cursor_local", 1)
    signals = RecordingSignals(stack.frames, identity.harness_execution_id)

    result = await stack.service.turn(_turn(operation), signals, attempt=_attempt())

    assert result.done
    assert OperationExecutionResult.model_validate(result.operation_result).status == "completed"
    page = await points.list_points(
        SCOPE, operation.identity.run_id, selection=CognitionPointFilter(), limit=50, cursor=None
    )
    rows = page.entries
    # system(init) is STATUS, the two tool completions and the turn end are step boundaries,
    # the result frame the result: 4 points, keyed by the lane's step ref (the offset).
    assert [row.coordinate.point.kind for row in rows] == ["session_cursor"] * 4
    locators = [row.coordinate.locator for row in rows]
    assert locators == [
        "agent-fake-1#run-fake-1#2",
        "agent-fake-1#run-fake-1#4",
        "agent-fake-1#run-fake-1#5",
        "agent-fake-1#run-fake-1#6",
    ]
    assert {row.written_by for row in rows} == {"adapter"}
    assert rows[0].roles == ("intermediate",) and rows[-1].roles == ("leaf", "result")
    assert [row.parent_point_id for row in rows[1:]] == [row.point_id for row in rows[:-1]]
    assert all(row.lane_profile == "cursor_local" for row in rows)
    assert all(
        row.coordinate.harness_execution_id == str(identity.harness_execution_id) for row in rows
    )
    # Frame ranges resolve from provider keys in the Postgres index (the in-memory index
    # resolves only a seeded `frame_ordinals` map): proven by the integration suites.
    assert rows[-1].attempt is not None and rows[-1].attempt.activity_attempt == 1
    assert rows[-1].budget_snapshot is not None, "the result point carries the settlement's usage"
    # The lane saw one request for the generation's one turn, terminal, with the attempt ref.
    assert lane.requests is not None and len(lane.requests) == 1
    request = lane.requests[0]
    assert request.terminal and request.native.turn_ref == "run-fake-1" and request.turn_no == 1
    assert request.attempt_ref is not None and request.attempt_ref.startswith("activity-attempt:")
    assert request.operation is operation or request.operation == operation


async def test_a_points_fold_failure_never_fails_the_settlement() -> None:
    operation = _unit_operation()
    lane = PointLane(frames=scripted_frames(), fail_fold=True)
    stack, points = _stack(lane, operation)
    identity = LaneExecutionIdentity.of(operation, "cursor_local", 1)

    result = await stack.service.turn(
        _turn(operation),
        RecordingSignals(stack.frames, identity.harness_execution_id),
        attempt=_attempt(),
    )

    assert result.done
    assert OperationExecutionResult.model_validate(result.operation_result).status == "completed"
    assert points.rows == {}


async def test_without_a_lineage_the_settlement_writes_no_points_and_still_settles() -> None:
    operation = _unit_operation()
    lane = PointLane(frames=scripted_frames())
    stack = lane_stack(lane, operation=operation)
    unit = operation.runtime_unit
    assert unit is not None
    stack.frames.register_run(
        SCOPE, operation.identity.run_id, RUN_UUID, {unit.unit_key: ACTIVATION_UUID}
    )
    identity = LaneExecutionIdentity.of(operation, "cursor_local", 1)
    result = await stack.service.turn(
        _turn(operation),
        RecordingSignals(stack.frames, identity.harness_execution_id),
        attempt=_attempt(),
    )
    assert result.done and lane.requests is not None and len(lane.requests) == 1


async def test_a_cancelled_turn_writes_its_points_too() -> None:
    import asyncio

    operation = _unit_operation()
    lane = PointLane(frames=scripted_frames(), hold_after=1)
    stack, points = _stack(lane, operation)
    identity = LaneExecutionIdentity.of(operation, "cursor_local", 1)
    task = asyncio.create_task(
        stack.service.turn(
            _turn(operation),
            RecordingSignals(stack.frames, identity.harness_execution_id),
            attempt=_attempt(),
        )
    )
    await asyncio.wait_for(lane.held.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    payload = {"operation": operation, "lane_profile": "cursor_local", "generation": 1}
    cancelled = await stack.service.cancel(
        LaneCancelRequest.model_validate(payload), attempt=_attempt(2)
    )
    assert cancelled.settled
    assert OperationExecutionResult.model_validate(cancelled.operation_result).status == "cancelled"
    page = await points.list_points(
        SCOPE, operation.identity.run_id, selection=CognitionPointFilter(), limit=50, cursor=None
    )
    # Two frames were persisted before the hold (init, the first running tool call): no step
    # boundary among them, so the generation's last frame is its one (result) point.
    assert len(page.entries) == 1
    (row,) = page.entries
    assert row.roles == ("leaf", "result") and row.written_by == "adapter"


# --- the pure fold: several native turns of one generation ---------------------------------


def _frames(turn: str, start: int, *kinds: FrameKind) -> list[Any]:
    return [
        provider_frame(
            start + index,
            kind,
            {"n": start + index},
            lane=LaneProfile.CURSOR_LOCAL,
            session="agent-1",
            turn=turn,
        )
        for index, kind in enumerate(kinds)
    ]


def _collect(request: TurnPointsRequest) -> tuple[CognitionPointObservation, ...]:
    assert request.native.turn_ref is not None
    return frame_boundary_points(
        request.frames,
        session_ref="agent-1",
        turn_ref=request.native.turn_ref,
        terminal=request.terminal,
        source_point=request.source_point,
        interrupted_turn_ref=request.interrupted_turn_ref,
        interrupted_leaf=request.interrupted,
    )


def test_generation_turns_assigns_lifecycle_frames_to_the_turn_in_progress() -> None:
    frames = [
        provider_frame(1, FrameKind.SESSION_INIT, lane=LaneProfile.CURSOR_LOCAL, turn=None),
        *_frames("run-a", 2, FrameKind.TURN_STARTED, FrameKind.TOOL_CALL_COMPLETED),
        provider_frame(4, FrameKind.HOOK_RESULT, lane=LaneProfile.CURSOR_LOCAL, turn=None),
        *_frames("run-b", 5, FrameKind.TURN_STARTED, FrameKind.RUN_RESULT),
    ]
    turns = generation_turns(frames)
    assert [ref for ref, _ in turns] == ["run-a", "run-b"]
    assert [frame.arrival_ordinal for frame in turns[0][1]] == [1, 2, 3, 4]
    assert [frame.arrival_ordinal for frame in turns[1][1]] == [5, 6]


def test_fold_chains_an_interrupted_turn_and_its_replacement() -> None:
    frames = [
        *_frames(
            "run-a", 1, FrameKind.TURN_STARTED, FrameKind.TOOL_CALL_COMPLETED, FrameKind.ERROR
        ),
        *_frames("run-b", 4, FrameKind.TURN_STARTED, FrameKind.MESSAGE, FrameKind.RUN_RESULT),
    ]
    source = SessionCursorPoint(session_ref="agent-0", turn_ref="run-0", step_ref="9")
    observed = fold_generation_points(
        frames,
        collect=_collect,
        lane_profile="cursor_local",
        harness_execution_id="heid",
        generation=1,
        session_ref="agent-1",
        facts=ClosingFacts(native_status="finished"),
        last_turn_no=2,
        last_turn_ref="run-b",
        replaced={"run-b": "run-a"},
        source_point=source,
    )
    a_points = [point for point in observed if point.native_turn_ref == "run-a"]
    b_points = [point for point in observed if point.native_turn_ref == "run-b"]
    assert len(a_points) == 3 and len(b_points) == 3
    # The first turn continues from the source point outside the generation; it is not the
    # result (its leaf is the interrupted one); the replacement starts from that leaf.
    assert a_points[0].parent_point == source and a_points[0].roles == ("input",)
    assert a_points[-1].roles == ("leaf", "interrupted") and a_points[-1].source == "interrupt"
    assert b_points[0].parent_locator == a_points[-1].locator and b_points[0].parent_point is None
    assert b_points[0].roles == ("input", "replacement_start")
    assert b_points[-1].roles == ("leaf", "result")
    assert [point.ordinal for point in b_points] == [0, 1, 2]


def test_fold_drops_a_locator_observed_twice_and_keeps_the_first() -> None:
    frames = [
        *_frames("run-a", 1, FrameKind.TURN_STARTED, FrameKind.RUN_RESULT),
        *_frames("run-b", 3, FrameKind.TURN_STARTED, FrameKind.RUN_RESULT),
    ]

    def same_locators(request: TurnPointsRequest) -> tuple[CognitionPointObservation, ...]:
        # A lane that keys every turn's steps the same way (an adapter defect).
        assert request.native.turn_ref is not None
        return frame_boundary_points(
            request.frames,
            session_ref="agent-1",
            turn_ref=request.native.turn_ref,
            terminal=request.terminal,
            point_for=lambda frame: SessionCursorPoint(
                session_ref="agent-1", turn_ref="same", step_ref=str(frame.kind.value)
            ),
        )

    observed = fold_generation_points(
        frames,
        collect=same_locators,
        lane_profile="cursor_local",
        harness_execution_id="heid",
        generation=1,
        session_ref="agent-1",
        facts=ClosingFacts(native_status="finished"),
        last_turn_ref="run-b",
    )
    assert [point.locator for point in observed] == [
        "agent-1#same#turn_started",
        "agent-1#same#run_result",
    ]


# --- K2: the derived unit's first session continues from its fork seed head ----------------


@dataclass
class SeedAwareLane(PointLane):
    """The point lane that records the seed head `prepare` and `start` were handed."""

    seeds: list[Any] | None = None

    async def prepare(self, request: Any) -> Any:
        if self.seeds is None:
            self.seeds = []
        self.seeds.append(("prepare", request.seed))
        return await super().prepare(request)

    async def start(self, request: Any) -> Any:
        assert self.seeds is not None
        self.seeds.append(("start", request.seed))
        return await super().start(request)


async def test_a_generation_one_unit_with_a_fork_seed_point_is_prepared_with_its_seed_head() -> (
    None
):
    from mission_control.domain.execution.cognition_points import (
        CognitionCoordinate,
        CognitionPointRecord,
        WorkspaceSnapshotPoint,
        location_facts,
        point_id_for,
    )
    from mission_control.domain.execution.lanes import LaneSeedHead

    operation = _unit_operation()
    lane = SeedAwareLane(frames=scripted_frames())
    stack, points = _stack(lane, operation)
    unit = operation.runtime_unit
    assert unit is not None
    head = LaneSeedHead(
        source_run_id="run-source",
        source_unit_key=unit.unit_key,
        source_execution_generation=1,
        point_kind="session_cursor",
        point_locator="agent-0#run-0#11",
        point={
            "kind": "session_cursor",
            "session_ref": "agent-0",
            "turn_ref": "run-0",
            "step_ref": "11",
        },
        restore_level="R2",
        history="reconstructed",
        native_artifacts={
            "snapshot_ref": "cursor-snapshot:payload://7",
            "transcript_ref": "payload://9",
        },
        message="continue",
        fork_request_id="fork-1",
    )
    seed_point = WorkspaceSnapshotPoint(
        snapshot_ref="cursor-snapshot:payload://7", session_ref="agent-0", turn_ref="run-0"
    )
    await points.record(
        SCOPE,
        [
            CognitionPointRecord(
                point_id=point_id_for(
                    operation.identity.run_id, unit.unit_key, 1, seed_point.kind, seed_point.locator
                ),
                coordinate=CognitionCoordinate(
                    run_id=operation.identity.run_id,
                    unit_key=unit.unit_key,
                    execution_generation=1,
                    point=seed_point,
                ),
                lane_profile="cursor_local",
                location=location_facts(unit),
                source="fork",
                roles=("fork_seed",),
                channel_facts={"seed_head": head.model_dump(mode="json")},
                seedable=True,
                written_by="fork_seed",
                recorded_at=NOW,
                restore_level="R2",
                history="reconstructed",
            )
        ],
        frame_keys={},
        turn_refs={},
    )
    identity = LaneExecutionIdentity.of(operation, "cursor_local", 1)

    result = await stack.service.turn(
        _turn(operation),
        RecordingSignals(stack.frames, identity.harness_execution_id),
        attempt=_attempt(),
    )

    assert result.done and lane.seeds is not None
    assert [(call, seed is not None) for call, seed in lane.seeds] == [
        ("prepare", True),
        ("start", True),
    ]
    assert lane.seeds[0][1] == head and lane.seeds[1][1] == head
    # The first point of the seeded generation names the seed point as its parent.
    page = await points.list_points(
        SCOPE,
        operation.identity.run_id,
        selection=CognitionPointFilter(kind="session_cursor"),
        limit=50,
        cursor=None,
    )
    assert page.entries and page.entries[0].parent_locator == seed_point.locator


async def test_an_ordinary_attempt_is_prepared_without_a_seed() -> None:
    operation = _unit_operation()
    lane = SeedAwareLane(frames=scripted_frames())
    stack, _points = _stack(lane, operation)
    identity = LaneExecutionIdentity.of(operation, "cursor_local", 1)
    result = await stack.service.turn(
        _turn(operation),
        RecordingSignals(stack.frames, identity.harness_execution_id),
        attempt=_attempt(),
    )
    assert result.done and lane.seeds == [("prepare", None), ("start", None)]
