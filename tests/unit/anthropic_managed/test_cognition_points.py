"""`claude_managed` cognition points folded from the frames a settled turn persisted.

The turn runs through the real `LaneTurnService` over `FakeManagedAgentsApi` (HL-23 event
shapes), so the points are folded from the exact frames the Native Event Store holds: one
`session_cursor` point per step boundary keyed by the Managed event id, the `user.message`
as the `input` point, the close as `leaf`+`result`, usage per step from the model request
spans and the turn's cost on the result.
"""

from __future__ import annotations

from pathlib import Path

from mission_control.adapters.anthropic_managed.cognition_points import (
    MANAGED_POINT_RULES,
    step_ref_of,
)
from mission_control.adapters.anthropic_managed.time_travel import ClaudeManagedTimeTravel
from mission_control.adapters.remote_session.cognition_points import generation_points
from mission_control.application.execution.harness.points import PointCollectingLane
from mission_control.domain.execution.cognition_points import SessionCursorPoint
from mission_control.domain.frames.contracts import FrameKind
from tests.fixtures.managed_agents import MODEL_USAGE, TURN_LIST_COST
from tests.fixtures.managed_lane import PROFILE, managed_stack
from tests.unit.remote_session.hosted_support import InMemoryFramesOf, settle_turn


async def test_a_settled_turn_folds_into_one_point_per_step_keyed_by_event_id(
    tmp_path: Path,
) -> None:
    stack = managed_stack(tmp_path)
    settled = await settle_turn(stack.harness, stack.operation, PROFILE)
    assert isinstance(stack.harness, PointCollectingLane)
    points = stack.harness.turn_points(settled.points_request())
    kinds = [point.channel_facts["raw_kind"] for point in points]
    assert kinds == ["user.message", "agent.message", "session.status_idle"]
    # Identity: the session, the turn (its user.message id) and the step's own event id.
    session_id = settled.session_ref
    events = stack.api.events[session_id]
    for point in points:
        ref = point.point
        assert isinstance(ref, SessionCursorPoint)
        assert ref.session_ref == session_id and ref.turn_ref == settled.turn_ref
        event = next(item for item in events if item["id"] == ref.step_ref)
        assert event["type"] == point.channel_facts["raw_kind"]
        assert point.channel_facts["event_id"] == ref.step_ref
        assert point.native_turn_ref == settled.turn_ref
        assert point.harness_execution_id == settled.harness_execution_id
        assert point.attempt_ref == "activity-attempt:test"
    first, middle, last = points
    assert first.point.locator == f"{session_id}#{settled.turn_ref}#{settled.turn_ref}"
    # Roles and sources, Deep Agents shaped.
    assert first.roles == ("input",) and first.source == "input"
    assert middle.roles == ("intermediate",) and middle.source == "loop"
    assert last.roles == ("leaf", "result") and last.source == "loop"
    assert last.channel_facts["stop_reason"] == "end_turn"
    assert last.channel_facts["turn_status"] == "finished"
    assert last.channel_facts["frame_kind"] == FrameKind.RUN_RESULT.value
    # Lineage: parents chain by locator inside the turn; the first has none outside it.
    assert first.parent_locator is None and first.parent_point is None
    assert middle.parent_locator == first.locator and last.parent_locator == middle.locator
    assert [point.ordinal for point in points] == [0, 1, 2]
    # Messages: the user message and the agent message are the two `message` frames.
    assert [point.message_count for point in points] == [1, 2, 2]
    # Frame ranges cover every persisted frame once, in order.
    covered = [key for point in points for key in point.frame_keys]
    assert covered == [frame.provider_key for frame in settled.frames]
    # Usage: the model request's tokens land on the step that folded its end span; the
    # turn's settled cost (the lane's `mc_turn` summary) lands on the result.
    assert first.usage_delta == {} and middle.usage_delta == {}
    assert last.usage_delta == {
        **{f"tokens.{name}": amount for name, amount in MODEL_USAGE.items()},
        "cost.list_cost_minor_units": TURN_LIST_COST,
    }
    assert all(point.seedable for point in points)


async def test_a_replacement_turn_names_its_source_and_replacement_start(
    tmp_path: Path,
) -> None:
    stack = managed_stack(tmp_path)
    settled = await settle_turn(stack.harness, stack.operation, PROFILE)
    previous = SessionCursorPoint(session_ref="sesn_prev", turn_ref="sevt_prev")
    points = stack.harness.turn_points(
        settled.points_request(interrupted_turn_ref="sevt_old", source_point=previous)
    )
    assert points[0].roles == ("input", "replacement_start")
    assert points[0].parent_point == previous
    assert all(point.parent_point is None for point in points[1:])


async def test_without_native_refs_there_is_no_point(tmp_path: Path) -> None:
    stack = managed_stack(tmp_path)
    settled = await settle_turn(stack.harness, stack.operation, PROFILE)
    request = settled.points_request(
        native=settled.result.native.model_copy(update={"turn_ref": None})
    )
    assert stack.harness.turn_points(request) == ()


async def test_collect_points_re_derives_the_settlement_fold(tmp_path: Path) -> None:
    """The reconciler's re-derivation (`namespace` = harness execution, digest = generation)
    folds the same rows the settlement wrote."""

    stack = managed_stack(tmp_path)
    settled = await settle_turn(stack.harness, stack.operation, PROFILE)
    expected = stack.harness.turn_points(settled.points_request(attempt_ref=None))
    lane = ClaudeManagedTimeTravel(InMemoryFramesOf(settled.lanes.frames))
    derived = await lane.collect_points(
        namespace=settled.harness_execution_id,
        checkpointer_ref_digest="1",
        source_locator=None,
        result_locator=expected[-1].locator,
    )
    assert derived == expected
    # From a source inside the generation: only what follows it.
    tail = await lane.collect_points(
        namespace=settled.harness_execution_id,
        checkpointer_ref_digest="1",
        source_locator=expected[0].locator,
        result_locator=expected[-1].locator,
    )
    assert tail == expected[1:]
    assert generation_points(settled.frames, MANAGED_POINT_RULES) == expected


def test_step_refs_fall_back_to_the_kernel_default_for_content_keyed_frames(
    tmp_path: Path,
) -> None:
    from tests.fixtures.provider_frames import provider_frame

    del tmp_path

    def keyed(ordinal: int, kind: FrameKind, key: str, raw_kind: str):  # type: ignore[no-untyped-def]
        return provider_frame(ordinal, kind, raw_kind=raw_kind).model_copy(
            update={"provider_key": key}
        )

    frame = keyed(3, FrameKind.STATUS, "sse-content:status:turn-1:abcd", "status")
    assert step_ref_of(frame, "turn-1") == "3:status"
    final = keyed(4, FrameKind.RUN_RESULT, "managed:turn-1:final", "turn.final")
    assert step_ref_of(final, "turn-1") == "final"
    stepped = keyed(5, FrameKind.MESSAGE, "managed:turn-1:1700000000.sevt_0042", "agent.message")
    assert step_ref_of(stepped, "turn-1") == "sevt_0042"
