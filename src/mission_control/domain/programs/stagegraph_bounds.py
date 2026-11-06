"""Compile-time payload bounds of a Stage Graph's family records (OVE-171; the W1 D10 lesson).

Every Stage Graph family decision persists the whole next projection inside one atomic family
mutation, which the run-control contracts bound (``MAX_FAMILY_MUTATION_BYTES`` serialized bytes,
the structural node/entry/depth limits of ``check_payload_bounds``). A large graph (many stages,
dependencies, facts or routes) can outgrow those bounds only once it has run for a while, which
W1 found as a decode loop. This module builds the graph's *completed* projection with
representative bounded result payloads (every stage accepted, every dependency carrying its
evidence, every fact recorded at its maximum size, every route decided) and refuses at compile
time, typed, when that record would not fit. It is an engineering estimate on the safe side of
the real payloads (refs and facts are sized at their ceilings), never a runtime authority.

Multipliers (review S3): every stage of a Revisit Region is counted once per visit up to the
region's cap (each visit keeps its instance, accepted result and liability); every stage carries
``RETRY_ALLOWANCE`` extra rejected attempts (a liability each; rejected results add no accepted
fact) and its one late or surplus result is its accepted fact. Deliberately, a large *legacy*
Stage Graph (no WI-08 marker) is refused too: the bound is a property of the family record, which
legacy runs already persist in full, so such a graph would hit the same decode failure later.
"""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from typing import Final

from mission_control.domain.authoring.contracts import StageGraphBlueprint
from mission_control.domain.authoring.graph_routes import MAX_FACT_STRING_CHARS
from mission_control.domain.policies.family_admission import MAX_FAMILY_MUTATION_BYTES
from mission_control.domain.policies.payload_bounds import (
    PayloadBoundViolation,
    check_payload_bounds,
)
from mission_control.domain.programs.contracts import (
    AcceptedResultFact,
    DependencyDisposition,
    ExecutionIdentity,
    ProducerLiability,
    ResultDecision,
    StageExecutionIdentity,
)
from mission_control.domain.programs.interpreter import StageGraphInterpreter
from mission_control.domain.programs.routing import ROUTE_FACTS_KEY

# Representative ceilings of one accepted result (an artifact ref and decision refs are a few
# hundred characters in practice; sized generously here).
REF_CHARS: Final = 240
# Room the decision envelope (proposal, digests, completion records) needs beside the projection.
DECISION_ENVELOPE_BYTES: Final = 12_288
BOUND_RUN_ID: Final = "run-" + "0" * 32
# Rejected attempts per stage the estimate allows for (each keeps a producer liability).
RETRY_ALLOWANCE: Final = 1


def _ref(kind: str, index: int) -> str:
    stem = f"artifact://{kind}/{index}/"
    return stem + "x" * max(REF_CHARS - len(stem), 0)


def completed_projection_record(blueprint: StageGraphBlueprint) -> dict[str, object]:
    """The family record of the graph's completed projection at representative ceilings."""

    interpreter = StageGraphInterpreter(blueprint, effective_max_concurrency=1_000_000)
    projection = interpreter.initial_projection(ExecutionIdentity(BOUND_RUN_ID), run_version=1)
    stages = {}
    accepted: list[AcceptedResultFact] = []
    liabilities: dict[str, ProducerLiability] = {}
    region = interpreter.region
    visits = region.max_visits if region is not None else 1
    instances = []
    for key, instance in sorted(projection.stages.items()):
        cycles = (
            visits if region is not None and instance.candidate.stage_id in region.stage_ids else 1
        )
        for cycle in range(cycles):
            candidate = replace(instance.candidate, workflow_cycle_ordinal=cycle)
            instances.append(
                (
                    candidate.semantic_prefix if cycle else key,
                    replace(instance, candidate=candidate),
                )
            )
    for order, (key, instance) in enumerate(instances):
        stage = interpreter.stages[instance.candidate.stage_id]
        for retry in range(RETRY_ALLOWANCE):
            rejected = StageExecutionIdentity(
                run_id=BOUND_RUN_ID,
                execution_epoch=1,
                candidate=instance.candidate,
                semantic_attempt=retry + 2,
            )
            liabilities[rejected.semantic_key] = ProducerLiability(
                semantic_attempt_id=rejected.semantic_key,
                reservation_id=f"reservation:{rejected.semantic_key}",
                reserved_amounts={"operation.attempts": 1, "concurrency.slots": 1},
                child_closed_or_quiesced=True,
                reservations_and_usage_settled=True,
                effects_settled=True,
                cancellation_reconciled=True,
                result_decision=ResultDecision.REJECT,
            )
        identity = StageExecutionIdentity(
            run_id=BOUND_RUN_ID,
            execution_epoch=1,
            candidate=instance.candidate,
            semantic_attempt=1,
        )
        outputs = [_ref(stage.stage_id, index) for index, _ in enumerate(stage.output_slots)]
        result: dict[str, object] = {
            "output_refs": outputs,
            "output_bindings": {
                slot.output_slot_id: [ref]
                for slot, ref in zip(stage.output_slots, outputs, strict=True)
            },
            "obligation_refs": [item.obligation_slot_id for item in stage.obligation_slots],
        }
        if stage.facts:
            result[ROUTE_FACTS_KEY] = {
                fact.fact_id: {
                    "status": "known",
                    "value": "v" * MAX_FACT_STRING_CHARS,
                    "evidence_ref": f"{outputs[0] if outputs else _ref('fact', order)}"
                    f"#{fact.pointer}@sha256:{'0' * 64}",
                }
                for fact in stage.facts
            }
        stages[key] = replace(
            instance,
            status="completed",
            semantic_attempt=1,
            admitted_operation_request_ref=_ref("operation-request", order),
            output_refs=tuple(outputs),
        )
        accepted.append(AcceptedResultFact(identity, result, order + 1))
        liabilities[identity.semantic_key] = ProducerLiability(
            semantic_attempt_id=identity.semantic_key,
            reservation_id=f"reservation:{identity.semantic_key}",
            reserved_amounts={"operation.attempts": 1, "concurrency.slots": 1},
            child_closed_or_quiesced=True,
            reservations_and_usage_settled=True,
            effects_settled=True,
            cancellation_reconciled=True,
            result_decision=ResultDecision.ADMIT,
        )
    dependencies = {
        key: replace(
            item,
            disposition=DependencyDisposition.FULFILLED,
            evidence_refs=(_ref("evidence", index),),
        )
        for index, (key, item) in enumerate(sorted(projection.dependencies.items()))
    }
    completed = replace(
        projection,
        stages=stages,
        dependencies=dependencies,
        producer_liabilities=liabilities,
        accepted_results=tuple(accepted),
    )
    view = interpreter.route_view(completed)
    return {
        "projection": asdict(completed),
        "route_decisions": [asdict(item) for item in view.decisions],
        "revisit_decisions": [asdict(item) for item in interpreter.revisit_view(completed)],
    }


def stagegraph_payload_problems(blueprint: StageGraphBlueprint) -> tuple[str, ...]:
    """Typed reasons the graph's family records would break their bounds; empty when they fit."""

    record = completed_projection_record(blueprint)
    problems: list[str] = []
    try:
        check_payload_bounds(record)
    except PayloadBoundViolation as error:
        problems.append(f"payload_bound_exceeded: {error}")
    size = len(json.dumps(record, sort_keys=True, default=str).encode("utf-8"))
    limit = MAX_FAMILY_MUTATION_BYTES - DECISION_ENVELOPE_BYTES
    if size > limit:
        problems.append(
            f"family_record_too_large: the completed projection needs about {size} bytes; one "
            f"family mutation holds {limit} beside its decision envelope"
        )
    return tuple(problems)


__all__ = ["completed_projection_record", "stagegraph_payload_problems"]
