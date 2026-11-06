"""Codex cognition points: one `thread_item` point per step boundary of a native turn.

Cross-provider control (2026-11-05, DESIGN §4.1, §5). The `codex` lane has no checkpointer:
its lifecycle is the ordered Provider Frames the app-server events became (MP-13 keys
`codex:<thread>:<turn>:<item>:<method>`). This module folds those frames with the shared
`frame_boundary_points` and names every point by the lane's native identity:

- `ThreadItemPoint(thread_ref=<thread id>, item_ref=<item id>)` for a frame that closes an
  item (`item/completed`: an agent or user message, a command execution, a file change, an
  MCP tool call, a dynamic tool call); the item id is read from the persisted provider key
  (stable even when the body was excerpted) and confirmed from the body when it is whole;
- `item_ref = <turn id>:<arrival ordinal>:<method>` for a boundary without an item
  (`turn/started`, `turn/completed`, the synthetic `turn/completed.result`, `error`,
  `thread/compacted`, `serverRequest/resolved`), unique within the generation and stable
  once the frame is persisted.

Usage deltas come from `thread/tokenUsage/updated` frames (`tokenUsage.last`, one model
call each; the lane's attributed companion frame is skipped so a call is never counted
twice). Compaction boundaries are the `thread/compacted` frames (`after_compaction`); a
sub-agent thread's events carry `subordinate_ref = codex:thread:<child>` and are never
seedable. Facts are redacted through `domain/frames/body.py` and never carry a message
text or a command output: text and output are digested and sized only.

Nothing here settles anything: `turn_points` is what `LaneTurnService._settle` records as
evidence (`written_by: adapter`); `collect_points` (`time_travel.py`) re-derives the same
rows from the same frames.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any, Final

from mission_control.application.execution.harness.points import (
    TurnPointsRequest,
    fold_generation_points,
    frame_boundary_points,
)
from mission_control.domain.execution.cognition_points import (
    CognitionPointObservation,
    CognitionPointRef,
    ThreadItemPoint,
)
from mission_control.domain.execution.lane_turns import ClosingFacts
from mission_control.domain.frames.body import frame_body_object, redact_value
from mission_control.domain.frames.contracts import FrameKind, ProviderFrame

PROFILE: Final = "codex"
USAGE_RAW_KIND: Final = "thread/tokenUsage/updated"
_ATTRIBUTED_MARK: Final = ":attributed:"
_KEY_PREFIX: Final = "codex"
MAX_ITEM_REF: Final = 512
# Frame kinds whose step closes a seedable head on this lane (a sub-agent thread's never is).
_SEEDABLE_KINDS: Final[frozenset[FrameKind]] = frozenset(
    {
        FrameKind.TURN_STARTED,
        FrameKind.MESSAGE,
        FrameKind.TOOL_CALL_COMPLETED,
        FrameKind.TOOL_CALL_FAILED,
        FrameKind.APPROVAL_RESOLVED,
        FrameKind.AFTER_COMPACTION,
        FrameKind.SUBAGENT_ENDED,
        FrameKind.TURN_ENDED,
        FrameKind.RUN_RESULT,
    }
)
# Item fields that are facts, never content.
_ITEM_FACT_FIELDS: Final = ("type", "status", "phase", "exitCode", "name", "server", "tool")


def key_parts(provider_key: str) -> tuple[str, str, str, str] | None:
    """`(thread, turn, item, method)` of a `codex:<thread>:<turn>:<item>:<method>...` key."""

    parts = provider_key.split(":")
    if len(parts) < 5 or parts[0] != _KEY_PREFIX:
        return None
    return parts[1], parts[2], parts[3], parts[4]


def body_of(frame: ProviderFrame) -> dict[str, Any]:
    """The whole persisted body, or `{}` when it was excerpted (facts then come from the key)."""

    return frame_body_object(frame.body_excerpt, frame.body_bytes, frame.lifecycle_body)


def item_of(frame: ProviderFrame) -> Mapping[str, Any]:
    item = body_of(frame).get("item")
    return item if isinstance(item, Mapping) else {}


def item_id_of(frame: ProviderFrame) -> str | None:
    """The native item id the frame closes: from the key, confirmed by a whole body."""

    parts = key_parts(frame.provider_key)
    from_key = parts[2] if parts is not None and parts[2] else None
    from_body = item_of(frame).get("id")
    if isinstance(from_body, str) and from_body:
        return from_body
    return from_key


def turn_id_of(frame: ProviderFrame) -> str | None:
    if frame.native_turn_ref:
        return frame.native_turn_ref
    parts = key_parts(frame.provider_key)
    return parts[1] if parts is not None and parts[1] else None


def item_ref_for(frame: ProviderFrame) -> str:
    """The point's `item_ref`: the item id, else `<turn>:<arrival ordinal>:<method>`."""

    item_id = item_id_of(frame)
    if item_id is not None and frame.kind is not FrameKind.USAGE:
        return item_id[:MAX_ITEM_REF]
    turn = turn_id_of(frame) or "turn"
    return f"{turn}:{frame.arrival_ordinal}:{frame.raw_kind}"[:MAX_ITEM_REF]


def point_for(frame: ProviderFrame) -> CognitionPointRef:
    return ThreadItemPoint(thread_ref=frame.native_session_ref[:512], item_ref=item_ref_for(frame))


def usage_of(frame: ProviderFrame) -> dict[str, int]:
    """`tokenUsage.last` of one `thread/tokenUsage/updated` (one model call), as `tokens.*`."""

    if frame.raw_kind != USAGE_RAW_KIND or _ATTRIBUTED_MARK in frame.provider_key:
        return {}
    usage = body_of(frame).get("tokenUsage")
    last = usage.get("last") if isinstance(usage, Mapping) else None
    if not isinstance(last, Mapping):
        return {}
    names = {
        "inputTokens": "tokens.input",
        "cachedInputTokens": "tokens.cached_input",
        "cacheWriteInputTokens": "tokens.cache_write_input",
        "outputTokens": "tokens.output",
        "reasoningOutputTokens": "tokens.reasoning_output",
        "totalTokens": "tokens.total",
    }
    delta: dict[str, int] = {}
    for wire, name in names.items():
        value = last.get(wire)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            delta[name] = value
    return delta


def _digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def facts_of(frame: ProviderFrame) -> dict[str, Any]:
    """Redacted, content-free facts of one boundary frame."""

    facts: dict[str, Any] = {}
    thread = frame.native_session_ref
    turn = turn_id_of(frame)
    if thread:
        facts["thread_id"] = thread
    if turn:
        facts["turn_id"] = turn
    item_id = item_id_of(frame)
    if item_id is not None and frame.kind is not FrameKind.USAGE:
        facts["item_id"] = item_id
    item = item_of(frame)
    for name in _ITEM_FACT_FIELDS:
        value = item.get(name)
        if isinstance(value, str | int | bool) and value != "":
            facts[f"item_{name.lower()}"] = value
    text = item.get("text")
    if isinstance(text, str) and text:
        facts["text_bytes"] = len(text.encode("utf-8"))
        facts["text_digest"] = _digest(text)
    command = item.get("command")
    if isinstance(command, str) and command:
        redacted, _found = redact_value(command)
        facts["command_digest"] = _digest(str(redacted))
    body = body_of(frame)
    if frame.kind is FrameKind.ERROR:
        error = body.get("error")
        if isinstance(error, Mapping):
            info = error.get("codexErrorInfo")
            if isinstance(info, str):
                facts["codex_error_info"] = info
            elif isinstance(info, Mapping) and len(info) == 1:
                facts["codex_error_info"] = str(next(iter(info)))
    if frame.kind in {FrameKind.TURN_ENDED, FrameKind.RUN_RESULT}:
        payload = body.get("turn")
        if isinstance(payload, Mapping):
            status = payload.get("status")
            if isinstance(status, str):
                facts["turn_status"] = status
            duration = payload.get("durationMs")
            if isinstance(duration, int) and not isinstance(duration, bool):
                facts["duration_ms"] = duration
    if frame.body_artifact_ref is not None:
        facts["body_artifact_ref"] = frame.body_artifact_ref
    redacted_facts, _found = redact_value(facts)
    return dict(redacted_facts) if isinstance(redacted_facts, Mapping) else facts


def seedable_for(frame: ProviderFrame) -> bool:
    return frame.subordinate_ref is None and frame.kind in _SEEDABLE_KINDS


def session_ref_of(frames: Sequence[ProviderFrame], fallback: str | None) -> str:
    for frame in frames:
        if frame.native_session_ref:
            return frame.native_session_ref
    return fallback or "thread"


def turn_points(request: TurnPointsRequest) -> tuple[CognitionPointObservation, ...]:
    """`PointCollectingLane.turn_points` for the `codex` lane (the shared fold with the
    lane's native identity, usage and facts)."""

    turn_ref = request.native.turn_ref
    if turn_ref is None:
        return ()
    return frame_boundary_points(
        request.frames,
        session_ref=session_ref_of(request.frames, request.native.session_ref),
        turn_ref=turn_ref,
        harness_execution_id=request.harness_execution_id,
        attempt_ref=request.attempt_ref,
        point_for=point_for,
        usage_of=usage_of,
        facts_of=facts_of,
        seedable=seedable_for,
        terminal=request.terminal,
        source_point=request.source_point,
        interrupted_turn_ref=request.interrupted_turn_ref,
        interrupted_leaf=request.interrupted,
    )


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
    """Every point of one settled generation (several native turns chained), the fold the
    reconciler re-derives with (`CodexTimeTravel.collect_points`)."""

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


def turn_order(frames: Sequence[ProviderFrame]) -> tuple[str, ...]:
    """The native turn ids of a generation in first-arrival order."""

    seen: dict[str, None] = {}
    for frame in sorted(frames, key=lambda item: item.arrival_ordinal):
        turn = frame.native_turn_ref
        if turn and frame.subordinate_ref is None:
            seen.setdefault(turn, None)
    return tuple(seen)


def closing_facts_of(frames: Sequence[ProviderFrame]) -> ClosingFacts:
    """The closing facts the last `turn/completed.result` frame of a generation carries, for
    a re-derivation without the settlement's record (`in_doubt` when none is whole)."""

    from mission_control.adapters.codex.frames import closing_facts
    from mission_control.adapters.codex.protocol import Turn

    for frame in sorted(frames, key=lambda item: item.arrival_ordinal, reverse=True):
        if frame.kind is not FrameKind.RUN_RESULT:
            continue
        payload = body_of(frame).get("turn")
        if isinstance(payload, Mapping):
            try:
                return closing_facts(
                    Turn.model_validate(payload), usage=None, last_agent_text=None, model=None
                )
            except ValueError:
                break
    return ClosingFacts(native_status="in_doubt", error_code="frames_incomplete")


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


__all__ = [
    "MAX_ITEM_REF",
    "PROFILE",
    "USAGE_RAW_KIND",
    "body_of",
    "closing_facts_of",
    "facts_of",
    "generation_points",
    "item_id_of",
    "item_of",
    "item_ref_for",
    "key_parts",
    "point_for",
    "seedable_for",
    "session_ref_of",
    "turn_id_of",
    "turn_order",
    "turn_points",
    "usage_of",
]
