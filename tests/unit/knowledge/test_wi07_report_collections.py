"""WI-07 / OVE-170: a report collection is assessed per member; goal-scoped waits do not hold.

The trusted settlement pass (``application/knowledge/trusted_settlement.py``) over the in-memory
1.7.0 store with a scripted bridge standing in for the KS transport (the real bridge is proven in
``test_trusted_judgment.py`` and on PostgreSQL). Proves: one ``submit_output`` act naming three
report handles finalizes (the OVE-160 refusal applies to the legacy selection path only) and is
assessed per exact revision, never through one report; a held member of a goal-scoped promise
never holds its invocation while an invocation-scoped one does; a later invocation's settlement
re-resolves the goal wait and promotes the approved member exactly once; successes are retained.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

from mission_control.application.knowledge.access import InvocationAccess
from mission_control.application.knowledge.judgment import TrustedOutcome
from mission_control.application.knowledge.trusted_settlement import (
    TrustedPlan,
    TrustedSettlement,
    pending_or_raise,
)
from mission_control.application.outputs.fulfillment import (
    AssessmentInput,
    HostAccess,
    PromoteOutput,
)
from mission_control.application.outputs.submission_service import SubmissionService
from mission_control.domain.knowledge.judgment import CognitionIdentity, decision_evidence
from mission_control.domain.outputs.contracts import (
    CandidateRef,
    Cardinality,
    EvaluationScope,
    OutputForm,
    Requirement,
)
from tests.fixtures.output_contracts import InMemoryOutputContractStore
from tests.unit.knowledge.test_gateway import origin
from tests.unit.outputs.scenario import Stack, build_stack, digest_of, fulfillment, obligation

pytestmark = pytest.mark.asyncio
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


class NoLegacyAssessor:
    """The K01 single-report handoff must not run for a named multi-report act."""

    binding = "aiengineer-postgres"

    async def invoke(self, call: Any, access: Any) -> Any:
        raise AssertionError("one report must never stand for the collection")

    async def poll(self, record: Any, caller: Any, *, scope: str) -> Any:
        raise AssertionError

    async def stored_handle(self, scope: str, operation_id: str) -> Any:
        return None


async def test_one_named_act_with_three_reports_is_assessed_per_exact_revision() -> None:
    stack = await stack_with(EvaluationScope.GOAL)
    stack.submissions._assessor = NoLegacyAssessor()  # type: ignore[assignment]
    bridge = ScriptedBridge(stack, {"a": "pass", "b": "pass", "c": "fail"})
    access = await run_iteration(stack, 1, "a", "b", "c")
    passed = await settlement(stack, bridge).settle(access, attempt=1)
    assert sorted(bridge.assessed) == ["a", "b", "c"]  # each member judged once, by itself
    assert len(passed.promoted) == 2 and not pending_or_raise(passed)
    result = await stack.evaluate()
    decided = fulfillment(result, "goal.reports")
    assert decided.distinct_count == 2 and decided.disposition == "unfulfilled"


async def test_the_legacy_selection_keeps_its_one_report_refusal() -> None:
    store = InMemoryOutputContractStore()
    service = SubmissionService(store.submissions)
    from mission_control.application.outputs.submission_service import (
        OutputSelection,
        SelectedItem,
    )

    items = tuple(
        SelectedItem(kind="handle", ref=handle(name).ref or "", digest=digest_of(name))
        for name in ("a", "b")
    )
    with pytest.raises(ValueError, match="report must be the only selected item"):
        await service.submit(
            invocation("legacy"), "report", OutputSelection(items=items), "collection"
        )


async def test_a_goal_scoped_review_wait_never_holds_independent_work() -> None:
    stack = await stack_with(EvaluationScope.GOAL)
    bridge = ScriptedBridge(stack, {"a": "pass", "b": "review", "c": "pass"})
    first = await run_iteration(stack, 1, "a", "b")
    one = await settlement(stack, bridge).settle(first, attempt=1)
    assert pending_or_raise(one) == ()  # the invocation settles; independent work proceeds
    assert len(one.goal_waits) == 1 and "d-b" in one.goal_waits[0]
    blocked = await stack.evaluate()
    assert fulfillment(blocked, "goal.reports").disposition == "unfulfilled"  # acceptance blocked
    # Iteration 2 works independently; its settlement re-resolves the standing goal wait.
    second = await run_iteration(stack, 2, "c")
    two = await settlement(stack, bridge).settle(second, attempt=2)
    assert bridge.resumed == ["b"] and two.goal_waits and not pending_or_raise(two)
    assert fulfillment(await stack.evaluate(), "goal.reports").distinct_count == 2
    # The reviewer approves; the next settlement promotes b exactly once; a and c are retained.
    bridge.verdicts["b"] = "pass"
    third = await run_iteration(stack, 3, "c")  # a repeat of c: same content, no new deliverable
    three = await settlement(stack, bridge).settle(third, attempt=3)
    assert three.goal_waits == () and len(three.promoted) >= 1
    done = await stack.evaluate()
    assert fulfillment(done, "goal.reports").disposition == "fulfilled"
    assert fulfillment(done, "goal.reports").distinct_count == 3
    heads = await stack.store.accepted_outputs(stack.host.scope, stack.run_id)
    assert sorted(item.deliverable_id for item in heads) == ["report-a", "report-b", "report-c"]
    again = await settlement(stack, bridge).settle(third, attempt=4)
    assert again.goal_waits == ()  # nothing waits any more; no duplicate head moves
    assert len(await stack.store.accepted_outputs(stack.host.scope, stack.run_id)) == 3


async def test_an_invocation_scoped_review_still_holds_its_own_invocation() -> None:
    stack = await stack_with(EvaluationScope.INVOCATION)
    bridge = ScriptedBridge(stack, {"a": "review"})
    access = await run_iteration(stack, 1, "a")
    passed = await settlement(stack, bridge).settle(access, attempt=1)
    assert pending_or_raise(passed) and passed.goal_waits == ()
    # A later pass of the same saved result keeps holding on the exact decision (the held
    # revision is no longer a submitted output, so only the resume pass sees it), never lost.
    again = await settlement(stack, bridge).settle(access, attempt=2)
    assert again.pending_reviews == passed.pending_reviews and bridge.resumed == ["a"]
    # Another invocation's settlement never re-resolves this invocation-scoped wait.
    other = await settlement(stack, bridge).settle(
        invocation("goal-iteration/9/executor"), attempt=3
    )
    assert other.pending_reviews == () and bridge.resumed == ["a"]
    bridge.verdicts["a"] = "pass"
    approved = await settlement(stack, bridge).settle(access, attempt=4)
    assert approved.pending_reviews == () and len(approved.promoted) == 1
