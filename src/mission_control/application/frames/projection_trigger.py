"""The Transcript projection released by the settlement outbox (TRACING-PROPOSAL §P3.9, TR-D10).

The operation journal never calls Temporal: the transaction that commits an
``operation_settlement`` also writes one ``transcript_projection`` outbox intent for the
settled run (ADR 0004's transactional outbox; the chain reducer of ADR 0029 is the model).
:class:`TranscriptProjectionRelay` leases due intents, starts the run's ``transcript.project``
job through a port and acknowledges the intent only after the start returned, so a crash
between the two re-delivers. Starting is idempotent: the Temporal starter derives the
workflow id from the run and the settlement, so a second delivery attaches to the first.
The projection itself is idempotent (``transcript_projection_state`` advances
``projected_through_seq`` and the last frame cursor), so an extra delivery costs one rebuild
and never a wrong row. Seconds behind the settlement; no schedule (owner, 2026-10-21).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Final, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

_LOG = logging.getLogger(__name__)

TRANSCRIPT_PROJECTION_DESTINATION: Final = "transcript_projection"
"""``outbox.destination_kind`` of a projection intent."""
TRANSCRIPT_PROJECTION_EVENT_TYPE: Final = "transcript.project"
TRANSCRIPT_PROJECTION_INTENT_SCHEMA: Final = "mc.transcript_projection_intent.v1"
MAX_DELIVERY_ATTEMPTS = 12


class TranscriptProjectionIntent(BaseModel):
    """One outbox intent (``mc.transcript_projection_intent.v1``): project this run now."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["mc.transcript_projection_intent.v1"] = (
        TRANSCRIPT_PROJECTION_INTENT_SCHEMA
    )
    request_scope: str = Field(min_length=1)
    run_key: str = Field(min_length=1)
    """The run-control identity (``mission_run.run_key``) the projection addresses."""
    settlement_id: str = Field(min_length=1)
    settlement_revision: int = Field(default=1, ge=1)
    delivery_key: str = Field(min_length=1)
    attempts: int = Field(default=0, ge=0)


def transcript_projection_delivery_key(
    run_key: str, settlement_id: str, *, settlement_revision: int = 1
) -> str:
    """``transcript-projection:{run}:{settlement}``; a reconciled revision adds ``:r{n}``."""

    key = f"transcript-projection:{run_key}:{settlement_id}"
    return key if settlement_revision == 1 else f"{key}:r{settlement_revision}"


def transcript_projection_intent(
    *, request_scope: str, run_key: str, settlement_id: str, settlement_revision: int = 1
) -> TranscriptProjectionIntent:
    return TranscriptProjectionIntent(
        request_scope=request_scope,
        run_key=run_key,
        settlement_id=settlement_id,
        settlement_revision=settlement_revision,
        delivery_key=transcript_projection_delivery_key(
            run_key, settlement_id, settlement_revision=settlement_revision
        ),
    )


class TranscriptProjectionIntentStore(Protocol):
    async def lease(
        self,
        request_scope: str,
        *,
        lease_owner: str,
        lease_until: datetime,
        now: datetime,
        limit: int,
    ) -> tuple[TranscriptProjectionIntent, ...]: ...

    async def mark_delivered(
        self, request_scope: str, delivery_key: str, *, lease_owner: str, delivered_at: datetime
    ) -> None: ...

    async def mark_failed(
        self,
        request_scope: str,
        delivery_key: str,
        *,
        lease_owner: str,
        retry_at: datetime,
        dead: bool,
    ) -> None: ...


class TranscriptProjectionStarter(Protocol):
    async def project(self, intent: TranscriptProjectionIntent) -> str:
        """Start (or attach to) the run's projection; returns the job's handle (workflow id)."""
        ...


@dataclass(frozen=True, slots=True)
class TranscriptProjectionRelayReport:
    delivered: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()
    dead: tuple[str, ...] = ()
    handles: dict[str, str] = field(default_factory=dict)


class TranscriptProjectionRelay:
    """At-least-once delivery of projection intents; acknowledgement follows the start."""

    def __init__(
        self,
        *,
        store: TranscriptProjectionIntentStore,
        starter: TranscriptProjectionStarter,
        lease_owner: str = "transcript-projection-relay",
        lease_seconds: int = 60,
        base_backoff_seconds: float = 2.0,
        max_backoff_seconds: float = 900.0,
    ) -> None:
        self._store = store
        self._starter = starter
        self._owner = lease_owner
        self._lease = timedelta(seconds=lease_seconds)
        self._base = base_backoff_seconds
        self._cap = max_backoff_seconds

    async def relay_once(
        self, request_scope: str, *, now: datetime, limit: int = 50
    ) -> TranscriptProjectionRelayReport:
        intents = await self._store.lease(
            request_scope,
            lease_owner=self._owner,
            lease_until=now + self._lease,
            now=now,
            limit=limit,
        )
        delivered: list[str] = []
        failed: list[str] = []
        dead: list[str] = []
        handles: dict[str, str] = {}
        for intent in intents:
            try:
                handles[intent.delivery_key] = await self._starter.project(intent)
            except Exception as error:  # delivery failures are retried, never dropped
                attempts = intent.attempts + 1
                is_dead = attempts >= MAX_DELIVERY_ATTEMPTS
                _LOG.warning(
                    "transcript projection intent %s delivery failed (attempt %s): %s",
                    intent.delivery_key,
                    attempts,
                    error,
                )
                delay = min(self._cap, self._base * (2 ** min(attempts, 16)))
                await self._store.mark_failed(
                    request_scope,
                    intent.delivery_key,
                    lease_owner=self._owner,
                    retry_at=now + timedelta(seconds=delay),
                    dead=is_dead,
                )
                (dead if is_dead else failed).append(intent.delivery_key)
                continue
            await self._store.mark_delivered(
                request_scope, intent.delivery_key, lease_owner=self._owner, delivered_at=now
            )
            delivered.append(intent.delivery_key)
        return TranscriptProjectionRelayReport(
            delivered=tuple(delivered), failed=tuple(failed), dead=tuple(dead), handles=handles
        )


class TranscriptProjectionPump:
    """The relay as a bounded, cancellable loop beside the maintenance worker.

    Each pass leases at most ``limit`` due intents per tenant scope (row-level security binds
    one tenant per transaction); a scope whose pass fails is logged and retried next pass.
    """

    def __init__(
        self,
        relay: TranscriptProjectionRelay,
        request_scopes: Sequence[str],
        *,
        interval_seconds: float = 2.0,
        limit: int = 50,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if interval_seconds <= 0 or limit < 1:
            raise ValueError("the projection pump needs a positive interval and batch limit")
        self._relay = relay
        self._scopes = tuple(request_scopes)
        self._interval = interval_seconds
        self._limit = limit
        self._clock = clock or (lambda: datetime.now(UTC))

    async def run_once(self) -> tuple[TranscriptProjectionRelayReport, ...]:
        reports: list[TranscriptProjectionRelayReport] = []
        for scope in self._scopes:
            try:
                reports.append(
                    await self._relay.relay_once(scope, now=self._clock(), limit=self._limit)
                )
            except Exception:  # a scope's outage never stops the other scopes or the worker
                _LOG.exception("transcript projection relay pass failed for one tenant scope")
        return tuple(reports)

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            await self.run_once()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=self._interval)


__all__ = [
    "MAX_DELIVERY_ATTEMPTS",
    "TRANSCRIPT_PROJECTION_DESTINATION",
    "TRANSCRIPT_PROJECTION_EVENT_TYPE",
    "TRANSCRIPT_PROJECTION_INTENT_SCHEMA",
    "TranscriptProjectionIntent",
    "TranscriptProjectionIntentStore",
    "TranscriptProjectionPump",
    "TranscriptProjectionRelay",
    "TranscriptProjectionRelayReport",
    "TranscriptProjectionStarter",
    "transcript_projection_delivery_key",
    "transcript_projection_intent",
]
