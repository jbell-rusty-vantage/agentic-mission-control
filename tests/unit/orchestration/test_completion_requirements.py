from dataclasses import replace

import pytest

from mission_control.domain.authoring.contracts import StageOutputSlot
from mission_control.domain.authoring.stagegraph_builder import (
    StageGraphStageSpec,
    build_stagegraph_v2,
)
from mission_control.domain.programs.contracts import (
    DependencyDisposition,
    ExecutionIdentity,
    LateResultFacts,
    ResultDecision,
    StageResultObservation,
)
from mission_control.domain.programs.human_gate import HumanGateOutcome, stagegraph_gate_result
from mission_control.domain.programs.interpreter import StageGraphInterpreter


def admitted_leaf(*, multiple=False):
    outputs = (
        StageOutputSlot(output_slot_id="report", output_contract_ref="report@1", required=True),
    )
    if multiple:
        outputs += (
            StageOutputSlot(output_slot_id="notes", output_contract_ref="notes@1", required=False),
        )
    graph = build_stagegraph_v2(
        logical_id="test.completion",
        title="Completion",
        description="Completion requirements",
        stages=(
            StageGraphStageSpec(
                "final",
                output_slots=tuple(x.output_slot_id for x in outputs),
                output_declarations=outputs,
                obligation_refs=("goal",),
            ),
        ),
    )
    kernel = StageGraphInterpreter(graph, effective_max_concurrency=1)
    initial = kernel.initial_projection(ExecutionIdentity("run"), run_version=1)
    admission = kernel.frontier(initial, available_concurrency=1)[0]
    projection = kernel.apply_admission(
        initial, admission, next_run_version=2, next_family_version=1
    )
    return kernel, admission.identity, projection


@pytest.mark.parametrize("status", ["failed", "cancelled", "in_doubt"])
def test_failed_leaf_never_becomes_accepted_output(status):
    kernel, identity, projection = admitted_leaf()
    candidate = {"output_refs": ["artifact:report"], "obligation_refs": ["goal"]}
    decision = kernel.result_decision(
        identity, LateResultFacts(), operation_disposition=status, operation_result=candidate
    )
    observation = StageResultObservation(
        identity, candidate, True, True, True, True, 1, operation_disposition=status
    )
    settled = kernel.apply_result_decision(
        projection, observation, decision, next_run_version=3, next_family_version=2
    )
    assert decision.decision == ResultDecision.REJECT
    assert settled.accepted_results == ()
    assert not settled.accepted_obligation_evidence
    assert not kernel.completion(settled).can_terminalize
    failure = kernel.failure_completion(settled)
    assert failure is not None and failure.failed


@pytest.mark.parametrize(
    "field",
    [
        "run_terminal",
        "terminalization_started",
        "run_cancelling",
        "generation_superseded",
        "producer_invalidated",
        "evidence_invalid",
    ],
)
def test_leaf_enforces_late_result_veto(field):
    kernel, identity, _ = admitted_leaf()
    decision = kernel.result_decision(identity, replace(LateResultFacts(), **{field: True}))
    assert decision.decision == ResultDecision.QUARANTINE


@pytest.mark.parametrize(
    ("candidate", "reason"),
    [
        ({"output_refs": []}, "outputs_missing:report"),
        (
            {"output_refs": ["artifact:r"], "obligation_refs": ["another-stage"]},
            "undeclared_obligation_claim",
        ),
        ({"output_refs": [17]}, "invalid_output_refs"),
        ({"output_refs": "artifact:r"}, "invalid_output_refs"),
        (
            {"output_refs": ["artifact:r"], "output_bindings": {"report": ["artifact:invented"]}},
            "unregistered_output_binding",
        ),
    ],
)
def test_completed_provider_is_rejected_when_requirements_fail(candidate, reason):
    kernel, identity, _ = admitted_leaf()
    assert reason in kernel.result_validation_errors(identity, candidate)
    assert (
        kernel.result_decision(identity, LateResultFacts(), operation_result=candidate).decision
        == ResultDecision.REJECT
    )


def test_named_required_output_cannot_be_replaced_with_optional_output():
    kernel, identity, _ = admitted_leaf(multiple=True)
    candidate = {
        "output_refs": ["artifact:notes"],
        "output_bindings": {"notes": ["artifact:notes"]},
    }
    assert kernel.result_validation_errors(identity, candidate) == ("outputs_missing:report",)
    valid = {"output_refs": ["artifact:r"], "output_bindings": {"report": ["artifact:r"]}}
    assert kernel.result_validation_errors(identity, valid) == ()
    assert (
        kernel.result_decision(identity, LateResultFacts(), operation_result=valid).decision
        == ResultDecision.ADMIT
    )


def test_duplicate_result_cannot_rewrite_the_accepted_projection():
    kernel, identity, projection = admitted_leaf()
    candidate = {"output_refs": ["artifact:r"], "obligation_refs": ["goal"]}
    observation = StageResultObservation(identity, candidate, True, True, True, True, 1)
    decision = kernel.result_decision(identity, LateResultFacts(), operation_result=candidate)
    settled = kernel.apply_result_decision(
        projection, observation, decision, next_run_version=3, next_family_version=2
    )
    with pytest.raises(ValueError, match="active semantic attempt"):
        kernel.apply_result_decision(
            settled, observation, decision, next_run_version=4, next_family_version=3
        )


def test_absent_optional_producer_output_cannot_fulfill_required_dependency():
    graph = build_stagegraph_v2(
        logical_id="test.optional-output",
        title="Optional output",
        description="Required input",
        stages=(
            StageGraphStageSpec(
                "producer",
                output_slots=("optional",),
                output_declarations=(
                    StageOutputSlot(
                        output_slot_id="optional",
                        output_contract_ref="report@1",
                        required=False,
                    ),
                ),
            ),
            StageGraphStageSpec("consumer", depends_on=("producer",)),
        ),
    )
    kernel = StageGraphInterpreter(graph, effective_max_concurrency=1)
    initial = kernel.initial_projection(ExecutionIdentity("run"), run_version=1)
    admission = kernel.frontier(initial, available_concurrency=1)[0]
    running = kernel.apply_admission(initial, admission, next_run_version=2, next_family_version=1)
    result = {"output_refs": []}
    decision = kernel.result_decision(
        admission.identity, LateResultFacts(), operation_result=result
    )
    assert decision.decision == ResultDecision.REJECT
    assert decision.matched_veto == "required_dependency_output_missing"
    assert decision.dependency_dispositions == {
        "producer:to:consumer": DependencyDisposition.FAILED
    }
    observation = StageResultObservation(admission.identity, result, True, True, True, True, 1)
    settled = kernel.apply_result_decision(
        running, observation, decision, next_run_version=3, next_family_version=2
    )
    assert kernel.frontier(settled, available_concurrency=1) == ()


@pytest.mark.parametrize("accepted", [True, False])
def test_attributed_gate_resolution_settles_only_its_owned_obligations(accepted):
    kernel, identity, running = admitted_leaf()
    outcome = HumanGateOutcome(
        human_task_id="task",
        task_key="task:key",
        gate_key="final",
        review_round=1,
        status="accepted" if accepted else "not_accepted",
        actor_ref="owner",
        resolution_ref="human-resolution:task",
        packet_digest="sha256:" + "a" * 64,
        decision="approve" if accepted else "deny",
    )
    disposition, payload = stagegraph_gate_result(
        outcome,
        evaluation_contract_ref=None,
        objective_contract_ref=None,
        accepted_obligation_refs=("goal",),
    )
    observation = StageResultObservation(
        identity, payload, True, True, True, True, 1, operation_disposition=disposition
    )
    decision = kernel.result_decision(
        identity, LateResultFacts(), operation_disposition=disposition, operation_result=payload
    )
    settled = kernel.apply_result_decision(
        running, observation, decision, next_run_version=3, next_family_version=2
    )
    assert kernel.completion(settled).can_terminalize is accepted
    assert ("goal" in settled.accepted_obligation_evidence) is accepted
