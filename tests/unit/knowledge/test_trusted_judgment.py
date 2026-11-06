"""The trusted judgment bridge (Sprint OC WI-03 / OVE-165) over a deterministic KS double.

Proves, deterministically (no model call): separate evaluator credentials and vendor; KS-held
roles; the exact seal/decision path; ungrounded disagreement holds; contrary evidence fails;
evaluator unavailability waits; a pending review waits and its exact successor resolves after a
"restart" (new MC objects over the same KS state); only the bridge supersedes; passing promotes
while held/review/fail never does; official use versus authorized held repair in both apps.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from mission_control.application.knowledge.access import InvocationAccess
from mission_control.application.knowledge.gateway import KnowledgeGateway
from mission_control.application.knowledge.judgment import (
    ROLE_LOCK_EVIDENCE_PREFIX,
    EvaluatorBinding,
    EvaluatorOutput,
    EvaluatorRetryPolicy,
    EvaluatorUnavailable,
    JudgmentSubject,
    TrustedJudgmentBridge,
    TrustedJudgmentRefused,
    UseSpec,
)
from mission_control.application.outputs.fulfillment import AssessmentInput
from mission_control.contracts.knowledge_protocol import Ref
from mission_control.domain.knowledge.judgment import CognitionIdentity, EvaluatorPin, head_demoted
from mission_control.domain.outputs.contracts import OutputForm, Requirement
from mission_control.domain.resolution.resolved import OutputContractProfile
from tests.fixtures.knowledge_binding import (
    AUDIENCE,
    BINDING,
    InMemoryKnowledgeHandleStore,
    InMemoryKnowledgeJournal,
    Issuer,
    SteppingClock,
    knowledge_port,
)
from tests.fixtures.output_contracts import InMemoryOutputContractStore
from tests.fixtures.trusted_knowledge import (
    ReportState,
    TrustedKnowledgeDouble,
    TrustedKnowledgeState,
    ks_ref,
)
from tests.unit.knowledge.test_gateway import origin
from tests.unit.outputs.scenario import build_stack, obligation, text

pytestmark = pytest.mark.asyncio

PIN = "knowledge.report.assess@1"
PROFILES = {
    app: OutputContractProfile(
        assessment_pin=PIN,
        required_review_classes=("official", "consequential"),
        consequential_signoff_classes=("consequential",),
    )
    for app in ("ai-engineer", "biotech")
}
JUDGE_PIN = EvaluatorPin(profile="judge.default", vendor="openai", model_id="gpt-5.6-terra")
PRODUCER = CognitionIdentity(
    credential_ref="producer.default",
    subject="mission-control-runtime",
    operation_ref="op-research-1",
    vendor="anthropic",
    model_id="claude-sonnet-5-5",
)


class ScriptedRunner:
    """Deterministic evaluator cognition: per role, a verdict or a run of unavailability."""

    def __init__(self, verdicts: dict[str, str], unavailable: dict[str, int] | None = None) -> None:
        self.verdicts = verdicts
        self.unavailable = dict(unavailable or {})
        self.calls: list[str] = []

    async def evaluate(
        self, evaluator: EvaluatorBinding, subject: JudgmentSubject
    ) -> EvaluatorOutput:
        self.calls.append(evaluator.role)
        if self.unavailable.get(evaluator.role, 0) > 0:
            self.unavailable[evaluator.role] -= 1
            raise EvaluatorUnavailable("provider unavailable")
        if evaluator.role == "auditor":
            return EvaluatorOutput(census={"evaluator": {"role": "auditor"}, "occurrences": []})
        observation = {
            "evaluator": {"role": evaluator.role},
            "verdict": self.verdicts[evaluator.role],
        }
        return EvaluatorOutput(observations=(observation,))


@dataclass
class World:
    clock: SteppingClock
    issuer: Issuer
    ks: TrustedKnowledgeState
    stack: Any
    application: str

    def access(self, subject: str, operation: str) -> InvocationAccess:
        return InvocationAccess(
            origin=self.stack.access.origin.model_copy(update={"operation_id": operation}),
            subject=subject,
            invocation_id=f"inv-{subject}",
            authenticated_at=self.clock.now,
        )

    def evaluator(
        self,
        role: str,
        *,
        subject: str | None = None,
        vendor: str | None = "openai",
        credential: str | None = None,
    ) -> EvaluatorBinding:
        subject = subject or f"mc-{role}"
        return EvaluatorBinding(
            role=role,  # type: ignore[arg-type]
            credential_ref=credential or f"{role}.default",
            vendor=None if role in {"auditor", "human_reviewer"} else vendor,
            family=None if role in {"auditor", "human_reviewer"} else "gpt-5.6",
            model_id=JUDGE_PIN.model_id if role == "judge" else None,
            access=self.access(subject, f"op-{role}"),
        )

    def bridge(self, runner: ScriptedRunner) -> TrustedJudgmentBridge:
        """A fresh MC process: new gateway, handles and bridge over the same KS and MC stores."""

        client = TrustedKnowledgeDouble(
            self.ks, verify=self.issuer.verifier().verify, clock=self.clock, binding=BINDING
        )
        gateway = KnowledgeGateway(
            client=client,
            journal=InMemoryKnowledgeJournal(),
            handles=InMemoryKnowledgeHandleStore(),
            minter=self.issuer.minter(),
            knowledge=knowledge_port(BINDING),
            audience=AUDIENCE,
            clock=self.clock,
        )
        return TrustedJudgmentBridge(
            gateway=gateway,
            fulfillment=self.stack.outputs,
            store=self.stack.store,
            profile=PROFILES[self.application],
            runner=runner,
            judge_pin=JUDGE_PIN,
            retry=EvaluatorRetryPolicy(max_attempts=2),
            clock=self.clock,
        )

    def use(self) -> UseSpec:
        tenant = self.stack.access.origin.tenant_id
        return UseSpec(
            use="report_consumption",
            audience="official",
            policy=ks_ref("policy", "report-use-policy", tenant, BINDING, "policy.v1"),
            rubric=ks_ref("rubric", "report-use-rubric", tenant, BINDING, "rubric.v1"),
        )


async def world(  # type: ignore[no-untyped-def]
    application: str = "biotech",
    *,
    review_required: bool = True,
    store: Any = None,
    access: InvocationAccess | None = None,
):
    clock = SteppingClock()
    store = store if store is not None else InMemoryOutputContractStore()
    access = access or InvocationAccess(
        origin=origin(application_id=application),
        subject="mission-control-runtime",
        invocation_id="inv-producer",
        authenticated_at=clock.now,
    )
    report_obligation = obligation(
        "draft.report",
        OutputForm.TEXT,
        requirements=(Requirement(key="trusted", validator=PIN),),
    )
    submissions = getattr(store, "submissions", store)
    stack = await build_stack(store, submissions, access, report_obligation)
    ks = TrustedKnowledgeState(review_required=review_required)
    w = World(clock, Issuer(clock=clock), ks, stack, application)
    ack = await stack.submit("call-1", "draft.report", text("report", "evidence report r1"))
    revision = await store.output_revision(access.scope, ack.revisions[0].revision_id)
    assert revision is not None
    report = ks_ref("report", "report-1-r1", access.origin.tenant_id, BINDING, "research-report.v2")
    ks.reports[report.id] = ReportState(producer_subject=PRODUCER.subject)
    subject = JudgmentSubject(
        run_id=stack.run_id, revision=revision, report=report, producer=PRODUCER, generation=1
    )
    return w, subject


def evaluators(w: World) -> tuple[EvaluatorBinding, ...]:
    return (w.evaluator("judge"), w.evaluator("auditor"))


async def head_of(w: World, subject: JudgmentSubject) -> str | None:
    head = await w.stack.store.accepted_head(
        w.stack.access.scope, subject.run_id, "draft.report", "report"
    )
    return None if head is None else head.revision_id


@pytest.mark.parametrize("application", ["ai-engineer", "biotech"])
async def test_review_wait_resolves_the_exact_successor_after_a_restart(application: str) -> None:
    w, subject = await world(application)
    host = w.stack.access
    first = w.bridge(ScriptedRunner({"judge": "full_support"}))
    outcome = await first.assess(subject, evaluators(w), host, w.use())
    # Separate credentials and roles reached KS: judge and auditor grants, never the producer.
    assert [(op, role) for op, role, _sub in w.ks.calls if op == "report.observe"] == [
        ("report.observe", "judge"),
        ("report.observe", "auditor"),
    ]
    assert all(sub != PRODUCER.subject for op, _r, sub in w.ks.calls if op == "report.observe")
    assert outcome.state == "waiting" and outcome.reason == "review_pending"
    assert outcome.result == "review" and outcome.pending_reviews
    assert await head_of(w, subject) is None  # a review verdict never promotes
    assert outcome.assessment is not None
    assert outcome.assessment.assessor_origin_ref.startswith("ks:")  # not self-recorded
    # Held bytes reach an authorized repair consumer; official use is refused.
    gate = first.use_gate(outcome.resolution, purpose="review_repair", repair_authorized=True)  # type: ignore[arg-type]
    assert (gate.read_bytes, gate.official_use) == (True, False)
    assert not first.use_gate(
        outcome.resolution, purpose="official", repair_authorized=True
    ).official_use  # type: ignore[arg-type]
    assert not first.use_gate(
        outcome.resolution, purpose="review_repair", repair_authorized=False
    ).read_bytes  # type: ignore[arg-type]

    # Still waiting before any review; the wait never reruns cognition.
    restarted = w.bridge(ScriptedRunner({}))
    still = await restarted.resume(subject, host, w.use(), attempt=1)
    assert still.state == "waiting" and restarted._runner.calls == []  # type: ignore[attr-defined]

    # An unqualified review refuses; a qualified one creates the exact successor in KS.
    reviewer = w.evaluator("human_reviewer", subject="reviewer-1")
    decision = Ref.model_validate(outcome.resolution.current)  # type: ignore[union-attr]
    with pytest.raises(TrustedJudgmentRefused) as unqualified:
        await restarted.review(
            reviewer,
            decision,
            outcome="approve",
            bound_effect_digest=w.ks.decisions[decision.id]["boundEffectDigest"],
            qualifiers_digest=None,
            rationale="ok",
        )
    assert unqualified.value.reason == "reviewer_not_qualified"
    w.ks.grants.add("reviewer-1")
    with pytest.raises(TrustedJudgmentRefused) as mis_signed:
        await restarted.review(
            reviewer,
            decision,
            outcome="approve",
            bound_effect_digest="sha256:" + "f" * 64,
            qualifiers_digest=None,
            rationale="ok",
        )
    assert mis_signed.value.reason == "review_binding_mismatch"
    await restarted.review(
        reviewer,
        decision,
        outcome="approve",
        bound_effect_digest=w.ks.decisions[decision.id]["boundEffectDigest"],
        qualifiers_digest=None,
        rationale="ok",
    )
    with pytest.raises(TrustedJudgmentRefused) as stale:
        await restarted.review(
            w.evaluator("human_reviewer", subject="reviewer-2"),
            decision,
            outcome="approve",
            bound_effect_digest=w.ks.decisions[decision.id]["boundEffectDigest"],
            qualifiers_digest=None,
            rationale="late",
        )
    assert stale.value.reason == "decision_superseded"

    # Another fresh process resolves the exact successor, supersedes the review assessment and
    # promotes the revision through the expected-head CAS.
    third = w.bridge(ScriptedRunner({}))
    resolved = await third.resume(subject, host, w.use(), attempt=2)
    assert resolved.state == "settled" and resolved.result == "pass"
    assert resolved.resolution is not None
    assert resolved.resolution.current.id == f"{decision.id}-rv"
    assert resolved.assessment is not None
    assert resolved.assessment.supersedes == outcome.assessment.assessment_id
    assert resolved.promoted and await head_of(w, subject) == subject.revision.revision_id
    gate = third.use_gate(resolved.resolution, purpose="official", repair_authorized=False)
    assert gate.official_use


async def test_ungrounded_disagreement_holds_and_contrary_evidence_fails() -> None:
    w, subject = await world()
    bridge = w.bridge(
        ScriptedRunner({"judge": "full_support", "second_family_judge": "insufficient_evidence"})
    )
    held = await bridge.assess(
        subject,
        (*evaluators(w), w.evaluator("second_family_judge", credential="judge.second")),
        w.stack.access,
        w.use(),
    )
    assert held.state == "settled" and held.result == "review"  # holds; never an automated fail
    assert any(item.startswith("disputed_verdict") for item in held.findings)
    assert await head_of(w, subject) is None

    w2, subject2 = await world()
    rejected = await w2.bridge(ScriptedRunner({"judge": "contradiction"})).assess(
        subject2, evaluators(w2), w2.stack.access, w2.use()
    )
    assert rejected.result == "fail" and await head_of(w2, subject2) is None


async def test_evaluator_unavailability_waits_within_policy_then_reassesses() -> None:
    w, subject = await world(review_required=False)
    runner = ScriptedRunner({"judge": "full_support"}, unavailable={"judge": 2})
    waiting = await w.bridge(runner).assess(subject, evaluators(w), w.stack.access, w.use())
    assert waiting.state == "waiting" and waiting.reason == "evaluator_unavailable"
    assert waiting.result == "unavailable" and runner.calls == ["judge", "judge"]
    assert not [call for call in w.ks.calls if call[0] == "report.seal"]
    later = await w.bridge(ScriptedRunner({"judge": "full_support"})).assess(
        subject, evaluators(w), w.stack.access, w.use()
    )
    # The later trusted pass replaces the unavailable wait record and promotes.
    assert later.result == "pass" and later.promoted
    assert later.assessment is not None
    # Every wait record of the revision is superseded (the chain ends in the verdict).
    rows = await w.stack.store.output_assessments(w.stack.access.scope, subject.run_id)
    superseded = {row.supersedes for row in rows if row.supersedes}
    assert waiting.assessment is not None and waiting.assessment.assessment_id in superseded
    assert not [r for r in rows if r.result == "unavailable" and r.assessment_id not in superseded]
    assert await head_of(w, subject) == subject.revision.revision_id


@pytest.mark.parametrize(
    ("evaluator", "code"),
    [
        ({"subject": "mission-control-runtime"}, "EVALUATOR_IS_PRODUCER"),
        ({"credential": "producer.default"}, "EVALUATOR_CREDENTIAL_SHARED"),
        ({"vendor": "anthropic"}, "JUDGE_VENDOR_NOT_INDEPENDENT"),
    ],
)
async def test_a_producer_credential_or_vendor_never_judges(
    evaluator: dict[str, str], code: str
) -> None:
    w, subject = await world()
    judge = w.evaluator("judge", **evaluator)
    with pytest.raises(TrustedJudgmentRefused) as refused:
        await w.bridge(ScriptedRunner({"judge": "full_support"})).assess(
            subject, (judge, w.evaluator("auditor")), w.stack.access, w.use()
        )
    assert refused.value.code == code
    assert w.ks.calls == []  # refused before anything is sent


async def test_a_judge_without_an_auditor_is_not_independent_coverage() -> None:
    w, subject = await world()
    with pytest.raises(TrustedJudgmentRefused, match="INDEPENDENCE_UNPROVEN"):
        await w.bridge(ScriptedRunner({"judge": "full_support"})).assess(
            subject, (w.evaluator("judge"),), w.stack.access, w.use()
        )


async def test_only_the_bridge_supersedes_with_ks_lineage() -> None:
    w, subject = await world()
    outcome = await w.bridge(ScriptedRunner({"judge": "full_support"})).assess(
        subject, evaluators(w), w.stack.access, w.use()
    )
    prior = outcome.assessment
    assert prior is not None
    attempt = AssessmentInput(
        run_id=subject.run_id,
        subject_kind="output_revision",
        subject_id=subject.revision.revision_id,
        subject_digest=subject.revision.content_digest,
        requirement_results={"trusted": "pass"},
        method_pin=PIN,
        policy_pin="p@1",
        supersedes=prior.assessment_id,
    )
    host = w.stack.host
    refused = await w.stack.outputs.record_assessment(host, attempt)
    assert refused.error is not None and refused.error.code == "SUPERSESSION_UNAUTHORIZED"
    # S6: an assessor that is not the bridge's actor never supersedes.
    assessor = w.stack.assessor
    stranger = await w.stack.outputs.record_assessment(assessor, attempt)
    assert stranger.error is not None and stranger.error.code == "SUPERSESSION_UNAUTHORIZED"
    # The bridge's actor without a KS successor of the prior decision is still refused: the chain
    # comes from KS decision.resolve, never from the caller.
    bridge_access = w.bridge(ScriptedRunner({}))._host(w.stack.access, origin_ref="ks:x")
    no_lineage = await w.stack.outputs.record_assessment(bridge_access, attempt)
    assert no_lineage.error is not None and no_lineage.error.code == "SUPERSESSION_NOT_A_SUCCESSOR"


async def test_a_pass_recorded_before_a_crash_promotes_on_resume() -> None:
    """S1: a crash between recording pass and promoting it recovers on the next pass."""

    w, subject = await world(review_required=False)
    crashing = w.bridge(ScriptedRunner({"judge": "full_support"}))

    async def crash(*_args: Any, **_kwargs: Any) -> bool:
        raise RuntimeError("worker lost before promotion")

    crashing._promote = crash  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        await crashing.assess(subject, evaluators(w), w.stack.access, w.use())
    assert await head_of(w, subject) is None
    resumed = await w.bridge(ScriptedRunner({})).resume(subject, w.stack.access, w.use(), attempt=1)
    assert resumed.result == "pass" and resumed.promoted
    assert await head_of(w, subject) == subject.revision.revision_id


async def test_a_revoked_decision_is_re_recorded_on_resume() -> None:
    """S2: a decision whose current eligibility changed is judged again, never a stale pass."""

    w, subject = await world(review_required=False)
    passed = await w.bridge(ScriptedRunner({"judge": "full_support"})).assess(
        subject, evaluators(w), w.stack.access, w.use()
    )
    assert passed.result == "pass" and passed.resolution is not None
    assert passed.assessment is not None
    w.ks.revoked.add(passed.resolution.current.id)
    revoked = await w.bridge(ScriptedRunner({})).resume(subject, w.stack.access, w.use(), attempt=1)
    assert revoked.result == "review" and revoked.assessment is not None
    assert revoked.assessment.supersedes == passed.assessment.assessment_id
    assert revoked.resolution is not None
    # OVE-169: the head promoted on the pass stands in storage but is demoted for every consumer.
    assert passed.promoted and revoked.demoted
    assert await head_of(w, subject) == subject.revision.revision_id
    rows = await w.stack.store.output_assessments(w.stack.access.scope, subject.run_id)
    revision = subject.revision
    assert head_demoted(rows, revision.revision_id, revision.content_digest)
    gate = w.bridge(ScriptedRunner({})).use_gate(
        revoked.resolution, purpose="official", repair_authorized=False
    )
    assert not gate.official_use


async def test_a_supersede_between_pass_and_promotion_never_promotes_the_revoked_revision() -> None:
    """N1: an interleaved supersede (revocation re-recorded as review) before the promotion step
    leaves the head unset; the promotion re-reads the standing assessment and eligibility."""

    w, subject = await world(review_required=False)
    first = w.bridge(ScriptedRunner({"judge": "full_support"}))
    promote = first._promote

    async def stall(*_args: Any, **_kwargs: Any) -> bool:
        raise RuntimeError("worker paused before promotion")

    first._promote = stall  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        await first.assess(subject, evaluators(w), w.stack.access, w.use())
    rows = await w.stack.store.output_assessments(w.stack.access.scope, subject.run_id)
    passed = rows[-1]
    assert passed.result == "pass"
    decision_id, digest = passed.evidence_refs[0].split(":", 1)[1].split("@", 1)
    decision = subject.report.model_copy(
        update={
            "kind": "use_decision",
            "id": decision_id,
            "digest": digest,
            "version": "research-core.use_decision.v2",
        }
    )
    # Concurrently: the decision is revoked and another process re-records the revision as review.
    w.ks.revoked.add(decision.id)
    superseding = await w.bridge(ScriptedRunner({})).resume(
        subject, w.stack.access, w.use(), attempt=1
    )
    assert superseding.result == "review"
    # The paused process now resumes its promotion of the revoked pass: refused, head unset.
    obligation = await w.stack.store.obligation_revision(
        w.stack.access.scope, subject.run_id, "draft.report", subject.revision.obligation_revision
    )
    assert obligation is not None
    promoted = await promote(
        subject,
        w.stack.access,
        obligation,
        assessment_id=passed.assessment_id,
        decision=decision,
        use=w.use(),
    )
    assert promoted is False and await head_of(w, subject) is None


async def test_consumer_recheck_observes_revocation_in_same_invocation_and_attempt(monkeypatch):
    """KS replays immutable request IDs: seal and delivery need different read observations."""
    from unittest.mock import AsyncMock

    from mission_control.application.knowledge.trusted_settlement import (
        TrustedPlan,
        TrustedSettlement,
    )

    w, subject = await world(review_required=False)
    bridge = w.bridge(ScriptedRunner({"judge": "full_support"}))
    passed = await bridge.assess(subject, evaluators(w), w.stack.access, w.use())
    assert passed.resolution is not None
    plans = AsyncMock()
    plans.plan.return_value = TrustedPlan(evaluators=(), use=w.use(), producer=subject.producer)
    # This test's output is inline; supply its existing exact KS report for the extractor only.
    monkeypatch.setattr(
        "mission_control.application.knowledge.trusted_settlement.report_ref",
        lambda *_args, **_kwargs: subject.report,
    )
    settlement = TrustedSettlement(
        bridge=bridge, store=w.stack.store, plans=plans, assessment_pin=PIN
    )
    await settlement.recheck(w.stack.access, subject.revision)
    observed = sum(operation == "decision.resolve" for operation, _, _ in w.ks.calls)
    writes = [call for call in w.ks.calls if call[0].startswith("report.")]
    w.ks.revoked.add(passed.resolution.current.id)
    await settlement.recheck(w.stack.access, subject.revision)
    assert sum(operation == "decision.resolve" for operation, _, _ in w.ks.calls) > observed
    assert [call for call in w.ks.calls if call[0].startswith("report.")] == writes
    rows = await w.stack.store.output_assessments(w.stack.access.scope, subject.run_id)
    assert head_demoted(rows, subject.revision.revision_id, subject.revision.content_digest)
    assert rows[-1].supersedes == passed.assessment.assessment_id


async def test_revocation_between_resolve_and_promotion_records_demotion(monkeypatch):
    w, subject = await world(review_required=False)
    bridge = w.bridge(ScriptedRunner({"judge": "full_support"}))
    passed = await bridge.assess(subject, evaluators(w), w.stack.access, w.use())
    assert passed.resolution is not None and passed.promoted
    resolve = bridge.resolve
    first = True

    async def revoke_after_read(*args, **kwargs):
        nonlocal first
        result = await resolve(*args, **kwargs)
        if first:
            first = False
            w.ks.revoked.add(passed.resolution.current.id)
        return result

    monkeypatch.setattr(bridge, "resolve", revoke_after_read)
    outcome = await bridge.resume(subject, w.stack.access, w.use(), attempt=0, fresh=True)
    assert outcome.result == "review" and outcome.demoted and not outcome.promoted
    assert outcome.assessment.supersedes == passed.assessment.assessment_id
    rows = await w.stack.store.output_assessments(w.stack.access.scope, subject.run_id)
    assert head_demoted(rows, subject.revision.revision_id, subject.revision.content_digest)


@pytest.mark.parametrize("basis", ["unavailable", "missing"])
async def test_strict_current_use_waits_without_changing_standing_judgment(monkeypatch, basis):
    from unittest.mock import AsyncMock

    from mission_control.application.knowledge.trusted_settlement import TrustedSettlement

    w, subject = await world(review_required=False)
    bridge = w.bridge(ScriptedRunner({"judge": "full_support"}))
    if basis == "unavailable":
        await bridge.assess(subject, evaluators(w), w.stack.access, w.use())
    before = await w.stack.store.output_assessments(w.stack.access.scope, subject.run_id)
    plans = AsyncMock()
    plans.plan.side_effect = EvaluatorUnavailable("temporarily unavailable")
    monkeypatch.setattr(
        "mission_control.application.knowledge.trusted_settlement.report_ref",
        lambda *_args, **_kwargs: subject.report,
    )
    guard = TrustedSettlement(bridge=bridge, store=w.stack.store, plans=plans, assessment_pin=PIN)
    with pytest.raises(EvaluatorUnavailable):
        await guard.recheck(w.stack.access, subject.revision, strict=True)
    assert await w.stack.store.output_assessments(w.stack.access.scope, subject.run_id) == before
    await guard.recheck(w.stack.access, subject.revision)  # legacy policy remains unchanged


async def test_a_failing_verdict_is_sticky_no_judge_shopping() -> None:
    """N2: fail, then unavailable, then a re-assessment with a passing judge does not pass: the
    judge's first verdict stands for this revision (KS refuses a second batch from the role)."""

    w, subject = await world(review_required=False)
    failing = ScriptedRunner({"judge": "insufficient_evidence"}, unavailable={"auditor": 2})
    waiting = await w.bridge(failing).assess(subject, evaluators(w), w.stack.access, w.use())
    assert waiting.reason == "evaluator_unavailable"  # the judge's failing verdict is recorded
    again = await w.bridge(ScriptedRunner({"judge": "full_support"})).assess(
        subject, evaluators(w), w.stack.access, w.use()
    )
    assert again.result != "pass" and await head_of(w, subject) is None
    # The second judge batch was refused (evaluator_role_observed): one judge verdict is recorded.
    verdicts = w.ks.reports[subject.report.id].verdicts
    assert [role for role, _verdict in verdicts] == ["judge"]
    # OVE-169: the role lock is observable on the recorded assessment (inspection reads it).
    assert again.locked_roles == ("judge",) and again.assessment is not None
    assert f"{ROLE_LOCK_EVIDENCE_PREFIX}judge" in again.assessment.evidence_refs


class EmptyThenFull(ScriptedRunner):
    """A judge that first answers nothing, then answers (nondeterministically worded)."""

    def __init__(self) -> None:
        super().__init__({"judge": "full_support"})
        self.round = 0

    async def evaluate(
        self, evaluator: EvaluatorBinding, subject: JudgmentSubject
    ) -> EvaluatorOutput:
        self.round += 1
        if evaluator.role == "judge" and self.round == 1:
            return EvaluatorOutput()
        output = await super().evaluate(evaluator, subject)
        if evaluator.role == "judge":
            observation = dict(output.observations[0]) | {"rationale": f"round {self.round}"}
            return EvaluatorOutput(observations=(observation,))
        return output


async def test_an_empty_evaluator_answer_is_unavailability() -> None:
    """S3: an empty answer is not an evaluation; the seal waits for every required role."""

    w, subject = await world(review_required=False)
    outcome = await w.bridge(EmptyThenFull()).assess(
        subject, evaluators(w), w.stack.access, w.use()
    )
    assert outcome.result == "pass"  # the second judge attempt evaluated; the empty one did not
    judged = [call for call in w.ks.calls if call[0] == "report.observe" and call[1] == "judge"]
    assert len(judged) == 1

    w2, subject2 = await world(review_required=False)
    empty = ScriptedRunner({"judge": "full_support"})

    async def nothing(evaluator: EvaluatorBinding, subject: JudgmentSubject) -> EvaluatorOutput:
        del evaluator, subject
        return EvaluatorOutput()

    empty.evaluate = nothing  # type: ignore[method-assign]
    waiting = await w2.bridge(empty).assess(subject2, evaluators(w2), w2.stack.access, w2.use())
    assert waiting.reason == "evaluator_unavailable"
    assert not [call for call in w2.ks.calls if call[0] == "report.seal"]


async def test_a_retried_nondeterministic_judge_is_a_new_content_bound_request() -> None:
    """S4: the observe request key binds the observation content, so a judge rerun that words its
    answer differently is a new request (no EFFECT_CONFLICT on the earlier request id)."""

    w, subject = await world(review_required=False)
    first = EmptyThenFull()
    first.round = 1  # answers at once, worded "round 2"
    bridge = w.bridge(first)
    judge = w.evaluator("judge")
    assert await bridge._observe(subject, judge, w.stack.access, w.use())
    # W1 (auditor handle gap): a later pass finds the role observed and neither re-runs the
    # paid evaluator nor sends a second observation; its first batch stands.
    second = EmptyThenFull()
    second.round = 5
    assert await w.bridge(second)._observe(subject, judge, w.stack.access, w.use()) == "locked"
    assert second.calls == []
    judged = [call for call in w.ks.calls if call[0] == "report.observe" and call[1] == "judge"]
    assert len(judged) == 1
