"""Authority-gated refusal is not a failed child while accepted cancellation is in transit.

The workflow behaviour runs on Temporal in
tests/integration/temporal/test_operation_cancel_delivery_race.py; this module keeps the
authority's pending-delivery signal and the one pre-patch case."""

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
from tests.support.operations import _workflow_request


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


# TODO(OVE-238): the pre-patch branch has no recorded history to replay (a history from before
# `mc-operation-cancel-delivery-race-v1` with a refused, cancel-requested round); until one is
# captured this patched-workflow case is its only cover. The patched cases run on Temporal in
# tests/integration/temporal/test_operation_cancel_delivery_race.py.
@pytest.mark.asyncio
async def test_pre_patch_history_keeps_failing_a_refused_round_with_a_cancel(monkeypatch):
    request = _workflow_request()
    instance = module.OperationWorkflow(request)
    instance._cancel_requested = True
    handle = failed_activity("operation_execution_rejected")
    monkeypatch.setattr(module.workflow, "start_activity", lambda *a, **k: handle)
    monkeypatch.setattr(module.workflow, "patched", lambda name: False)
    monkeypatch.setattr(module.workflow, "wait_condition", AsyncMock())
    with pytest.raises(ActivityError):
        await instance._execute_cancellable(request)


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
