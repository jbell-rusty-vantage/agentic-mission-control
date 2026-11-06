"""Deep Agents hook callback mapping and effect naming (tracing proposal P3.5; TR-D4).

The Deep Agents lane runs its hook scripts in-process (`hooks.py`), so what a script posts to
the worker's Kernel Hook callback is the `mc.hook_input.v1` it received on stdin, not a
provider payload. `DeepAgentsHookMapper` is therefore the identity mapper: it keeps the
script's tool call and details, takes every identity field from the verified task token
(never from the payload), and names the side effect a permission event gates the same way
the in-process kernel hooks do (`deep_agents_effect`), so an intent written through the
callback and one written by `mc.operation_intent` share the effect ref:

| `mc.hook_event` | effect ref | kind |
| --- | --- | --- |
| `before_tool`, `before_shell`, `before_mcp` | `tool_use:<call_id>` (else a digest) | by tool |
| `subagent_start` | `subagent:<call_id>` | `task` |

The lane's context index reaches a `sessionStart` script through the service's shared
`context_reader` over the token's `workspace_root`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final, cast

from pydantic import ValidationError

from mission_control.adapters.cursor.hooks_callback import hook_scope, tool_effect_kind
from mission_control.application.execution.harness.hook_callbacks import HookTokenContext
from mission_control.contracts.hooks import HookInput, HookToolCall
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.capabilities.hooks import HookEvent
from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.policies.stop_fence import EffectKind

DEEP_AGENTS_SHELL_TOOLS: Final = frozenset({"shell", "execute", "bash"})
DEEP_AGENTS_FILE_TOOLS: Final = frozenset({"write_file", "edit_file"})
_EFFECT_KINDS: Final = frozenset({"shell", "mcp", "file", "task", "model", "other"})
_GATED: Final = frozenset(
    {HookEvent.BEFORE_TOOL, HookEvent.BEFORE_SHELL, HookEvent.BEFORE_MCP, HookEvent.SUBAGENT_START}
)


def deep_agents_effect_kind(tool: HookToolCall) -> EffectKind:
    """The effect class of one Deep Agents tool call: the binding's class when the
    middleware attached one, else the lane's tool names, else the shared rules."""

    declared = (tool.side_effect_class or "").strip().lower()
    if declared in _EFFECT_KINDS:
        return cast(EffectKind, declared)
    name = tool.name.strip().lower()
    if name in DEEP_AGENTS_SHELL_TOOLS:
        return "shell"
    if name in DEEP_AGENTS_FILE_TOOLS:
        return "file"
    return tool_effect_kind(tool.name)


def deep_agents_effect(
    event: HookEvent, tool: HookToolCall | None
) -> tuple[str, EffectKind] | None:
    """The side effect a permission event gates; None when the event gates nothing or the
    call cannot be identified."""

    if event not in _GATED or tool is None:
        return None
    ref = tool.call_id or sha256_digest({"name": tool.name, "input": tool.input})
    if event is HookEvent.SUBAGENT_START:
        return f"subagent:{ref}", "task"
    return f"tool_use:{ref}", deep_agents_effect_kind(tool)


def callback_url(base_url: str, request_scope: str) -> str:
    """The worker's loopback callback for the application of `request_scope` (the route
    `interfaces/http/hook_callback.py::HOOK_CALLBACK_PATH`; the same shape the command-hook
    lanes write into their hook context)."""

    application = request_scope.split("/")[2] if request_scope.startswith("mc/") else "local"
    return f"{base_url.rstrip('/')}/v1/applications/{application}/internal/hook-callback"


def _tool(payload: Mapping[str, Any]) -> HookToolCall | None:
    raw = payload.get("tool")
    if not isinstance(raw, Mapping):
        return None
    try:
        return HookToolCall.model_validate(dict(raw))
    except ValidationError:
        return None


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


class DeepAgentsHookMapper:
    """`NativeHookMapper` for `deep_agents`: the posted payload is already `mc.hook_input.v1`."""

    def hook_input(
        self, event: HookEvent, payload: Mapping[str, Any], context: HookTokenContext
    ) -> HookInput:
        details = payload.get("details")
        return HookInput(
            event=event,
            lane_profile=LaneProfile.DEEP_AGENTS,
            scope=hook_scope(context),
            run_id=context.run_id,
            activation_id=_text(payload.get("activation_id")),
            attempt_no=context.attempt_no,
            generation=context.generation,
            harness_execution_id=str(context.harness_execution_id),
            native_session_ref=_text(payload.get("native_session_ref")),
            native_turn_ref=_text(payload.get("native_turn_ref")),
            tool=_tool(payload),
            workspace_root=context.workspace_root,
            provider_payload_digest=sha256_digest(dict(payload)),
            details=dict(details) if isinstance(details, Mapping) else {},
        )

    def effect(self, event: HookEvent, payload: Mapping[str, Any]) -> tuple[str, EffectKind] | None:
        return deep_agents_effect(event, _tool(payload))


__all__ = [
    "DEEP_AGENTS_FILE_TOOLS",
    "DEEP_AGENTS_SHELL_TOOLS",
    "DeepAgentsHookMapper",
    "callback_url",
    "deep_agents_effect",
    "deep_agents_effect_kind",
]
