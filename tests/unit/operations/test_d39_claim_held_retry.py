"""W1 D39 (OVE-169): a worker lost mid `operation.execute` is recoverable.

Live (session 12, run eb311192): the worker was killed 15 s into the verifier's
`operation.execute`. Its claim lease (the attempt's start-to-close, 300 s) stayed live; the
activity retry policy (3 attempts, about 3 s of backoff) spent attempts 2 and 3 within
seconds, each refused `operation_execution_in_progress`, and the unit, family and run failed.

The fix keeps every guarantee of the claim lease (no two attempts work concurrently, a takeover
advances the fence) and only moves *when* the refused attempt retries:

- the refusal names the live holder's lease deadline (`OperationClaimHeld`);
- the activity schedules its retry after that deadline (`next_retry_delay`, the pattern
  `session_owned_elsewhere` uses);
- if the attempt budget still ends on a refusal, the operation workflow waits durably until the
  named deadline and starts one more bounded round (patched for replay).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from temporalio.exceptions import ActivityError, ApplicationError, RetryState

from mission_control.adapters.temporal.operation_activities import (
    CLAIM_HELD_RETRY_MARGIN,
    claim_held_failure,
)
from mission_control.adapters.temporal.workflows import operation as module
from mission_control.application.execution.operations.operation_execution import (
    OperationClaimHeld,
)
from tests.unit.operations.test_operation_execution import _workflow_request

NOW = datetime(2026, 11, 2, 20, 0, tzinfo=UTC)


def test_a_refusal_behind_a_live_lease_retries_after_the_holder_deadline() -> None:
    deadline = NOW + timedelta(seconds=255)
    failure = claim_held_failure(OperationClaimHeld("held", lease_expires_at=deadline), NOW)
    assert failure.type == "operation_execution_in_progress"
    assert not failure.non_retryable
    assert failure.next_retry_delay == timedelta(seconds=255) + CLAIM_HELD_RETRY_MARGIN
    assert failure.details == ({"holder_lease_expires_at": deadline.isoformat()},)


def test_an_expired_or_unknown_holder_deadline_keeps_a_short_retry() -> None:
    expired = claim_held_failure(
        OperationClaimHeld("held", lease_expires_at=NOW - timedelta(seconds=5)), NOW
    )
    assert expired.next_retry_delay == timedelta(seconds=1)
    unknown = claim_held_failure(OperationClaimHeld("held", lease_expires_at=None), NOW)
    assert unknown.next_retry_delay is None and unknown.details == ()


def _held_failure(deadline: datetime | None) -> ActivityError:
    error = ActivityError(
        "refused",
        scheduled_event_id=1,
        started_event_id=2,
        identity="fixture",
        activity_type="operation.execute",
        activity_id="1",
        retry_state=RetryState.MAXIMUM_ATTEMPTS_REACHED,
    )
    details = () if deadline is None else ({"holder_lease_expires_at": deadline.isoformat()},)
    error.__cause__ = ApplicationError("held", *details, type="operation_execution_in_progress")
    return error


class _Handles:
    """`workflow.start_activity` stand-in: each round answers the next scripted outcome."""

    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = outcomes
        self.started = 0

    def __call__(self, *args: Any, **kwargs: Any) -> asyncio.Future[Any]:
        outcome = self.outcomes[self.started]
        self.started += 1
        handle: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        if isinstance(outcome, BaseException):
            handle.set_exception(outcome)
        else:
            handle.set_result(outcome)
        return handle


def _workflow_clock(monkeypatch: pytest.MonkeyPatch, *, patched: bool) -> list[float]:
    waits: list[float] = []
    clock = [NOW]

    # `workflow.wait_condition`'s own signature.
    async def wait_condition(predicate: Any, timeout: timedelta | None = None) -> None:  # noqa: ASYNC109
        if predicate():
            return
        assert timeout is not None, "the claim-held wait is a durable timer"
        waits.append(timeout.total_seconds())
        clock[0] += timeout
        raise TimeoutError

    monkeypatch.setattr(module.workflow, "wait_condition", wait_condition)
    monkeypatch.setattr(module.workflow, "now", lambda: clock[0])
    monkeypatch.setattr(module.workflow, "patched", lambda name: patched)
    return waits


@pytest.mark.asyncio
async def test_a_round_that_ends_refused_waits_for_the_lease_then_continues_the_unit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _workflow_request()
    instance = module.OperationWorkflow(request)
    deadline = NOW + timedelta(seconds=240)
    handles = _Handles([_held_failure(deadline), {"status": "completed"}])
    monkeypatch.setattr(module.workflow, "start_activity", handles)
    waits = _workflow_clock(monkeypatch, patched=True)

    assert await instance._execute_cancellable(request) == {"status": "completed"}
    assert handles.started == 2
    assert waits == [240 + CLAIM_HELD_RETRY_MARGIN.total_seconds()]


@pytest.mark.asyncio
async def test_claim_held_rounds_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    request = _workflow_request()
    instance = module.OperationWorkflow(request)
    rounds = module.MAX_CLAIM_HELD_ROUNDS + 1
    handles = _Handles([_held_failure(NOW + timedelta(seconds=30)) for _ in range(rounds)])
    monkeypatch.setattr(module.workflow, "start_activity", handles)
    _workflow_clock(monkeypatch, patched=True)

    with pytest.raises(ActivityError):
        await instance._execute_cancellable(request)
    assert handles.started == rounds


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("patched", "deadline", "cancelled"),
    [
        (False, NOW + timedelta(seconds=30), False),  # a recorded history replays as before
        (True, None, False),  # no holder deadline named: nothing to wait for
        (True, NOW + timedelta(seconds=30), True),  # a requested cancel is never re-run
    ],
)
async def test_the_old_failure_stands_without_patch_deadline_or_with_a_cancel(
    monkeypatch: pytest.MonkeyPatch,
    patched: bool,
    deadline: datetime | None,
    cancelled: bool,
) -> None:
    request = _workflow_request()
    instance = module.OperationWorkflow(request)
    instance._cancel_requested = cancelled
    handles = _Handles([_held_failure(deadline), {"status": "completed"}])
    monkeypatch.setattr(module.workflow, "start_activity", handles)
    _workflow_clock(monkeypatch, patched=patched)

    with pytest.raises((ActivityError, module._CancellationRequested)):
        await instance._execute_cancellable(request)
    assert handles.started == 1
