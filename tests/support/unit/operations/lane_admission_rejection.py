"""Builders, constants and fakes that other test files import.

Moved from tests/unit/operations/test_lane_admission_rejection.py.
"""

from __future__ import annotations

from typing import Any

from mission_control.domain.execution.journal import OperationClaimResult
from mission_control.domain.policies.errors import IdempotencyConflict


class RejectionJournal:
    def __init__(self) -> None:
        self.claims: dict[str, Any] = {}
        self.settlements: dict[str, Any] = {}
        self.crash_claim = False
        self.crash_settlement = False

    async def commit(self, mutation: Any) -> OperationClaimResult:
        if mutation.settlement is None and self.crash_claim:
            self.crash_claim = False
            raise RuntimeError("lost claim journal write")
        if mutation.settlement is not None and self.crash_settlement:
            self.crash_settlement = False
            raise RuntimeError("lost settlement journal write")
        claim = mutation.claim
        prior = self.claims.get(claim.effect_claim_id)
        if mutation.settlement is not None:
            previous = self.settlements.get(claim.effect_claim_id)
            if previous is not None and previous != mutation.settlement:
                raise IdempotencyConflict("rejection settlement changed on replay")
            self.settlements[claim.effect_claim_id] = mutation.settlement
        self.claims[claim.effect_claim_id] = prior or claim
        return OperationClaimResult(
            status="existing" if prior else "acquired", claim=prior or claim, reason="recorded"
        )

    async def get_settlement(self, request_scope: str, effect_claim_id: str) -> Any:
        del request_scope
        return self.settlements.get(effect_claim_id)
