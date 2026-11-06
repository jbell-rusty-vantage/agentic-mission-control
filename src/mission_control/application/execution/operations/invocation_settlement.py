"""The saved-result store port and the lane settlement hook (Sprint OC WI-04).

`OperationExecutionService` saves a completed provider result through
:class:`InvocationSettlementStore` **before** the lane's post-execution settlement runs, then
advances the record by compare-and-set after each settlement pass. The record is the durable
reconciliation state of that result: a retry, restart, continue-as-new or cancellation reads it
and settles the saved result; cognition is never dispatched again for it.

A lane that has post-execution work (assessment handoff, effect receipts, reviews) implements
:class:`SettlesInvocation`; a lane without it settles at once. The PostgreSQL store lives in
``adapters/postgres/operations/invocation_settlement.py`` (common component 1.7.0, migration
0058); :class:`InMemoryInvocationSettlementStore` keeps the same rules for unit proofs.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from mission_control.domain.execution.contracts import RuntimeInvocation
from mission_control.domain.execution.invocation_settlement import (
    InvocationSettlement,
    SettlementEventKind,
    SettlementOutcome,
)
from mission_control.domain.policies.errors import IdempotencyConflict

MAX_SAVED_RESULT_BYTES = 8 * 1024 * 1024


class SavedSettlementConflict(RuntimeError):
    """The record moved since it was read (another holder advanced it); re-read and retry."""


class StaleSettlementHolder(RuntimeError):
    """The writer's claim fence is no longer the unit generation's current fence (a takeover
    happened, even if the new holder has not written yet): it must stand down."""


class SavedResultTooLarge(ValueError):
    """The provider result exceeds the saved-result bound (8 MiB of canonical JSON)."""


def saved_result_size(record: InvocationSettlement) -> int:
    return len(
        json.dumps(
            record.saved_result.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    )


@dataclass(frozen=True)
class SettlementEvent:
    """One durable settlement event (`invocation_settlement_event`, append-only)."""

    settlement_id: str
    kind: SettlementEventKind
    sequence: int
    occurred_at: datetime
    detail: Mapping[str, Any]


class InvocationSettlementStore(Protocol):
    async def save(self, record: InvocationSettlement) -> InvocationSettlement:
        """Insert the saved result once; the same saved bytes return the existing record,
        different bytes for the same binding refuse (``IdempotencyConflict``)."""
        ...

    async def get(self, request_scope: str, binding_id: str) -> InvocationSettlement | None: ...

    async def advance(
        self, record: InvocationSettlement, *, expected_version: int
    ) -> InvocationSettlement:
        """Compare-and-set the successor state (``SavedSettlementConflict`` when it moved).

        In the same transaction the successor's ``claim_fence`` must still be the unit
        generation's current claim fence (``StaleSettlementHolder`` otherwise)."""
        ...

    async def record_event(self, record: InvocationSettlement, event: SettlementEvent) -> bool:
        """Append one durable settlement event once (same kind and sequence: no-op, False)."""
        ...


@runtime_checkable
class SettlesInvocation(Protocol):
    """A lane's post-execution settlement of a saved result (no cognition, no native write).

    ``fenced``: a cancellation fenced the result; no new evaluation may start, committed work
    is still reconciled. A pass that cannot run raises; the boundary records it as a wait.
    """

    async def settle_invocation(
        self, invocation: RuntimeInvocation, *, fenced: bool = False
    ) -> SettlementOutcome: ...


class InvocationSettler(Protocol):
    """One post-execution settlement capability a lane composes (the knowledge lane support,
    or a generic durable-wait double). ``applies`` selects it for an invocation."""

    def applies(self, invocation: RuntimeInvocation) -> bool: ...

    async def settle(
        self, invocation: RuntimeInvocation, *, fenced: bool = False
    ) -> SettlementOutcome: ...


UnitFenceReader = Callable[[str, str, int], int | None]


class InMemoryInvocationSettlementStore:
    """The store's rules without a database (unit proofs; shared by "workers" in a test).

    ``fences`` reads the unit generation's current claim fence (the in-memory lineage), so a
    stale holder is refused exactly as the PostgreSQL store refuses it."""

    def __init__(
        self,
        *,
        fences: UnitFenceReader | None = None,
        max_bytes: int = MAX_SAVED_RESULT_BYTES,
    ) -> None:
        self.records: dict[tuple[str, str], InvocationSettlement] = {}
        self.history: list[InvocationSettlement] = []
        self.events: list[SettlementEvent] = []
        self.fences = fences
        self._max_bytes = max_bytes
        self._lock = asyncio.Lock()

    async def save(self, record: InvocationSettlement) -> InvocationSettlement:
        key = (record.request_scope, record.binding_id)
        size = saved_result_size(record)
        if size > self._max_bytes:
            raise SavedResultTooLarge(f"saved result is {size} bytes, over the bound")
        async with self._lock:
            prior = self.records.get(key)
            if prior is not None:
                if prior.saved_result_digest != record.saved_result_digest:
                    raise IdempotencyConflict("the binding already saved another provider result")
                return deepcopy(prior)
            self.records[key] = record
            self.history.append(record)
            return deepcopy(record)

    async def get(self, request_scope: str, binding_id: str) -> InvocationSettlement | None:
        record = self.records.get((request_scope, binding_id))
        return None if record is None else deepcopy(record)

    async def advance(
        self, record: InvocationSettlement, *, expected_version: int
    ) -> InvocationSettlement:
        key = (record.request_scope, record.binding_id)
        async with self._lock:
            prior = self.records.get(key)
            if prior is None or prior.version != expected_version:
                raise SavedSettlementConflict("the saved result moved since it was read")
            current = (
                None
                if self.fences is None
                else self.fences(record.request_scope, record.unit_key, record.execution_generation)
            )
            if current is not None and current != record.claim_fence:
                raise StaleSettlementHolder("the writer's claim fence is no longer current")
            _check_successor(prior, record)
            self.records[key] = record
            self.history.append(record)
            return deepcopy(record)

    async def record_event(self, record: InvocationSettlement, event: SettlementEvent) -> bool:
        async with self._lock:
            if any(
                (item.settlement_id, item.kind, item.sequence)
                == (event.settlement_id, event.kind, event.sequence)
                for item in self.events
            ):
                return False
            self.events.append(event)
            return True


def _check_successor(prior: InvocationSettlement, successor: InvocationSettlement) -> None:
    """The same guards the PostgreSQL trigger enforces."""

    immutable = (
        "settlement_id",
        "request_scope",
        "run_id",
        "binding_id",
        "operation_ref",
        "operation_attempt",
        "unit_key",
        "execution_generation",
        "saved_result_digest",
        "execution_outcome",
        "saved_at",
    )
    if any(getattr(prior, name) != getattr(successor, name) for name in immutable):
        raise ValueError("a saved result's identity and bytes are immutable")
    if prior.settled:
        raise ValueError("a settled saved result never changes")
    if successor.version != prior.version + 1 or successor.claim_fence < prior.claim_fence:
        raise ValueError("a successor advances the version by one under a newer or equal fence")
    if prior.stop_fence == "cancelled" and successor.stop_fence != "cancelled":
        raise ValueError("a stop fence is never lifted")


__all__ = [
    "MAX_SAVED_RESULT_BYTES",
    "InMemoryInvocationSettlementStore",
    "InvocationSettlementStore",
    "InvocationSettler",
    "SavedResultTooLarge",
    "SavedSettlementConflict",
    "SettlementEvent",
    "SettlesInvocation",
    "StaleSettlementHolder",
    "UnitFenceReader",
    "saved_result_size",
]
