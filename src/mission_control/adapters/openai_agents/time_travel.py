"""`codex_agents` time travel: R1 reconstructed reads and seeds over the session's items.

The Agents API (openai 3.29.0) retrieves sessions, turns, items, children, artifacts and
traces but has no public session-fork, checkpoint selection/restore, history-edit or
rollback endpoint (OPENAI-AGENTS-API-SURFACE-2026-10-30, "Checkpoints, inspection and fork
limits"; design decision OA-D4: offer R1 reconstructed forks, refuse R3). The derived unit of
a fork therefore continues from a **hydration prompt** (`remote_session.time_travel`): the
transcript to the point rebuilt from the durable items this lane persisted as frames (user
and assistant `message` items, command executions, function calls and their outputs), sent
as the first `agent.session.input.message` of a new session that `start` creates and stamps
with the fork request. The source session is never written. Read level R1: messages only;
the provider environment's files are not captured (R2 would need a captured workspace
scope, OA-D4).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, ClassVar, Final

from mission_control.adapters.openai_agents import frames as agents
from mission_control.adapters.openai_agents.cognition_points import AGENTS_POINT_RULES
from mission_control.adapters.openai_agents.harness import PROFILE
from mission_control.adapters.remote_session.cognition_points import HostedPointRules
from mission_control.adapters.remote_session.time_travel import (
    RemoteSessionTimeTravel,
    state_message,
)
from mission_control.application.execution.harness.time_travel import ForkSeedRequest
from mission_control.domain.execution.cognition_points import (
    CognitionPointRef,
    StateMessage,
    ThreadItemPoint,
)
from mission_control.domain.frames.contracts import ProviderFrame

SEED_ITEM: Final = "fork-seed"
_TEXT_PARTS: Final = frozenset({"output_text", "input_text", "text"})
_TOOL_ITEMS: Final = frozenset({"command_execution", "file_change", "web_search", "mcp_tool_call"})


class CodexAgentsTimeTravel(RemoteSessionTimeTravel):
    """`TimeTravelLane` of `codex_agents` over `thread_item` points."""

    profile: ClassVar[str] = PROFILE
    point_kind: ClassVar[str] = "thread_item"
    rules: ClassVar[HostedPointRules] = AGENTS_POINT_RULES

    def messages_of(
        self, frame: ProviderFrame, body: Mapping[str, Any], withheld: list[str]
    ) -> tuple[StateMessage, ...]:
        if frame.raw_kind != agents.ITEM_DONE:
            return ()
        item = agents.mapping(body.get("item"))
        item_id = str(item.get("id")) if item.get("id") else None
        kind = str(item.get("type") or "")
        if kind == "message":
            role = str(item.get("role") or "assistant")
            return (
                state_message(
                    role=role,
                    text=_text(item.get("content")),
                    cap=self._cap,
                    withheld=withheld,
                    message_id=item_id,
                    name=str(item["phase"]) if item.get("phase") else None,
                ),
            )
        if kind == "function_call":
            arguments = item.get("arguments")
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except ValueError:
                    arguments = {"raw": arguments}
            return (
                state_message(
                    role="assistant",
                    text=None,
                    cap=self._cap,
                    withheld=withheld,
                    message_id=item_id,
                    tool_calls=(
                        (
                            str(item.get("call_id") or item_id or ""),
                            str(item.get("name") or "function"),
                            arguments if arguments is not None else {},
                        ),
                    ),
                ),
            )
        if kind == "function_call_output":
            return (
                state_message(
                    role="tool",
                    text=_plain(item.get("output")),
                    cap=self._cap,
                    withheld=withheld,
                    message_id=item_id,
                    tool_call_id=str(item.get("call_id")) if item.get("call_id") else None,
                ),
            )
        if kind in _TOOL_ITEMS:
            arguments = {
                name: value
                for name, value in item.items()
                if name in {"command", "path", "query", "server", "name", "arguments", "cwd"}
            }
            outcome = {
                name: value
                for name, value in item.items()
                if name in {"status", "exit_code", "output", "result", "error"}
            }
            return (
                state_message(
                    role="assistant",
                    text=None,
                    cap=self._cap,
                    withheld=withheld,
                    message_id=item_id,
                    tool_calls=((item_id, kind, arguments),),
                ),
                state_message(
                    role="tool",
                    text=_plain(outcome) if outcome else None,
                    cap=self._cap,
                    withheld=withheld,
                    message_id=f"{item_id}:result" if item_id else None,
                    name=kind,
                    tool_call_id=item_id,
                ),
            )
        return ()

    def derived_point(self, request: ForkSeedRequest) -> CognitionPointRef:
        return ThreadItemPoint(
            thread_ref=request.derived_namespace[:512],
            item_ref=f"{SEED_ITEM}#{request.fork_request_id}"[:512],
        )


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return _plain(content)
    return "".join(
        str(part.get("text") or "")
        for part in content
        if isinstance(part, Mapping) and part.get("type") in _TEXT_PARTS
    )


def _plain(value: Any) -> str:
    if value is None:
        return ""
    return value if isinstance(value, str) else json.dumps(value, sort_keys=True, default=str)


__all__ = ["SEED_ITEM", "CodexAgentsTimeTravel"]
