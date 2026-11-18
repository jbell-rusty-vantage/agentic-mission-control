"""Builders, constants and fakes that other test files import.

Moved from tests/unit/resolution/test_resolution_types.py.
"""

from __future__ import annotations

from mission_control.domain.resolution.configuration import AgentConfiguration
from mission_control.domain.resolution.resolved import ResolvedRuntime
from mission_control.domain.resolution.selection import RuntimeSelection
from tests.conformance.lanes.compile.fixtures import canonical_agent
from tests.conformance.lanes.compile.stub import StubLaneAdapter
from tests.conformance.resolution.fixtures import AI_ENGINEER


def _selection(agent: AgentConfiguration) -> RuntimeSelection:
    return RuntimeSelection(
        lane_profile=agent.lane_profile,
        model_profile=agent.model.profile,
        family="GoalDirected",
        node_role="executor",
        application_id="ai-engineer",
        agent=agent,
    )


def _runtime(**overrides: object) -> ResolvedRuntime:
    agent = canonical_agent("deep_agents")
    binding, receipt = StubLaneAdapter().compile(agent, {})
    fields: dict[str, object] = {
        "selection_digest": _selection(agent).digest(),
        "agent": agent,
        "lane_binding": binding,
        "knowledge": AI_ENGINEER.knowledge,
        "outputs": AI_ENGINEER.outputs,
        "transfer": AI_ENGINEER.transfer,
        "receipt": receipt,
        "application_revision": AI_ENGINEER.revision,
    }
    return ResolvedRuntime.create(**{**fields, **overrides})
