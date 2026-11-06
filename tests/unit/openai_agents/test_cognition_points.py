"""`codex_agents` cognition points folded from the frames a settled turn persisted.

The turn runs through the real `LaneTurnService` over the stateful Agents API fake, so the
points are folded from the exact frames the Native Event Store holds: one `thread_item`
point per completed item keyed `session#turn#item`, the terminal record as `leaf`+`result`
carrying the turn's usage.
"""

from __future__ import annotations

from pathlib import Path

from mission_control.adapters.openai_agents.cognition_points import (
    AGENTS_POINT_RULES,
    split_item_ref,
    step_ref_of,
)
from mission_control.adapters.openai_agents.time_travel import CodexAgentsTimeTravel
from mission_control.adapters.remote_session.cognition_points import generation_points
from mission_control.application.execution.harness.points import PointCollectingLane
from mission_control.domain.execution.cognition_points import ThreadItemPoint
from mission_control.domain.frames.contracts import FrameKind
from tests.fixtures.agents_lane import agents_stack
from tests.unit.remote_session.hosted_support import InMemoryFramesOf, settle_turn

PROFILE = "codex_agents"


async def test_a_settled_turn_folds_into_one_point_per_item_keyed_by_item_id(
    tmp_path: Path,
) -> None:
    stack = agents_stack(tmp_path)
    settled = await settle_turn(stack.harness, stack.operation, PROFILE)
    assert isinstance(stack.harness, PointCollectingLane)
    points = stack.harness.turn_points(settled.points_request())
    kinds = [point.channel_facts["frame_kind"] for point in points]
    # The three recovered command executions, the final answer, then the terminal record.
    assert kinds == [
        FrameKind.TOOL_CALL_COMPLETED.value,
        FrameKind.TOOL_CALL_COMPLETED.value,
        FrameKind.TOOL_CALL_COMPLETED.value,
        FrameKind.MESSAGE.value,
        FrameKind.RUN_RESULT.value,
    ]
    session_id, turn_id = settled.session_ref, settled.turn_ref
    items = {item["id"]: item for item in stack.api.item_store[turn_id]}
    for point in points[:-1]:
        ref = point.point
        assert isinstance(ref, ThreadItemPoint) and ref.thread_ref == session_id
        turn, item_id = split_item_ref(ref.item_ref)
        assert turn == turn_id and items[item_id]["type"] == point.channel_facts["item_type"]
        assert point.channel_facts["item_id"] == item_id
        assert point.native_turn_ref == turn_id
    last = points[-1]
    assert isinstance(last.point, ThreadItemPoint)
    assert last.point.locator == f"{session_id}#{turn_id}#done"
    assert last.channel_facts["turn_status"] == "completed"
    # Roles: no user-message item in this turn (the fake records none), so the first point
    # is an ordinary step; the close is the leaf and the result.
    assert points[0].roles == ("intermediate",) and points[0].source == "input"
    assert points[3].roles == ("intermediate",)
    assert points[3].channel_facts["item_phase"] == "final_answer"
    assert last.roles == ("leaf", "result")
    assert [point.ordinal for point in points] == [0, 1, 2, 3, 4]
    assert [point.parent_locator for point in points] == [
        None,
        *[point.locator for point in points[:-1]],
    ]
    assert [point.message_count for point in points] == [0, 0, 0, 1, 1]
    covered = [key for point in points for key in point.frame_keys]
    assert covered == [frame.provider_key for frame in settled.frames]
    # Usage: per turn on the terminal record, nothing per item.
    assert all(point.usage_delta == {} for point in points[:-1])
    assert last.usage_delta == {
        "tokens.input_tokens": 7,
        "tokens.output_tokens": 3,
        "tokens.total_tokens": 10,
    }


async def test_unknown_usage_leaves_the_result_without_a_delta(tmp_path: Path) -> None:
    stack = agents_stack(tmp_path, ("no_usage",))
    settled = await settle_turn(stack.harness, stack.operation, PROFILE)
    points = stack.harness.turn_points(settled.points_request())
    assert points[-1].usage_delta == {}
    assert points[-1].channel_facts["turn_status"] == "completed"


async def test_a_replacement_turn_names_its_source_and_replacement_start(
    tmp_path: Path,
) -> None:
    stack = agents_stack(tmp_path)
    settled = await settle_turn(stack.harness, stack.operation, PROFILE)
    previous = ThreadItemPoint(thread_ref="sess_prev", item_ref="turn_prev#done")
    points = stack.harness.turn_points(
        settled.points_request(interrupted_turn_ref="turn_old", source_point=previous)
    )
    assert points[0].roles == ("intermediate", "replacement_start")
    assert points[0].parent_point == previous


async def test_collect_points_re_derives_the_settlement_fold(tmp_path: Path) -> None:
    stack = agents_stack(tmp_path)
    settled = await settle_turn(stack.harness, stack.operation, PROFILE)
    expected = stack.harness.turn_points(settled.points_request(attempt_ref=None))
    lane = CodexAgentsTimeTravel(InMemoryFramesOf(settled.lanes.frames))
    derived = await lane.collect_points(
        namespace=settled.harness_execution_id,
        checkpointer_ref_digest="1",
        source_locator=None,
        result_locator=expected[-1].locator,
    )
    assert derived == expected
    assert generation_points(settled.frames, AGENTS_POINT_RULES) == expected


def test_step_refs_read_the_item_the_event_or_the_kernel_default() -> None:
    from tests.fixtures.provider_frames import provider_frame

    def keyed(ordinal: int, kind: FrameKind, key: str):  # type: ignore[no-untyped-def]
        return provider_frame(ordinal, kind).model_copy(update={"provider_key": key})

    assert step_ref_of(keyed(1, FrameKind.MESSAGE, "agents:turn_1:item~msg_9"), "turn_1") == "msg_9"
    assert step_ref_of(keyed(2, FrameKind.RUN_RESULT, "agents:turn_1:done"), "turn_1") == "done"
    assert step_ref_of(keyed(3, FrameKind.STATUS, "agents:turn_1:ev_4"), "turn_1") == "ev_4"
    assert (
        step_ref_of(keyed(4, FrameKind.STATUS, "sse-content:x:turn_1:abc"), "turn_1") == "4:status"
    )
