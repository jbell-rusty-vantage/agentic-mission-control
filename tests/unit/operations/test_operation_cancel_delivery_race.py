"""Authority-gated refusal is not a failed child while accepted cancellation is in transit."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from temporalio.exceptions import ActivityError, ApplicationError, RetryState

from mission_control.adapters.temporal.workflows import operation as module
from mission_control.application.execution.operations.operation_execution import (
    OperationCancellationPending,
    RunControlOperationAuthority,
    bind_operation_execution_request,
)
from mission_control.domain.policies.contracts import RunPhase
from tests.unit.operations.test_operation_execution import _workflow_request


def failed_activity(kind):
    error = ActivityError(
        "refused",
        scheduled_event_id=1,
        started_event_id=2,
        identity="fixture",
        activity_type="operation.execute",
        activity_id="1",
        retry_state=RetryState.NON_RETRYABLE_FAILURE,
    )
    error.__cause__ = ApplicationError("refused", type=kind, non_retryable=True)
    handle = asyncio.get_running_loop().create_future()
    handle.set_exception(error)
    return handle


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("cancelled", "kind", "patched", "reconcile"),
    [
        (True, "operation_execution_rejected", True, True),
        (True, "operation_execution_rejected", False, False),
        (False, "operation_execution_rejected", True, False),
    ],
)
async def test_finished_activity_failure_cannot_bypass_delivered_cancel(
    monkeypatch,
    cancelled,
    kind,
    patched,
    reconcile,
):
    request = _workflow_request()
    instance = module.OperationWorkflow(request)
    instance._cancel_requested = cancelled
    handle = failed_activity(kind)
    monkeypatch.setattr(module.workflow, "start_activity", lambda *a, **k: handle)
    monkeypatch.setattr(module.workflow, "patched", lambda name: patched)
    monkeypatch.setattr(module.workflow, "wait_condition", AsyncMock())
    with pytest.raises(module._CancellationRequested if reconcile else ActivityError):
        await instance._execute_cancellable(request)


@pytest.mark.asyncio
async def test_accepted_but_undelivered_cancel_waits_durably_then_reconciles(monkeypatch):
    request = _workflow_request()
    instance = module.OperationWorkflow(request)
    handle = failed_activity("operation_cancellation_pending")
    waiting, delivered = asyncio.Event(), asyncio.Event()

    async def wait_condition(predicate):
        if not predicate():
            waiting.set()
            await delivered.wait()
            assert predicate()

    monkeypatch.setattr(module.workflow, "start_activity", lambda *a, **k: handle)
    monkeypatch.setattr(module.workflow, "patched", lambda name: True)
    monkeypatch.setattr(module.workflow, "wait_condition", wait_condition)
    task = asyncio.create_task(instance._execute_cancellable(request))
    try:
        async with asyncio.timeout(2):
            await waiting.wait()
        assert not task.done()
        instance.request_cancel()
        delivered.set()
        with pytest.raises(module._CancellationRequested):
            await task
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_only_cancelling_bound_authority_emits_the_pending_delivery_signal():
    request = _workflow_request().operation
    binding = bind_operation_execution_request(request)
    run = SimpleNamespace(version=request.run_control_revision + 1, phase=RunPhase.CANCELLING)
    control = SimpleNamespace(get_run=AsyncMock(return_value=run))
    authority = RunControlOperationAuthority(control, None)
    with pytest.raises(OperationCancellationPending):
        await authority.verify_continuation(request, binding)
    for phase in (RunPhase.TERMINAL, RunPhase.PENDING, RunPhase.PAUSED):
        run.phase = phase
        with pytest.raises(ValueError) as rejected:
            await authority.verify_continuation(request, binding)
        assert not isinstance(rejected.value, OperationCancellationPending)
    run.phase = RunPhase.CANCELLING
    with pytest.raises(ValueError, match="bound operation attempt") as rejected:
        await authority.verify_continuation(
            request, binding.model_copy(update={"run_id": "foreign"})
        )
    assert not isinstance(rejected.value, OperationCancellationPending)
