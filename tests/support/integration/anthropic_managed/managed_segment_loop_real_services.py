"""Builders, constants and fakes that other test files import.

Moved from tests/integration/anthropic_managed/test_managed_segment_loop_real_services.py.
"""

from __future__ import annotations

import os
from datetime import timedelta
from typing import Any

import pytest
from temporalio.client import Client, WorkflowHandle
from temporalio.worker import Replayer, Worker

from mission_control.adapters.temporal.operation_activities import OperationExecutionActivities
from mission_control.adapters.temporal.registration.activities import agent_cognitive_activities
from mission_control.adapters.temporal.workflow_sandbox import coordinator_workflow_runner
from mission_control.adapters.temporal.workflows.operation import OperationWorkflow
from mission_control.application.execution.harness.lane_turns import LaneTurnService
from mission_control.domain.execution.contracts import (
    OperationExecutionRequest,
    OperationWorkflowRequest,
)
from mission_control.domain.execution.lanes import LaneSegmentBounds

ADDRESS = os.environ.get("MC_TEMPORAL_TEST_ADDRESS", "127.0.0.1:7233")
NAMESPACE = os.environ.get("MC_TEMPORAL_TEST_NAMESPACE", "default")
BOUNDS = LaneSegmentBounds(
    max_frames=50,
    max_duration_s=30,
    start_to_close_s=60,
    heartbeat_timeout_s=3,
    status_poll_limit=3,
    status_poll_interval_s=1,
    busy_wait_s=30,
)
WITHIN_S = 120.0


async def _client() -> Client:
    try:
        return await Client.connect(ADDRESS, namespace=NAMESPACE)
    except RuntimeError as error:
        pytest.fail(f"the real local Temporal server at {ADDRESS} is required: {error}")


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


async def _replayed(handle: WorkflowHandle[Any, Any]) -> Any:
    history = await handle.fetch_history()
    await Replayer(
        workflows=[OperationWorkflow], workflow_runner=coordinator_workflow_runner()
    ).replay_workflow(history)
    return history
