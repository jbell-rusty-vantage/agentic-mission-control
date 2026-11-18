"""Builders, constants and fakes that other test files import.

Moved from tests/unit/authoring/test_goal_verifier_objective.py.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, cast

from mission_control.adapters.deep_agents.knowledge_tools import (
    knowledge_launch_bindings,
    knowledge_registry_tools,
    knowledge_tools,
)
from mission_control.domain.authoring.mission_definition import MissionDefinition
from mission_control.domain.execution.contracts import OperationExecutionRequest
from tests.support.ids import canonical_scope
from tests.support.manifests.experiment_loop import rendered
from tests.support.manifests.launch_inputs import admitted, compile_programs, resolver
from tests.unit.authoring.manifest_launch_fixture import fixture_bindings, fixture_served

E4 = "e4-linked-chain.mission.yml"


async def loop_templates(
    name: str, index: int = 0
) -> tuple[MissionDefinition, Any, dict[str, OperationExecutionRequest]]:
    """The production Goal Loop templates of one experiment-loop mission (no provider)."""

    scope = canonical_scope("tenant-1", "ai-engineer")
    definitions, programs = await compile_programs(rendered(name), scope=scope)
    definition, program = definitions[index], programs[index]
    pins = {
        item.resolved.capability_id: item.resolved.digest
        for item in definition.capabilities
        if item.resolved is not None and item.resolved.digest is not None
    }
    tools = knowledge_tools(cast(Any, None))
    bindings = fixture_bindings(
        model_profiles=("producer.default", "producer.fallback")
    ).model_copy(update={"capabilities": knowledge_launch_bindings(pins, tools)})
    served = fixture_served(bindings)
    served = replace(served, tools=served.tools | frozenset(knowledge_registry_tools(tools)))
    launch = admitted(program, scope=scope)
    templates = resolver(bindings, served=served).goal_templates(definition, launch)
    return definition, launch.blueprint, templates


def text_of(template: OperationExecutionRequest) -> str:
    return "\n".join(segment.content for segment in template.prompt_segments)
