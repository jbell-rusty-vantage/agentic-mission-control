"""OVE-169 L1-06: the Goal Loop verifier's own objective (experiment loop iteration 1).

Live runs E1 11c9369d and E4 consumer 2a6bc6a7: the verifier template carried the executor's
objective line and its D35 ``output_contract_ref`` line, no rubric and no decision procedure,
so the verifier re-read and grepped until the in-turn budget stop. The verifier template now
carries a verifier objective derived from the authored goal: the subject (the executor's
declared outputs and where they arrive), the inputs the executor received, what it cannot read,
a rubric from the goal's criteria and objectives, a decision procedure that ends at one verdict,
and the exact ``GoalVerifierObservation`` fields the convergence policy reads. The executor's
procedure (the goal text, which the packet still carries as the specification) is not in the
verifier's template segments; the executor template is unchanged.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, cast

import pytest

from mission_control.adapters.deep_agents.knowledge_tools import (
    knowledge_launch_bindings,
    knowledge_registry_tools,
    knowledge_tools,
)
from mission_control.domain.authoring.mission_definition import MissionDefinition
from mission_control.domain.execution.contracts import OperationExecutionRequest, PromptTrustClass
from tests.fixtures.mission_control_common_db import canonical_scope
from tests.unit.authoring.manifest_launch_fixture import fixture_bindings, fixture_served
from tests.unit.authoring.test_experiment_loop_fixtures import rendered
from tests.unit.authoring.test_manifest_launch_inputs import admitted, compile_programs, resolver

E1 = "e1-goal-loop-report.mission.yml"
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


def procedure_lines(definition: MissionDefinition) -> list[str]:
    """The executor's authored procedure: every non-empty line of the goal text."""

    return [line.strip() for line in definition.goals[0].description.splitlines() if line.strip()]


@pytest.mark.asyncio
async def test_e1_verifier_prompt_has_rubric_procedure_verdict_not_executor_steps() -> None:
    definition, blueprint, templates = await loop_templates(E1)
    verifier = text_of(templates["verifier"])

    # Role framing: the verifier judges; it never performs the executor's work.
    assert "Goal Loop verifier" in verifier
    assert "independent verifier" in verifier
    assert "never perform the executor's work" in verifier
    # Subject: the executor's declared outputs, with the plan-borne subject bindings.
    assert "## Subject" in verifier
    for name in ("report", "progress_note", "summary", "caveats"):
        assert f"- {name} (" in verifier
    assert "binding subject-root-report" in verifier
    assert "binding subject-root-progress-note" in verifier
    # Inputs: E1 has no program or chain inputs, and says so.
    assert "## Inputs the executor received" in verifier
    assert "None: this goal has no program or chain inputs" in verifier
    assert "## What you cannot read" in verifier
    assert "missionctl" in verifier  # names the unreachable fetch commands
    # Rubric from the authored criteria and objectives.
    assert "## Rubric" in verifier
    criterion = definition.criteria[0]
    assert f"criterion {criterion.key}: {criterion.description}" in verifier
    assert "Evidence: report, progress_note" in verifier
    assert "human review_accept" in verifier
    objective = definition.objectives[0]
    assert f"objective {objective.key}: {objective.description}" in verifier
    assert "knowledge.report.assess@1" in verifier  # the host-run requirement, named
    # Decision procedure that ends at one verdict.
    assert "## Decision procedure" in verifier
    assert "do not re-verify" in verifier
    # The verdict contract the reconciler and the convergence policy read.
    assert "## Verdict: GoalVerifierObservation" in verifier
    assert "belllabs.goal-verifier-observation.v1" in verifier
    (obligation,) = sorted(blueprint.required_obligation_refs)
    assert f'accepted_obligation_refs: on accepted exactly ["{obligation}"]' in verifier
    contracts = ", ".join(sorted(blueprint.required_output_contracts))
    assert f"output_contract_ref: exactly one of {contracts}" in verifier
    assert "else output:report" in verifier
    # The run budget the turn is held to.
    assert "tool.calls.total 30" in verifier and "tokens.total 400000" in verifier
    # The executor's procedure and its output instructions are absent.
    for line in procedure_lines(definition):
        assert line not in verifier, line
    assert "report_register" not in verifier
    assert "submit_output" not in verifier
    assert "Return output_refs" not in verifier
    assert "(not the objective reference above)" not in verifier
    # Admitted input, not a privileged segment (no published Prompt source; trust model kept).
    assert all(
        segment.trust_class == PromptTrustClass.ADMITTED_INPUT
        for segment in templates["verifier"].prompt_segments
    )


@pytest.mark.asyncio
async def test_e1_executor_objective_is_unchanged() -> None:
    _definition, blueprint, templates = await loop_templates(E1)
    executor = text_of(templates["executor"])
    assert executor.startswith(
        "Mission e1-goal-loop-report Goal Loop executor: "
        "manifest:e1-goal-loop-report:objective:model_facts_report\n"
        "Set output_contract_ref to exactly one of: "
        + ", ".join(sorted(blueprint.required_output_contracts))
        + " (not the objective reference above)."
    )
    assert "## Rubric" not in executor and "## Verdict" not in executor


@pytest.mark.asyncio
async def test_e4_consumer_verifier_names_the_chain_input_it_receives() -> None:
    definition, blueprint, templates = await loop_templates(E4, index=1)
    assert definition.mission_key == "e4-brief"
    verifier = text_of(templates["verifier"])

    assert "## Inputs the executor received" in verifier
    assert (
        "- evidence_map: chain supply from e4-evidence.evidence_map, delivered to you read-only"
        in verifier
    )
    assert "binding subject-root-brief" in verifier
    criterion = definition.criteria[0]
    assert f"criterion {criterion.key}: {criterion.description}" in verifier
    assert "Evidence: brief, progress_note" in verifier
    assert 'accepted_obligation_refs: on accepted exactly ["brief"]' in verifier
    assert "output_contract_ref: exactly one of output:brief, output:progress_note" in verifier
    assert "tool.calls.total 16" in verifier
    for line in procedure_lines(definition):
        assert line not in verifier, line
    assert "submit_output" not in verifier
    assert sorted(blueprint.required_obligation_refs) == ["brief"]
