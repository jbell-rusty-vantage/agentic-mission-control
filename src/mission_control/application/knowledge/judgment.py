"""The trusted judgment bridge (Sprint OC WI-03 / OVE-165; OUTPUT-CONTRACTS §§4-5, ADR-0059/0060).

Ordinary independent judgments reach trusted Knowledge Services sealing, use and review decisions
through one path, never self-recorded and never through process memory:

1. **Admission of evaluators.** Each judge, second-family judge or auditor is a *separate* admitted
   invocation (:class:`EvaluatorBinding`): its own credential reference, origin subject and
   operation; a judge runs on another vendor than the producer and on the application's
   ``judge.default`` pin. :func:`~mission_control.domain.knowledge.judgment.evaluator_refusals`
   refuses a producer credential before anything is sent.
2. **Observation.** The evaluator's cognition (:class:`EvaluatorRunner`: the MC-hosted Deep
   Agents judge/auditor operation; scripted in deterministic proofs) is retried within
   :class:`EvaluatorRetryPolicy`; its observations go to KS ``report.observe`` under a credential
   carrying the host's evaluator grant. Exhausted retries record an ``unavailable`` assessment and
   answer ``waiting`` (``evaluator_unavailable``): completed producer cognition is kept.
3. **Seal and decide.** The host seals the exact VerificationRun (``report.seal``) and asks for the
   official use decision (``report.decide``); ``decision.resolve`` answers current eligibility.
4. **Record.** One ``Assessment@1`` per exact output revision, by the bridge's own assessor
   origin (the KS decision, never the producer), citing the exact KS decision as evidence.
   Only a KS rejection fails; ungrounded disagreement holds; a pending review waits.
5. **Promote.** A passing trusted assessment promotes the revision through the existing
   ``promote_output`` compare-and-set when every required requirement of its obligation stands
   at ``pass``; a held, review or failed verdict never promotes.
6. **Resume.** After a restart, :meth:`TrustedJudgmentBridge.resume` re-resolves the exact
   decision through KS; a successor supersedes the earlier assessment (only the bridge may) and
   a passing successor promotes.

Official use versus authorized held review/repair (:meth:`TrustedJudgmentBridge.use_gate`) applies
the application's output-contract minimums to the current KS resolution.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol
from uuid import uuid4

from mission_control.application.knowledge.access import InvocationAccess, instant
from mission_control.application.knowledge.gateway import KnowledgeGateway, TrustedAnswer
from mission_control.application.knowledge.operations import KnowledgeRefused
from mission_control.application.outputs.fulfillment import (
    AssessmentInput,
    HostAccess,
    OutputFulfillmentService,
    PromoteOutput,
)
from mission_control.application.ports.knowledge import RecordedUseDecision, UseDecisionRecorder
from mission_control.application.ports.outputs import (
    AssessmentSupersessionConflict,
    OutputContractStore,
)
from mission_control.contracts.knowledge_assessment import (
    Build,
    CredentialEvaluation,
    DecisionResolution,
    DecisionResolveRequest,
    EvaluatorRole,
    ReportObservationRequest,
    ReportReviewRequest,
    ReportSealRequest,
    ReportUseRequest,
    UsePurpose,
)
from mission_control.contracts.knowledge_protocol import Budget, Governors, Ref, digest_canonical
from mission_control.domain.knowledge.judgment import (
    TRUSTED_BRIDGE_ACTOR,
    CognitionIdentity,
    EvaluatorPin,
    JudgmentRefusal,
    UseGate,
    assessment_result,
    cited_decisions,
    decision_evidence,
    evaluator_refusals,
    use_gate,
)
from mission_control.domain.outputs.contracts import (
    Assessment,
    ExactOutput,
    Finding,
    OutputObligation,
)
from mission_control.domain.outputs.fulfillment import judged
from mission_control.domain.resolution.resolved import OutputContractProfile

TRUSTED_CAPABILITY_PIN = "knowledge.report.trusted-assessment@1"
_LOGGER = logging.getLogger(__name__)
BRIDGE_ACTOR = TRUSTED_BRIDGE_ACTOR
# W1 (OVE-169): an evaluator role KS had already recorded for the run (`evaluator_role_observed`,
# for example a batch recorded only in part) is treated as observed; the recorded assessment names
# each such role with this evidence ref, so inspection shows the partial-batch role lock.
ROLE_LOCK_EVIDENCE_PREFIX = "ks-evaluator-role-observed:"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class TrustedJudgmentRefused(RuntimeError):
    """A typed refusal on the trusted path (MC independence rule or KS refusal reason).

    ``issues`` are KS's bounded validation issues (W1 D20: ``path: message``); they ride in the
    message too, so the settlement log names what KS refused, not only that it refused."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        reason: str | None = None,
        issues: Sequence[str] = (),
        billed: bool = False,
    ) -> None:
        shown = "; ".join(issues[:5])
        suffix = f" [{reason}]" if reason else ""
        super().__init__(f"{code}: {message}{suffix}" + (f" -- {shown}" if shown else ""))
        self.code = code
        self.reason = reason
        self.issues = tuple(issues)
        # W1 D23: KS refused documents an evaluator run produced (that run was billed).
        self.billed = billed


class EvaluatorUnavailable(RuntimeError):
    """The evaluator's cognition could not run now (provider down, budget wait, quota).

    W1 D23: the message is the concrete, bounded and redacted cause (exception class and message,
    refusal, empty structured response, schema validation errors). ``billed`` says whether a
    model answered (a paid attempt the bridge bounds per exact revision and role); ``code``,
    ``reason`` and ``issues`` are what the settlement wait records (``SettlementOutcome.
    unavailable`` reads them duck-typed)."""

    def __init__(
        self,
        message: str,
        *,
        billed: bool = False,
        code: str = "EVALUATOR_UNAVAILABLE",
        reason: str | None = None,
        issues: Sequence[str] = (),
    ) -> None:
        super().__init__(message)
        self.billed = billed
        self.code = code
        self.reason = reason
        self.issues = tuple(issues)


@dataclass(frozen=True)
class EvaluatorBinding:
    """One separate admitted evaluator invocation: its own credential, origin and role."""

    role: EvaluatorRole
    credential_ref: str
    vendor: str | None
    family: str | None
    model_id: str | None
    access: InvocationAccess
    # W1 D16: how the evaluator's model row returns a structured response (None: undeclared).
    structured_output: str | None = None
    # W1 D24: the row's OpenAI API surface (`responses`: the Responses API).
    api_surface: str | None = None

    def identity(self) -> CognitionIdentity:
        return CognitionIdentity(
            credential_ref=self.credential_ref,
            subject=self.access.subject,
            operation_ref=self.access.origin.operation_id,
            vendor=self.vendor,
            model_id=self.model_id,
        )

    def grant(self) -> CredentialEvaluation:
        return CredentialEvaluation(
            role=self.role,
            credentialRef=self.credential_ref,
            provider=self.vendor,
            family=self.family,
        )


@dataclass(frozen=True)
class EvaluatorOutput:
    """An evaluator's typed output: research-core observation documents and, for the auditor,
    its independent census discovery pass."""

    observations: tuple[dict[str, Any], ...] = ()
    census: dict[str, Any] | None = None


@dataclass(frozen=True)
class JudgmentSubject:
    """What one trusted assessment judges: one exact output revision naming one KS report."""

    run_id: str
    revision: ExactOutput
    report: Ref
    producer: CognitionIdentity
    generation: int


class EvaluatorRunner(Protocol):
    """The MC-hosted evaluator cognition (a separate Deep Agents judge/auditor operation)."""

    async def evaluate(
        self, evaluator: EvaluatorBinding, subject: JudgmentSubject
    ) -> EvaluatorOutput:
        """Raise :class:`EvaluatorUnavailable` when the evaluator cannot run now."""
        ...


@dataclass(frozen=True)
class EvaluatorRetryPolicy:
    """Bounded evaluator retry before a durable, actionable wait (OC-D109; PROOFS §6).

    ``max_attempts`` bounds the evaluator runs of one pass, and (W1 D23) the *billed* runs of one
    role over one exact revision across every pass: the count is persisted on the revision's
    standing wait assessment (``mc-evaluator-attempts:<role>:<n>``), so a settlement pass after
    the bound never re-runs the paid evaluator; it waits with the recorded cause."""

    max_attempts: int = 2


@dataclass(frozen=True)
class UseSpec:
    """The official use the assessment decides (from the admitted run configuration)."""

    use: str
    audience: str
    policy: Ref
    rubric: Ref
    target_schema: str = "research-report.v2"


@dataclass(frozen=True)
class TrustedOutcome:
    """The settlement-facing outcome of one trusted assessment pass.

    ``state``: ``settled`` (a verdict is recorded: pass promotes; fail or a held decision stays
    unmet for repair), or ``waiting`` with ``reason`` ``review_pending`` (``pending_reviews``
    names the exact KS decisions) or ``evaluator_unavailable`` (retry later; cognition kept).
    """

    state: Literal["settled", "waiting"]
    result: Literal["pass", "fail", "review", "unavailable"]
    reason: Literal["review_pending", "evaluator_unavailable"] | None = None
    assessment: Assessment | None = None
    resolution: DecisionResolution | None = None
    pending_reviews: tuple[str, ...] = ()
    promoted: bool = False
    findings: tuple[str, ...] = field(default_factory=tuple)
    # Roles whose observations KS already held (the per-role cap): their first batch stands.
    locked_roles: tuple[str, ...] = ()
    # A revision promoted on an earlier pass whose current judgment is no longer a pass (a
    # post-promotion revocation): its accepted head stays in storage (heads are never deleted)
    # but no consumer admits it (`domain.knowledge.judgment.head_demoted`).
    demoted: bool = False
    # W1 D23: an ``evaluator_unavailable`` wait names the concrete cause per role
    # (``<role>: <cause>``); ``exhausted`` when a role's billed attempts reached the bound, so no
    # later pass re-runs it (an operator acts on the recorded cause).
    causes: tuple[str, ...] = ()
    exhausted: bool = False


def _governors(clock: Callable[[], datetime]) -> Governors:
    return Governors(
        deadline=instant(clock() + timedelta(minutes=10)),
        maxItems=64,
        partialResults="forbid",
        budget=Budget(calls=0, tokens=0, costUsd="0"),
    )


def _key(*parts: str) -> str:
    """A stable request id (≤ 200 chars) for one exact trusted operation."""

    return "wi03-" + digest_canonical(list(parts))[7:47]


# W1 D23: the evaluator attempt ledger of one exact revision, carried on its standing wait
# assessment (an ``unavailable`` record citing no KS decision): the billed runs per role and a
# digest of each role's latest cause (so a changed cause is a new record), the causes themselves
# as findings (``<role>: <cause>``, bounded and redacted).
ATTEMPTS_PREFIX = "mc-evaluator-attempts:"
CAUSE_PREFIX = "mc-evaluator-cause:"
CAUSE_FINDINGS = frozenset({"evaluator_unavailable", "evaluator_attempts_exhausted"})
MAX_CAUSE_CHARS = 400
# W1 fix G N1: a KS refusal recorded on the standing wait (D20) stays visible on every later wait.
KS_REFUSAL_PREFIX = "ks-refusal:"
# W1 fix G S2: an operator reset of a role's billed attempts, on the superseding wait it records.
RESET_PREFIX = "mc-evaluator-reset:"
RESET_FINDING = "evaluator_attempts_reset"
WAIT_ORIGIN_PREFIX = "mc-evaluator-wait:"
# W1 (auditor handle gap): the observe request id a role dispatched (written before the request
# is sent) and the role's observation KS holds (`<operation id>`, or `ks-held` when KS refused a
# second batch for the role). A later pass recovers a dispatched observation by `operation.get`
# and never re-runs the paid evaluator of an observed role.
DISPATCH_PREFIX = "mc-evaluator-dispatch:"
OBSERVED_PREFIX = "mc-evaluator-observed:"
KS_HELD = "ks-held"
# W1 fix G S1: each wait write is its own row (a unique write id), so two passes recording the same
# count can never collapse into one deduplicated row; the store's compare-and-set orders them.
WRITE_PREFIX = "mc-evaluator-write:"


def _write_ref() -> str:
    return f"{WRITE_PREFIX}{uuid4().hex[:16]}"


def _unwritten(refs: Sequence[str]) -> tuple[str, ...]:
    return tuple(ref for ref in refs if not ref.startswith(WRITE_PREFIX))


def evaluator_cause(error: BaseException) -> str:
    """The bounded, redacted cause of an evaluator failure (never a credential or local path)."""

    from mission_control.application.knowledge.redaction import redacted

    text = str(error).strip() or type(error).__name__
    return redacted(" ".join(text.split()), MAX_CAUSE_CHARS)


def _wait_evidence(
    attempts: dict[str, int], causes: dict[str, str], carried: Sequence[str] = ()
) -> tuple[str, ...]:
    return (
        *carried,
        *(f"{ATTEMPTS_PREFIX}{role}:{count}" for role, count in sorted(attempts.items()) if count),
        *(
            f"{CAUSE_PREFIX}{role}:{digest_canonical(text)[7:23]}"
            for role, text in sorted(causes.items())
        ),
    )


@dataclass(frozen=True)
class _Ledger:
    wait: Assessment | None
    attempts: dict[str, int]
    causes: dict[str, str]
    # N1: the standing wait's KS refusal evidence and findings, carried to its successor.
    refusal_refs: tuple[str, ...] = ()
    refusal_findings: tuple[Finding, ...] = ()
    # The observe request id each role dispatched, and what KS holds for each observed role.
    dispatched: dict[str, str] = field(default_factory=dict)
    observed: dict[str, str] = field(default_factory=dict)

    @property
    def carried(self) -> tuple[str, ...]:
        """Evidence every successor wait keeps: KS refusals, dispatches, observations."""

        return (
            *self.refusal_refs,
            *(f"{DISPATCH_PREFIX}{role}:{key}" for role, key in sorted(self.dispatched.items())),
            *(f"{OBSERVED_PREFIX}{role}:{held}" for role, held in sorted(self.observed.items())),
        )

    @classmethod
    def of(cls, wait: Assessment | None) -> _Ledger:
        attempts: dict[str, int] = {}
        causes: dict[str, str] = {}
        if wait is None:
            return cls(None, attempts, causes)
        for ref in wait.evidence_refs:
            if ref.startswith(ATTEMPTS_PREFIX):
                role, _, count = ref.removeprefix(ATTEMPTS_PREFIX).rpartition(":")
                if role and count.isdigit():
                    attempts[role] = int(count)
        for finding in wait.findings:
            if finding.code in CAUSE_FINDINGS and finding.pointer:
                causes[finding.pointer] = finding.message.removeprefix(f"{finding.pointer}: ")
        dispatched: dict[str, str] = {}
        observed: dict[str, str] = {}
        for ref in wait.evidence_refs:
            for prefix, into in ((DISPATCH_PREFIX, dispatched), (OBSERVED_PREFIX, observed)):
                if ref.startswith(prefix):
                    role, _, value = ref.removeprefix(prefix).partition(":")
                    if role and value:
                        into[role] = value
        return cls(
            wait,
            attempts,
            causes,
            tuple(ref for ref in wait.evidence_refs if ref.startswith(KS_REFUSAL_PREFIX)),
            tuple(f for f in wait.findings if f.code.startswith("ks_")),
            dispatched,
            observed,
        )

    def messages(self) -> tuple[str, ...]:
        return tuple(f"{role}: {text}" for role, text in sorted(self.causes.items()))


def standing_wait(rows: Sequence[Assessment], revision: ExactOutput) -> Assessment | None:
    """The standing evaluator wait of an exact revision: its unsuperseded ``unavailable``
    assessment citing no KS decision (one per revision; supersession is a compare-and-set)."""

    superseded = {row.supersedes for row in rows if row.supersedes is not None}
    waiting = [
        row
        for row in rows
        if row.subject_kind == "output_revision"
        and row.subject_id == revision.revision_id
        and row.subject_digest == revision.content_digest
        and row.result == "unavailable"
        and row.assessment_id not in superseded
        and not cited_decisions(row.evidence_refs)
    ]
    return waiting[-1] if waiting else None


def _cause_findings(
    causes: dict[str, str], attempts: dict[str, int], bound: int
) -> tuple[Finding, ...]:
    return tuple(
        Finding(
            code="evaluator_attempts_exhausted"
            if attempts.get(name, 0) >= bound
            else "evaluator_unavailable",
            message=f"{name}: {text}"[:500],
            pointer=name,
        )
        for name, text in sorted(causes.items())
    )


class EvaluatorWaitConflict(EvaluatorUnavailable):
    """W1 fix G S1: a concurrent writer replaced the standing wait twice while this pass
    recorded its evaluator attempt (re-read and retried once); the pass waits and retries."""

    def __init__(self, message: str, *, billed: bool = False) -> None:
        super().__init__(message, billed=billed, code="EVALUATOR_WAIT_CONFLICT")


class EvaluatorWaitUnrecorded(EvaluatorUnavailable):
    """W1 fix G S1: the evaluator attempt or its cause could not be recorded (never swallowed:
    the pass waits, and the log names the cause and the failed write)."""

    def __init__(self, message: str, *, billed: bool = False) -> None:
        super().__init__(message, billed=billed, code="EVALUATOR_WAIT_UNRECORDED")


class EvaluatorResetRefused(RuntimeError):
    """An operator reset refused: ``not_found`` (no such revision in the run) or
    ``nothing_to_reset`` (the role has no recorded billed attempt on that revision)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


async def _supersede_wait(
    fulfillment: OutputFulfillmentService,
    host: HostAccess,
    record: Callable[[_Ledger], AssessmentInput | None],
    read: Callable[[], Awaitable[_Ledger]],
    *,
    what: str,
    billed: bool,
) -> Assessment | None:
    """Record a new standing wait built by ``record`` from the current ledger, as a
    compare-and-set on the standing row: on a rival supersession re-read and retry once, then a
    typed :class:`EvaluatorWaitConflict`; any other failure is a typed
    :class:`EvaluatorWaitUnrecorded` (logged, never swallowed). ``record`` answering ``None``
    means nothing changed (the standing wait is returned)."""

    for attempt in (1, 2):
        ledger = await read()
        candidate = record(ledger)
        if candidate is None:
            return ledger.wait
        try:
            receipt = await fulfillment.record_assessment(host, candidate)
        except AssessmentSupersessionConflict as conflict:
            _LOGGER.warning("%s: the standing wait moved (%s); attempt %d", what, conflict, attempt)
            if attempt == 2:
                raise EvaluatorWaitConflict(
                    f"{what}: the standing wait moved twice while recording", billed=billed
                ) from conflict
            continue
        except Exception as error:
            _LOGGER.exception("%s was not recorded", what)
            raise EvaluatorWaitUnrecorded(
                f"{what} was not recorded: {type(error).__name__}", billed=billed
            ) from error
        if receipt.assessment is None:
            code = None if receipt.error is None else receipt.error.code
            _LOGGER.error("%s was refused: %s", what, code)
            raise EvaluatorWaitUnrecorded(f"{what} was refused: {code}", billed=billed)
        return receipt.assessment
    return None  # pragma: no cover - the loop returns or raises


class EvaluatorAttemptReset:
    """W1 fix G S2: the audited operator reset of a role's exhausted evaluator attempts.

    It records a new standing wait for the exact revision that supersedes the current one with
    the role's billed-attempt count and cause removed (every other role's count, cause and the
    KS refusal evidence carried), a ``mc-evaluator-reset:<role>:<digest>`` evidence ref and an
    ``evaluator_attempts_reset`` finding naming the operator and the reason; the assessor origin is
    ``mc-evaluator-reset:<revision>:<operator>``. Rows are immutable, so the reset stays on record
    after later waits supersede it. The next settlement pass may run the evaluator again (up to
    the bound). Authorization is the caller's (the operator review route)."""

    def __init__(
        self,
        fulfillment: OutputFulfillmentService,
        store: OutputContractStore,
        *,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._fulfillment = fulfillment
        self._store = store
        self._clock = clock

    async def reset(
        self,
        scope: str,
        run_id: str,
        revision_id: str,
        role: str,
        *,
        operator: str,
        reason: str,
    ) -> Assessment:
        revision = await self._store.output_revision(scope, revision_id)
        if revision is None or revision.run_id != run_id:
            raise EvaluatorResetRefused("not_found", f"no revision {revision_id} in run {run_id}")

        async def read() -> _Ledger:
            return _Ledger.of(
                standing_wait(await self._store.output_assessments(scope, run_id), revision)
            )

        first = await read()
        if first.wait is None or not first.attempts.get(role):
            raise EvaluatorResetRefused(
                "nothing_to_reset", f"the {role} has no recorded billed attempt on {revision_id}"
            )
        at = self._clock().isoformat()

        def record(ledger: _Ledger) -> AssessmentInput | None:
            wait = ledger.wait
            if wait is None or not ledger.attempts.get(role):
                return None
            attempts = {name: n for name, n in ledger.attempts.items() if name != role}
            causes = {name: text for name, text in ledger.causes.items() if name != role}
            stamp = digest_canonical([role, operator, reason, wait.assessment_id, at])[7:23]
            return AssessmentInput(
                run_id=run_id,
                subject_kind="output_revision",
                subject_id=revision.revision_id,
                subject_digest=revision.content_digest,
                requirement_results=dict.fromkeys(wait.requirement_results, "unavailable"),
                method_pin=wait.method_pin,
                policy_pin=wait.policy_pin,
                evidence_refs=(
                    *_wait_evidence(attempts, causes, ledger.carried),
                    f"{RESET_PREFIX}{role}:{stamp}",
                    _write_ref(),
                ),
                findings=(
                    *ledger.refusal_findings,
                    *_cause_findings(causes, attempts, 1 << 30),
                    Finding(
                        code=RESET_FINDING,
                        message=f"{role}: attempts reset by {operator}: {reason}"[:500],
                        pointer=role,
                    ),
                ),
                supersedes=wait.assessment_id,
            )

        host = HostAccess(
            scope=scope,
            actor_ref=BRIDGE_ACTOR,
            origin_ref=f"{RESET_PREFIX}{revision.revision_id}:{operator}",
            role="assessor",
        )
        recorded = await _supersede_wait(
            self._fulfillment,
            host,
            record,
            read,
            what=f"the {role} reset of {revision_id}",
            billed=False,
        )
        if recorded is None or recorded.assessment_id == first.wait.assessment_id:
            raise EvaluatorResetRefused(
                "nothing_to_reset", f"the {role} attempts on {revision_id} were already reset"
            )
        _LOGGER.warning(
            "evaluator attempts of %s on revision %s reset by %s: %s",
            role,
            revision_id,
            operator,
            reason,
        )
        return recorded


@dataclass(frozen=True)
class _Unavailable:
    """An evaluator that cannot judge now: its latest cause, and whether its billed attempts on
    this exact revision reached the bound (no later pass re-runs it)."""

    cause: str
    role: str
    exhausted: bool = False
    causes: tuple[str, ...] = ()


class TrustedJudgmentBridge:
    """Compose the KS trusted transport into MC assessments, promotion and resumable waits."""

    def __init__(
        self,
        *,
        gateway: KnowledgeGateway,
        fulfillment: OutputFulfillmentService,
        store: OutputContractStore,
        profile: OutputContractProfile,
        runner: EvaluatorRunner,
        judge_pin: EvaluatorPin | None,
        decisions: UseDecisionRecorder | None = None,
        retry: EvaluatorRetryPolicy | None = None,
        clock: Callable[[], datetime] = _utcnow,
        build: Build | None = None,
    ) -> None:
        self._gateway = gateway
        self._fulfillment = fulfillment
        self._store = store
        self._profile = profile
        self._runner = runner
        self._judge_pin = judge_pin
        self._decisions = decisions
        self._retry = retry or EvaluatorRetryPolicy()
        self._clock = clock
        self._build = build or Build(buildId="mission-control", runtime="python", dirty=False)

    # ------------------------------------------------------------------ assess

    async def assess(
        self,
        subject: JudgmentSubject,
        evaluators: Sequence[EvaluatorBinding],
        host: InvocationAccess,
        use: UseSpec,
    ) -> TrustedOutcome:
        """One full trusted pass: independent observations, seal, decision, record, promote."""

        self._admit(subject, evaluators)
        locked: list[str] = []
        for evaluator in evaluators:
            try:
                observed = await self._observe(subject, evaluator, host, use)
            except TrustedJudgmentRefused as refused:
                # W1 D20: what KS refused, durably on the revision (inspection, output events).
                await self._refused_record(subject, host, use, evaluator.role, refused)
                raise
            if isinstance(observed, _Unavailable):
                return await self._unavailable(subject, host, use, observed)
            if observed == "locked":
                locked.append(evaluator.role)
        try:
            sealed = await self._call(
                "report.seal",
                ReportSealRequest(
                    schema_="report-seal.v1", report=subject.report, build=self._build
                ),
                host,
                key=_key("seal", subject.report.id, subject.report.digest),
            )
        except TrustedJudgmentRefused as refused:
            raise _seal_refusal(refused) from None
        del sealed
        request = self._use_request(subject, use, "official")
        decided = await self._call(
            "report.decide",
            request,
            host,
            key=_key("decide", subject.revision.revision_id, request.boundEffectDigest),
        )
        decision = Ref.model_validate(decided["decision"])
        resolution = await self.resolve(host, decision, attempt=0)
        return await self._record(
            subject,
            host,
            use,
            resolution,
            prior=await self._waiting_record(subject, host),
            locked=tuple(locked),
        )

    async def resume(
        self,
        subject: JudgmentSubject,
        host: InvocationAccess,
        use: UseSpec,
        *,
        attempt: int,
        fresh: bool = False,
    ) -> TrustedOutcome:
        """Re-resolve the exact KS decision a standing assessment rests on (after a restart).

        A successor (a qualified review) supersedes that assessment by its exact chain; without
        one the wait stands. An earlier ``unavailable`` assessment is re-assessed from scratch by
        the caller (:meth:`assess`), not here.
        """

        prior = await self._standing(subject, host)
        if prior is None or not cited_decisions(prior.evidence_refs):
            raise TrustedJudgmentRefused(
                "NOT_FOUND", "no standing trusted assessment cites a KS decision to resume"
            )
        decision_id, digest = prior.evidence_refs[0].split(":", 1)[1].split("@", 1)
        decision = subject.report.model_copy(
            update={
                "kind": "use_decision",
                "id": decision_id,
                "digest": digest,
                "version": "research-core.use_decision.v2",
            }
        )
        resolution = await self.resolve(host, decision, attempt=attempt, fresh=fresh)
        current = assessment_result(
            resolution.disposition,
            admissible=resolution.officially_usable,
            review_pending=resolution.reviewPending,
        )
        if resolution.current == resolution.requested and current == prior.result:
            if current == "review" and resolution.reviewPending:
                return TrustedOutcome(
                    state="waiting",
                    result="review",
                    reason="review_pending",
                    assessment=prior,
                    resolution=resolution,
                    pending_reviews=(decision_evidence(decision.id, decision.digest),),
                )
            # S1: a pass recorded before a crash still promotes (idempotent CAS on the head).
            promoted = False
            if current == "pass":
                obligation = await self._obligation(subject, host)
                if obligation is not None:
                    promotion = await self._promote(
                        subject,
                        host,
                        obligation,
                        assessment_id=prior.assessment_id,
                        decision=resolution.current,
                        use=use,
                    )
                    if isinstance(promotion, TrustedOutcome):
                        return promotion
                    promoted = promotion
            return TrustedOutcome(
                state="settled",
                result=current,
                assessment=prior,
                resolution=resolution,
                promoted=promoted,
            )
        # A successor, or (S2) the same decision whose current eligibility changed (revocation,
        # epoch, expiry): record the current judgment, superseding the earlier one.
        return await self._record(subject, host, use, resolution, prior=prior)

    async def resolve(
        self, access: InvocationAccess, decision: Ref, *, attempt: int, fresh: bool = False
    ) -> DecisionResolution:
        """The current successor of ``decision`` and its current exact-use eligibility."""

        document = await self._call(
            "decision.resolve",
            DecisionResolveRequest(schema_="decision-resolve.v1", decision=decision),
            access,
            key=_key(
                "resolve",
                decision.id,
                decision.digest,
                str(uuid4()) if fresh else str(attempt),
                access.invocation_ref,
            ),
        )
        return DecisionResolution.model_validate(document)

    async def review(
        self,
        reviewer: EvaluatorBinding,
        decision: Ref,
        *,
        outcome: Literal["approve", "hold", "reject"],
        bound_effect_digest: str,
        qualifiers_digest: str | None,
        rationale: str,
    ) -> dict[str, Any]:
        """Relay one authorized human review to KS; KS checks the live grant and digests.

        The one review path: :class:`ReviewRelay` (the operator review route composes the relay
        alone, W1 D2)."""

        return await ReviewRelay(self._gateway, clock=self._clock).review(
            reviewer,
            decision,
            outcome=outcome,
            bound_effect_digest=bound_effect_digest,
            qualifiers_digest=qualifiers_digest,
            rationale=rationale,
        )

    def use_gate(
        self, resolution: DecisionResolution, *, purpose: UsePurpose, repair_authorized: bool
    ) -> UseGate:
        """Official use vs authorized held review/repair under the application minimums."""

        return use_gate(
            purpose=purpose,
            use_class=resolution.useClass,
            admissible=resolution.officially_usable,
            reviewed=resolution.reviewer is not None,
            required_review_classes=self._profile.required_review_classes,
            signoff_classes=self._profile.consequential_signoff_classes,
            repair_authorized=repair_authorized,
        )

    async def decide_native_plan(
        self,
        host: InvocationAccess,
        report: Ref,
        use: UseSpec,
        *,
        revision_id: str,
        bound_effect_digest: str,
        target_schema: str,
        attempt: int,
    ) -> tuple[Ref, DecisionResolution]:
        """The plan-level official decision of a native write (W1 native write; ADR-0059/0060).

        ``report.decide`` over the exact report with the exact native digest of THIS invocation
        (the native plan binds the originating origin), then its current resolution. The request
        key is the revision and the bound digest, so a replay after a crash answers the decision
        KS already recorded (KS mints decision ids deterministically over run, use, audience,
        effect and epoch) instead of a second one. Review conditions are KS's: a plan decision
        needs its own qualified review whenever its use class requires one; a review of the report
        decision does not carry over (a review binds the exact bound digest).
        """

        request = ReportUseRequest(
            schema_="report-use.v1",
            report=report,
            subject=report,
            use=use.use,
            audience=use.audience,
            purpose="official",
            boundEffectDigest=bound_effect_digest,
            targetSchema=target_schema,
            normalizedValues={},
            policy=use.policy,
            rubric=use.rubric,
            expiresAt=None,
        )
        decided = await self._call(
            "report.decide",
            request,
            host,
            key=_key("decide-native", revision_id, bound_effect_digest),
        )
        decision = Ref.model_validate(decided["decision"])
        return decision, await self.resolve(host, decision, attempt=attempt, fresh=True)

    async def record_apply_decision(
        self, access: InvocationAccess, decision: RecordedUseDecision
    ) -> RecordedUseDecision:
        """Record one exact KS decision for a native plan in the durable store (0059)."""

        if self._decisions is None:
            raise TrustedJudgmentRefused("CAPABILITY_UNAVAILABLE", "no durable decision store")
        return await self._decisions.record(
            access.scope, decision, actor_ref=BRIDGE_ACTOR, at=self._clock()
        )

    # ------------------------------------------------------------------ internals

    def _admit(self, subject: JudgmentSubject, evaluators: Sequence[EvaluatorBinding]) -> None:
        roles = {evaluator.role for evaluator in evaluators}
        if "auditor" not in roles or not roles & {"judge", "second_family_judge"}:
            raise TrustedJudgmentRefused(
                "INDEPENDENCE_UNPROVEN",
                "a trusted assessment needs an independent judge and auditor",
            )
        for evaluator in evaluators:
            refusals = evaluator_refusals(
                subject.producer,
                evaluator.identity(),
                role=evaluator.role,
                judge_pin=self._judge_pin,
            )
            if refusals:
                raise TrustedJudgmentRefused(
                    refusals[0].value,
                    f"the {evaluator.role} is not independent of the producer: "
                    + ", ".join(item.value for item in refusals),
                )

    async def _observe(
        self,
        subject: JudgmentSubject,
        evaluator: EvaluatorBinding,
        host: InvocationAccess,
        use: UseSpec,
    ) -> Literal["observed", "locked"] | _Unavailable:
        """Run the evaluator within policy and send its observations (``locked``: KS already
        held this role's first batch for the run).

        W1 D23: every failed run records its concrete cause on the revision's standing wait
        assessment, and a billed run counts against the role's bound for this exact revision
        (persisted there), so no later pass re-runs a paid evaluator past the bound."""

        role = evaluator.role
        subject_ref = f"output:{subject.revision.revision_id}"
        known = await self._ledger(subject, host)
        held = known.observed.get(role)
        if held is not None:
            # KS holds this role's observation (recorded or recovered on an earlier pass): no
            # paid evaluator run and no second KS observation; its first batch stands.
            return "locked"
        request_key = known.dispatched.get(role)
        if request_key is not None:
            recovered = await self._recover(subject, evaluator, host, use, request_key)
            if recovered is not None:
                return recovered
        output: EvaluatorOutput | None = None
        cause = "the evaluator did not run"
        for _attempt in range(self._retry.max_attempts):
            ledger = await self._ledger(subject, host)
            if ledger.attempts.get(role, 0) >= self._retry.max_attempts:
                return _Unavailable(
                    cause=ledger.causes.get(role, cause),
                    role=role,
                    exhausted=True,
                    causes=ledger.messages(),
                )
            try:
                candidate = await self._runner.evaluate(evaluator, subject)
            except EvaluatorUnavailable as error:
                cause, billed = evaluator_cause(error), error.billed
            else:
                # S3: an evaluator that produced nothing did not evaluate; the seal waits for it.
                if candidate.observations or candidate.census is not None:
                    output = candidate
                    break
                cause, billed = "the evaluator answered no observations and no census", True
            _LOGGER.warning(
                "trusted %s evaluation of revision %s unavailable (%s): %s",
                role,
                subject.revision.revision_id,
                "billed" if billed else "not billed",
                cause,
            )
            await self._record_wait(subject, host, use, role, cause, billed=billed)
        if output is None:
            ledger = await self._ledger(subject, host)
            return _Unavailable(
                cause=cause,
                role=role,
                exhausted=ledger.attempts.get(role, 0) >= self._retry.max_attempts,
                causes=ledger.messages(),
            )
        # S4: bound to the exact observation content, so a retried nondeterministic evaluator
        # is a new request (never EFFECT_CONFLICT on the old request id).
        request_key = _key(
            "observe",
            subject.revision.revision_id,
            evaluator.role,
            evaluator.credential_ref,
            digest_canonical({"observations": list(output.observations), "census": output.census}),
        )
        # W1 (auditor handle gap): the request id is durable before it is sent, so a pass after a
        # lost answer reads the operation KS holds instead of re-running the evaluator.
        await self._mark(subject, host, use, role, dispatched=request_key)
        try:
            answer = await self._gateway.trusted(
                "report.observe",
                ReportObservationRequest(
                    schema_="report-observation.v1",
                    report=subject.report,
                    observations=output.observations,
                    census=output.census,
                ),
                evaluator.access,
                evaluation=evaluator.grant(),
                request_key=request_key,
                governors=_governors(self._clock),
                capability_pin=TRUSTED_CAPABILITY_PIN,
                subject_ref=subject_ref,
            )
        except KnowledgeRefused as refused:
            if refused.code == "CAPABILITY_UNAVAILABLE":
                # KS cannot take the observations now. The evaluator ran (billed): the run
                # counts, so a KS outage never re-runs a paid evaluator past the bound.
                cause = f"report.observe unavailable: {evaluator_cause(refused)}"
                return await self._after_run_unavailable(subject, host, use, role, cause)
            raise TrustedJudgmentRefused(refused.code, str(refused), billed=True) from None
        except Exception as error:
            # W1 D22 shape: KS may have accepted the observations while the host could not record
            # or read the answer. The dispatch is durable, so the next pass recovers the
            # operation (`operation.get`) without a second paid run: the cause is recorded, not
            # counted against the bound.
            cause = f"report.observe failed: {type(error).__name__}: {evaluator_cause(error)}"
            _LOGGER.warning("trusted %s observation of %s: %s", role, subject_ref, cause)
            await self._record_wait(subject, host, use, role, cause, billed=False)
            raise
        if answer.refusal is not None:
            if answer.reason == "evaluator_role_observed":
                # This role already observed the run (possibly only in part): its first batch
                # stands (N2: a failing verdict is sticky; only a review moves it).
                await self._mark(subject, host, use, role, observed=KS_HELD)
                return "locked"
            if answer.reason == "run_sealed":
                await self._mark(subject, host, use, role, observed=KS_HELD)
                return "observed"  # an earlier pass sealed the run; its observations stand
            raise _refused(answer, billed=True)
        # The dispatch marker already names the request: a later pass reads its operation
        # (`operation.get`, unbilled) instead of re-running the evaluator, so success writes
        # no further record.
        return "observed"

    async def _recover(
        self,
        subject: JudgmentSubject,
        evaluator: EvaluatorBinding,
        host: InvocationAccess,
        use: UseSpec,
        request_key: str,
    ) -> Literal["locked"] | None:
        """W1 (auditor handle gap): a pass found the role's observe request dispatched by an
        earlier pass (whose answer may have been lost). Read the operation KS holds for exactly
        that request id and record its handle (no second observation, no paid evaluator run).
        ``None``: KS holds no such operation (the dispatch never landed), so the evaluator may
        run within its bound."""

        role = evaluator.role
        try:
            answer = await self._gateway.recover_trusted(
                "report.observe",
                evaluator.access,
                request_key=request_key,
                subject_ref=f"output:{subject.revision.revision_id}",
            )
        except KnowledgeRefused as refused:
            if refused.code == "CAPABILITY_UNAVAILABLE":
                raise EvaluatorUnavailable(
                    f"recovering the {role} observation failed: {evaluator_cause(refused)}"
                ) from None
            # A protocol fault (e.g. KS answered another operation id): typed, never a rerun.
            raise TrustedJudgmentRefused(
                refused.code, f"recovering the {role} observation: {refused}"
            ) from None
        if answer is None:
            _LOGGER.warning(
                "the %s observation dispatched for revision %s is not held by KS; re-evaluating",
                role,
                subject.revision.revision_id,
            )
            return None
        if answer.refusal is not None or answer.status is None:
            raise _refused(answer, billed=True)
        if answer.status.state != "succeeded":
            raise EvaluatorUnavailable(
                f"the recovered {role} observation is {answer.status.state}; waiting"
            )
        assert answer.handle_record is not None
        _LOGGER.info(
            "the %s observation of revision %s is held by KS (%s)",
            role,
            subject.revision.revision_id,
            answer.handle_record.handle.operationId,
        )
        return "locked"

    async def _mark(
        self,
        subject: JudgmentSubject,
        host: InvocationAccess,
        use: UseSpec,
        role: str,
        *,
        dispatched: str | None = None,
        observed: str | None = None,
    ) -> None:
        """Record a role's dispatched observe request id or what KS holds for it on the
        revision's standing wait (a compare-and-set successor carrying the whole ledger)."""

        obligation = await self._obligation(subject, host)
        keys = self._requirement_keys(obligation) or ("trusted_assessment",)
        bound = self._retry.max_attempts

        def record(ledger: _Ledger) -> AssessmentInput | None:
            markers = replace(
                ledger,
                dispatched={**ledger.dispatched, **({role: dispatched} if dispatched else {})},
                observed={**ledger.observed, **({role: observed} if observed else {})},
            )
            evidence = _wait_evidence(ledger.attempts, ledger.causes, markers.carried)
            if ledger.wait is not None and _unwritten(ledger.wait.evidence_refs) == evidence:
                return None
            return AssessmentInput(
                run_id=subject.run_id,
                subject_kind="output_revision",
                subject_id=subject.revision.revision_id,
                subject_digest=subject.revision.content_digest,
                requirement_results=dict.fromkeys(keys, "unavailable"),
                method_pin=self._profile.assessment_pin,
                policy_pin=f"{use.policy.id}@{use.policy.version}",
                evidence_refs=(*evidence, _write_ref()),
                findings=(
                    *ledger.refusal_findings,
                    *_cause_findings(ledger.causes, ledger.attempts, bound),
                ),
                supersedes=None if ledger.wait is None else ledger.wait.assessment_id,
            )

        await _supersede_wait(
            self._fulfillment,
            self._host(host, origin_ref=f"{WAIT_ORIGIN_PREFIX}{subject.revision.revision_id}"),
            record,
            lambda: self._ledger(subject, host),
            what=f"the {role} observation marker of revision {subject.revision.revision_id}",
            billed=False,
        )

    async def _call(
        self,
        operation: Literal[
            "report.observe", "report.seal", "report.decide", "report.review", "decision.resolve"
        ],
        request: Any,
        access: InvocationAccess,
        *,
        key: str,
        evaluation: CredentialEvaluation | None = None,
    ) -> dict[str, Any]:
        answer = await self._gateway.trusted(
            operation,
            request,
            access,
            evaluation=evaluation,
            request_key=key,
            governors=_governors(self._clock),
            capability_pin=TRUSTED_CAPABILITY_PIN,
        )
        if answer.document is None:
            raise _refused(answer)
        return answer.document

    def _use_request(
        self, subject: JudgmentSubject, use: UseSpec, purpose: UsePurpose
    ) -> ReportUseRequest:
        return ReportUseRequest(
            schema_="report-use.v1",
            report=subject.report,
            subject=subject.report,
            use=use.use,
            audience=use.audience,
            purpose=purpose,
            boundEffectDigest=digest_canonical(
                {
                    "report": subject.report.digest,
                    "use": use.use,
                    "audience": use.audience,
                    "output_revision": subject.revision.revision_id,
                }
            ),
            targetSchema=use.target_schema,
            normalizedValues={},
            policy=use.policy,
            rubric=use.rubric,
            expiresAt=None,
        )

    def _requirement_keys(self, obligation: OutputObligation | None) -> tuple[str, ...]:
        """The deliverable requirements the trusted assessment answers (its validator pin)."""

        if obligation is None:
            return ()
        return tuple(
            item.key
            for item in obligation.contract.requirements
            if item.subject == "deliverable" and item.validator == self._profile.assessment_pin
        )

    async def _obligation(
        self, subject: JudgmentSubject, host: InvocationAccess
    ) -> OutputObligation | None:
        revision = subject.revision
        return await self._store.obligation_revision(
            host.scope, subject.run_id, revision.obligation_key, revision.obligation_revision
        )

    async def _waiting_record(
        self, subject: JudgmentSubject, host: InvocationAccess
    ) -> Assessment | None:
        """The standing evaluator-unavailable record a fresh trusted judgment replaces."""

        rows = await self._store.output_assessments(host.scope, subject.run_id)
        return standing_wait(rows, subject.revision)

    async def _standing(
        self, subject: JudgmentSubject, host: InvocationAccess
    ) -> Assessment | None:
        """The newest standing (unsuperseded) trusted assessment of the exact revision."""

        revision = subject.revision
        rows = await self._store.output_assessments(host.scope, subject.run_id)
        mine = [
            row
            for row in rows
            if row.subject_kind == "output_revision"
            and row.subject_id == revision.revision_id
            and row.subject_digest == revision.content_digest
            and cited_decisions(row.evidence_refs)
        ]
        superseded = {row.supersedes for row in mine if row.supersedes is not None}
        standing = [row for row in mine if row.assessment_id not in superseded]
        return standing[-1] if standing else None

    async def _ledger(self, subject: JudgmentSubject, host: InvocationAccess) -> _Ledger:
        """The billed evaluator attempts and recorded causes of the exact revision (its
        standing wait assessment)."""

        return _Ledger.of(await self._waiting_record(subject, host))

    async def _record_wait(
        self,
        subject: JudgmentSubject,
        host: InvocationAccess,
        use: UseSpec,
        role: str,
        cause: str,
        *,
        billed: bool,
    ) -> Assessment | None:
        """Record the role's failed run on a new standing wait that supersedes the current one
        (an ``unavailable`` wait citing no decision is replaceable by the bridge), carrying every
        role's attempt count and the KS refusal evidence forward. The ledger is re-read at write
        time and the write is a compare-and-set on the standing row (W1 fix G S1), so concurrent
        passes never undercount or fork the wait. An unchanged ledger (an unbilled failure with
        the same cause) records nothing new."""

        obligation = await self._obligation(subject, host)
        keys = self._requirement_keys(obligation) or ("trusted_assessment",)
        bound = self._retry.max_attempts

        def record(ledger: _Ledger) -> AssessmentInput | None:
            attempts = dict(ledger.attempts)
            if billed:
                attempts[role] = attempts.get(role, 0) + 1
            causes = {**ledger.causes, role: cause}
            evidence = _wait_evidence(attempts, causes, ledger.carried)
            if ledger.wait is not None and _unwritten(ledger.wait.evidence_refs) == evidence:
                return None
            return AssessmentInput(
                run_id=subject.run_id,
                subject_kind="output_revision",
                subject_id=subject.revision.revision_id,
                subject_digest=subject.revision.content_digest,
                requirement_results=dict.fromkeys(keys, "unavailable"),
                method_pin=self._profile.assessment_pin,
                policy_pin=f"{use.policy.id}@{use.policy.version}",
                evidence_refs=(*evidence, _write_ref()),
                findings=(*ledger.refusal_findings, *_cause_findings(causes, attempts, bound)),
                supersedes=None if ledger.wait is None else ledger.wait.assessment_id,
            )

        return await _supersede_wait(
            self._fulfillment,
            self._host(host, origin_ref=f"{WAIT_ORIGIN_PREFIX}{subject.revision.revision_id}"),
            record,
            lambda: self._ledger(subject, host),
            what=f"the {role} wait of revision {subject.revision.revision_id}",
            billed=billed,
        )

    async def _after_run_unavailable(
        self,
        subject: JudgmentSubject,
        host: InvocationAccess,
        use: UseSpec,
        role: str,
        cause: str,
    ) -> _Unavailable:
        """A billed evaluator run whose observations could not reach KS: counted, recorded."""

        _LOGGER.warning(
            "trusted %s observation of revision %s: %s", role, subject.revision.revision_id, cause
        )
        await self._record_wait(subject, host, use, role, cause, billed=True)
        ledger = await self._ledger(subject, host)
        return _Unavailable(
            cause=cause,
            role=role,
            exhausted=ledger.attempts.get(role, 0) >= self._retry.max_attempts,
            causes=ledger.messages(),
        )

    async def _unavailable(
        self,
        subject: JudgmentSubject,
        host: InvocationAccess,
        use: UseSpec,
        unavailable: _Unavailable,
    ) -> TrustedOutcome:
        wait = await self._waiting_record(subject, host)
        if wait is None:
            # No run recorded a cause (an injected runner that never ran): one plain wait.
            wait = await self._record_wait(
                subject, host, use, unavailable.role, unavailable.cause, billed=False
            )
        return TrustedOutcome(
            state="waiting",
            result="unavailable",
            reason="evaluator_unavailable",
            assessment=wait,
            causes=unavailable.causes or (f"{unavailable.role}: {unavailable.cause}",),
            exhausted=unavailable.exhausted,
        )

    async def _refused_record(
        self,
        subject: JudgmentSubject,
        host: InvocationAccess,
        use: UseSpec,
        role: str,
        refused: TrustedJudgmentRefused,
    ) -> None:
        """W1 D20: an ``unavailable`` assessment naming KS's refusal of an evaluator's documents
        (one finding for the refusal, one per bounded issue), so inspection and the output events
        show what KS refused. Best effort: a recording failure never hides the refusal."""

        obligation = await self._obligation(subject, host)
        keys = self._requirement_keys(obligation) or ("trusted_assessment",)
        findings = [
            Finding(
                code=f"ks_{refused.code.lower()}"[:128],
                message=f"KS refused the {role}'s documents: {refused}"[:500],
                pointer=refused.reason,
            ),
            *(
                Finding(
                    code="ks_issue",
                    message=issue[:500],
                    pointer=issue.split(":", 1)[0][:200] or None,
                )
                for issue in refused.issues[:8]
            ),
        ]
        bound = self._retry.max_attempts

        def record(ledger: _Ledger) -> AssessmentInput:
            # W1 D23 / fix G: the refusal replaces the standing wait (one standing wait per
            # revision) as a compare-and-set, carrying every role's attempt count and cause.
            attempts = dict(ledger.attempts)
            if refused.billed:  # the refused documents came from a billed evaluator run
                attempts[role] = attempts.get(role, 0) + 1
            return AssessmentInput(
                run_id=subject.run_id,
                subject_kind="output_revision",
                subject_id=subject.revision.revision_id,
                subject_digest=subject.revision.content_digest,
                requirement_results=dict.fromkeys(keys, "unavailable"),
                method_pin=self._profile.assessment_pin,
                policy_pin=f"{use.policy.id}@{use.policy.version}",
                evidence_refs=(
                    f"{KS_REFUSAL_PREFIX}{role}:{refused.code}:{refused.reason or '-'}",
                    *_wait_evidence(
                        attempts,
                        ledger.causes,
                        tuple(ref for ref in ledger.carried if ref not in ledger.refusal_refs),
                    ),
                    _write_ref(),
                ),
                findings=(*findings, *_cause_findings(ledger.causes, attempts, bound)),
                supersedes=None if ledger.wait is None else ledger.wait.assessment_id,
            )

        try:
            await _supersede_wait(
                self._fulfillment,
                self._host(host, origin_ref=f"ks-refusal:{subject.revision.revision_id}:{role}"),
                record,
                lambda: self._ledger(subject, host),
                what=f"the {role} KS refusal of revision {subject.revision.revision_id}",
                billed=refused.billed,
            )
        except EvaluatorUnavailable:
            # The refusal itself is re-raised by the caller; its record's failure was logged
            # by `_supersede_wait` (review N2: never hides the refusal).
            return

    def _host(self, host: InvocationAccess, *, origin_ref: str) -> HostAccess:
        return HostAccess(
            scope=host.scope, actor_ref=BRIDGE_ACTOR, origin_ref=origin_ref, role="assessor"
        )

    async def _record(
        self,
        subject: JudgmentSubject,
        host: InvocationAccess,
        use: UseSpec,
        resolution: DecisionResolution,
        *,
        prior: Assessment | None,
        locked: tuple[str, ...] = (),
    ) -> TrustedOutcome:
        current = resolution.current
        result = assessment_result(
            resolution.disposition,
            admissible=resolution.officially_usable,
            review_pending=resolution.reviewPending,
        )
        obligation = await self._obligation(subject, host)
        keys = self._requirement_keys(obligation) or ("trusted_assessment",)
        evidence = (
            decision_evidence(current.id, current.digest),
            *(decision_evidence(ref.id, ref.digest) for ref in resolution.chain if ref != current),
            *(f"{ROLE_LOCK_EVIDENCE_PREFIX}{role}" for role in sorted(set(locked))),
        )
        receipt = await self._fulfillment.record_assessment(
            self._host(host, origin_ref=f"ks:{current.binding}/use_decision/{current.id}"),
            AssessmentInput(
                run_id=subject.run_id,
                subject_kind="output_revision",
                subject_id=subject.revision.revision_id,
                subject_digest=subject.revision.content_digest,
                requirement_results=dict.fromkeys(keys, result),
                method_pin=self._profile.assessment_pin,
                policy_pin=f"{use.policy.id}@{use.policy.version}",
                evidence_refs=evidence,
                supersedes=None if prior is None else prior.assessment_id,
            ),
            lineage=_KsLineage(self, host, subject.report),
        )
        if receipt.assessment is None:
            error = receipt.error
            raise TrustedJudgmentRefused(
                "ASSESSMENT_REFUSED",
                "the trusted assessment was not recorded",
                reason=None if error is None else str(error.code),
            )
        promoted = False
        if result == "pass" and obligation is not None:
            promotion = await self._promote(
                subject,
                host,
                obligation,
                assessment_id=receipt.assessment.assessment_id,
                decision=current,
                use=use,
            )
            if isinstance(promotion, TrustedOutcome):
                return promotion
            promoted = promotion
        demoted = False
        if prior is not None and prior.result == "pass" and result != "pass":
            revision = subject.revision
            head = await self._store.accepted_head(
                host.scope, subject.run_id, revision.obligation_key, revision.deliverable_id
            )
            demoted = head is not None and head.revision_id == revision.revision_id
        if result == "review" and resolution.reviewPending:
            return TrustedOutcome(
                state="waiting",
                result=result,
                reason="review_pending",
                assessment=receipt.assessment,
                resolution=resolution,
                pending_reviews=(decision_evidence(current.id, current.digest),),
                locked_roles=locked,
                demoted=demoted,
            )
        return TrustedOutcome(
            state="settled",
            result=result,
            assessment=receipt.assessment,
            resolution=resolution,
            promoted=promoted,
            findings=tuple(resolution.conditions),
            locked_roles=locked,
            demoted=demoted,
        )

    async def _promote(
        self,
        subject: JudgmentSubject,
        host: InvocationAccess,
        obligation: OutputObligation,
        *,
        assessment_id: str,
        decision: Ref,
        use: UseSpec,
    ) -> bool | TrustedOutcome:
        """Promote only when every required deliverable requirement stands at ``pass``.

        N1 (promotion race): immediately before the head compare-and-set, the standing trusted
        assessment must still be exactly ``assessment_id`` at ``pass`` and the KS decision must
        still be officially usable now; a concurrent supersede (a revocation re-recorded as
        ``review``) or a lost eligibility refuses. The store's CAS binds the head only, so a
        supersede landing between this re-read and the CAS remains a bounded window; a
        revocation after promotion is recorded by a later pass as a superseding assessment, and
        `head_demoted` keeps every consumer from admitting that head (OVE-169).
        """

        revision = subject.revision
        standing = await self._standing(subject, host)
        if standing is None or standing.assessment_id != assessment_id or standing.result != "pass":
            return False
        current = await self.resolve(host, decision, attempt=0, fresh=True)
        if not current.officially_usable:
            # A revocation racing the first read must supersede the standing pass, not merely
            # skip this CAS while leaving a previously promoted head apparently usable.
            return await self._record(subject, host, use, current, prior=standing)
        if current.current != decision:
            return False
        assessments = await self._store.output_assessments(host.scope, subject.run_id)
        for requirement in obligation.contract.requirements:
            if not requirement.required or requirement.subject != "deliverable":
                continue
            result, _standing = judged(
                assessments,
                "output_revision",
                revision.revision_id,
                revision.content_digest,
                requirement.key,
            )
            if result != "pass":
                return False
        head = await self._store.accepted_head(
            host.scope, subject.run_id, revision.obligation_key, revision.deliverable_id
        )
        if head is not None and head.revision_id == revision.revision_id:
            return True
        promoted = await self._fulfillment.promote_output(
            self._host(host, origin_ref=BRIDGE_ACTOR),
            PromoteOutput(
                run_id=subject.run_id,
                revision_id=revision.revision_id,
                expected_head=None if head is None else head.revision_id,
                generation=subject.generation,
            ),
        )
        return promoted.status == "promoted"


class ReviewRelay:
    """KS ``report.review`` under the reviewer's own separate invocation and reviewer grant.

    :meth:`TrustedJudgmentBridge.review` delegates here; the operator review route (W1 D2)
    composes the relay over the API's knowledge gateway, so both run the same request, key and
    refusal handling. KS checks the live reviewer grant, the exact digests and that the
    reviewer is not the run's producer; the settlement's next pass re-resolves the successor.
    """

    def __init__(
        self, gateway: KnowledgeGateway, *, clock: Callable[[], datetime] = _utcnow
    ) -> None:
        self._gateway = gateway
        self._clock = clock

    async def review(
        self,
        reviewer: EvaluatorBinding,
        decision: Ref,
        *,
        outcome: Literal["approve", "hold", "reject"],
        bound_effect_digest: str,
        qualifiers_digest: str | None,
        rationale: str,
    ) -> dict[str, Any]:
        if reviewer.role != "human_reviewer":
            raise TrustedJudgmentRefused(
                JudgmentRefusal.EVALUATOR_ROLE_INVALID.value, "a review is a human reviewer's"
            )
        answer = await self._gateway.trusted(
            "report.review",
            ReportReviewRequest(
                schema_="report-review.v1",
                decision=decision,
                outcome=outcome,
                boundEffectDigest=bound_effect_digest,
                qualifiersDigest=qualifiers_digest,
                rationale=rationale,
            ),
            reviewer.access,
            evaluation=reviewer.grant(),
            request_key=_key("review", decision.id, reviewer.access.subject, outcome, rationale),
            governors=_governors(self._clock),
            capability_pin=TRUSTED_CAPABILITY_PIN,
        )
        if answer.document is None:
            raise _refused(answer)
        return answer.document


class _KsLineage:
    """Supersession lineage resolved through KS ``decision.resolve`` (WI-03 S6)."""

    def __init__(self, bridge: TrustedJudgmentBridge, host: InvocationAccess, report: Ref) -> None:
        self._bridge = bridge
        self._host = host
        self._report = report

    async def successor_chain(self, decision_evidence: str) -> tuple[str, ...]:
        decision_id, digest = decision_evidence.split(":", 1)[1].split("@", 1)
        decision = self._report.model_copy(
            update={
                "kind": "use_decision",
                "id": decision_id,
                "digest": digest,
                "version": "research-core.use_decision.v2",
            }
        )
        resolution = await self._bridge.resolve(
            self._host, decision, attempt=int(self._bridge._clock().timestamp() * 1000)
        )
        return tuple(ref.id for ref in resolution.chain)


def _seal_refusal(refused: TrustedJudgmentRefused) -> TrustedJudgmentRefused:
    """W1 D25: KS cannot seal because the installation does not pin the executor's seal key
    (``CAPABILITY_UNAVAILABLE`` / ``seal_key_unregistered`` | ``seal_key_inactive``). A
    provisioning gap, not a transient fault: the settlement waits (``settlement_unavailable``)
    with KS's message (it names the key id) and the operator action as ``issues``. Every
    evaluator's observation is already held by KS under its durable dispatch marker, so a later
    pass recovers it (``operation.get``) and seals again; no paid evaluator runs twice. The HTTP
    client never re-sends ``invoke`` (it is not idempotent there), so nothing retries in between.
    """

    if refused.code != "CAPABILITY_UNAVAILABLE" or not (refused.reason or "").startswith(
        "seal_key_"
    ):
        return refused
    return TrustedJudgmentRefused(
        refused.code,
        "report.seal refused: the KS executor's seal key is not registered active",
        reason=refused.reason,
        issues=(
            f"report.seal: {refused}"[:300],
            "operator: register the KS executor's seal key (root installer `seal-key` step), "
            "then the next settlement pass seals; the recorded observations stand",
            *refused.issues,
        ),
        billed=False,
    )


def _refused(answer: TrustedAnswer, *, billed: bool = False) -> TrustedJudgmentRefused:
    error = answer.refusal
    if error is None:
        state = "no status" if answer.status is None else answer.status.state
        return TrustedJudgmentRefused(
            "CAPABILITY_UNAVAILABLE", f"{answer.operation} ended {state}", billed=billed
        )
    return TrustedJudgmentRefused(
        error.code, error.message, reason=answer.reason, issues=answer.issues, billed=billed
    )


__all__ = [
    "BRIDGE_ACTOR",
    "ROLE_LOCK_EVIDENCE_PREFIX",
    "TRUSTED_CAPABILITY_PIN",
    "EvaluatorAttemptReset",
    "EvaluatorBinding",
    "EvaluatorOutput",
    "EvaluatorResetRefused",
    "EvaluatorRetryPolicy",
    "EvaluatorRunner",
    "EvaluatorUnavailable",
    "EvaluatorWaitConflict",
    "EvaluatorWaitUnrecorded",
    "JudgmentSubject",
    "ReviewRelay",
    "TrustedJudgmentBridge",
    "TrustedJudgmentRefused",
    "TrustedOutcome",
    "UseSpec",
]
