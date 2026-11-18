"""Builders, constants and fakes that other test files import.

Moved from tests/integration/temporal/test_claude_lane_turns.py.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import asyncpg
import pytest
from temporalio.client import Client, WorkflowHandle
from temporalio.worker import Replayer, Worker

from mission_control.adapters.claude.permissions import PermissionBindingPort
from mission_control.adapters.postgres.frames.repository import PostgresFrameRepository
from mission_control.adapters.postgres.lanes.execution_state import PostgresLaneExecutionStateStore
from mission_control.adapters.temporal.operation_activities import OperationExecutionActivities
from mission_control.adapters.temporal.registration.activities import agent_cognitive_activities
from mission_control.adapters.temporal.workflow_sandbox import coordinator_workflow_runner
from mission_control.adapters.temporal.workflows.operation import OperationWorkflow
from mission_control.application.execution.harness.lane_turns import LaneTurnService
from mission_control.application.execution.harness.sessions import WorkerSessionManager
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.execution.contracts import (
    OperationAttemptIdentity,
    OperationExecutionRequest,
    OperationWorkflowRequest,
)
from mission_control.domain.execution.lane_turns import LaneSegmentBounds
from tests.support.db import CommonDatabase
from tests.support.db_builders import admit_unit_attempt
from tests.support.providers.claude import ClaudeStack, claude_operation, claude_stack

ADDRESS = os.environ.get("MC_TEMPORAL_TEST_ADDRESS", "127.0.0.1:7233")
NAMESPACE = os.environ.get("MC_TEMPORAL_TEST_NAMESPACE", "default")
WORKER = "mp07-worker-a"
# Three frames per segment: the full run spans several `lane.turn` activities, each one
# reattaching the live session this process holds (the SDK subprocess outlives a segment).
BOUNDS = LaneSegmentBounds(
    max_frames=3,
    max_duration_s=30,
    start_to_close_s=60,
    heartbeat_timeout_s=5,
    status_poll_limit=3,
    status_poll_interval_s=1,
    busy_wait_s=30,
)


async def temporal_client() -> Client:
    try:
        return await Client.connect(ADDRESS, namespace=NAMESPACE)
    except RuntimeError as error:
        pytest.fail(f"the real local Temporal server at {ADDRESS} is required: {error}")


async def claude_unit(
    pool: asyncpg.Pool,
    db: CommonDatabase,
    tmp_path: Path,
    *,
    script: str,
    lane_queue: str,
    permissions: PermissionBindingPort | None = None,
) -> tuple[ClaudeStack, LaneTurnService, PostgresFrameRepository, PostgresLaneExecutionStateStore]:
    """An admitted unit attempt in PostgreSQL whose operation is a claude unit bound to
    `lane_queue` (its `provider_binding.task_queue`), and the production lane-turn service."""

    admitted = await admit_unit_attempt(pool, db)
    unit = admitted.unit
    payload = claude_operation(task_queue=lane_queue).model_dump(mode="python")
    payload.update(
        request_scope=unit.request_scope,
        identity=OperationAttemptIdentity(
            run_id=admitted.run_key,
            operation_id=unit.semantic_operation_id,
            operation_attempt=unit.semantic_attempt,
        ),
        runtime_unit=unit,
        idempotency_key=f"mp07:{unit.unit_key}",
    )
    operation = OperationExecutionRequest.model_validate(payload)
    stack = claude_stack(tmp_path, script=script, operation=operation, permissions=permissions)
    frames = PostgresFrameRepository(pool)
    states = PostgresLaneExecutionStateStore(pool)
    service = LaneTurnService(
        lanes=stack.lanes.service._lanes,
        boundary=stack.lanes.boundary,
        frames=frames,
        states=states,
        frame_reader=frames,
        sessions=WorkerSessionManager(owner_ref=WORKER, min_lease=timedelta(seconds=1)),
    )
    return stack, service, frames, states


def workflow_request(operation: OperationExecutionRequest) -> OperationWorkflowRequest:
    return OperationWorkflowRequest.model_validate(
        {
            "semantic_attempt_id": operation.identity.semantic_key,
            "operation_kind": "bound_operation",
            "operation": operation,
            "segments": BOUNDS,
        }
    )


@asynccontextmanager
async def operation_workers(
    client: Client, stack: ClaudeStack, service: LaneTurnService, workflow_queue: str
) -> AsyncIterator[None]:
    """The production workflow on its queue; the lane activities on the binding's queue."""

    assert ProviderExecutionBinding.carried_by(stack.operation) is not None
    lane_queue = ProviderExecutionBinding.carried_by(stack.operation).task_queue
    assert lane_queue is not None
    activities = OperationExecutionActivities(
        stack.lanes.boundary, worker_identity=WORKER, lane_turns=service
    )
    async with (
        Worker(
            client,
            task_queue=workflow_queue,
            workflows=[OperationWorkflow],
            workflow_runner=coordinator_workflow_runner(),
        ),
        Worker(client, task_queue=lane_queue, activities=agent_cognitive_activities(activities)),
    ):
        yield


async def start_operation(
    client: Client, request: OperationWorkflowRequest, workflow_queue: str
) -> WorkflowHandle[Any, Any]:
    return await client.start_workflow(
        OperationWorkflow.run,
        request,
        id=f"mp07-claude-{uuid4().hex[:10]}",
        task_queue=workflow_queue,
        execution_timeout=timedelta(minutes=5),
    )


async def replayed(handle: WorkflowHandle[Any, Any]) -> Any:
    history = await handle.fetch_history()
    await Replayer(
        workflows=[OperationWorkflow], workflow_runner=coordinator_workflow_runner()
    ).replay_workflow(history)
    return history


def queues() -> tuple[str, str]:
    return f"mp07-lane-{uuid4().hex[:8]}", f"mp07-wf-{uuid4().hex[:8]}"
