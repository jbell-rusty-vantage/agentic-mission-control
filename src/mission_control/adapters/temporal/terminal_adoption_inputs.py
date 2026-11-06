"""Bounded immutable start-input retrieval; never rematerialize an admitted operation."""

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from typing import TypeVar

from temporalio.client import Client

from mission_control.adapters.temporal.closed_workflow import (
    TERMINAL,
    TemporalClosedWorkflowObserver,
    require,
)
from mission_control.application.recovery.terminal_evidence_adoption import PendingFamilyResult
from mission_control.contracts.identities import mission_operation_id
from mission_control.domain.execution.contracts import OperationWorkflowRequest
from mission_control.domain.policies.contracts import RunProjection
from mission_control.domain.programs.contracts import StageGraphRunInput

T = TypeVar("T", OperationWorkflowRequest, StageGraphRunInput)


@dataclass(frozen=True)
class TerminalWorkflowInputs:
    operation: OperationWorkflowRequest
    family: StageGraphRunInput
    operation_temporal_run_id: str
    family_temporal_run_id: str
    pending_family_result: PendingFamilyResult | None = None


class TemporalTerminalInputReader:
    def __init__(self, client: Client) -> None:
        self._client = client
        self._validator = TemporalClosedWorkflowObserver(client)

    async def read(
        self,
        run: RunProjection,
        *,
        semantic_attempt_key: str,
        operation_temporal_run_id: str,
        family_temporal_run_id: str,
    ) -> TerminalWorkflowInputs:
        async with asyncio.timeout(30):
            return await self._read(
                run,
                semantic_attempt_key=semantic_attempt_key,
                operation_temporal_run_id=operation_temporal_run_id,
                family_temporal_run_id=family_temporal_run_id,
            )

    async def _read(
        self,
        run: RunProjection,
        *,
        semantic_attempt_key: str,
        operation_temporal_run_id: str,
        family_temporal_run_id: str,
    ) -> TerminalWorkflowInputs:
        target = run.execution_target
        require(
            target is not None and target.family == "StageGraph", "exact StageGraph target required"
        )
        assert target is not None
        operation = await self._one(
            run,
            mission_operation_id(run.request_scope, run.run_id, semantic_attempt_key),
            operation_temporal_run_id,
            OperationWorkflowRequest,
        )
        family = await self._one(
            run, target.family_workflow_id, family_temporal_run_id, StageGraphRunInput
        )
        require(
            operation.semantic_attempt_id == semantic_attempt_key,
            "operation input semantic identity differs",
        )
        return TerminalWorkflowInputs(
            operation, family, operation_temporal_run_id, family_temporal_run_id
        )

    async def _one(self, run: RunProjection, workflow_id: str, exact_id: str, hint: type[T]) -> T:
        require(bool(exact_id), "pinned Temporal execution is required")
        latest = self._client.get_workflow_handle(workflow_id)
        description = await latest.describe(rpc_timeout=timedelta(seconds=5))
        require(
            description.run_id == exact_id
            and description.status is not None
            and description.status.name in TERMINAL,
            "latest workflow differs or is active",
        )
        handle = self._client.get_workflow_handle(workflow_id, run_id=exact_id)
        first = None
        async for event in handle.fetch_history_events(
            page_size=1, rpc_timeout=timedelta(seconds=5)
        ):
            require(
                event.event_id == 1
                and event.ByteSize() <= 4_000_000
                and event.HasField("workflow_execution_started_event_attributes"),
                "start input bound or identity differs",
            )
            first = event.workflow_execution_started_event_attributes
            break
        require(first is not None, "authoritative workflow start input is absent")
        assert first is not None
        await self._validator._validate_input(run, workflow_id, first)
        values = await self._client.data_converter.decode(first.input.payloads, [hint])
        require(len(values) == 1 and isinstance(values[0], hint), "workflow input type differs")
        after = await latest.describe(rpc_timeout=timedelta(seconds=5))
        require(
            after.run_id == exact_id and after.status == description.status,
            "workflow changed during input read",
        )
        return values[0]
