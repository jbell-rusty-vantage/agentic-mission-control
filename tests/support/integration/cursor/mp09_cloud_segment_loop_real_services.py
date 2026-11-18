"""Builders, constants and fakes that other test files import.

Moved from tests/integration/cursor/test_mp09_cloud_segment_loop_real_services.py.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import asyncpg
import pytest
from temporalio.client import Client, WorkflowHandle
from temporalio.worker import Replayer, Worker

from mission_control.adapters.postgres.frames.repository import PostgresFrameRepository
from mission_control.adapters.postgres.lanes.execution_state import PostgresLaneExecutionStateStore
from mission_control.adapters.temporal.operation_activities import OperationExecutionActivities
from mission_control.adapters.temporal.registration.activities import agent_cognitive_activities
from mission_control.adapters.temporal.workflow_sandbox import coordinator_workflow_runner
from mission_control.adapters.temporal.workflows.operation import OperationWorkflow
from mission_control.application.execution.harness.lane_turns import (
    LaneExecutionIdentity,
    LaneTurnService,
)
from mission_control.application.execution.harness.sessions import WorkerSessionManager
from mission_control.domain.execution.contracts import (
    OperationAttemptIdentity,
    OperationExecutionRequest,
    OperationWorkflowRequest,
)
from mission_control.domain.execution.lanes import CursorExecutionBinding, LaneSegmentBounds
from tests.fixtures.lane_bindings import lane_fields
from tests.fixtures.lane_turns import LaneStack, lane_stack
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.support.db_builders import admit_unit_attempt
from tests.support.providers.cursor import CloudStack, cloud_stack

ADDRESS = os.environ.get("MC_TEMPORAL_TEST_ADDRESS", "127.0.0.1:7233")
NAMESPACE = os.environ.get("MC_TEMPORAL_TEST_NAMESPACE", "default")
PROFILE = "cursor_cloud"
BOUNDS = LaneSegmentBounds(
    max_frames=50,
    max_duration_s=30,
    start_to_close_s=60,
    heartbeat_timeout_s=3,
    status_poll_limit=3,
    status_poll_interval_s=1,
    busy_wait_s=30,
)


async def _client() -> Client:
    try:
        return await Client.connect(ADDRESS, namespace=NAMESPACE)
    except RuntimeError as error:
        pytest.fail(f"the real local Temporal server at {ADDRESS} is required: {error}")


@dataclass
class PgCloudUnit:
    operation: OperationExecutionRequest
    stack: LaneStack
    cloud: CloudStack
    frames: PostgresFrameRepository
    states: PostgresLaneExecutionStateStore

    @property
    def identity(self) -> LaneExecutionIdentity:
        return LaneExecutionIdentity.of(self.operation, PROFILE, 1)

    def service(self, owner: str) -> LaneTurnService:
        return LaneTurnService(
            lanes=self.stack.service._lanes,
            boundary=self.stack.boundary,
            frames=self.frames,
            states=self.states,
            frame_reader=self.frames,
            sessions=WorkerSessionManager(owner_ref=owner, min_lease=timedelta(seconds=1)),
        )


async def pg_cloud_unit(
    pool: asyncpg.Pool,
    db: CommonDatabase,
    tmp_path: Path,
    *,
    task_queue: str,
    api_changes: dict[str, Any],
    **stack: Any,
) -> PgCloudUnit:
    """A `cursor_cloud` operation bound to one admitted runtime unit of a real run in
    PostgreSQL, over the fixture Cloud API (its binding re-sealed with the test queue);
    `stack` goes to `cloud_stack`."""

    admitted = await admit_unit_attempt(pool, db)
    unit = admitted.unit
    cloud = cloud_stack(tmp_path, api_changes=api_changes, **stack)
    base = CursorExecutionBinding.carried_by(cloud.operation)
    assert base is not None
    binding = CursorExecutionBinding.sealed(
        **{**base.model_dump(mode="python", exclude={"binding_digest"}), "task_queue": task_queue}
    )
    payload = cloud.operation.model_dump(mode="python")
    payload.update(
        request_scope=unit.request_scope,
        identity=OperationAttemptIdentity(
            run_id=admitted.run_key,
            operation_id=unit.semantic_operation_id,
            operation_attempt=unit.semantic_attempt,
        ),
        runtime_unit=unit,
        idempotency_key=f"mp09:{unit.unit_key}",
        **lane_fields(binding),
    )
    operation = OperationExecutionRequest.model_validate(payload)
    stack = lane_stack(cloud.harness, operation=operation)
    return PgCloudUnit(
        operation=operation,
        stack=stack,
        cloud=cloud,
        frames=PostgresFrameRepository(pool),
        states=PostgresLaneExecutionStateStore(pool),
    )


def _request(operation: OperationExecutionRequest) -> OperationWorkflowRequest:
    return OperationWorkflowRequest.model_validate(
        {
            "semantic_attempt_id": operation.identity.semantic_key,
            "operation_kind": "bound_operation",
            "operation": operation,
            "segments": BOUNDS,
        }
    )


def _workflow_worker(client: Client, queue: str) -> Worker:
    return Worker(
        client,
        task_queue=queue,
        workflows=[OperationWorkflow],
        workflow_runner=coordinator_workflow_runner(),
    )


def _activity_worker(client: Client, queue: str, boundary: Any, service: LaneTurnService) -> Worker:
    activities = OperationExecutionActivities(
        boundary, worker_identity=service.sessions.owner_ref, lane_turns=service
    )
    return Worker(
        client,
        task_queue=queue,
        activities=agent_cognitive_activities(activities),
        graceful_shutdown_timeout=timedelta(0),
    )


async def _start(
    client: Client, request: OperationWorkflowRequest, queue: str, name: str
) -> WorkflowHandle[Any, Any]:
    return await client.start_workflow(
        OperationWorkflow.run,
        request,
        id=f"{name}-{uuid4().hex[:10]}",
        task_queue=queue,
        execution_timeout=timedelta(minutes=5),
    )


async def _replayed(handle: WorkflowHandle[Any, Any]) -> Any:
    history = await handle.fetch_history()
    await Replayer(
        workflows=[OperationWorkflow], workflow_runner=coordinator_workflow_runner()
    ).replay_workflow(history)
    return history


async def _run(
    unit: PgCloudUnit, client: Client, lane_queue: str, workflow_queue: str, name: str
) -> tuple[Any, Any]:
    service = unit.service(f"mp09-worker-{uuid4().hex[:6]}")
    async with (
        _workflow_worker(client, workflow_queue),
        _activity_worker(client, lane_queue, unit.stack.boundary, service),
    ):
        handle = await _start(client, _request(unit.operation), workflow_queue, name)
        result = await asyncio.wait_for(handle.result(), timeout=180)
        history = await _replayed(handle)
    return result, history
