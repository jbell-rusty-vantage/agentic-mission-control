"""Collections: exact members, per-member judgments and the authored aggregate rule (WI-07).

OUTPUT-CONTRACTS §§2, 4, 8 and PROOFS §4 ("collection: exact members/current heads/aggregate
rule; first member cannot attest others"). A collection revision is an exact manifest: its
``CandidateRef.members`` (ref + digest). Each member requirement is judged **per member** by an
independent ``member`` assessment bound to that member's exact ref and digest; an assessment of
one member, of the manifest revision or of the pinned set never stands for another member. The
requirement's aggregate rule (:func:`~mission_control.domain.outputs.contracts.aggregate_rule`)
decides the collection: ``all`` (default) needs every member to pass, so one held member keeps
it unfulfilled; ``at_least k`` needs ``k`` distinct passing members and keeps the others visible.
Coverage counts only subjects whose manifest entry names a member that passes every member
requirement: a held or rejected member never covers anything.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from mission_control.domain.knowledge.judgment import cited_decisions
from mission_control.domain.outputs.contracts import (
    Assessment,
    ExactOutput,
    MemberDecisions,
    OutputObligation,
    Requirement,
    TrustedValidators,
    Unmet,
    aggregate_rule,
)
from mission_control.domain.outputs.rules import pointer_get

MemberState = Literal["pass", "fail", "review", "unavailable", "unassessed"]
# How a member's state reads in the current-set index and in ``Unmet`` messages.
MEMBER_LABELS: dict[str, str] = {
    "pass": "accepted",
    "fail": "rejected",
    "review": "held",
    "unavailable": "waiting",
    "unassessed": "pending",
}
_SEVERITY: dict[str, int] = {"pass": 0, "unassessed": 1, "review": 2, "unavailable": 3, "fail": 4}


def collection_members(output: ExactOutput) -> tuple[tuple[str, str], ...]:
    """The exact (ref, digest) members a collection revision lists, in manifest order."""

    items = output.candidate.get("members")
    if not isinstance(items, list):
        return ()
    found: list[tuple[str, str]] = []
    for item in items:
        if isinstance(item, dict):
            ref, digest = item.get("ref"), item.get("digest")
            if isinstance(ref, str) and isinstance(digest, str):
                found.append((ref, digest))
    return tuple(found)


def is_trusted(validator: str, trusted_validators: TrustedValidators) -> bool:
    """``None``: no pin was configured, so every validator is trusted (fail closed)."""

    return trusted_validators is None or validator in trusted_validators


def _standing(
    assessments: Sequence[Assessment],
    ref: str,
    digest: str,
    key: str,
    *,
    verified: frozenset[str] | None,
) -> tuple[MemberState, tuple[str, ...]]:
    """``verified`` (trusted requirement): the KS decision ids the host verified standing for
    exactly this member; only assessments citing one of them count (``None``: not trusted)."""

    matching = [
        item
        for item in assessments
        if item.subject_kind == "member"
        and item.subject_id == ref
        and item.subject_digest == digest
        and key in item.requirement_results
        and (verified is None or bool(set(cited_decisions(item.evidence_refs)) & verified))
    ]
    superseded = {item.supersedes for item in matching if item.supersedes is not None}
    standing = [item for item in matching if item.assessment_id not in superseded]
    if not standing:
        return "unassessed", ()
    worst = max((item.requirement_results[key] for item in standing), key=_SEVERITY.__getitem__)
    return worst, tuple(item.assessment_id for item in standing)


@dataclass(frozen=True)
class MemberOutcome:
    """One exact member's standing judgment for every member requirement of its promise."""

    ref: str
    digest: str
    results: tuple[tuple[str, MemberState], ...]
    assessment_refs: tuple[str, ...]

    @property
    def state(self) -> MemberState:
        """The worst state over its requirements (``pass`` only when every one passes)."""

        if not self.results:
            return "pass"
        return max((state for _, state in self.results), key=_SEVERITY.__getitem__)

    @property
    def label(self) -> str:
        return MEMBER_LABELS[self.state]


def member_requirements(obligation: OutputObligation) -> tuple[Requirement, ...]:
    return tuple(
        item
        for item in obligation.contract.requirements
        if item.required and item.subject == "member"
    )


def member_outcomes(
    obligation: OutputObligation,
    output: ExactOutput,
    assessments: Sequence[Assessment],
    *,
    trusted_validators: TrustedValidators = None,
    member_decisions: MemberDecisions | None = None,
) -> tuple[MemberOutcome, ...]:
    """Every listed member judged by its own exact assessments only (never another member's).
    A requirement under a trusted-judgment validator counts only assessments citing a KS
    decision verified standing for that exact member (``member_decisions``); without that
    verification it stays unassessed (a host pass or a forged citation never proves it)."""

    keys = [
        (item.key, is_trusted(item.validator, trusted_validators))
        for item in member_requirements(obligation)
    ]
    decisions = member_decisions or {}
    outcomes: list[MemberOutcome] = []
    for ref, digest in collection_members(output):
        results: list[tuple[str, MemberState]] = []
        refs: list[str] = []
        for key, trusted in keys:
            verified = decisions.get((ref, digest), frozenset()) if trusted else None
            state, standing = _standing(assessments, ref, digest, key, verified=verified)
            results.append((key, state))
            refs.extend(standing)
        outcomes.append(MemberOutcome(ref, digest, tuple(results), tuple(refs)))
    return tuple(outcomes)


@dataclass(frozen=True)
class CollectionDecision:
    unmet: tuple[Unmet, ...]
    assessment_refs: tuple[str, ...]
    outcomes: tuple[MemberOutcome, ...]

    def passing(self) -> frozenset[tuple[str, str]]:
        return frozenset((item.ref, item.digest) for item in self.outcomes if item.state == "pass")


def _member_unmet(deliverable: str, outcome: MemberOutcome, key: str, state: str) -> Unmet:
    where = f"{key} on member {outcome.ref} of {deliverable}"
    if state == "unassessed":
        return Unmet(code="MEMBER_UNASSESSED", message=f"{where} not yet assessed"[:500])
    if state == "review":
        return Unmet(code="MEMBER_HELD", message=f"{where} held for review"[:500], owner="reviewer")
    if state == "unavailable":
        return Unmet(code="MEMBER_UNAVAILABLE", message=f"{where} unavailable"[:500], owner="host")
    return Unmet(code="MEMBER_REJECTED", message=f"{where} failed"[:500])


def decide_collection(
    obligation: OutputObligation,
    output: ExactOutput,
    assessments: Sequence[Assessment],
    *,
    trusted_validators: TrustedValidators = None,
    member_decisions: MemberDecisions | None = None,
) -> CollectionDecision:
    """The aggregate decision of one collection revision under its member requirements."""

    outcomes = member_outcomes(
        obligation,
        output,
        assessments,
        trusted_validators=trusted_validators,
        member_decisions=member_decisions,
    )
    unmet: list[Unmet] = []
    refs = sorted({ref for outcome in outcomes for ref in outcome.assessment_refs})
    for requirement in member_requirements(obligation):
        rule, minimum = aggregate_rule(requirement)
        states = [(outcome, dict(outcome.results)[requirement.key]) for outcome in outcomes]
        passed = sum(1 for _, state in states if state == "pass")
        if rule == "all":
            unmet.extend(
                _member_unmet(output.deliverable_id, outcome, requirement.key, state)
                for outcome, state in states
                if state != "pass"
            )
            continue
        assert minimum is not None
        if passed >= minimum:
            continue  # the authored rule permits it; the other members stay visible per member
        pending = sum(1 for _, state in states if state in {"unassessed", "review", "unavailable"})
        reachable = passed + pending >= minimum
        unmet.append(
            Unmet(
                code="AGGREGATE_SHORT",
                message=(
                    f"{passed} of at least {minimum} members pass {requirement.key} on "
                    f"{output.deliverable_id}"
                    + ("" if reachable else "; the remaining members cannot reach it")
                )[:500],
                waiting=reachable,
            )
        )
    return CollectionDecision(tuple(unmet), tuple(refs), outcomes)


def blocked_by_members(
    obligation: OutputObligation,
    output: ExactOutput,
    assessments: Sequence[Assessment],
    *,
    trusted_validators: TrustedValidators = None,
) -> bool:
    """A collection candidate a receiver must not take as its subject (review S1): a held or
    rejected member keeps its aggregate rule unmet. Members merely unassessed, or held ones an
    authored ``at_least`` rule tolerates, do not block delivery."""

    decided = decide_collection(
        obligation, output, assessments, trusted_validators=trusted_validators
    )
    return bool(decided.unmet) and any(
        state in {"fail", "review"} for outcome in decided.outcomes for _, state in outcome.results
    )


def cited_member_decisions(
    obligation: OutputObligation,
    outputs: Sequence[ExactOutput],
    assessments: Sequence[Assessment],
    *,
    trusted_validators: TrustedValidators,
) -> tuple[tuple[str, str, str], ...]:
    """(member ref, member digest, KS decision id) the standing member assessments of these
    collection revisions cite under trusted requirements: what the host must verify."""

    keys = {
        item.key
        for item in member_requirements(obligation)
        if is_trusted(item.validator, trusted_validators)
    }
    if not keys:
        return ()
    listed = {pair for output in outputs for pair in collection_members(output)}
    superseded = {item.supersedes for item in assessments if item.supersedes is not None}
    found = {
        (item.subject_id, item.subject_digest, decision)
        for item in assessments
        if item.subject_kind == "member"
        and (item.subject_id, item.subject_digest) in listed
        and item.assessment_id not in superseded
        and keys & set(item.requirement_results)
        for decision in cited_decisions(item.evidence_refs)
    }
    return tuple(sorted(found))


def covered_by_members(
    output: ExactOutput,
    pointer: str,
    key: str | None,
    passing: frozenset[tuple[str, str]],
) -> set[str]:
    """Subjects the manifest value attributes to a passing member (``entry[key]``)."""

    found, entries = pointer_get(output.candidate.get("value"), pointer)
    if not found or not isinstance(entries, list) or key is None:
        return set()
    return {
        entry[key]
        for entry in entries
        if isinstance(entry, dict)
        and isinstance(entry.get(key), str)
        and (entry.get("ref"), entry.get("digest")) in passing
    }


__all__ = [
    "MEMBER_LABELS",
    "CollectionDecision",
    "MemberOutcome",
    "MemberState",
    "blocked_by_members",
    "cited_member_decisions",
    "collection_members",
    "covered_by_members",
    "decide_collection",
    "is_trusted",
    "member_outcomes",
    "member_requirements",
]
