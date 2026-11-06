"""`frame_boundary_points`: the shared fold from one turn's persisted frames to cognition points
(cross-provider control, 2026-11-05)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from mission_control.application.execution.harness.points import (
    MAX_STEP_POINTS,
    default_step_ref,
    frame_boundary_points,
    frames_of_turn,
)
from mission_control.domain.execution.cognition_points import (
    SessionCursorPoint,
    ThreadItemPoint,
)
from mission_control.domain.frames.contracts import (
    FrameKind,
    FrameScope,
    LaneProfile,
    ProviderFrame,
    is_closing,
)
from tests.fixtures.provider_frames import FRAME_NOW, SCOPE

EXECUTION = uuid4()
RUN = uuid4()
ACTIVATION = uuid4()


def frame(
    ordinal: int, kind: FrameKind, *, turn: str | None = "turn-1", **updates: Any
) -> ProviderFrame:
    values: dict[str, Any] = {
        "frame_id": uuid4(),
        "scope": FrameScope.from_request_scope(SCOPE),
        "run_id": RUN,
        "activation_id": ACTIVATION,
        "attempt_no": 1,
        "harness_execution_id": EXECUTION,
        "generation": 1,
        "lane_profile": LaneProfile.CLAUDE_AGENT_SDK,
        "native_session_ref": "session-1",
        "native_turn_ref": turn,
        "provider_key": f"session-1::{turn}:{ordinal}:{kind.value}",
        "arrival_ordinal": ordinal,
        "observed_at": FRAME_NOW,
        "kind": kind,
        "closing": is_closing(kind),
        "body_digest": "sha256:" + "a" * 64,
        "body_bytes": 2,
        "body_media_type": "application/json",
        "body_excerpt": "{}",
        "raw_kind": f"raw.{kind.value}",
    }
    values.update(updates)
    return ProviderFrame.model_validate(values)


def a_turn() -> list[ProviderFrame]:
    return [
        frame(1, FrameKind.TURN_STARTED),
        frame(2, FrameKind.MESSAGE_DELTA),
        frame(3, FrameKind.TOOL_CALL_STARTED, tool_call_ref="call-1"),
        frame(4, FrameKind.HOOK_RESULT, tool_call_ref="call-1"),
        frame(5, FrameKind.TOOL_CALL_COMPLETED, tool_call_ref="call-1"),
        frame(6, FrameKind.USAGE),
        frame(7, FrameKind.MESSAGE),
        frame(8, FrameKind.TURN_ENDED),
        frame(9, FrameKind.USAGE),
    ]


def usage(frame: ProviderFrame) -> dict[str, int]:
    return {"tokens.total": 10 * frame.arrival_ordinal}


def test_one_point_per_step_boundary_with_chained_parents_and_frame_ranges() -> None:
    points = frame_boundary_points(
        a_turn(),
        session_ref="session-1",
        turn_ref="turn-1",
        harness_execution_id=str(EXECUTION),
        attempt_ref="attempt-1",
        usage_of=usage,
    )
    assert [point.channel_facts["frame_kind"] for point in points] == [
        "turn_started",
        "tool_call_completed",
        "message",
        "turn_ended",
    ]
    assert [point.roles for point in points] == [
        ("input",),
        ("intermediate",),
        ("intermediate",),
        ("leaf", "result"),
    ]
    assert [point.ordinal for point in points] == [0, 1, 2, 3]
    assert [point.source for point in points] == ["input", "loop", "loop", "loop"]
    locators = [point.locator for point in points]
    assert locators[0] == "session-1#turn-1#1:turn_started"
    assert [point.parent_locator for point in points] == [None, *locators[:-1]]
    # The tool point folds the delta, start and hook frames before it; the result point
    # takes the trailing usage frame after `turn_ended`.
    assert points[1].frame_keys == tuple(
        f"session-1::turn-1:{n}:{k}"
        for n, k in (
            (2, "message_delta"),
            (3, "tool_call_started"),
            (4, "hook_result"),
            (5, "tool_call_completed"),
        )
    )
    assert points[3].frame_keys[-1].endswith(":9:usage")
    assert points[2].usage_delta == {"tokens.total": 60}
    assert points[3].usage_delta == {"tokens.total": 90}
    assert [point.message_count for point in points] == [0, 0, 1, 1]
    assert points[1].channel_facts["tool_call_ref"] == "call-1"
    assert all(point.seedable for point in points)
    assert all(point.native_turn_ref == "turn-1" for point in points)
    assert all(isinstance(point.point, SessionCursorPoint) for point in points)


def test_native_point_identity_source_point_and_replacement_roles() -> None:
    source = ThreadItemPoint(thread_ref="thread-0", item_ref="item-0")
    points = frame_boundary_points(
        a_turn(),
        session_ref="thread-1",
        turn_ref="turn-1",
        point_for=lambda f: ThreadItemPoint(
            thread_ref="thread-1", item_ref=f"item-{f.arrival_ordinal}"
        ),
        source_point=source,
        interrupted_turn_ref="turn-0",
        terminal=False,
        seedable=lambda f: f.kind is FrameKind.TURN_ENDED,
    )
    assert points[0].parent_point == source
    assert points[0].roles == ("input", "replacement_start")
    assert points[-1].roles == ("leaf",)
    assert [point.locator for point in points] == [
        "thread-1#item-1",
        "thread-1#item-5",
        "thread-1#item-7",
        "thread-1#item-8",
    ]
    assert [point.seedable for point in points] == [False, False, False, True]


def test_other_turns_are_excluded_and_an_empty_turn_folds_nothing() -> None:
    frames = [*a_turn(), frame(10, FrameKind.TURN_STARTED, turn="turn-2")]
    assert len(frames_of_turn(frames, "turn-1")) == 9
    assert frame_boundary_points(frames, session_ref="s", turn_ref="turn-9") == ()


def test_a_turn_without_step_frames_still_names_a_result_point() -> None:
    frames = [frame(1, FrameKind.STATUS), frame(2, FrameKind.HEARTBEAT)]
    points = frame_boundary_points(frames, session_ref="s", turn_ref="turn-1")
    assert len(points) == 1
    assert points[0].roles == ("leaf", "result")
    assert points[0].frame_keys == tuple(f.provider_key for f in frames)


def test_long_turns_are_bounded_and_marked_incomplete() -> None:
    frames = [frame(n, FrameKind.MESSAGE) for n in range(1, MAX_STEP_POINTS + 10)]
    frames.append(frame(MAX_STEP_POINTS + 10, FrameKind.TURN_ENDED))
    points = frame_boundary_points(frames, session_ref="s", turn_ref="turn-1")
    assert len(points) == MAX_STEP_POINTS
    assert points[-1].channel_facts["points_status"] == "incomplete"
    assert points[-1].channel_facts["frame_kind"] == "turn_ended"
    assert default_step_ref(frames[-1]) == f"{MAX_STEP_POINTS + 10}:turn_ended"
