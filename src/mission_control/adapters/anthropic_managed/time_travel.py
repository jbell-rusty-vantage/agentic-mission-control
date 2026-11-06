"""`claude_managed` time travel: R1 reconstructed reads and seeds over the session's frames.

Managed Agents (anthropic 1.13.0, beta `managed-agents-2026-04-01`) offers no session fork, no
history import on `create_session` and no event replay into another session: a session is
created idle and only `user.*` events can be sent to it. R3 is therefore refused, and the
derived unit of a fork continues from a **hydration prompt** (`remote_session.time_travel`):
the transcript to the point rebuilt from the frames this lane persisted (`user.message`,
`agent.message`, the tool uses and their results), sent as the first `user.message` of a new
session that `start` creates and stamps with the fork request. The source session is never
written. Read level R1: messages only; the provider environment's files are not captured.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, ClassVar, Final

from mission_control.adapters.anthropic_managed.cognition_points import MANAGED_POINT_RULES
from mission_control.adapters.anthropic_managed.harness import PROFILE
from mission_control.adapters.remote_session.cognition_points import HostedPointRules
from mission_control.adapters.remote_session.time_travel import (
    RemoteSessionTimeTravel,
    state_message,
)
from mission_control.application.execution.harness.time_travel import ForkSeedRequest
from mission_control.domain.execution.cognition_points import (
    CognitionPointRef,
    SessionCursorPoint,
    StateMessage,
)
from mission_control.domain.frames.contracts import ProviderFrame

SEED_TURN: Final = "fork-seed"
_TOOL_USES: Final = {
    "agent.tool_use": "tool",
    "agent.mcp_tool_use": "mcp_tool",
    "agent.custom_tool_use": "custom_tool",
}
_TOOL_RESULTS: Final = {
    "agent.tool_result": "tool_use_id",
    "agent.mcp_tool_result": "tool_use_id",
    "user.custom_tool_result": "custom_tool_use_id",
}


class ClaudeManagedTimeTravel(RemoteSessionTimeTravel):
    """`TimeTravelLane` of `claude_managed` over `session_cursor` points."""

    profile: ClassVar[str] = PROFILE
    point_kind: ClassVar[str] = "session_cursor"
    rules: ClassVar[HostedPointRules] = MANAGED_POINT_RULES

    def messages_of(
        self, frame: ProviderFrame, body: Mapping[str, Any], withheld: list[str]
    ) -> tuple[StateMessage, ...]:
        kind = frame.raw_kind
        event_id = str(body.get("id")) if body.get("id") else None
        if kind == "user.message":
            return (
                state_message(
                    role="user",
                    text=_text(body),
                    cap=self._cap,
                    withheld=withheld,
                    message_id=event_id,
                ),
            )
        if kind == "agent.message":
            return (
                state_message(
                    role="assistant",
                    text=_text(body),
                    cap=self._cap,
                    withheld=withheld,
                    message_id=event_id,
                ),
            )
        if kind in _TOOL_USES:
            name = str(body.get("name") or _TOOL_USES[kind])
            arguments = body.get("input")
            return (
                state_message(
                    role="assistant",
                    text=None,
                    cap=self._cap,
                    withheld=withheld,
                    message_id=event_id,
                    tool_calls=((event_id, name, arguments if arguments is not None else {}),),
                ),
            )
        if kind in _TOOL_RESULTS:
            call_id = body.get(_TOOL_RESULTS[kind])
            content = body.get("content")
            text = _text(body) if isinstance(content, list) else _json_text(content)
            if body.get("is_error"):
                text = f"[error] {text}" if text else "[error]"
            return (
                state_message(
                    role="tool",
                    text=text or None,
                    cap=self._cap,
                    withheld=withheld,
                    message_id=event_id,
                    tool_call_id=str(call_id) if call_id else None,
                ),
            )
        return ()

    def derived_point(self, request: ForkSeedRequest) -> CognitionPointRef:
        return SessionCursorPoint(
            session_ref=request.derived_namespace[:512],
            turn_ref=f"{SEED_TURN}:{request.fork_request_id}"[:512],
        )


def _text(body: Mapping[str, Any]) -> str:
    blocks = body.get("content")
    if not isinstance(blocks, list):
        return _json_text(blocks)
    return "".join(
        str(block.get("text") or "")
        for block in blocks
        if isinstance(block, Mapping) and block.get("type") == "text"
    )


def _json_text(value: Any) -> str:
    if value is None:
        return ""
    return value if isinstance(value, str) else json.dumps(value, sort_keys=True, default=str)


__all__ = ["SEED_TURN", "ClaudeManagedTimeTravel"]
