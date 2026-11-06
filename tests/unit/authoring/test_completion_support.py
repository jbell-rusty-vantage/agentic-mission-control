import pytest
from pydantic import ValidationError

from mission_control.application.authoring.completion_support import completion_support_issues
from mission_control.domain.authoring.manifest import Behavior, parse_manifest
from mission_control.domain.authoring.manifest_lowering import lower_mission
from mission_control.domain.authoring.mission_definition import (
    AcceptanceExpression,
    DefinitionOutput,
    manifest_to_definitions,
)
from tests.unit.authoring.test_manifest_schema import minimal


def definition():
    document = minimal()
    return manifest_to_definitions(parse_manifest(document), document)[0]


@pytest.mark.parametrize(
    "expression",
    [
        {"op": "human", "decision": "approved", "schema_ref": "report@1"},
        {"op": "schema", "schema_ref": ""},
        {"op": "assessment", "capability_pointer": "/capability", "threshold": "1.1"},
        {"op": "all", "operands": []},
    ],
)
def test_committed_acceptance_rejects_ambiguous_or_invalid_expression(expression):
    with pytest.raises(ValidationError):
        AcceptanceExpression.model_validate(expression)


@pytest.mark.parametrize(
    "expression",
    [
        AcceptanceExpression(op="schema", schema_ref="report@1"),
        AcceptanceExpression(op="assessment", capability_pointer="/assessment", threshold="0.8"),
        AcceptanceExpression(
            op="any", operands=(AcceptanceExpression(op="human", decision="approved"),)
        ),
    ],
)
def test_unimplemented_acceptance_is_pointed_and_never_treated_as_provider_success(expression):
    authored = definition()
    authored = authored.model_copy(
        update={"criteria": (authored.criteria[0].model_copy(update={"acceptance": expression}),)}
    )
    issue = completion_support_issues(authored)[0]
    assert issue.reason == "completion_evaluator_unavailable"
    assert issue.pointer == "/mission/goals/0/criteria/0/acceptance"


@pytest.mark.parametrize("decision", ["review_accept", "approved"])
def test_goal_loop_human_acceptance_matches_durable_review_action(decision):
    authored = definition()
    expression = AcceptanceExpression(op="human", decision=decision)
    authored = authored.model_copy(
        update={
            "program": authored.program.model_copy(
                update={"behavior": Behavior.GOAL_LOOP, "nodes": (), "completion": expression}
            ),
            "criteria": (authored.criteria[0].model_copy(update={"acceptance": expression}),),
        }
    )
    issues = completion_support_issues(authored)
    assert (issues == ()) is (decision == "review_accept")
    if issues:
        assert len(issues) == 2
        assert issues[0].reason == "completion_evaluator_unavailable"
        assert "this task produces 'review_accept'" in issues[0].message


def test_stagegraph_lowering_preserves_output_schema_and_requiredness():
    authored = definition()
    lowered = lower_mission(authored)
    output = next(
        stage for stage in lowered.blueprint.stages if stage.stage_id == "synthesize"
    ).output_slots[0]
    assert output.output_contract_ref == "claim_table@1"
    assert output.required is True


@pytest.mark.parametrize("required", [True, False])
def test_goal_output_schema_requires_qualified_validation_even_with_human_acceptance(required):
    authored = definition()
    authored = authored.model_copy(
        update={
            "program": authored.program.model_copy(
                update={
                    "behavior": Behavior.GOAL_LOOP,
                    "nodes": (),
                    "outputs": (
                        DefinitionOutput(
                            node_key="root",
                            name="report",
                            schema_ref="report@1",
                            enforcement="required" if required else "optional",
                        ),
                    ),
                }
            ),
            "criteria": (
                authored.criteria[0].model_copy(
                    update={
                        "acceptance": AcceptanceExpression(op="human", decision="review_accept"),
                    }
                ),
            ),
        }
    )
    issues = completion_support_issues(authored)
    if required:
        assert len(issues) == 1
        assert issues[0].reason == "output_schema_validator_unavailable"
        assert issues[0].pointer == "/mission/program/outputs/0/schema"
    else:
        assert issues == ()


@pytest.mark.parametrize("kind", [None, "REVIEW", "APPROVAL"])
@pytest.mark.parametrize("decision", ["review_accept", "approved"])
def test_stage_gate_criteria_and_node_completion_match_actual_task_action(kind, decision):
    authored = definition()
    expression = AcceptanceExpression(op="human", decision=decision)
    gate = authored.program.nodes[-1].model_copy(
        update={
            "behavior": Behavior.HUMAN_GATE,
            "body": {"task": {} if kind is None else {"kind": kind}},
            "outputs": (),
            "depends_on": (),
            "completion": expression,
        }
    )
    authored = authored.model_copy(
        update={
            "program": authored.program.model_copy(update={"nodes": (gate,)}),
            "criteria": (authored.criteria[0].model_copy(update={"acceptance": expression}),),
        }
    )
    issues = completion_support_issues(authored)
    expected = "approved" if kind == "APPROVAL" else "review_accept"
    if decision == expected:
        assert issues == ()
    else:
        assert len(issues) == 2
        assert all(issue.reason == "completion_evaluator_unavailable" for issue in issues)
        assert issues[0].pointer.endswith("/criteria/0/acceptance")
        assert issues[1].pointer.endswith("/completion/acceptance")
