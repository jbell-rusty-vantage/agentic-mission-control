"""Builders, constants and fakes that other test files import.

Moved from tests/unit/operations/test_rrm_009_cancellation_composition.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def _claim(effect_id: str, kind: str, operation_ref: str, *, settled: bool) -> Any:
    from mission_control.domain.policies.contracts import (
        ConsequentialEffectClaim,
        EffectDisposition,
        EffectSettlement,
        EffectSettlementOutcome,
    )

    at = datetime(2026, 10, 2, tzinfo=UTC)
    return ConsequentialEffectClaim(
        effect_id=effect_id,
        run_id="run-1",
        effect_kind=kind,
        operation_ref=operation_ref,
        provider_idempotency_key=f"key:{effect_id}",
        reservation_id="reservation",
        disposition=EffectDisposition.CANCELLED if settled else EffectDisposition.CLAIMED,
        claimed_at=at,
        settlement=(
            EffectSettlement(
                settlement_id=f"settlement:{effect_id}",
                observation_id=f"observation:{effect_id}",
                outcome=EffectSettlementOutcome.CANCELLED,
                usage_settlement_ref=f"usage:{effect_id}",
                settled_at=at,
            )
            if settled
            else None
        ),
    )
