"""Cursor cost evidence in existing scoped immutable runtime documents and journals."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from uuid import UUID

import asyncpg

from mission_control.adapters.cursor.costs import (
    CostContext,
)
from mission_control.adapters.postgres.documents import PostgresDocumentStore
from mission_control.adapters.postgres.frames.repository import PostgresFrameRepository
from mission_control.adapters.postgres.operations.operation_binding_repository import (
    PostgresOperationBindingRepository,
)
from mission_control.adapters.postgres.operations.operation_journal import (
    PostgresAtomicOperationJournalRepository,
)
from mission_control.application.execution.operations.journaled_operation_execution import (
    operation_effect_claim_id,
)
from mission_control.domain.execution.contracts import (
    OperationExecutionBinding,
    OperationSettlement,
)
from mission_control.domain.execution.cursor_costs import (
    COST_DIMENSION,
    CostReadResult,
    CostRequest,
    NativeBillingRun,
)
from mission_control.domain.execution.lanes import CursorExecutionBinding
from mission_control.domain.policies.errors import IdempotencyConflict

MAX_BILLING_FRAMES = 5_000


class PostgresCursorCosts:
    def __init__(
        self,
        pool: asyncpg.Pool,
        settlement_reader: Callable[
            [OperationExecutionBinding], Awaitable[OperationSettlement | None]
        ],
    ) -> None:
        self._pool = pool
        self._bindings = PostgresOperationBindingRepository(pool)
        self._journal = PostgresAtomicOperationJournalRepository(pool)
        self._documents = PostgresDocumentStore(pool)
        self._frames = PostgresFrameRepository(pool)
        self._settlement_reader = settlement_reader

    async def context(self, request: CostRequest) -> CostContext:
        binding = await self._bindings.get_binding_by_id(
            request.binding_id, request_scope=request.request_scope
        )
        if binding is None or binding.lane_profile not in {"cursor_cloud", "cursor_local"}:
            raise ValueError("cost reconciliation requires the exact Cursor operation binding")
        settlement = await self._settlement_reader(binding)
        effect = operation_effect_claim_id(request.request_scope, binding.binding_id)
        claim = await self._journal.get_claim(request.request_scope, effect)
        journal = await self._journal.get_settlement(request.request_scope, effect)
        if (
            settlement is None
            or claim is None
            or journal is None
            or journal.settlement_id != settlement.settlement_id
        ):
            raise ValueError(
                "cost reconciliation requires the persisted operation settlement journal"
            )
        if journal.pending_external_usage.keys() - {COST_DIMENSION}:
            raise ValueError(
                "Cursor cost reconciliation cannot settle unrelated pending dimensions"
            )
        if (
            journal.settlement_revision < 2
            and journal.pending_external_usage.get(COST_DIMENSION, 0) <= 0
        ):
            raise ValueError("Cursor unknown currency has no pending reservation")
        unit_key = binding.runtime_unit.unit_key if binding.runtime_unit else binding.operation_id
        runs: tuple[NativeBillingRun, ...] = ()
        attributable = False
        try:
            cursor = CursorExecutionBinding.carried_by(binding)
            if cursor is None:
                raise ValueError("Cursor provider binding is unavailable")
            frames = await self._frames.frames_for_semantic_attempt(
                request.request_scope,
                binding.run_id,
                unit_key,
                binding.semantic_attempt_key,
                cursor.binding_digest,
                binding.lane_profile,
                limit=MAX_BILLING_FRAMES,
            )
        except ValueError:
            # Missing, drifted or truncated history is not a partial billing total.
            # Database failures still propagate so the activity can retry.
            frames = ()
        if frames:
            top_level = tuple(
                frame
                for frame in frames
                if frame.subordinate_ref is None and frame.native_turn_ref is not None
            )
            observed = {(frame.harness_execution_id, frame.generation) for frame in frames}
            identified = {(frame.harness_execution_id, frame.generation) for frame in top_level}
            sessions = {
                (frame.harness_execution_id, frame.generation, frame.native_session_ref)
                for frame in frames
                if frame.subordinate_ref is None
            }
            identified_sessions = {
                (frame.harness_execution_id, frame.generation, frame.native_session_ref)
                for frame in top_level
            }
            # A predecessor with only session/subordinate observations cannot be
            # silently omitted just because a later generation has a billable run.
            attributable = observed == identified and sessions == identified_sessions
            if attributable:
                runs = tuple(
                    NativeBillingRun(agent_id=agent, run_id=run)
                    for agent, run in sorted(
                        {
                            (frame.native_session_ref, frame.native_turn_ref)
                            for frame in top_level
                            if frame.native_turn_ref is not None
                        }
                    )
                )
        if binding.lane_profile == "cursor_local":
            try:
                for run in runs:
                    UUID(run.run_id)
            except ValueError:
                attributable = False  # Client-minted labels cannot be turned into billing UUIDs.
        return CostContext(
            binding,
            claim,
            settlement,
            journal.pending_external_usage.get(COST_DIMENSION, 0),
            journal.settlement_revision >= 2,
            runs,
            attributable,
            journal.usage.get(COST_DIMENSION) if journal.settlement_revision >= 2 else None,
            settlement.usage.amounts.get(COST_DIMENSION, 0),
        )

    async def observation(self, request: CostRequest, read_no: int) -> CostReadResult | None:
        document = await self._documents.get(
            request_scope=request.request_scope,
            contract="mc.cursor-cost-observation/1",
            identity=f"{request.binding_id}:{read_no}",
        )
        return CostReadResult.model_validate(document.payload) if document else None

    async def record(
        self, request: CostRequest, read_no: int, result: CostReadResult
    ) -> CostReadResult:
        try:
            document = await self._documents.put(
                request_scope=request.request_scope,
                contract="mc.cursor-cost-observation/1",
                identity=f"{request.binding_id}:{read_no}",
                payload=result.model_dump(mode="json"),
                recorded_at=datetime.fromisoformat(result.recorded_at),
            )
        except IdempotencyConflict:
            # Overlapping retry workers use the first immutable observed fact.
            prior = await self.observation(request, read_no)
            if prior is None or prior.native_runs != result.native_runs:
                raise
            return prior
        return CostReadResult.model_validate(document.payload)
