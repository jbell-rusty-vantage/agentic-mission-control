"""WI-04 / OVE-166 (RV-01): saved-result settlement on real Temporal with PostgreSQL custody.

The `OperationWorkflow` (time-skipping test server) drives the real operation boundary (RRM-004
harness: a `create_deep_agent` graph with a deterministic two-call model, the journaled
coordinator, checkpoint lineage, in-memory run control); the saved provider result lives only
in `mission_control.invocation_settlement` on a disposable PostgreSQL 17 with release 1.7.0
(restricted runtime role). The generic durable-wait double (`tests/fixtures/saved_settlement.py`)
performs one native write per cognition answer turn, holds it until its receipt, and can hold a
review. Every window converges to one logical result: two model calls, one native write, one
lane dispatch, one operation settlement; the histories replay.

* a worker shut down inside the settlement pass after completion -> a fresh worker's retry
  settles the saved result (one `operation.execute`, retried by the scheduler);
* a review wait across a worker restart, with the verdict arriving while no worker runs ->
  the workflow's durable timer, then the next `operation.execute` settles;
* an effect wait whose receipt arrives late -> waits (growing delay), then settles;
* a cancel during the review wait -> `operation.cancel` settles the saved result `cancelled`
  without evaluation, cognition or a second write.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from typing import Any

import asyncpg
import pytest
import pytest_asyncio
from temporalio.client import WorkflowHandle
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from mission_control.adapters.postgres.operations.invocation_settlement import (
    PostgresInvocationSettlementStore,
)
from mission_control.adapters.temporal.operation_activities import (
    OperationExecutionActivities,
    parse_operation_result,
)
from mission_control.adapters.temporal.workflow_sandbox import coordinator_workflow_runner
from mission_control.adapters.temporal.workflows.operation import (
    SAVED_SETTLEMENT_CAN_PATCH,
    SAVED_SETTLEMENT_PATCH,
    OperationWorkflow,
)
from mission_control.domain.execution.contracts import (
    OperationExecutionRequest,
    OperationWorkflowRequest,
)
from mission_control.domain.execution.invocation_settlement import (
    InvocationSettlement,
    SettlementState,
)
from tests.fixtures.checkpoint_recovery import (
    RecoveryHarness,
    recovery_harness,
    stage_recovery_unit,
)
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.fixtures.saved_settlement import DurableEffectDouble
from tests.fixtures.temporal_history import patch_ids
from tests.integration.postgres.runtime_common import common_db  # noqa: F401

pytestmark = [pytest.mark.asyncio, pytest.mark.common_db]
WORKFLOW_QUEUE = "wi04-operation-workflows"
HEARTBEAT_SECONDS = 2
TIMEOUT_SECONDS = 60


@pytest_asyncio.fixture
async def pool(common_db: CommonDatabase) -> AsyncIterator[asyncpg.Pool]:  # noqa: F811
    await common_db.add_tenants(["tenant-1"])
    created = await common_db.pool()
    try:
        yield created
    finally:
        await created.close()


async def _environment() -> WorkflowEnvironment:
    existing = os.environ.get("MISSION_CONTROL_TEST_TEMPORAL_SERVER") or None
    try:
        return await WorkflowEnvironment.start_time_skipping(test_server_existing_path=existing)
    except RuntimeError as error:
        pytest.skip(f"Temporal test server is unavailable: {error}")


class _Stack:
    def __init__(
        self,
        harness: RecoveryHarness,
        environment: WorkflowEnvironment,
        store: PostgresInvocationSettlementStore,
    ) -> None:
        self.harness = harness
        self.environment = environment
        self.store = store

    def workflow_worker(self) -> Worker:
        return Worker(
            self.environment.client,
            task_queue=WORKFLOW_QUEUE,
            workflows=[OperationWorkflow],
            workflow_runner=coordinator_workflow_runner(),
        )

    def activity_worker(self, identity: str) -> Worker:
        """A fresh activity worker over the same durable stores (a restarted process)."""

        activities = OperationExecutionActivities(self.harness.service, worker_identity=identity)
        return Worker(
            self.environment.client,
            task_queue=self.harness.binding.task_queue,
            activities=[activities.execute, activities.cancel],
        )

    async def start(
        self,
        request: OperationExecutionRequest,
        workflow_id: str,
        *,
        waits_per_run: int | None = None,
    ) -> WorkflowHandle[Any, Any]:
        return await self.environment.client.start_workflow(
            OperationWorkflow.run,
            OperationWorkflowRequest(
                semantic_attempt_id=request.identity.semantic_key,
                operation_kind="bound_operation",
                operation=request,
                timeout_seconds=TIMEOUT_SECONDS,
                heartbeat_timeout_seconds=HEARTBEAT_SECONDS,
                settlement_waits_per_run=waits_per_run,
            ),
            id=workflow_id,
            task_queue=WORKFLOW_QUEUE,
        )

    async def record(self, request: OperationExecutionRequest) -> InvocationSettlement | None:
        binding = await self.harness.bindings.get_binding(  # type: ignore[union-attr]
            request.identity.semantic_key, request_scope=request.request_scope
        )
        if binding is None:
            return None
        return await self.store.get(request.request_scope, binding.binding_id)

    async def until(
        self, request: OperationExecutionRequest, state: SettlementState, *, seconds: float = 60
    ) -> InvocationSettlement:
        async with asyncio.timeout(seconds):
            while True:
                record = await self.record(request)
                if record is not None and record.settlement is state:
                    return record
                await asyncio.sleep(0.1)


async def _stack(
    common_db: CommonDatabase,  # noqa: F811
    pool: asyncpg.Pool,
    environment: WorkflowEnvironment,
    double: DurableEffectDouble,
) -> tuple[_Stack, OperationExecutionRequest]:
    scope = common_db.scope("tenant-1")
    # The harness lineage is in memory: no PostgreSQL attempt row carries the unit's fence.
    store = PostgresInvocationSettlementStore(pool, require_unit_generation=False)
    harness = await recovery_harness(request_scope=scope, saved_results=store, settlers=(double,))
    double.attach(harness.model, answer_turns=(2, 4, 6))
    request = await harness.request(stage_recovery_unit(harness.run_id, request_scope=scope))
    return _Stack(harness, environment, store), request


async def _replays(handle: WorkflowHandle[Any, Any]) -> Any:
    history = await handle.fetch_history()
    await Replayer(
        workflows=[OperationWorkflow], workflow_runner=coordinator_workflow_runner()
    ).replay_workflow(history)
    return history


def _scheduled(history: Any) -> list[str]:
    return [
        event.activity_task_scheduled_event_attributes.activity_type.name
        for event in history.events
        if event.HasField("activity_task_scheduled_event_attributes")
    ]


def _timers(history: Any) -> int:
    return sum(1 for event in history.events if event.HasField("timer_started_event_attributes"))


def _one_logical_result(stack: _Stack, double: DurableEffectDouble) -> None:
    harness = stack.harness
    assert len(harness.model.calls) == 2, "no second model turn"
    assert double.writes == ["native-write:1"], "no second native write"
    assert harness.runtime.invocations == 1, "the saved result was never redispatched"
    assert len(harness.journal.settlements) == 1


async def test_worker_lost_in_the_settlement_pass_settles_on_a_fresh_worker(
    common_db: CommonDatabase,  # noqa: F811
    pool: asyncpg.Pool,
) -> None:
    double = DurableEffectDouble(acknowledge_on_write=True)
    environment = await _environment()
    async with environment:
        stack, request = await _stack(common_db, pool, environment, double)
        entered, _release = double.gate_on_pass(1)
        with environment.auto_time_skipping_disabled():
            async with stack.workflow_worker():
                async with stack.activity_worker("wi04-worker-1"):
                    handle = await stack.start(request, "wi04-lost-in-settlement")
                    await asyncio.wait_for(entered.wait(), timeout=60)
                # The worker is gone inside the pass: saved, nothing settled.
                saved = await stack.record(request)
                assert saved is not None and saved.settlement is SettlementState.PENDING
                assert stack.harness.journal.settlements == {}
                async with stack.activity_worker("wi04-worker-2"):
                    result = await asyncio.wait_for(handle.result(), timeout=120)
                    history = await _replays(handle)
    assert result.disposition == "completed"
    assert parse_operation_result(result.result).status == "completed"
    _one_logical_result(stack, double)
    assert _scheduled(history) == ["operation.execute"], "one Activity, retried by the scheduler"
    record = await stack.record(request)
    assert record is not None and record.settled and double.passes == [False, False]
    print(
        "WI-04 EVIDENCE worker lost in settlement:",
        {
            "model_calls": len(stack.harness.model.calls),
            "native_writes": len(double.writes),
            "dispatches": stack.harness.runtime.invocations,
            "passes": double.passes,
            "scheduled": _scheduled(history),
        },
    )


async def test_review_wait_survives_a_worker_restart_and_settles_after_the_verdict(
    common_db: CommonDatabase,  # noqa: F811
    pool: asyncpg.Pool,
) -> None:
    double = DurableEffectDouble(review_required=True, acknowledge_on_write=True)
    environment = await _environment()
    async with environment:
        stack, request = await _stack(common_db, pool, environment, double)
        with environment.auto_time_skipping_disabled():
            async with stack.workflow_worker():
                async with stack.activity_worker("wi04-worker-1"):
                    handle = await stack.start(request, "wi04-review-restart")
                    waiting = await stack.until(request, SettlementState.WAITING)
                    assert waiting.pending_reviews and waiting.next_action == "await_review"
                # No worker runs while the verdict arrives (late acknowledgment of the review).
                double.verdict()
                async with stack.activity_worker("wi04-worker-2"):
                    await environment.sleep(30)  # the workflow's durable timer fires
                    result = await asyncio.wait_for(handle.result(), timeout=120)
                    history = await _replays(handle)
    assert result.disposition == "completed"
    _one_logical_result(stack, double)
    scheduled = _scheduled(history)
    assert scheduled == ["operation.execute", "operation.execute"]
    assert _timers(history) == 1 and SAVED_SETTLEMENT_PATCH in patch_ids(history)
    print(
        "WI-04 EVIDENCE review wait across restart:",
        {"scheduled": scheduled, "timers": _timers(history), "passes": double.passes},
    )


async def test_effect_wait_settles_once_when_the_receipt_arrives_late(
    common_db: CommonDatabase,  # noqa: F811
    pool: asyncpg.Pool,
) -> None:
    double = DurableEffectDouble()
    environment = await _environment()
    async with environment:
        stack, request = await _stack(common_db, pool, environment, double)
        with environment.auto_time_skipping_disabled():
            async with stack.workflow_worker(), stack.activity_worker("wi04-worker-1"):
                handle = await stack.start(request, "wi04-late-receipt")
                await stack.until(request, SettlementState.WAITING)
                await environment.sleep(6)  # one more pass: still no receipt
                async with asyncio.timeout(60):
                    while True:
                        if len(double.passes) >= 2:
                            break
                        await asyncio.sleep(0.1)
                double.acknowledge()
                await environment.sleep(30)
                result = await asyncio.wait_for(handle.result(), timeout=120)
                history = await _replays(handle)
    assert result.disposition == "completed"
    _one_logical_result(stack, double)
    record = await stack.record(request)
    assert record is not None and record.settled and record.waits >= 2
    assert _scheduled(history).count("operation.execute") == len(double.passes)


async def test_cancel_during_the_review_wait_settles_the_saved_result_cancelled(
    common_db: CommonDatabase,  # noqa: F811
    pool: asyncpg.Pool,
) -> None:
    double = DurableEffectDouble(review_required=True, acknowledge_on_write=True)
    environment = await _environment()
    async with environment:
        stack, request = await _stack(common_db, pool, environment, double)
        with environment.auto_time_skipping_disabled():
            async with stack.workflow_worker(), stack.activity_worker("wi04-worker-1"):
                handle = await stack.start(request, "wi04-cancel-review")
                await stack.until(request, SettlementState.WAITING)
                await handle.cancel()
                result = await asyncio.wait_for(handle.result(), timeout=120)
                history = await _replays(handle)
                double.verdict()  # a verdict after the cancel reopens nothing
    assert result.disposition == "cancelled"
    settled = parse_operation_result(result.result)
    assert settled.status == "cancelled" and settled.output_text
    assert settled.usage.amounts["tokens.total"] == 10, "the completed cognition's usage"
    _one_logical_result(stack, double)
    assert double.passes == [False, True], "the saga's pass is fenced"
    record = await stack.record(request)
    assert record is not None and record.settled and record.stop_fence == "cancelled"
    scheduled = _scheduled(history)
    assert scheduled == ["operation.execute", "operation.cancel"]
    print("WI-04 EVIDENCE cancel during review wait:", {"scheduled": scheduled})


async def test_a_long_review_wait_continues_as_new_with_its_wait_and_bounded_history(
    common_db: CommonDatabase,  # noqa: F811
    pool: asyncpg.Pool,
) -> None:
    """Review 4: after `settlement_waits_per_run` waits the workflow continues as new carrying
    the wait (the next run sleeps on it first), so a review wait never grows one history
    without bound; the result still settles once and every run replays."""

    double = DurableEffectDouble(review_required=True, acknowledge_on_write=True)
    environment = await _environment()
    async with environment:
        stack, request = await _stack(common_db, pool, environment, double)
        with environment.auto_time_skipping_disabled():
            async with stack.workflow_worker(), stack.activity_worker("wi04-worker-1"):
                handle = await stack.start(request, "wi04-review-can", waits_per_run=2)
                first_run = (await handle.describe()).run_id
                await stack.until(request, SettlementState.WAITING)
                async with asyncio.timeout(120):
                    while True:
                        if (await handle.describe()).run_id != first_run:
                            break
                        await environment.sleep(30)
                double.verdict()
                await environment.sleep(60)
                result = await asyncio.wait_for(handle.result(), timeout=120)
                first = await stack.environment.client.get_workflow_handle(
                    handle.id, run_id=first_run
                ).fetch_history()
                last = await _replays(handle)
                await Replayer(
                    workflows=[OperationWorkflow], workflow_runner=coordinator_workflow_runner()
                ).replay_workflow(first)
    assert result.disposition == "completed"
    _one_logical_result(stack, double)
    assert any(
        event.HasField("workflow_execution_continued_as_new_event_attributes")
        for event in first.events
    )
    assert SAVED_SETTLEMENT_CAN_PATCH in patch_ids(first)
    assert _scheduled(first).count("operation.execute") == 2 and _timers(first) == 2
    # The continued run starts with the carried wait (a timer before any activity).
    commands = [
        "timer" if event.HasField("timer_started_event_attributes") else "activity"
        for event in last.events
        if event.HasField("timer_started_event_attributes")
        or event.HasField("activity_task_scheduled_event_attributes")
    ]
    assert commands[0] == "timer"
    print(
        "WI-04 EVIDENCE continue-as-new:",
        {
            "first_run_events": len(first.events),
            "last_run_events": len(last.events),
            "passes": len(double.passes),
        },
    )
