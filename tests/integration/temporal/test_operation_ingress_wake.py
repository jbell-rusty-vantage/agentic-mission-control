"""MO-75 `OperationWorkflow.ingress_wake` on the time-skipping server (OVE-238 G4).

The real `OperationWorkflow` runs a `cursor_local` segment loop over the real lane activities
(`LaneTurnService` over a governed in-memory boundary and a scripted Session Lane). An ingress
hint is evidence only:

* during an active turn (`mo75-active-ingress-status-v1`) hints present at one boundary
  coalesce into one `lane.status` read, the reads are bounded per segment, and the original
  `lane.turn` handle alone settles the unit (nothing is re-sent);
* a hint that lands while a segment runs (`mo75-session-nudge-snapshot-v1`) is not lost: the
  `in_doubt` park it would otherwise wait in wakes at once.

Replaces tests/unit/runtime/test_run2_ingress_wake.py, which drove `object.__new__
(OperationWorkflow)` with a patched `temporalio.workflow`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from temporalio.client import WorkflowHandle
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from mission_control.adapters.temporal.operation_activities import (
    OperationExecutionActivities,
    parse_operation_result,
)
from mission_control.adapters.temporal.registration.activities import agent_cognitive_activities
from mission_control.adapters.temporal.workflow_sandbox import coordinator_workflow_runner
from mission_control.adapters.temporal.workflows.operation import (
    INGRESS_SNAPSHOT_PATCH,
    INGRESS_STATUS_PATCH,
    MAX_INGRESS_PROBES_PER_SEGMENT,
    OperationWorkflow,
)
from mission_control.domain.execution.contracts import OperationWorkflowRequest
from mission_control.domain.execution.lanes import LaneSegmentBounds
from tests.fixtures.lane_turns import (
    LANE_QUEUE,
    LaneStack,
    ScriptedSessionLane,
    cursor_operation,
    lane_stack,
    scripted_frames,
)
from tests.support.temporal import patch_ids

WORKFLOW_QUEUE = "mo75-ingress-operation-workflows"
# One long segment: the held turn stays in flight while the hints arrive.
BOUNDS = LaneSegmentBounds(
    max_frames=50,
    max_duration_s=30,
    start_to_close_s=60,
    heartbeat_timeout_s=10,
    status_poll_limit=2,
    status_poll_interval_s=1,
    busy_wait_s=30,
)


class _GatedStatusLane(ScriptedSessionLane):
    """Holds the turn after its first frame; each `status` read waits on `gate`."""

    def __init__(self) -> None:
        super().__init__(frames=scripted_frames(), hold_after=1)
        self.gate = asyncio.Event()
        self.gate.set()
        self.status_reads = 0
        self.status_entered = asyncio.Event()

    async def status(self, request: Any) -> Any:
        self.status_reads += 1
        self.status_entered.set()
        await self.gate.wait()
        return await super().status(request)


def _request() -> OperationWorkflowRequest:
    operation = cursor_operation()
    return OperationWorkflowRequest.model_validate(
        {
            "semantic_attempt_id": operation.identity.semantic_key,
            "operation_kind": "bound_operation",
            "operation": operation,
            "segments": BOUNDS,
        }
    )


def _workers(env: WorkflowEnvironment, stack: LaneStack) -> tuple[Worker, Worker]:
    activities = OperationExecutionActivities(
        stack.boundary, worker_identity="mo75-worker", lane_turns=stack.service
    )
    return (
        Worker(
            env.client,
            task_queue=WORKFLOW_QUEUE,
            workflows=[OperationWorkflow],
            workflow_runner=coordinator_workflow_runner(),
        ),
        Worker(
            env.client, task_queue=LANE_QUEUE, activities=agent_cognitive_activities(activities)
        ),
    )


def _scheduled(history: Any) -> list[str]:
    return [
        event.activity_task_scheduled_event_attributes.activity_type.name
        for event in history.events
        if event.HasField("activity_task_scheduled_event_attributes")
    ]


def _completed_status_reads(history: Any) -> int:
    scheduled = {
        event.event_id
        for event in history.events
        if event.HasField("activity_task_scheduled_event_attributes")
        and event.activity_task_scheduled_event_attributes.activity_type.name == "lane.status"
    }
    return sum(
        1
        for event in history.events
        if event.HasField("activity_task_completed_event_attributes")
        and event.activity_task_completed_event_attributes.scheduled_event_id in scheduled
    )


def _signals(history: Any) -> int:
    return sum(
        1
        for event in history.events
        if event.HasField("workflow_execution_signaled_event_attributes")
    )


async def _until(check: Callable[[], Awaitable[bool]], *, seconds: float = 60) -> None:
    for _ in range(int(seconds * 10)):
        if await check():
            return
        await asyncio.sleep(0.1)
    raise AssertionError("condition did not hold in time")


async def _replays(handle: WorkflowHandle[Any, Any]) -> Any:
    history = await handle.fetch_history()
    await Replayer(
        workflows=[OperationWorkflow], workflow_runner=coordinator_workflow_runner()
    ).replay_workflow(history)
    return history


@pytest.mark.asyncio
async def test_hints_present_at_one_boundary_coalesce_into_one_status_read(
    workflow_env: WorkflowEnvironment,
) -> None:
    lane = _GatedStatusLane()
    stack = lane_stack(lane)
    workflow_worker, activity_worker = _workers(workflow_env, stack)
    async with workflow_worker, activity_worker:
        handle = await workflow_env.client.start_workflow(
            OperationWorkflow.run, _request(), id="mo75-coalesce", task_queue=WORKFLOW_QUEUE
        )
        await asyncio.wait_for(lane.held.wait(), timeout=60)
        lane.gate.clear()
        await handle.signal(OperationWorkflow.ingress_wake, "ingress-1")
        await asyncio.wait_for(lane.status_entered.wait(), timeout=60)
        # Two duplicate hints land while the first read runs.
        await handle.signal(OperationWorkflow.ingress_wake, "ingress-2")
        await handle.signal(OperationWorkflow.ingress_wake, "ingress-2")

        async def three_signals() -> bool:
            return _signals(await handle.fetch_history()) == 3

        await _until(three_signals)
        lane.gate.set()

        async def two_reads() -> bool:
            return _completed_status_reads(await handle.fetch_history()) == 2

        await _until(two_reads)
        await asyncio.sleep(1)
        assert lane.status_reads == 2, "the two hints after the first read coalesced"
        assert lane.sends != [] and len(lane.sends) == 1
        lane.released.set()
        result = await asyncio.wait_for(handle.result(), timeout=120)
        history = await _replays(handle)

    # Status observations never replace the original turn handle: it settles the unit.
    assert result.disposition == "completed"
    assert parse_operation_result(result.result).status == "completed"
    assert _scheduled(history) == ["lane.turn", "lane.status", "lane.status", "lane.cleanup"]
    assert len(lane.sends) == 1 and lane.cancels == []
    assert INGRESS_STATUS_PATCH in patch_ids(history)


@pytest.mark.asyncio
async def test_status_reads_per_segment_are_bounded_even_with_new_hints(
    workflow_env: WorkflowEnvironment,
) -> None:
    lane = _GatedStatusLane()
    stack = lane_stack(lane)
    workflow_worker, activity_worker = _workers(workflow_env, stack)
    async with workflow_worker, activity_worker:
        handle = await workflow_env.client.start_workflow(
            OperationWorkflow.run, _request(), id="mo75-bounded", task_queue=WORKFLOW_QUEUE
        )
        await asyncio.wait_for(lane.held.wait(), timeout=60)
        for read in range(1, MAX_INGRESS_PROBES_PER_SEGMENT + 1):
            await handle.signal(OperationWorkflow.ingress_wake, f"ingress-{read}")

            async def read_done(read: int = read) -> bool:
                return _completed_status_reads(await handle.fetch_history()) == read

            await _until(read_done)
        # Further hints in the same segment trigger no read.
        await handle.signal(OperationWorkflow.ingress_wake, "ingress-extra-1")
        await handle.signal(OperationWorkflow.ingress_wake, "ingress-extra-2")

        async def five_signals() -> bool:
            return _signals(await handle.fetch_history()) == MAX_INGRESS_PROBES_PER_SEGMENT + 2

        await _until(five_signals)
        await asyncio.sleep(1)
        assert lane.status_reads == MAX_INGRESS_PROBES_PER_SEGMENT
        lane.released.set()
        result = await asyncio.wait_for(handle.result(), timeout=120)
        history = await _replays(handle)

    assert result.disposition == "completed"
    assert _scheduled(history).count("lane.status") == MAX_INGRESS_PROBES_PER_SEGMENT
    assert len(lane.sends) == 1


@pytest.mark.asyncio
async def test_a_hint_during_the_segment_wakes_the_in_doubt_park(
    workflow_env: WorkflowEnvironment,
) -> None:
    """The unit is cancelled; the provider never turns terminal, so the cancel segment ends
    `in_doubt`. A hint that lands during that segment re-runs the cancel path at once; without
    the snapshot the park would wait for another hint."""

    lane = _GatedStatusLane()
    lane.never_terminal = True
    stack = lane_stack(lane)
    workflow_worker, activity_worker = _workers(workflow_env, stack)
    async with workflow_worker, activity_worker:
        handle = await workflow_env.client.start_workflow(
            OperationWorkflow.run, _request(), id="mo75-snapshot", task_queue=WORKFLOW_QUEUE
        )
        await asyncio.wait_for(lane.held.wait(), timeout=60)
        lane.gate.clear()
        lane.status_entered.clear()
        await handle.execute_update("cancel_command", args=["cmd-1"])
        # The cancel segment's first status poll is in flight: the hint lands mid-segment.
        await asyncio.wait_for(lane.status_entered.wait(), timeout=60)
        await handle.signal(OperationWorkflow.ingress_wake, "ingress-during-segment")

        async def signalled() -> bool:
            return _signals(await handle.fetch_history()) == 1

        await _until(signalled)
        lane.gate.set()

        async def cancel_path_ran_again() -> bool:
            # First segment: lane.cancel, then lane.cancel(in_doubt); the woken park runs
            # the cancel path again before any operator decision.
            return _scheduled(await handle.fetch_history()).count("lane.cancel") >= 3

        await _until(cancel_path_ran_again)
        lane.never_terminal = False
        await handle.signal(OperationWorkflow.unit_reconciliation_recorded, "decision-1")
        result = await asyncio.wait_for(handle.result(), timeout=120)
        history = await _replays(handle)

    assert result.disposition == "cancelled"
    assert INGRESS_SNAPSHOT_PATCH in patch_ids(history)
    assert len(lane.sends) == 1
