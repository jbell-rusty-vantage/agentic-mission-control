"""Cross-provider control: the `codex` lane folds a settled turn's persisted frames into
`thread_item` cognition points (`adapters/codex/cognition_points.py`).

The frames are the ones a real `lane.turn` over the FIXTURE app-server persisted into the
in-memory frame store (never hand-built), so the fold is proven on exactly what the Native
Event Store holds: item ids from the provider keys, usage from `thread/tokenUsage/updated`,
roles, parents, facts without content. No Codex runs.
"""

from __future__ import annotations

from pathlib import Path

from mission_control.adapters.codex import cognition_points as points
from mission_control.adapters.codex.harness import CodexLocalHarness
from mission_control.application.execution.harness.points import (
    PointCollectingLane,
    TurnPointsRequest,
)
from mission_control.domain.execution.cognition_points import ThreadItemPoint
from mission_control.domain.execution.lane_turns import NativeRefs
from mission_control.domain.frames.contracts import FrameKind, ProviderFrame
from tests.fixtures.lane_turns import RecordingSignals
from tests.unit.codex.support import CodexStack, codex_stack
from tests.unit.codex.test_harness import BOUNDS


async def _settled_turn(tmp_path: Path, *scripts: str) -> tuple[CodexStack, str, str]:
    stack = codex_stack(tmp_path, *scripts)
    result = await stack.lanes.service.turn(
        stack.turn(segment=BOUNDS), RecordingSignals(stack.lanes.frames)
    )
    assert result.done and result.native.session_ref and result.native.turn_ref
    return stack, result.native.session_ref, result.native.turn_ref


def _request(stack: CodexStack, thread: str, turn: str, **changes: object) -> TurnPointsRequest:
    frames: tuple[ProviderFrame, ...] = tuple(stack.frames())
    values: dict[str, object] = {
        "operation": stack.operation,
        "lane_profile": "codex",
        "harness_execution_id": stack.heid,
        "generation": 1,
        "native": NativeRefs(session_ref=thread, turn_ref=turn),
        "turn_no": 1,
        "frames": frames,
        "facts": points.closing_facts_of(frames),
        "attempt_ref": "attempt-1",
    }
    values.update(changes)
    return TurnPointsRequest(**values)  # type: ignore[arg-type]


async def test_a_full_turn_folds_into_thread_item_points_keyed_by_item_id(tmp_path: Path) -> None:
    stack, thread, turn = await _settled_turn(tmp_path, "turn_full")
    assert isinstance(stack.harness, PointCollectingLane)
    observed = stack.harness.turn_points(_request(stack, thread, turn))

    kinds = [point.channel_facts["frame_kind"] for point in observed]
    assert kinds == ["turn_started", "tool_call_completed", "message", "turn_ended", "run_result"]
    assert all(isinstance(point.point, ThreadItemPoint) for point in observed)
    assert all(point.point.thread_ref == thread for point in observed)  # type: ignore[union-attr]
    # Item boundaries carry the native item id; turn boundaries a `<turn>:<ordinal>:<method>`.
    assert observed[1].point.item_ref == "item-cmd-1"  # type: ignore[union-attr]
    assert observed[2].point.item_ref == "item-msg-1"  # type: ignore[union-attr]
    assert observed[3].point.item_ref.startswith(f"{turn}:")  # type: ignore[union-attr]
    assert observed[3].point.item_ref.endswith(":turn/completed")  # type: ignore[union-attr]
    assert observed[4].point.item_ref.endswith(":turn/completed.result")  # type: ignore[union-attr]
    assert len({point.locator for point in observed}) == len(observed)
    assert [point.roles for point in observed] == [
        ("input",),
        ("intermediate",),
        ("intermediate",),
        ("intermediate",),
        ("leaf", "result"),
    ]
    locators = [point.locator for point in observed]
    assert [point.parent_locator for point in observed] == [None, *locators[:-1]]
    assert all(
        point.native_turn_ref == turn and point.attempt_ref == "attempt-1" for point in observed
    )
    assert all(point.harness_execution_id == stack.heid for point in observed)
    # The message boundary folds the two deltas before it; the result takes the trailing
    # frames (usage, status) after `turn/completed`.
    assert sum(":item/agentMessage/delta" in key for key in observed[2].frame_keys) == 2
    # The usage update is scripted before `turn/completed`, so it lands on the turn-end
    # point; the result point is the synthetic `turn/completed.result` frame alone (the
    # observation ends at the terminal frame; nothing trails it).
    assert any(":usage:" in key for key in observed[3].frame_keys)
    assert observed[4].frame_keys == (observed[4].frame_keys[0],)
    assert observed[4].frame_keys[0].endswith(":turn/completed.result")
    assert [point.message_count for point in observed] == [0, 0, 1, 1, 1]
    # Usage: the thread/tokenUsage/updated (`last`) lands on the point whose range holds it.
    usage = {name: amount for point in observed for name, amount in point.usage_delta.items()}
    assert usage == {"tokens.input": 120, "tokens.output": 40, "tokens.total": 160}
    assert sum(1 for point in observed if point.usage_delta) == 1
    # Facts: identity and shape, never content.
    tool = observed[1].channel_facts
    assert tool["tool_call_ref"] == "item-cmd-1" and tool["item_type"] == "commandExecution"
    assert tool["item_status"] == "completed" and tool["command_digest"].startswith("sha256:")
    assert "command" not in tool and "aggregatedOutput" not in tool
    message = observed[2].channel_facts
    assert message["text_digest"].startswith("sha256:") and message["text_bytes"] > 0
    assert "text" not in message
    assert observed[4].channel_facts["turn_status"] == "completed"
    assert observed[4].channel_facts["duration_ms"] == 10_000
    assert all(point.seedable for point in observed)
    assert observed[0].source == "input" and observed[4].source == "loop"


async def test_replacement_and_interrupted_roles_and_the_source_point(tmp_path: Path) -> None:
    stack, thread, turn = await _settled_turn(tmp_path, "turn_full")
    source = ThreadItemPoint(thread_ref="thr-0000", item_ref="item-prev")
    observed = points.turn_points(
        _request(
            stack,
            thread,
            turn,
            interrupted_turn_ref="turn-0000",
            source_point=source,
            terminal=False,
            interrupted=True,
        )
    )
    assert observed[0].roles == ("input", "replacement_start")
    assert observed[0].parent_point == source and observed[0].parent_locator is None
    assert observed[-1].roles == ("leaf", "interrupted")


async def test_the_generation_fold_and_the_turn_fold_agree_on_one_turn(tmp_path: Path) -> None:
    stack, thread, turn = await _settled_turn(tmp_path, "turn_full")
    frames = tuple(stack.frames())
    per_turn = points.turn_points(_request(stack, thread, turn, attempt_ref=None))
    whole = points.generation_points(
        frames, harness_execution_id=stack.heid, generation=1, facts=points.closing_facts_of(frames)
    )
    assert [point.locator for point in whole] == [point.locator for point in per_turn]
    assert [point.roles for point in whole] == [point.roles for point in per_turn]
    assert points.turn_order(frames) == (turn,)
    assert points.closing_facts_of(frames).native_status == "finished"


def test_item_identity_comes_from_the_key_when_the_body_was_excerpted(tmp_path: Path) -> None:
    del tmp_path
    assert points.key_parts("codex:thr-1:turn-1:item-9:item/completed") == (
        "thr-1",
        "turn-1",
        "item-9",
        "item/completed",
    )
    assert points.key_parts("codex:thr-1:turn-1::turn/completed") == (
        "thr-1",
        "turn-1",
        "",
        "turn/completed",
    )
    assert points.key_parts("claude:uuid:assistant") is None


def test_usage_skips_the_attributed_companion_frame(tmp_path: Path) -> None:
    """The lane writes a second USAGE frame per update (`:attributed:`); one model call is
    counted once."""

    del tmp_path
    from tests.unit.frames.test_frame_boundary_points import frame

    raw = frame(
        3,
        FrameKind.USAGE,
        lane_profile="codex",
        native_session_ref="thr-1",
        raw_kind=points.USAGE_RAW_KIND,
        provider_key="codex:thr-1:turn-1:usage:30",
        body_excerpt='{"tokenUsage":{"last":{"inputTokens":20,"outputTokens":10,"totalTokens":30}}}',
        body_bytes=len(
            '{"tokenUsage":{"last":{"inputTokens":20,"outputTokens":10,"totalTokens":30}}}'
        ),
    )
    companion = raw.model_copy(
        update={"provider_key": "codex:thr-1:turn-1:usage:30:attributed:sha256:abc"}
    )
    assert points.usage_of(raw) == {"tokens.input": 20, "tokens.output": 10, "tokens.total": 30}
    assert points.usage_of(companion) == {}


def test_the_harness_is_a_point_collecting_lane(tmp_path: Path) -> None:
    from tests.unit.codex.fixture_app_server import FixtureLauncher
    from tests.unit.codex.support import build_harness

    harness, *_rest = build_harness(tmp_path, FixtureLauncher())
    assert isinstance(harness, CodexLocalHarness) and isinstance(harness, PointCollectingLane)
