"""Claude Agent SDK cognition points: one `session_cursor` point per step boundary of a turn.

Cross-provider control (2026-11-05, DESIGN §4.1, §5). The `claude_agent_sdk` lane has no
checkpointer: its lifecycle is the ordered Provider Frames the SDK messages became (MP-13
keys `claude:<message uuid>[:<block>]:<raw_kind>`, the lane's own `claude:<session>:lane:<n>:
<raw_kind>` for hook and permission frames). This module folds those frames with the shared
`frame_boundary_points` and names every point by the lane's native identity:

- `SessionCursorPoint(session_ref=<session_id>, turn_ref=<user message uuid>, step_ref=<the
  step frame's provider key tail>)`: `<uuid>:assistant` for a model message, `<uuid>:<block>:
  user.tool_result` for a tool close (the frame's `tool_call_ref` is the `tool_use_id`),
  `<uuid>:result.turn_ended` / `<uuid>:result` for the turn end, `<session>:lane:<n>:<raw>`
  for a resolved permission or a hook boundary;
- usage deltas: the SDK reports no `usage` frame; an `assistant` message carries
  `usage` (input/output/cache tokens of that model call) and the terminal `result` the turn's
  totals. A point's `usage_delta` is the sum of the `assistant` usages in its frame range
  (`tokens.*`); the result's own usage is recorded as facts only, never added twice;
- compaction: the SDK exposes `PreCompact` as a hook event only; the lane's Kernel Hook
  frame (`hook.invoked` with `event: before_compaction`) is folded as a boundary too
  (`CLAUDE_STEP_KINDS` adds `before_compaction` to the shared `STEP_KINDS`), so a compaction
  stands as a point even though no `after_compaction` frame exists on this lane;
- subagents: a frame of a subagent's messages carries `subordinate_ref = claude:task:<tool
  use id>` (from `parent_tool_use_id`); such a point is never seedable.

Facts are redacted through `domain/frames/body.py` and never carry message text or tool
output: text is digested and sized only. Nothing here settles anything.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any, Final

from mission_control.application.execution.harness.points import (
    MAX_STEP_REF_LENGTH,
    STEP_KINDS,
    TurnPointsRequest,
    fold_generation_points,
    frame_boundary_points,
)
from mission_control.domain.execution.cognition_points import (
    CognitionPointObservation,
    CognitionPointRef,
    SessionCursorPoint,
)
from mission_control.domain.execution.lane_turns import ClosingFacts
from mission_control.domain.frames.body import frame_body_object, redact_value
from mission_control.domain.frames.contracts import FrameKind, ProviderFrame

PROFILE: Final = "claude_agent_sdk"
_KEY_PREFIX: Final = "claude:"
ASSISTANT_RAW_KIND: Final = "assistant"
RESULT_RAW_KIND: Final = "result"
# The SDK has no `after_compaction` message; `PreCompact` is a hook event the lane records
# as a Kernel Hook frame, folded as a boundary here.
CLAUDE_STEP_KINDS: Final[frozenset[FrameKind]] = STEP_KINDS | {FrameKind.BEFORE_COMPACTION}
_SEEDABLE_KINDS: Final[frozenset[FrameKind]] = frozenset(
    {
        FrameKind.TURN_STARTED,
        FrameKind.MESSAGE,
        FrameKind.TOOL_CALL_COMPLETED,
        FrameKind.TOOL_CALL_FAILED,
        FrameKind.APPROVAL_RESOLVED,
        FrameKind.BEFORE_COMPACTION,
        FrameKind.AFTER_COMPACTION,
        FrameKind.SUBAGENT_ENDED,
        FrameKind.TURN_ENDED,
        FrameKind.RUN_RESULT,
    }
)
_USAGE_NAMES: Final = {
    "input_tokens": "tokens.input",
    "output_tokens": "tokens.output",
    "cache_read_input_tokens": "tokens.cache_read",
    "cache_creation_input_tokens": "tokens.cache_creation",
}


def step_ref_for(frame: ProviderFrame) -> str:
    """The provider key tail (`claude:` stripped), bounded to the step-ref length."""

    key = frame.provider_key
    tail = key.removeprefix(_KEY_PREFIX)
    return tail[:MAX_STEP_REF_LENGTH] or f"{frame.arrival_ordinal}:{frame.kind.value}"


def message_uuid_of(frame: ProviderFrame) -> str | None:
    """The SDK message uuid a frame's key names (`claude:<uuid>[:<block>]:<raw_kind>`)."""

    if not frame.provider_key.startswith(_KEY_PREFIX):
        return None
    parts = frame.provider_key[len(_KEY_PREFIX) :].split(":")
    return parts[0] if parts and parts[0] and parts[0] != "" else None


def body_of(frame: ProviderFrame) -> dict[str, Any]:
    return frame_body_object(frame.body_excerpt, frame.body_bytes, frame.lifecycle_body)


def point_for_turn(turn_ref: str, session_ref: str) -> Any:
    def point_for(frame: ProviderFrame) -> CognitionPointRef:
        return SessionCursorPoint(
            session_ref=session_ref[:512], turn_ref=turn_ref[:512], step_ref=step_ref_for(frame)
        )

    return point_for


def assistant_usage(frame: ProviderFrame) -> dict[str, int]:
    """The `usage` of one `assistant` message frame (one model call), as `tokens.*`."""

    if frame.raw_kind != ASSISTANT_RAW_KIND:
        return {}
    return assistant_usage_of_body(body_of(frame))


def assistant_usage_of_body(body: Mapping[str, Any]) -> dict[str, int]:
    """`tokens.*` of one assistant message body (a frame body or a mirror entry's message)."""

    usage = body.get("usage")
    if not isinstance(usage, Mapping):
        return {}
    delta: dict[str, int] = {}
    for wire, name in _USAGE_NAMES.items():
        value = usage.get(wire)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            delta[name] = value
    if delta:
        delta["tokens.total"] = sum(delta.values())
    return delta


def _digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(block.get("text"))
            for block in content
            if isinstance(block, Mapping) and isinstance(block.get("text"), str)
        )
    return ""


def facts_of(frame: ProviderFrame) -> dict[str, Any]:
    """Redacted, content-free facts of one boundary frame."""

    facts: dict[str, Any] = {}
    if frame.native_session_ref:
        facts["session_id"] = frame.native_session_ref
    uuid = message_uuid_of(frame)
    if uuid:
        facts["message_uuid"] = uuid
    body = body_of(frame)
    raw = frame.raw_kind
    if raw == ASSISTANT_RAW_KIND:
        model = body.get("model")
        if isinstance(model, str):
            facts["model"] = model
        stop = body.get("stop_reason")
        if isinstance(stop, str):
            facts["stop_reason"] = stop
        parent = body.get("parent_tool_use_id")
        if isinstance(parent, str):
            facts["parent_tool_use_id"] = parent
        text = _text_of(body.get("content"))
        if text:
            facts["text_bytes"] = len(text.encode("utf-8"))
            facts["text_digest"] = _digest(text)
        content = body.get("content")
        if isinstance(content, list):
            calls = [
                str(block.get("name"))
                for block in content
                if isinstance(block, Mapping) and block.get("type") == "tool_use"
            ]
            if calls:
                facts["tool_names"] = calls
    elif raw == "user.tool_result":
        facts["tool_use_id"] = body.get("tool_use_id")
        facts["is_error"] = bool(body.get("is_error"))
        text = _text_of(body.get("content"))
        if text:
            facts["result_bytes"] = len(text.encode("utf-8"))
            facts["result_digest"] = _digest(text)
    elif raw in {RESULT_RAW_KIND, "result.turn_ended"}:
        for name in ("subtype", "is_error", "num_turns", "duration_ms", "stop_reason"):
            value = body.get(name)
            if isinstance(value, str | int | bool):
                facts[name] = value
        reason = body.get("terminal_reason")
        if isinstance(reason, str):
            facts["terminal_reason"] = reason
        usage = body.get("usage")
        if isinstance(usage, Mapping):
            facts["result_usage"] = {
                name: value
                for name, value in usage.items()
                if isinstance(value, int) and not isinstance(value, bool)
            }
    elif raw.startswith("hook."):
        event = body.get("event") or body.get("hook_event_name")
        if isinstance(event, str):
            facts["hook_event"] = event
    elif raw.startswith("permission."):
        decision = body.get("decision") or body.get("behavior")
        if isinstance(decision, str):
            facts["permission_decision"] = decision
    if frame.body_artifact_ref is not None:
        facts["body_artifact_ref"] = frame.body_artifact_ref
    redacted, _found = redact_value(facts)
    return dict(redacted) if isinstance(redacted, Mapping) else facts


def seedable_for(frame: ProviderFrame) -> bool:
    return frame.subordinate_ref is None and frame.kind in _SEEDABLE_KINDS


def session_ref_of(frames: Sequence[ProviderFrame], fallback: str | None) -> str:
    for frame in frames:
        if frame.native_session_ref:
            return frame.native_session_ref
    return fallback or "session"


def _with_assistant_usage(
    observed: tuple[CognitionPointObservation, ...], frames: Sequence[ProviderFrame]
) -> tuple[CognitionPointObservation, ...]:
    """The fold sums `usage` frames only; this lane's usage rides on `assistant` messages,
    so each point's delta is the sum over the assistant frames of its range."""

    by_key = {frame.provider_key: frame for frame in frames}
    updated: list[CognitionPointObservation] = []
    for point in observed:
        delta: dict[str, int] = dict(point.usage_delta)
        for key in point.frame_keys:
            frame = by_key.get(key)
            if frame is None:
                continue
            for name, amount in assistant_usage(frame).items():
                delta[name] = delta.get(name, 0) + amount
        updated.append(point.model_copy(update={"usage_delta": delta}) if delta else point)
    return tuple(updated)


def turn_points(request: TurnPointsRequest) -> tuple[CognitionPointObservation, ...]:
    """`PointCollectingLane.turn_points` for the `claude_agent_sdk` lane."""

    turn_ref = request.native.turn_ref
    if turn_ref is None:
        return ()
    session_ref = session_ref_of(request.frames, request.native.session_ref)
    observed = frame_boundary_points(
        request.frames,
        session_ref=session_ref,
        turn_ref=turn_ref,
        harness_execution_id=request.harness_execution_id,
        attempt_ref=request.attempt_ref,
        point_for=point_for_turn(turn_ref, session_ref),
        facts_of=facts_of,
        step_kinds=CLAUDE_STEP_KINDS,
        seedable=seedable_for,
        terminal=request.terminal,
        source_point=request.source_point,
        interrupted_turn_ref=request.interrupted_turn_ref,
        interrupted_leaf=request.interrupted,
    )
    return _with_assistant_usage(observed, request.frames)


def generation_points(
    frames: Sequence[ProviderFrame],
    *,
    harness_execution_id: str,
    generation: int,
    facts: ClosingFacts,
    attempt_ref: str | None = None,
    last_turn_ref: str | None = None,
    replaced: Mapping[str, str] | None = None,
    source_point: CognitionPointRef | None = None,
) -> tuple[CognitionPointObservation, ...]:
    """Every point of one settled generation, the fold the reconciler re-derives with."""

    return fold_generation_points(
        frames,
        collect=turn_points,
        lane_profile=PROFILE,
        harness_execution_id=harness_execution_id,
        generation=generation,
        session_ref=session_ref_of(frames, None),
        facts=facts,
        attempt_ref=attempt_ref,
        last_turn_ref=last_turn_ref,
        replaced=replaced,
        source_point=source_point,
    )


def closing_facts_of(frames: Sequence[ProviderFrame]) -> ClosingFacts:
    """The closing facts of the last whole `result` frame (`in_doubt` when none is)."""

    from mission_control.adapters.claude.frames import closing_facts

    for frame in sorted(frames, key=lambda item: item.arrival_ordinal, reverse=True):
        if frame.kind is FrameKind.RUN_RESULT:
            body = body_of(frame)
            if body:
                return closing_facts(body)
    return ClosingFacts(native_status="in_doubt", error_code="frames_incomplete")


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


__all__ = [
    "ASSISTANT_RAW_KIND",
    "CLAUDE_STEP_KINDS",
    "PROFILE",
    "RESULT_RAW_KIND",
    "assistant_usage",
    "assistant_usage_of_body",
    "body_of",
    "canonical",
    "closing_facts_of",
    "facts_of",
    "generation_points",
    "message_uuid_of",
    "point_for_turn",
    "seedable_for",
    "session_ref_of",
    "step_ref_for",
    "turn_points",
]
