"""PostgreSQL Watcher Evaluator store (SPEC-04 §5.3) over the released common tables.

No new tables: watcher descriptors are read from the run's committed definition snapshot
(``mission_revision`` -> ``definition_snapshot``), observations from ``mission_event`` and the
Native Event Store (``provider_frame``), and firing history from the journal itself. A firing
is recorded through the canonical ledger writer (``append_events``) under its deterministic
event id, which is both the ledger ``commit_key`` and the outbox ``delivery_key``; the two
unique keys make a concurrent duplicate a no-op, so a replayed pass never records twice.

Signals are provider frames whose native kind is ``signal.<type>`` (SPEC-04 §3: the
IngressDrainer writes them through the FrameWriter). Their redacted body is a JSON object:
``data`` holds the signal fields a condition reads and ``trust_tier`` the ingress tier; a
body without a recognised tier is treated as the lowest tier by the evaluator. Signals are paged
by their insertion time (``created_at``, the database clock at insert), never by the producer's
``observed_at``: a spooled signal uploaded late keeps its early observation time but still sorts
after the signals already read.
"""

from __future__ import annotations

import heapq
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Final, get_args

import asyncpg

from mission_control.adapters.postgres.control_plane.manifest_submission import (
    PostgresManifestSubmissionRepository,
)
from mission_control.adapters.postgres.run_control import canonical as mc
from mission_control.application.subscriptions.aliases import PUBLIC_ALIASES
from mission_control.application.watchers.ports import ObservationPage, WatcherCursor
from mission_control.domain.authoring.mission_definition import MissionDefinition
from mission_control.domain.policies.contracts import DomainEventEnvelope
from mission_control.domain.programs.watchers import (
    WATCHER_EVENTS,
    FiringRecord,
    Observation,
    TrustTier,
    WatcherDescriptor,
    firing_record,
)
from mission_control.domain.subscriptions.contracts import node_key_of

SCOPE = mc.SCOPE
WATCHER_ACTOR_REF: Final = "system:watcher-evaluator"
SIGNAL_KIND_PREFIX: Final = "signal."
_TIERS: Final = frozenset(get_args(TrustTier))
_RUN = f"""
    SELECT run_id FROM mission_control.mission_run WHERE {SCOPE} AND run_key = $4
"""


def _inner(payload: Any) -> dict[str, Any]:
    """The domain payload of a stored ``DomainEventEnvelope`` dump."""

    if isinstance(payload, Mapping):
        inner = payload.get("payload")
        if isinstance(inner, Mapping):
            return dict(inner)
        return dict(payload)
    return {}


def _signal_body(excerpt: bytes) -> tuple[dict[str, Any], TrustTier | None]:
    try:
        body = json.loads(bytes(excerpt).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}, None
    if not isinstance(body, Mapping):
        return {}, None
    data = body.get("data")
    tier = body.get("trust_tier")
    return (
        dict(data) if isinstance(data, Mapping) else {},
        tier if isinstance(tier, str) and tier in _TIERS else None,  # type: ignore[return-value]
    )


class PostgresWatcherStore:
    def __init__(
        self,
        pool: asyncpg.Pool,
        request_scope: str,
        *,
        submissions: PostgresManifestSubmissionRepository | None = None,
    ) -> None:
        self._pool = pool
        self._scope = request_scope
        self._submissions = submissions or PostgresManifestSubmissionRepository(pool)
        # A committed definition is immutable: its descriptors are read once per run.
        self._descriptors: dict[str, tuple[WatcherDescriptor, ...]] = {}

    @property
    def request_scope(self) -> str:
        return self._scope

    async def descriptors(self, run_id: str) -> tuple[WatcherDescriptor, ...]:
        cached = self._descriptors.get(run_id)
        if cached is not None:
            return cached
        info = await self._submissions.run_subscriptions(self._scope, run_id)
        found: tuple[WatcherDescriptor, ...] = ()
        if info is not None and info["definition"]:
            found = MissionDefinition.model_validate(info["definition"]).policies.watchers
        self._descriptors[run_id] = found
        return found

    async def observations(
        self, run_id: str, *, after: WatcherCursor, limit: int
    ) -> ObservationPage:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, self._scope)
            run_uuid = await connection.fetchval(_RUN, *args, run_id)
            if run_uuid is None:
                return ObservationPage((), after, exhausted=True)
            events = await connection.fetch(
                f"""
                SELECT event_id, seq, event_type, recorded_at, causation_ref, payload
                FROM mission_control.mission_event
                WHERE {SCOPE} AND run_id = $4 AND seq > $5
                ORDER BY seq
                LIMIT $6
                """,
                *args,
                run_uuid,
                after.event_seq,
                limit,
            )
            signals = await connection.fetch(
                f"""
                SELECT frame_id, raw_kind, observed_at, created_at, body_excerpt
                FROM mission_control.provider_frame
                WHERE {SCOPE} AND run_id = $4 AND starts_with(raw_kind, $5)
                  AND ($6::timestamptz IS NULL OR (created_at, frame_id::text) > ($6, $7))
                ORDER BY created_at, frame_id::text
                LIMIT $8
                """,
                *args,
                run_uuid,
                SIGNAL_KIND_PREFIX,
                after.signal_at,
                after.signal_ref or "",
                limit,
            )
        inserted = {str(row["frame_id"]): row["created_at"] for row in signals}
        # Interleave by time, but keep each source in its cursor order: a page cut short never
        # passes over an event with a lower sequence (or a signal inserted earlier) than one it
        # took.
        merged = list(
            heapq.merge(
                (self._event(row) for row in events),
                (self._signal(row) for row in signals),
                key=lambda item: (item.at, item.source != "event"),
            )
        )
        taken = merged[:limit]
        cursor = after
        for item in taken:
            if item.source == "event":
                assert item.seq is not None
                cursor = WatcherCursor(item.seq, cursor.signal_at, cursor.signal_ref)
            else:
                cursor = WatcherCursor(cursor.event_seq, inserted[item.ref], item.ref)
        exhausted = len(events) < limit and len(signals) < limit and len(merged) <= limit
        return ObservationPage(tuple(taken), cursor, exhausted=exhausted)

    @staticmethod
    def _event(row: asyncpg.Record) -> Observation:
        event_type = row["event_type"]
        stored = mc.load(row["payload"])
        alias = PUBLIC_ALIASES.get(event_type)
        return Observation(
            source="event",
            ref=str(row["event_id"]),
            types=(event_type, alias) if alias is not None else (event_type,),
            at=row["recorded_at"],
            seq=row["seq"],
            causation_ref=row["causation_ref"],
            node_key=node_key_of(stored),
            data=_inner(stored),
        )

    @staticmethod
    def _signal(row: asyncpg.Record) -> Observation:
        data, tier = _signal_body(row["body_excerpt"])
        return Observation(
            source="signal",
            ref=str(row["frame_id"]),
            types=(str(row["raw_kind"]).removeprefix(SIGNAL_KIND_PREFIX),),
            at=row["observed_at"],
            data=data,
            trust=tier,
        )

    async def history(self, run_id: str) -> tuple[FiringRecord, ...]:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, self._scope)
            rows = await connection.fetch(
                f"""
                SELECT event.event_type, event.payload
                FROM mission_control.mission_event AS event
                JOIN mission_control.mission_run AS run
                  ON run.installation_id = event.installation_id
                 AND run.application_id = event.application_id
                 AND run.tenant_id = event.tenant_id AND run.run_id = event.run_id
                WHERE {mc.scoped("event")} AND run.run_key = $4
                  AND event.event_type = ANY($5::text[])
                ORDER BY event.seq
                """,
                *args,
                run_id,
                sorted(WATCHER_EVENTS),
            )
        records = (
            firing_record(_inner(mc.load(row["payload"])), row["event_type"]) for row in rows
        )
        return tuple(record for record in records if record is not None)

    async def last_seen(self, run_id: str) -> Mapping[str, datetime]:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, self._scope)
            run_uuid = await connection.fetchval(_RUN, *args, run_id)
            if run_uuid is None:
                return {}
            row = await connection.fetchrow(
                f"""
                SELECT
                  (SELECT max(recorded_at) FROM mission_control.mission_event
                    WHERE {SCOPE} AND run_id = $4 AND event_type <> ALL($6::text[])) AS event,
                  (SELECT max(observed_at) FROM mission_control.provider_frame
                    WHERE {SCOPE} AND run_id = $4 AND NOT starts_with(raw_kind, $5)) AS frame,
                  (SELECT max(observed_at) FROM mission_control.provider_frame
                    WHERE {SCOPE} AND run_id = $4 AND starts_with(raw_kind, $5)) AS signal
                """,
                *args,
                run_uuid,
                SIGNAL_KIND_PREFIX,
                sorted(WATCHER_EVENTS),
            )
        assert row is not None
        return {name: row[name] for name in ("event", "frame", "signal") if row[name] is not None}

    async def usage(self, run_id: str) -> Mapping[str, int]:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, self._scope)
            budget = await mc.budget_state(connection, args, run_key=run_id)
        if budget is None:
            return {}
        usage: dict[str, int] = {}
        for bucket in (budget.consumed, budget.pending_settlement, budget.reserved):
            for dimension, amount in bucket.items():
                usage[dimension] = usage.get(dimension, 0) + amount
        return usage

    async def record(self, run_id: str, event: DomainEventEnvelope) -> bool:
        try:
            async with self._pool.acquire() as connection, connection.transaction():
                args = await mc.begin(connection, self._scope)
                present = await connection.fetchval(
                    f"SELECT 1 FROM mission_control.outbox WHERE {SCOPE} AND delivery_key = $4",
                    *args,
                    event.event_id,
                )
                if present is not None:
                    return False
                await mc.append_events(
                    connection,
                    args,
                    run_key=run_id,
                    commit_key=event.event_id,
                    expected_versions={},
                    events=(event,),
                    actor_ref=WATCHER_ACTOR_REF,
                )
        except asyncpg.UniqueViolationError:
            return False  # a concurrent pass recorded the same firing first
        return True


__all__ = ["SIGNAL_KIND_PREFIX", "WATCHER_ACTOR_REF", "PostgresWatcherStore"]
