"""Pins, promotion, assessment recording, frontier fulfillment and governed successors (WI-01).

Target signatures of IMPLEMENTATION §2 over the existing ports:

* :meth:`OutputFulfillmentService.register_promises` records the admitted
  ``EffectiveRunConfiguration.output_promises`` of a run: the set (with its closed completion,
  the only completion ever evaluated) and revision 1 of every promise.
* :meth:`~OutputFulfillmentService.pin_invocation` pins, at invocation start, the active
  revision of every promise; ``submit_output`` then always uses the pin.
* :meth:`~OutputFulfillmentService.promote_output` moves one deliverable's accepted head by
  expected-head and generation compare-and-set; drafts never move it, an older revision never
  replaces a newer head, and of two concurrent promotions exactly one wins.
* :meth:`~OutputFulfillmentService.record_assessment` is the host-access recording interface
  (``AssessmentRecorder``); the trusted knowledge bridge (``application/knowledge/judgment.py``,
  WI-03) records through it. Nobody judges an output they produced, a retry of the same judgment
  is the same row, and only the bridge supersedes an assessment: same exact subject, citing a KS
  successor decision of the decision the superseded assessment rested on.
* :meth:`~OutputFulfillmentService.pin_frontier` atomically pins the current accepted set;
  :meth:`~OutputFulfillmentService.evaluate_frontier` decides every declared promise against
  exactly that set under the admitted completion and records immutable decisions.
* :meth:`~OutputFulfillmentService.activate_contract_successor` admits a governed revision as
  *pending*; :meth:`~OutputFulfillmentService.activate_at_boundary` makes it active only when
  the host reports the declared boundary as reached, by compare-and-set.
* :meth:`~OutputFulfillmentService.resolve_missing_submission` applies the one-reminder /
  one-unambiguous-association / one-repair rule for a missing required submission.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from mission_control.application.knowledge.access import InvocationAccess
from mission_control.application.outputs.submission_service import SubmissionService
from mission_control.application.ports.outputs import (
    AcceptedHead,
    OlderRevision,
    OutputContractStore,
    PromisesConflict,
    StaleGeneration,
    StaleHead,
    StaleObligationRevision,
)
from mission_control.domain.knowledge.judgment import (
    KS_DECISION_EVIDENCE_PREFIX,
    TRUSTED_BRIDGE_ACTOR,
    JudgmentRefusal,
    cited_decisions,
    official_use_evidence,
    supersession_refusal,
)
from mission_control.domain.outputs.collections import (
    cited_member_decisions,
    collection_members,
    decide_collection,
)
from mission_control.domain.outputs.contracts import (
    AdmittedBinding,
    Assessment,
    AssessmentResult,
    CandidateRef,
    Enforcement,
    EvaluationScope,
    ExactOutput,
    Finding,
    FulfillmentResult,
    MemberDecisions,
    OutputError,
    OutputErrorCode,
    OutputForm,
    OutputObligation,
    OutputPromiseSet,
    OutputSet,
    SubmissionAck,
    SubmitOutput,
    TrustedValidators,
    tagged_digest,
)
from mission_control.domain.outputs.fulfillment import (
    EffectReceiptProof,
    evaluate_frontier_decisions,
    listed_members,
)
from mission_control.domain.outputs.rules import CandidateRefused, check_candidate
from mission_control.domain.outputs.successors import (
    SAFE_BOUNDARIES,
    ContractRevisionProposal,
    RegisteredCandidate,
    SuccessorInvalid,
    WeakeningGrant,
    classify_successor,
    next_association,
)

_LOG = logging.getLogger(__name__)
_ASSESSMENT_NAMESPACE = UUID("8f1d4a62-3c55-4c0e-9a7b-0e5b1e2f7a01")


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class HostAccess:
    """Host-authenticated access: never a producer-writable identity."""

    scope: str
    actor_ref: str
    origin_ref: str
    role: Literal["host", "assessor", "reconciler"] = "host"


@dataclass(frozen=True)
class AuthorAccess:
    """Who proposes a contract revision and which explicit authority they hold."""

    scope: str
    actor_id: str
    role: Literal["author", "operator", "coordinator", "executor"]
    delegation_refs: frozenset[str] = frozenset()
    weakening_grants: tuple[WeakeningGrant, ...] = ()


class PromoteOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(min_length=1)
    revision_id: str = Field(min_length=1)
    expected_head: str | None = None
    generation: int = Field(ge=1)


@dataclass(frozen=True)
class PromotionResult:
    status: Literal["promoted", "refused"]
    head: AcceptedHead | None = None
    error: OutputError | None = None


class AssessmentInput(BaseModel):
    """One independent judgment of an exact subject, as the host records it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(min_length=1)
    subject_kind: Literal["output_revision", "output_set", "member"]
    subject_id: str = Field(min_length=1)
    subject_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    requirement_results: dict[str, AssessmentResult] = Field(min_length=1)
    method_pin: str = Field(min_length=1)
    policy_pin: str = Field(min_length=1)
    evidence_refs: tuple[str, ...] = ()
    findings: tuple[Finding, ...] = ()
    # ``member``: the exact index revision that lists the member.
    index_revision_id: str | None = None
    supersedes: str | None = None


@dataclass(frozen=True)
class AssessmentReceipt:
    status: Literal["recorded", "refused"]
    assessment: Assessment | None = None
    error: OutputError | None = None


class SuccessorLineage(Protocol):
    """Resolves, through KS ``decision.resolve``, the successor chain of an exact decision cited as
    ``ks-use-decision:<id>@<digest>`` (WI-03 S6): supersession never trusts a supplied chain."""

    async def successor_chain(self, decision_evidence: str) -> tuple[str, ...]: ...


class AssessmentRecorder(Protocol):
    """Host-access interface for recording assessments (trusted composition is WI-03)."""

    async def record_assessment(
        self, access: HostAccess, assessment: AssessmentInput
    ) -> AssessmentReceipt: ...


@dataclass(frozen=True)
class OutputSetRef:
    run_id: str
    set_id: str


@dataclass(frozen=True)
class RevisionResult:
    status: Literal["pending", "activated", "refused"]
    obligation: OutputObligation | None = None
    weakenings: tuple[str, ...] = ()
    tightenings: tuple[str, ...] = ()
    error: OutputError | None = None


@dataclass(frozen=True)
class AssociationOutcome:
    action: Literal["not_missing", "remind", "associate", "request_repair", "block"]
    ack: SubmissionAck | None = None
    ambiguous: tuple[str, ...] = ()
    message: str = ""


# W1 D21 (OUTPUT-CONTRACTS §7): "The continuing profile requires a compact attributed progress
# note at each normal iteration handoff ... Crash records a missing note and retains host state; it
# never fabricates one." A handoff happens after a rejected verdict too, so a promise authored as a
# per-iteration record (``evaluation_scope: iteration``) of a shape-only form (text or
# control_record, no declared requirement) is satisfied by that iteration's own finalized
# submission whatever the verdict. Every other promise keeps the fix-D rule: only an accepted
# iteration's output becomes an accepted head (ESCALATION H12: exactness and authority; the
# reading is recorded in docs/knowledge/collections-and-current-sets.md).
ITERATION_RECORD_FORMS = frozenset({OutputForm.TEXT, OutputForm.CONTROL_RECORD})


def _iteration_record(obligation: OutputObligation) -> bool:
    return (
        obligation.evaluation_scope is EvaluationScope.ITERATION
        and obligation.contract.form in ITERATION_RECORD_FORMS
        and not obligation.contract.requirements
    )


def _member_judged_collection(obligation: OutputObligation) -> bool:
    """A collection judged only through its members: every declared requirement is a member
    requirement and at least one is required (review B1). An optional-only collection keeps the
    fix-D rule (any declared requirement belongs to the assessment path) and never auto-promotes
    unjudged."""

    contract = obligation.contract
    return (
        contract.form is OutputForm.COLLECTION
        and any(item.required for item in contract.requirements)
        and all(item.subject == "member" for item in contract.requirements)
    )


def _error(code: OutputErrorCode, message: str, **extra: Any) -> OutputError:
    return OutputError(code=code, safe_message=message[:500], **extra)


def _refused_assessment(code: OutputErrorCode, message: str, **extra: Any) -> AssessmentReceipt:
    return AssessmentReceipt("refused", error=_error(code, message, **extra))


class FileRealizationPort(Protocol):
    async def file_realizations(
        self, scope: str, source_refs: Sequence[str]
    ) -> Mapping[str, str]: ...


class ReferenceUsePort(Protocol):
    """Current official use of the exact revisions reference members name (WI-03).

    Answers, per reference revision id, the evidence ref of a current exact-use decision that
    admits official use now (resolved through the KS transport, never a cached decision).
    """

    async def reference_uses(
        self, scope: str, members: Sequence[ExactOutput]
    ) -> Mapping[str, str]: ...


class TrustedReferenceUses:
    """The production ``ReferenceUsePort`` (W1 D28): current official use of exact reference
    revisions from the trusted bridge's adjudicated record.

    A reference revision is officially usable when its newest standing assessment citing a KS
    decision, for exactly that revision id and digest, is ``pass``
    (``domain.knowledge.judgment.official_use_evidence``): the bridge records ``pass`` only from
    a KS resolution that is admitted, officially usable and not awaiting review, an approved
    review reaches MC as the bridge's superseding ``pass``, and a revocation as a later
    superseding non-pass (resume, or the consumer recheck before use). Nothing else (a held or
    pending decision, readable bytes, another revision with the same digest) is official use.
    """

    def __init__(self, store: OutputContractStore) -> None:
        self._store = store

    async def reference_uses(self, scope: str, members: Sequence[ExactOutput]) -> Mapping[str, str]:
        found: dict[str, str] = {}
        for run_id in sorted({member.run_id for member in members}):
            assessments = await self._store.output_assessments(scope, run_id)
            for member in members:
                if member.run_id != run_id:
                    continue
                evidence = official_use_evidence(
                    assessments, member.revision_id, member.content_digest
                )
                if evidence is not None:
                    found[member.revision_id] = evidence
        return found


class EffectReceiptPort(Protocol):
    """The settled native effect each effect-receipt member names (WI-05, OC-D117).

    Answers, per effect-receipt revision id, the host's proof of the exact effect key the
    candidate names: applied only once the effect settled from its protocol receipt (after a
    lost acknowledgment, from the reconstructed original receipt); pending or uncertain waits.
    """

    async def effect_receipts(
        self, scope: str, members: Sequence[ExactOutput]
    ) -> Mapping[str, EffectReceiptProof]: ...


class MemberDecisionPort(Protocol):
    """Which cited KS decisions are standing for exact collection members (WI-07 review B2').

    Answers, per member (ref, digest), the subset of the cited decision ids that exist, are bound
    to exactly that member and are standing now (not revoked, superseded or expired), resolved
    through the KS transport. No port composed: nothing is verified, so trusted member
    requirements wait.
    """

    async def standing_member_decisions(
        self, scope: str, cited: Sequence[tuple[str, str, str]]
    ) -> MemberDecisions: ...


class OutputFulfillmentService:
    def __init__(
        self,
        store: OutputContractStore,
        submissions: SubmissionService,
        *,
        clock: Callable[[], datetime] = _utcnow,
        realizations: FileRealizationPort | None = None,
        reference_uses: ReferenceUsePort | None = None,
        effect_receipts: EffectReceiptPort | None = None,
        refresh_on_change: bool = False,
        trusted_validators: TrustedValidators = None,
        member_decisions: MemberDecisionPort | None = None,
    ) -> None:
        # WI-07 review B2/B2'/N1: collection member requirements under the application's
        # trusted-judgment pin count only bridge-recorded assessments citing a KS decision the
        # host verified standing for that exact member (``member_decisions``). ``None`` (no pin
        # configured) treats every validator as trusted: fail closed, never open.
        self._trusted_validators = trusted_validators
        self._member_decisions = member_decisions
        # W1 (OVE-169): production re-decides the run's fulfillment after every head move and
        # every recorded assessment, so `output.fulfilled` / `output.fulfillment_unmet` reach the
        # coordinator from the real write, not only at the run's convergence boundary.
        self._refresh_on_change = refresh_on_change
        # WI-02: where file revisions were read back through an actual receiving backend.
        self._realizations = realizations
        self._reference_uses = reference_uses
        self._effect_receipts = effect_receipts
        self._store = store
        self._submissions = submissions
        self._clock = clock

    # ------------------------------------------------------------------ promises and pins

    async def register_promises(
        self,
        access: HostAccess,
        run_id: str,
        promises: OutputPromiseSet,
        *,
        configuration_digest: str | None = None,
    ) -> tuple[OutputObligation, ...] | OutputError:
        try:
            return await self._store.register_promises(
                access.scope,
                run_id,
                promises,
                configuration_digest=configuration_digest,
                actor_ref=access.actor_ref,
                at=self._clock(),
            )
        except PromisesConflict as conflict:
            return _error(
                OutputErrorCode.PROMISES_CONFLICT,
                str(conflict),
                retry_state="terminal",
                recovery_owner="host",
                available_actions=("activate_contract_successor",),
            )

    async def pin_invocation(
        self, access: HostAccess, invocation: InvocationAccess
    ) -> Mapping[str, int]:
        """At invocation start: pin the active revision of every promise of the run."""

        identity = invocation.identity()
        return await self._store.pin_invocation(
            access.scope,
            identity.run_id,
            identity.invocation_ref,
            actor_ref=access.actor_ref,
            at=self._clock(),
        )

    # ------------------------------------------------------------------ promotion

    async def promote_output(self, access: HostAccess, request: PromoteOutput) -> PromotionResult:
        """Move one deliverable's accepted head; a stale head, generation or revision refuses."""

        revision = await self._store.output_revision(access.scope, request.revision_id)
        if revision is None:
            return PromotionResult(
                "refused",
                error=_error(OutputErrorCode.SUBJECT_UNKNOWN, "no such output revision"),
            )
        if revision.run_id != request.run_id:
            return PromotionResult(
                "refused",
                error=_error(
                    OutputErrorCode.RUN_MISMATCH,
                    f"{revision.revision_id} belongs to another run",
                    retry_state="terminal",
                    recovery_owner="host",
                ),
            )
        try:
            head = await self._store.promote(
                access.scope,
                request.run_id,
                revision,
                expected_head=request.expected_head,
                generation=request.generation,
                actor_ref=access.actor_ref,
                at=self._clock(),
            )
        except StaleHead as stale:
            return PromotionResult(
                "refused",
                error=_error(
                    OutputErrorCode.STALE_HEAD,
                    f"accepted head is {stale.current}, not {request.expected_head}",
                    retry_state="retryable",
                    recovery_owner="host",
                    available_actions=("inspect_head", "promote_output"),
                ),
            )
        except StaleGeneration as stale:
            return PromotionResult(
                "refused",
                error=_error(
                    OutputErrorCode.STALE_GENERATION,
                    str(stale),
                    retry_state="terminal",
                    recovery_owner="host",
                ),
            )
        except OlderRevision as older:
            return PromotionResult(
                "refused",
                error=_error(
                    OutputErrorCode.OLDER_REVISION,
                    str(older),
                    retry_state="terminal",
                    recovery_owner="host",
                ),
            )
        await self._refresh(access, request.run_id)
        return PromotionResult("promoted", head=head)

    # ------------------------------------------------------------------ assessments

    async def record_assessment(
        self,
        access: HostAccess,
        assessment: AssessmentInput,
        *,
        lineage: SuccessorLineage | None = None,
    ) -> AssessmentReceipt:
        if access.role not in {"host", "assessor"}:
            return _refused_assessment(
                OutputErrorCode.ASSESSOR_UNAUTHORIZED,
                f"a {access.role} does not record assessments",
                retry_state="terminal",
                recovery_owner="host",
            )
        if access.actor_ref != TRUSTED_BRIDGE_ACTOR and any(
            ref.startswith(KS_DECISION_EVIDENCE_PREFIX) for ref in assessment.evidence_refs
        ):
            # WI-07 review B2': only the trusted bridge cites an exact KS decision; a host or
            # assessor never asserts one (first-time passes and supersessions alike).
            return _refused_assessment(
                OutputErrorCode.ASSESSOR_UNAUTHORIZED,
                "only the trusted knowledge bridge records KS decision evidence",
                retry_state="terminal",
                recovery_owner="host",
            )
        producers: set[str] = set()
        index_revision_id: str | None = None
        if assessment.subject_kind in {"output_revision", "member"}:
            revision_id = (
                assessment.subject_id
                if assessment.subject_kind == "output_revision"
                else assessment.index_revision_id
            )
            subject = (
                None
                if revision_id is None
                else await self._store.output_revision(access.scope, revision_id)
            )
            if subject is None or subject.run_id != assessment.run_id:
                return _refused_assessment(
                    OutputErrorCode.SUBJECT_UNKNOWN,
                    "the assessment names no exact output revision of this run",
                )
            if assessment.subject_kind == "output_revision":
                if subject.content_digest != assessment.subject_digest:
                    return _refused_assessment(
                        OutputErrorCode.SUBJECT_UNKNOWN, "the digest is not the revision's"
                    )
            else:
                index = await self._store.obligation_revision(
                    access.scope,
                    subject.run_id,
                    subject.obligation_key,
                    subject.obligation_revision,
                )
                nested = None if index is None else index.contract.member_contract
                if index is not None and index.contract.form is OutputForm.COLLECTION:
                    # WI-07: a collection lists its exact manifest members; each is judged
                    # alone (one member's assessment never attests another).
                    listed = set(collection_members(subject))
                else:
                    listed = (
                        set() if nested is None else set(listed_members(subject, nested.pointer))
                    )
                if (assessment.subject_id, assessment.subject_digest) not in listed:
                    return _refused_assessment(
                        OutputErrorCode.MEMBER_NOT_LISTED,
                        "the index revision does not list this exact member",
                    )
                index_revision_id = subject.revision_id
            producers.add(subject.producer_origin_ref)
        else:
            pinned = await self._store.output_set(access.scope, assessment.subject_id)
            if pinned is None or pinned.membership_digest != assessment.subject_digest:
                return _refused_assessment(
                    OutputErrorCode.SUBJECT_UNKNOWN, "no such exact output set"
                )
            producers |= {member.producer_origin_ref for member in pinned.members}
        if access.origin_ref in producers:
            return _refused_assessment(
                OutputErrorCode.SELF_ASSESSMENT,
                "a producer never assesses its own output",
                retry_state="terminal",
                recovery_owner="host",
            )
        if assessment.supersedes is not None:
            standing = await self._store.output_assessments(access.scope, assessment.run_id)
            prior = next(
                (item for item in standing if item.assessment_id == assessment.supersedes), None
            )
            chain: tuple[str, ...] = ()
            if prior is not None and lineage is not None:
                cited = [ref for ref in prior.evidence_refs if cited_decisions((ref,))]
                if cited:
                    chain = await lineage.successor_chain(cited[0])
            refusal = (
                JudgmentRefusal.SUPERSESSION_SUBJECT_MISMATCH
                if prior is None
                else supersession_refusal(
                    role=access.role,
                    actor_ref=access.actor_ref,
                    prior_subject=(prior.subject_kind, prior.subject_id, prior.subject_digest),
                    new_subject=(
                        assessment.subject_kind,
                        assessment.subject_id,
                        assessment.subject_digest,
                    ),
                    prior_evidence=prior.evidence_refs,
                    successor_chain=chain,
                    prior_result=prior.result,
                )
            )
            if refusal is not None:
                return _refused_assessment(
                    OutputErrorCode(refusal.value),
                    "only the trusted knowledge bridge supersedes an assessment of the same "
                    "exact subject, citing its KS successor decision",
                    retry_state="terminal",
                    recovery_owner="host",
                )
        results = set(assessment.requirement_results.values())
        overall: AssessmentResult = (
            "fail"
            if "fail" in results
            else "unavailable"
            if "unavailable" in results
            else "review"
            if "review" in results
            else "pass"
        )
        identity = {
            "run_id": assessment.run_id,
            "subject": [assessment.subject_kind, assessment.subject_id, assessment.subject_digest],
            "index_revision_id": index_revision_id,
            "results": dict(sorted(assessment.requirement_results.items())),
            "assessor": access.origin_ref,
            "method": assessment.method_pin,
            "policy": assessment.policy_pin,
            "evidence": list(assessment.evidence_refs),
            "supersedes": assessment.supersedes,
        }
        record = Assessment(
            # Deterministic: a retry of the same judgment is the same row.
            assessment_id=str(
                uuid5(_ASSESSMENT_NAMESPACE, tagged_digest("mc.output_assessment.v1", identity))
            ),
            subject_kind=assessment.subject_kind,
            subject_id=assessment.subject_id,
            subject_digest=assessment.subject_digest,
            requirement_results=dict(assessment.requirement_results),
            result=overall,
            assessor_origin_ref=access.origin_ref,
            method_pin=assessment.method_pin,
            policy_pin=assessment.policy_pin,
            evidence_refs=assessment.evidence_refs,
            findings=assessment.findings,
            index_revision_id=index_revision_id,
            supersedes=assessment.supersedes,
        )
        stored = await self._store.record_output_assessment(
            access.scope, assessment.run_id, record, actor_ref=access.actor_ref, at=self._clock()
        )
        await self._refresh(access, assessment.run_id)
        return AssessmentReceipt("recorded", assessment=stored)

    # ------------------------------------------------------------------ frontier

    async def pin_frontier(self, access: HostAccess, run_id: str) -> OutputSet:
        """Atomically pin the current accepted set: active promise revisions and exact heads."""

        return await self._store.pin_set(
            access.scope, run_id, actor_ref=access.actor_ref, at=self._clock()
        )

    async def evaluate_frontier(
        self,
        access: HostAccess,
        frontier: OutputSetRef,
        *,
        facts: Mapping[str, bool | None] | None = None,
    ) -> FulfillmentResult:
        """Decide every declared promise against exactly the pinned set's members, under the
        completion admitted with the run's promises (never a caller-supplied expression)."""

        pinned = await self._store.output_set(access.scope, frontier.set_id)
        if pinned is None:
            raise LookupError(f"no output set {frontier.set_id}")
        admitted = await self._store.promise_set(access.scope, frontier.run_id)
        if admitted is None:
            raise LookupError(f"run {frontier.run_id} registered no promises")
        obligations = await self._pinned_obligations(access.scope, frontier.run_id, pinned)
        assessments = await self._store.output_assessments(access.scope, frontier.run_id)
        files = [m for m in pinned.members if m.form is OutputForm.FILE]
        realized = (
            await self._realizations.file_realizations(access.scope, [m.revision_id for m in files])
            if files and self._realizations is not None
            else {}
        )
        references = [m for m in pinned.members if m.form is OutputForm.REFERENCE]
        uses = (
            await self._reference_uses.reference_uses(access.scope, references)
            if references and self._reference_uses is not None
            else {}
        )
        effects = [m for m in pinned.members if m.form is OutputForm.EFFECT_RECEIPT]
        if effects and self._effect_receipts is None:
            # Never wait forever on evidence nobody can deliver: an uncomposed port is a host fault.
            proofs: Mapping[str, EffectReceiptProof] = {
                m.revision_id: EffectReceiptProof(
                    "not_applied",
                    code="EFFECT_EVIDENCE_UNWIRED",
                    reason="this host composes no effect-receipt evidence port",
                )
                for m in effects
            }
        elif effects and self._effect_receipts is not None:
            proofs = await self._effect_receipts.effect_receipts(access.scope, effects)
        else:
            proofs = {}
        result = evaluate_frontier_decisions(
            obligations,
            admitted.completion,
            pinned,
            assessments,
            facts=facts,
            realizations=realized,
            reference_uses=uses,
            effect_receipts=proofs,
            trusted_validators=self._trusted_validators,
            member_decisions=await self._verified_members(
                access.scope, obligations, pinned.members, assessments
            ),
            unaccepted=await self._unaccepted(access.scope, frontier.run_id, obligations, pinned),
        )
        for decided in result.fulfillments:
            await self._store.record_fulfillment(
                access.scope,
                frontier.run_id,
                pinned.set_id,
                decided,
                actor_ref=access.actor_ref,
                at=self._clock(),
            )
        return result

    async def converge(
        self,
        access: HostAccess,
        run_id: str,
        *,
        operation_ref: str,
        generation: int,
        promote: bool = True,
        operation_attempt: int | None = None,
        execution_generation: int | None = None,
        owner_position: str | None = None,
    ) -> FulfillmentResult | None:
        """The convergence boundary's explicit fulfillment of a run (W1, OVE-169); None for a
        run that registered no promises.

        A collection whose requirements are all member requirements (WI-07) is promoted the
        same way only when its members' own standing assessments satisfy its aggregate rule.
        A promise whose contract declares no requirement has no layer beyond the shape its
        submission act already proved, so, when ``promote`` (the verifier accepted this
        iteration), the host promotes the newest revision per deliverable that ``operation_ref``
        submitted in a finalized invocation (expected-head compare-and-set; a concurrent
        promotion wins and stands). A rejected iteration's output never becomes an accepted head
        a later iteration could be judged by. A promise that declares any requirement (required
        or optional) is promoted only by its assessment path (WI-03, ``_trusted``). Then the
        accepted set is pinned and every declared promise decided against exactly it, recording
        ``Fulfillment@1`` rows (idempotent per set and decision): required absence blocks,
        expected shortfall is visible, optional absence is silent.
        """

        if await self._store.promise_set(access.scope, run_id) is None:
            return None
        assessments: tuple[Assessment, ...] | None = None
        for obligation in await self._store.active_obligations(access.scope, run_id):
            if owner_position is not None and obligation.owner_position != owner_position:
                continue
            collection = _member_judged_collection(obligation)
            if obligation.contract.requirements and not collection:
                continue  # fix D: any declared requirement belongs to the assessment path
            if not promote and not _iteration_record(obligation):
                continue  # only an accepted iteration's output becomes an accepted head
            submitted = await self._store.submitted_outputs(
                access.scope,
                run_id,
                obligation.key,
                operation_ref=operation_ref,
                operation_attempt=operation_attempt,
                execution_generation=execution_generation,
            )
            if collection:
                # WI-07: a collection whose requirements are all member requirements is promoted
                # by the host only when its exact members' own independent assessments satisfy
                # the authored aggregate rule (never from the producer or one member's verdict).
                if assessments is None:
                    assessments = await self._store.output_assessments(access.scope, run_id)
                judged_now = assessments
                verified = await self._verified_members(
                    access.scope, (obligation,), submitted, judged_now
                )
                submitted = tuple(
                    item
                    for item in submitted
                    if not decide_collection(
                        obligation,
                        item,
                        judged_now,
                        trusted_validators=self._trusted_validators,
                        member_decisions=verified,
                    ).unmet
                )
            for revision in submitted:
                head = await self._store.accepted_head(
                    access.scope, run_id, obligation.key, revision.deliverable_id
                )
                if head is not None and head.revision_id == revision.revision_id:
                    continue
                await self._promote_quietly(
                    access,
                    PromoteOutput(
                        run_id=run_id,
                        revision_id=revision.revision_id,
                        expected_head=None if head is None else head.revision_id,
                        generation=generation,
                    ),
                )
        pinned = await self.pin_frontier(access, run_id)
        return await self.evaluate_frontier(
            access, OutputSetRef(run_id=run_id, set_id=pinned.set_id)
        )

    async def _verified_members(
        self,
        scope: str,
        obligations: Sequence[OutputObligation],
        outputs: Sequence[ExactOutput],
        assessments: Sequence[Assessment],
    ) -> MemberDecisions:
        """The KS decisions verified standing per exact collection member (B2'); empty when no
        verification port is composed (trusted member requirements then wait)."""

        cited: set[tuple[str, str, str]] = set()
        for obligation in obligations:
            if obligation.contract.form is not OutputForm.COLLECTION:
                continue
            mine = [item for item in outputs if item.obligation_key == obligation.key]
            cited |= set(
                cited_member_decisions(
                    obligation, mine, assessments, trusted_validators=self._trusted_validators
                )
            )
        if not cited or self._member_decisions is None:
            return {}
        return await self._member_decisions.standing_member_decisions(scope, sorted(cited))

    async def _unaccepted(
        self,
        scope: str,
        run_id: str,
        obligations: Sequence[OutputObligation],
        pinned: OutputSet,
    ) -> dict[str, int]:
        """Per promise, the distinct deliverables with a finalized submission under the pinned
        revision but no accepted head in the set (W1 D29: visible, never reported missing)."""

        heads = {(m.obligation_key, m.deliverable_id) for m in pinned.members}
        revisions = {item.key: item.revision for item in obligations}
        pending: dict[str, set[str]] = {}
        for item in await self._store.finalized_outputs(scope, run_id):
            if revisions.get(item.obligation_key) != item.obligation_revision:
                continue
            if (item.obligation_key, item.deliverable_id) in heads:
                continue
            pending.setdefault(item.obligation_key, set()).add(item.deliverable_id)
        return {key: len(value) for key, value in pending.items()}

    async def _promote_quietly(self, access: HostAccess, request: PromoteOutput) -> None:
        refresh, self._refresh_on_change = self._refresh_on_change, False
        try:
            await self.promote_output(access, request)
        finally:
            self._refresh_on_change = refresh

    async def _refresh(self, access: HostAccess, run_id: str) -> None:
        """Best effort, after the committing write: re-decide the run's fulfillment so the
        attention events fire from it. A failure here never undoes or fails the promotion or
        assessment that already committed; it is logged, and the convergence boundary
        (:meth:`converge`) recomputes the decision anyway."""

        if not self._refresh_on_change:
            return
        try:
            if await self._store.promise_set(access.scope, run_id) is None:
                return
            pinned = await self.pin_frontier(access, run_id)
            await self.evaluate_frontier(access, OutputSetRef(run_id=run_id, set_id=pinned.set_id))
        except Exception:
            _LOG.warning("fulfillment refresh after a committed change failed", exc_info=True)

    async def _pinned_obligations(
        self, scope: str, run_id: str, pinned: OutputSet
    ) -> tuple[OutputObligation, ...]:
        found: list[OutputObligation] = []
        for key, revision in pinned.obligation_refs:
            # A frontier keeps the revision it pinned, even after a successor activated.
            obligation = await self._store.obligation_revision(scope, run_id, key, revision)
            if obligation is None:
                raise LookupError(f"obligation {key}@{revision} is not recorded")
            found.append(obligation)
        return tuple(found)

    # ------------------------------------------------------------------ successors

    async def activate_contract_successor(
        self, access: AuthorAccess, proposal: ContractRevisionProposal
    ) -> RevisionResult:
        """Admit a governed revision as pending; it activates only at its declared boundary."""

        if proposal.transfer_successor is not None:
            return RevisionResult(
                "refused",
                error=_error(
                    OutputErrorCode.TRANSFER_SUCCESSOR_UNSUPPORTED,
                    "transfer-policy successors are delivered with the sealed plan (WI-02)",
                    retry_state="terminal",
                    recovery_owner="host",
                ),
            )
        if proposal.boundary not in SAFE_BOUNDARIES:
            return RevisionResult(
                "refused",
                error=_error(
                    OutputErrorCode.UNSAFE_BOUNDARY,
                    f"{proposal.boundary} is not a safe future boundary",
                ),
            )
        if proposal.actor_id != access.actor_id or proposal.actor_role != access.role:
            return RevisionResult(
                "refused",
                error=_error(
                    OutputErrorCode.WEAKENING_UNAUTHORIZED,
                    "the proposal's actor is not the authenticated author",
                    retry_state="terminal",
                ),
            )
        if proposal.delegation_ref not in access.delegation_refs:
            return RevisionResult(
                "refused",
                error=_error(
                    OutputErrorCode.DELEGATION_REQUIRED,
                    "the proposal's delegation is not held by the author",
                    retry_state="terminal",
                    recovery_owner="reviewer",
                ),
            )
        active = {
            item.key: item
            for item in await self._store.active_obligations(access.scope, proposal.run_id)
        }
        prior = active.get(proposal.obligation_key)
        if prior is None:
            return RevisionResult(
                "refused",
                error=_error(OutputErrorCode.OBLIGATION_UNDECLARED, "no such admitted promise"),
            )
        if prior.revision != proposal.expected_prior_revision:
            return RevisionResult(
                "refused",
                error=_error(
                    OutputErrorCode.STALE_REVISION,
                    f"the active revision is {prior.revision}, not "
                    f"{proposal.expected_prior_revision}",
                    retry_state="retryable",
                ),
            )
        try:
            change = classify_successor(prior, proposal.successor)
        except SuccessorInvalid as invalid:
            return RevisionResult(
                "refused", error=_error(OutputErrorCode.SUCCESSOR_INVALID, str(invalid))
            )
        admitted = await self._store.promise_set(access.scope, proposal.run_id)
        if admitted is not None:
            try:
                # The admitted completion must still admit the promises with the successor in
                # place (e.g. expected -> required inside an ``any`` is not a conjunct).
                OutputPromiseSet(
                    obligations=tuple(
                        proposal.successor if item.key == proposal.obligation_key else item
                        for item in active.values()
                    ),
                    completion=admitted.completion,
                    integrity_checks=admitted.integrity_checks,
                    human_tasks=admitted.human_tasks,
                    criteria=admitted.criteria,
                )
            except ValidationError as broken:
                return RevisionResult(
                    "refused",
                    tightenings=change.tightenings,
                    error=_error(
                        OutputErrorCode.SUCCESSOR_BREAKS_COMPLETION,
                        "the admitted completion does not admit this successor: "
                        f"{broken.errors()[0]['msg']}",
                        retry_state="terminal",
                        recovery_owner="reviewer",
                    ),
                )
        if change.weakens:
            if access.role == "executor":
                return RevisionResult(
                    "refused",
                    weakenings=change.weakenings,
                    error=_error(
                        OutputErrorCode.SELF_WAIVER,
                        "an executor cannot waive or weaken its own promise",
                        retry_state="terminal",
                        recovery_owner="reviewer",
                    ),
                )
            authority = proposal.weakening_authority_ref
            grant = next(
                (
                    item
                    for item in access.weakening_grants
                    if item.ref == authority
                    and item.covers(access.scope, proposal.run_id, proposal.obligation_key)
                ),
                None,
            )
            if grant is None:
                return RevisionResult(
                    "refused",
                    weakenings=change.weakenings,
                    error=_error(
                        OutputErrorCode.WEAKENING_UNAUTHORIZED,
                        "weakening needs explicit delegated weakening authority for this run "
                        "and promise: " + "; ".join(change.weakenings),
                        retry_state="terminal",
                        recovery_owner="reviewer",
                    ),
                )
        try:
            pending = await self._store.propose_successor(
                access.scope,
                proposal.run_id,
                proposal.successor,
                expected_prior_revision=proposal.expected_prior_revision,
                proposal=proposal.document()
                | {
                    "weakenings": list(change.weakenings),
                    "tightenings": list(change.tightenings),
                    "proposal_digest": proposal.digest,
                },
                boundary=proposal.boundary,
                actor_ref=access.actor_id,
                at=self._clock(),
            )
        except StaleObligationRevision as stale:
            return RevisionResult(
                "refused",
                error=_error(
                    OutputErrorCode.STALE_REVISION,
                    f"the active revision is {stale.current} or a successor is already pending",
                    retry_state="retryable",
                ),
            )
        return RevisionResult(
            "pending",
            obligation=pending,
            weakenings=change.weakenings,
            tightenings=change.tightenings,
        )

    async def activate_at_boundary(
        self, access: HostAccess, run_id: str, *, boundary: str, boundary_ref: str
    ) -> tuple[OutputObligation, ...] | OutputError:
        """The host reports a boundary actually reached (e.g. ``between_iterations`` with the
        iteration ref); every pending successor declared for it becomes active by CAS.
        Invocations that already pinned keep their revision."""

        if access.role != "host":
            return _error(OutputErrorCode.HOST_REQUIRED, "only the host reports boundaries")
        if boundary not in SAFE_BOUNDARIES:
            return _error(OutputErrorCode.UNSAFE_BOUNDARY, f"{boundary} is not a safe boundary")
        return await self._store.activate_pending(
            access.scope,
            run_id,
            boundary=boundary,
            boundary_ref=boundary_ref,
            actor_ref=access.actor_ref,
            at=self._clock(),
        )

    # ------------------------------------------------------------------ association

    async def resolve_missing_submission(
        self,
        access: HostAccess,
        invocation: InvocationAccess,
        obligation_key: str,
        candidates: tuple[RegisteredCandidate, ...] = (),
        *,
        position: str,
        bindings: tuple[AdmittedBinding, ...] = (),
    ) -> AssociationOutcome:
        """One reminder; then one unambiguous registered candidate or named receipt is
        associated; then one ambiguity repair; then the promise stays unmet and blocks."""

        identity = invocation.identity()
        pins = await self._store.invocation_pins(access.scope, identity.invocation_ref)
        revision = pins.get(obligation_key)
        obligation = (
            None
            if revision is None
            else await self._store.obligation_revision(
                access.scope, identity.run_id, obligation_key, revision
            )
        )
        if obligation is None:
            return AssociationOutcome("block", message="no promise pinned for this invocation")
        heads = [
            item
            for item in await self._store.accepted_outputs(access.scope, identity.run_id)
            if item.obligation_key == obligation_key
        ]
        submitted = await self._submissions.submitted_obligations(
            identity.scope, identity.invocation_ref
        )
        if (
            heads
            or obligation_key in submitted
            or obligation.enforcement is not Enforcement.REQUIRED
        ):
            return AssociationOutcome("not_missing")
        unique: dict[str, CandidateRef] = {}
        for item in candidates:
            if self._matches(obligation, item, bindings):
                unique.setdefault(
                    tagged_digest("mc.candidate.v1", item.candidate.document()), item.candidate
                )
        matching = tuple(
            RegisteredCandidate(candidate=candidate, source="registered_output")
            for candidate in unique.values()
        )
        taken = await self._store.association_steps(
            access.scope, identity.invocation_ref, obligation_key
        )
        decision = next_association(taken, matching)
        if decision.action == "associate" and decision.candidate is not None:
            ack = await self._submissions.submit_output(
                invocation,
                SubmitOutput(
                    submission_key=f"auto-association:{obligation_key}",
                    obligation_key=obligation_key,
                    mode="final",
                    items=(decision.candidate,),
                ),
                position=position,
                bindings=bindings,
                caller_origin_ref=access.origin_ref,
            )
            # Only an accepted association is recorded as one; a refused one is the repair.
            step = "auto_associated" if ack.status == "accepted" else "repair_requested"
            await self._step(
                access,
                identity.run_id,
                identity.invocation_ref,
                obligation_key,
                step,
                {"candidate_digest": decision.candidate.digest},
            )
            if ack.status == "accepted":
                return AssociationOutcome("associate", ack=ack)
            return AssociationOutcome(
                "request_repair", ack=ack, message="the associated candidate was refused"
            )
        step = {"remind": "reminder", "request_repair": "repair_requested", "block": "blocked"}[
            decision.action
        ]
        detail = {"ambiguous": sorted(item.digest for item in decision.ambiguous)}
        recorded = await self._step(
            access, identity.run_id, identity.invocation_ref, obligation_key, step, detail
        )
        if not recorded and decision.action != "block":
            # Another worker took this step first: answer from the state it left.
            return await self.resolve_missing_submission(
                access,
                invocation,
                obligation_key,
                candidates,
                position=position,
                bindings=bindings,
            )
        if decision.action == "request_repair":
            return AssociationOutcome(
                "request_repair",
                ambiguous=tuple(item.digest for item in decision.ambiguous),
                message=f"{len(decision.ambiguous)} candidates match; submit one exactly",
            )
        if decision.action == "remind":
            return AssociationOutcome(
                "remind", message=f"required output {obligation_key} has not been submitted"
            )
        return AssociationOutcome("block", message=f"{obligation_key} remains unmet")

    async def _step(
        self,
        access: HostAccess,
        run_id: str,
        invocation_ref: str,
        obligation_key: str,
        step: str,
        detail: Mapping[str, Any],
    ) -> bool:
        return await self._store.record_association_step(
            access.scope,
            run_id,
            invocation_ref,
            obligation_key,
            step,
            detail,
            actor_ref=access.actor_ref,
            at=self._clock(),
        )

    def _matches(
        self,
        obligation: OutputObligation,
        registered: RegisteredCandidate,
        bindings: tuple[AdmittedBinding, ...],
    ) -> bool:
        """A registered candidate, or a receipt of a capability the promise names, that passes
        exactly the checks ``submit_output`` would apply."""

        if registered.source == "named_capability_receipt" and (
            registered.capability_ref not in obligation.contract.receipt_capabilities
        ):
            return False
        try:
            check_candidate(
                obligation,
                registered.candidate,
                bindings=bindings,
                validate_schema=self._submissions.validate_schema,
            )
        except CandidateRefused:
            return False
        return True


__all__ = [
    "AssessmentInput",
    "AssessmentReceipt",
    "AssessmentRecorder",
    "AssociationOutcome",
    "AuthorAccess",
    "EffectReceiptPort",
    "HostAccess",
    "MemberDecisionPort",
    "OutputFulfillmentService",
    "OutputSetRef",
    "PromoteOutput",
    "PromotionResult",
    "RevisionResult",
    "TrustedReferenceUses",
]
