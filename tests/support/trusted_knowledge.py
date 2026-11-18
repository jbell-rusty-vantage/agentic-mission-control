"""Builders, constants and fakes that other test files import.

Moved from tests/unit/knowledge/test_trusted_judgment.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mission_control.application.knowledge.access import InvocationAccess
from mission_control.application.knowledge.gateway import KnowledgeGateway
from mission_control.application.knowledge.judgment import (
    EvaluatorBinding,
    EvaluatorOutput,
    EvaluatorRetryPolicy,
    EvaluatorUnavailable,
    JudgmentSubject,
    TrustedJudgmentBridge,
    UseSpec,
)
from mission_control.domain.knowledge.judgment import CognitionIdentity, EvaluatorPin
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
from tests.support.knowledge import origin
from tests.unit.outputs.scenario import build_stack, obligation, text

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
