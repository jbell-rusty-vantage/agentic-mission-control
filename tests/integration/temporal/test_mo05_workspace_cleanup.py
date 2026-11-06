"""MO-05 on the real local Temporal server (127.0.0.1:7233): the operation workflow cleans a
settled unit's leased worktree (SPEC-03 sections 2 and 7).

The real `OperationWorkflow` drives the real `cursor_local` harness (FIXTURE bridge, real git
worktrees, the binding's `within_run` policy) through the real `lane.turn` and `lane.cleanup`
activities. A completed unit's worktree is removed after the settlement registered its
Artifacts, its snapshots stay in custody, and the run's next unit continues from them; a
failed unit's work is retained. Every history replays.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from temporalio.client import Client, WorkflowHandle
from temporalio.worker import Replayer, Worker

from mission_control.adapters.temporal.operation_activities import (
    OperationExecutionActivities,
    parse_operation_result,
)
from mission_control.adapters.temporal.registration.activities import agent_cognitive_activities
from mission_control.adapters.temporal.workflow_sandbox import coordinator_workflow_runner
from mission_control.adapters.temporal.workflows.operation import (
    WORKSPACE_CLEANUP_PATCH,
    OperationWorkflow,
)
from mission_control.application.execution.harness.leases import WorkspaceLease
from mission_control.domain.execution.contracts import (
    OperationExecutionRequest,
    OperationWorkflowRequest,
)
from mission_control.domain.execution.lanes import LaneSegmentBounds
from tests.fixtures.cursor_local import LocalStack, local_stack
from tests.fixtures.lane_turns import lane_stack
from tests.fixtures.local_lane_workspaces import WITHIN_RUN, LaneDriver
from tests.fixtures.temporal_history import completed_activity_results, patch_ids

ADDRESS = os.environ.get("MC_TEMPORAL_TEST_ADDRESS", "127.0.0.1:7233")
NAMESPACE = os.environ.get("MC_TEMPORAL_TEST_NAMESPACE", "default")
BOUNDS = LaneSegmentBounds(
    max_frames=50,
    max_duration_s=30,
    start_to_close_s=120,
    heartbeat_timeout_s=10,
    status_poll_limit=2,
    status_poll_interval_s=1,
    busy_wait_s=30,
)


async def _client() -> Client:
    try:
        return await Client.connect(ADDRESS, namespace=NAMESPACE)
    except RuntimeError as error:
        pytest.fail(f"the real local Temporal server at {ADDRESS} is required: {error}")


def _scheduled(history: Any) -> list[str]:
    return [
        event.activity_task_scheduled_event_attributes.activity_type.name
        for event in history.events
        if event.HasField("activity_task_scheduled_event_attributes")
    ]


def _stack(tmp_path: Path, fixture: str, queue: str) -> LocalStack:
    return local_stack(
        tmp_path, fixture, binding_changes={"policy": WITHIN_RUN.model_dump(), "task_queue": queue}
    )


def _request(operation: OperationExecutionRequest) -> OperationWorkflowRequest:
    return OperationWorkflowRequest(
        semantic_attempt_id=operation.identity.semantic_key,
        operation_kind="bound_operation",
        operation=operation,
        segments=BOUNDS,
    )


async def _run(
    client: Client, stack: LocalStack, lane_queue: str
) -> tuple[Any, Any, WorkspaceLease]:
    lanes = lane_stack(stack.harness, frames=stack.frames, operation=stack.operation)
    activities = OperationExecutionActivities(
        lanes.boundary, worker_identity="mo05-worker", lane_turns=lanes.service
    )
    workflow_queue = f"mo05-wf-{uuid4().hex[:8]}"
    async with (
        Worker(
            client,
            task_queue=workflow_queue,
            workflows=[OperationWorkflow],
            workflow_runner=coordinator_workflow_runner(),
        ),
        Worker(client, task_queue=lane_queue, activities=agent_cognitive_activities(activities)),
    ):
        handle: WorkflowHandle[Any, Any] = await client.start_workflow(
            OperationWorkflow.run,
            _request(stack.operation),
            id=f"mo05-{uuid4().hex[:10]}",
            task_queue=workflow_queue,
        )
        result = await asyncio.wait_for(handle.result(), timeout=180)
        history = await handle.fetch_history()
    await Replayer(
        workflows=[OperationWorkflow], workflow_runner=coordinator_workflow_runner()
    ).replay_workflow(history)
    (lease,) = stack.leases._leases.values()
    return result, history, lease


async def test_a_completed_unit_is_cleaned_after_settlement_and_its_snapshot_retained(
    tmp_path: Path,
) -> None:
    client = await _client()
    lane_queue = f"mo05-lane-{uuid4().hex[:8]}"
    stack = _stack(tmp_path, "full_run", lane_queue)
    result, history, lease = await _run(client, stack, lane_queue)

    assert result.disposition == "completed"
    settled = parse_operation_result(result.result)
    assert _scheduled(history) == ["lane.turn", "lane.cleanup"]
    cleaned = completed_activity_results(history, "lane.cleanup")
    assert [entry["outcome"] for entry in cleaned] == ["removed"]
    assert WORKSPACE_CLEANUP_PATCH in patch_ids(history)
    # Cleaned after the settlement registered the Artifacts; the snapshots stay in custody.
    assert lease.policy is not None and lease.policy.reuse == "within_run"
    assert lease.cleanup_status == "completed"
    assert not await asyncio.to_thread(Path(lease.path).exists)
    assert lease.snapshot_ref is not None and lease.snapshot_ref in settled.output_refs
    assert lease.workspace_snapshot_ref is not None
    custody = lease.workspace_snapshot_ref.removeprefix("workspace-snapshot:")
    assert custody in stack.artifacts.staged and lease.patch_artifact_ref in settled.output_refs

    # The run's next holder of the slot continues from the retained custody snapshot.
    driver = LaneDriver(
        "cursor_local", stack.harness, stack.operation, stack.leases, stack.artifacts
    )
    continued = await driver.prepare(2)
    assert continued == Path(lease.path)
    assert await asyncio.to_thread((continued / "src" / "feature.py").is_file)


async def test_a_failed_unit_keeps_its_worktree(tmp_path: Path) -> None:
    client = await _client()
    lane_queue = f"mo05-lane-{uuid4().hex[:8]}"
    stack = _stack(tmp_path, "error_run", lane_queue)
    result, history, lease = await _run(client, stack, lane_queue)

    assert result.disposition == "failed"
    assert _scheduled(history) == ["lane.turn"]
    assert WORKSPACE_CLEANUP_PATCH not in patch_ids(history)
    assert lease.released and lease.workspace_snapshot_ref is not None
    assert lease.cleanup_status == "pending"
    assert await asyncio.to_thread(Path(lease.path).is_dir)
