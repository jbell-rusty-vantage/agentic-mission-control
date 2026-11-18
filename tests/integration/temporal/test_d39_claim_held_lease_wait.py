"""W1 D39 on Temporal (time-skipping server): an `operation.execute` refused behind a live claim
lease retries after the holder's deadline and, when its attempts still end refused, the
operation workflow waits durably for that deadline and continues the unit in a new round.

The `operation.execute` stand-in refuses exactly as the real activity does behind a lost
worker's lease (`claim_held_failure`: `operation_execution_in_progress`, the holder's deadline
in the details and as `next_retry_delay`), for all three attempts of the first round, then
completes. Before the fix the unit failed after the first round (session 12, run eb311192).
The rounds are bounded, a refusal naming no deadline is not waited on, and a cancel during the
wait reconciles through `operation.cancel` without another round (OVE-238 G4: these replace the
`temporalio.workflow`-patching tests of tests/unit/operations/test_d39_claim_held_retry.py).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ActivityError, ApplicationError
from temporalio.worker import Replayer, Worker

from mission_control.adapters.temporal.operation_activities import claim_held_failure
from mission_control.adapters.temporal.workflow_sandbox import coordinator_workflow_runner
from mission_control.adapters.temporal.workflows.operation import (
    CLAIM_HELD_WAIT_PATCH,
    MAX_CLAIM_HELD_ROUNDS,
    OperationWorkflow,
)
from mission_control.application.execution.operations.operation_execution import (
    OperationClaimHeld,
)
from tests.support.operations import _workflow_request
from tests.support.temporal import RecordingOperationCancel, patch_ids, start_workflow_env

WORKFLOW_QUEUE = "d39-operation-workflows"
HOLDER_LEASE = timedelta(seconds=240)


@pytest.mark.asyncio
async def test_a_refused_round_waits_for_the_holder_lease_then_continues_the_unit() -> None:
    environment = await start_workflow_env()
    calls: list[tuple[int, datetime]] = []
    deadline: list[datetime] = []

    @activity.defn(name="operation.execute")
    async def execute(payload: dict[str, Any]) -> dict[str, Any]:
        # The test server's skipped time; the activity's wall clock does not skip.
        now = await environment.get_current_time()
        calls.append((activity.info().attempt, now))
        if len(calls) <= 3:
            if not deadline:
                deadline.append(now + HOLDER_LEASE)
            raise claim_held_failure(OperationClaimHeld("held", lease_expires_at=deadline[0]), now)
        return {"status": "completed"}

    request = _workflow_request()
    async with environment:
        async with (
            Worker(
                environment.client,
                task_queue=WORKFLOW_QUEUE,
                workflows=[OperationWorkflow],
                workflow_runner=coordinator_workflow_runner(),
            ),
            Worker(
                environment.client,
                task_queue=request.activity_task_queue,
                activities=[execute],
            ),
        ):
            handle = await environment.client.start_workflow(
                OperationWorkflow.run,
                request,
                id="d39-claim-held-lease-wait",
                task_queue=WORKFLOW_QUEUE,
            )
            result = await handle.result()
            history = await handle.fetch_history()

    assert result.disposition == "completed"
    # Round 1: attempt 1 refused; attempts 2 and 3 run after the holder's deadline (still
    # refused by the stand-in); round 2 starts a fresh activity whose attempt 1 completes.
    assert [attempt for attempt, _ in calls] == [1, 2, 3, 1]
    assert calls[1][1] >= deadline[0], "the retry is scheduled after the holder's lease"
    assert CLAIM_HELD_WAIT_PATCH in patch_ids(history)
    await Replayer(
        workflows=[OperationWorkflow], workflow_runner=coordinator_workflow_runner()
    ).replay_workflow(history)


class _AlwaysHeld:
    """`operation.execute` refused behind a live holder on every attempt; `lease` is the
    holder's remaining lease, or None when the refusal names no deadline."""

    def __init__(self, environment: Any, lease: timedelta | None) -> None:
        self.environment = environment
        self.lease = lease
        self.calls: list[int] = []

    @activity.defn(name="operation.execute")
    async def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = await self.environment.get_current_time()
        self.calls.append(activity.info().attempt)
        deadline = None if self.lease is None else now + self.lease
        raise claim_held_failure(OperationClaimHeld("held", lease_expires_at=deadline), now)


def _workers(environment: Any, *activities: Any) -> tuple[Worker, Worker]:
    request = _workflow_request()
    return (
        Worker(
            environment.client,
            task_queue=WORKFLOW_QUEUE,
            workflows=[OperationWorkflow],
            workflow_runner=coordinator_workflow_runner(),
        ),
        Worker(
            environment.client, task_queue=request.activity_task_queue, activities=list(activities)
        ),
    )


def _timers(history: Any) -> int:
    return sum(1 for event in history.events if event.HasField("timer_started_event_attributes"))


@pytest.mark.asyncio
async def test_claim_held_rounds_are_bounded_then_the_unit_fails() -> None:
    environment = await start_workflow_env()
    async with environment:
        refusing = _AlwaysHeld(environment, timedelta(seconds=30))
        workflow_worker, activity_worker = _workers(environment, refusing.execute)
        async with workflow_worker, activity_worker:
            handle = await environment.client.start_workflow(
                OperationWorkflow.run,
                _workflow_request(),
                id="d39-claim-held-bounded",
                task_queue=WORKFLOW_QUEUE,
            )
            with pytest.raises(WorkflowFailureError) as failed:
                await handle.result()
            history = await handle.fetch_history()

    # MAX_CLAIM_HELD_ROUNDS waits, then one last round; each round spends three attempts.
    assert refusing.calls == [1, 2, 3] * (MAX_CLAIM_HELD_ROUNDS + 1)
    assert _timers(history) == MAX_CLAIM_HELD_ROUNDS
    cause = failed.value.cause
    assert isinstance(cause, ActivityError) and isinstance(cause.cause, ApplicationError)
    assert cause.cause.type == "operation_execution_in_progress"
    await Replayer(
        workflows=[OperationWorkflow], workflow_runner=coordinator_workflow_runner()
    ).replay_workflow(history)


@pytest.mark.asyncio
async def test_a_refusal_naming_no_holder_deadline_fails_after_one_round() -> None:
    environment = await start_workflow_env()
    async with environment:
        refusing = _AlwaysHeld(environment, None)
        workflow_worker, activity_worker = _workers(environment, refusing.execute)
        async with workflow_worker, activity_worker:
            handle = await environment.client.start_workflow(
                OperationWorkflow.run,
                _workflow_request(),
                id="d39-claim-held-no-deadline",
                task_queue=WORKFLOW_QUEUE,
            )
            with pytest.raises(WorkflowFailureError):
                await handle.result()
            history = await handle.fetch_history()

    assert refusing.calls == [1, 2, 3], "nothing to wait for: no second round"
    assert _timers(history) == 0
    assert CLAIM_HELD_WAIT_PATCH not in patch_ids(history)


@pytest.mark.asyncio
async def test_a_cancel_during_the_lease_wait_reconciles_without_another_round() -> None:
    environment = await start_workflow_env()
    async with environment:
        refusing = _AlwaysHeld(environment, HOLDER_LEASE)
        cancel = RecordingOperationCancel()
        workflow_worker, activity_worker = _workers(environment, refusing.execute, cancel.cancel)
        async with workflow_worker, activity_worker:
            handle = await environment.client.start_workflow(
                OperationWorkflow.run,
                _workflow_request(),
                id="d39-claim-held-cancel",
                task_queue=WORKFLOW_QUEUE,
            )
            # Skip server time until the first round has ended and its lease wait started.
            for _ in range(60):
                if _timers(await handle.fetch_history()):
                    break
                await environment.sleep(timedelta(seconds=60))
            assert _timers(await handle.fetch_history()) == 1
            await handle.signal(OperationWorkflow.request_cancel)
            result = await handle.result()
            history = await handle.fetch_history()

    assert result.disposition == "cancelled"
    assert refusing.calls == [1, 2, 3], "a requested cancel never starts another round"
    assert len(cancel.calls) == 1
    assert CLAIM_HELD_WAIT_PATCH in patch_ids(history)
    await Replayer(
        workflows=[OperationWorkflow], workflow_runner=coordinator_workflow_runner()
    ).replay_workflow(history)
