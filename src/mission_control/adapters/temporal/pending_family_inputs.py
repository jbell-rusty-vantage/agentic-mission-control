"""Read one pinned currently scheduled result activity in a quiescent family."""

import asyncio
from collections.abc import Sequence
from datetime import timedelta
from typing import Any, TypeVar, cast

from temporalio.api.common.v1 import Payload
from temporalio.api.enums.v1 import PendingActivityState
from temporalio.api.history.v1 import HistoryEvent
from temporalio.client import Client, WorkflowExecutionStatus

from mission_control.adapters.temporal.closed_workflow import require
from mission_control.adapters.temporal.terminal_adoption_inputs import (
    TemporalTerminalInputReader,
    TerminalWorkflowInputs,
)
from mission_control.application.recovery.terminal_evidence_adoption import PendingFamilyResult
from mission_control.contracts.identities import mission_operation_id
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import StageGraphBlueprint
from mission_control.domain.execution.contracts import OperationWorkflowRequest
from mission_control.domain.policies.contracts import RunProjection
from mission_control.domain.programs.contracts import (
    CancelAck,
    CancelDelivery,
    StageGraphResultActivityRequest,
    StageGraphRunInput,
)

T = TypeVar("T")


class TemporalPendingResultInputReader:
    def __init__(self, client: Client) -> None:
        self._client = client
        self._closed = TemporalTerminalInputReader(client)

    async def read(
        self,
        run: RunProjection,
        *,
        semantic_attempt_key: str,
        operation_temporal_run_id: str,
        family_temporal_run_id: str,
        expected_family_digest: str,
        scheduled_event_id: int,
        activity_id: str,
        task_queue: str,
        expected_activity_attempt: int,
        cancel_command_id: str,
        cancel_issuer: str,
    ) -> TerminalWorkflowInputs:
        async with asyncio.timeout(30):
            target = run.execution_target
            require(
                target is not None and target.family == "StageGraph", "exact family target required"
            )
            assert target is not None
            require(
                bool(
                    family_temporal_run_id
                    and activity_id
                    and task_queue
                    and cancel_command_id
                    and cancel_issuer
                )
                and scheduled_event_id > 1
                and type(expected_activity_attempt) is int
                and expected_activity_attempt >= 1,
                "pending activity trusted pins required",
            )
            operation_id = mission_operation_id(run.request_scope, run.run_id, semantic_attempt_key)
            operation = await self._closed._one(
                run, operation_id, operation_temporal_run_id, OperationWorkflowRequest
            )
            require(
                operation.semantic_attempt_id == semantic_attempt_key,
                "operation semantic identity differs",
            )
            handle = self._client.get_workflow_handle(
                target.family_workflow_id, run_id=family_temporal_run_id
            )
            latest = self._client.get_workflow_handle(target.family_workflow_id)
            before = await latest.describe(rpc_timeout=timedelta(seconds=5))
            require(
                before.run_id == family_temporal_run_id
                and before.status == WorkflowExecutionStatus.RUNNING,
                "pending family is not exact latest running execution",
            )
            info = before.raw_description
            pending = info.pending_activities
            require(
                len(pending) == 1
                and pending[0].activity_id == activity_id
                and pending[0].state == PendingActivityState.PENDING_ACTIVITY_STATE_SCHEDULED
                and pending[0].attempt == expected_activity_attempt,
                "pending result must be sole scheduled pinned attempt",
            )
            events: list[HistoryEvent] = []
            size = 0
            async for event in handle.fetch_history_events(
                page_size=100, rpc_timeout=timedelta(seconds=5)
            ):
                size += event.ByteSize()
                require(
                    len(events) < 4096 and size <= 8 * 1024 * 1024, "pending history exceeds bound"
                )
                require(event.event_id == len(events) + 1, "pending history is not contiguous")
                events.append(event)
            require(
                bool(events) and len(events) == info.workflow_execution_info.history_length,
                "pending history is incomplete or advanced",
            )
            first = events[0].workflow_execution_started_event_attributes
            require(
                events[0].HasField("workflow_execution_started_event_attributes")
                and not first.continued_execution_run_id,
                "original family start required",
            )
            await self._closed._validator._validate_input(run, target.family_workflow_id, first)
            family = await self._decode(first.input.payloads, StageGraphRunInput)
            scheduled, ended, started, children, closed_children, updates = (
                {},
                set(),
                set(),
                {},
                set(),
                {},
            )
            delivered = False
            for event in events:
                field = event.WhichOneof("attributes") or ""
                attrs: Any = getattr(event, field) if field else None
                require(
                    not field.startswith(
                        ("signal_external_workflow", "request_cancel_external_workflow")
                    )
                    and field != "workflow_execution_continued_as_new_event_attributes",
                    "external command or continuation requires separate reconciliation",
                )
                if field == "activity_task_scheduled_event_attributes":
                    scheduled[event.event_id] = attrs
                elif field == "activity_task_started_event_attributes":
                    started.add(attrs.scheduled_event_id)
                elif field in {
                    "activity_task_completed_event_attributes",
                    "activity_task_failed_event_attributes",
                    "activity_task_timed_out_event_attributes",
                    "activity_task_canceled_event_attributes",
                }:
                    ended.add(attrs.scheduled_event_id)
                elif field == "start_child_workflow_execution_initiated_event_attributes":
                    children[event.event_id] = attrs.workflow_id
                elif (
                    field.startswith("child_workflow_execution_")
                    and field != "child_workflow_execution_started_event_attributes"
                ):
                    closed_children.add(attrs.initiated_event_id)
                    if children.get(attrs.initiated_event_id) == operation_id:
                        require(
                            attrs.workflow_execution.run_id == operation_temporal_run_id,
                            "child execution pin differs",
                        )
                elif field == "start_child_workflow_execution_failed_event_attributes":
                    require(False, "unstarted child requires separate reconciliation")
                elif field == "workflow_execution_update_accepted_event_attributes":
                    updates[event.event_id] = attrs.accepted_request
                elif field == "workflow_execution_update_completed_event_attributes":
                    accepted = updates.pop(attrs.accepted_event_id, None)
                    require(accepted is not None, "update completion has no acceptance")
                    require(
                        bool(accepted.meta.update_id)
                        and attrs.meta.update_id == accepted.meta.update_id,
                        "update completion identity differs",
                    )
                    if accepted.input.name == "deliver_cancel":
                        delivery = await self._decode(accepted.input.args.payloads, CancelDelivery)
                        require(attrs.outcome.HasField("success"), "cancel update failed")
                        ack = await self._decode(attrs.outcome.success.payloads, CancelAck)
                        require(
                            delivery.command_id == cancel_command_id
                            and delivery.idempotency_issuer == cancel_issuer
                            and delivery.execution_epoch == target.execution_epoch
                            and delivery.execution_generation == target.execution_generation
                            and ack.command_id == cancel_command_id
                            and ack.status in {"delivered", "duplicate"},
                            "cancel delivery is stale or differs",
                        )
                        delivered = True
            require(not updates and delivered, "completed exact cancel delivery required")
            require(
                set(children) == closed_children and operation_id in children.values(),
                "active or missing exact operation child",
            )
            require(
                set(scheduled) - ended == {scheduled_event_id}
                and scheduled_event_id not in started,
                "result activity must be sole unresolved activity without recorded start",
            )
            activity = scheduled[scheduled_event_id]
            require(
                activity.activity_id == activity_id
                and activity.activity_type.name == "stagegraph.decide_result"
                and activity.task_queue.name == task_queue,
                "scheduled result activity pins differ",
            )
            request = await self._decode(activity.input.payloads, StageGraphResultActivityRequest)
            observation = request.observation
            checks = {
                "request_scope": request.request_scope == run.request_scope,
                "run_id": request.run_id == run.run_id,
                "semantic_identity": observation.identity.semantic_key == semantic_attempt_key,
                "result_generation": observation.identity.execution_generation
                == target.execution_generation,
                "operation_generation": operation.execution_generation
                == target.execution_generation,
                "family_epoch": family.execution_epoch == target.execution_epoch,
                "admission_projection": request.projection.digest == expected_family_digest,
                "request_blueprint": request.blueprint == family.blueprint,
                "blueprint_digest": sha256_digest(
                    StageGraphBlueprint.model_validate(family.blueprint)
                )
                == family.blueprint_digest,
                "operation_configuration": family.effective_configuration_digest
                == operation.operation.effective_configuration_digest,
                "run_configuration": family.effective_configuration_digest
                == run.effective_configuration_digest,
                "failed_disposition": observation.operation_disposition == "failed",
                "child_closed": observation.child_closed_or_quiesced,
            }
            require(
                all(checks.values()),
                "scheduled result input differs: "
                + ",".join(key for key, matches in checks.items() if not matches),
            )
            after = await latest.describe(rpc_timeout=timedelta(seconds=5))
            require(
                after.run_id == before.run_id
                and after.status == before.status
                and after.raw_description.workflow_execution_info.history_length == len(events)
                and after.raw_description.pending_activities == pending,
                "pending family frontier advanced",
            )
            pinned = PendingFamilyResult(
                operation_temporal_run_id,
                family_temporal_run_id,
                scheduled_event_id,
                activity_id,
                task_queue,
                request,
                activity_attempt=expected_activity_attempt,
            )
            return TerminalWorkflowInputs(
                operation,
                family,
                operation_temporal_run_id,
                family_temporal_run_id,
                pending_family_result=pinned,
            )

    async def _decode(self, payloads: Sequence[Payload], hint: type[T]) -> T:
        values = await self._client.data_converter.decode(payloads, [hint])
        require(
            len(values) == 1 and isinstance(values[0], hint), "pending history typed input differs"
        )
        return cast(T, values[0])
