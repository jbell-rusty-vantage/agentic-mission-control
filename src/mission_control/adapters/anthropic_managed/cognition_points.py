"""`claude_managed` cognition points: one `session_cursor` point per step of a Managed turn.

Identity (DESIGN cross-provider-control section 5): `session_ref` is the Managed session id,
`turn_ref` the `user.message` event id the lane sent, `step_ref` the **event id** of the step
frame that closed the step, read from the frame's key `managed:<turn>:<processed_at
micros>.<event id>` (`frames.ManagedEventCursors`); the history-synthesized close
(`managed:<turn>:final`) is step `final`; a content-keyed frame (an id-less event) falls back
to the kernel's `<arrival_ordinal>:<kind>`.

Boundaries are the kernel `STEP_KINDS` as `application/frames/kinds.py` classifies the
Managed events: the turn's `user.message` (the `input` point), every `agent.message`, every
tool result (`agent.tool_result`, `agent.mcp_tool_result`, `user.custom_tool_result`), a
tool confirmation (`user.tool_confirmation`), a compaction
(`agent.thread_context_compacted`), a `session.error` and the close (`session.status_idle`
with an ending stop reason, `session.status_terminated`, `turn.final`).

Usage per step is the `model_usage` of the `span.model_request_end` events folded into the
step (`tokens.<name>`); the turn's cost (`cost.list_cost_minor_units`) is the lane's own
settlement on the closing frame (`mc_turn.list_cost_minor_units`), recorded on the result
point. `session.usage` frames are cumulative session figures and add nothing per step.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from mission_control.adapters.anthropic_managed import frames as managed
from mission_control.adapters.remote_session.cognition_points import (
    HostedPointRules,
    bounded_text,
    frame_body,
)
from mission_control.application.execution.harness.points import default_step_ref
from mission_control.domain.execution.cognition_points import (
    CognitionPointRef,
    SessionCursorPoint,
)
from mission_control.domain.frames.contracts import ProviderFrame

FINAL_STEP: Final = "final"
TOOL_USE_KINDS: Final = frozenset({"agent.tool_use", "agent.mcp_tool_use", "agent.custom_tool_use"})


def step_ref_of(frame: ProviderFrame, turn_ref: str) -> str:
    """The native step reference of a stored Managed frame (see the module doc)."""

    prefix = f"{managed.KEY_PREFIX}:{turn_ref}:"
    if frame.provider_key.startswith(prefix):
        rest = frame.provider_key.removeprefix(prefix)
        if rest == FINAL_STEP:
            return FINAL_STEP
        parsed = managed.parse_position(rest)
        if parsed is not None:
            return parsed[1][:256]
    return default_step_ref(frame)


def point_for(frame: ProviderFrame, session_ref: str, turn_ref: str) -> CognitionPointRef:
    return SessionCursorPoint(
        session_ref=session_ref[:512],
        turn_ref=turn_ref[:512],
        step_ref=step_ref_of(frame, turn_ref),
    )


def step_usage_of(frame: ProviderFrame) -> Mapping[str, int]:
    """The model usage of one `span.model_request_end` event (`tokens.<name>`)."""

    if frame.raw_kind != "span.model_request_end":
        return {}
    usage = frame_body(frame).get("model_usage")
    if not isinstance(usage, Mapping):
        return {}
    return {
        f"tokens.{name}": value
        for name, value in usage.items()
        if isinstance(value, int) and not isinstance(value, bool)
    }


def terminal_usage(frame: ProviderFrame) -> Mapping[str, int]:
    """The turn's settled cost from the lane's close summary (`mc_turn`)."""

    summary = frame_body(frame).get(managed.SUMMARY_KEY)
    if not isinstance(summary, Mapping):
        return {}
    cost = summary.get("list_cost_minor_units")
    if isinstance(cost, int) and not isinstance(cost, bool):
        return {"cost.list_cost_minor_units": cost}
    return {}


def facts_of(frame: ProviderFrame) -> Mapping[str, Any]:
    body = frame_body(frame)
    facts: dict[str, Any] = {}
    event_id = body.get("id")
    if event_id:
        facts["event_id"] = str(event_id)[:256]
    processed_at = body.get("processed_at")
    if isinstance(processed_at, str):
        facts["processed_at"] = processed_at[:64]
    reason = managed.stop_reason(body)
    if reason is not None:
        facts["stop_reason"] = reason
    if frame.raw_kind in TOOL_USE_KINDS or frame.raw_kind == "user.tool_confirmation":
        name = bounded_text(body.get("name"))
        if name:
            facts["tool_name"] = name
        permission = bounded_text(body.get("evaluated_permission"))
        if permission:
            facts["evaluated_permission"] = permission
    if frame.raw_kind in {"agent.tool_result", "agent.mcp_tool_result", "user.custom_tool_result"}:
        facts["is_error"] = bool(body.get("is_error"))
    summary = body.get(managed.SUMMARY_KEY)
    if isinstance(summary, Mapping):
        facts["turn_status"] = bounded_text(summary.get("status"), 32)
        facts["interrupted"] = bool(summary.get("interrupted"))
    return facts


def is_input(frame: ProviderFrame) -> bool:
    return frame.raw_kind == "user.message"


MANAGED_POINT_RULES: Final = HostedPointRules(
    point_for=point_for,
    usage_of=None,
    facts_of=facts_of,
    is_input=is_input,
    terminal_usage=terminal_usage,
    step_usage_of=step_usage_of,
)

__all__ = [
    "FINAL_STEP",
    "MANAGED_POINT_RULES",
    "facts_of",
    "is_input",
    "point_for",
    "step_ref_of",
    "step_usage_of",
    "terminal_usage",
]
