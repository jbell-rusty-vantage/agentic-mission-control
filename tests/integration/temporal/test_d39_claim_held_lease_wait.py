"""W1 D39 on Temporal (time-skipping server): an `operation.execute` refused behind a live claim
lease retries after the holder's deadline and, when its attempts still end refused, the
operation workflow waits durably for that deadline and continues the unit in a new round.

The `operation.execute` stand-in refuses exactly as the real activity does behind a lost
worker's lease (`claim_held_failure`: `operation_execution_in_progress`, the holder's deadline
in the details and as `next_retry_delay`), for all three attempts of the first round, then
completes. Before the fix the unit failed after the first round (session 12, run eb311192).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from mission_control.adapters.temporal.operation_activities import claim_held_failure
from mission_control.adapters.temporal.workflow_sandbox import coordinator_workflow_runner
from mission_control.adapters.temporal.workflows.operation import (
    CLAIM_HELD_WAIT_PATCH,
    OperationWorkflow,
)
from mission_control.application.execution.operations.operation_execution import (
    OperationClaimHeld,
)
from tests.fixtures.temporal_history import patch_ids
from tests.unit.operations.test_operation_execution import _workflow_request

WORKFLOW_QUEUE = "d39-operation-workflows"
HOLDER_LEASE = timedelta(seconds=240)


@pytest.mark.asyncio
async def test_a_refused_round_waits_for_the_holder_lease_then_continues_the_unit() -> None:
    try:
        environment = await WorkflowEnvironment.start_time_skipping()
    except RuntimeError as error:
        pytest.skip(f"Temporal test server is unavailable: {error}")
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
