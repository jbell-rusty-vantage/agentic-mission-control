"""Builders, constants and fakes that other test files import.

Moved from tests/conformance/resolution/test_resolver_conformance.py.
"""

from __future__ import annotations

from typing import Any

from mission_control.application.resolution.ports import LaneRegistration
from mission_control.application.resolution.registries import DescribeOnlyLane
from mission_control.domain.resolution.configuration import Family, Vendor
from mission_control.domain.resolution.profiles import LaneDeclaration
from mission_control.domain.resolution.selection import RuntimeSelection
from tests.conformance.lanes.compile.fixtures import canonical_agent
from tests.conformance.lanes.compile.stub import StubLaneAdapter


def _registration(declaration: LaneDeclaration, **adapter: Any) -> LaneRegistration:
    return LaneRegistration(
        profile=declaration.lane_profile,
        declaration=declaration,
        adapter=StubLaneAdapter(declaration, **adapter),
        harness_factory=lambda _deps: DescribeOnlyLane(declaration.describe),
    )


def _selection(
    lane: str = "deep_agents",
    *,
    vendor: Vendor = "anthropic",
    family: Family = "GoalDirected",
    application: str = "ai-engineer",
    model_profile: str | None = None,
    required: frozenset[str] = frozenset(),
    lane_options: dict[str, Any] | None = None,
    data_class: str = "internal",
) -> RuntimeSelection:
    agent = canonical_agent(lane, vendor=vendor, required=required)
    if data_class != agent.data_class:
        agent = type(agent).create(
            **{
                **{k: getattr(agent, k) for k in ("lane_profile", "node_ref", "instructions_ref")},
                "model": agent.model,
                "items": agent.items,
                "budgets": agent.budgets,
                "data_class": data_class,
                "data_class_source": agent.data_class_source,
            }
        )
    if model_profile is not None:
        agent = type(agent).create(
            lane_profile=agent.lane_profile,
            node_ref=agent.node_ref,
            instructions_ref=agent.instructions_ref,
            model=agent.model.model_copy(update={"profile": model_profile}),
            items=agent.items,
            budgets=agent.budgets,
            data_class=agent.data_class,
            data_class_source=agent.data_class_source,
        )
    return RuntimeSelection(
        lane_profile=lane,
        model_profile=agent.model.profile,
        family=family,
        node_role="executor",
        application_id=application,
        agent=agent,
        lane_options=lane_options or {},
    )
