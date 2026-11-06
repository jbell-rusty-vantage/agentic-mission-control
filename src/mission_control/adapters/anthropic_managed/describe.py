"""The `claude_managed` lane's declared describe matrix and declaration (ADR-0050, OC-R3).

Anthropic Managed Agents, the API-billed hosted agent API. The lane package owns its matrix;
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

# --- ADR-0050: the API-billed hosted agent APIs --------------------------------------------------
#
# SPEC-06 section 9 (the `cloud` and `openai_hosted` tool placements; `self_hosted` is
# funding-gated and has no matrix yet) and the HL-23 provider smoke
# (docs/specs/archive/materialization-observation-2026-10/research/provider-smoke-2026-10.md).
# A lane
# that cannot pause mid-run holds `pause` at `unsupported` (the workflow then pauses at the run
# boundary only); HL-12 flips the Agents API to its function-tool gate.

_MANAGED_NATIVE: Final = FeatureEvidence(
    status="native",
    implemented=True,
    account_enabled="unknown",
    qualified=False,
    evidence_ref="tests/unit/anthropic_managed/test_harness.py",
    transport="https+sse (httpx)",
    sdk_language="python",
    sdk_version="anthropic 1.13.0 wire shapes",
    provider_scope="anthropic:managed_agents:cloud",
)


# Anthropic Managed Agents (anthropic 1.13.0, beta `managed-agents-2026-04-01`): Anthropic runs
# the loop and the tools; a `user.message` sent while running is consumed at the next model
# request of the current turn (Q-M1), `user.interrupt` ends the turn after the in-flight model
# request, and `session.usage` with `list_cost` precedes every idle. No hook file runs there:
# Kernel Hooks become Mission Control custom tools. HL-08 implements the session lifecycle
# (`adapters/anthropic_managed/harness.py`): prepare from the pack, a budgeted session, sends
# gated on idle, the stream-then-history observe, native reattach, interrupt, usage settled from
# `list_cost`, and end as interrupt, archive, then deletion after retention. Opt-in managed
# budget controls are wired through BudgetControlService and the StageGraph/GoalDirected
# callers; native boundary/resume enforcement still needs the HL-24 drill. Legacy pause
# remains unsupported. The declarations below distinguish implemented emulation and
# unqualified native controls; this wiring does not qualify the hosted lane.
CLAUDE_MANAGED_DESCRIBE: Final = LaneDescribe(
    schema_version=LANE_DESCRIBE_SCHEMA_V2,
    lane="claude",
    lane_profile="claude_managed",
    versions={
        "anthropic_sdk": "1.13.0",
        "managed_agents_beta": "managed-agents-2026-04-01",
        "agent_toolset": "agent_toolset_20260401",
    },
    controls={
        **_UNQUALIFIED_CONTROLS,
        "prepare": "native",
        "start": "native",
        "reattach": "native",
        "send_turn": "native",
        "cancel_turn": "native",
        "observe": "native",
        "usage": "native",
        "end_session": "native",
    },
    delivery_semantics={
        # A send while running steers the current turn (Q-M1), so a next-turn queue waits
        # for idle; `[user.interrupt, user.message]` is the documented cancel-and-replace.
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
        session_ref="session_id",
        turn_ref="user_message_event_id",
        effect_ref="tool_use_event_id",
        cursor="event_processed_at_and_id",
    ),
    hooks=LaneHooks(mechanism="none", fail_closed=False),
    instruction_channel=("agent.system", "skills"),
    subagents=LaneSubagents(
        file=None, inline=None, readonly_supported_inline=False, fields=unsupported_row()
    ),
    usage=LaneUsage(tokens="settled", cost="settled"),
    placement="cloud",
    qualified=False,
    features={
        **unqualified_features(),
        "launch": _MANAGED_NATIVE,
        "status": _MANAGED_NATIVE,
        "observe": _MANAGED_NATIVE,
        "follow_up": _MANAGED_NATIVE,
        "cancel": _MANAGED_NATIVE,
        "usage": _MANAGED_NATIVE,
        "configuration_materialization": _MANAGED_NATIVE,
        "output_custody": _MANAGED_NATIVE.model_copy(
            update={
                "status": "emulated",
                "evidence_ref": "tests/unit/effects/test_hosted_bundle_publication.py",
            }
        ),
        "approval_suspension": _MANAGED_NATIVE.model_copy(
            update={
                "status": "emulated",
                "evidence_ref": "tests/unit/anthropic_managed/test_tools.py",
            }
        ),
    },
    approval_modes=("workflow_gate", "provider_permission", "governed_effect"),
    compaction_control="unqualified",
    subordinate_visibility="unqualified",
    enforcement_coverage={"shell": "unqualified", "file": "unqualified", "mcp": "unqualified"},
    # Cross-provider control (2026-11-05): `session_cursor` points per step from the
    # persisted events (`cognition_points.py`); `read_as_of` and `seed_fork` at R1 over the
    # same frames (`time_travel.py`): Managed Agents forks no session and imports no
    # history, so a fork is a new session seeded by a hydration prompt. `fork` stays
    # `emulated` in the delivery semantics; `interrupt_and_inject` stays `cancel_and_replace`
    # although `steer` exists on the harness: Q-M1 steering is HL-24-unqualified and the
    # conformance suite proves only cancel-and-replace (`SteeringLane` is implemented,
    # not declared).
    time_travel=LaneTimeTravel(read="R1", fork="R1"),
)

# What `claude_managed` declares to the resolution seam (design §§3, 6.1, 9.3; D11, OC-D199).
# The compile is describe-only until the provider sweep: the cells state what today's launch
# resolver (`manifest_launch_inputs.py::provider_node`, hosted placement) and the lane's
# projection writer (the hosted agent API target) do. Evidence per cell:
# - model routes: Managed Agents run Anthropic models (the deployment's
#   model pins).
# - skill_bundle: uploaded as API skills (`send_options["hosted_skills"]`, `pack.py`).
# - mcp_server: streamable HTTPS servers only (others are reported degraded and skipped).
# - hook_script, subagent_profile: no trusted executor for catalog hooks or subagent programs
#   on a hosted API (reported and skipped); environment_kit, tool, context_bundle, middleware,
#   sandbox_profile: no launch binding.
# - families: StageGraph and GoalDirected launch through `lane.turn` (hosted placement), with
#   the opt-in managed budget controls.
# Why a v2 manifest naming this profile compiles with a launch-refused warning (ADR-0050).
CLAUDE_MANAGED_LAUNCH_NOTE: Final = "HL-07 to HL-09"

CLAUDE_MANAGED_DECLARATION: Final = LaneDeclaration(
    describe=CLAUDE_MANAGED_DESCRIBE,
    model_routes=(
        ModelRoute(vendor="anthropic", verdict="native", mechanism="managed_agents_session_api"),
        ModelRoute(vendor="openai", verdict="unsupported", mechanism="none"),
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
    # The exact versions a deployment must pin (`providers.claude_managed.pins`).
    pins={"sdk.anthropic": "1.13.0", "beta.managed_agents": "managed-agents-2026-04-01"},
)

__all__ = ["CLAUDE_MANAGED_DECLARATION", "CLAUDE_MANAGED_DESCRIBE", "CLAUDE_MANAGED_LAUNCH_NOTE"]
