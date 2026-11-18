"""Builders, constants and fakes that other test files import.

Moved from tests/unit/operations/test_operation_cancellation.py.
"""

from __future__ import annotations

from typing import Any

from mission_control.application.execution.operations.journaled_operation_execution import (
    _effect_claim_id,
)
from mission_control.application.execution.operations.operation_execution import (
    bind_operation_execution_request,
)
from mission_control.domain.execution.contracts import OperationExecutionRequest
from tests.fixtures.checkpoint_recovery import RecoveryHarness


def _settlements(harness: RecoveryHarness, request: OperationExecutionRequest) -> list[Any]:
    claim_id = _effect_claim_id(bind_operation_execution_request(request))
    return [item for key, item in harness.journal.settlements.items() if key == claim_id]


async def _liability(
    harness: RecoveryHarness, request: OperationExecutionRequest
) -> dict[str, Any]:
    """The unit's run-control liability after settlement: reservation, effect, evidence."""

    binding = bind_operation_execution_request(request)
    budget = await harness.run_control.get_budget("tenant-1", harness.run_id)
    effects = await harness.run_control.get_effects("tenant-1", harness.run_id)
    run = await harness.run_control.get_run("tenant-1", harness.run_id)
    claim = effects.claims.get(_effect_claim_id(binding))
    return {
        "reservation_open": request.budget_reservation_id in budget.reservations,
        "pending_settlement": dict(budget.pending_settlement),
        "effect": claim.disposition.value if claim is not None else None,
        "effect_settled": claim is not None and claim.settlement is not None,
        "evidence": [
            item.settlement_id
            for item in run.accepted_operation_settlement_evidence
            if item.accepted_by_authority_ref == binding.binding_id
        ],
        "consumed": dict(budget.consumed),
    }
