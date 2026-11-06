"""W1 criterion-selected assessment and exact later-iteration transfer, without providers."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from mission_control.adapters.deep_agents.knowledge_tools import (
    knowledge_launch_bindings,
    knowledge_registry_tools,
    knowledge_tools,
)
from mission_control.application.authoring.manifest_launch_inputs import _goal_assessment_subjects
from mission_control.application.programs.goal_directed import _iteration_transfer
from mission_control.domain.authoring.manifest import parse_manifest_yaml
from mission_control.domain.authoring.mission_definition import manifest_to_definitions
from tests.fixtures.mission_control_common_db import canonical_scope
from tests.unit.authoring.manifest_launch_fixture import fixture_bindings, fixture_served
from tests.unit.authoring.test_manifest_launch_inputs import admitted, compile_programs, resolver

ROOT = Path(__file__).resolve().parents[3]


def source(app: str, variant: str = "native-write") -> str:
    return (
        (ROOT / f"tests/fixtures/manifests/sprint-oc-w1/{app}.{variant}.mission.yml")
        .read_text(encoding="utf-8")
        .replace("__PACK__", "{}")
        .replace("__PRODUCER__", "producer.default")
    )


async def launch_templates(text: str, app: str):
    scope = canonical_scope("tenant-1", app)
    definitions, programs = await compile_programs(text, scope=scope)
    definition, program = definitions[0], programs[0]
    pins = {
        item.resolved.capability_id: item.resolved.digest
        for item in definition.capabilities
        if item.resolved is not None
    }
    tools = knowledge_tools(cast(Any, None))
    bindings = fixture_bindings(
        model_profiles=("producer.default", "producer.fallback")
    ).model_copy(update={"capabilities": knowledge_launch_bindings(pins, tools)})
    served = fixture_served(bindings)
    served = replace(served, tools=served.tools | frozenset(knowledge_registry_tools(tools)))
    templates = resolver(bindings, served=served).goal_templates(
        definition, admitted(program, scope=scope)
    )
    return definition, program, templates


@pytest.mark.asyncio
@pytest.mark.parametrize("app", ["ai-engineer", "biotech"])
@pytest.mark.parametrize("variant", ["report", "native-write"])
async def test_actual_w1_launch_nominates_criterion_evidence_and_keeps_later_outputs(app, variant):
    definition, program, templates = await launch_templates(source(app, variant), app)
    judge = templates["verifier"].transfer
    assert judge is not None
    assert [item.source.output_key for item in judge.inputs] == [
        "root.report",
        "root.progress_note",
    ]
    assert all(item.required for item in judge.inputs)
    assert judge.isolation == "independent_evaluator"
    first = _iteration_transfer(
        templates["executor"], SimpleNamespace(operation_role="executor", goal_iteration=1)
    )
    assert first is not None and not first.inputs
    later = _iteration_transfer(
        templates["executor"], SimpleNamespace(operation_role="executor", goal_iteration=2)
    )
    assert later is not None
    predecessors = [item for item in later.inputs if item.purpose == "dependent_input"]
    assert {item.source.output_key for item in predecessors} == {
        output.key for output in definition.program.outputs
    }
    assert all(item.producer_operation == "goal-iteration/1/executor" for item in predecessors)
    assert later.inputs[-1].source.binding_pin == "mc.current-set@1"
    assert later.inputs[-1].required
    if variant == "native-write":
        receipt = next(o for o in definition.program.outputs if o.name == "native_receipt")
        assert receipt.required
        assert admitted(program).blueprint.max_iterations >= 2


def test_full_output_keys_and_explicit_optional_nomination_remain_strict():
    manifest, document = parse_manifest_yaml(source("ai-engineer"))
    definition = manifest_to_definitions(manifest, document)[0]
    criterion = definition.criteria[0].model_copy(
        update={"evidence": ("root.report", "root.caveats")}
    )
    definition = definition.model_copy(update={"criteria": (criterion,)})
    assert _goal_assessment_subjects(definition) == (
        ("root", "root.report"),
        ("root", "root.caveats"),
    )


def test_legacy_external_evidence_does_not_make_optional_outputs_required_subjects():
    manifest, document = parse_manifest_yaml(source("ai-engineer"))
    definition = manifest_to_definitions(manifest, document)[0]
    criterion = definition.criteria[0].model_copy(update={"evidence": ("artifact:external",)})
    definition = definition.model_copy(update={"criteria": (criterion,)})
    assert _goal_assessment_subjects(definition) == (
        ("root", "root.report"),
        ("root", "root.progress_note"),
        ("root", "root.native_receipt"),
    )


@pytest.mark.asyncio
async def test_only_optional_outputs_with_external_evidence_keep_an_isolated_verifier():
    text = source("ai-engineer", "report").replace("enforcement: required", "enforcement: optional")
    text = text.replace("evidence: [report, progress_note]", "evidence: [artifact:external@1]")
    definition, _, templates = await launch_templates(text, "ai-engineer")
    assert _goal_assessment_subjects(definition) == ()
    selection = templates["verifier"].transfer
    assert selection is not None
    assert selection.isolation == "independent_evaluator"
    assert selection.inputs == ()
    # Explicit optional evidence still becomes a strict nominated subject.
    text = text.replace("evidence: [artifact:external@1]", "evidence: [caveats]")
    _, _, nominated = await launch_templates(text, "ai-engineer")
    (subject,) = nominated["verifier"].transfer.inputs
    assert subject.source.output_key == "root.caveats" and subject.required
