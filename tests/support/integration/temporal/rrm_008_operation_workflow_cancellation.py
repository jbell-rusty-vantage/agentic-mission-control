"""Builders, constants and fakes that other test files import.

Moved from tests/integration/temporal/test_operation_workflow_cancellation.py.
"""

from __future__ import annotations

from typing import Any

from temporalio.client import WorkflowHandle
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from mission_control.adapters.temporal.operation_activities import OperationExecutionActivities
from mission_control.adapters.temporal.workflow_sandbox import coordinator_workflow_runner
from mission_control.adapters.temporal.workflows.operation import OperationWorkflow
from mission_control.domain.execution.contracts import (
    OperationExecutionRequest,
    OperationWorkflowRequest,
)
from tests.fixtures.checkpoint_recovery import RecoveryHarness

WORKFLOW_QUEUE = "rrm008-operation-workflows"
HEARTBEAT_SECONDS = 2
TIMEOUT_SECONDS = 60


def _request(request: OperationExecutionRequest) -> OperationWorkflowRequest:
    return OperationWorkflowRequest(
        semantic_attempt_id=request.identity.semantic_key,
        operation_kind="bound_operation",
        operation=request,
        timeout_seconds=TIMEOUT_SECONDS,
        heartbeat_timeout_seconds=HEARTBEAT_SECONDS,
    )


def _scheduled(history: Any) -> list[str]:
    return [
        event.activity_task_scheduled_event_attributes.activity_type.name
        for event in history.events
        if event.HasField("activity_task_scheduled_event_attributes")
    ]


class _Stack:
    def __init__(self, harness: RecoveryHarness, environment: WorkflowEnvironment) -> None:
        self.harness = harness
        self.environment = environment
        self.activities = OperationExecutionActivities(
            harness.service, worker_identity="rrm008-worker"
        )

    def workers(self) -> tuple[Worker, Worker]:
        return (
            Worker(
                self.environment.client,
                task_queue=WORKFLOW_QUEUE,
                workflows=[OperationWorkflow],
                workflow_runner=coordinator_workflow_runner(),
            ),
            Worker(
                self.environment.client,
                task_queue=self.harness.binding.task_queue,
                activities=[self.activities.execute, self.activities.cancel],
            ),
        )

    async def start(
        self, request: OperationExecutionRequest, workflow_id: str
    ) -> WorkflowHandle[Any, Any]:
        return await self.environment.client.start_workflow(
            OperationWorkflow.run,
            _request(request),
            id=workflow_id,
            task_queue=WORKFLOW_QUEUE,
        )


async def _replays(handle: WorkflowHandle[Any, Any]) -> Any:
    history = await handle.fetch_history()
    await Replayer(
        workflows=[OperationWorkflow], workflow_runner=coordinator_workflow_runner()
    ).replay_workflow(history)
    return history
