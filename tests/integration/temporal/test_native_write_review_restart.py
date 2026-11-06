"""W1 native write: a plan decision waiting on review across a worker restart (Temporal + PG).

The `OperationWorkflow` (time-skipping server) drives the real operation boundary with the saved
provider result in `mission_control.invocation_settlement` (WI-04). In the invocation, the
agent's `knowledge_apply` of an accepted AI Engineer report ran the host sequence (doubled KS:
derive, `knowledge.plan_preview`, plan-level decide, record) and the plan decision waits on a
qualified review. The lane's settler is the native write's settlement pass: pass 1 (worker 1)
waits `review_pending` on the exact plan decision; while no worker runs the reviewer approves;
pass 2 (worker 2, after the durable timer) re-resolves the decision and applies it exactly once,
under the same invocation's origin (provisional, ESCALATION H12). Cognition ran once.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import asyncpg
import pytest
import pytest_asyncio
from temporalio.api.enums.v1 import EventType

from mission_control.adapters.knowledge.decisions import InMemoryUseDecisionStore
from mission_control.adapters.postgres.operations.invocation_settlement import (
    PostgresInvocationSettlementStore,
)
from mission_control.application.execution.operations.journaled_operation_execution import (
    output_payload,
)
from mission_control.domain.execution.contracts import RuntimeInvocation
from mission_control.domain.execution.invocation_settlement import (
    SettlementOutcome,
    SettlementState,
    WaitReason,
)
from mission_control.domain.knowledge.effects import JournalState
from tests.fixtures.checkpoint_recovery import recovery_harness, stage_recovery_unit
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.fixtures.saved_settlement import DurableEffectDouble
from tests.integration.postgres.runtime_common import common_db  # noqa: F401
from tests.integration.temporal.test_wi04_saved_settlement_restart import (
    _environment,
    _replays,
    _scheduled,
    _Stack,
)
from tests.unit.knowledge.test_native_write import (
    DIGEST,
    HANDLE,
    PLAN,
    Applier,
    Bridge,
    Preview,
    accepted_report,
    service,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.common_db]


@pytest_asyncio.fixture
async def pool(common_db: CommonDatabase) -> AsyncIterator[asyncpg.Pool]:  # noqa: F811
    await common_db.add_tenants(["tenant-1"])
    created = await common_db.pool()
    try:
        yield created
    finally:
        await created.close()


EFFECT_KEY = "ek1:" + "b" * 64
RECEIPT_REF = "aiengineer-postgres/native_receipt/native-1@receipt.v1"


class ReceiptApplier(Applier):
    async def __call__(self, handle: str) -> Any:
        self.handles.append(handle)
        return SimpleNamespace(
            state=JournalState.APPLIED,
            refusal_code=None,
            document=lambda: {
                "effect_key": EFFECT_KEY,
                "receipt_ref": RECEIPT_REF,
                "journal_state": "applied",
                "raw_receipt": "PRIVATE_RECEIPT_BODY",
            },
        )


class NativeSettler:
    """The WI-04 `InvocationSettler` whose pass is the native write's settlement pass."""

    def __init__(self, native: Any, access: Any, apply: Applier) -> None:
        self.native = native
        self.access = access
        self.apply = apply
        self.passes: list[str] = []

    def applies(self, invocation: RuntimeInvocation) -> bool:
        del invocation
        return True

    async def settle(
        self, invocation: RuntimeInvocation, *, fenced: bool = False
    ) -> SettlementOutcome:
        del invocation, fenced
        outcome = await self.native.settle(
            self.access, attempt=len(self.passes) + 10, apply=self.apply
        )
        pending = outcome.pending_reviews
        detail = {
            "native_effects": [row.document() for row in outcome.outcomes],
            "raw_provider_body": "PRIVATE_SETTLEMENT_DETAIL",
        }
        if pending:
            self.passes.append("waiting")
            return SettlementOutcome(
                state="waiting",
                reason=WaitReason.REVIEW_PENDING,
                pending_reviews=pending,
                detail=detail,
            )
        self.passes.append("settled")
        return SettlementOutcome.done(
            fulfillment_refs=("obligation:root.native_receipt",), detail=detail
        )


async def test_a_plan_review_wait_survives_a_restart_and_applies_once(
    common_db: CommonDatabase,  # noqa: F811
    pool: asyncpg.Pool,
) -> None:
    stack_outputs = await accepted_report()
    bridge = Bridge(InMemoryUseDecisionStore(), pending=True)
    preview = Preview()
    native = service(stack_outputs, bridge, preview=preview)
    apply = ReceiptApplier()
    # The agent's tool call in this invocation: the whole host sequence up to the review wait.
    first = await native.write(
        stack_outputs.access, HANDLE, DIGEST, plan_reports=PLAN, attempt=1, apply=apply
    )
    assert first.state == "pending_review" and not apply.handles
    settler = NativeSettler(native, stack_outputs.access, apply)
    effects = DurableEffectDouble(acknowledge_on_write=True)
    scope = common_db.scope("tenant-1")
    store = PostgresInvocationSettlementStore(pool, require_unit_generation=False)
    harness = await recovery_harness(request_scope=scope, saved_results=store, settlers=(settler,))
    effects.attach(harness.model, answer_turns=(2, 4, 6))
    request = await harness.request(stage_recovery_unit(harness.run_id, request_scope=scope))
    environment = await _environment()
    async with environment:
        stack = _Stack(harness, environment, store)
        with environment.auto_time_skipping_disabled():
            async with stack.workflow_worker():
                async with stack.activity_worker("native-worker-1"):
                    handle = await stack.start(request, "w1-native-plan-review-restart")
                    waiting = await stack.until(request, SettlementState.WAITING)

                    # The DB wait precedes activity completion. Keep this worker alive until
                    # the workflow has consumed the result and started its durable review timer;
                    # otherwise stopping here races a retry of the still-running activity.
                    async def timer_started() -> None:
                        while True:
                            snapshot = await handle.fetch_history()
                            if any(
                                event.event_type == EventType.EVENT_TYPE_TIMER_STARTED
                                for event in snapshot.events
                            ):
                                return
                            await asyncio.sleep(0.01)

                    await asyncio.wait_for(timer_started(), timeout=15)
                assert list(waiting.pending_reviews) == list(first.pending_reviews)
                assert waiting.next_action == "await_review" and not apply.handles
                assert (
                    waiting.evidence()["invocation_settlement"]["native_effects"][0]["state"]
                    == "pending_review"
                )
                # A scheduler retry may re-observe the pending decision before this worker
                # stops. Pending observations may repeat; cognition and the native effect
                # remain exact. Freeze this prefix while no worker runs, then require one
                # settled pass after approval with no further pending review or dispatch.
                passes_before_approval = tuple(settler.passes)
                assert passes_before_approval
                assert all(state == "waiting" for state in passes_before_approval)
                bridge.pending = False  # no worker runs: the reviewer approves the plan decision
                async with stack.activity_worker("native-worker-2"):
                    await environment.sleep(30)  # the durable timer fires
                    result = await asyncio.wait_for(handle.result(), timeout=120)
                    history = await _replays(handle)
    assert result.disposition == "completed"
    assert _scheduled(history) == ["operation.execute", "operation.execute"]
    assert harness.runtime.invocations == 1, "the saved result was never redispatched"
    assert settler.passes == [*passes_before_approval, "settled"]
    assert apply.handles == [first.decision.handle], "applied exactly once, after approval"
    assert len(bridge.decided) == 1 and len(preview.calls) == 1 + len(settler.passes), (
        "one immutable decision, fresh preview for the tool call and each settlement pass"
    )
    record = await stack.record(request)
    assert record is not None and record.settled
    # A fresh repository read after both workers stopped returns the receipt references.
    reread = await PostgresInvocationSettlementStore(pool, require_unit_generation=False).get(
        record.request_scope, record.binding_id
    )
    assert reread is not None
    references = reread.evidence()["invocation_settlement"]["native_effects"]
    assert references[0]["receipt_ref"] == RECEIPT_REF
    assert references[0]["effect_key"] == EFFECT_KEY
    assert "raw_receipt" not in references[0]
    assert reread.saved_result_digest == record.saved_result_digest
    # Exercise the actual settled operation result's digest-bound event-payload channel.
    import json

    assert harness.bindings is not None
    binding = await harness.bindings.get_binding(
        request.identity.semantic_key, request_scope=request.request_scope
    )
    assert binding is not None
    operation_result = await harness.coordinator.get_settlement(binding)
    assert operation_result is not None
    result_payload = json.loads(output_payload(operation_result))
    projected = next(
        item["invocation_settlement"]
        for item in result_payload["event_payloads"]
        if "invocation_settlement" in item
    )
    assert projected["native_effects"] == references
    assert "PRIVATE_" not in json.dumps(projected)

    print(
        "NATIVE RESTART EVIDENCE",
        {
            "passes_before_approval": passes_before_approval,
            "passes": settler.passes,
            "cognition_dispatches": harness.runtime.invocations,
            "native_applies": len(apply.handles),
            "plan_decisions": len(bridge.decided),
            "previews": len(preview.calls),
            "scheduled_activities": _scheduled(history),
            "activity_attempts": [
                event.activity_task_started_event_attributes.attempt
                for event in history.events
                if event.HasField("activity_task_started_event_attributes")
            ],
            "activity_timeout_event_ids": [
                event.event_id
                for event in history.events
                if event.HasField("activity_task_timed_out_event_attributes")
            ],
        },
    )


async def test_explicit_native_selection_fulfills_after_review_successor_and_saved_restart(
    common_db: CommonDatabase,  # noqa: F811
    pool: asyncpg.Pool,
) -> None:
    """Real MC PG/Temporal boundary; KS transport is doubled with an immutable review successor."""
    from mission_control.adapters.deep_agents.knowledge_tools import live_invocation
    from tests.fixtures.native_receipt_selection import (
        approve_review_successor,
        pending_receipt_case,
    )

    case = None

    class ExplicitSettler:
        def __init__(self):
            self.passes = []

        def applies(self, invocation):
            return True

        async def settle(self, invocation, *, fenced=False):
            assert case is not None
            actual = live_invocation(invocation)
            assert (
                case.live.request_scope,
                case.live.run_id,
                case.live.operation_id,
                case.live.operation_attempt,
                case.live.execution_generation,
                case.live.lane,
            ) == (
                actual.request_scope,
                actual.run_id,
                actual.operation_id,
                actual.operation_attempt,
                actual.execution_generation,
                actual.lane,
            )
            report, pending = await case.tools.toolset.settle_saved(case.live, fenced=fenced)
            detail = {"native_effects": list(report.native_effects)}
            if pending:
                self.passes.append("waiting")
                return SettlementOutcome(
                    state="waiting",
                    reason=WaitReason.REVIEW_PENDING,
                    pending_reviews=tuple(pending),
                    detail=detail,
                )
            assert (await case.converge()).disposition == "fulfilled"
            self.passes.append("settled")
            return SettlementOutcome.done(
                fulfillment_refs=("obligation:root.native_receipt",), detail=detail
            )

    settler = ExplicitSettler()
    store = PostgresInvocationSettlementStore(pool, require_unit_generation=False)
    harness = await recovery_harness(
        request_scope=common_db.scope("tenant-1"), saved_results=store, settlers=(settler,)
    )
    execute = harness.runtime.execute

    async def execute_producer(invocation, secrets):
        nonlocal case
        assert case is None, "saved settlement must never dispatch producer cognition again"
        case = await pending_receipt_case(live_invocation(invocation))
        await case.select()  # explicit tool calls in the actual runtime coordinates, before save
        assert not case.tools.journal.rows
        return await execute(invocation, secrets)

    harness.runtime.execute = execute_producer
    effects = DurableEffectDouble(acknowledge_on_write=True)
    effects.attach(harness.model, answer_turns=(2, 4, 6))
    request = await harness.request(
        stage_recovery_unit(harness.run_id, request_scope=common_db.scope("tenant-1"))
    )
    environment = await _environment()
    async with environment:
        stack = _Stack(harness, environment, store)
        with environment.auto_time_skipping_disabled():
            async with stack.workflow_worker():
                async with stack.activity_worker("explicit-native-worker-1"):
                    handle = await stack.start(request, "explicit-native-review-restart")
                    waiting = await stack.until(request, SettlementState.WAITING)

                    async def timer_started():
                        while not any(  # noqa: ASYNC110 - poll externally owned Temporal history
                            e.event_type == EventType.EVENT_TYPE_TIMER_STARTED
                            for e in (await handle.fetch_history()).events
                        ):
                            await asyncio.sleep(0.01)

                    await asyncio.wait_for(timer_started(), timeout=15)
                assert waiting.saved_result is not None and not case.tools.fake.calls_of("invoke")
                prefix = tuple(settler.passes)
                approve_review_successor(case)  # no worker/cognition runs here
                async with stack.activity_worker("explicit-native-worker-2"):
                    await environment.sleep(30)
                    result = await asyncio.wait_for(handle.result(), timeout=120)
                    history = await _replays(handle)
    assert case is not None
    selected = case.answer["result"]["effect_key"]
    assert case.live.run_id == harness.run_id
    assert result.disposition == "completed" and harness.runtime.invocations == 1
    assert _scheduled(history) == ["operation.execute", "operation.execute"]
    assert settler.passes == [*prefix, "settled"] and case.selections == 1
    assert len(case.tools.fake.calls_of("invoke")) == 1 and len(case.bridge.decided) == 1
    assert (await case.converge()).disposition == "fulfilled"
    row = await stack.record(request)
    fresh = await PostgresInvocationSettlementStore(pool, require_unit_generation=False).get(
        row.request_scope, row.binding_id
    )
    refs = fresh.evidence()["invocation_settlement"]["native_effects"]
    assert refs[0]["effect_key"] == selected and refs[0]["receipt_ref"]
    assert fresh.saved_result_digest == waiting.saved_result_digest
    access = case.tools.toolset.access(case.live)
    journal = await case.tools.journal.lookup(access.scope, selected)
    assert journal.originating_origin.mission.runId == fresh.run_id == case.live.run_id
    roots = await case.bridge.store.for_invocation(access.scope, access.invocation_ref)
    assert len(roots) == 1 and roots[0].invocation_ref == access.invocation_ref
    revision = await case.stack.store.output_revision(
        access.scope, case.submission["result"]["revisions"][0]["revision_id"]
    )
    assert revision.run_id == fresh.run_id
    assert revision.producer_origin_ref == roots[0].invocation_ref
    import json

    binding = await harness.bindings.get_binding(
        request.identity.semantic_key, request_scope=request.request_scope
    )
    operation = await harness.coordinator.get_settlement(binding)
    payload = json.loads(output_payload(operation))
    projected = next(
        x["invocation_settlement"]
        for x in payload["event_payloads"]
        if "invocation_settlement" in x
    )
    assert projected["native_effects"] == refs
    print(
        "EXPLICIT NATIVE SAVED RESTART",
        {
            "cognition": harness.runtime.invocations,
            "submissions": case.selections,
            "applies": len(case.tools.fake.calls_of("invoke")),
            "fulfillment": "fulfilled",
            "passes": settler.passes,
            "effect_key": selected,
            "receipt_ref": refs[0]["receipt_ref"],
        },
    )
