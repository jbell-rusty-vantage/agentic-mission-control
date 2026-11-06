"""Explicit budget-gate routing; legacy histories never schedule this activity."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import suppress
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from mission_control.domain.execution.budget_controls import (
        BudgetControlRecord,
        LaneBudgetControlRequest,
    )
    from mission_control.domain.execution.contracts import OperationWorkflowRequest
    from mission_control.domain.programs.contracts import BoundaryCommandDelivery

BUDGET_GATE_PATCH = "run2-managed-budget-gate-v1"


def declares_budget_gate(request: OperationWorkflowRequest) -> bool:
    """Whether the attempt's lane applies a budget gate natively (its dispatch says so)."""

    dispatch = request.operation.lane_dispatch
    return dispatch is not None and dispatch.declares("budget_gate")


def budget_gate(delivery: BoundaryCommandDelivery) -> bool:
    decision = delivery.payload.get("decision")
    return (
        delivery.kind in {"pause", "resume"}
        and isinstance(decision, dict)
        and isinstance(decision.get("budget_gate"), dict)
    )


async def route_budget_gate(
    delivery: BoundaryCommandDelivery,
    requests: Sequence[OperationWorkflowRequest],
    cancelled: Callable[[], bool],
) -> tuple[str, list[dict]]:
    if not workflow.patched(BUDGET_GATE_PATCH) or not requests:
        return "not_applicable", []
    # The lane declares the gate on the operation's dispatch (OC-R3, `LaneDispatch.
    # boundary_controls`): deterministic workflow code reads that fact, never a lane name or
    # the registry.
    if not all(declares_budget_gate(item) for item in requests):
        return "not_applicable", []
    receipts: dict[str, BudgetControlRecord] = {}
    while not cancelled():
        for request in requests:
            prior = receipts.get(request.semantic_attempt_id)
            if prior is not None and prior.applied:
                continue
            payload = LaneBudgetControlRequest(
                operation=request.operation,
                generation=request.execution_generation,
                command_id=delivery.command_id,
                command_issuer=delivery.idempotency_issuer,
            )
            try:
                result = await workflow.execute_activity(
                    "lane.budget_control",
                    payload.model_dump(mode="json"),
                    task_queue=request.activity_task_queue,
                    result_type=dict,
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
            except ActivityError:
                # Refusal cannot silently become a boundary pause. An uncertain native
                # update remains in its durable journal and retains its liability.
                return "not_applicable", [r.model_dump(mode="json") for r in receipts.values()]
            record = BudgetControlRecord.model_validate(result)
            receipts[request.semantic_attempt_id] = record
            if (
                record.phase == "rejected"
                or record.reason == "budget_boundary_not_observed:terminal"
            ):
                return "not_applicable", [r.model_dump(mode="json") for r in receipts.values()]
        if all(record.applied for record in receipts.values()) and len(receipts) == len(requests):
            return "", [r.model_dump(mode="json") for r in receipts.values()]
        with suppress(TimeoutError):
            await workflow.wait_condition(cancelled, timeout=timedelta(seconds=1))
    return "superseded", [r.model_dump(mode="json") for r in receipts.values()]
