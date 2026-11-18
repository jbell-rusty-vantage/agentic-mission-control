"""Builders, constants and fakes that other test files import.

Moved from tests/unit/orchestration/test_stagegraph_v2.py.
"""

from __future__ import annotations

from mission_control.domain.authoring.contracts import AllowedOperationVariant, StageOperationSlot


def operation_slot(slot_id: str = "execute", *, priority: int = 0) -> StageOperationSlot:
    return StageOperationSlot(
        operation_slot_id=slot_id,
        priority=priority,
        reservation={"tokens.total": 1},
        allowed_variants=(
            AllowedOperationVariant(
                operation_variant_id="default",
                operation_contract_ref=f"operation:{slot_id}@1",
            ),
        ),
    )
