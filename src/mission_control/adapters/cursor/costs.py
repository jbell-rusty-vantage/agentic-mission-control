"""Bounded Cursor billed-cost reconciliation over the existing pending usage journal."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from mission_control.domain.execution.cursor_costs import (
    COST_DIMENSION,
    CostReadResult,
    CostRequest,
    CostState,
    NativeBillingRun,
)


@dataclass(frozen=True)
class CostContext:
    binding: Any
    claim: Any
    settlement: Any
    pending_micros: int
    settled: bool
    native_runs: tuple[NativeBillingRun, ...]
    attributable: bool
    settled_micros: int | None = None
    initial_recorded_micros: int = 0


class CostRepository(Protocol):
    async def context(self, request: CostRequest) -> CostContext: ...
    async def observation(self, request: CostRequest, read_no: int) -> CostReadResult | None: ...
    async def record(
        self, request: CostRequest, read_no: int, result: CostReadResult
    ) -> CostReadResult: ...


class CursorCostReconciler:
    def __init__(
        self,
        repository: CostRepository,
        reader: Callable[[str, str, str], Awaitable[int | None]],
        coordinator: Any,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self._repository, self._reader, self._coordinator, self._clock = (
            repository,
            reader,
            coordinator,
            clock,
        )

    async def observe(self, request: CostRequest, read_no: int) -> CostReadResult:
        if not 0 <= read_no <= 2:
            raise ValueError("Cursor cost reconciliation permits exactly three reads")
        context = await self._repository.context(request)
        binding = context.binding
        if (
            binding.request_scope != request.request_scope
            or binding.binding_id != request.binding_id
        ):
            raise ValueError("Cursor cost reconciliation crosses immutable binding scope")
        prior = await self._repository.observation(request, read_no)
        native_runs = tuple(
            NativeBillingRun(agent_id=agent, run_id=run)
            for agent, run in sorted({(r.agent_id, r.run_id) for r in context.native_runs})
        )
        if prior is not None and prior.native_runs != native_runs:
            raise ValueError("native billing identity set changed during cost reconciliation")
        if prior is None:
            costs = []
            read_failed = False
            if context.attributable and context.native_runs and not context.settled:
                for run in native_runs:
                    try:
                        cost = await self._reader(binding.lane_profile, run.agent_id, run.run_id)
                    except Exception:
                        # Provider bodies and credential-bearing URLs never enter receipts.
                        cost = None
                        read_failed = True
                    if cost is not None and (
                        isinstance(cost, bool) or not isinstance(cost, int) or cost < 0
                    ):
                        raise ValueError("invalid Cursor charged amount")
                    costs.append(cost)
            total = (
                sum(cost for cost in costs if cost is not None)
                if costs and all(cost is not None for cost in costs)
                else None
            )
            if context.settled:
                total = context.settled_micros
            state: CostState = (
                "settled"
                if context.settled
                else "unattributable"
                if not context.attributable or not context.native_runs
                else "unknown"
                if total is None
                else "conflict"
                if total < context.initial_recorded_micros
                else "overage"
                if total - context.initial_recorded_micros > context.pending_micros
                else "settled"
            )
            prior = await self._repository.record(
                request,
                read_no,
                CostReadResult(
                    state=state,
                    observed_micros=total,
                    pending_micros=context.pending_micros,
                    native_runs=native_runs,
                    native_costs_micros=tuple(costs),
                    initial_recorded_micros=context.initial_recorded_micros,
                    source=(
                        "cursor.charged_cents.read_failed"
                        if read_failed
                        else "cursor.charged_cents"
                    ),
                    requested_model=binding.model_policy.model,
                    recorded_at=self._clock().isoformat(),
                ),
            )
        if context.settled:
            return prior.model_copy(
                update={
                    "state": "settled",
                    "observed_micros": context.settled_micros,
                    "pending_micros": 0,
                }
            )
        if prior.state == "settled" and prior.observed_micros is not None:
            delta = prior.observed_micros - prior.initial_recorded_micros
            await self._coordinator.settle_pending_usage(
                binding,
                context.claim,
                context.settlement,
                actual_amounts={COST_DIMENSION: delta},
                release_amounts={COST_DIMENSION: prior.pending_micros - delta},
                reconciled_at=datetime.fromisoformat(prior.recorded_at),
            )
        return prior
