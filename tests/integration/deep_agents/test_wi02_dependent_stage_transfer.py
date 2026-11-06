"""WI-02: a dependent stage reads its upstream report through the sealed plan, and a changed or
unavailable upstream member blocks its readiness before any model call.

Replaces the removed run-wide "tampered upstream blocks the next stage" acceptance through the new
path: the dependent stage's selection is the Stage Graph builder's (its declared
``from: draft.report`` binding); the upstream report is the producer's finalized submission; the
exact read goes through the real knowledge gateway over the verifying fake binding (Ed25519
credentials); the receiver is a real ``create_deep_agent`` graph with a scripted local model.
"""

from __future__ import annotations

from collections import deque
from datetime import timedelta
from typing import Any

import pytest
from tests.acceptance.control_plane.test_wp_cp_040 import registry
from tests.fixtures.checkpoint_lineage import activity_attempt
from tests.fixtures.knowledge_binding import (
    AUDIENCE,
    BINDING,
    FakeKnowledgeBinding,
    InMemoryKnowledgeHandleStore,
    InMemoryKnowledgeJournal,
    InMemoryStaging,
    InMemoryTransferPlanStore,
    Issuer,
    RecordingMinter,
    SteppingClock,
    knowledge_port,
    report_package,
)
from tests.integration.deep_agents.test_wi02_transfer_plan_lane import (
    PlanReadingModel,
    _invocation,
    _selection,
)
from tests.unit.context.test_transfer_materializer import FakeOutputs
from tests.unit.knowledge.test_gateway import TENANT, origin

from mission_control.adapters.deep_agents.adapter import DeepAgentRuntimeAdapter
from mission_control.adapters.deep_agents.materializer import ExactDeepAgentMaterializer
from mission_control.application.context.materialization import (
    ContextDeliveryBlocked,
    KnowledgeReadAccess,
    ProducedOutputResolver,
    TransferMaterializer,
)
from mission_control.application.context.resolution import ContentResolutionService
from mission_control.application.execution.operations.checkpoint_lineage import (
    CheckpointLineageService,
    InMemoryCheckpointLineageRepository,
)
from mission_control.application.knowledge.access import InvocationAccess
from mission_control.application.knowledge.gateway import KnowledgeGateway
from mission_control.domain.context import transfer_builders
from mission_control.domain.outputs.contracts import (
    ExactOutput,
    OutputContract,
    OutputForm,
    OutputObligation,
)


async def _no_sleep(_seconds: float) -> None:
    return None


class _ReceiverAccess:
    """The lane's knowledge support as the materializer sees it: a fresh host access for the
    receiving attempt (the receiver itself has no knowledge tools)."""

    def __init__(self, clock: SteppingClock) -> None:
        self._clock = clock

    def uses_knowledge(self, invocation: Any) -> bool:
        return False

    def scope_reads(self, plan: Any) -> None:
        self.scoped = plan

    async def access_for(self, invocation: Any) -> InvocationAccess:
        attempt = invocation.binding.operation_attempt
        return InvocationAccess(
            origin=origin(attempt, operation_id="op-review-1"),
            subject="mission-control-runtime",
            invocation_id=f"inv-review-{attempt}",
            authenticated_at=self._clock.now,
        )


def _stack() -> tuple[Any, ...]:
    clock = SteppingClock(step=timedelta(milliseconds=1))
    issuer = Issuer(clock=clock)
    fake = FakeKnowledgeBinding(verifier=issuer.verifier(), clock=clock)
    fake.operation_statuses["knowledge.read"] = deque(["succeeded"] * 32)
    gateway = KnowledgeGateway(
        client=fake,
        journal=InMemoryKnowledgeJournal(),
        handles=InMemoryKnowledgeHandleStore(),
        minter=RecordingMinter(issuer.minter()),
        content=fake,
        knowledge=knowledge_port(BINDING),
        audience=AUDIENCE,
        clock=clock,
        sleep=_no_sleep,
    )
    support = _ReceiverAccess(clock)
    reports = ContentResolutionService(gateway)
    outputs = FakeOutputs()
    staging = InMemoryStaging()
    store = InMemoryTransferPlanStore()
    materializer = TransferMaterializer(
        store=store,
        staging=staging,
        custody=staging,
        resolvers={"produced_output": ProducedOutputResolver(outputs, reports=reports)},  # type: ignore[arg-type]
        access={"produced_output": KnowledgeReadAccess(reports)},
        clock=clock,
    )
    return fake, outputs, store, staging, support, materializer


def _dependent(invocation_tenant: str) -> Any:
    invocation, binding, bundle = _invocation()
    base = transfer_builders.first_invocation("review", _selection().bounds, _selection().backend)
    selection = transfer_builders.dependent_stage(base, [("draft", "draft", "draft.report")])
    request = invocation.binding.model_copy(update={"transfer": selection})
    return invocation.model_copy(update={"binding": request}), binding, bundle


def _submitted(fake: FakeKnowledgeBinding, outputs: FakeOutputs, run_id: str) -> Any:
    package = fake.register_package(
        report_package("report-7", "1", tenant=TENANT, body=b"# Exact upstream findings\n")
    )
    report = package.report
    outputs.obligations.append(
        OutputObligation(
            key="draft.report",
            owner_position="draft",
            contract=OutputContract(form=OutputForm.REFERENCE),
        )
    )
    outputs.accepted.append(
        ExactOutput(
            revision_id="rev-draft-1",
            run_id=run_id,
            obligation_key="draft.report",
            obligation_revision=1,
            deliverable_id="report",
            revision=1,
            form=OutputForm.REFERENCE,
            content_digest=report.digest,
            candidate={
                "kind": "handle",
                "ref": f"kh:{report.binding}/report/{report.id}@{report.version}",
            },
            producer_origin_ref="mc-inv:draft",
        )
    )
    return package


async def _run(adapter: DeepAgentRuntimeAdapter, invocation: Any) -> Any:
    lineage = CheckpointLineageService(InMemoryCheckpointLineageRepository())
    plan = await lineage.observe_attempt(invocation.binding, activity_attempt(1), dispatching=True)
    return await adapter.execute(invocation.model_copy(update={"checkpoint_plan": plan}), {})


@pytest.mark.asyncio
async def test_the_dependent_stage_reads_its_exact_upstream_report_through_the_plan() -> None:
    fake, outputs, store, _staging, support, materializer = _stack()
    invocation, binding, bundle = _dependent(TENANT)
    package = _submitted(fake, outputs, invocation.binding.run_id)
    PlanReadingModel.paths = [
        "/inputs/draft/report-7_research-report.v2/body.md",
    ]
    PlanReadingModel.observed = []
    adapter = DeepAgentRuntimeAdapter(
        ExactDeepAgentMaterializer(registry(binding, bundle, PlanReadingModel())),
        transfer=materializer,
        knowledge=support,  # type: ignore[arg-type]
    )
    result = await _run(adapter, invocation)
    assert result.output_text == "plan observed"
    (observed,) = PlanReadingModel.observed
    assert "Exact upstream findings" in observed
    (plan,) = store.plans.values()
    assert plan.boundary.value == "dependent_stage"
    assert {m.source_ref for m in plan.exact_sources} == {"rev-draft-1"}
    body = next(m for m in plan.exact_sources if m.part == "body")
    assert body.size_bytes == len(package.body)


@pytest.mark.asyncio
async def test_a_changed_or_unavailable_upstream_member_blocks_the_dependent_stage() -> None:
    fake, outputs, store, staging, support, materializer = _stack()
    invocation, binding, bundle = _dependent(TENANT)
    _submitted(fake, outputs, invocation.binding.run_id)
    PlanReadingModel.paths = ["/inputs/draft/report-7_research-report.v2/body.md"]
    adapter = DeepAgentRuntimeAdapter(
        ExactDeepAgentMaterializer(registry(binding, bundle, PlanReadingModel())),
        transfer=materializer,
        knowledge=support,  # type: ignore[arg-type]
    )
    await _run(adapter, invocation)  # sealed and ready once
    (plan,) = store.plans.values()
    # (1) The upstream bytes in custody are tampered: a redelivery is refused before any model
    # call (the plan is reused, never re-resolved).
    body = next(m for m in plan.exact_sources if m.part == "body")
    assert body.custody_ref is not None
    original = staging.objects[body.custody_ref]
    staging.objects[body.custody_ref] = original + b"tampered"
    PlanReadingModel.observed = []
    with pytest.raises(ContextDeliveryBlocked, match="DIGEST_MISMATCH"):
        await _run(adapter, invocation)  # a restart redelivers
    assert PlanReadingModel.observed == []
    # (2) The exact upstream revision is no longer available at KS: readiness stops too.
    staging.objects[body.custody_ref] = original
    fake.packages.clear()
    with pytest.raises(ContextDeliveryBlocked):
        await _run(adapter, invocation)
    assert PlanReadingModel.observed == []
    receipts = await store.receipts(plan.receiver.scope, plan.plan_id)
    assert [receipt.result for receipt in receipts] == ["ready", "refused", "refused"]
