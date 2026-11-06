"""Bounded describe/history-only evidence of exact closed workflow trees/chains."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from temporalio.api.history.v1 import HistoryEvent
from temporalio.client import Client

from mission_control.application.recovery.closed_workflow import (
    ClosedExecution,
    ClosedWorkflowEvidence,
)
from mission_control.contracts.contracts import MissionControlRejected
from mission_control.contracts.identities import mission_operation_id, mission_root_id
from mission_control.domain.execution.contracts import OperationWorkflowRequest
from mission_control.domain.policies.contracts import RunProjection
from mission_control.domain.programs.contracts import BellLabsRunInput, StageGraphRunInput

TERMINAL = frozenset({"COMPLETED", "FAILED", "CANCELED", "TERMINATED", "TIMED_OUT"})


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise MissionControlRejected("recovery_workflow_evidence", reason)


class TemporalClosedWorkflowObserver:
    def __init__(self, client: Client) -> None:
        self._client = client

    async def observe(
        self, run: RunProjection, producers: tuple[str, ...]
    ) -> ClosedWorkflowEvidence:
        try:
            return await self._observe(run, producers)
        except MissionControlRejected:
            raise
        except Exception:
            raise MissionControlRejected(
                "unavailable", "exact closed workflow history is unavailable"
            ) from None

    async def _observe(
        self, run: RunProjection, producers: tuple[str, ...]
    ) -> ClosedWorkflowEvidence:
        target = run.execution_target
        require(
            target is not None and bool(target.root_workflow_id), "an exact root target is required"
        )
        assert target is not None and target.root_workflow_id is not None
        require(
            target.root_workflow_id == mission_root_id(run.request_scope, run.run_id),
            "root scope identity differs",
        )
        pending: list[tuple[str, str | None]] = [
            (target.root_workflow_id, None),
            (target.family_workflow_id, None),
        ]
        pending.extend((workflow_id, None) for workflow_id in producers)
        visited: set[tuple[str, str]] = set()
        latest: dict[str, str] = {}
        executions: list[ClosedExecution] = []
        while pending:
            workflow_id, exact_id = pending.pop()
            require(
                len(visited) <= 32 and len(pending) <= 64,
                "workflow evidence tree exceeds its finite bound",
            )
            if workflow_id not in latest:
                description = await self._client.get_workflow_handle(workflow_id).describe(
                    rpc_timeout=timedelta(seconds=5)
                )
                require(
                    description.status is not None and description.status.name in TERMINAL,
                    "a latest workflow execution is active or continued",
                )
                latest[workflow_id] = description.run_id
                pending.append((workflow_id, description.run_id))
            exact_id = exact_id or latest[workflow_id]
            pair = (workflow_id, exact_id)
            if pair in visited:
                continue
            require(len(visited) < 32, "workflow evidence tree exceeds its finite bound")
            visited.add(pair)
            handle = self._client.get_workflow_handle(workflow_id, run_id=exact_id)
            description = await handle.describe(rpc_timeout=timedelta(seconds=5))
            require(
                description.run_id == exact_id
                and description.status is not None
                and description.status.name in TERMINAL | {"CONTINUED_AS_NEW"},
                "exact workflow is not closed",
            )
            events: list[HistoryEvent] = []
            total_bytes = 0
            async for event in handle.fetch_history_events(
                page_size=100, rpc_timeout=timedelta(seconds=5)
            ):
                total_bytes += event.ByteSize()
                require(
                    len(events) < 4096 and total_bytes <= 8_000_000,
                    "workflow history exceeds its finite bound",
                )
                events.append(event)
            require(
                bool(events) and events[0].HasField("workflow_execution_started_event_attributes"),
                "workflow history has no authoritative input",
            )
            require(
                [event.event_id for event in events] == list(range(1, len(events) + 1)),
                "workflow history has a gap or truncated prefix",
            )
            first = events[0].workflow_execution_started_event_attributes
            await self._validate_input(run, workflow_id, first)
            if first.continued_execution_run_id:
                pending.append((workflow_id, first.continued_execution_run_id))
            initiated: set[int] = set()
            resolved_starts: set[int] = set()
            activities: set[int] = set()
            closed_activities: set[int] = set()
            for event in events:
                if event.HasField("start_child_workflow_execution_initiated_event_attributes"):
                    initiated.add(event.event_id)
                elif event.HasField("child_workflow_execution_started_event_attributes"):
                    attributes = event.child_workflow_execution_started_event_attributes
                    resolved_starts.add(attributes.initiated_event_id)
                    pending.append(
                        (
                            attributes.workflow_execution.workflow_id,
                            attributes.workflow_execution.run_id,
                        )
                    )
                elif event.HasField("start_child_workflow_execution_failed_event_attributes"):
                    resolved_starts.add(
                        event.start_child_workflow_execution_failed_event_attributes.initiated_event_id
                    )
                elif event.HasField("activity_task_scheduled_event_attributes"):
                    activities.add(event.event_id)
                for field in (
                    "activity_task_completed_event_attributes",
                    "activity_task_failed_event_attributes",
                    "activity_task_timed_out_event_attributes",
                    "activity_task_canceled_event_attributes",
                ):
                    if event.WhichOneof("attributes") == field:
                        closed_activities.add(getattr(event, field).scheduled_event_id)
                for field in (
                    "workflow_execution_continued_as_new_event_attributes",
                    "workflow_execution_failed_event_attributes",
                    "workflow_execution_completed_event_attributes",
                ):
                    if event.WhichOneof("attributes") == field:
                        successor = getattr(getattr(event, field), "new_execution_run_id", "")
                        if successor:
                            pending.append((workflow_id, successor))
                # A request to a non-child external workflow can conceal an adopted
                # producer outside this tree. Its authority requires a different repair.
                for field in (
                    "signal_external_workflow_execution_initiated_event_attributes",
                    "request_cancel_external_workflow_execution_initiated_event_attributes",
                ):
                    require(
                        event.WhichOneof("attributes") != field,
                        "external workflow authority requires separate reconciliation",
                    )
            require(initiated <= resolved_starts, "a child start remains ambiguous")
            require(activities <= closed_activities, "an activity remains unresolved")
            require(
                any(
                    events[-1].WhichOneof("attributes") == field
                    for field in (
                        "workflow_execution_completed_event_attributes",
                        "workflow_execution_failed_event_attributes",
                        "workflow_execution_canceled_event_attributes",
                        "workflow_execution_terminated_event_attributes",
                        "workflow_execution_timed_out_event_attributes",
                        "workflow_execution_continued_as_new_event_attributes",
                    )
                ),
                "history has no terminal closing event",
            )
            assert description.status is not None
            closing_field = {
                "COMPLETED": "workflow_execution_completed_event_attributes",
                "FAILED": "workflow_execution_failed_event_attributes",
                "CANCELED": "workflow_execution_canceled_event_attributes",
                "TERMINATED": "workflow_execution_terminated_event_attributes",
                "TIMED_OUT": "workflow_execution_timed_out_event_attributes",
                "CONTINUED_AS_NEW": "workflow_execution_continued_as_new_event_attributes",
            }[description.status.name]
            require(
                events[-1].WhichOneof("attributes") == closing_field,
                "history closing event differs from exact execution status",
            )
            if description.status.name == "CONTINUED_AS_NEW":
                require(
                    bool(
                        events[
                            -1
                        ].workflow_execution_continued_as_new_event_attributes.new_execution_run_id
                    ),
                    "continued execution has no exact successor identity",
                )
            h = hashlib.sha256()
            for event in events:
                raw = event.SerializeToString(deterministic=True)
                h.update(len(raw).to_bytes(8, "big"))
                h.update(raw)
            assert description.status is not None
            executions.append(
                ClosedExecution(
                    workflow_id,
                    exact_id,
                    description.status.name,
                    events[-1].event_id,
                    "sha256:" + h.hexdigest(),
                )
            )
        executions = [
            replace(item, latest=latest[item.workflow_id] == item.temporal_run_id)
            for item in executions
        ]
        evidence = ClosedWorkflowEvidence(
            run.request_scope,
            run.run_id,
            target.execution_epoch,
            target.execution_generation,
            datetime.now(UTC),
            tuple(sorted(executions, key=lambda item: (item.workflow_id, item.temporal_run_id))),
        )
        await self.recheck(evidence)
        return evidence

    async def _validate_input(self, run: RunProjection, workflow_id: str, attributes: Any) -> None:
        target = run.execution_target
        assert target is not None
        kind = attributes.workflow_type.name
        hints: list[type] = [
            {
                "mc.mission_run.v1": BellLabsRunInput,
                "belllabs.stagegraph": StageGraphRunInput,
                "mc.operation.v1": OperationWorkflowRequest,
            }.get(kind, object)
        ]
        require(
            hints[0] is not object,
            "unknown descendant workflow type requires separate reconciliation",
        )
        values = await self._client.data_converter.decode(attributes.input.payloads, hints)
        require(len(values) == 1, "workflow input is not exact")
        value = values[0]
        if isinstance(value, BellLabsRunInput):
            value.validate_mission_binding()
            require(
                not value.continuity.active_operation_ids
                and not value.continuity.linked_run_ids
                and not value.continuity.pending_message_ids,
                "carried external producer or pending messages require separate reconciliation",
            )
            require(
                value.workflow_type_digest == run.workflow_type_ref.digest,
                "root workflow type differs",
            )
            require(
                workflow_id == target.root_workflow_id
                and value.family_workflow_id == target.family_workflow_id
                and value.continuity.execution_epoch == target.execution_epoch
                and value.continuity.execution_generation == target.execution_generation,
                "root generation differs",
            )
            bound_run = value.run_id
        elif isinstance(value, StageGraphRunInput):
            require(
                value.workflow_type_digest == run.workflow_type_ref.digest,
                "family workflow type differs",
            )
            require(
                workflow_id == target.family_workflow_id
                and value.execution_epoch == target.execution_epoch,
                "family identity differs",
            )
            bound_run = value.run_id
        elif isinstance(value, OperationWorkflowRequest):
            require(
                not value.active_async_child_ids,
                "carried async-child authority requires separate reconciliation",
            )
            operation = value.operation
            require(
                workflow_id
                == mission_operation_id(run.request_scope, run.run_id, value.semantic_attempt_id)
                and value.execution_generation == target.execution_generation
                and operation.runtime_unit is not None
                and operation.runtime_unit.execution_epoch == target.execution_epoch,
                "operation generation differs",
            )
            value = operation
            bound_run = operation.identity.run_id
        else:
            raise MissionControlRejected(
                "recovery_workflow_evidence", "workflow input type differs"
            )
        require(
            value.request_scope == run.request_scope
            and bound_run == run.run_id
            and value.effective_configuration_digest == run.effective_configuration_digest,
            "workflow scope/run/binding differs",
        )

    async def recheck(self, evidence: ClosedWorkflowEvidence) -> None:
        try:
            for execution in evidence.executions:
                if not execution.latest:
                    continue
                latest = await self._client.get_workflow_handle(execution.workflow_id).describe(
                    rpc_timeout=timedelta(seconds=5)
                )
                require(
                    latest.run_id == execution.temporal_run_id
                    and latest.status is not None
                    and latest.status.name in TERMINAL,
                    "latest execution changed or reopened",
                )
        except MissionControlRejected:
            raise
        except Exception:
            raise MissionControlRejected(
                "unavailable", "closed workflow execution recheck is unavailable"
            ) from None
