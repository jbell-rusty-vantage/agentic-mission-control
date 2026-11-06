"""Trusted judgment rules (Sprint OC WI-03 / OVE-165; OUTPUT-CONTRACTS §§4-5, OC-D108-113/121).

Pure decisions the knowledge bridge applies around the Knowledge Services transport:

* :func:`evaluator_refusals`: a judge, auditor or reviewer is a *separate* admitted invocation with
  its own credential reference, origin subject and operation; a judge also runs on another vendor
  than the producer (``models.toml`` ``judge.default``). A producer credential never acts as one.
* :func:`assessment_result`: how a KS use decision becomes an MC ``Assessment@1`` result. Only a
  KS rejection (contrary evidence or integrity failure) fails; an ungrounded disagreement or a
  pending review holds as ``review``; an unavailable evaluator is ``unavailable``.
* :func:`supersession_refusal`: who may supersede an assessment (the open WI-01 question). Only the
  trusted bridge (role ``assessor``), for the same exact subject, citing a KS successor decision
  whose chain contains the superseded assessment's decision.
* :func:`use_gate`: official use versus authorized held review/repair under the application's
  output-contract minimums (``required_review_classes``, ``consequential_signoff_classes``).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Literal, Protocol

KS_DECISION_EVIDENCE_PREFIX: Final = "ks-use-decision:"
# The trusted knowledge bridge's actor: the only actor that may supersede an assessment.
TRUSTED_BRIDGE_ACTOR: Final = "mission-control:trusted-judgment"


class JudgmentRefusal(StrEnum):
    EVALUATOR_IS_PRODUCER = "EVALUATOR_IS_PRODUCER"
    EVALUATOR_CREDENTIAL_SHARED = "EVALUATOR_CREDENTIAL_SHARED"
    JUDGE_VENDOR_NOT_INDEPENDENT = "JUDGE_VENDOR_NOT_INDEPENDENT"
    JUDGE_PIN_MISMATCH = "JUDGE_PIN_MISMATCH"
    EVALUATOR_ROLE_INVALID = "EVALUATOR_ROLE_INVALID"
    SUPERSESSION_UNAUTHORIZED = "SUPERSESSION_UNAUTHORIZED"
    SUPERSESSION_SUBJECT_MISMATCH = "SUPERSESSION_SUBJECT_MISMATCH"
    SUPERSESSION_NOT_A_SUCCESSOR = "SUPERSESSION_NOT_A_SUCCESSOR"


@dataclass(frozen=True)
class CognitionIdentity:
    """Who did a piece of cognition: the admitted invocation's credential, subject and operation."""

    credential_ref: str
    subject: str
    operation_ref: str
    vendor: str | None
    model_id: str | None = None


@dataclass(frozen=True)
class EvaluatorPin:
    """The pinned evaluator model of an application (``models.toml`` ``judge.default``)."""

    profile: str
    vendor: str
    model_id: str


def evaluator_refusals(
    producer: CognitionIdentity,
    evaluator: CognitionIdentity,
    *,
    role: Literal["judge", "second_family_judge", "auditor", "human_reviewer"],
    judge_pin: EvaluatorPin | None = None,
) -> tuple[JudgmentRefusal, ...]:
    """Why ``evaluator`` cannot judge ``producer``'s output (empty: it may)."""

    found: list[JudgmentRefusal] = []
    if evaluator.subject == producer.subject or evaluator.operation_ref == producer.operation_ref:
        found.append(JudgmentRefusal.EVALUATOR_IS_PRODUCER)
    if evaluator.credential_ref == producer.credential_ref:
        found.append(JudgmentRefusal.EVALUATOR_CREDENTIAL_SHARED)
    if role in {"judge", "second_family_judge"}:
        if evaluator.vendor is None or evaluator.vendor == producer.vendor:
            found.append(JudgmentRefusal.JUDGE_VENDOR_NOT_INDEPENDENT)
        if (
            role == "judge"
            and judge_pin is not None
            and (evaluator.vendor != judge_pin.vendor or evaluator.model_id != judge_pin.model_id)
        ):
            found.append(JudgmentRefusal.JUDGE_PIN_MISMATCH)
    if role == "human_reviewer" and evaluator.vendor is not None:
        found.append(JudgmentRefusal.EVALUATOR_ROLE_INVALID)
    return tuple(found)


AssessmentResult = Literal["pass", "fail", "review", "unavailable"]


def assessment_result(
    disposition: Literal["admitted", "held", "rejected"] | None,
    *,
    admissible: bool,
    review_pending: bool,
) -> AssessmentResult:
    """The MC result of one KS decision. ``None`` disposition: the evaluator was unavailable.

    Automated failure needs a KS rejection (contrary evidence or integrity failure); a held
    decision (ungrounded disagreement, missing coverage) and an admitted decision that still
    waits on a qualified review both hold as ``review``; ``pass`` needs current eligibility.
    """

    if disposition is None:
        return "unavailable"
    if disposition == "rejected":
        return "fail"
    if disposition == "admitted" and admissible and not review_pending:
        return "pass"
    return "review"


def decision_evidence(decision_id: str, digest: str) -> str:
    """The evidence ref an assessment carries for the exact KS decision it rests on."""

    return f"{KS_DECISION_EVIDENCE_PREFIX}{decision_id}@{digest}"


def cited_decisions(evidence_refs: Sequence[str]) -> tuple[str, ...]:
    """The KS decision ids an assessment's evidence names."""

    return tuple(
        ref.removeprefix(KS_DECISION_EVIDENCE_PREFIX).split("@", 1)[0]
        for ref in evidence_refs
        if ref.startswith(KS_DECISION_EVIDENCE_PREFIX)
    )


class _Judged(Protocol):
    @property
    def assessment_id(self) -> str: ...
    @property
    def subject_id(self) -> str: ...
    @property
    def subject_digest(self) -> str: ...
    @property
    def result(self) -> str: ...
    @property
    def evidence_refs(self) -> tuple[str, ...]: ...
    @property
    def supersedes(self) -> str | None: ...


def _standing_trusted(
    assessments: Sequence[_Judged], revision_id: str, content_digest: str
) -> list[_Judged]:
    """The unsuperseded assessments citing a KS decision for exactly this revision and digest,
    in recording order (the store answers ``output_assessments`` by ``recorded_seq``)."""

    trusted = [
        row
        for row in assessments
        if row.subject_id == revision_id
        and row.subject_digest == content_digest
        and cited_decisions(row.evidence_refs)
    ]
    superseded = {row.supersedes for row in trusted if row.supersedes is not None}
    return [row for row in trusted if row.assessment_id not in superseded]


def head_demoted(assessments: Sequence[_Judged], revision_id: str, content_digest: str) -> bool:
    """Whether an accepted revision is demoted (OVE-169; a post-promotion revocation): it has
    standing trusted assessments and is not officially usable under the worst-wins rule
    (``official_use_evidence``: any standing non-pass, e.g. a later revocation or an
    unsuperseded forked failure, demotes). Accepted heads are never deleted; consumers re-check
    with this before use. A revision with no trusted assessment is not demoted (it was promoted
    another way)."""

    standing = _standing_trusted(assessments, revision_id, content_digest)
    return bool(standing) and any(row.result != "pass" for row in standing)


def official_use_evidence(
    assessments: Sequence[_Judged], revision_id: str, content_digest: str
) -> str | None:
    """The KS decision evidence that makes an exact revision officially usable now (W1 D28).

    The trusted bridge records ``pass`` only for a decision KS resolved as admitted, officially
    usable and with no pending review (``assessment_result``); a review adjudication reaches MC as
    the bridge's superseding ``pass`` (resume), and a revocation as a later superseding non-pass
    (resume or consumer recheck). Judgments combine conservatively, as everywhere in fulfillment
    (the worst standing result wins): only when EVERY standing (unsuperseded) assessment citing a
    KS decision for exactly this revision and digest is ``pass`` is the revision officially usable;
    the evidence is the cited decision of the newest such row (highest ``recorded_seq``). A forked,
    unsuperseded failure beside a later pass answers ``None``. Only the trusted bridge may cite KS
    decisions (WI-07 B2').

    Integrator ruling (W1): this reads MC's recorded judgment, not a live KS resolution, at
    fulfillment time. Current eligibility is re-checked at use and read (IMPLEMENTATION.md, the
    consumer recheck before admission and the exact read with purpose), not at fulfillment.
    """

    standing = _standing_trusted(assessments, revision_id, content_digest)
    if not standing or any(row.result != "pass" for row in standing):
        return None
    return next(
        ref for ref in standing[-1].evidence_refs if ref.startswith(KS_DECISION_EVIDENCE_PREFIX)
    )


def supersession_refusal(
    *,
    role: str,
    actor_ref: str = TRUSTED_BRIDGE_ACTOR,
    prior_subject: tuple[str, str, str],
    new_subject: tuple[str, str, str],
    prior_evidence: Sequence[str],
    successor_chain: Sequence[str],
    prior_result: str | None = None,
) -> JudgmentRefusal | None:
    """Whether a new assessment may supersede ``prior`` (``None``: it may).

    Supersession replaces a standing judgment, so it is reserved to the trusted knowledge bridge:
    the same exact subject (kind, id, digest) and a KS successor chain that contains a decision
    the prior assessment rested on (or a prior ``unavailable`` wait record citing no decision). A
    later pass without that lineage never overrides a failure.
    """

    if role != "assessor" or actor_ref != TRUSTED_BRIDGE_ACTOR:
        return JudgmentRefusal.SUPERSESSION_UNAUTHORIZED
    if prior_subject != new_subject:
        return JudgmentRefusal.SUPERSESSION_SUBJECT_MISMATCH
    if prior_result == "unavailable" and not cited_decisions(prior_evidence):
        # An evaluator-unavailable record is a wait, not a verdict: the bridge's later trusted
        # judgment of the same exact subject replaces it.
        return None
    prior = set(cited_decisions(prior_evidence))
    if not prior or not prior & set(successor_chain):
        return JudgmentRefusal.SUPERSESSION_NOT_A_SUCCESSOR
    return None


UseClass = Literal["official", "consequential", "internal", "draft"]
UsePurpose = Literal["official", "review_repair"]


@dataclass(frozen=True)
class UseGate:
    """What a consumer may do with exact report bytes for one purpose."""

    read_bytes: bool
    official_use: bool
    reason: str | None


def use_gate(
    *,
    purpose: UsePurpose,
    use_class: UseClass,
    admissible: bool,
    reviewed: bool,
    required_review_classes: Sequence[str],
    signoff_classes: Sequence[str],
    repair_authorized: bool,
) -> UseGate:
    """Official use versus authorized held review/repair (OC-D121; RV-08).

    Official use needs current exact-use eligibility and, for a class the application lists, a
    qualified review (for a sign-off class, a human review: KS reviews are human-reviewer grants).
    Held or draft bytes reach a review/repair consumer only when that consumer holds repair
    authority; it never becomes official use.
    """

    if purpose == "review_repair":
        if not repair_authorized:
            return UseGate(False, False, "repair_unauthorized")
        return UseGate(True, False, None)
    if not admissible:
        return UseGate(False, False, "use_ineligible")
    if (use_class in required_review_classes or use_class in signoff_classes) and not reviewed:
        return UseGate(False, False, "review_required")
    return UseGate(True, True, None)


__all__ = [
    "KS_DECISION_EVIDENCE_PREFIX",
    "TRUSTED_BRIDGE_ACTOR",
    "AssessmentResult",
    "CognitionIdentity",
    "EvaluatorPin",
    "JudgmentRefusal",
    "UseGate",
    "assessment_result",
    "cited_decisions",
    "decision_evidence",
    "evaluator_refusals",
    "head_demoted",
    "official_use_evidence",
    "supersession_refusal",
    "use_gate",
]
