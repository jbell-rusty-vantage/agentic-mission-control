"""Ordering waits for producer completion without inventing required data or transfer."""

from dataclasses import replace

import pytest
from pydantic import ValidationError

from mission_control.domain.authoring.contracts import JoinKind, StageOutputSlot
from mission_control.domain.authoring.stagegraph_builder import (
    StageGraphStageSpec,
    StageInputBindingSpec,
    build_stagegraph_v2,
)
from mission_control.domain.programs.contracts import (
    DependencyDisposition,
    ExecutionIdentity,
    LateResultFacts,
    ResultDecision,
    StageResultObservation,
)
from mission_control.domain.programs.interpreter import StageGraphInterpreter


def graph(*, data=False, required=False, explicit_order=False):
    return build_stagegraph_v2(
        logical_id="ordering.test",
        title="Ordering",
        description="Optional output remains optional under ordering",
        stages=(
            StageGraphStageSpec(
                "produce",
                output_slots=("note",),
                output_declarations=(
                    StageOutputSlot(
                        output_slot_id="note", output_contract_ref="text", required=False
                    ),
                ),
            ),
            StageGraphStageSpec(
                "consume",
                depends_on=("produce",),
                output_slots=("result",),
                bindings=(StageInputBindingSpec("produce", "note", required=required),)
                if data
                else (),
                ordering_predecessors=("produce",) if explicit_order else (),
            ),
        ),
    )


def execute_producer(blueprint, *, disposition="completed", result=None):
    kernel = StageGraphInterpreter(blueprint, effective_max_concurrency=1)
    projection = kernel.initial_projection(ExecutionIdentity("run-1"), run_version=1)
    (proposal,) = kernel.frontier(projection, available_concurrency=1)
    assert proposal.identity.stage_id == "produce"
    projection = kernel.apply_admission(
        projection, proposal, next_run_version=2, next_family_version=1
    )
    assert not kernel.frontier(projection, available_concurrency=1)
    body = result or {"output_refs": []}
    decision = kernel.result_decision(
        proposal.identity,
        LateResultFacts(),
        operation_disposition=disposition,
        operation_result=body,
    )
    projection = kernel.apply_result_decision(
        projection,
        StageResultObservation(
            identity=proposal.identity,
            operation_disposition=disposition,
            operation_result=body,
            child_closed_or_quiesced=True,
            reservations_and_usage_settled=True,
            effects_settled=True,
            cancellation_reconciled=True,
            accepted_order=1,
        ),
        decision,
        next_run_version=3,
        next_family_version=2,
    )
    return kernel, projection, decision


@pytest.mark.parametrize("explicit_optional_data", [False, True])
def test_optional_output_omission_releases_only_after_ordered_producer_completed(
    explicit_optional_data,
):
    blueprint = graph(data=explicit_optional_data, explicit_order=explicit_optional_data)
    assert any(edge.ordering_only for edge in blueprint.dependencies)
    kernel, projection, decision = execute_producer(blueprint)
    assert decision.decision == ResultDecision.ADMIT
    (consumer,) = kernel.frontier(projection, available_concurrency=1)
    assert consumer.identity.stage_id == "consume"
    assert not consumer.frozen_input_refs and not consumer.frozen_input_bindings
    assert any(item.accepted_decision_ref for item in consumer.released_by)


@pytest.mark.parametrize("disposition", ["failed", "cancelled"])
def test_failed_ordering_predecessor_never_releases_consumer(disposition):
    kernel, projection, decision = execute_producer(graph(), disposition=disposition)
    assert decision.decision != ResultDecision.ADMIT
    assert not kernel.frontier(projection, available_concurrency=1)


def test_explicit_required_data_still_requires_the_named_output():
    blueprint = graph(data=True, required=True)
    assert not any(edge.ordering_only for edge in blueprint.dependencies)
    _, _, decision = execute_producer(blueprint)
    assert decision.decision == ResultDecision.REJECT
    assert decision.matched_veto == "required_dependency_output_missing"


def test_ordering_does_not_transfer_even_available_output_bytes():
    kernel, projection, _ = execute_producer(graph(), result={"output_refs": ["artifact:note"]})
    (consumer,) = kernel.frontier(projection, available_concurrency=1)
    assert not consumer.frozen_input_refs and not consumer.frozen_input_bindings


def test_ordering_flag_default_is_digest_neutral_and_cannot_be_optional():
    data = graph(data=True, required=True).dependencies[0]
    assert "ordering_only" not in data.model_dump(mode="json")
    ordering = graph().dependencies[0]
    with pytest.raises(ValidationError, match="ordering dependencies"):
        type(ordering).model_validate(
            {**ordering.model_dump(mode="python"), "dependency_class": "optional"}
        )


def test_explicit_ordering_remains_all_even_with_any_data_join():
    blueprint = build_stagegraph_v2(
        logical_id="ordering.any",
        title="Ordering and any data",
        description="Both explicit predecessors gate a first qualifying data join",
        stages=(
            StageGraphStageSpec("a", output_slots=("data",)),
            StageGraphStageSpec("b", output_slots=("data",)),
            StageGraphStageSpec(
                "consume",
                depends_on=("a", "b"),
                ordering_predecessors=("a", "b"),
                bindings=(StageInputBindingSpec("a", "data"), StageInputBindingSpec("b", "data")),
                join=JoinKind.ANY,
                output_slots=("result",),
            ),
        ),
    )
    joins = {item.join_id: item.kind for item in blueprint.joins}
    assert joins == {"consume:inputs": JoinKind.ANY, "consume:ordering": JoinKind.ALL}
    kernel = StageGraphInterpreter(blueprint, effective_max_concurrency=3)
    projection = kernel.initial_projection(ExecutionIdentity("run-1"), run_version=1)
    dependencies = dict(projection.dependencies)
    for edge in blueprint.dependencies:
        if edge.producer_stage_id == "a":
            dependencies[edge.dependency_id] = replace(
                dependencies[edge.dependency_id], disposition=DependencyDisposition.FULFILLED
            )
    partial = replace(projection, dependencies=dependencies)
    assert "consume" not in {
        item.identity.stage_id for item in kernel.frontier(partial, available_concurrency=3)
    }
