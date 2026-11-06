"""The Claude lane family's declared describe matrices and declarations (MP-07; OC-R3).

`claude_agent_sdk` (SPEC-01 "Claude local") and the evidence-blocked provider-hosted
`claude_cloud` stub. The lane package owns both matrices (OC-R3);
`application/execution/harness/describe.py` aggregates every lane package's module. Pure data:
this module imports only domain types. The harness in `harness.py` reports
`CLAUDE_AGENT_SDK_DESCRIBE`; the notes below record the SDK source behind each cell: which
controls the harness implements natively, which it emulates, and which stay `unqualified`
because no code exists or the SDK offers no surface. Nothing is `qualified`: a qualified cell
needs the owner-run bounded live drill recorded under `docs/qualification/lanes/claude_agent_sdk/`.

Every statement below is backed by the pinned `claude_agent_sdk==0.2.165` source:

- `start`/`send_turn`/`observe`: `claude_agent_sdk.client.ClaudeSDKClient.connect`, `.query`,
  `.receive_messages` (streaming input mode, one subprocess per session).
- `cancel_turn`: `ClaudeSDKClient.interrupt` -> `_internal.query.Query.interrupt`
  (`{"subtype": "interrupt"}` control request); the aborted turn's `ResultMessage` carries
  `terminal_reason` `aborted_streaming` / `aborted_tools` (`types.ResultMessage`).
- `reattach` is *emulated*: the agent loop lives in the worker's subprocess and there is no
  attach-to-running-process API; recovery is `ClaudeAgentOptions.resume=<session_id>` into a
  fresh process (`types.ClaudeAgentOptions.resume`), which is a new connection/generation.
- `usage`: `ResultMessage.usage` (per turn, main loop only) and `total_cost_usd` (a client-side
  estimate, per `types.ResultMessage` / docs cost-tracking) -> tokens settled, cost estimated.
- `snapshot`: emulated through the MP-04 workspace allocator (git patch custody).
- `pause`: the SDK has no pause; the `PreToolUse` `permissionDecision: "defer"` path
  (`types.PreToolUseHookSpecificOutput`) is not implemented here, so the cell stays
  `unqualified` (and `pause` is a typed `unsupported_control` mid-run).
- `fork`: emulated (cross-provider control, 2026-11-05): `time_travel.ClaudeTimeTravel.
  seed_fork` truncates the state-root transcript mirror at the point and the derived unit
  resumes it under a new session id (`ClaudeAgentOptions.resume`; `fork_session` is not used,
  the id is minted here); the derived workspace is not restored by the fork. Time travel:
  `read` R3 (the mirror, when a lease on this worker still holds it; R1 from the frames
  otherwise, R2 with the turn's continuation snapshot), `fork` R3 reconstructed (R1 when the
  transcript is rebuilt from frames). FIXTURE-proven; no drill backs a truncated resume.
- approvals: `ClaudeAgentOptions.can_use_tool` (`types.CanUseTool`) binds provider permission
  requests; MCP elicitation is not forwarded by the Python SDK (`types.McpSdkServerConfig`
  docstring: "Requests ... the server sends to the client (sampling, elicitation, ...) are not
  forwarded yet"), and no user-question callback exists in the Python type surface, so
  `provider_question` and `mcp_elicitation` are not claimed.
- compaction: `PreCompact` is a Python hook event (`types.HookEvent`) and is observed as a
  `before_compaction` frame; there is no `PostCompact` callback and no compaction control
  request in `Query`, so `compaction_control` stays `unqualified` (observation, no control).
- subordinates: `AssistantMessage.parent_tool_use_id` / `Task*Message.tool_use_id` give the
  spawn identity; with `forward_subagent_text` the SDK also forwards text, but only the tool
  and task lifecycle is proven by fixtures here -> `lifecycle_only`.
"""

from __future__ import annotations

from typing import Final

from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.execution.lanes import (
    LANE_CONTROLS,
    LANE_DESCRIBE_SCHEMA_V2,
    ControlSupport,
    FeatureEvidence,
    LaneDescribe,
    LaneHooks,
    LaneIdentityMap,
    LaneSubagents,
    LaneTimeTravel,
    LaneUsage,
    unqualified_features,
)
from mission_control.domain.execution.subagent_support import derived_file_lane_row
from mission_control.domain.resolution.configuration import ConfigurationItemKind
from mission_control.domain.resolution.profiles import ItemSupport, LaneDeclaration, ModelRoute

_UNQUALIFIED_CONTROLS: Final = dict.fromkeys(LANE_CONTROLS, "unqualified")
_UNSUPPORTED: Final = FeatureEvidence(status="unsupported")

_CLAUDE_HOOKS: Final = (
    "session_start",
    "before_prompt",
    "before_tool",
    "after_tool",
    "after_tool_failure",
    "before_shell",
    "after_shell",
    "before_mcp",
    "after_file_edit",
    "before_compaction",
    "after_compaction",
    "subagent_start",
    "subagent_stop",
    "stop",
    "session_end",
)

CLAUDE_SDK_VERSION: Final = "0.2.165"
CLAUDE_BUNDLED_CLI_VERSION: Final = "2.1.294"


def _local_feature(
    status: ControlSupport, *, transport: str, sdk_version: str, provider_scope: str, os: str
) -> FeatureEvidence:
    return FeatureEvidence(
        status=status,
        implemented=True,
        account_enabled="unknown",
        qualified=False,
        transport=transport,
        sdk_language="python",
        sdk_version=sdk_version,
        provider_scope=provider_scope,
        os=os,
    )


def _claude(status: ControlSupport = "native") -> FeatureEvidence:
    return _local_feature(
        status,
        transport="stdio_subprocess",
        sdk_version=CLAUDE_SDK_VERSION,
        provider_scope="anthropic:claude_code_local",
        os="linux",
    )


# Approvals: `can_use_tool` binds provider permission requests (MP-11 broker). The Python SDK
# forwards no MCP elicitation (`types.McpSdkServerConfig`) and has no user-question callback,
# so neither `provider_question` nor `mcp_elicitation` is claimed. `PreCompact` is observed
# only (no compaction control request), so compaction stays `unqualified`.
CLAUDE_AGENT_SDK_DESCRIBE: Final = LaneDescribe(
    schema_version=LANE_DESCRIBE_SCHEMA_V2,
    lane="claude",
    lane_profile="claude_agent_sdk",
    versions={
        "claude_agent_sdk": CLAUDE_SDK_VERSION,
        "claude_code_bundled": CLAUDE_BUNDLED_CLI_VERSION,
        "transport": "stdio_subprocess",
    },
    controls={
        "prepare": "native",
        "start": "native",
        "reattach": "emulated",
        "send_turn": "native",
        "cancel_turn": "native",
        "observe": "native",
        "snapshot": "emulated",
        "usage": "native",
        "end_session": "native",
        "pause": "unqualified",
        "fork": "emulated",
    },
    delivery_semantics={
        "queue_instruction": "turn_boundary_guaranteed",
        "interrupt_and_inject": "cancel_and_replace",
        "pause": "pause_at_tool_gate",
        "hard_pause": "unsupported",
        "resume": "turn_boundary_guaranteed",
        "cancel": "turn_boundary_guaranteed",
        "fork": "emulated",
        "request_continuation": "emulated",
    },
    identity=LaneIdentityMap(
        session_ref="session_id",
        turn_ref="user_message_uuid",
        effect_ref="tool_use_id",
        cursor="session_log_ordinal",
    ),
    hooks=LaneHooks(
        mechanism="sdk_callbacks+command_hooks", events_supported=_CLAUDE_HOOKS, fail_closed=True
    ),
    instruction_channel=("CLAUDE.md", "prompt", ".claude/settings.json"),
    subagents=LaneSubagents(
        file=".claude/agents/*.md",
        inline="ClaudeAgentOptions.agents",
        readonly_supported_inline=True,
        fields=derived_file_lane_row(LaneProfile.CLAUDE_AGENT_SDK),
    ),
    usage=LaneUsage(tokens="settled_per_turn", cost="estimated"),
    placement="worker_hosted",
    qualified=False,
    features={
        "launch": _claude(),
        "status": _claude(),
        "observe": _claude(),
        "follow_up": _claude(),
        "cancel": _claude(),
        "usage": _claude(),
        "output_custody": _claude("emulated"),
        "environment_selection": FeatureEvidence(status="unqualified"),
        "configuration_materialization": _claude(),
        "approval_suspension": _claude(),
        "subordinate_lineage": _claude(),
        # Sealed-checkpoint transfer into a fresh session (no conversation fork claimed).
        "continuation": _claude("emulated"),
    },
    approval_modes=("workflow_gate", "provider_permission", "governed_effect"),
    compaction_control="unqualified",
    subordinate_visibility="lifecycle_only",
    enforcement_coverage={"shell": "native", "file": "native", "mcp": "native"},
    # Cross-provider control (2026-11-05): the maximum each port reaches; every read and
    # seed receipt names the level it actually reached (`time_travel.py`).
    time_travel=LaneTimeTravel(read="R3", fork="R3"),
)

# Provider-hosted Claude Code (docs/qualification/lanes/claude_cloud/FEASIBILITY.md): the
# repository's settings-file hooks run in the cloud session, but no loopback callback can be
# reached, so no fail-closed Kernel Hook runs there.
CLAUDE_CLOUD_DESCRIBE: Final = LaneDescribe(
    schema_version=LANE_DESCRIBE_SCHEMA_V2,
    lane="claude",
    lane_profile="claude_cloud",
    versions={"claude_code": "unpinned", "cloud_api": "undocumented"},
    controls=dict(_UNQUALIFIED_CONTROLS),
    delivery_semantics={
        "queue_instruction": "wait_then_send",
        "interrupt_and_inject": "cancel_and_replace",
        "pause": "unsupported",
        "hard_pause": "unsupported",
        "resume": "wait_then_send",
        # No public cancel/interrupt surface exists (FEASIBILITY "Required controls" 4).
        "cancel": "unsupported",
        "fork": "unsupported",
        "request_continuation": "emulated",
    },
    identity=LaneIdentityMap(
        session_ref="cloud_session_id",
        turn_ref="message_uuid",
        effect_ref="tool_use_id",
        cursor="uuid",
    ),
    hooks=LaneHooks(mechanism="command_hooks", events_supported=_CLAUDE_HOOKS, fail_closed=False),
    instruction_channel=("CLAUDE.md", ".claude/settings.json"),
    subagents=LaneSubagents(
        file=".claude/agents/*.md",
        inline=None,
        readonly_supported_inline=False,
        fields=derived_file_lane_row(LaneProfile.CLAUDE_CLOUD),
    ),
    usage=LaneUsage(tokens="unavailable", cost="unavailable"),
    placement="cloud",
    qualified=False,
    features={
        **unqualified_features(),
        # Undocumented on every public surface as of 2026-10-08 (FEASIBILITY per-feature table).
        "status": _UNSUPPORTED,
        "cancel": _UNSUPPORTED,
        "approval_suspension": _UNSUPPORTED,
        "subordinate_lineage": _UNSUPPORTED,
    },
    approval_modes=("workflow_gate",),
    compaction_control="unqualified",
    subordinate_visibility="unavailable",
    enforcement_coverage={"shell": "unqualified", "file": "unqualified", "mcp": "unqualified"},
)
# Why `claude_cloud` compiles structurally but never launches (MP-18; the v2 admission warning).
CLAUDE_CLOUD_LAUNCH_EVIDENCE: Final = (
    "docs/qualification/lanes/claude_cloud/REVALIDATION-2026-10-09.md (MP-18)"
)

# What the Claude profiles declare to the resolution seam (design §§3, 6.1, 9.1; D11,
# OC-D199). The compile is describe-only until the provider sweep: the cells state what
# today's launch resolver (`manifest_launch_inputs.py::provider_node`) and the lane's projection
# writer do, not what a compile has receipted. Evidence per cell:
# - model routes: Claude Code runs Anthropic models only (the vendor of the
#   `domain/execution/bindings.ModelPin` resolved per `providers.<profile>`).
# - skill_bundle, mcp_server, hook_script, subagent_profile: projected (`.claude/skills`,
#   `.mcp.json`, `.claude/settings.json` entries after the Kernel Hooks, `.claude/agents/*.md`).
# - environment_kit: the worker's environment preparation runs the kit (process environment
#   delivery, `application/environments/preparation.py`); the cloud stub never launches.
# - tool, context_bundle, middleware, sandbox_profile: no Claude launch binding.
# - families: StageGraph and GoalDirected roles launch through `lane.turn` on the local
#   profile; the cloud stub compiles them with the evidence-blocked warning (unqualified).
_CLAUDE_ITEMS: Final[dict[ConfigurationItemKind, ItemSupport]] = {
    "skill_bundle": "native",
    "mcp_server": "native",
    "tool": "unsupported",
    "hook_script": "native",
    "subagent_profile": "native",
    "environment_kit": "native",
    "context_bundle": "unsupported",
    "middleware": "unsupported",
    "sandbox_profile": "unsupported",
}
_CLAUDE_ROUTES: Final = (
    ModelRoute(vendor="anthropic", verdict="native", mechanism="claude_code_cli"),
    ModelRoute(vendor="openai", verdict="unsupported", mechanism="none"),
)

CLAUDE_AGENT_SDK_DECLARATION: Final = LaneDeclaration(
    describe=CLAUDE_AGENT_SDK_DESCRIBE,
    model_routes=_CLAUDE_ROUTES,
    items=dict(_CLAUDE_ITEMS),
    families={
        "StageGraph": "native",
        "GoalDirected": "native",
        "ParallelSwarm": "unsupported",
        "EvaluatorOptimizer": "unsupported",
    },
    # The exact versions a deployment must pin (`providers.claude_agent_sdk.pins`).
    pins={
        "sdk.claude_agent_sdk": CLAUDE_SDK_VERSION,
        "cli.claude_code": CLAUDE_BUNDLED_CLI_VERSION,
    },
)
CLAUDE_CLOUD_DECLARATION: Final = LaneDeclaration(
    describe=CLAUDE_CLOUD_DESCRIBE,
    model_routes=(
        ModelRoute(vendor="anthropic", verdict="native", mechanism="claude_code_cloud"),
        ModelRoute(vendor="openai", verdict="unsupported", mechanism="none"),
    ),
    items={**_CLAUDE_ITEMS, "environment_kit": "unsupported"},
    families={
        "StageGraph": "unqualified",
        "GoalDirected": "unqualified",
        "ParallelSwarm": "unsupported",
        "EvaluatorOptimizer": "unsupported",
    },
)

PROFILE: Final = "claude_agent_sdk"
SDK_VERSION: Final = CLAUDE_SDK_VERSION
# `claude_agent_sdk._cli_version.__cli_version__`: the CLI bundled with the pinned SDK.
BUNDLED_CLI_VERSION: Final = CLAUDE_BUNDLED_CLI_VERSION
TRANSPORT: Final = "stdio_subprocess"
SDK_LANGUAGE: Final = "python"
# Local CLI lanes run under WSL/Linux; the Windows worker runs a SelectorEventLoop without
# subprocess support.
WORKER_OS: Final = "linux"
# The settings-file hook vocabulary of Claude Code (`domain/capabilities/hooks._CLAUDE`); the
# in-process subset the Python SDK exposes is what the Kernel Hooks of this lane use (`hooks.py`).
CLAUDE_HOOK_EVENTS: Final = CLAUDE_AGENT_SDK_DESCRIBE.hooks.events_supported


__all__ = [
    "BUNDLED_CLI_VERSION",
    "CLAUDE_AGENT_SDK_DECLARATION",
    "CLAUDE_AGENT_SDK_DESCRIBE",
    "CLAUDE_BUNDLED_CLI_VERSION",
    "CLAUDE_CLOUD_DECLARATION",
    "CLAUDE_CLOUD_DESCRIBE",
    "CLAUDE_CLOUD_LAUNCH_EVIDENCE",
    "CLAUDE_HOOK_EVENTS",
    "CLAUDE_SDK_VERSION",
    "PROFILE",
    "SDK_LANGUAGE",
    "SDK_VERSION",
    "TRANSPORT",
    "WORKER_OS",
]
