"""The one test fake of the atomic operation journal repository.

`MemoryOperationJournal` holds one claim and one settlement per effect, in public dicts a test
reads (`claims`, `settlements`, `technical_attempts`), and can lose the next claim or settlement
write (`crash_claim`, `crash_settlement`) as a worker crash would. It replaces
`tests/fixtures/checkpoint_recovery.MemoryOperationJournal` and the lane-admission
`RejectionJournal`.

It is not the src `InMemoryAtomicOperationJournalRepository`: that repository validates each
mutation, compares run versions and authority proofs it must be seeded with (`seed_run`,
`seed_authority_proof`), keeps its rows private and has no `record_reconciliation_applied`
receipt seam, so the run-control and lane tests that only need "one claim, one settlement per
effect" would have to seed a full run to use it.
"""

from __future__ import annotations

from typing import Any

from mission_control.application.execution.operations.operation_journal import (
    OperationJournalMutation,
)
from mission_control.domain.execution.journal import (
    OperationClaimResult,
    OperationEffectClaim,
    OperationJournalSettlement,
)
from mission_control.domain.policies.errors import IdempotencyConflict


class MemoryOperationJournal:
    """Atomic journal repository for unit tests: one claim and one settlement per effect."""

    def __init__(self) -> None:
        self.claims: dict[str, OperationEffectClaim] = {}
        self.settlements: dict[str, OperationJournalSettlement] = {}
        self.technical_attempts: dict[str, list[int]] = {}
        self.crash_claim = False
        self.crash_settlement = False

    async def record_reconciliation_applied(self, binding: Any, decision: Any) -> None:
        """RRM-007 receipt seam: the in-memory journal keeps no receipt ledger."""
        return

    async def commit(self, mutation: OperationJournalMutation) -> OperationClaimResult:
        if mutation.settlement is None and self.crash_claim:
            self.crash_claim = False
            raise RuntimeError("lost claim journal write")
        if mutation.settlement is not None and self.crash_settlement:
            self.crash_settlement = False
            raise RuntimeError("lost settlement journal write")
        claim_id = mutation.claim.effect_claim_id
        prior = self.claims.get(claim_id)
        if mutation.settlement is not None:
            existing = self.settlements.get(claim_id)
            if (
                existing is not None
                and existing.settlement_revision == mutation.settlement.settlement_revision
                and existing.settlement_digest != mutation.settlement.settlement_digest
            ):
                raise IdempotencyConflict("operation settlement replay conflicts")
            self.settlements[claim_id] = mutation.settlement
            self.claims.setdefault(claim_id, mutation.claim)
            if mutation.attempt is not None:
                self.technical_attempts.setdefault(claim_id, []).append(
                    mutation.attempt.technical_attempt
                )
            return OperationClaimResult(
                status="existing", claim=prior or mutation.claim, reason="settled"
            )
        if prior is not None:
            return OperationClaimResult(status="existing", claim=prior, reason="claim exists")
        self.claims[claim_id] = mutation.claim
        return OperationClaimResult(status="acquired", claim=mutation.claim, reason="acquired")

    async def get_claim(self, request_scope: str, effect_claim_id: str) -> OperationEffectClaim:
        del request_scope
        return self.claims[effect_claim_id]

    async def get_settlement(
        self, request_scope: str, effect_claim_id: str
    ) -> OperationJournalSettlement | None:
        del request_scope
        return self.settlements.get(effect_claim_id)


__all__ = ["MemoryOperationJournal"]
