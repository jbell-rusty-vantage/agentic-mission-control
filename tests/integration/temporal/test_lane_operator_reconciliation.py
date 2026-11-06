"""Protocol cancellation uses actual operator authority; no provider is permitted."""

from __future__ import annotations

import asyncio

from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from mission_control.adapters.temporal.operation_activities import OperationExecutionActivities
from mission_control.adapters.temporal.registration.activities import agent_cognitive_activities
from mission_control.adapters.temporal.workflow_sandbox import coordinator_workflow_runner
from mission_control.adapters.temporal.workflows.operation import OperationWorkflow
from mission_control.domain.execution.contracts import OperationWorkflowRequest
from tests.unit.harness.test_lane_operator_abandonment import lane_recovery, no_adapter_selection


async def test_real_lane_cancel_parks_then_normal_abandon_hint_settles_and_replays(monkeypatch):
    recovery, service, local, lane, identity = await lane_recovery()
    monkeypatch.setattr(service, "_session_lane", no_adapter_selection)
    activities = OperationExecutionActivities(
        recovery.harness.service, worker_identity="operator-reconciliation", lane_turns=service
    )
    request = OperationWorkflowRequest(
        semantic_attempt_id=recovery.request.identity.semantic_key,
        operation_kind="bound_operation",
        operation=recovery.request,
    )
    # Failure to start the disposable server is a failure, never an availability skip.
    async with await WorkflowEnvironment.start_time_skipping() as env:
        workflow_worker = Worker(
            env.client,
            task_queue="operator-reconciliation-workflows",
            workflows=[OperationWorkflow],
            workflow_runner=coordinator_workflow_runner(),
        )
        activity_worker = Worker(
            env.client,
            task_queue=request.activity_task_queue,
            activities=agent_cognitive_activities(activities),
        )
        with env.auto_time_skipping_disabled():
            async with workflow_worker:
                handle = await env.client.start_workflow(
                    OperationWorkflow.run,
                    request,
                    id="protocol-operator-abandonment",
                    task_queue="operator-reconciliation-workflows",
                )
                # Deliver the command before an activity worker can select any adapter.
                await handle.execute_update("cancel_command", args=["cancel-native-fixture"])
                async with activity_worker:
                    async with asyncio.timeout(60):
                        while await recovery.incident() is None:  # noqa: ASYNC110 - durable state poll
                            await asyncio.sleep(0.05)
                    assert await recovery.harness.service.lane_settlement(recovery.request) is None
                    decision = await recovery.abandon()
                    await handle.signal(
                        OperationWorkflow.unit_reconciliation_recorded, decision.command_id
                    )
                    result = await asyncio.wait_for(handle.result(), timeout=60)
                    history = await handle.fetch_history()
                    await Replayer(
                        workflows=[OperationWorkflow],
                        workflow_runner=coordinator_workflow_runner(),
                    ).replay_workflow(history)
    assert result.disposition == "cancelled"
    assert result.result["failure_code"] == "in_doubt_abandoned"
    assert not lane.calls and not lane.cleanups and not recovery.harness.model.calls
    state = await local.states.load(identity.request_scope, identity.harness_execution_id)
    assert next(iter(state.dispatches.values())).phase == "in_doubt"
    assert state.native_session_ref is None
    assert all(
        call.args[3] != "provider_acknowledged"
        for call in recovery.milestones.record_milestone.await_args_list
    )
    scheduled = [
        event.activity_task_scheduled_event_attributes.activity_type.name
        for event in history.events
        if event.HasField("activity_task_scheduled_event_attributes")
    ]
    assert scheduled.count("lane.cancel") >= 2
