"""The Cursor lane family's declared describe matrices and declarations (ADR-0030, OC-R3).

`cursor_local` and `cursor_cloud`: the FT-G1 `mc.lane_describe.v1` cells (kept as `*_V1`,
still readable) and the MP-09 v2 matrices the harnesses report. The lane package owns them;
`application/execution/harness/describe.py` aggregates. Pure data: domain imports only.
"""

from __future__ import annotations

from typing import Final

from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.execution.lanes import (
    LANE_DESCRIBE_SCHEMA_V2,
    LANE_FEATURES,
    ControlSupport,
    FeatureEvidence,
    LaneDescribe,
    LaneHooks,
    LaneIdentityMap,
    LaneSubagents,
    LaneTimeTravel,
    LaneUsage,
)
from mission_control.domain.execution.subagent_support import derived_file_lane_row
from mission_control.domain.resolution.configuration import ConfigurationItemKind, Family
from mission_control.domain.resolution.profiles import (
    FamilySupport,
    ItemSupport,
    LaneDeclaration,
    ModelRoute,
)

_CURSOR_VERSIONS: Final = {"cursor_sdk": "1.0.37", "bridge": "1.0.37", "protocol": "sdk.v1"}
_CURSOR_LOCAL_HOOKS: Final = (
    "session_start",
    "before_tool",
    "after_tool",
    "after_tool_failure",
    "before_shell",
    "after_shell",
    "after_file_edit",
    "before_prompt",
    "before_compaction",
    "subagent_start",
    "subagent_stop",
    "stop",
    "session_end",
)

CURSOR_LOCAL_DESCRIBE_V1: Final = LaneDescribe(
    lane="cursor",
    lane_profile="cursor_local",
    versions=dict(_CURSOR_VERSIONS),
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
        "pause": "unsupported",
        "fork": "emulated",
    },
    delivery_semantics={
        "queue_instruction": "wait_then_send",
        "interrupt_and_inject": "cancel_and_replace",
        "pause": "unsupported",
        "hard_pause": "unsupported",
        "resume": "wait_then_send",
        "cancel": "turn_boundary_guaranteed",
        "fork": "emulated",
        "request_continuation": "emulated",
    },
    identity=LaneIdentityMap(
        session_ref="agent_id", turn_ref="run_id", effect_ref="call_id", cursor="bridge_offset"
    ),
    hooks=LaneHooks(
        mechanism="command_hooks", events_supported=_CURSOR_LOCAL_HOOKS, fail_closed=True
    ),
    instruction_channel=("AGENTS.md", ".cursor/rules/mc-mission.mdc", "prompt_prefix"),
    subagents=LaneSubagents(
        file=".cursor/agents/*.md",
        inline="AgentOptions.agents",
        readonly_supported_inline=False,
        fields=derived_file_lane_row(LaneProfile.CURSOR_LOCAL),
    ),
    usage=LaneUsage(tokens="settled_per_turn", cost="estimated_then_settled"),
    placement="worker_hosted",
    qualified=False,
    # Cross-provider control (2026-11-05): `read_as_of` reconstructs the transcript from the
    # persisted frames up to the point and lists the files of the turn-close
    # `mc.cursor_snapshot.v1` (R2); `seed_fork` stages that snapshot and a reconstructed
    # transcript prompt for the derived unit's fresh lease and agent (R2; the SDK has no
    # conversation fork). `adapters/cursor/time_travel.py`.
    time_travel=LaneTimeTravel(read="R2", fork="R2"),
)

CURSOR_CLOUD_DESCRIBE_V1: Final = LaneDescribe(
    lane="cursor",
    lane_profile="cursor_cloud",
    versions={**_CURSOR_VERSIONS, "cloud_api": "v1"},
    controls={**CURSOR_LOCAL_DESCRIBE_V1.controls, "reattach": "native"},
    delivery_semantics=dict(CURSOR_LOCAL_DESCRIBE_V1.delivery_semantics),
    identity=LaneIdentityMap(
        session_ref="agent_id", turn_ref="run_id", effect_ref="call_id", cursor="sse_event_id"
    ),
    # Cloud runs fire no sessionStart, sessionEnd or MCP hooks. The cloud VM cannot reach the
    # worker's loopback callback, so no fail-closed Kernel Hook runs there (catalog command
    # hooks only; the Stop Fence reaches a cloud run through `POST .../cancel`): FT-G6 states
    # it honestly.
    hooks=LaneHooks(
        mechanism="command_hooks",
        events_supported=tuple(
            event for event in _CURSOR_LOCAL_HOOKS if event not in {"session_start", "session_end"}
        ),
        fail_closed=False,
    ),
    instruction_channel=("AGENTS.md", ".cursor/rules/mc-mission.mdc"),
    subagents=LaneSubagents(
        file=".cursor/agents/*.md",
        inline="customSubagents",
        readonly_supported_inline=False,
        fields=derived_file_lane_row(LaneProfile.CURSOR_CLOUD),
    ),
    usage=LaneUsage(tokens="settled_per_turn", cost="estimated_then_settled"),
    placement="cloud",
    qualified=False,
    # Cross-provider control (2026-11-05): the transcript from the SSE frames up to the
    # point plus the run branch tree at the turn's `branch:<branch>@<sha>` head (R2 when the
    # branch publisher is composed, else the messages only); `seed_fork` names that head and
    # stages the hydration transcript for a new cloud agent created on it (R2).
    time_travel=LaneTimeTravel(read="R2", fork="R2"),
)

# --- MP-09: the Cursor profiles as `mc.lane_describe.v2` ----------------------------------------
#
# Controls, delivery and identity are the FT-G1 v1 cells (kept above as `*_V1`, still readable);
# v2 adds per-feature evidence. Implemented cells are `native`/`emulated` with `qualified=False`
# (the convention of every implemented v2 matrix) and cite their offline evidence
# (OVE-55 fixture suites and the MP-09 suites); nothing is qualified until the owner-run drill
# records it. `approval_suspension` has no vendor surface on this pin: cursor-sdk 1.0.37 exposes
# `SDKRequestMessage(request_id)` and no API that answers it, and the cloud run stream carries
# no request event. Cloud agents fire no MCP hooks, so cloud `enforcement_coverage["mcp"]` is
# unsupported. The approval coverage report is `adapters/cursor/qualification.py`.
_CURSOR_SDK_REQUEST: Final = (
    "cursor_sdk==1.0.37 types.py SDKRequestMessage(request_id); no respond API in "
    "_async_run.py/_async_agent.py/_async_client.py"
)
_CURSOR_CLOUD_HOOKS: Final = (
    "../mission-control-general/runtime-facts/CURSOR_SDK_FACTS.md section 7: cloud agents "
    "run command hooks only; no sessionStart/sessionEnd/beforeMCPExecution/afterMCPExecution"
)
_CURSOR_FIXTURES: Final = "tests/unit/harness/test_lane_qualification_fixtures.py"
_CURSOR_HOOK_ROUNDTRIP: Final = "tests/integration/cursor/test_kernel_hook_roundtrip.py"
_CURSOR_HONESTY: Final = "tests/unit/harness/test_describe_honesty.py::request_continuation"
# Patch-based custody and hydrated handover, as the v1 `snapshot`/`fork` cells state them.
_CURSOR_EMULATED: Final = frozenset({"output_custody", "continuation"})


def _cursor_features(*, local: bool) -> dict[str, FeatureEvidence]:
    transport = "cursor-sdk bridge (local)" if local else "Cloud Agents API v1 over httpx"
    os = "Linux|Darwin (WSL 2 on a Windows host)" if local else "any worker host"
    implemented = {
        "launch": True,
        "status": True,
        "observe": True,
        "follow_up": True,
        "cancel": True,
        "usage": True,
        "output_custody": True,
        "environment_selection": True,
        "configuration_materialization": True,
        "approval_suspension": False,
        "subordinate_lineage": local,
        "continuation": True,
    }
    unsupported = set() if local else {"approval_suspension"}
    refs = {
        "approval_suspension": _CURSOR_SDK_REQUEST,
        "subordinate_lineage": _CURSOR_HOOK_ROUNDTRIP if local else _CURSOR_CLOUD_HOOKS,
        "continuation": _CURSOR_HONESTY,
        "usage": (
            "tests/unit/harness/test_cursor_local.py::"
            "test_error_run_fails_and_settles_cost_when_the_provider_reports_it"
            if local
            else "tests/unit/cursor/test_cloud_usage_unknown.py"
        ),
        "observe": (
            "tests/unit/harness/test_cursor_local.py::"
            "test_a_resume_from_a_stored_offset_stores_no_frame_twice"
            if local
            else "tests/unit/cursor/test_cloud_stream_expiry.py"
        ),
        "launch": _CURSOR_FIXTURES
        if local
        else "tests/unit/cursor/test_cloud_capacity_and_busy.py",
        "follow_up": _CURSOR_FIXTURES if local else "tests/unit/cursor/test_cloud_reconcile.py",
        "output_custody": (
            _CURSOR_FIXTURES if local else "tests/unit/cursor/test_cloud_workspace_and_resume.py"
        ),
    }
    cells: dict[str, FeatureEvidence] = {}
    for feature in LANE_FEATURES:
        # The cell's status is how the lane supports it (as the v1 controls state it);
        # `qualified` stays False until the owner-run drill records the profile.
        status: ControlSupport
        if feature in unsupported:
            status = "unsupported"
        elif not implemented[feature]:
            status = "unqualified"
        else:
            status = "emulated" if feature in _CURSOR_EMULATED else "native"
        cells[feature] = FeatureEvidence(
            status=status,
            implemented=implemented[feature] and status != "unsupported",
            account_enabled="unknown",
            qualified=False,
            evidence_ref=refs.get(feature, _CURSOR_FIXTURES),
            transport=transport,
            sdk_language="python",
            sdk_version="1.0.37",
            provider_scope="cursor account bound at launch",
            os=os,
        )
    return cells


CURSOR_LOCAL_DESCRIBE: Final = LaneDescribe.model_validate(
    {
        **CURSOR_LOCAL_DESCRIBE_V1.model_dump(mode="python"),
        "schema_version": LANE_DESCRIBE_SCHEMA_V2,
        "features": _cursor_features(local=True),
        "approval_modes": ("workflow_gate",),
        "compaction_control": "unsupported",  # preCompact is observe-only; no SDK/REST compact
        "subordinate_visibility": "unqualified",
        "enforcement_coverage": {
            "shell": "unqualified",
            "file": "unqualified",
            "mcp": "unqualified",
        },
    }
)
CURSOR_CLOUD_DESCRIBE: Final = LaneDescribe.model_validate(
    {
        **CURSOR_CLOUD_DESCRIBE_V1.model_dump(mode="python"),
        "schema_version": LANE_DESCRIBE_SCHEMA_V2,
        "features": _cursor_features(local=False),
        "approval_modes": ("workflow_gate",),
        "compaction_control": "unsupported",
        "subordinate_visibility": "unqualified",
        "enforcement_coverage": {
            "shell": "unqualified",
            "file": "unqualified",
            "mcp": "unsupported",
        },
    }
)

# What the Cursor profiles declare to the resolution seam (design §§3, 6.1; D11, OC-D199). The
# compile is describe-only until the provider sweep: the cells state what today's launch
# resolver (`application/authoring/manifest_launch_inputs.py::cursor_node`, whose binding kinds
# are `_CURSOR_MANIFEST_KINDS`) and the lane's projection writer do, not what a compile has
# receipted. Evidence per cell:
# - model routes: the deployment pins a Cursor model id (`providers.<profile>.model_profiles`);
#   Cursor serves both vendors' models under its own ids (`GET /v1/models`,
#   `mission-control-general/runtime-facts/CURSOR_SDK_FACTS.md`), so both routes are the
#   Cursor model catalog.
# - skill_bundle, mcp_server, hook_script, subagent_profile: projected (`.cursor/skills`,
#   `.cursor/mcp.json` or inline MCP on cloud, `.cursor/hooks.json`, `.cursor/agents/*.md`).
# - environment_kit: the kit's mission layer runs at `prepare` (MO-12 local, MO-13 cloud).
# - tool, context_bundle, middleware, sandbox_profile: no Cursor launch binding (refused).
# - families: StageGraph and GoalDirected roles launch through `lane.turn`; Parallel Swarm and
#   Evaluator Optimizer are Deep Agents-only program behaviors.
_CURSOR_ITEMS: Final[dict[ConfigurationItemKind, ItemSupport]] = {
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
_CURSOR_FAMILIES: Final[dict[Family, FamilySupport]] = {
    "StageGraph": "native",
    "GoalDirected": "native",
    "ParallelSwarm": "unsupported",
    "EvaluatorOptimizer": "unsupported",
}
_CURSOR_ROUTES: Final = (
    ModelRoute(vendor="anthropic", verdict="native", mechanism="cursor_model_catalog"),
    ModelRoute(vendor="openai", verdict="native", mechanism="cursor_model_catalog"),
)

CURSOR_LOCAL_DECLARATION: Final = LaneDeclaration(
    describe=CURSOR_LOCAL_DESCRIBE,
    model_routes=_CURSOR_ROUTES,
    items=dict(_CURSOR_ITEMS),
    families=dict(_CURSOR_FAMILIES),
)
CURSOR_CLOUD_DECLARATION: Final = LaneDeclaration(
    describe=CURSOR_CLOUD_DESCRIBE,
    model_routes=_CURSOR_ROUTES,
    items=dict(_CURSOR_ITEMS),
    families=dict(_CURSOR_FAMILIES),
)

__all__ = [
    "CURSOR_CLOUD_DECLARATION",
    "CURSOR_CLOUD_DESCRIBE",
    "CURSOR_CLOUD_DESCRIBE_V1",
    "CURSOR_LOCAL_DECLARATION",
    "CURSOR_LOCAL_DESCRIBE",
    "CURSOR_LOCAL_DESCRIBE_V1",
]
