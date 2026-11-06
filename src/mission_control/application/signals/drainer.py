"""Worker-only inbox processing. Persistence precedes wake and acknowledgement.

Claim locks remain held until acknowledgement. Effects must use the supplied stable
identity: a process crash rolls back the inbox transaction, not an already stored frame.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from mission_control.application.frames.writer import FrameWriter
from mission_control.domain.frames.contracts import FrameKind, FrameObservation


@dataclass(frozen=True)
class DrainItem:
    ingress_id: UUID
    request_scope: str | None
    installation_id: UUID
    application_id: str
    kind: str
    credential_ref: str
    dedupe_key: str
    payload: Mapping[str, Any]
    received_at: datetime
    run_key: str | None = None
    unit_key: str | None = None
    generation: int | None = None
    attempts: int = 0
    outcome: Mapping[str, Any] = field(default_factory=dict)

    @property
    def effect_key(self) -> str:
        space = "signal" if self.kind.startswith("signal.") else self.kind
        return f"ingress:{self.credential_ref}:{space}:{self.dedupe_key}"


class DrainRejected(Exception):
    """Only static, sanitized reason codes may cross the persistence boundary."""

    def __init__(self, code: str) -> None:
        if (
            not code
            or len(code) > 128
            or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789_" for c in code)
        ):
            raise ValueError("invalid drainer reason code")
        super().__init__(code)
        self.code = code


class DrainDeferred(Exception):
    """Durable owner work is pending; this is not a delivery failure.

    A route receipt must commit before its DB-only owner request is enqueued. If this
    process dies before the callback, the next claim resumes from that durable receipt.
    """

    def __init__(
        self,
        outcome: Mapping[str, Any],
        *,
        after_commit: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        super().__init__("native_history_pending")
        self.outcome = outcome
        self.after_commit = after_commit


class DrainBatch(Protocol):
    items: Sequence[DrainItem]

    async def defer(self, item: DrainItem, outcome: Mapping[str, Any]) -> None: ...

    async def settle(
        self, item: DrainItem, state: str, outcome: Mapping[str, Any], error: str | None = None
    ) -> None: ...


class DrainStore(Protocol):
    def claim_batch(self, limit: int) -> AbstractAsyncContextManager[DrainBatch]: ...


class DrainEffects(Protocol):
    async def persist(self, item: DrainItem) -> Mapping[str, Any]:
        """Idempotently persist/reconcile/admit. Never infer completion from ingress."""
        ...

    async def wake(self, item: DrainItem) -> None:
        """Worker-owned Temporal wake; duplicates must be harmless."""
        ...


class IngressDrainer:
    def __init__(
        self,
        store: DrainStore,
        effects: DrainEffects,
        *,
        max_attempts: int = 5,
        batch_size: int = 100,
    ) -> None:
        if max_attempts < 1 or not 1 <= batch_size <= 100:
            raise ValueError("invalid ingress drainer bounds")
        self._store, self._effects = store, effects
        self._max_attempts, self._batch_size = max_attempts, batch_size

    async def drain_once(self) -> int:
        count = 0
        after_commit: list[Callable[[], Awaitable[None]]] = []
        async with self._store.claim_batch(self._batch_size) as batch:
            for item in batch.items:
                outcome: Mapping[str, Any] = item.outcome
                try:
                    async with asyncio.timeout(30):
                        outcome = await self._effects.persist(item)
                        await self._effects.wake(item)
                except DrainDeferred as deferred:
                    await batch.defer(item, deferred.outcome)
                    if deferred.after_commit is not None:
                        after_commit.append(deferred.after_commit)
                    continue  # a full pending batch must still take the polling pause
                except DrainRejected as rejected:
                    await batch.settle(item, "rejected", {**item.outcome, "reason": rejected.code})
                except Exception:
                    # Exception messages may contain tokens, URLs or provider response bodies.
                    dead = item.attempts + 1 >= self._max_attempts
                    await batch.settle(
                        item,
                        "dead" if dead else "pending",
                        {**outcome, "reason": "delivery_failed"},
                        "delivery_failed",
                    )
                else:
                    await batch.settle(item, "drained", outcome)
                count += 1
        # The claim transaction committed its original-binding receipts before these
        # bounded DB-only calls. No provider I/O or wake is performed by the callbacks.
        for enqueue in after_commit:
            try:
                async with asyncio.timeout(5):
                    await enqueue()
            except Exception:
                pass  # the committed pending receipt retries through persist next time
        return count

    async def run(self, stop: asyncio.Event, notified: asyncio.Event) -> None:
        """LISTEN adapter sets notified; missing/disconnected LISTEN keeps 5 s fallback."""
        while not stop.is_set():
            notified.clear()
            if await self.drain_once() == self._batch_size:
                continue
            wake = asyncio.create_task(notified.wait())
            stopped = asyncio.create_task(stop.wait())
            try:
                await asyncio.wait((wake, stopped), timeout=5, return_when=asyncio.FIRST_COMPLETED)
            finally:
                wake.cancel()
                stopped.cancel()
                await asyncio.gather(wake, stopped, return_exceptions=True)


async def write_signal(item: DrainItem, writer: FrameWriter) -> Mapping[str, Any]:
    """Trusted resolver supplies the current writer, never a payload-selected execution."""
    handle = writer.handle
    if item.request_scope != handle.request_scope or item.generation != handle.generation:
        raise DrainRejected("stale_or_cross_scope")
    if not (item.kind.startswith("signal.") or item.kind == "gate.decision"):
        raise DrainRejected("unsupported_kind")
    receipt = await writer.write(
        [
            FrameObservation(
                provider_key=item.effect_key,
                raw_kind=item.kind,
                kind=FrameKind.STATUS,
                observed_at=item.received_at,
                body={"ingress_id": str(item.ingress_id), "evidence": dict(item.payload)},
            )
        ]
    )
    if receipt.stale:
        raise DrainRejected("stale_generation")
    return {"frame_persisted": True}
