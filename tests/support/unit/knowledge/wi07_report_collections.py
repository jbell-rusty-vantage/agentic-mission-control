"""Builders, constants and fakes that other test files import.

Moved from tests/unit/knowledge/test_report_collections.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from mission_control.adapters.outputs.memory import InMemoryOutputContractStore
from mission_control.application.knowledge.access import InvocationAccess
from mission_control.application.knowledge.judgment import TrustedOutcome
from mission_control.application.knowledge.trusted_settlement import TrustedPlan, TrustedSettlement
from mission_control.application.outputs.fulfillment import (
    AssessmentInput,
    HostAccess,
    PromoteOutput,
)
from mission_control.domain.knowledge.judgment import CognitionIdentity, decision_evidence
from mission_control.domain.outputs.contracts import (
    CandidateRef,
    Cardinality,
    EvaluationScope,
    OutputForm,
    Requirement,
)
from tests.support.knowledge.gateway import origin
from tests.unit.outputs.scenario import Stack, build_stack, digest_of, obligation

AT = datetime(2026, 10, 28, 12, tzinfo=UTC)
PIN = "knowledge.report.assess@1"


def invocation(operation: str) -> InvocationAccess:
    return InvocationAccess(
        origin=origin(1, operation_id=operation),
        subject="mission-control-runtime",
        invocation_id="inv-" + operation.replace("/", "-"),
        authenticated_at=AT,
    )


def handle(name: str) -> CandidateRef:
    return CandidateRef(
        deliverable_id=f"report-{name}",
        form=OutputForm.REFERENCE,
        kind="handle",
        ref=f"kh:aiengineer-postgres/report/{name}@research_report.v2",
        digest=digest_of(name),
    )


# TODO(OVE-238): a hand-written TrustedJudgmentBridge; TrustedSettlement takes the concrete
# bridge, so run test_report_collections over the real one on TrustedKnowledgeState with
# a ScriptedRunner (tests/support/trusted_knowledge.py). Not done in AS-S5 for size.
@dataclass
class ScriptedBridge:
    """Records one cited assessment per exact revision and promotes a pass (CAS), like the
    trusted bridge; ``verdicts`` is the KS decision per report id (changed to approve)."""

    stack: Stack
    verdicts: dict[str, str]
    assessed: list[str] = field(default_factory=list)
    resumed: list[str] = field(default_factory=list)

    def _report(self, subject: Any) -> str:
        return subject.report.id

    async def _promote(self, subject: Any) -> bool:
        revision = subject.revision
        head = await self.stack.store.accepted_head(
            self.stack.host.scope, subject.run_id, revision.obligation_key, revision.deliverable_id
        )
        if head is not None and head.revision_id == revision.revision_id:
            return True
        result = await self.stack.outputs.promote_output(
            self.stack.host,
            PromoteOutput(
                run_id=subject.run_id,
                revision_id=revision.revision_id,
                expected_head=None if head is None else head.revision_id,
                generation=subject.generation,
            ),
        )
        return result.status == "promoted"

    async def assess(self, subject: Any, evaluators: Any, host: Any, use: Any) -> TrustedOutcome:
        report = self._report(subject)
        self.assessed.append(report)
        verdict = self.verdicts[report]
        receipt = await self.stack.outputs.record_assessment(
            HostAccess(
                scope=host.scope,
                actor_ref="mission-control:trusted-judgment",
                origin_ref=f"ks:decision/{report}",
                role="assessor",
            ),
            AssessmentInput(
                run_id=subject.run_id,
                subject_kind="output_revision",
                subject_id=subject.revision.revision_id,
                subject_digest=subject.revision.content_digest,
                requirement_results={"assessed": verdict},  # type: ignore[dict-item]
                method_pin=PIN,
                policy_pin="policy@1",
                evidence_refs=(decision_evidence(f"d-{report}", digest_of(report)),),
            ),
        )
        assert receipt.status == "recorded", receipt.error
        if verdict == "review":
            return TrustedOutcome(
                state="waiting",
                result="review",
                reason="review_pending",
                pending_reviews=(decision_evidence(f"d-{report}", digest_of(report)),),
            )
        promoted = verdict == "pass" and await self._promote(subject)
        return TrustedOutcome(state="settled", result=verdict, promoted=promoted)  # type: ignore[arg-type]

    async def resume(self, subject: Any, host: Any, use: Any, *, attempt: int) -> TrustedOutcome:
        report = self._report(subject)
        self.resumed.append(report)
        if self.verdicts[report] == "review":
            return TrustedOutcome(
                state="waiting",
                result="review",
                reason="review_pending",
                pending_reviews=(decision_evidence(f"d-{report}", digest_of(report)),),
            )
        # An approved KS successor: like the real bridge, supersede the held judgment of the same
        # exact subject citing the successor chain, then promote by compare-and-set.
        revision = subject.revision
        standing = [
            item
            for item in await self.stack.store.output_assessments(host.scope, subject.run_id)
            if item.subject_id == revision.revision_id and item.result == "review"
        ]
        superseded = {
            item.supersedes
            for item in await self.stack.store.output_assessments(host.scope, subject.run_id)
            if item.supersedes
        }
        open_waits = [item for item in standing if item.assessment_id not in superseded]
        if open_waits:
            receipt = await self.stack.outputs.record_assessment(
                HostAccess(
                    scope=host.scope,
                    actor_ref="mission-control:trusted-judgment",
                    origin_ref=f"ks:decision/{report}-approved",
                    role="assessor",
                ),
                AssessmentInput(
                    run_id=subject.run_id,
                    subject_kind="output_revision",
                    subject_id=revision.revision_id,
                    subject_digest=revision.content_digest,
                    requirement_results={"assessed": "pass"},
                    method_pin=PIN,
                    policy_pin="policy@1",
                    evidence_refs=(decision_evidence(f"d-{report}-2", digest_of(report)),),
                    supersedes=open_waits[-1].assessment_id,
                ),
                lineage=Lineage(),
            )
            assert receipt.status == "recorded", receipt.error
        return TrustedOutcome(state="settled", result="pass", promoted=await self._promote(subject))


class Lineage:
    """KS answers the successor chain of the held decision (the review approved it)."""

    async def successor_chain(self, decision_evidence: str) -> tuple[str, ...]:
        held = decision_evidence.removeprefix("ks-use-decision:").split("@", 1)[0]
        return (held, f"{held}-2")


class CurrentUse:
    """Every exact reference revision is currently usable (WI-03 port, scripted)."""

    async def reference_uses(self, scope: str, members: Any) -> dict[str, str]:
        return {item.revision_id: f"ks-use:{item.revision_id}" for item in members}


class Plans:
    async def plan(self, access: InvocationAccess, revision: Any) -> TrustedPlan:
        producer = CognitionIdentity(
            credential_ref="producer",
            subject=access.subject,
            operation_ref=access.origin.operation_id,
            vendor="anthropic",
        )
        return TrustedPlan(evaluators=(), use=None, producer=producer)  # type: ignore[arg-type]


async def stack_with(scope: EvaluationScope) -> Stack:
    store = InMemoryOutputContractStore()
    reports = obligation(
        "goal.reports",
        OutputForm.REFERENCE,
        position="goal",
        cardinality=Cardinality(min=3, max=3),
        requirements=(Requirement(key="assessed", validator=PIN),),
    ).model_copy(update={"evaluation_scope": scope})
    stack = await build_stack(
        store, store.submissions, invocation("goal-iteration/1/executor"), reports
    )
    stack.outputs._reference_uses = CurrentUse()
    return stack


def settlement(stack: Stack, bridge: ScriptedBridge) -> TrustedSettlement:
    return TrustedSettlement(
        bridge=bridge,  # type: ignore[arg-type]
        store=stack.store,
        plans=Plans(),
        assessment_pin=PIN,
    )


async def run_iteration(stack: Stack, number: int, *names: str) -> InvocationAccess:
    access = invocation(f"goal-iteration/{number}/executor")
    worker = await stack.start(access)
    ack = await worker.submit(
        f"i{number}", "goal.reports", *(handle(name) for name in names), position="goal"
    )
    assert ack.status == "accepted", ack.error
    report = await stack.submissions.finalize(access.identity(("goal.reports",)))
    assert report.finalization_id is not None  # one act naming several reports finalizes
    return access
