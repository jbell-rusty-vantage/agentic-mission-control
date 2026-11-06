"""Cross-provider control: the `claude_agent_sdk` lane folds a settled turn's persisted frames
into `session_cursor` cognition points (`adapters/claude/cognition_points.py`).

The frames are the ones a real `lane.turn` over the FIXTURE SDK client persisted into the
in-memory frame store (never hand-built): step refs from the provider keys, usage from the
`assistant` messages, hook boundaries, roles, parents, facts without content. No Claude
Code runs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mission_control.adapters.claude import cognition_points as points
from mission_control.adapters.claude.harness import turn_reference
from mission_control.application.execution.harness.points import (
    PointCollectingLane,
    TurnPointsRequest,
)
from mission_control.domain.execution.cognition_points import SessionCursorPoint
from mission_control.domain.execution.lane_turns import NativeRefs
from mission_control.domain.frames.contracts import ProviderFrame
from tests.fixtures.lane_turns import RecordingSignals
from tests.unit.claude.fixtures import SESSION_ID, ClaudeStack, claude_stack
from tests.unit.claude.test_claude_harness import _frames, _identity, _turn


async def _settled_turn(tmp_path: Path, script: str = "full_run") -> tuple[ClaudeStack, str]:
    stack = claude_stack(tmp_path, script)
    result = await stack.lanes.service.turn(
        _turn(stack), RecordingSignals(stack.frames, _identity(stack).harness_execution_id)
    )
    assert result.done and result.native.turn_ref is not None
    return stack, result.native.turn_ref


def _request(stack: ClaudeStack, turn: str, **changes: Any) -> TurnPointsRequest:
    frames: tuple[ProviderFrame, ...] = tuple(_frames(stack))
    values: dict[str, Any] = {
        "operation": stack.operation,
        "lane_profile": "claude_agent_sdk",
        "harness_execution_id": str(_identity(stack).harness_execution_id),
        "generation": 1,
        "native": NativeRefs(session_ref=SESSION_ID, turn_ref=turn),
        "turn_no": 1,
        "frames": frames,
        "facts": points.closing_facts_of(frames),
        "attempt_ref": "attempt-1",
    }
    values.update(changes)
    return TurnPointsRequest(**values)


async def test_a_full_turn_folds_into_session_cursor_points_keyed_by_message_uuid(
    tmp_path: Path,
) -> None:
    stack, turn = await _settled_turn(tmp_path)
    assert isinstance(stack.harness, PointCollectingLane)
    assert turn == turn_reference(f"{_identity(stack).harness_execution_id}:1:turn:1")
    observed = stack.harness.turn_points(_request(stack, turn))

    kinds = [point.channel_facts["frame_kind"] for point in observed]
    # The SDK echoes no user prompt and has no turn-start message: the first boundary is the
    # first assistant message; every tool close, the final message, the turn end and the
    # result are boundaries; hook invocations fold into the tool close's range.
    assert kinds == [
        "message",
        "tool_call_completed",
        "message",
        "tool_call_completed",
        "message",
        "turn_ended",
        "run_result",
    ]
    assert all(isinstance(point.point, SessionCursorPoint) for point in observed)
    refs = [point.point for point in observed]
    assert all(ref.session_ref == SESSION_ID and ref.turn_ref == turn for ref in refs)  # type: ignore[union-attr]
    assert [ref.step_ref for ref in refs] == [  # type: ignore[union-attr]
        "a-0001::assistant",
        "u-0002:0:user.tool_result",
        "a-0003::assistant",
        "u-0004:0:user.tool_result",
        "a-0005::assistant",
        "r-0006::result.turn_ended",
        "r-0006::result",
    ]
    assert observed[0].locator == f"{SESSION_ID}#{turn}#a-0001::assistant"
    assert len({point.locator for point in observed}) == len(observed)
    assert [point.roles for point in observed] == [
        ("intermediate",),
        ("intermediate",),
        ("intermediate",),
        ("intermediate",),
        ("intermediate",),
        ("intermediate",),
        ("leaf", "result"),
    ]
    assert observed[0].source == "input" and observed[-1].source == "loop"
    locators = [point.locator for point in observed]
    assert [point.parent_locator for point in observed] == [None, *locators[:-1]]
    assert all(point.native_turn_ref == turn for point in observed)
    # The first point folds the session init and the Discovery Proof before it; the tool
    # close folds the Kernel Hook frames (`hook.invoked`, `hook.result`) of its range.
    assert any(":system.init" in key for key in observed[0].frame_keys)
    hook_keys = [key for key in observed[1].frame_keys if ":hook." in key]
    assert hook_keys and all(key.endswith((":hook.invoked", ":hook.result")) for key in hook_keys)
    assert not any(":hook." in key for key in observed[0].frame_keys)
    assert observed[1].channel_facts["tool_call_ref"] == "toolu_bash_01"
    assert observed[1].channel_facts["tool_use_id"] == "toolu_bash_01"
    assert observed[1].channel_facts["is_error"] is False
    assert observed[1].channel_facts["result_digest"].startswith("sha256:")
    assert "content" not in observed[1].channel_facts
    # Usage rides on the assistant messages: one model call per message boundary.
    assert observed[0].usage_delta == {"tokens.input": 120, "tokens.output": 9, "tokens.total": 129}
    assert observed[1].usage_delta == {}
    assert observed[4].usage_delta["tokens.total"] == 129
    assert observed[6].usage_delta == {}, "the result's totals are facts, never added twice"
    assert observed[6].channel_facts["result_usage"]["input_tokens"] == 1500
    assert observed[6].channel_facts["subtype"] == "success"
    assert observed[6].channel_facts["num_turns"] == 2
    first = observed[0].channel_facts
    assert first["message_uuid"] == "a-0001" and first["model"] == "claude-sonnet-4-5"
    assert first["tool_names"] == ["Bash"] and first["text_digest"].startswith("sha256:")
    assert "text" not in first and "content" not in first
    assert [point.message_count for point in observed] == [1, 1, 2, 2, 3, 3, 3]
    assert all(point.seedable for point in observed)


async def test_replacement_and_interrupted_roles_and_the_source_point(tmp_path: Path) -> None:
    stack, turn = await _settled_turn(tmp_path)
    source = SessionCursorPoint(session_ref="sess-0", turn_ref="turn-0", step_ref="x:result")
    observed = points.turn_points(
        _request(
            stack,
            turn,
            interrupted_turn_ref="turn-0",
            source_point=source,
            terminal=False,
            interrupted=True,
        )
    )
    assert observed[0].roles == ("intermediate", "replacement_start")
    assert observed[0].parent_point == source and observed[0].parent_locator is None
    assert observed[-1].roles == ("leaf", "interrupted")


async def test_subagent_steps_carry_the_subordinate_and_are_never_seedable(tmp_path: Path) -> None:
    stack, turn = await _settled_turn(tmp_path, "subagent_task")
    observed = points.turn_points(_request(stack, turn))
    nested = [point for point in observed if "subordinate_ref" in point.channel_facts]
    assert nested, "the subagent's messages become points of the parent's turn"
    assert all(
        point.channel_facts["subordinate_ref"].startswith("claude:task:") for point in nested
    )
    assert all(not point.seedable for point in nested)
    assert observed[-1].seedable and "subordinate_ref" not in observed[-1].channel_facts


async def test_the_generation_fold_and_the_turn_fold_agree_on_one_turn(tmp_path: Path) -> None:
    stack, turn = await _settled_turn(tmp_path)
    frames = tuple(_frames(stack))
    per_turn = points.turn_points(_request(stack, turn, attempt_ref=None))
    whole = points.generation_points(
        frames,
        harness_execution_id=str(_identity(stack).harness_execution_id),
        generation=1,
        facts=points.closing_facts_of(frames),
    )
    assert [point.locator for point in whole] == [point.locator for point in per_turn]
    assert [point.usage_delta for point in whole] == [point.usage_delta for point in per_turn]
    assert points.closing_facts_of(frames).native_status == "finished"


def test_step_refs_are_the_provider_key_tail() -> None:
    from mission_control.domain.frames.contracts import FrameKind
    from tests.unit.frames.test_frame_boundary_points import frame

    assistant = frame(
        3, FrameKind.MESSAGE, provider_key="claude:a-9::assistant", raw_kind="assistant"
    )
    assert points.step_ref_for(assistant) == "a-9::assistant"
    assert points.message_uuid_of(assistant) == "a-9"
    lane_frame = frame(
        4,
        FrameKind.APPROVAL_RESOLVED,
        provider_key="claude:sess:lane:2:permission.resolved",
        raw_kind="permission.resolved",
    )
    assert points.step_ref_for(lane_frame) == "sess:lane:2:permission.resolved"
    assert points.message_uuid_of(frame(5, FrameKind.MESSAGE, provider_key="codex:x:y:z:m")) is None
