"""An accepted cancel that has not reached the operation yet is waited for durably (OVE-238 G4).

Run Control fences cognition as soon as it accepts a cancel, before its outbox necessarily
delivers the cancel to the operation workflow. `operation.execute` then ends
`operation_cancellation_pending`. Under `mc-operation-cancel-delivery-race-v1` the real
`OperationWorkflow` (time-skipping server) keeps the child open for that delivery, however long
it takes, and reconciles through `operation.cancel` once it lands; an authority refusal racing
a delivered cancel is reconciled the same way; a refusal with no cancel still fails the unit.

`operation.execute` and `operation.cancel` are stand-ins at the activity boundary that answer
exactly as the operation boundary does. Replaces the `temporalio.workflow`-patching workflow
tests of tests/unit/operations/test_operation_cancel_delivery_race.py.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import pytest
from temporalio import activity
from temporalio.client import WorkflowFailureError, WorkflowHandle
from temporalio.exceptions import ActivityError, ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from mission_control.adapters.temporal.operation_activities import parse_operation_result
from mission_control.adapters.temporal.workflow_sandbox import coordinator_workflow_runner
from mission_control.adapters.temporal.workflows.operation import (
    CANCEL_DELIVERY_RACE_PATCH,
    OperationWorkflow,
)
from tests.support.operations import _workflow_request
from tests.support.temporal import RecordingOperationCancel, patch_ids

WORKFLOW_QUEUE = "cancel-delivery-race-workflows"


class _Execute:
    """`operation.execute` refused by run control with a typed, non-retryable failure."""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.calls = 0

    @activity.defn(name="operation.execute")
    async def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        raise ApplicationError("refused by run control", type=self.kind, non_retryable=True)


def _workflow_worker(env: WorkflowEnvironment, **options: Any) -> Worker:
    return Worker(
        env.client,
        task_queue=WORKFLOW_QUEUE,
        workflows=[OperationWorkflow],
        workflow_runner=coordinator_workflow_runner(),
        **options,
    )


def _activity_worker(
    env: WorkflowEnvironment, execute: _Execute, cancel: RecordingOperationCancel
) -> Worker:
    return Worker(
        env.client,
        task_queue=_workflow_request().activity_task_queue,
        activities=[execute.execute, cancel.cancel],
    )


def _workers(
    env: WorkflowEnvironment, execute: _Execute, cancel: RecordingOperationCancel
) -> tuple[Worker, Worker]:
    return _workflow_worker(env), _activity_worker(env, execute, cancel)


async def _start(env: WorkflowEnvironment, workflow_id: str) -> WorkflowHandle[Any, Any]:
    return await env.client.start_workflow(
        OperationWorkflow.run, _workflow_request(), id=workflow_id, task_queue=WORKFLOW_QUEUE
    )


async def _replays(handle: WorkflowHandle[Any, Any]) -> Any:
    history = await handle.fetch_history()
    await Replayer(
        workflows=[OperationWorkflow], workflow_runner=coordinator_workflow_runner()
    ).replay_workflow(history)
    return history


async def _has(handle: WorkflowHandle[Any, Any], attribute: str) -> bool:
    history = await handle.fetch_history()
    return any(event.HasField(attribute) for event in history.events)


async def _until_has(handle: WorkflowHandle[Any, Any], attribute: str) -> None:
    for _ in range(600):
        if await _has(handle, attribute):
            return
        await asyncio.sleep(0.1)
    raise AssertionError(f"no {attribute} in time")


@pytest.mark.asyncio
async def test_accepted_but_undelivered_cancel_waits_durably_then_reconciles(
    workflow_env: WorkflowEnvironment,
) -> None:
    execute = _Execute("operation_cancellation_pending")
    cancel = RecordingOperationCancel()
    workflow_worker, activity_worker = _workers(workflow_env, execute, cancel)
    async with workflow_worker, activity_worker:
        handle = await _start(workflow_env, "cancel-delivery-pending")
        await _until_has(handle, "activity_task_failed_event_attributes")
        # A day passes on the server: the child neither fails nor gives up waiting.
        await workflow_env.sleep(timedelta(days=1))
        description = await handle.describe()
        assert description.status is not None and description.status.name == "RUNNING"
        assert cancel.calls == []
        await handle.signal(OperationWorkflow.request_cancel)
        result = await asyncio.wait_for(handle.result(), timeout=60)
        history = await _replays(handle)

    assert result.disposition == "cancelled"
    assert parse_operation_result(result.result).status == "cancelled"
    assert execute.calls == 1, "cognition was never dispatched again"
    assert len(cancel.calls) == 1, "the unit settled once through operation.cancel"
    assert CANCEL_DELIVERY_RACE_PATCH in patch_ids(history)


@pytest.mark.asyncio
async def test_a_refusal_racing_a_delivered_cancel_reconciles_instead_of_failing(
    workflow_env: WorkflowEnvironment,
) -> None:
    """The refusal and the delivered cancel reach the workflow in the same task: no workflow
    worker runs while the activity fails and the cancel signal lands."""

    execute = _Execute("operation_execution_rejected")
    cancel = RecordingOperationCancel()
    activity_worker = _activity_worker(workflow_env, execute, cancel)
    # No sticky cache: the next workflow task goes to whichever workflow worker polls next.
    async with _workflow_worker(workflow_env, max_cached_workflows=0):
        handle = await _start(workflow_env, "cancel-delivery-rejected-cancelled")
        await _until_has(handle, "activity_task_scheduled_event_attributes")
    async with activity_worker:
        await _until_has(handle, "activity_task_failed_event_attributes")
        await handle.signal(OperationWorkflow.request_cancel)
        async with _workflow_worker(workflow_env):
            result = await asyncio.wait_for(handle.result(), timeout=60)
            history = await _replays(handle)

    assert result.disposition == "cancelled"
    assert execute.calls == 1
    assert len(cancel.calls) == 1, "operation.cancel reconciled the refused unit"
    # The SDK applies the signal before the activity resolution in one activation, so the
    # workflow takes the cancel-in-flight branch; either branch reconciles the unit.
    assert "operation.cancel" in [
        event.activity_task_scheduled_event_attributes.activity_type.name
        for event in history.events
        if event.HasField("activity_task_scheduled_event_attributes")
    ]


@pytest.mark.asyncio
async def test_a_refusal_without_a_cancel_still_fails_the_unit(
    workflow_env: WorkflowEnvironment,
) -> None:
    execute = _Execute("operation_execution_rejected")
    cancel = RecordingOperationCancel()
    workflow_worker, activity_worker = _workers(workflow_env, execute, cancel)
    async with workflow_worker, activity_worker:
        handle = await _start(workflow_env, "cancel-delivery-rejected")
        with pytest.raises(WorkflowFailureError) as failed:
            await asyncio.wait_for(handle.result(), timeout=60)
        history = await _replays(handle)

    cause = failed.value.cause
    assert isinstance(cause, ActivityError)
    assert isinstance(cause.cause, ApplicationError)
    assert cause.cause.type == "operation_execution_rejected"
    assert cancel.calls == []
    assert CANCEL_DELIVERY_RACE_PATCH not in patch_ids(history)
