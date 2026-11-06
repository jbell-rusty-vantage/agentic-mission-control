"""Pinned pending result history; no workflow/client side effects or external calls."""

import copy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import TypeAdapter
from temporalio.api.enums.v1 import PendingActivityState
from temporalio.api.history.v1 import HistoryEvent
from temporalio.client import WorkflowExecutionStatus
from tests.unit.recovery.test_closed_workflow_temporal import Client, Handle, history
from tests.unit.recovery.test_terminal_adoption_readers import context_scenario

from mission_control.adapters.temporal.pending_family_inputs import TemporalPendingResultInputReader
from mission_control.contracts.contracts import MissionControlRejected
from mission_control.contracts.identities import mission_operation_id
from mission_control.domain.execution.contracts import OperationWorkflowRequest
from mission_control.domain.programs.contracts import (
    CancelAck,
    CancelDelivery,
    LateResultFacts,
    StageExecutionIdentity,
    StageGraphAcceptedProjection,
    StageGraphResultActivityRequest,
    StageGraphRunInput,
    StageResultObservation,
)


class PendingHandle(Handle):
    def __init__(self, workflow_id, run_id, events, pending):
        super().__init__(workflow_id, run_id, events, WorkflowExecutionStatus.RUNNING)
        self.pending = pending
        self.descriptions = 0
        self.advance = False
        self.advance_attempt = False

    async def describe(self, **kwargs):
        self.descriptions += 1
        current_pending = copy.deepcopy(self.pending)
        if self.advance_attempt and self.descriptions > 1:
            current_pending[0].attempt += 1
        return SimpleNamespace(
            run_id=self.run_id,
            status=self.status,
            raw_description=SimpleNamespace(
                pending_activities=current_pending,
                workflow_execution_info=SimpleNamespace(
                    history_length=len(self.events) + int(self.advance and self.descriptions > 1)
                ),
            ),
        )


async def fixture(monkeypatch):
    _, _, digest, run, connection, inputs = await context_scenario(monkeypatch)
    projection = TypeAdapter(StageGraphAcceptedProjection).validate_python(
        connection.head.decision_payload["projection"]
    )
    stage = next(iter(projection.stages.values()))
    identity = StageExecutionIdentity(
        run.run_id, inputs.family.execution_epoch, stage.candidate, stage.semantic_attempt
    )
    request = StageGraphResultActivityRequest(
        run.run_id,
        run.request_scope,
        projection,
        StageResultObservation(
            identity, {}, True, True, True, True, 1, operation_disposition="failed"
        ),
        LateResultFacts(),
        inputs.family.blueprint,
        1,
        connection.head.decided_at,
        "fixture",
        "correlation",
    )
    delivery = CancelDelivery(
        "exact-cancel", "exact-issuer", 1, 1, 1, run.version, "sha256:" + "a" * 64
    )
    ack = CancelAck("exact-cancel", "delivered", 1)
    opid = mission_operation_id(run.request_scope, run.run_id, inputs.operation.semantic_attempt_id)
    events = [HistoryEvent(event_id=n) for n in range(1, 8)]
    events[0].workflow_execution_started_event_attributes.workflow_type.name = "belllabs.stagegraph"
    events[1].start_child_workflow_execution_initiated_event_attributes.workflow_id = opid
    started = events[2].child_workflow_execution_started_event_attributes
    started.initiated_event_id = 2
    started.workflow_execution.workflow_id = opid
    started.workflow_execution.run_id = "op-exact"
    failed = events[3].child_workflow_execution_failed_event_attributes
    failed.initiated_event_id = 2
    failed.workflow_execution.CopyFrom(started.workflow_execution)
    accepted = events[4].workflow_execution_update_accepted_event_attributes
    accepted.protocol_instance_id = "update-exact"
    accepted.accepted_request.meta.update_id = "update-exact"
    accepted.accepted_request.input.name = "deliver_cancel"
    completed = events[5].workflow_execution_update_completed_event_attributes
    completed.accepted_event_id = 5
    completed.meta.update_id = "update-exact"
    completed.outcome.success.SetInParent()
    scheduled = events[6].activity_task_scheduled_event_attributes
    scheduled.activity_id = "pending-result"
    scheduled.activity_type.name = "stagegraph.decide_result"
    scheduled.task_queue.name = "exact-family-queue"
    pending = SimpleNamespace(
        activity_id="pending-result",
        state=PendingActivityState.PENDING_ACTIVITY_STATE_SCHEDULED,
        attempt=27,
    )
    family = PendingHandle(
        run.execution_target.family_workflow_id, "family-exact", events, [pending]
    )
    op_events = history()
    op_events[0].workflow_execution_started_event_attributes.workflow_type.name = "mc.operation.v1"
    operation = Handle(opid, "op-exact", op_events, WorkflowExecutionStatus.FAILED)
    client = Client(
        {(opid, "op-exact"): operation, (family.workflow_id, "family-exact"): family},
        {opid: "op-exact", family.workflow_id: "family-exact"},
    )
    values = {
        OperationWorkflowRequest: inputs.operation,
        StageGraphRunInput: inputs.family,
        StageGraphResultActivityRequest: request,
        CancelDelivery: delivery,
        CancelAck: ack,
    }

    async def decode(payloads, hints):
        return [values[hints[0]]]

    client.data_converter.decode = AsyncMock(side_effect=decode)
    kwargs = {
        "semantic_attempt_key": inputs.operation.semantic_attempt_id,
        "operation_temporal_run_id": "op-exact",
        "family_temporal_run_id": "family-exact",
        "expected_family_digest": digest,
        "scheduled_event_id": 7,
        "activity_id": "pending-result",
        "task_queue": "exact-family-queue",
        "expected_activity_attempt": 27,
        "cancel_command_id": "exact-cancel",
        "cancel_issuer": "exact-issuer",
    }
    return TemporalPendingResultInputReader(client), run, kwargs, family, operation, values


async def test_exact_scheduled_attempt27_failed_result_is_retained_without_closing_family(
    monkeypatch,
):
    reader, run, kwargs, family, _, values = await fixture(monkeypatch)
    result = await reader.read(run, **kwargs)
    assert result.pending_family_result.request == values[StageGraphResultActivityRequest]
    assert result.pending_family_result.scheduled_event_id == 7
    assert result.pending_family_result.activity_id == "pending-result"
    assert result.pending_family_result.digest.startswith("sha256:")
    assert family.status == WorkflowExecutionStatus.RUNNING


@pytest.mark.parametrize(
    "change",
    [
        "family_closed",
        "operation_active",
        "attempt",
        "started",
        "extra_pending",
        "history_gap",
        "history_advanced",
        "wrong_activity",
        "wrong_queue",
        "wrong_digest",
        "request_disposition",
        "request_generation",
        "request_blueprint",
        "cancel_stale",
        "cancel_identity",
        "cancel_epoch",
        "child_pending",
        "child_run",
        "cancel_incomplete",
        "attempt_advanced",
        "continuation",
        "external",
    ],
)
async def test_changed_or_unsafe_pending_frontier_refuses(monkeypatch, change):
    reader, run, kwargs, family, operation, values = await fixture(monkeypatch)
    pending = family.pending[0]
    if change == "family_closed":
        family.status = WorkflowExecutionStatus.FAILED
    elif change == "operation_active":
        operation.status = WorkflowExecutionStatus.RUNNING
    elif change == "attempt":
        pending.attempt = 2
    elif change == "started":
        pending.state = PendingActivityState.PENDING_ACTIVITY_STATE_STARTED
    elif change == "extra_pending":
        family.pending.append(pending)
    elif change == "history_gap":
        family.events[2].event_id = 99
    elif change == "history_advanced":
        family.advance = True
    elif change == "attempt_advanced":
        family.advance_attempt = True
    elif change == "continuation":
        family.events[
            0
        ].workflow_execution_started_event_attributes.continued_execution_run_id = "previous"
    elif change == "external":
        event = HistoryEvent(event_id=8)
        event.signal_external_workflow_execution_initiated_event_attributes.SetInParent()
        family.events.append(event)
    elif change == "wrong_activity":
        kwargs["activity_id"] = "another"
    elif change == "wrong_queue":
        kwargs["task_queue"] = "another"
    elif change == "wrong_digest":
        kwargs["expected_family_digest"] = "sha256:" + "f" * 64
    elif change.startswith("request_"):
        request = values[StageGraphResultActivityRequest]
        if change == "request_disposition":
            request = replace(
                request, observation=replace(request.observation, operation_disposition="completed")
            )
        elif change == "request_generation":
            request = replace(
                request,
                observation=replace(
                    request.observation,
                    identity=replace(request.observation.identity, execution_generation=2),
                ),
            )
        else:
            request = replace(request, blueprint={"changed": True})
        values[StageGraphResultActivityRequest] = request
    elif change == "cancel_stale":
        values[CancelAck] = replace(values[CancelAck], status="stale_generation")
    elif change == "cancel_identity":
        values[CancelDelivery] = replace(values[CancelDelivery], idempotency_issuer="another")
    elif change == "cancel_epoch":
        values[CancelDelivery] = replace(values[CancelDelivery], execution_epoch=2)
    elif change == "child_pending":
        family.events[3].ClearField("child_workflow_execution_failed_event_attributes")
    elif change == "child_run":
        family.events[
            3
        ].child_workflow_execution_failed_event_attributes.workflow_execution.run_id = "other"
    elif change == "cancel_incomplete":
        family.events[5].ClearField("workflow_execution_update_completed_event_attributes")
    with pytest.raises(MissionControlRejected):
        await reader.read(run, **kwargs)
