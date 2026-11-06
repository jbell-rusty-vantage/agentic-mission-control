"""The `codex_agents` lane's declared describe matrix and declaration (ADR-0050, OC-R3).

The OpenAI Agents API running the Codex harness. The lane package owns its matrix;
`application/execution/harness/describe.py` aggregates. Pure data: domain imports only.
"""

from __future__ import annotations

from typing import Final

from mission_control.domain.execution.lanes import (
    LANE_CONTROLS,
    LANE_DESCRIBE_SCHEMA_V2,
    FeatureEvidence,
    LaneDescribe,
    LaneHooks,
    LaneIdentityMap,
    LaneSubagents,
    LaneTimeTravel,
    LaneUsage,
    unqualified_features,
)
from mission_control.domain.execution.subagent_support import unsupported_row
from mission_control.domain.resolution.profiles import LaneDeclaration, ModelRoute

_UNQUALIFIED_CONTROLS: Final = dict.fromkeys(LANE_CONTROLS, "unqualified")

# OpenAI Agents API with the closed Codex harness (openai 3.29.0, model `gpt-6-luna` accepted):
# a message sent during a turn steers it (HL-23), sends are status-gated otherwise, cancel is
# `agent.session.input.cancel`, and only Mission Control function tools raise
# `required_actions`: per-command approval of the built-in shell and file tools is unsupported
# (missions needing it resolve to the `codex` lane).
_AGENTS_NATIVE: Final = FeatureEvidence(
    status="native",
    implemented=True,
    account_enabled="unknown",
    qualified=False,
    evidence_ref="tests/unit/openai_agents/test_harness.py",
    transport="https+sse (httpx)",
    sdk_language="python",
    sdk_version="openai 3.29.0 wire shapes",
    provider_scope="openai:agents:openai_hosted",
)

CODEX_AGENTS_DESCRIBE: Final = LaneDescribe(
    schema_version=LANE_DESCRIBE_SCHEMA_V2,
    lane="codex",
    lane_profile="codex_agents",
    versions={"openai_sdk": "3.29.0", "agents_api": "beta"},
    controls={
        **_UNQUALIFIED_CONTROLS,
        **dict.fromkeys(
            (
                "prepare",
                "start",
                "reattach",
                "send_turn",
                "cancel_turn",
                "observe",
                "usage",
                "end_session",
            ),
            "native",
        ),
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
        session_ref="session_id", turn_ref="turn_id", effect_ref="call_id", cursor="item_id"
    ),
    hooks=LaneHooks(mechanism="none", fail_closed=False),
    instruction_channel=("instructions", "AGENTS.md"),
    subagents=LaneSubagents(
        file=None, inline=None, readonly_supported_inline=False, fields=unsupported_row()
    ),
    usage=LaneUsage(tokens="settled_per_turn", cost="unknown"),
    placement="cloud",
    qualified=False,
    features={
        **unqualified_features(),
        **dict.fromkeys(
            (
                "launch",
                "status",
                "observe",
                "follow_up",
                "cancel",
                "usage",
                "configuration_materialization",
            ),
            _AGENTS_NATIVE,
        ),
        "output_custody": _AGENTS_NATIVE.model_copy(
            update={
                "status": "emulated",
                "evidence_ref": "tests/unit/openai_agents/test_tools.py",
            }
        ),
        "approval_suspension": _AGENTS_NATIVE.model_copy(
            update={
                "status": "emulated",
                "evidence_ref": "tests/unit/openai_agents/test_tools.py",
            }
        ),
    },
    approval_modes=("workflow_gate", "governed_effect"),
    compaction_control="unqualified",
    subordinate_visibility="unqualified",
    enforcement_coverage={"shell": "unsupported", "file": "unsupported", "mcp": "unqualified"},
    # Cross-provider control (2026-11-05): `thread_item` points per step from the persisted
    # items (`cognition_points.py`); `read_as_of` and `seed_fork` at R1 over the same frames
    # (`time_travel.py`): the Agents API has no session fork or checkpoint restore (OA-D4),
    # so a fork is a new session seeded by a hydration prompt. `fork` stays `emulated`;
    # `interrupt_and_inject` stays `cancel_and_replace` although `steer` exists on the
    # harness: native input has no expected-turn compare-and-swap (OA-D5) and the
    # conformance suite proves only cancel-and-replace (`SteeringLane` is implemented,
    # not declared).
    time_travel=LaneTimeTravel(read="R1", fork="R1"),
)

# What `codex_agents` declares to the resolution seam (design §§3, 6.1, 9.3; D11, OC-D199). The
# compile is describe-only until the provider sweep: the cells state what today's launch
# resolver (`manifest_launch_inputs.py::provider_node`, hosted placement) and the lane's
# projection writer (the hosted agent API target) do. Evidence per cell:
# - model routes: the Agents API runs OpenAI models (the deployment's
#   model pins).
# - skill_bundle: uploaded as API skills (`send_options["hosted_skills"]`, `pack.py`).
# - mcp_server: streamable HTTPS servers only (others are reported degraded and skipped).
# - hook_script, subagent_profile: no trusted executor for catalog hooks or subagent programs
#   on a hosted API (reported and skipped); environment_kit, tool, context_bundle, middleware,
#   sandbox_profile: no launch binding.
# - families: StageGraph and GoalDirected launch through `lane.turn` (hosted placement).
# Why a v2 manifest naming this profile compiles with a launch-refused warning (ADR-0050).
CODEX_AGENTS_LAUNCH_NOTE: Final = "HL-11 to HL-13"

CODEX_AGENTS_DECLARATION: Final = LaneDeclaration(
    describe=CODEX_AGENTS_DESCRIBE,
    model_routes=(
        ModelRoute(vendor="anthropic", verdict="unsupported", mechanism="none"),
        ModelRoute(vendor="openai", verdict="native", mechanism="agents_api_session"),
    ),
    items={
        "skill_bundle": "native",
        "mcp_server": "native",
        "tool": "unsupported",
        "hook_script": "unsupported",
        "subagent_profile": "unsupported",
        "environment_kit": "unsupported",
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
    # The exact versions a deployment must pin (`providers.codex_agents.pins`).
    pins={"sdk.openai": "3.29.0", "beta.agents": "agents=v1"},
)

__all__ = ["CODEX_AGENTS_DECLARATION", "CODEX_AGENTS_DESCRIBE", "CODEX_AGENTS_LAUNCH_NOTE"]
