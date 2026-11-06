"""Hook Event vocabulary and its per-lane-profile native mapping (ADR-0026, SPEC-01;
materialization-observation SPEC-02 §5, MO-31).

One provider-neutral vocabulary; each lane profile maps an event to its native hook name
and, where the provider has no dedicated event, a matcher over the tool name. ``None``
means the event cannot run on that profile and is reported as ``unsupported_on_lane``.

Each entry also records what the provider does with the hook, from the provider's own
documentation and the runs this repository records:

- ``mode``: ``enforce`` when the hook's answer can block the native action (on a stop event,
  blocking means the agent keeps going), ``observe`` when it fires but cannot block;
- ``cloud``: whether the event also fires on the lane's provider-hosted profile; the
  ``cursor_cloud``, ``claude_cloud`` and ``codex_cloud`` mappings are derived from it;
- ``timeout_s`` and ``timeout_max_s``: the provider's default when a hook omits its timeout,
  and its cap (``None`` when the provider documents no number);
- ``fail_closed``: the native form a fail-closed hook takes, ``None`` where the provider has
  none for that event (never on an ``observe`` entry);
- ``evidence``: ``recorded`` when a run this repository records or executes observed the
  event fire (a provider listing the handler is not enough), ``documented`` when the provider
  documentation states it, ``unverified`` otherwise.

A fail-closed hook is enforced only on an ``enforce`` entry with a fail-closed form
(:func:`enforcement_gaps`): compile refuses a fail-closed manifest hook on any other event,
and the Host Projection reports the gap.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mission_control.domain.capabilities.host_support import LaneProfile


class HookEvent(StrEnum):
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    BEFORE_PROMPT = "before_prompt"
    BEFORE_MODEL = "before_model"
    AFTER_MODEL = "after_model"
    BEFORE_TOOL = "before_tool"
    AFTER_TOOL = "after_tool"
    AFTER_TOOL_FAILURE = "after_tool_failure"
    BEFORE_SHELL = "before_shell"
    AFTER_SHELL = "after_shell"
    BEFORE_MCP = "before_mcp"
    AFTER_FILE_EDIT = "after_file_edit"
    BEFORE_COMPACTION = "before_compaction"
    AFTER_COMPACTION = "after_compaction"
    SUBAGENT_START = "subagent_start"
    SUBAGENT_STOP = "subagent_stop"
    STOP = "stop"


class HookInterpreter(StrEnum):
    SH = "sh"
    BASH = "bash"
    PYTHON = "python"
    NODE = "node"


class HookCallback(StrEnum):
    NONE = "none"
    SERVICE = "service"


class HookDecision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    DEFER = "defer"


class HookMode(StrEnum):
    ENFORCE = "enforce"
    OBSERVE = "observe"


class FailClosedForm(StrEnum):
    """How a fail-closed hook is expressed natively on a lane."""

    # Mission Control's own middleware or SDK callback denies when the hook fails.
    IN_PROCESS = "in_process"
    # Cursor `failClosed: true`: a crash, timeout, non-zero exit or missing output blocks;
    # exit 2 denies.
    FAIL_CLOSED_FLAG = "fail_closed_flag"
    # Claude Code `onFailure: "block"` (2.1.295 and later): a failure acts as exit 2 does.
    ON_FAILURE_BLOCK = "on_failure_block"
    # Codex has no fail-closed switch and a crashing or non-zero hook fails open, so the hook
    # (Mission Control's runner and `kernel.py`) answers JSON `permissionDecision: "deny"` /
    # `decision: "block"` with exit 0 itself.
    JSON_DECISION = "json_decision"


class HookEvidence(StrEnum):
    RECORDED = "recorded"
    DOCUMENTED = "documented"
    UNVERIFIED = "unverified"


class NativeHook(BaseModel):
    """Where one Hook Event lands on one lane profile, and what the provider does with it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    native_event: str
    matcher: str | None = None
    mode: HookMode
    cloud: bool = False
    timeout_s: int | None = Field(default=None, ge=1)
    timeout_max_s: int | None = Field(default=None, ge=1)
    fail_closed: FailClosedForm | None = None
    evidence: HookEvidence

    @model_validator(mode="after")
    def observed_hooks_cannot_fail_closed(self) -> NativeHook:
        if self.mode is HookMode.OBSERVE and self.fail_closed is not None:
            raise ValueError("an observe-only native hook has no fail-closed form")
        return self

    @property
    def enforceable(self) -> bool:
        """A fail-closed hook on this entry can block the native action."""
        return self.mode is HookMode.ENFORCE and self.fail_closed is not None


E = HookEvent
ENFORCE, OBSERVE = HookMode.ENFORCE, HookMode.OBSERVE
RECORDED, DOCUMENTED, UNVERIFIED = (
    HookEvidence.RECORDED,
    HookEvidence.DOCUMENTED,
    HookEvidence.UNVERIFIED,
)


def _cloud(local: Mapping[HookEvent, NativeHook]) -> dict[HookEvent, NativeHook]:
    """The entries that also fire on the lane's provider-hosted profile."""
    return {event: hook for event, hook in local.items() if hook.cloud}


# Mission Control's own middleware (adapters/deep_agents/hooks.py): a deny before a tool or a
# model call stops it, a deny on the model's answer (after_model, stop, session_end) replaces
# it with a stop; tool post events and summarization only add context. Executed in
# tests/unit/deep_agents/test_hook_middleware.py and, against a local model,
# tests/integration/deep_agents/test_hooks_local_model.py.
def _deep_agents(native_event: str, mode: HookMode, matcher: str | None = None) -> NativeHook:
    return NativeHook(
        native_event=native_event,
        matcher=matcher,
        mode=mode,
        fail_closed=FailClosedForm.IN_PROCESS if mode is ENFORCE else None,
        evidence=RECORDED,
    )


_DEEP_AGENTS: dict[HookEvent, NativeHook] = {
    E.SESSION_START: _deep_agents("before_agent", ENFORCE),
    E.SESSION_END: _deep_agents("after_agent", ENFORCE),
    E.BEFORE_PROMPT: _deep_agents("before_agent", ENFORCE),
    E.BEFORE_MODEL: _deep_agents("before_model", ENFORCE),
    E.AFTER_MODEL: _deep_agents("after_model", ENFORCE),
    E.BEFORE_TOOL: _deep_agents("wrap_tool_call", ENFORCE),
    E.AFTER_TOOL: _deep_agents("wrap_tool_call", OBSERVE),
    E.AFTER_TOOL_FAILURE: _deep_agents("wrap_tool_call", OBSERVE),
    E.BEFORE_SHELL: _deep_agents("wrap_tool_call", ENFORCE, "shell|execute"),
    E.AFTER_SHELL: _deep_agents("wrap_tool_call", OBSERVE, "shell|execute"),
    E.BEFORE_MCP: _deep_agents("wrap_tool_call", ENFORCE, "mcp__.*"),
    E.AFTER_FILE_EDIT: _deep_agents("wrap_tool_call", OBSERVE, "write_file|edit_file"),
    E.BEFORE_COMPACTION: _deep_agents("summarization", OBSERVE),
    E.AFTER_COMPACTION: _deep_agents("summarization", OBSERVE),
    E.SUBAGENT_START: _deep_agents("wrap_tool_call", ENFORCE, "task"),
    E.SUBAGENT_STOP: _deep_agents("wrap_tool_call", OBSERVE, "task"),
    E.STOP: _deep_agents("after_agent", ENFORCE),
}


# Cursor `.cursor/hooks.json` (cursor.com/docs/hooks, read 2026-10-13; research/cursor.md §5.1
# and fast-track research/cursor-platform.md §2.3). Permission hooks (`preToolUse`,
# `beforeShellExecution`, `beforeMCPExecution`, `subagentStart`) and `beforeSubmitPrompt` can
# block; `sessionStart` is fire-and-forget, `stop`/`subagentStop` only queue a follow-up and
# `preCompact` cannot block. The timeout default is "platform default" with no number. Cloud
# agents run project command hooks only and skip `sessionStart`, `sessionEnd` and the MCP
# hooks (and every hook during early read-only turns). No Cursor run is recorded here: the
# headless SDK per-hook matrix is UNVERIFIED, and `beforeMCPExecution` in particular is
# (docs/qualification/lanes/cursor_local/README.md `governed_effect`).
def _cursor(
    native_event: str,
    mode: HookMode,
    *,
    cloud: bool = True,
    evidence: HookEvidence = DOCUMENTED,
) -> NativeHook:
    return NativeHook(
        native_event=native_event,
        mode=mode,
        cloud=cloud,
        fail_closed=FailClosedForm.FAIL_CLOSED_FLAG if mode is ENFORCE else None,
        evidence=evidence,
    )


_CURSOR_LOCAL: dict[HookEvent, NativeHook] = {
    E.SESSION_START: _cursor("sessionStart", OBSERVE, cloud=False),
    E.SESSION_END: _cursor("sessionEnd", OBSERVE, cloud=False),
    E.BEFORE_PROMPT: _cursor("beforeSubmitPrompt", ENFORCE),
    E.AFTER_MODEL: _cursor("afterAgentResponse", OBSERVE),
    E.BEFORE_TOOL: _cursor("preToolUse", ENFORCE),
    E.AFTER_TOOL: _cursor("postToolUse", OBSERVE),
    E.AFTER_TOOL_FAILURE: _cursor("postToolUseFailure", OBSERVE),
    E.BEFORE_SHELL: _cursor("beforeShellExecution", ENFORCE),
    E.AFTER_SHELL: _cursor("afterShellExecution", OBSERVE),
    E.BEFORE_MCP: _cursor("beforeMCPExecution", ENFORCE, cloud=False, evidence=UNVERIFIED),
    E.AFTER_FILE_EDIT: _cursor("afterFileEdit", OBSERVE),
    E.BEFORE_COMPACTION: _cursor("preCompact", OBSERVE),
    E.SUBAGENT_START: _cursor("subagentStart", ENFORCE),
    E.SUBAGENT_STOP: _cursor("subagentStop", OBSERVE),
    E.STOP: _cursor("stop", OBSERVE),
}
_CURSOR_CLOUD = _cloud(_CURSOR_LOCAL)


# Claude Code settings-file hooks (`.claude/settings.json`, loaded through `setting_sources`),
# which is how the materialized `.mission/hooks/run.py` reaches the session
# (code.claude.com/docs/en/hooks "Exit code 2 behavior per event" and "Decision control", read
# 2026-10-13; research/claude-code.md "Hooks"; docs/research/2026-10-07-coding-lane-surfaces.md).
# `SubagentStart`, `SessionStart`, `SessionEnd`, `PostCompact` and the post-tool events cannot
# block; `Stop`/`SubagentStop` block by continuing, where `onFailure` has no effect. Command
# hooks default to 600 s, 30 s on `UserPromptSubmit`. Claude Code fires the same events in a
# hosted session (repository hooks, single-repository sessions only). Recorded: Claude Code
# 2.1.296 fired the projected `SessionStart` hook and named MCP tools `mcp__<server>__<tool>`
# (tests/fixtures/projections/discovery/claude_agent_sdk.recorded.json).
def _claude(
    native_event: str,
    mode: HookMode,
    matcher: str | None = None,
    *,
    fail_closed: bool = True,
    timeout_s: int = 600,
    evidence: HookEvidence = DOCUMENTED,
) -> NativeHook:
    return NativeHook(
        native_event=native_event,
        matcher=matcher,
        mode=mode,
        cloud=True,
        timeout_s=timeout_s,
        fail_closed=FailClosedForm.ON_FAILURE_BLOCK if mode is ENFORCE and fail_closed else None,
        evidence=evidence,
    )


_CLAUDE: dict[HookEvent, NativeHook] = {
    E.SESSION_START: _claude("SessionStart", OBSERVE, evidence=RECORDED),
    E.SESSION_END: _claude("SessionEnd", OBSERVE),
    E.BEFORE_PROMPT: _claude("UserPromptSubmit", ENFORCE, timeout_s=30),
    E.BEFORE_TOOL: _claude("PreToolUse", ENFORCE),
    E.AFTER_TOOL: _claude("PostToolUse", OBSERVE),
    E.AFTER_TOOL_FAILURE: _claude("PostToolUseFailure", OBSERVE),
    E.BEFORE_SHELL: _claude("PreToolUse", ENFORCE, "Bash"),
    E.AFTER_SHELL: _claude("PostToolUse", OBSERVE, "Bash"),
    E.BEFORE_MCP: _claude("PreToolUse", ENFORCE, "mcp__.*"),
    E.AFTER_FILE_EDIT: _claude("PostToolUse", OBSERVE, "Edit|Write"),
    E.BEFORE_COMPACTION: _claude("PreCompact", ENFORCE),
    E.AFTER_COMPACTION: _claude("PostCompact", OBSERVE),
    E.SUBAGENT_START: _claude("SubagentStart", OBSERVE),
    E.SUBAGENT_STOP: _claude("SubagentStop", ENFORCE, fail_closed=False),
    E.STOP: _claude("Stop", ENFORCE, fail_closed=False),
}
# The provider-hosted Claude Code session runs the same settings-file hooks; the lane profile
# itself stays unqualified until the drill in docs/qualification/lanes/claude_cloud runs.
_CLAUDE_CLOUD = _cloud(_CLAUDE)

# The subset of `_CLAUDE` that the pinned Python `claude_agent_sdk.types.HookEvent` union
# also exposes as in-process callbacks (`PreToolUse`, `PostToolUse`, `PostToolUseFailure`,
# `UserPromptSubmit`, `Stop`, `SubagentStop`, `PreCompact`, `Notification`, `SubagentStart`,
# `PermissionRequest`). `SessionStart`, `SessionEnd` and `PostCompact` fire only as
# settings-file hooks; an in-process kernel hook on them is `unsupported_on_lane`
# (multi-provider RESEARCH.md "Claude SDK language mismatch").
CLAUDE_SDK_CALLBACK_EVENTS: frozenset[HookEvent] = frozenset(
    {
        E.BEFORE_PROMPT,
        E.BEFORE_TOOL,
        E.AFTER_TOOL,
        E.AFTER_TOOL_FAILURE,
        E.BEFORE_SHELL,
        E.AFTER_SHELL,
        E.BEFORE_MCP,
        E.AFTER_FILE_EDIT,
        E.BEFORE_COMPACTION,
        E.SUBAGENT_START,
        E.SUBAGENT_STOP,
        E.STOP,
    }
)


# Codex hooks (`.codex/hooks.json`; learn.chatgpt.com/docs/hooks, read 2026-10-13;
# research/codex.md "Hooks"). Twelve native events, no PostToolUseFailure; the matcher sees
# `Bash` for shell, `apply_patch` for file edits (aliases Write|Edit) and
# `mcp__<server>__<tool>` for MCP tools. `UserPromptSubmit`, `PreToolUse` and `PreCompact`
# block; `Stop`/`SubagentStop` block by continuing; `SessionStart`, `SessionEnd`,
# `SubagentStart`, `PostToolUse` and `PostCompact` cannot block. Timeouts default to 600 s,
# `SessionEnd` to 1 s capped at 3 s. Codex Cloud runs no command, local or repository hooks
# under cloud orchestration. codex-cli 0.162.1 `hooks/list` loaded and trusted the projected
# handler of every native event below
# (tests/fixtures/provider_frames/codex/hooks_list/trust-0.162.1.json); a listing is not a
# firing, so those entries stay `documented`. Recorded: a JSON `permissionDecision: "deny"`
# from the kernel's `PreToolUse` hook blocked a real turn while a non-zero exit failed open
# (MO-03, tests/integration/codex/test_codex_kernel_hook_drill.py).
def _codex(
    native_event: str,
    mode: HookMode,
    matcher: str | None = None,
    *,
    fail_closed: bool = True,
    timeout_s: int = 600,
    timeout_max_s: int | None = None,
    evidence: HookEvidence = DOCUMENTED,
) -> NativeHook:
    return NativeHook(
        native_event=native_event,
        matcher=matcher,
        mode=mode,
        timeout_s=timeout_s,
        timeout_max_s=timeout_max_s,
        fail_closed=FailClosedForm.JSON_DECISION if mode is ENFORCE and fail_closed else None,
        evidence=evidence,
    )


_CODEX: dict[HookEvent, NativeHook] = {
    E.SESSION_START: _codex("SessionStart", OBSERVE),
    E.SESSION_END: _codex("SessionEnd", OBSERVE, timeout_s=1, timeout_max_s=3),
    E.BEFORE_PROMPT: _codex("UserPromptSubmit", ENFORCE),
    E.BEFORE_TOOL: _codex("PreToolUse", ENFORCE, evidence=RECORDED),
    E.AFTER_TOOL: _codex("PostToolUse", OBSERVE),
    E.BEFORE_SHELL: _codex("PreToolUse", ENFORCE, "Bash"),
    E.AFTER_SHELL: _codex("PostToolUse", OBSERVE, "Bash"),
    E.BEFORE_MCP: _codex("PreToolUse", ENFORCE, "mcp__.*"),
    E.AFTER_FILE_EDIT: _codex("PostToolUse", OBSERVE, "apply_patch"),
    E.BEFORE_COMPACTION: _codex("PreCompact", ENFORCE),
    E.AFTER_COMPACTION: _codex("PostCompact", OBSERVE),
    E.SUBAGENT_START: _codex("SubagentStart", OBSERVE),
    E.SUBAGENT_STOP: _codex("SubagentStop", ENFORCE, fail_closed=False),
    E.STOP: _codex("Stop", ENFORCE, fail_closed=False),
}
# Codex Cloud tasks accept no command, local or plugin hooks under cloud orchestration
# (docs/qualification/lanes/codex_cloud/FEASIBILITY.md, "Configuration materialization"):
# every Hook Event is `unsupported_on_lane` there.
_CODEX_CLOUD = _cloud(_CODEX)

# The hosted agent APIs (ADR-0050) run no hook files: Managed Agents ignores `.claude/` hooks
# and the Agents API runs the closed Codex harness. Kernel Hooks are projected as Mission
# Control custom/function tools instead (SPEC-06 section 9), so no Hook Event maps natively.
_HOSTED_AGENT_API: dict[HookEvent, NativeHook] = {}

HOOK_EVENT_MAPPING: Mapping[LaneProfile, Mapping[HookEvent, NativeHook]] = {
    LaneProfile.DEEP_AGENTS: _DEEP_AGENTS,
    LaneProfile.CURSOR_LOCAL: _CURSOR_LOCAL,
    LaneProfile.CURSOR_CLOUD: _CURSOR_CLOUD,
    LaneProfile.CLAUDE_AGENT_SDK: _CLAUDE,
    LaneProfile.CODEX: _CODEX,
    LaneProfile.CLAUDE_CLOUD: _CLAUDE_CLOUD,
    LaneProfile.CODEX_CLOUD: _CODEX_CLOUD,
    LaneProfile.CLAUDE_MANAGED: _HOSTED_AGENT_API,
    LaneProfile.CODEX_AGENTS: _HOSTED_AGENT_API,
}

if set(HOOK_EVENT_MAPPING) != set(LaneProfile):  # pragma: no cover - import-time guard
    raise RuntimeError("HOOK_EVENT_MAPPING must cover every LaneProfile")


def native_hook(profile: LaneProfile | str, event: HookEvent | str) -> NativeHook | None:
    return HOOK_EVENT_MAPPING[LaneProfile(profile)].get(HookEvent(event))


def unsupported_events(
    profile: LaneProfile | str, events: Iterable[HookEvent | str]
) -> tuple[HookEvent, ...]:
    mapping = HOOK_EVENT_MAPPING[LaneProfile(profile)]
    return tuple(sorted({HookEvent(event) for event in events if HookEvent(event) not in mapping}))


def enforcement_gaps(
    profile: LaneProfile | str, events: Iterable[HookEvent | str]
) -> tuple[HookEvent, ...]:
    """The events a fail-closed hook cannot enforce on the profile: unmapped, observe-only, or
    without a native fail-closed form."""

    mapping = HOOK_EVENT_MAPPING[LaneProfile(profile)]
    gaps = set()
    for event in map(HookEvent, events):
        native = mapping.get(event)
        if native is None or not native.enforceable:
            gaps.add(event)
    return tuple(sorted(gaps))


# Mission Control's kernel hooks, in their fixed composition order (SPEC-01 "Kernel hooks").
KERNEL_HOOK_IDS: tuple[str, ...] = (
    "mc.stop_fence",
    "mc.operation_intent",
    "mc.frame_capture",
    "mc.usage",
)

# The events the Stop Fence and the Operation Intent gate: a lane that only observes one of
# them cannot hold the effect it fires for.
KERNEL_GATED_EVENTS: tuple[HookEvent, ...] = (
    E.BEFORE_TOOL,
    E.BEFORE_SHELL,
    E.BEFORE_MCP,
    E.SUBAGENT_START,
)
KERNEL_GATE_HOOK_IDS: frozenset[str] = frozenset({"mc.stop_fence", "mc.operation_intent"})
KERNEL_HOOK_EVENTS: Mapping[str, tuple[HookEvent, ...]] = {
    "mc.stop_fence": KERNEL_GATED_EVENTS,
    "mc.operation_intent": KERNEL_GATED_EVENTS,
    "mc.frame_capture": tuple(HookEvent),
    "mc.usage": (E.AFTER_MODEL, E.AFTER_TOOL, E.STOP),
}
