"""The Codex lane family's declared describe matrices and declarations (MP-08; OC-R3).

`codex` (Codex app-server on a worker) and the evidence-blocked provider-hosted `codex_cloud`
stub. The lane package owns both matrices (OC-R3); `application/execution/harness/describe.py`
aggregates every lane package's module. Pure data: this module imports only domain types; the
harness checks the declared versions against the pinned app-server
(`protocol.codex_local_describe`). Every cell is honest about this pin (`codex-cli 0.162.1`,
app-server protocol v2 over stdio, Linux/WSL workers), none of it qualified:

- controls: `prepare`, `start`, `send_turn`, `cancel_turn`, `observe`, `usage`,
  `end_session` native; `reattach` and `snapshot` emulated (a relaunch plus `thread/resume`
  and history; a git patch); `pause` emulated (approval requests are held at the tool gate,
  `pause_at_tool_gate`); `fork` emulated (cross-provider control, 2026-11-05: `time_travel.
  CodexTimeTravel.seed_fork` forks the source thread through a turn with `thread/fork`
  `lastTurnId` and reconstructs the steps inside a turn from the frames; the derived unit's
  workspace is not restored by the fork; FIXTURE-proven, no drill backs `thread/fork`).
- time travel: `read` R3 (`thread/read` of a thread this worker still holds; R1 from the
  persisted frames otherwise, R2 with the turn's continuation snapshot), `fork` R3 (native
  through a closed turn, reconstructed inside a turn; R1 transcript without a live thread).
- delivery: `queue_instruction` and `resume` are `wait_then_send` (a `turn/start` on an
  active thread would steer it, so the lane only sends on an idle thread);
  `interrupt_and_inject` reads the frozen `LANE_COMMAND_SEMANTICS` cell so the describe and
  the workflow's receipts always agree (the harness implements both `cooperative_inject` via
  `turn/steer` and `cancel_and_replace`); `cancel` is `turn_boundary_guaranteed`.
- identity: thread id, turn id, item id; the cursor is `turn_id@connection_epoch:event_seq`.
- features: implemented on fixtures only; `qualified=False` everywhere until the owner-run
  drill (docs/qualification/lanes/codex/README.md); `environment_selection` is unsupported
  on a local workspace lane.
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
from mission_control.domain.resolution.profiles import LaneDeclaration, ModelRoute

_UNQUALIFIED_CONTROLS: Final = dict.fromkeys(LANE_CONTROLS, "unqualified")
_UNSUPPORTED: Final = FeatureEvidence(status="unsupported")

# Claude Code's settings-file vocabulary less `after_tool_failure` (Codex has no failure hook).
_CODEX_HOOKS: Final = (
    "session_start",
    "before_prompt",
    "before_tool",
    "after_tool",
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

CODEX_CLI_VERSION: Final = "0.162.1"
CODEX_APP_SERVER_SCHEMA_SHA256: Final = (
    "0bf5254bede109d4ae03ce2e81372e4c93a30b359c0749ec7dce7a9382a7f857"
)


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


def _codex(status: ControlSupport) -> FeatureEvidence:
    return _local_feature(
        status,
        transport="app-server jsonrpc v2 over stdio",
        sdk_version=f"codex-cli {CODEX_CLI_VERSION}",
        provider_scope="local worker, owner account",
        os="linux (WSL)",
    )


# Codex: `turn/start` on an active thread would steer it, so queued instructions and resume
# only send on an idle thread (`wait_then_send`); `turn/steer` gives cooperative inject but the
# declared interrupt mode stays `cancel_and_replace` (`LANE_COMMAND_SEMANTICS`). Approval and
# user-input server requests bind to Human Tasks; `thread/compact` is the explicit compaction.
CODEX_DESCRIBE: Final = LaneDescribe(
    schema_version=LANE_DESCRIBE_SCHEMA_V2,
    lane="codex",
    lane_profile="codex",
    versions={
        "codex_cli": CODEX_CLI_VERSION,
        "app_server_protocol": "v2",
        "app_server_schema_sha256": CODEX_APP_SERVER_SCHEMA_SHA256,
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
        "pause": "emulated",
        "fork": "emulated",
    },
    delivery_semantics={
        "queue_instruction": "wait_then_send",
        "interrupt_and_inject": "cancel_and_replace",
        "pause": "pause_at_tool_gate",
        "hard_pause": "unsupported",
        "resume": "wait_then_send",
        "cancel": "turn_boundary_guaranteed",
        "fork": "emulated",
        "request_continuation": "emulated",
    },
    identity=LaneIdentityMap(
        session_ref="thread_id",
        turn_ref="turn_id",
        effect_ref="item_id",
        cursor="turn_id@connection_epoch:event_seq",
    ),
    hooks=LaneHooks(mechanism="command_hooks", events_supported=_CODEX_HOOKS, fail_closed=True),
    instruction_channel=("AGENTS.md", ".codex/config.toml", "developer_instructions"),
    subagents=LaneSubagents(
        file=".codex/agents/*.toml",
        inline=None,
        readonly_supported_inline=False,
        fields=derived_file_lane_row(LaneProfile.CODEX),
    ),
    usage=LaneUsage(tokens="settled_per_turn", cost="estimated"),
    placement="worker_hosted",
    qualified=False,
    features={
        "launch": _codex("native"),
        "status": _codex("native"),
        "observe": _codex("native"),
        "follow_up": _codex("native"),
        "cancel": _codex("native"),
        "usage": _codex("native"),
        "output_custody": _codex("emulated"),
        "environment_selection": _UNSUPPORTED,
        "configuration_materialization": _codex("native"),
        "approval_suspension": _codex("native"),
        "subordinate_lineage": _codex("emulated"),
        "continuation": _codex("emulated"),
    },
    approval_modes=(
        "workflow_gate",
        "provider_permission",
        "provider_question",
        "mcp_elicitation",
        "governed_effect",
    ),
    compaction_control="native",
    subordinate_visibility="lifecycle_only",
    enforcement_coverage={"shell": "native", "file": "native", "mcp": "emulated"},
    # Cross-provider control (2026-11-05): the maximum each port reaches; every read and
    # seed receipt names the level it actually reached (`time_travel.py`).
    time_travel=LaneTimeTravel(read="R3", fork="R3"),
)

# Codex Cloud tasks (docs/qualification/lanes/codex_cloud/FEASIBILITY.md): no per-task
# config, approval, sandbox, MCP or hook overrides; no command/local hooks under cloud
# orchestration; follow-up and observation are not documented.
CODEX_CLOUD_DESCRIBE: Final = LaneDescribe(
    schema_version=LANE_DESCRIBE_SCHEMA_V2,
    lane="codex",
    lane_profile="codex_cloud",
    versions={"codex_cli": "unpinned", "cloud_api": "undocumented"},
    controls=dict(_UNQUALIFIED_CONTROLS),
    delivery_semantics={
        "queue_instruction": "unsupported",
        "interrupt_and_inject": "unsupported",
        "pause": "unsupported",
        "hard_pause": "unsupported",
        "resume": "unsupported",
        # The experimental CLI exposes submit and list only; no cancel (FEASIBILITY item 5).
        "cancel": "unsupported",
        "fork": "unsupported",
        "request_continuation": "unsupported",
    },
    identity=LaneIdentityMap(
        session_ref="task_id", turn_ref="task_id", effect_ref="item_id", cursor="task_id"
    ),
    hooks=LaneHooks(mechanism="none", fail_closed=False),
    instruction_channel=("AGENTS.md",),
    subagents=LaneSubagents(
        file=None,
        inline=None,
        readonly_supported_inline=False,
        fields=derived_file_lane_row(LaneProfile.CODEX_CLOUD),
    ),
    usage=LaneUsage(tokens="unavailable", cost="unavailable"),
    placement="cloud",
    qualified=False,
    features={
        **unqualified_features(),
        # Absent from every public surface as of 2026-10-08 (FEASIBILITY "Required controls").
        "observe": _UNSUPPORTED,
        "follow_up": _UNSUPPORTED,
        "cancel": _UNSUPPORTED,
        "usage": _UNSUPPORTED,
        "approval_suspension": _UNSUPPORTED,
        "subordinate_lineage": _UNSUPPORTED,
        "continuation": _UNSUPPORTED,
    },
    approval_modes=("workflow_gate",),
    compaction_control="unsupported",
    subordinate_visibility="unavailable",
    enforcement_coverage={"shell": "unsupported", "file": "unsupported", "mcp": "unsupported"},
)
# Why `codex_cloud` compiles structurally but never launches (MP-19; the v2 admission warning).
CODEX_CLOUD_LAUNCH_EVIDENCE: Final = (
    "docs/qualification/lanes/codex_cloud/REVALIDATION-2026-10-09.md (MP-19)"
)

# What the Codex profiles declare to the resolution seam (design §§3, 6.1; D11, OC-D199). The
# compile is describe-only until the provider sweep: the cells state what today's launch
# resolver (`manifest_launch_inputs.py::provider_node`) and the lane's projection writer do,
# not what a compile has receipted. Evidence per cell:
# - model routes: the app-server runs OpenAI models only (the vendor the deployment's
#   model pins belong to).
# - skill_bundle, mcp_server, hook_script, subagent_profile: projected on `codex`
#   (`.agents/skills`, `.codex/config.toml` `mcp_servers`, `.codex/hooks.json`,
#   `.codex/agents/*.toml`). `codex_cloud` takes no per-task MCP configuration and runs no
#   command hooks under cloud orchestration (FEASIBILITY), so those are unsupported there, and
#   its subagent row is unsupported (no agent file surface).
# - environment_kit: the worker's environment preparation runs the kit on `codex`.
# - tool, context_bundle, middleware, sandbox_profile: no Codex launch binding.
# - families: as the Claude profiles (local launches; the cloud stub compiles with a warning).
CODEX_DECLARATION: Final = LaneDeclaration(
    describe=CODEX_DESCRIBE,
    model_routes=(
        ModelRoute(vendor="anthropic", verdict="unsupported", mechanism="none"),
        ModelRoute(vendor="openai", verdict="native", mechanism="codex_app_server"),
    ),
    items={
        "skill_bundle": "native",
        "mcp_server": "native",
        "tool": "unsupported",
        "hook_script": "native",
        "subagent_profile": "native",
        "environment_kit": "native",
        "context_bundle": "unsupported",
        "middleware": "unsupported",
        "sandbox_profile": "unsupported",
    },
    families={
        "StageGraph": "native",
        "GoalDirected": "native",
        "ParallelSwarm": "unsupported",
        "EvaluatorOptimizer": "unsupported",
    },
    # The exact versions a deployment must pin (`providers.codex.pins`).
    pins={"cli.codex": CODEX_CLI_VERSION, "schema.app_server_v2": CODEX_APP_SERVER_SCHEMA_SHA256},
)
CODEX_CLOUD_DECLARATION: Final = LaneDeclaration(
    describe=CODEX_CLOUD_DESCRIBE,
    model_routes=(
        ModelRoute(vendor="anthropic", verdict="unsupported", mechanism="none"),
        ModelRoute(vendor="openai", verdict="native", mechanism="codex_cloud_task"),
    ),
    items={
        "skill_bundle": "native",
        "mcp_server": "unsupported",
        "tool": "unsupported",
        "hook_script": "unsupported",
        "subagent_profile": "unsupported",
        "environment_kit": "unsupported",
        "context_bundle": "unsupported",
        "middleware": "unsupported",
        "sandbox_profile": "unsupported",
    },
    families={
        "StageGraph": "unqualified",
        "GoalDirected": "unqualified",
        "ParallelSwarm": "unsupported",
        "EvaluatorOptimizer": "unsupported",
    },
)

TRANSPORT: Final = "app-server jsonrpc v2 over stdio"

__all__ = [
    "CODEX_APP_SERVER_SCHEMA_SHA256",
    "CODEX_CLI_VERSION",
    "CODEX_CLOUD_DECLARATION",
    "CODEX_CLOUD_DESCRIBE",
    "CODEX_CLOUD_LAUNCH_EVIDENCE",
    "CODEX_DECLARATION",
    "CODEX_DESCRIBE",
    "TRANSPORT",
]
