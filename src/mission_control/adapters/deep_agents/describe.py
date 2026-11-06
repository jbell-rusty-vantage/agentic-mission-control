"""The Deep Agents lane's declared describe matrix and declaration (ADR-0063, OC-R3).

The lane package owns its matrix (`application/execution/harness/describe.py` aggregates
the lane packages' modules). Pure data: this module imports only domain types, so the
aggregator may read it (`tests/architecture/test_package_boundaries.py`).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from mission_control.adapters.deep_agents.routes import DEEP_AGENTS_MODEL_ROUTES
from mission_control.domain.execution.lanes import (
    LaneDescribe,
    LaneHooks,
    LaneIdentityMap,
    LaneSubagents,
    LaneTimeTravel,
    LaneUsage,
    SubagentFieldVerdict,
)
from mission_control.domain.execution.subagent_support import complete_row
from mission_control.domain.resolution.profiles import LaneDeclaration

# The Deep Agents lane's row of the per-lane subagent support matrix (SUBAGENT_FIELDS
# vocabulary). It lives beside the lane's describe matrix, which is its one reader; the lane
# adapter re-exports it (`adapters/deep_agents/lane.py::SUBAGENT_FIELDS`).
DEEP_AGENTS_SUBAGENT_FIELDS: Final[Mapping[str, SubagentFieldVerdict]] = {
    "kind.sync": "native",
    "kind.async": "native",
    "kind.linked_run": "unsupported",
    "capabilities.inherit": "native",
    "capabilities.seeded": "native",
    "seeds.skills": "native",
    "seeds.mcp_servers": "native",
    "seeds.plugins": "degraded",
    "seeds.tools": "native",
    "model": "native",
    "tools": "native",
    "skills": "native",
    "mcp_servers": "native",
    "readonly": "degraded",
    "background": "degraded",
    "context_mode.fork": "degraded",
    "interrupt_on": "degraded",
    "max_turns": "degraded",
    "sandbox.own": "degraded",
    "sandbox.none": "degraded",
    "budget": "native",
    "placement.in_process": "native",
    "placement.agent_server": "native",
    "placement.lane": "unsupported",
}


DEEP_AGENTS_DESCRIBE: Final = LaneDescribe(
    lane="deep_agents",
    lane_profile="deep_agents",
    versions={"deepagents": "0.7.5", "langgraph": "1.2.10"},
    controls={
        "prepare": "native",
        "start": "native",
        "reattach": "native",
        "send_turn": "native",
        "cancel_turn": "native",
        "observe": "native",
        "snapshot": "emulated",
        "usage": "native",
        "end_session": "native",
        "pause": "native",
        "fork": "emulated",
    },
    delivery_semantics={
        "queue_instruction": "turn_boundary_guaranteed",
        "interrupt_and_inject": "cooperative_inject",
        "pause": "pause_at_tool_gate",
        "hard_pause": "unsupported",
        "resume": "turn_boundary_guaranteed",
        "cancel": "turn_boundary_guaranteed",
        "fork": "emulated",
        "request_continuation": "emulated",
    },
    identity=LaneIdentityMap(
        session_ref="thread_id",
        turn_ref="checkpoint_id",
        effect_ref="tool_call_id",
        cursor="checkpoint_id",
    ),
    hooks=LaneHooks(
        mechanism="middleware",
        events_supported=(
            "session_start",
            "before_model",
            "after_model",
            "before_tool",
            "after_tool",
            "after_tool_failure",
            "before_compaction",
            "stop",
            "session_end",
        ),
        fail_closed=True,
    ),
    instruction_channel=("system_prompt",),
    subagents=LaneSubagents(
        file=None,
        inline="SubAgent",
        readonly_supported_inline=False,
        # P1 subagents: the lane's own row (`DEEP_AGENTS_SUBAGENT_FIELDS` above).
        fields=complete_row("deep_agents", DEEP_AGENTS_SUBAGENT_FIELDS),
    ),
    usage=LaneUsage(tokens="settled_per_turn", cost="estimated"),
    placement="worker_hosted",
    # P1 turn 4: `read_as_of` folds the saver's state at any stamped root checkpoint and
    # `seed_fork` copies the thread and branches in the copy (`adapters/deep_agents/time_travel`).
    time_travel=LaneTimeTravel(read="R3", fork="R3"),
    # The first lane: qualified by the Deep Agents acceptance suite (WP-CP-040, parity).
    qualified=True,
)


# What this lane declares (design §§3, 8; D10). Evidence per cell:
# - model routes: both vendors in-process (`routes.DEEP_AGENTS_MODEL_ROUTES`, built by
#   `materializer.ExactModelFactory` from the resolved pin's vendor)
#   (`AnthropicExactModelFactory` -> ChatAnthropic, `OpenAIExactModelFactory` -> ChatOpenAI).
# - skill_bundle, mcp_server, tool: mapped to exact `capabilities` components below and
#   materialized by `ExactDeepAgentMaterializer` (Skills middleware, in-process MCP client,
#   in-process tools).
# - subagent_profile: `lane.DeepAgentsLaneAdapter` (inherit, seeded and async children).
# - sandbox_profile: `sandbox_profiles` components (LangSmith, Docker, State backends).
# - middleware: `DeepAgentMiddlewareComponent` on the scaffold profile, run in order by the
#   materializer; an item resolves when the scaffold serves that exact component.
# - hook_script: the binding and the materializer carry catalog hook scripts
#   (`DeepAgentExecutionBinding.hook_scripts`), but no launch binding serves them, so a
#   selected hook script is refused at launch: unsupported at compile until one does.
# - context_bundle: no launch binding (a pinned context bundle has always been refused here).
# - environment_kit: Deep Agents runs no Environment Kit bootstrap (design D10).
# - families: StageGraph and GoalDirected run under `operation.execute`; ParallelSwarm and
#   EvaluatorOptimizer are specified, not implemented.
DEEP_AGENTS_DECLARATION: Final = LaneDeclaration(
    describe=DEEP_AGENTS_DESCRIBE,
    model_routes=DEEP_AGENTS_MODEL_ROUTES,
    items={
        "skill_bundle": "native",
        "mcp_server": "native",
        "tool": "native",
        "hook_script": "unsupported",
        "subagent_profile": "native",
        "environment_kit": "unsupported",
        "context_bundle": "unsupported",
        "middleware": "native",
        "sandbox_profile": "native",
    },
    families={
        "StageGraph": "native",
        "GoalDirected": "native",
        "ParallelSwarm": "unqualified",
        "EvaluatorOptimizer": "unqualified",
    },
    # The runtime pins the lane is built and qualified on (pyproject, the describe versions).
    pins=dict(DEEP_AGENTS_DESCRIBE.versions),
)

__all__ = ["DEEP_AGENTS_DECLARATION", "DEEP_AGENTS_DESCRIBE", "DEEP_AGENTS_SUBAGENT_FIELDS"]
