"""MO-03: Codex hook payloads to `mc.hook_input.v1`, and the callback service's per-lane mapper.

Payload shapes follow the PreToolUse stdin codex-cli 0.162.1 handed a hook in the MO-03 probe
(`session_id`, `turn_id`, `transcript_path`, `cwd`, `hook_event_name`, `model`,
`permission_mode`, `tool_name` "Bash", `tool_input`, `tool_use_id`) and research/codex.md.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from mission_control.adapters.codex.hooks_callback import CodexHookMapper
from mission_control.adapters.cursor.hooks_callback import CursorHookMapper
from mission_control.application.execution.harness.hook_callbacks import (
    HookCallbackService,
    InMemoryHookIntentLedger,
    InMemoryHookTokenStore,
)
from mission_control.domain.capabilities.hooks import HookDecision, HookEvent
from tests.unit.harness.test_hook_callback import Stack, _context

PRE_TOOL: dict[str, Any] = {
    "session_id": "thr-1",
    "turn_id": "turn-1",
    "transcript_path": "/home/codex/sessions/rollout.jsonl",
    "cwd": "/lease",
    "hook_event_name": "PreToolUse",
    "model": "gpt-5-codex",
    "permission_mode": "bypassPermissions",
    "tool_name": "Bash",
    "tool_input": {"command": "make deploy"},
    "tool_use_id": "call-1",
}


def test_a_pre_tool_use_payload_names_its_call_and_effect() -> None:
    mapper = CodexHookMapper()
    context = _context(lane_profile="codex")
    hook_input = mapper.hook_input(HookEvent.BEFORE_SHELL, PRE_TOOL, context)
    assert hook_input.lane_profile == "codex"
    assert (hook_input.native_session_ref, hook_input.native_turn_ref) == ("thr-1", "turn-1")
    assert hook_input.tool is not None
    assert (hook_input.tool.name, hook_input.tool.call_id) == ("Bash", "call-1")
    assert hook_input.tool.input == {"command": "make deploy"}
    assert hook_input.tool.side_effect_class == "shell"
    assert hook_input.details == {"provider_event": "PreToolUse", "model": "gpt-5-codex"}
    for event in (HookEvent.BEFORE_TOOL, HookEvent.BEFORE_SHELL):
        assert mapper.effect(event, PRE_TOOL) == ("tool_use:call-1", "shell")
    mcp = {**PRE_TOOL, "tool_name": "mcp__docs__search", "tool_use_id": "call-2"}
    assert mapper.effect(HookEvent.BEFORE_MCP, mcp) == ("tool_use:call-2", "mcp")
    patch = {**PRE_TOOL, "tool_name": "apply_patch", "tool_use_id": "call-3"}
    assert mapper.effect(HookEvent.BEFORE_TOOL, patch) == ("tool_use:call-3", "file")
    assert mapper.effect(HookEvent.BEFORE_TOOL, {**PRE_TOOL, "tool_use_id": None}) is None


def test_observation_and_subagent_events_keep_excerpts_and_digests_only() -> None:
    mapper = CodexHookMapper()
    context = _context(lane_profile="codex")
    after = mapper.hook_input(
        HookEvent.AFTER_TOOL,
        {**PRE_TOOL, "hook_event_name": "PostToolUse", "tool_response": "x" * 5_000},
        context,
    )
    assert after.tool is not None and after.tool.output_excerpt == "x" * 2_000
    prompt = mapper.hook_input(
        HookEvent.BEFORE_PROMPT,
        {"hook_event_name": "UserPromptSubmit", "prompt": "secret"},
        context,
    )
    assert "secret" not in prompt.model_dump_json()
    assert prompt.details["prompt_digest"].startswith("sha256:")
    start = mapper.hook_input(HookEvent.SESSION_START, {"source": "startup"}, context)
    assert start.details == {"source": "startup", "provider_event": "session_start"}
    subagent = {"hook_event_name": "SubagentStart", "agent_id": "agent-7", "agent_type": "worker"}
    assert mapper.effect(HookEvent.SUBAGENT_START, subagent) == ("subagent:agent-7", "task")
    stop = mapper.hook_input(HookEvent.STOP, {"stop_hook_active": True}, context)
    assert stop.details["stop_hook_active"] is True


async def test_the_service_reads_each_payload_with_its_lanes_mapper() -> None:
    """One worker service serves both command-hook lanes; the token's lane picks the mapper."""

    stack = Stack()
    service = HookCallbackService(
        tokens=InMemoryHookTokenStore(),
        intents=(intents := InMemoryHookIntentLedger()),
        mapper=CursorHookMapper(),
        lane_mappers={"codex": CodexHookMapper()},
    )
    for lane, kind in (("codex", "file"), ("cursor_local", "other")):
        patch = {**PRE_TOOL, "tool_name": "apply_patch", "tool_use_id": f"call-{lane}"}
        call = stack.call("mc.operation_intent", "before_tool", patch)
        token = await service.issue(_context(lane_profile=lane), ttl=timedelta(minutes=5))
        result = await service.handle(call, token)
        assert result.decision == HookDecision.ALLOW
        recorded = [intent for intent in intents.intents() if intent.lane_profile == lane]
        assert [(intent.effect_ref, intent.effect_kind) for intent in recorded] == [
            (f"tool_use:call-{lane}", kind)
        ]
