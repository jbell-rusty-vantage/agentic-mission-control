"""The trusted assessment pass of a saved result's settlement (WI-03 behind the WI-04 seam).

WI-04's settlement (``InvocationSettler`` / ``SettlementOutcome``, the durable
``invocation_settlement`` record) owns the wait; this pass supplies its reasons. For every output
revision the finalized invocation submitted under an obligation whose requirements name the
application's assessment pin, it runs the trusted judgment bridge once (``assess``), or, when a
standing trusted assessment already cites a KS decision, re-resolves that exact decision
(``resume``). The answer is what the settler turns into ``waiting/review_pending`` (the exact KS
decision refs) or a raise (an evaluator still unavailable: the boundary records
``settlement_unavailable`` and retries). No second wait record exists: the standing
``output_assessment`` citing the exact decision plus the settlement record are the durable state.

WI-07: a promise evaluated over the goal or mission (``evaluation_scope``) is the goal's, not the
invocation's: its review wait is reported in ``goal_waits`` and never holds the invocation, so
independent goal work proceeds while the required promise stays unfulfilled at convergence. Each
pass re-resolves earlier goal-scoped review waits of the run and this invocation's own held
revisions (``resumed``), promoting an approved successor; a report collection is therefore judged
member by member, each exact revision once.

Which evaluators judge, under which use and on whose behalf, is the admitted run configuration's
(:class:`TrustedAssessmentPlans`); the MC-hosted Deep Agents judge/auditor runner is W1 (OVE-169).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from mission_control.application.knowledge.access import InvocationAccess
from mission_control.application.knowledge.judgment import (
    EvaluatorBinding,
    EvaluatorUnavailable,
    JudgmentSubject,
    TrustedJudgmentBridge,
    TrustedJudgmentRefused,
    UseSpec,
    evaluator_cause,
)
from mission_control.application.ports.outputs import OutputContractStore
from mission_control.contracts.knowledge_protocol import Ref
from mission_control.domain.knowledge.judgment import CognitionIdentity, cited_decisions
from mission_control.domain.outputs.contracts import (
    Assessment,
    EvaluationScope,
    ExactOutput,
    OutputObligation,
)

_HANDLE = "kh:"


@dataclass(frozen=True)
class TrustedPlan:
    """The admitted evaluators, use and producer identity of one output revision."""

    evaluators: tuple[EvaluatorBinding, ...]
    use: UseSpec
    producer: CognitionIdentity


class TrustedAssessmentPlans(Protocol):
    async def plan(self, access: InvocationAccess, revision: ExactOutput) -> TrustedPlan: ...


# WI-07 (OC-D134): a review wait on a promise evaluated over the whole goal (or mission) does not
# hold the invocation that submitted it: independent work proceeds, the required promise stays
# unfulfilled at convergence (final acceptance blocked), and a later settlement re-resolves it.
GOAL_SCOPES = frozenset({EvaluationScope.GOAL, EvaluationScope.MISSION})


@dataclass
class _Resumed:
    revisions: list[str] = field(default_factory=list)
    goal: dict[str, str] = field(default_factory=dict)
    own: dict[str, str] = field(default_factory=dict)
    approved: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TrustedSettlementPass:
    pending_reviews: tuple[str, ...] = ()
    unavailable: tuple[str, ...] = ()
    promoted: tuple[str, ...] = ()
    # Goal-scoped review waits this pass left standing (exact KS decision refs): they never hold
    # the invocation; ``resumed`` names the earlier goal-scoped revisions this pass re-resolved.
    goal_waits: tuple[str, ...] = ()
    resumed: tuple[str, ...] = ()
    # W1 D23: why each unavailable revision waits (``<revision>: <role>: <cause>``, bounded and
    # redacted) and whether an evaluator's billed attempts on it are exhausted.
    causes: tuple[str, ...] = ()
    exhausted: tuple[str, ...] = ()


def report_ref(revision: ExactOutput, *, tenant: str) -> Ref | None:
    """The exact KS report a revision names (``kh:<binding>/report/<id>@<version>``)."""

    ref = revision.candidate.get("ref")
    digest = revision.candidate.get("digest")
    if not isinstance(ref, str) or not ref.startswith(_HANDLE) or not isinstance(digest, str):
        return None
    try:
        binding, kind, rest = ref.removeprefix(_HANDLE).split("/", 2)
        item, version = rest.rsplit("@", 1)
    except ValueError:
        return None
    if kind != "report":
        return None
    return Ref(
        kind="report", id=item, version=version, digest=digest, tenant=tenant, binding=binding
    )


class TrustedSettlement:
    def __init__(
        self,
        *,
        bridge: TrustedJudgmentBridge,
        store: OutputContractStore,
        plans: TrustedAssessmentPlans,
        assessment_pin: str,
    ) -> None:
        self._bridge = bridge
        self._store = store
        self._plans = plans
        self._pin = assessment_pin

    async def settle(self, access: InvocationAccess, *, attempt: int) -> TrustedSettlementPass:
        """One pass over the invocation's trusted subjects (assess, or resume the exact wait)."""

        scope, run_id = access.scope, access.origin.run_id
        pending: list[str] = []
        goal_waits: list[str] = []
        unavailable: list[str] = []
        causes: list[str] = []
        exhausted: list[str] = []
        promoted: list[str] = []
        pins = await self._store.invocation_pins(scope, access.invocation_ref)
        assessments = await self._store.output_assessments(scope, run_id)
        mine: set[str] = set()
        for key, revision_no in sorted(pins.items()):
            obligation = await self._store.obligation_revision(scope, run_id, key, revision_no)
            if obligation is None or not self._trusted(obligation):
                continue
            goal_scoped = obligation.evaluation_scope in GOAL_SCOPES
            outputs = await self._store.submitted_outputs(
                scope, run_id, key, operation_ref=access.origin.operation_id
            )
            for revision in outputs:
                mine.add(revision.revision_id)
                report = report_ref(revision, tenant=access.origin.tenant_id)
                if report is None:
                    continue
                try:
                    plan = await self._plans.plan(access, revision)
                except EvaluatorUnavailable as error:
                    unavailable.append(revision.revision_id)
                    causes.append(f"{revision.revision_id}: plan: {evaluator_cause(error)}")
                    continue
                subject = JudgmentSubject(
                    run_id=run_id,
                    revision=revision,
                    report=report,
                    producer=plan.producer,
                    generation=access.origin.generation,
                )
                cited = any(
                    item.subject_id == revision.revision_id
                    and item.subject_digest == revision.content_digest
                    and cited_decisions(item.evidence_refs)
                    for item in assessments
                )
                try:
                    outcome = (
                        await self._bridge.resume(subject, access, plan.use, attempt=attempt)
                        if cited
                        else await self._bridge.assess(subject, plan.evaluators, access, plan.use)
                    )
                except EvaluatorUnavailable as error:
                    unavailable.append(revision.revision_id)
                    causes.append(f"{revision.revision_id}: {evaluator_cause(error)}")
                    continue
                if outcome.reason == "review_pending":
                    (goal_waits if goal_scoped else pending).extend(outcome.pending_reviews)
                elif outcome.reason == "evaluator_unavailable":
                    unavailable.append(revision.revision_id)
                    causes.extend(f"{revision.revision_id}: {item}" for item in outcome.causes)
                    if outcome.exhausted:
                        exhausted.append(revision.revision_id)
                if outcome.promoted:
                    promoted.append(revision.revision_id)
        resumed = await self._resume_waits(access, assessments, exclude=mine, attempt=attempt)
        promoted.extend(resumed.approved)
        return TrustedSettlementPass(
            (*pending, *sorted(set(resumed.own.values()))),
            tuple(unavailable),
            tuple(promoted),
            goal_waits=(*goal_waits, *sorted(set(resumed.goal.values()))),
            resumed=tuple(resumed.revisions),
            causes=tuple(causes),
            exhausted=tuple(exhausted),
        )

    async def _resume_waits(
        self,
        access: InvocationAccess,
        assessments: Sequence[Assessment],
        *,
        exclude: set[str],
        attempt: int,
    ) -> _Resumed:
        """Re-resolve each standing trusted review wait this pass is responsible for: every
        goal-scoped revision of the run (whoever submitted it) and this invocation's own
        invocation-scoped revisions (``submitted_outputs`` no longer lists a held revision, so
        without this its wait would be lost on the next pass). An approved successor supersedes
        and promotes it; a wait that still stands is returned with its exact KS decision ref; a
        rejection is recorded by the bridge and stays unmet. An own wait whose resolution cannot
        run now keeps holding with the decision it rests on."""

        superseded = {item.supersedes for item in assessments if item.supersedes is not None}
        waiting: dict[str, str] = {}
        for item in assessments:
            if (
                item.subject_kind == "output_revision"
                and item.result == "review"
                and item.assessment_id not in superseded
                and cited_decisions(item.evidence_refs)
                and item.subject_id not in exclude
            ):
                waiting[item.subject_id] = next(
                    ref for ref in item.evidence_refs if cited_decisions((ref,))
                )
        resumed = _Resumed()
        for revision_id in sorted(waiting):
            revision = await self._store.output_revision(access.scope, revision_id)
            if revision is None or revision.run_id != access.origin.run_id:
                continue
            obligation = await self._store.obligation_revision(
                access.scope, revision.run_id, revision.obligation_key, revision.obligation_revision
            )
            if obligation is None or not self._trusted(obligation):
                continue
            goal_scoped = obligation.evaluation_scope in GOAL_SCOPES
            if not goal_scoped and revision.producer_origin_ref != access.invocation_ref:
                continue  # another invocation's own wait is held by that invocation
            report = report_ref(revision, tenant=access.origin.tenant_id)
            if report is None:
                continue
            holding = resumed.goal if goal_scoped else resumed.own
            try:
                plan = await self._plans.plan(access, revision)
                outcome = await self._bridge.resume(
                    JudgmentSubject(
                        run_id=revision.run_id,
                        revision=revision,
                        report=report,
                        producer=plan.producer,
                        generation=access.origin.generation,
                    ),
                    access,
                    plan.use,
                    # This pass's attempt: KS resolves the decision afresh, never a replay.
                    attempt=attempt,
                )
            except (EvaluatorUnavailable, TrustedJudgmentRefused):
                if not goal_scoped:
                    holding[revision_id] = waiting[revision_id]
                continue  # the standing wait decides; a later pass retries
            resumed.revisions.append(revision_id)
            if outcome.reason == "review_pending":
                holding[revision_id] = outcome.pending_reviews[0]
            elif outcome.promoted:
                resumed.approved.append(revision_id)
        return resumed

    async def recheck(
        self, access: InvocationAccess, revision: ExactOutput, *, strict: bool = False
    ) -> None:
        """OVE-169 consumer re-check: re-resolve the exact KS decision an accepted revision's
        standing trusted assessment cites; a revocation since promotion is recorded as a
        superseding assessment (``head_demoted`` then keeps consumers from admitting the head).
        No trusted assessment, or KS/plans unavailable now: nothing changes (the standing record
        decides). Strict linked consumers instead wait when current use cannot be established."""

        report = report_ref(revision, tenant=access.origin.tenant_id)
        if report is None:
            return
        assessments = await self._store.output_assessments(access.scope, revision.run_id)
        if not any(
            item.subject_id == revision.revision_id
            and item.subject_digest == revision.content_digest
            and cited_decisions(item.evidence_refs)
            for item in assessments
        ):
            if strict:
                raise EvaluatorUnavailable("current use has no trusted decision to resolve")
            return
        try:
            plan = await self._plans.plan(access, revision)
            subject = JudgmentSubject(
                run_id=revision.run_id,
                revision=revision,
                report=report,
                producer=plan.producer,
                generation=access.origin.generation,
            )
            await self._bridge.resume(subject, access, plan.use, attempt=0, fresh=True)
        except (EvaluatorUnavailable, TrustedJudgmentRefused):
            if strict:
                raise
            return

    def _trusted(self, obligation: OutputObligation | None) -> bool:
        if obligation is None:
            return False
        return any(item.validator == self._pin for item in obligation.contract.requirements)


def _finally_judged(assessments: Sequence[Assessment]) -> set[tuple[str, str]]:
    """The exact revisions whose standing (unsuperseded) trusted assessment cites a KS decision
    with a final result (pass or fail)."""

    superseded = {item.supersedes for item in assessments if item.supersedes is not None}
    return {
        (item.subject_id, item.subject_digest)
        for item in assessments
        if item.subject_kind == "output_revision"
        and item.assessment_id not in superseded
        and item.result in {"pass", "fail"}
        and cited_decisions(item.evidence_refs)
    }


class UncomposedTrustedSettlement:
    """W1 D30: the settlement pass of a worker that composes no trusted settlement (an evaluator
    credential is unset). A revision this invocation submitted under an obligation whose
    requirements name the application's trusted assessment pin cannot be judged here; instead of
    finalizing without an assessment (the promise would stay missing and the run fail), the pass
    reports it unavailable with an actionable cause, so the saved result waits
    (`settlement_unavailable`, reason `evaluator_unavailable`) until a worker with both evaluator
    credentials settles it. Revisions naming no KS report are left alone, as the trusted pass
    leaves them, and so is a revision whose standing trusted assessment already cites a final
    KS verdict (pass or fail): a credentialed worker judged it, and a worker resuming the run
    without credentials never re-holds it. The invocation's own standing review wait still holds
    (resolving its successor needs the composed bridge); a goal-scoped one never holds the
    invocation, as in the composed pass."""

    def __init__(
        self,
        *,
        store: OutputContractStore,
        assessment_pin: str,
        cause: str = (
            "no trusted settlement is composed in this worker: set MC_JUDGE_OPENAI_API_KEY and "
            "MC_AUDITOR_ANTHROPIC_API_KEY and restart it"
        ),
    ) -> None:
        self._store = store
        self._pin = assessment_pin
        self._cause = cause

    async def settle(self, access: InvocationAccess, *, attempt: int) -> TrustedSettlementPass:
        del attempt
        scope, run_id = access.scope, access.origin.run_id
        waiting: list[str] = []
        pins = await self._store.invocation_pins(scope, access.invocation_ref)
        assessments = await self._store.output_assessments(scope, run_id)
        judged = _finally_judged(assessments)
        for key, revision_no in sorted(pins.items()):
            obligation = await self._store.obligation_revision(scope, run_id, key, revision_no)
            if obligation is None or not any(
                item.validator == self._pin for item in obligation.contract.requirements
            ):
                continue
            outputs = await self._store.submitted_outputs(
                scope, run_id, key, operation_ref=access.origin.operation_id
            )
            waiting.extend(
                revision.revision_id
                for revision in outputs
                if report_ref(revision, tenant=access.origin.tenant_id) is not None
                and (revision.revision_id, revision.content_digest) not in judged
            )
        # This invocation's own held revisions (a standing review wait citing a KS decision):
        # `submitted_outputs` no longer lists them, and resolving their successor needs the
        # composed bridge, so they hold too (the composed pass resumes them the same way).
        superseded = {item.supersedes for item in assessments if item.supersedes is not None}
        for item in assessments:
            if (
                item.subject_kind != "output_revision"
                or item.result != "review"
                or item.assessment_id in superseded
                or not cited_decisions(item.evidence_refs)
                or item.subject_id in waiting
            ):
                continue
            revision = await self._store.output_revision(scope, item.subject_id)
            if revision is None or revision.run_id != run_id:
                continue
            if revision.producer_origin_ref != access.invocation_ref:
                continue
            obligation = await self._store.obligation_revision(
                scope, run_id, revision.obligation_key, revision.obligation_revision
            )
            if (
                obligation is not None
                and obligation.evaluation_scope not in GOAL_SCOPES
                and any(req.validator == self._pin for req in obligation.contract.requirements)
            ):
                waiting.append(revision.revision_id)
        return TrustedSettlementPass(
            unavailable=tuple(waiting),
            causes=tuple(f"{revision}: {self._cause}" for revision in waiting),
        )


def pending_or_raise(result: TrustedSettlementPass) -> Sequence[str]:
    """The exact pending KS reviews; an evaluator still unavailable raises (the boundary waits).

    W1 D23: the raise carries each revision's concrete cause as ``issues`` and, when a role's
    billed attempts are exhausted, the reason ``evaluator_attempts_exhausted`` (no later pass
    re-runs that evaluator; an operator acts on the cause), so the settlement wait records why."""

    if result.unavailable:
        exhausted = ", ".join(result.exhausted)
        raise EvaluatorUnavailable(
            "trusted evaluator unavailable for "
            + ", ".join(result.unavailable)
            + (f" (attempts exhausted for {exhausted})" if exhausted else ""),
            reason="evaluator_attempts_exhausted" if result.exhausted else "evaluator_unavailable",
            issues=result.causes[:20],
        )
    return result.pending_reviews


__all__ = [
    "TrustedAssessmentPlans",
    "TrustedPlan",
    "TrustedSettlement",
    "TrustedSettlementPass",
    "UncomposedTrustedSettlement",
    "pending_or_raise",
    "report_ref",
]
