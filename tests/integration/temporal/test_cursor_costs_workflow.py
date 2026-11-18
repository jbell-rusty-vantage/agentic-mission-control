"""Cursor delayed billing on Temporal (time-skipping server; OVE-238 G4).

* `CursorCostsWorkflow` (`mc.cursor_costs.v1`) reads the cost at most three times, after two
  bounded durable timers (300 s and 900 s), and returns the last read: an unknown cost stays a
  pending liability; a settled read ends the reads at once.
* A settled `cursor_local` unit whose lane declares `external_cost_settlement` and leaves a
  pending estimated amount starts that workflow as an abandoned child on the operation
  workflow's own queue, while its reads run on the lane's activity queue
  (`cm01-cursor-pending-costs-v1`).

`cursor.costs.reconcile`, `lane.turn` and `lane.cleanup` are stand-ins at the activity
boundary. Replaces the `temporalio.workflow`-patching workflow tests of
tests/unit/runtime/test_cursor_costs.py and tests/unit/runtime/test_worker_boundary_joins.py.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from itertools import pairwise
from typing import Any

import pytest
from temporalio import activity
from temporalio.api.enums.v1 import ParentClosePolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from mission_control.adapters.temporal.activities.cursor_costs import (
    COST_ACTIVITY,
    COST_WORKFLOW,
    CostRead,
)
from mission_control.adapters.temporal.workflow_sandbox import coordinator_workflow_runner
from mission_control.adapters.temporal.workflows.cursor_costs import CursorCostsWorkflow
from mission_control.adapters.temporal.workflows.operation import (
    CURSOR_COSTS_PATCH,
    OperationWorkflow,
)
from mission_control.domain.execution.contracts import OperationWorkflowRequest
from mission_control.domain.execution.cursor_costs import CostReadResult, CostRequest
from mission_control.domain.execution.lane_turns import LaneTurnResult
from tests.support.lanes import cursor_operation
from tests.support.temporal import patch_ids

WORKFLOW_QUEUE = "cursor-costs-workflows"
LANE_QUEUE = "cursor-costs-lane"
PENDING = {"currency.estimated_micros": 100}


class _CostReads:
    """`cursor.costs.reconcile`: answers `states` in turn, recording the read number, the
    queue it ran on and the server time."""

    def __init__(self, environment: WorkflowEnvironment, states: list[str]) -> None:
        self.environment = environment
        self.states = states
        self.reads: list[tuple[int, str, datetime]] = []

    @activity.defn(name=COST_ACTIVITY)
    async def reconcile(self, read: CostRead) -> CostReadResult:
        now = await self.environment.get_current_time()
        self.reads.append((read.read_no, activity.info().task_queue, now))
        return CostReadResult(
            state=self.states[read.read_no],  # type: ignore[arg-type]
            pending_micros=100,
            recorded_at=now.isoformat(),
        )


@pytest.mark.asyncio
async def test_an_unknown_cost_is_read_after_two_bounded_timers_and_stays_pending(
    workflow_env: WorkflowEnvironment,
) -> None:
    reads = _CostReads(workflow_env, ["unknown", "unknown", "unknown"])
    request = CostRequest(request_scope="scope", binding_id="binding", activity_task_queue="lane")
    async with (
        Worker(
            workflow_env.client,
            task_queue=WORKFLOW_QUEUE,
            workflows=[CursorCostsWorkflow],
            workflow_runner=coordinator_workflow_runner(),
        ),
        Worker(workflow_env.client, task_queue="lane", activities=[reads.reconcile]),
    ):
        handle = await workflow_env.client.start_workflow(
            CursorCostsWorkflow.run, request, id=request.workflow_id, task_queue=WORKFLOW_QUEUE
        )
        result = await asyncio.wait_for(handle.result(), timeout=60)
        history = await handle.fetch_history()

    assert result.state == "unknown" and result.pending_micros == 100
    assert [read_no for read_no, _, _ in reads.reads] == [0, 1, 2]
    times = [at for _, _, at in reads.reads]
    gaps = [(later - earlier).total_seconds() for earlier, later in pairwise(times)]
    assert [round(gap) for gap in gaps] == [300, 900]
    timers = [
        event.timer_started_event_attributes.start_to_fire_timeout.ToSeconds()
        for event in history.events
        if event.HasField("timer_started_event_attributes")
    ]
    assert timers == [300, 900]
    await Replayer(
        workflows=[CursorCostsWorkflow], workflow_runner=coordinator_workflow_runner()
    ).replay_workflow(history)


@pytest.mark.asyncio
async def test_a_settled_read_ends_the_reads(workflow_env: WorkflowEnvironment) -> None:
    reads = _CostReads(workflow_env, ["settled"])
    request = CostRequest(request_scope="scope", binding_id="settled", activity_task_queue="lane")
    async with (
        Worker(
            workflow_env.client,
            task_queue=WORKFLOW_QUEUE,
            workflows=[CursorCostsWorkflow],
            workflow_runner=coordinator_workflow_runner(),
        ),
        Worker(workflow_env.client, task_queue="lane", activities=[reads.reconcile]),
    ):
        result = await workflow_env.client.execute_workflow(
            CursorCostsWorkflow.run, request, id=request.workflow_id, task_queue=WORKFLOW_QUEUE
        )

    assert result.state == "settled"
    assert len(reads.reads) == 1


class _SettledLane:
    """`lane.turn` settling the unit at once with a pending estimated cost, and `lane.cleanup`."""

    @activity.defn(name="lane.turn")
    async def turn(self, payload: dict[str, Any]) -> dict[str, Any]:
        return LaneTurnResult(
            done=True,
            segment_no=1,
            operation_result={
                "status": "completed",
                "binding_id": "bound",
                "usage": {"pending_external_amounts": PENDING},
            },
        ).model_dump(mode="json")

    @activity.defn(name="lane.cleanup")
    async def cleanup(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"released": True}


@pytest.mark.asyncio
async def test_a_pending_cursor_cost_starts_an_abandoned_child_on_the_workflow_queue(
    workflow_env: WorkflowEnvironment,
) -> None:
    operation = cursor_operation()
    assert operation.lane_dispatch is not None
    assert operation.lane_dispatch.declares("external_cost_settlement")
    request = OperationWorkflowRequest.model_validate(
        {
            "semantic_attempt_id": operation.identity.semantic_key,
            "operation_kind": "bound_operation",
            "operation": operation,
            "segments": {
                "max_frames": 50,
                "max_duration_s": 30,
                "start_to_close_s": 60,
                "heartbeat_timeout_s": 10,
                "status_poll_limit": 2,
                "status_poll_interval_s": 1,
                "busy_wait_s": 30,
            },
        }
    )
    lane = _SettledLane()
    reads = _CostReads(workflow_env, ["settled"])
    cost = CostRequest(
        request_scope=operation.request_scope,
        binding_id="bound",
        activity_task_queue=request.activity_task_queue,
    )
    async with (
        Worker(
            workflow_env.client,
            task_queue=WORKFLOW_QUEUE,
            workflows=[OperationWorkflow, CursorCostsWorkflow],
            workflow_runner=coordinator_workflow_runner(),
        ),
        Worker(
            workflow_env.client,
            task_queue=request.activity_task_queue,
            activities=[lane.turn, lane.cleanup, reads.reconcile],
        ),
    ):
        handle = await workflow_env.client.start_workflow(
            OperationWorkflow.run, request, id="cursor-costs-operation", task_queue=WORKFLOW_QUEUE
        )
        result = await asyncio.wait_for(handle.result(), timeout=60)
        child = workflow_env.client.get_workflow_handle(cost.workflow_id)
        settled = await asyncio.wait_for(child.result(), timeout=60)
        description = await child.describe()
        history = await handle.fetch_history()

    # The operation result is the lane's settlement, unchanged.
    assert result.disposition == "completed"
    usage = result.result["usage"]
    assert isinstance(usage, dict) and usage["pending_external_amounts"] == PENDING
    # The child runs on the operation workflow's queue, its reads on the lane queue.
    assert description.task_queue == WORKFLOW_QUEUE
    assert settled["state"] == "settled"
    assert [(read_no, queue) for read_no, queue, _ in reads.reads] == [
        (0, request.activity_task_queue)
    ]
    (initiated,) = [
        event.start_child_workflow_execution_initiated_event_attributes
        for event in history.events
        if event.HasField("start_child_workflow_execution_initiated_event_attributes")
    ]
    assert initiated.workflow_type.name == COST_WORKFLOW
    assert initiated.task_queue.name == WORKFLOW_QUEUE
    assert initiated.parent_close_policy == ParentClosePolicy.PARENT_CLOSE_POLICY_ABANDON
    assert CURSOR_COSTS_PATCH in patch_ids(history)
    await Replayer(
        workflows=[OperationWorkflow, CursorCostsWorkflow],
        workflow_runner=coordinator_workflow_runner(),
    ).replay_workflow(history)
