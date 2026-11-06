"""K01 trusted assessment contracts (Sprint OC WI-03 / OVE-165; OUTPUT-CONTRACTS §5).

Python mirrors of Knowledge Services' ``packages/knowledge-operation-protocol/src/assessment.ts``.
The published JSON Schemas and golden vectors are byte copies under
``tests/fixtures/knowledge_protocol``; wire names only, no semantic renaming.

Five handle operations compose the KS research services behind the authenticated transport:
``report.observe`` (an independent evaluator's observations; its role is the credential's
``evaluation`` grant), ``report.seal`` (the exact VerificationRun), ``report.decide`` (an exact
use decision for a declared use, audience and purpose), ``report.review`` (the reviewer is the
credential subject; a successor decision is persisted) and ``decision.resolve`` (the current
successor and its exact-use eligibility, also after a restart).
"""

# ruff: noqa: N815
# (wire names are the K01 field names: no semantic renaming)
from __future__ import annotations

from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from mission_control.contracts.knowledge_protocol import (
    Digest,
    Id,
    Instant,
    Name,
    Ref,
    SafeInt,
    SchemaVersion,
    digest_canonical,
)

OBSERVE_CONTRACT: Final = {"name": "report-observation", "version": "v1"}
SEAL_CONTRACT: Final = {"name": "report-seal", "version": "v1"}
DECIDE_CONTRACT: Final = {"name": "report-use", "version": "v1"}
REVIEW_CONTRACT: Final = {"name": "report-review", "version": "v1"}
RESOLVE_CONTRACT: Final = {"name": "decision-resolve", "version": "v1"}
# OVE-169: the independent evaluator's role-scoped context (`knowledge.read` on the trusted path).
EVALUATION_CONTEXT_CONTRACT: Final = {"name": "evaluation-context-read", "version": "v1"}
EVALUATION_CONTEXT_VERSION: Final = "research-evaluation-context.v1"

ASSESSMENT_CONTRACTS: Final = {
    "report.observe": OBSERVE_CONTRACT,
    "report.seal": SEAL_CONTRACT,
    "report.decide": DECIDE_CONTRACT,
    "report.review": REVIEW_CONTRACT,
    "decision.resolve": RESOLVE_CONTRACT,
}
RESULT_VERSIONS: Final = {
    "report.observe": "report-observation-result.v1",
    "report.seal": "report-seal-result.v1",
    "report.decide": "use-decision-result.v1",
    "report.review": "report-review-result.v1",
    "decision.resolve": "use-decision-resolution.v1",
}

MAX_OBSERVATIONS: Final = 64
OBSERVER_ROLES: Final = frozenset({"judge", "second_family_judge", "auditor"})
EvaluatorRole = Literal["judge", "second_family_judge", "auditor", "human_reviewer"]
UsePurpose = Literal["official", "review_repair"]
AdmissibilityStatus = Literal["admitted", "held", "rejected"]
ReasonCode = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
# The protocol's normalized values: strings, safe integers, booleans and null (never floats).
NormalizedValue = str | int | bool | None


class _Wire(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class CredentialEvaluation(_Wire):
    """``credential-evaluation.v1``: the evaluator authority the host attests for one invocation.

    ``credentialRef`` names the evaluator's own admitted credential (never secret bytes).
    """

    role: EvaluatorRole
    credentialRef: Id
    provider: Name | None
    family: Name | None


def _a_kind(ref: Ref, *kinds: str) -> None:
    if ref.kind not in kinds:
        raise ValueError(f"{ref.kind} handle where {' or '.join(kinds)} is required")


class ReportObservationRequest(_Wire):
    """``report-observation.v1``: observations of one exact revision (records are research-core
    ``VerificationObservation`` documents, validated by the binding) and, for an auditor, the
    independent census discovery pass."""

    schema_: Literal["report-observation.v1"] = Field(alias="schema")
    report: Ref
    observations: Annotated[tuple[dict[str, Any], ...], Field(max_length=MAX_OBSERVATIONS)]
    census: dict[str, Any] | None

    @model_validator(mode="after")
    def _something_observed(self) -> ReportObservationRequest:
        _a_kind(self.report, "report")
        if not self.observations and self.census is None:
            raise ValueError("an observation request carries at least one observation or a census")
        return self


class EvaluationContextRequest(_Wire):
    """``evaluation-context-read.v1``: the exact report whose evaluation context the credential's
    observer role reads (KS scopes the answer by that role)."""

    schema_: Literal["evaluation-context-read.v1"] = Field(alias="schema")
    report: Ref

    @model_validator(mode="after")
    def _report(self) -> EvaluationContextRequest:
        _a_kind(self.report, "report")
        return self


class Build(_Wire):
    buildId: Id
    runtime: Name
    dirty: bool


class ReportSealRequest(_Wire):
    schema_: Literal["report-seal.v1"] = Field(alias="schema")
    report: Ref
    build: Build

    @model_validator(mode="after")
    def _report(self) -> ReportSealRequest:
        _a_kind(self.report, "report")
        return self


class ReportUseRequest(_Wire):
    """``report-use.v1``: an exact use decision of the sealed revision for a declared use,
    audience and purpose (``official`` or ``review_repair``; the purpose never changes the
    disposition)."""

    schema_: Literal["report-use.v1"] = Field(alias="schema")
    report: Ref
    subject: Ref
    use: Name
    audience: Name
    purpose: UsePurpose
    boundEffectDigest: Digest
    targetSchema: SchemaVersion
    normalizedValues: dict[Name, NormalizedValue]
    policy: Ref
    rubric: Ref
    expiresAt: Instant | None

    @model_validator(mode="after")
    def _exact(self) -> ReportUseRequest:
        _a_kind(self.report, "report")
        _a_kind(self.subject, "report", "assertion")
        _a_kind(self.policy, "policy")
        _a_kind(self.rubric, "rubric")
        if self.subject.kind == "report" and (
            self.subject.id != self.report.id or self.subject.digest != self.report.digest
        ):
            raise ValueError("a report decision's subject is its report")
        if any(isinstance(value, float) for value in self.normalizedValues.values()):
            raise ValueError("normalized values are never floats")
        return self


class ReportReviewRequest(_Wire):
    schema_: Literal["report-review.v1"] = Field(alias="schema")
    decision: Ref
    outcome: Literal["approve", "hold", "reject"]
    boundEffectDigest: Digest
    qualifiersDigest: Digest | None
    rationale: Annotated[str, StringConstraints(min_length=1, max_length=4000)]

    @model_validator(mode="after")
    def _decision(self) -> ReportReviewRequest:
        _a_kind(self.decision, "use_decision")
        return self


class DecisionResolveRequest(_Wire):
    schema_: Literal["decision-resolve.v1"] = Field(alias="schema")
    decision: Ref

    @model_validator(mode="after")
    def _decision(self) -> DecisionResolveRequest:
        _a_kind(self.decision, "use_decision")
        return self


class Admissibility(_Wire):
    status: AdmissibilityStatus
    reason: ReasonCode | None


class DecisionResolution(_Wire):
    """``use-decision-resolution.v1``: the current successor of an exact decision and its
    current exact-use eligibility. ``judgment`` lists what only policy-admitted judgments cover:
    their approval is never fact entailment."""

    schema_: Literal["use-decision-resolution.v1"] = Field(alias="schema")
    requested: Ref
    current: Ref
    chain: Annotated[tuple[Ref, ...], Field(min_length=1)]
    report: Ref
    subject: Ref
    use: Name
    audience: Name
    useClass: Literal["official", "consequential", "internal", "draft"]
    disposition: AdmissibilityStatus
    conditions: tuple[Annotated[str, StringConstraints(min_length=1, max_length=500)], ...]
    admissibility: Admissibility
    reviewPending: bool
    reviewer: Ref | None
    judgment: tuple[Id, ...]
    revocationEpoch: SafeInt
    checkedAt: Instant
    # Authoritative KS verification-run identity; older non-native replies may omit it.
    runId: Id | None = None

    @property
    def officially_usable(self) -> bool:
        """Current exact-use eligibility: admitted now (review satisfied, epoch current)."""

        return self.admissibility.status == "admitted"


def assessment_request_digest(request: BaseModel) -> str:
    """The digest of an assessment request's canonical wire bytes (what a wait record binds)."""

    return digest_canonical(request.model_dump(mode="json", by_alias=True))


__all__ = [
    "ASSESSMENT_CONTRACTS",
    "DECIDE_CONTRACT",
    "MAX_OBSERVATIONS",
    "OBSERVER_ROLES",
    "OBSERVE_CONTRACT",
    "RESOLVE_CONTRACT",
    "RESULT_VERSIONS",
    "REVIEW_CONTRACT",
    "SEAL_CONTRACT",
    "Admissibility",
    "Build",
    "CredentialEvaluation",
    "DecisionResolution",
    "DecisionResolveRequest",
    "EvaluatorRole",
    "ReportObservationRequest",
    "ReportReviewRequest",
    "ReportSealRequest",
    "ReportUseRequest",
    "UsePurpose",
    "assessment_request_digest",
]
