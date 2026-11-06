"""Codex hook payloads to `mc.hook_input.v1` (SPEC-02 section 5; gap G11).

`CodexHookMapper` is the `NativeHookMapper` of the `codex` profile. Codex runs the projected
`.codex/hooks.json` command hooks with a JSON payload on stdin carrying `session_id`,
`turn_id`, `cwd`, `hook_event_name`, `model` and `transcript_path`, plus the event's own
fields (research/codex.md "Hooks"): `tool_name`, `tool_input`, `tool_use_id` and
`tool_response` on the tool events, `prompt` on `UserPromptSubmit`, `source` on
`SessionStart`, `agent_id` on the subagent events and `stop_hook_active` on `Stop`. The raw
payload is kept only as a digest. The effect a permission event gates is named by the tool
call Codex identifies:

| Codex event | `mc.hook_event` | effect ref |
| --- | --- | --- |
| `PreToolUse` | `before_tool` | `tool_use:<tool_use_id>` |
| `PreToolUse` (`Bash`) | `before_shell` | `tool_use:<tool_use_id>` |
| `PreToolUse` (`mcp__.*`) | `before_mcp` | `tool_use:<tool_use_id>` |
| `SubagentStart` | `subagent_start` | `subagent:<agent_id>` |

One shell call fires both `before_tool` and `before_shell`; both name the same effect, so
its Operation Intent is written once.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Final

from mission_control.adapters.cursor.hooks_callback import hook_scope, tool_effect_kind
from mission_control.application.execution.harness.hook_callbacks import HookTokenContext
from mission_control.contracts.hooks import HookInput, HookToolCall
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.capabilities.hooks import HookEvent
from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.policies.stop_fence import EffectKind

EXCERPT_CHARS: Final = 2_000
_TOOL_EVENTS: Final = frozenset(
    {
        HookEvent.BEFORE_TOOL,
        HookEvent.BEFORE_SHELL,
        HookEvent.BEFORE_MCP,
        HookEvent.AFTER_TOOL,
        HookEvent.AFTER_SHELL,
        HookEvent.AFTER_FILE_EDIT,
    }
)
_BEFORE_EVENTS: Final = frozenset(
    {HookEvent.BEFORE_TOOL, HookEvent.BEFORE_SHELL, HookEvent.BEFORE_MCP}
)


def codex_effect_kind(tool_name: str | None) -> EffectKind:
    """Codex names its patch tool `apply_patch`; every other name follows the shared rules."""

    if (tool_name or "").strip().lower() == "apply_patch":
        return "file"
    return tool_effect_kind(tool_name)


def _text(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def _excerpt(value: Any) -> str | None:
    if value is None:
        return None
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True, default=str)
    return text[:EXCERPT_CHARS]


def _tool_input(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    return {} if value is None else {"value": value}


class CodexHookMapper:
    """`NativeHookMapper` for `codex` (the local app-server lane)."""

    def tool(self, event: HookEvent, payload: Mapping[str, Any]) -> HookToolCall | None:
        if event in _TOOL_EVENTS:
            name = _text(payload.get("tool_name"))
            if name is None:
                return None
            return HookToolCall(
                name=name,
                call_id=_text(payload.get("tool_use_id")),
                input=_tool_input(payload.get("tool_input")),
                side_effect_class=codex_effect_kind(name),
                output_excerpt=(
                    None if event in _BEFORE_EVENTS else _excerpt(payload.get("tool_response"))
                ),
            )
        if event in {HookEvent.SUBAGENT_START, HookEvent.SUBAGENT_STOP}:
            return HookToolCall(
                name="task",
                call_id=_text(payload.get("agent_id")),
                input={"agent_type": payload.get("agent_type")},
                side_effect_class="task",
            )
        return None

    def details(self, event: HookEvent, payload: Mapping[str, Any]) -> dict[str, Any]:
        if event == HookEvent.SESSION_START:
            return {"source": payload.get("source")}
        if event == HookEvent.BEFORE_PROMPT:
            return {"prompt_digest": sha256_digest(str(payload.get("prompt", "")))}
        if event in {HookEvent.SESSION_END, HookEvent.BEFORE_COMPACTION}:
            return {"reason": payload.get("reason"), "trigger": payload.get("trigger")}
        if event == HookEvent.STOP:
            return {"stop_hook_active": payload.get("stop_hook_active")}
        return {}

    def hook_input(
        self, event: HookEvent, payload: Mapping[str, Any], context: HookTokenContext
    ) -> HookInput:
        details = {
            key: value for key, value in self.details(event, payload).items() if value is not None
        }
        details["provider_event"] = _text(payload.get("hook_event_name")) or event.value
        if _text(payload.get("model")):
            details["model"] = payload["model"]
        return HookInput(
            event=event,
            lane_profile=LaneProfile(context.lane_profile),
            scope=hook_scope(context),
            run_id=context.run_id,
            attempt_no=context.attempt_no,
            generation=context.generation,
            harness_execution_id=str(context.harness_execution_id),
            native_session_ref=_text(payload.get("session_id")),
            native_turn_ref=_text(payload.get("turn_id")),
            tool=self.tool(event, payload),
            workspace_root=context.workspace_root,
            provider_payload_digest=sha256_digest(dict(payload)),
            details=details,
        )

    def effect(self, event: HookEvent, payload: Mapping[str, Any]) -> tuple[str, EffectKind] | None:
        if event in _BEFORE_EVENTS:
            tool_use_id = _text(payload.get("tool_use_id"))
            if tool_use_id is None:
                return None
            return f"tool_use:{tool_use_id}", codex_effect_kind(_text(payload.get("tool_name")))
        if event == HookEvent.SUBAGENT_START:
            agent_id = _text(payload.get("agent_id"))
            return (f"subagent:{agent_id}", "task") if agent_id is not None else None
        return None


__all__ = ["CodexHookMapper", "codex_effect_kind"]
