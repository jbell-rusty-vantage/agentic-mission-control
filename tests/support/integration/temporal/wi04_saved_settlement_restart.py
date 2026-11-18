"""Builders, constants and fakes that other test files import.

Moved from tests/integration/temporal/test_wi04_saved_settlement_restart.py.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import pytest
from temporalio.client import WorkflowHandle
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from mission_control.adapters.postgres.operations.invocation_settlement import (
    PostgresInvocationSettlementStore,
)
from mission_control.adapters.temporal.operation_activities import OperationExecutionActivities
from mission_control.adapters.temporal.workflow_sandbox import coordinator_workflow_runner
from mission_control.adapters.temporal.workflows.operation import OperationWorkflow
from mission_control.domain.execution.contracts import (
    OperationExecutionRequest,
    OperationWorkflowRequest,
)
from mission_control.domain.execution.invocation_settlement import (
    InvocationSettlement,
    SettlementState,
)
from tests.fixtures.checkpoint_recovery import RecoveryHarness

WORKFLOW_QUEUE = "wi04-operation-workflows"
HEARTBEAT_SECONDS = 2
TIMEOUT_SECONDS = 60


async def _environment() -> WorkflowEnvironment:
    existing = os.environ.get("MISSION_CONTROL_TEST_TEMPORAL_SERVER") or None
    try:
        return await WorkflowEnvironment.start_time_skipping(test_server_existing_path=existing)
    except RuntimeError as error:
        pytest.skip(f"Temporal test server is unavailable: {error}")


class _Stack:
    def __init__(
        self,
        harness: RecoveryHarness,
        environment: WorkflowEnvironment,
        store: PostgresInvocationSettlementStore,
    ) -> None:
        self.harness = harness
        self.environment = environment
        self.store = store

    def workflow_worker(self) -> Worker:
        return Worker(
            self.environment.client,
            task_queue=WORKFLOW_QUEUE,
            workflows=[OperationWorkflow],
            workflow_runner=coordinator_workflow_runner(),
        )

    def activity_worker(self, identity: str) -> Worker:
        """A fresh activity worker over the same durable stores (a restarted process)."""

        activities = OperationExecutionActivities(self.harness.service, worker_identity=identity)
        return Worker(
            self.environment.client,
            task_queue=self.harness.binding.task_queue,
            activities=[activities.execute, activities.cancel],
        )

    async def start(
        self,
        request: OperationExecutionRequest,
        workflow_id: str,
        *,
        waits_per_run: int | None = None,
    ) -> WorkflowHandle[Any, Any]:
        return await self.environment.client.start_workflow(
            OperationWorkflow.run,
            OperationWorkflowRequest(
                semantic_attempt_id=request.identity.semantic_key,
                operation_kind="bound_operation",
                operation=request,
                timeout_seconds=TIMEOUT_SECONDS,
                heartbeat_timeout_seconds=HEARTBEAT_SECONDS,
                settlement_waits_per_run=waits_per_run,
            ),
            id=workflow_id,
            task_queue=WORKFLOW_QUEUE,
        )

    async def record(self, request: OperationExecutionRequest) -> InvocationSettlement | None:
        binding = await self.harness.bindings.get_binding(  # type: ignore[union-attr]
            request.identity.semantic_key, request_scope=request.request_scope
        )
        if binding is None:
            return None
        return await self.store.get(request.request_scope, binding.binding_id)

    async def until(
        self, request: OperationExecutionRequest, state: SettlementState, *, seconds: float = 60
    ) -> InvocationSettlement:
        async with asyncio.timeout(seconds):
            while True:
                record = await self.record(request)
                if record is not None and record.settlement is state:
                    return record
                await asyncio.sleep(0.1)


async def _replays(handle: WorkflowHandle[Any, Any]) -> Any:
    history = await handle.fetch_history()
    await Replayer(
        workflows=[OperationWorkflow], workflow_runner=coordinator_workflow_runner()
    ).replay_workflow(history)
    return history


def _scheduled(history: Any) -> list[str]:
    return [
        event.activity_task_scheduled_event_attributes.activity_type.name
        for event in history.events
        if event.HasField("activity_task_scheduled_event_attributes")
    ]
