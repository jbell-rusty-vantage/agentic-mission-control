"""Pure evaluation of explicit Stage Graph routes and named release groups (OVE-171, WI-08).

OUTPUT-CONTRACTS §7 engineering resolution, exactly:

- a predicate over an unknown fact is unknown (never false);
- ``all_matching``: every true branch releases while unknown branches wait;
- ``first_match``: branches are read in declared order and an unknown branch stops the walk, so a
  later true branch is never selected past an earlier unknown;
- ``else`` is selected only when every branch is conclusively false;
- a named group's threshold counts distinct members; its selection is the first qualifying
  distinct set in durable eligibility order (producer acceptance order, then declared position),
  and a quorum never waives the group's coverage subjects. The selection is the shortest prefix
  of that order meeting both the threshold and the coverage, so with coverage it may hold more
  members than the quorum (review N2).

Facts are read from the host-attributed ``route_facts`` record of a stage's accepted result
(written by the result decision from validated output bytes, never by the provider).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

from mission_control.domain.authoring.contracts import JoinKind
from mission_control.domain.authoring.graph_routes import (
    FactPredicate,
    JoinGroup,
    StageFact,
    StageRoute,
    scalar_type,
)
from mission_control.domain.programs.contracts import (
    FactObservation,
    JoinDisposition,
    RouteBranchDisposition,
    RouteBranchEvaluation,
    RouteDecision,
    RouteTruth,
)

# The host-owned key of an accepted stage result that carries its attributed facts.
ROUTE_FACTS_KEY: Final = "route_facts"


def fact_from_result(
    stage_id: str, fact: StageFact, operation_result: dict[str, Any] | None, *, final: bool
) -> FactObservation:
    """The fact as recorded on an accepted result; anything malformed is unknown."""

    if operation_result is None:
        return FactObservation(
            stage_id, fact.fact_id, False, reason="source_not_accepted", final=final
        )
    record = operation_result.get(ROUTE_FACTS_KEY)
    entry = record.get(fact.fact_id) if isinstance(record, dict) else None
    if not isinstance(entry, dict) or entry.get("status") != "known":
        reason = entry.get("reason") if isinstance(entry, dict) else None
        return FactObservation(
            stage_id,
            fact.fact_id,
            False,
            reason=str(reason) if reason else "fact_unrecorded",
            final=True,
        )
    value = entry.get("value")
    if scalar_type(value) != fact.value_type:
        return FactObservation(
            stage_id, fact.fact_id, False, reason="fact_type_mismatch", final=True
        )
    evidence = entry.get("evidence_ref")
    return FactObservation(
        stage_id,
        fact.fact_id,
        True,
        value=value,
        evidence_ref=str(evidence) if isinstance(evidence, str) else None,
    )


def evaluate_predicate(predicate: FactPredicate, observation: FactObservation) -> bool | None:
    """True/false over a known fact; None (unknown) otherwise. Closed operators only."""

    if not observation.known:
        return None
    value = observation.value
    if scalar_type(value) != predicate.value_type:
        return None
    expected = predicate.value
    match predicate.op:
        case "eq":
            return value == expected
        case "ne":
            return value != expected
        case "in":
            return isinstance(expected, tuple) and value in expected
        case "not_in":
            return isinstance(expected, tuple) and value not in expected
    if not isinstance(value, int) or not isinstance(expected, int):
        return None
    match predicate.op:
        case "lt":
            return value < expected
        case "le":
            return value <= expected
        case "gt":
            return value > expected
        case _:
            return value >= expected


Observe = Callable[[str, str], FactObservation]


def evaluate_route(route: StageRoute, observe: Observe) -> RouteDecision:
    truths: list[tuple[RouteTruth, tuple[str, ...], tuple[str, ...], bool]] = []
    for branch in route.branches:
        results: list[bool | None] = []
        evidence: list[str] = []
        unknown: list[str] = []
        unknown_final: list[bool] = []
        for predicate in branch.predicates:
            observation = observe(predicate.stage_id, predicate.fact_id)
            outcome = evaluate_predicate(predicate, observation)
            results.append(outcome)
            if observation.evidence_ref:
                evidence.append(observation.evidence_ref)
            if outcome is None:
                unknown.append(
                    f"{predicate.stage_id}.{predicate.fact_id}:{observation.reason or 'unknown'}"
                )
                unknown_final.append(observation.final)
        truth: RouteTruth = (
            "false"
            if any(item is False for item in results)
            else "true"
            if all(item is True for item in results)
            else "unknown"
        )
        # Exhausted only when every unknown conjunct is final: a pending conjunct of the same
        # branch could still resolve false, which decides the branch conclusively.
        final = bool(unknown_final) and all(unknown_final)
        truths.append((truth, tuple(sorted(set(evidence))), tuple(unknown), final))
    dispositions: list[RouteBranchDisposition] = []
    else_disposition: RouteBranchDisposition
    if route.mode == "all_matching":
        dispositions = [
            "selected" if truth == "true" else "not_selected" if truth == "false" else "waiting"
            for truth, *_ in truths
        ]
        kinds = {truth for truth, *_ in truths}
        else_disposition = (
            "selected" if kinds == {"false"} else "not_selected" if "true" in kinds else "waiting"
        )
    else:
        else_disposition = "selected"
        stopped = False
        for truth, *_ in truths:
            if stopped:
                dispositions.append("waiting" if else_disposition == "waiting" else "not_selected")
                continue
            if truth == "unknown":
                dispositions.append("waiting")
                else_disposition = "waiting"
                stopped = True
            elif truth == "true":
                dispositions.append("selected")
                else_disposition = "not_selected"
                stopped = True
            else:
                dispositions.append("not_selected")
    exhausted = any(
        disposition == "waiting" and final
        for disposition, (_truth, _evidence, _unknown, final) in zip(
            dispositions, truths, strict=True
        )
    )
    return RouteDecision(
        route_id=route.route_id,
        mode=route.mode,
        branches=tuple(
            RouteBranchEvaluation(
                branch_id=branch.branch_id,
                truth=truth,
                disposition=disposition,
                evidence_refs=evidence,
                unknown_reasons=unknown,
            )
            for branch, disposition, (truth, evidence, unknown, _final) in zip(
                route.branches, dispositions, truths, strict=True
            )
        ),
        else_disposition=else_disposition if route.else_stage_ids else "absent",
        exhausted=exhausted,
    )


def target_gates(route: StageRoute, decision: RouteDecision) -> dict[str, RouteBranchDisposition]:
    """Each target's gate: selected by any of its branches, not selected by all, else waiting."""

    by_target: dict[str, list[RouteBranchDisposition]] = {}
    for branch, evaluation in zip(route.branches, decision.branches, strict=True):
        for stage_id in branch.target_stage_ids:
            by_target.setdefault(stage_id, []).append(evaluation.disposition)
    if decision.else_disposition != "absent":
        for stage_id in route.else_stage_ids:
            by_target.setdefault(stage_id, []).append(decision.else_disposition)
    gates: dict[str, RouteBranchDisposition] = {}
    for stage_id, values in by_target.items():
        gates[stage_id] = (
            "selected"
            if "selected" in values
            else "not_selected"
            if all(item == "not_selected" for item in values)
            else "waiting"
        )
    return gates


MemberStateKind = Literal["satisfied", "pending", "failed"]


@dataclass(frozen=True)
class MemberState:
    stage_id: str
    state: MemberStateKind
    # Durable eligibility order: producer acceptance order, then the declared position.
    accepted_order: int = 0
    position: int = 0


@dataclass(frozen=True)
class GroupOutcome:
    disposition: JoinDisposition
    selected: tuple[str, ...] = ()
    surplus: tuple[str, ...] = ()


def group_outcome(
    group: JoinGroup, kind: JoinKind, minimum: int | None, members: Sequence[MemberState]
) -> GroupOutcome:
    threshold = (
        len(group.member_stage_ids)
        if kind == JoinKind.ALL
        else 1
        if kind == JoinKind.ANY
        else (minimum or len(group.member_stage_ids))
    )
    required = frozenset(group.coverage_subjects)
    ordered = sorted(
        (item for item in members if item.state == "satisfied"),
        key=lambda item: (item.accepted_order, item.position, item.stage_id.encode("utf-8")),
    )
    selected: list[str] = []
    covered: set[str] = set()
    for item in ordered:
        selected.append(item.stage_id)
        covered |= group.covers(item.stage_id)
        if len(selected) >= threshold and required <= covered:
            surplus = tuple(entry.stage_id for entry in ordered[len(selected) :])
            return GroupOutcome(JoinDisposition.SATISFIED, tuple(selected), surplus)
    open_members = [item for item in members if item.state != "failed"]
    reachable = set().union(*(group.covers(item.stage_id) for item in open_members))
    if len(open_members) < threshold or not required <= reachable:
        return GroupOutcome(JoinDisposition.IMPOSSIBLE)
    return GroupOutcome(JoinDisposition.PENDING)


__all__ = [
    "ROUTE_FACTS_KEY",
    "GroupOutcome",
    "MemberState",
    "evaluate_predicate",
    "evaluate_route",
    "fact_from_result",
    "group_outcome",
    "target_gates",
]
