"""MO-31: the per-profile Hook Event mapping is evidence-based (SPEC-02 §5).

Each entry records enforce/observe, cloud support, the provider's timeouts and its
fail-closed form. Every Codex entry is held to the recorded codex-cli 0.162.1 ``hooks/list``
(MO-03; a listing, so ``documented``), its ``PreToolUse`` deny to the MO-03 drill
(``recorded``), the Claude ``SessionStart`` entry to the recorded Claude Code discovery run;
the rest cite the provider documentation and the packet's fact sheets.
Offline: recorded fixtures only.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from mission_control.domain.capabilities.hooks import (
    HOOK_EVENT_MAPPING,
    KERNEL_GATED_EVENTS,
    FailClosedForm,
    HookEvent,
    HookEvidence,
    HookMode,
    NativeHook,
    enforcement_gaps,
    native_hook,
)
from mission_control.domain.capabilities.host_support import LaneProfile

ROOT = Path(__file__).resolve().parents[3]
CODEX_HOOKS_LIST = ROOT / "tests/fixtures/provider_frames/codex/hooks_list/trust-0.162.1.json"
CLAUDE_DISCOVERY = ROOT / "tests/fixtures/projections/discovery/claude_agent_sdk.recorded.json"
E = HookEvent


def _enforced(profile: LaneProfile) -> set[HookEvent]:
    return {event for event, hook in HOOK_EVENT_MAPPING[profile].items() if hook.enforceable}


@pytest.mark.parametrize("profile", list(LaneProfile))
def test_every_entry_states_mode_form_and_evidence(profile: LaneProfile) -> None:
    for event, hook in HOOK_EVENT_MAPPING[profile].items():
        if hook.mode is HookMode.OBSERVE:
            assert hook.fail_closed is None, (profile, event)
        assert hook.timeout_max_s is None or (hook.timeout_s or 0) <= hook.timeout_max_s
    with pytest.raises(ValidationError, match="observe-only"):
        NativeHook(
            native_event="postToolUse",
            mode=HookMode.OBSERVE,
            fail_closed=FailClosedForm.FAIL_CLOSED_FLAG,
            evidence=HookEvidence.DOCUMENTED,
        )


def test_cloud_profiles_are_the_entries_that_fire_in_the_provider_vm() -> None:
    for local, cloud in (
        (LaneProfile.CURSOR_LOCAL, LaneProfile.CURSOR_CLOUD),
        (LaneProfile.CLAUDE_AGENT_SDK, LaneProfile.CLAUDE_CLOUD),
        (LaneProfile.CODEX, LaneProfile.CODEX_CLOUD),
    ):
        expected = {e: hook for e, hook in HOOK_EVENT_MAPPING[local].items() if hook.cloud}
        assert dict(HOOK_EVENT_MAPPING[cloud]) == expected
    # Cursor Cloud: no session or MCP hooks; Codex Cloud: no command hooks at all.
    assert set(HOOK_EVENT_MAPPING[LaneProfile.CURSOR_LOCAL]) - set(
        HOOK_EVENT_MAPPING[LaneProfile.CURSOR_CLOUD]
    ) == {E.SESSION_START, E.SESSION_END, E.BEFORE_MCP}
    assert HOOK_EVENT_MAPPING[LaneProfile.CODEX_CLOUD] == {}


def test_cursor_blocks_on_permission_hooks_and_before_submit_prompt_only() -> None:
    """cursor.com/docs/hooks: permission hooks and beforeSubmitPrompt block; `failClosed`
    makes a failure block; `sessionStart` is fire-and-forget, `stop` and `preCompact` cannot
    block; the timeout default is unnumbered. No Cursor run is recorded."""

    cursor = HOOK_EVENT_MAPPING[LaneProfile.CURSOR_LOCAL]
    assert _enforced(LaneProfile.CURSOR_LOCAL) == {
        E.BEFORE_PROMPT,
        E.BEFORE_TOOL,
        E.BEFORE_SHELL,
        E.BEFORE_MCP,
        E.SUBAGENT_START,
    }
    assert {hook.fail_closed for hook in cursor.values() if hook.enforceable} == {
        FailClosedForm.FAIL_CLOSED_FLAG
    }
    assert {hook.timeout_s for hook in cursor.values()} == {None}
    assert {hook.evidence for hook in cursor.values()} <= {
        HookEvidence.DOCUMENTED,
        HookEvidence.UNVERIFIED,
    }
    # The headless SDK run of beforeMCPExecution is unverified (cursor_local qualification).
    assert cursor[E.BEFORE_MCP].evidence is HookEvidence.UNVERIFIED


def test_claude_blocks_where_the_exit_2_table_says_and_fails_closed_with_on_failure() -> None:
    """code.claude.com/docs/en/hooks: SubagentStart, SessionStart/End, PostCompact and the
    post-tool events cannot block; Stop/SubagentStop block by continuing, where `onFailure`
    has no effect; command hooks default to 600 s, 30 s on UserPromptSubmit."""

    claude = HOOK_EVENT_MAPPING[LaneProfile.CLAUDE_AGENT_SDK]
    blocking = {event for event, hook in claude.items() if hook.mode is HookMode.ENFORCE}
    assert blocking == {
        E.BEFORE_PROMPT,
        E.BEFORE_TOOL,
        E.BEFORE_SHELL,
        E.BEFORE_MCP,
        E.BEFORE_COMPACTION,
        E.SUBAGENT_STOP,
        E.STOP,
    }
    assert _enforced(LaneProfile.CLAUDE_AGENT_SDK) == blocking - {E.SUBAGENT_STOP, E.STOP}
    assert {hook.fail_closed for hook in claude.values() if hook.enforceable} == {
        FailClosedForm.ON_FAILURE_BLOCK
    }
    assert claude[E.BEFORE_PROMPT].timeout_s == 30
    assert {hook.timeout_s for e, hook in claude.items() if e is not E.BEFORE_PROMPT} == {600}
    assert all(hook.cloud for hook in claude.values())


def test_claude_session_start_is_recorded_by_the_discovery_run() -> None:
    recorded = json.loads(CLAUDE_DISCOVERY.read_text(encoding="utf-8"))
    hooks = {
        (item["name"], item["origin"])
        for item in recorded["layering"]["discovery"]
        if item["kind"] == "hook"
    }
    assert ("SessionStart", "mission") in hooks
    assert any("session_start" in name for name in recorded["hooks_fired"])
    assert HOOK_EVENT_MAPPING[LaneProfile.CLAUDE_AGENT_SDK][E.SESSION_START].evidence is (
        HookEvidence.RECORDED
    )
    # The recorded run names MCP tools the way the before_mcp matcher expects.
    assert all(name.startswith("mcp__") for name in recorded["discovered"]["mcp_tools"])


def test_codex_entries_are_the_events_hooks_list_loaded_and_trusted() -> None:
    """codex-cli 0.162.1 `hooks/list` over the golden projection: every entry's native event
    and matcher is a listed, trusted, enabled handler. A listing is not a firing: only the
    `PreToolUse` deny the MO-03 drill observed is `recorded`."""

    recorded = json.loads(CODEX_HOOKS_LIST.read_text(encoding="utf-8"))
    listed = {
        (hook["eventName"], hook["matcher"])
        for case in recorded["cases"].values()
        for entry in case["hooks_list_result"]["data"]
        for hook in entry["hooks"]
        if hook["trustStatus"] == "trusted" and hook["enabled"]
    }
    codex = HOOK_EVENT_MAPPING[LaneProfile.CODEX]
    for event, hook in codex.items():
        camel = hook.native_event[0].lower() + hook.native_event[1:]
        assert (camel, hook.matcher) in listed, (event, hook)
    assert {event for event, hook in codex.items() if hook.evidence is HookEvidence.RECORDED} == {
        E.BEFORE_TOOL
    }
    # No PostToolUseFailure on Codex; SessionEnd defaults to 1 s capped at 3 s.
    assert E.AFTER_TOOL_FAILURE not in codex
    assert (codex[E.SESSION_END].timeout_s, codex[E.SESSION_END].timeout_max_s) == (1, 3)
    # A non-zero hook fails open on Codex: the fail-closed form is the JSON decision.
    assert {hook.fail_closed for hook in codex.values() if hook.enforceable} == {
        FailClosedForm.JSON_DECISION
    }
    assert _enforced(LaneProfile.CODEX) == {
        E.BEFORE_PROMPT,
        E.BEFORE_TOOL,
        E.BEFORE_SHELL,
        E.BEFORE_MCP,
        E.BEFORE_COMPACTION,
    }
    assert native_hook("codex", "subagent_start") is not None
    assert codex[E.SUBAGENT_START].mode is HookMode.OBSERVE


@pytest.mark.parametrize(
    ("profile", "events", "gaps"),
    [
        ("cursor_cloud", ["before_mcp", "before_shell"], [E.BEFORE_MCP]),
        ("cursor_local", ["before_shell", "stop", "after_file_edit"], [E.AFTER_FILE_EDIT, E.STOP]),
        ("claude_agent_sdk", ["stop", "subagent_start", "before_tool"], [E.STOP, E.SUBAGENT_START]),
        ("codex", ["subagent_start", "before_prompt"], [E.SUBAGENT_START]),
        ("codex_cloud", ["before_tool"], [E.BEFORE_TOOL]),
        ("deep_agents", ["before_tool", "after_tool"], [E.AFTER_TOOL]),
    ],
)
def test_enforcement_gaps_name_what_a_fail_closed_hook_cannot_hold(
    profile: str, events: list[str], gaps: list[HookEvent]
) -> None:
    assert list(enforcement_gaps(profile, events)) == gaps


def test_kernel_gates_are_enforceable_where_kernel_hooks_run_fail_closed() -> None:
    """Stop Fence and Operation Intent gates hold on Deep Agents and Cursor Local; Claude and
    Codex only observe a subagent start, which the projection reports as degraded."""

    assert enforcement_gaps("deep_agents", KERNEL_GATED_EVENTS) == ()
    assert enforcement_gaps("cursor_local", KERNEL_GATED_EVENTS) == ()
    assert enforcement_gaps("claude_agent_sdk", KERNEL_GATED_EVENTS) == (E.SUBAGENT_START,)
    assert enforcement_gaps("codex", KERNEL_GATED_EVENTS) == (E.SUBAGENT_START,)
