"""In-memory use decisions for unit proofs only (integrator decision 2026-10-25; WI-03).

The agent names a decision handle; the gateway resolves the exact use from a store. Ordinary
launch composes the durable ``PostgresUseDecisionStore`` (release 1.7.0, migration 0059) that the
trusted knowledge bridge records into; this process-memory double is never composed.
"""

from __future__ import annotations

from mission_control.application.ports.knowledge import RecordedUseDecision


class InMemoryUseDecisionStore:
    """Use decisions by (request scope, handle)."""

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], RecordedUseDecision] = {}

    async def record(
        self,
        scope: str,
        decision: RecordedUseDecision,
        *,
        actor_ref: str = "test",
        at: object = None,
    ) -> RecordedUseDecision:
        existing = self._rows.setdefault((scope, decision.handle), decision)
        if existing != decision:
            raise ValueError(f"decision handle {decision.handle!r} already names another decision")
        return existing

    async def get(self, scope: str, handle: str) -> RecordedUseDecision | None:
        return self._rows.get((scope, handle))

    async def for_invocation(
        self, scope: str, invocation_ref: str
    ) -> tuple[RecordedUseDecision, ...]:
        return tuple(
            row
            for (stored, _), row in sorted(self._rows.items())
            if stored == scope and row.invocation_ref == invocation_ref
        )


__all__ = ["InMemoryUseDecisionStore"]
