"""Obligation fulfillment and closed completion evaluation (OUTPUT-CONTRACTS §4; ADR-0010).

Fulfillment always iterates the *declared* obligations of a pinned frontier, including those
with no submission; a submitted row never counts by itself. Revisions of one deliverable count
once (heads are per deliverable) and the distinct count must lie within the promised
cardinality. Every promised layer is checked: each required requirement through exact
independent assessments, declared coverage, nested member guarantees and, for a collection,
per-member judgments under its aggregate rule (``domain.outputs.collections``). Forms whose proof
belongs to a later work item are reported as not yet fulfillable, never as success.

Judgments combine conservatively: for one exact subject and requirement, every assessment
stands unless a later one explicitly supersedes it, and the worst standing result wins, so a
later pass never silently overrides an earlier failure.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from mission_control.domain.outputs.collections import covered_by_members, decide_collection
from mission_control.domain.outputs.contracts import (
    DEFERRED_FORMS,
    AllOf,
    AnyOf,
    Assessment,
    AssessmentLeaf,
    AssessmentResult,
    CompletionState,
    CriterionLeaf,
    Enforcement,
    ExactOutput,
    Fulfillment,
    FulfillmentResult,
    HumanResolutionLeaf,
    IntegrityLeaf,
    MemberDecisions,
    ObligationLeaf,
    OutputForm,
    OutputObligation,
    OutputSet,
    TrustedValidators,
    Unmet,
)
from mission_control.domain.outputs.rules import pointer_get

SATISFIED_DISPOSITIONS = frozenset({"fulfilled", "not_applicable"})
_SEVERITY: dict[str, int] = {"pass": 0, "review": 1, "unavailable": 2, "fail": 3}
# Internal three-plus-one valued evaluation: ``neutral`` is an expected/optional promise that is
# not fulfilled. It never satisfies an alternative and never blocks.
_State = Literal["satisfied", "waiting", "blocked", "neutral"]


def judged(
    assessments: Sequence[Assessment], kind: str, subject_id: str, digest: str, key: str
) -> tuple[AssessmentResult | None, tuple[str, ...]]:
    """The standing judgment of one exact subject for ``key`` and the assessments behind it."""

    matching = [
        item
        for item in assessments
        if item.subject_kind == kind
        and item.subject_id == subject_id
        and item.subject_digest == digest
        and key in item.requirement_results
    ]
    superseded = {item.supersedes for item in matching if item.supersedes is not None}
    standing = [item for item in matching if item.assessment_id not in superseded]
    if not standing:
        return None, ()
    worst = max((item.requirement_results[key] for item in standing), key=_SEVERITY.__getitem__)
    return worst, tuple(item.assessment_id for item in standing)


def _requirement_unmet(key: str, result: str | None, subject: str) -> Unmet | None:
    if result == "pass":
        return None
    if result is None:
        return Unmet(code="REQUIREMENT_UNASSESSED", message=f"{key} not yet assessed on {subject}")
    if result == "review":
        return Unmet(
            code="REQUIREMENT_IN_REVIEW",
            message=f"{key} held for review on {subject}",
            owner="reviewer",
        )
    if result == "unavailable":
        return Unmet(
            code="REQUIREMENT_UNAVAILABLE",
            message=f"{key} assessment unavailable on {subject}",
            owner="host",
        )
    return Unmet(code="REQUIREMENT_FAILED", message=f"{key} failed on {subject}")


def listed_members(output: ExactOutput, pointer: str) -> tuple[tuple[str, str], ...]:
    """The exact (ref, digest) members an index revision lists at ``pointer``."""

    found, items = pointer_get(output.candidate.get("value"), pointer)
    if not found or not isinstance(items, list):
        return ()
    return tuple(
        (item["ref"], item["digest"])
        for item in items
        if isinstance(item, dict)
        and isinstance(item.get("ref"), str)
        and isinstance(item.get("digest"), str)
    )


@dataclass(frozen=True)
class EffectReceiptProof:
    """What the host knows of the native effect an ``effect_receipt`` member names (WI-05).

    ``applied``: the effect settled applied from its protocol receipt (a Biotech dispatch only
    after its verified delivery), ``ref`` naming that receipt. ``unresolved``: dispatched but not
    proven (pending dispatch, uncertain after a lost acknowledgment): it waits and never
    fulfills. ``not_applied``: never fulfills; ``code`` says why (``EFFECT_NOT_APPLIED``:
    rejected, partial, unknown or another receipt; ``EFFECT_FOREIGN_RUN``: another run's effect,
    including a fork's or a child's; ``EFFECT_ORIGIN_UNPROVEN``: no mission run coordinates;
    ``EFFECT_EVIDENCE_UNWIRED``: no evidence port composed).
    """

    state: Literal["applied", "unresolved", "not_applied"]
    ref: str | None = None
    reason: str = ""
    code: Literal[
        "EFFECT_NOT_APPLIED",
        "EFFECT_FOREIGN_RUN",
        "EFFECT_ORIGIN_UNPROVEN",
        "EFFECT_EVIDENCE_UNWIRED",
    ] = "EFFECT_NOT_APPLIED"


def decide_fulfillment(
    obligation: OutputObligation,
    output_set: OutputSet,
    assessments: Sequence[Assessment],
    realizations: Mapping[str, str] | None = None,
    reference_uses: Mapping[str, str] | None = None,
    effect_receipts: Mapping[str, EffectReceiptProof] | None = None,
    trusted_validators: TrustedValidators = None,
    member_decisions: MemberDecisions | None = None,
    unaccepted: int = 0,
) -> Fulfillment:
    """Decide one declared obligation against exactly the members of ``output_set``.

    ``realizations`` maps a file revision to the transfer receipt whose receiving backend read
    its exact custody bytes back (WI-02): a file promise needs one per member; custody storage
    readback alone is not enough. ``reference_uses`` maps a reference revision to the current
    official-use evidence of the exact revision it names (WI-03, RV-08): an exact handle alone,
    readable bytes or a held decision never fulfill a reference promise. ``effect_receipts``
    maps an effect-receipt revision to the host's proof of the native effect it names (WI-05,
    OC-D117): only an applied, receipt-settled effect fulfills; pending or uncertain waits.
    ``unaccepted`` counts the distinct deliverables with a finalized submission but no accepted
    head (W1 D29): a short promise then reads ``SUBMITTED_NOT_ACCEPTED``, never ``MISSING``.
    """

    contract = obligation.contract
    mine = [m for m in output_set.members if m.obligation_key == obligation.key]
    eligible = [m for m in mine if m.obligation_revision == obligation.revision]
    unmet: list[Unmet] = []
    refs: list[str] = []
    for stale in (m for m in mine if m.obligation_revision != obligation.revision):
        unmet.append(
            Unmet(
                code="HEAD_UNDER_SUPERSEDED_REVISION",
                message=(
                    f"{stale.deliverable_id} was accepted under revision "
                    f"{stale.obligation_revision}; the frontier pins {obligation.revision}"
                ),
            )
        )
    distinct = len({m.deliverable_id for m in eligible})
    if contract.form is OutputForm.FILE:
        for member in eligible:
            receipt = (realizations or {}).get(member.revision_id)
            if receipt is None:
                unmet.append(
                    Unmet(
                        code="FILE_NOT_REALIZED",
                        message=(
                            f"{member.deliverable_id} has no receiving-backend read of its "
                            "exact custody bytes"
                        ),
                        owner="host",
                    )
                )
            else:
                refs.append(receipt)
    if contract.form is OutputForm.REFERENCE:
        for member in eligible:
            use = (reference_uses or {}).get(member.revision_id)
            if use is None:
                unmet.append(
                    Unmet(
                        code="REFERENCE_USE_UNPROVEN",
                        message=(
                            f"{member.deliverable_id} names no revision with current official "
                            "use eligibility"
                        ),
                        owner="knowledge_service",
                    )
                )
            else:
                refs.append(use)
    if contract.form is OutputForm.EFFECT_RECEIPT:
        for member in eligible:
            proof = (effect_receipts or {}).get(member.revision_id)
            if proof is not None and proof.state == "applied" and proof.ref is not None:
                refs.append(proof.ref)
            elif proof is None or proof.state == "unresolved":
                unmet.append(
                    Unmet(
                        code="EFFECT_UNRESOLVED",
                        message=(
                            f"{member.deliverable_id} names an effect without a settled native "
                            "receipt yet (pending or uncertain)"
                        )[:500],
                        owner="knowledge_service",
                    )
                )
            else:
                reason = proof.reason or "the effect was not applied"
                unmet.append(
                    Unmet(
                        code=proof.code,
                        message=f"{member.deliverable_id}: {reason}"[:500],
                        waiting=False,
                        owner="host"
                        if proof.code == "EFFECT_EVIDENCE_UNWIRED"
                        else "knowledge_service",
                    )
                )
    deferred = DEFERRED_FORMS.get(contract.form)
    if deferred is not None and eligible:
        unmet.append(
            Unmet(
                code="FORM_NOT_YET_FULFILLABLE",
                message=f"{contract.form} fulfillment proof is delivered by {deferred}",
                waiting=False,
                owner="host",
            )
        )
    if distinct < obligation.cardinality.min:
        if unaccepted:
            # OUTPUT-CONTRACTS §2: an expected shortfall is visible as what it is: submitted
            # material that no assessment or accepting verdict has made an accepted head yet.
            unmet.append(
                Unmet(
                    code="SUBMITTED_NOT_ACCEPTED",
                    message=(
                        f"{distinct} of at least {obligation.cardinality.min} distinct "
                        f"deliverables accepted for {obligation.key}; {unaccepted} submitted "
                        "but not accepted (no passing assessment or accepting verdict yet)"
                    ),
                )
            )
        else:
            unmet.append(
                Unmet(
                    code="MISSING" if distinct == 0 else "CARDINALITY_SHORT",
                    message=(
                        f"{distinct} of at least {obligation.cardinality.min} distinct "
                        f"deliverables accepted for {obligation.key}"
                    ),
                )
            )
    if distinct > obligation.cardinality.max:
        unmet.append(
            Unmet(
                code="CARDINALITY_EXCEEDED",
                message=(
                    f"{distinct} distinct deliverables accepted, the promise allows at most "
                    f"{obligation.cardinality.max}"
                ),
                waiting=False,
                owner="host",
            )
        )
    schema = contract.schema_pin
    if eligible and schema is not None and not schema.bound:
        unmet.append(
            Unmet(
                code="SCHEMA_UNBOUND",
                message=f"no admitted validator is bound for {schema.ref}",
                waiting=False,
                owner="host",
            )
        )
    required = [item for item in contract.requirements if item.required]
    passing: set[tuple[str, str]] = set()
    for member in eligible:
        for requirement in (item for item in required if item.subject == "deliverable"):
            result, standing = judged(
                assessments,
                "output_revision",
                member.revision_id,
                member.content_digest,
                requirement.key,
            )
            refs.extend(standing)
            missing = _requirement_unmet(requirement.key, result, member.deliverable_id)
            if missing is not None:
                unmet.append(missing)
        if contract.form is OutputForm.COLLECTION:
            # WI-07: each member by its own exact assessment, under the authored aggregate rule.
            decided = decide_collection(
                obligation,
                member,
                assessments,
                trusted_validators=trusted_validators,
                member_decisions=member_decisions,
            )
            refs.extend(decided.assessment_refs)
            unmet.extend(decided.unmet)
            passing |= decided.passing()
        elif contract.member_contract is not None:
            nested = [item.key for item in required if item.subject == "member"]
            for ref, digest in listed_members(member, contract.member_contract.pointer):
                for key in nested:
                    result, standing = judged(assessments, "member", ref, digest, key)
                    refs.extend(standing)
                    if result != "pass":
                        code = (
                            "NESTED_GUARANTEE_UNPROVEN"
                            if result is None
                            else "NESTED_GUARANTEE_FAILED"
                        )
                        unmet.append(Unmet(code=code, message=f"{key} on nested member {ref}"))
    for requirement in (item for item in required if item.subject == "set"):
        if not eligible:
            continue
        result, standing = judged(
            assessments,
            "output_set",
            output_set.set_id,
            output_set.membership_digest,
            requirement.key,
        )
        refs.extend(standing)
        missing = _requirement_unmet(requirement.key, result, f"set {output_set.revision}")
        if missing is not None:
            unmet.append(missing)
    if contract.coverage is not None and eligible:
        covered: set[str] = set()
        for member in eligible:
            if contract.form is OutputForm.COLLECTION:
                # Only a passing member covers a subject (never a held or rejected one).
                covered |= covered_by_members(
                    member, contract.coverage.pointer, contract.coverage.key, frozenset(passing)
                )
            else:
                covered |= _covered(member, contract.coverage.pointer, contract.coverage.key)
        absent = sorted(set(contract.coverage.subjects) - covered)
        if absent:
            unmet.append(
                Unmet(
                    code="COVERAGE_INCOMPLETE",
                    message=f"promised subjects not covered: {', '.join(absent)}"[:500],
                )
            )
    if not unmet:
        disposition = "fulfilled"
    elif any(not item.waiting for item in unmet):
        disposition = "blocked"
    else:
        disposition = "unfulfilled"
    return Fulfillment(
        obligation_key=obligation.key,
        obligation_revision=obligation.revision,
        enforcement=obligation.enforcement,
        disposition=disposition,
        eligible_members=tuple(sorted(m.revision_id for m in eligible)),
        assessment_refs=tuple(sorted(set(refs))),
        distinct_count=distinct,
        unmet=tuple(unmet),
        submitted=bool(mine) or unaccepted > 0,
    )


def _covered(member: ExactOutput, pointer: str, key: str | None) -> set[str]:
    found, items = pointer_get(member.candidate.get("value"), pointer)
    if not found or not isinstance(items, list):
        return set()
    subjects = set()
    for item in items:
        if isinstance(item, str):
            subjects.add(item)
        elif key is not None and isinstance(item, dict) and isinstance(item.get(key), str):
            subjects.add(item[key])
    return subjects


def _all(states: Sequence[_State]) -> _State:
    decided = [state for state in states if state != "neutral"]
    if not decided:
        return "neutral"
    if "blocked" in decided:
        return "blocked"
    return "waiting" if "waiting" in decided else "satisfied"


def _any(states: Sequence[_State]) -> _State:
    if "satisfied" in states:
        return "satisfied"
    if "waiting" in states:
        return "waiting"
    if "blocked" in states:
        return "blocked"
    return "neutral"


def _evaluate(
    expression: Any,
    fulfillments: Mapping[str, Fulfillment],
    output_set: OutputSet,
    assessments: Sequence[Assessment],
    facts: Mapping[str, bool | None],
) -> _State:
    def again(item: Any) -> _State:
        return _evaluate(item, fulfillments, output_set, assessments, facts)

    if isinstance(expression, AllOf):
        return _all([again(item) for item in expression.items])
    if isinstance(expression, AnyOf):
        return _any([again(item) for item in expression.items])
    if isinstance(expression, ObligationLeaf):
        decided = fulfillments[expression.obligation]
        if decided.disposition in SATISFIED_DISPOSITIONS:
            return "satisfied"
        if decided.enforcement is not Enforcement.REQUIRED:
            return "neutral"  # a visible shortfall or silent absence, never a block
        return "blocked" if decided.disposition == "blocked" else "waiting"
    if isinstance(expression, AssessmentLeaf):
        decided = fulfillments[expression.obligation]
        members = [
            m
            for m in output_set.members
            if m.obligation_key == expression.obligation
            and m.revision_id in decided.eligible_members
        ]
        if not members:
            return "waiting" if decided.enforcement is Enforcement.REQUIRED else "neutral"
        states: list[_State] = []
        for member in members:
            result, _ = judged(
                assessments,
                "output_revision",
                member.revision_id,
                member.content_digest,
                expression.requirement,
            )
            if result in expression.allowed:
                states.append("satisfied")
            elif result is None or result == "review":
                states.append("waiting")
            else:
                states.append("blocked")
        return _all(states)
    if isinstance(expression, IntegrityLeaf | HumanResolutionLeaf | CriterionLeaf):
        name = (
            f"integrity:{expression.check}"
            if isinstance(expression, IntegrityLeaf)
            else f"human:{expression.task}"
            if isinstance(expression, HumanResolutionLeaf)
            else f"criterion:{expression.criterion}"
        )
        value = facts.get(name)
        if value is None:
            return "waiting"
        return "satisfied" if value else "blocked"
    raise TypeError(f"not a completion expression: {type(expression).__name__}")


def evaluate_completion(
    expression: Any,
    fulfillments: Mapping[str, Fulfillment],
    *,
    output_set: OutputSet,
    assessments: Sequence[Assessment] = (),
    facts: Mapping[str, bool | None] | None = None,
) -> CompletionState:
    """Evaluate the closed AST. Expected/optional promises never block or satisfy by absence."""

    state = _evaluate(expression, fulfillments, output_set, assessments, facts or {})
    return "satisfied" if state == "neutral" else state


def evaluate_frontier_decisions(
    obligations: Sequence[OutputObligation],
    completion: Any,
    output_set: OutputSet,
    assessments: Sequence[Assessment],
    *,
    facts: Mapping[str, bool | None] | None = None,
    realizations: Mapping[str, str] | None = None,
    reference_uses: Mapping[str, str] | None = None,
    effect_receipts: Mapping[str, EffectReceiptProof] | None = None,
    trusted_validators: TrustedValidators = None,
    member_decisions: MemberDecisions | None = None,
    unaccepted: Mapping[str, int] | None = None,
) -> FulfillmentResult:
    """Every declared obligation is decided; required unmet blocks, expected is visible.

    The admitted expression makes every required promise a conjunct, so ``blocking`` (required
    promises not fulfilled) and a satisfied ``completion`` never coexist.
    """

    decided = {
        item.key: decide_fulfillment(
            item,
            output_set,
            assessments,
            realizations,
            reference_uses,
            effect_receipts,
            trusted_validators=trusted_validators,
            member_decisions=member_decisions,
            unaccepted=(unaccepted or {}).get(item.key, 0),
        )
        for item in obligations
    }
    state = evaluate_completion(
        completion, decided, output_set=output_set, assessments=assessments, facts=facts
    )
    blocking = tuple(
        key
        for key, item in decided.items()
        if item.enforcement is Enforcement.REQUIRED
        and item.disposition not in SATISFIED_DISPOSITIONS
    )
    if blocking and state == "satisfied":
        # Invariant kept at registration and successor admission (every required promise is a
        # conjunct of the admitted completion); never answer "satisfied" past it.
        raise ValueError("completion does not cover every required promise")
    shortfalls = tuple(
        key
        for key, item in decided.items()
        if item.disposition not in SATISFIED_DISPOSITIONS
        and (
            item.enforcement is Enforcement.EXPECTED
            # optional absence is silent; submitted-but-unmet optional material stays visible
            or (item.enforcement is Enforcement.OPTIONAL and item.submitted)
        )
    )
    waiting_on = tuple(
        key
        for key, item in decided.items()
        if item.disposition == "unfulfilled" and item.enforcement is Enforcement.REQUIRED
    )
    return FulfillmentResult(
        set_id=output_set.set_id,
        membership_digest=output_set.membership_digest,
        fulfillments=tuple(decided[item.key] for item in obligations),
        completion=state,
        blocking=blocking,
        shortfalls=shortfalls,
        waiting_on=waiting_on,
    )


__all__ = [
    "SATISFIED_DISPOSITIONS",
    "EffectReceiptProof",
    "decide_fulfillment",
    "evaluate_completion",
    "evaluate_frontier_decisions",
    "judged",
    "listed_members",
]
