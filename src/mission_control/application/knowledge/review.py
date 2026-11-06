"""Authorized operator review of a KS use decision (W1 D2; OUTPUT-CONTRACTS §5, ADR-0059/0060).

An official or consequential use decision that KS admits only after review waits
(``review_pending``) until a qualified human reviews its exact decision. This is the operator
path to that review: ``POST .../runs/{run_id}/knowledge-reviews``, ``missionctl knowledge
review`` and the operator MCP ``knowledge_review`` tool all call
:meth:`KnowledgeReviewService.review`, which relays through the one KS review path
(:class:`~mission_control.application.knowledge.judgment.ReviewRelay`, the same code
``TrustedJudgmentBridge.review`` runs) under the reviewer's own separate invocation and a
``human_reviewer`` grant. The settlement's next pass re-resolves the successor decision.

Mission Control refuses before anything is sent (typed ``unauthorized_review``) when the actor
lacks the ``knowledge.review`` permission, names the run's producer or one of its evaluators
(the producer runtime subject, its reconciler, the judge and auditor subjects), or launched the
run (admitted it, owns or created its mission, or authored one of its revisions): the launcher
never approves its own run's decision, so a review needs a principal distinct from the launcher.
W1 fix G S2: the same route resets a role's exhausted evaluator attempts on one exact output
revision (``POST .../runs/{run_id}/evaluator-attempt-resets``,
:meth:`KnowledgeReviewService.reset_evaluator_attempts`), under the same authorization (the
``knowledge.review`` permission, never the producer, an evaluator or the launcher). The reset is
an audited superseding wait (:class:`~mission_control.application.knowledge.judgment.
EvaluatorAttemptReset`) naming the operator and the reason; the next settlement pass may run the
paid evaluator again, up to the bound.

The run is resolved in the tenant (``not_found``) and the decision must be one a trusted
assessment of that run cites, by id and digest (``decision_not_in_run``), so the reviewer origin
never names a run the decision does not belong to. KS then checks the live reviewer grant, the
exact bound digests and that the reviewer did not produce the run. The same review body twice
is the same KS request (one adjudication).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Literal, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from mission_control.application.knowledge.access import InvocationAccess
from mission_control.application.knowledge.evaluator_plans import AUDITOR_SUBJECT, JUDGE_SUBJECT
from mission_control.application.knowledge.judgment import (
    EvaluatorAttemptReset,
    EvaluatorBinding,
    EvaluatorResetRefused,
    TrustedJudgmentRefused,
)
from mission_control.application.knowledge.operations import KnowledgeRefused
from mission_control.contracts.identities import parse_request_scope
from mission_control.contracts.knowledge_protocol import Ref
from mission_control.domain.knowledge.judgment import decision_evidence
from mission_control.domain.knowledge.origin import InvocationOrigin
from mission_control.domain.outputs.contracts import Assessment
from mission_control.domain.policies.contracts import ActorContext

REVIEW_PERMISSION: Final = "knowledge.review"
REVIEWER_CREDENTIAL: Final = "mc-operator-reviewer"
REVIEW_LANE: Final = "operator"
_SUBJECT: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,199}$")
# KS refusal reasons that mean "this reviewer may not review this decision".
_UNAUTHORIZED_REASONS: Final = frozenset(
    {"reviewer_not_qualified", "reviewer_is_producer", "evaluator_role_required"}
)


class KnowledgeReviewRequest(BaseModel):
    """The operator's review of one exact KS use decision (the HTTP/MCP/CLI body)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: Ref
    outcome: Literal["approve", "hold", "reject"]
    bound_effect_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    qualifiers_digest: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    rationale: str = Field(min_length=1, max_length=4000)


class EvaluatorAttemptResetRequest(BaseModel):
    """The operator's reset of one role's exhausted evaluator attempts on an exact revision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    revision_id: str = Field(min_length=1, max_length=200)
    role: Literal["judge", "second_family_judge", "auditor"]
    reason: str = Field(min_length=1, max_length=400)


class ReviewRejected(Exception):
    """A typed refusal: ``unauthorized_review``, ``invalid``, ``not_found``,
    ``decision_not_in_run``, ``review_refused``, ``review_unavailable``."""

    def __init__(self, code: str, message: str, *, ks_code: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.ks_code = ks_code


class ReviewPort(Protocol):
    """The one KS review path (``ReviewRelay`` / ``TrustedJudgmentBridge.review``)."""

    async def review(
        self,
        reviewer: EvaluatorBinding,
        decision: Ref,
        *,
        outcome: Literal["approve", "hold", "reject"],
        bound_effect_digest: str,
        qualifiers_digest: str | None,
        rationale: str,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ResolvedRun:
    """A run resolved once in its tenant: its public run id (``run_key``, the id output records
    and invocation origins carry), its ledger mission id (the reviewer origin's mission) and who
    admitted, owns or revised it."""

    run_key: str
    mission_id: str
    actors: frozenset[str]


class RunActorsUnavailable(RuntimeError):
    """The run's actors cannot be read (a missing runtime grant): the review fails closed."""


class RunActors(Protocol):
    """Resolve a run (public or internal id) in this tenant; ``None``: no such run."""

    async def resolve_run(self, request_scope: str, run_id: str) -> ResolvedRun | None: ...


class RunAssessments(Protocol):
    async def output_assessments(self, scope: str, run_id: str) -> tuple[Assessment, ...]: ...


def _canonical_uuid(value: str) -> bool:
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def _utcnow() -> datetime:
    return datetime.now(UTC)


class KnowledgeReviewService:
    """One tenant's operator review route over the KS review path."""

    def __init__(
        self,
        relay: ReviewPort,
        *,
        runs: RunActors,
        assessments: RunAssessments,
        request_scope: str,
        issuer: str,
        producer_subject: str,
        knowledge_installation_id: str | None = None,
        clock: Callable[[], datetime] = _utcnow,
        resets: EvaluatorAttemptReset | None = None,
    ) -> None:
        self.request_scope = request_scope
        self._resets = resets
        self._scope = parse_request_scope(request_scope)
        self._relay = relay
        self._runs = runs
        self._assessments = assessments
        self._issuer = issuer
        self._knowledge_installation_id = knowledge_installation_id
        self._clock = clock
        # Who can never review this tenant's runs: the producer and the evaluators.
        self._excluded = frozenset(
            {producer_subject, f"{producer_subject}:reconciler", JUDGE_SUBJECT, AUDITOR_SUBJECT}
        )

    def authorize(self, actor: ActorContext) -> str:
        """The reviewer subject, or ``unauthorized_review`` before anything is sent."""

        if REVIEW_PERMISSION not in actor.permissions:
            raise ReviewRejected(
                "unauthorized_review", f"the actor holds no {REVIEW_PERMISSION} grant"
            )
        if actor.actor_id in self._excluded:
            raise ReviewRejected(
                "unauthorized_review",
                "the reviewer is the run's producer or one of its evaluators",
            )
        if not _SUBJECT.fullmatch(actor.actor_id):
            raise ReviewRejected("invalid", "the reviewer id is not a K01 subject")
        return actor.actor_id

    def reviewer(self, run: ResolvedRun, subject: str, decision: Ref) -> EvaluatorBinding:
        """A separate reviewer invocation: own subject, own operation, new invocation id.

        Its origin names the run's ledger mission (provenance slice 1, OVE-204) and no
        activation: an operator review is no runtime unit of the run."""

        origin = InvocationOrigin(
            issuer=self._issuer,
            installation_id=str(self._scope.installation_id),
            application_id=self._scope.application_id,
            tenant_id=str(self._scope.tenant_id),
            mission_id=run.mission_id,
            run_id=run.run_key,
            activation_id=None,
            operation_id=f"review/{decision.id}",
            attempt=1,
            generation=1,
            lane=REVIEW_LANE,
        )
        return EvaluatorBinding(
            role="human_reviewer",
            credential_ref=REVIEWER_CREDENTIAL,
            vendor=None,
            family=None,
            model_id=None,
            access=InvocationAccess(
                origin=origin,
                subject=subject,
                invocation_id=f"inv-review-{uuid4()}",
                authenticated_at=self._clock(),
                knowledge_installation_id=self._knowledge_installation_id,
            ),
        )

    async def _authorized_run(self, run_id: str, subject: str) -> ResolvedRun:
        """The resolved run, or a typed refusal (not found, unavailable, the launcher)."""

        try:
            resolved = await self._runs.resolve_run(self.request_scope, run_id)
        except RunActorsUnavailable as error:
            raise ReviewRejected("review_unavailable", str(error)) from None
        if resolved is None or not _canonical_uuid(resolved.run_key):
            # Output records key the run by its public UUID; anything else names no run here.
            raise ReviewRejected("not_found", f"no run {run_id} in this tenant")
        if subject in resolved.actors:
            raise ReviewRejected(
                "unauthorized_review",
                "the reviewer launched or revised this run; a different principal must review",
            )
        return resolved

    async def reset_evaluator_attempts(
        self, run_id: str, request: EvaluatorAttemptResetRequest, actor: ActorContext
    ) -> dict[str, Any]:
        """W1 fix G S2: reset one role's billed evaluator attempts on an exact revision after
        ``evaluator_attempts_exhausted``; audited on the superseding wait it records."""

        subject = self.authorize(actor)
        if self._resets is None:
            raise ReviewRejected("review_unavailable", "no evaluator attempt reset is composed")
        run_key = (await self._authorized_run(run_id, subject)).run_key
        try:
            recorded = await self._resets.reset(
                self.request_scope,
                run_key,
                request.revision_id,
                request.role,
                operator=subject,
                reason=request.reason,
            )
        except EvaluatorResetRefused as refused:
            code = "not_found" if refused.code == "not_found" else "nothing_to_reset"
            raise ReviewRejected(code, str(refused)) from None
        return {
            "run_id": run_key,
            "revision_id": request.revision_id,
            "role": request.role,
            "operator": subject,
            "assessment_id": recorded.assessment_id,
            "supersedes": recorded.supersedes,
        }

    async def review(
        self, run_id: str, request: KnowledgeReviewRequest, actor: ActorContext
    ) -> dict[str, Any]:
        subject = self.authorize(actor)
        if request.decision.kind != "use_decision":
            raise ReviewRejected("invalid", "a review names an exact use decision")
        if request.decision.tenant != str(self._scope.tenant_id):
            raise ReviewRejected("invalid", "the decision names another tenant")
        # One identifier for the assessments and the reviewer origin.
        run = await self._authorized_run(run_id, subject)
        run_id = run.run_key
        cited = decision_evidence(request.decision.id, request.decision.digest)
        recorded = await self._assessments.output_assessments(self.request_scope, run_id)
        if not any(cited in item.evidence_refs for item in recorded):
            raise ReviewRejected(
                "decision_not_in_run",
                "no trusted assessment of this run cites that exact decision",
            )
        reviewer = self.reviewer(run, subject, request.decision)
        try:
            document = await self._relay.review(
                reviewer,
                request.decision,
                outcome=request.outcome,
                bound_effect_digest=request.bound_effect_digest,
                qualifiers_digest=request.qualifiers_digest,
                rationale=request.rationale,
            )
        except TrustedJudgmentRefused as refused:
            if refused.reason in _UNAUTHORIZED_REASONS:
                raise ReviewRejected(
                    "unauthorized_review", str(refused), ks_code=refused.code
                ) from None
            raise ReviewRejected("review_refused", str(refused), ks_code=refused.code) from None
        except KnowledgeRefused as refused:
            if refused.code == "CAPABILITY_UNAVAILABLE":
                raise ReviewRejected("review_unavailable", str(refused)) from None
            raise ReviewRejected("review_refused", str(refused), ks_code=refused.code) from None
        return {
            "run_id": run_id,
            "decision": request.decision.model_dump(mode="json"),
            "reviewer": subject,
            "outcome": request.outcome,
            "review": document,
        }


__all__ = [
    "REVIEWER_CREDENTIAL",
    "REVIEW_PERMISSION",
    "EvaluatorAttemptResetRequest",
    "KnowledgeReviewRequest",
    "KnowledgeReviewService",
    "ResolvedRun",
    "ReviewPort",
    "ReviewRejected",
    "RunActors",
    "RunActorsUnavailable",
    "RunAssessments",
]
