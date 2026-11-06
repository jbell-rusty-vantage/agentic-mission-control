"""The persisted Transcript projection on PostgreSQL (TRACING-PROPOSAL §P2 0048, §P3.9, TR-D10).

``mission_control.transcript_entry`` holds one row per ``mc.transcript_entry.v2`` entry of
a run (the typed columns beside the entry document) and
``mission_control.transcript_projection_state`` where the projection stands:
``projected_through_seq`` (the run's ``mission_event.seq``) and ``projected_through_frame``
(``{harness_execution_id, generation, arrival_ordinal, frame_count}`` of the latest
``provider_frame`` and the run's frame count).
:meth:`PostgresTranscriptEntries.replace` makes a run's rows equal the entries in one
transaction under the advisory lock the search projection takes
(``transcript-projection:{run_id}``), so a replay is idempotent;
:meth:`PostgresTranscriptEntries.current_entries` is the ``TranscriptEntryStore`` the
transcript service consults first: the rows, ordered by ``entry_seq``, when the marks equal
the live sources, else ``None`` (the view serves). The tables are a read view, never state;
forced RLS scopes every row and every statement also filters on the three scope columns.

Tracing Stage 3 (R4-F1, R4-F7, R4-F8): the frame count is part of the marks (inside the
``projected_through_frame`` document, no schema change), so a frame retention deleted, or a
late frame with an older ``observed_at``, leaves the projection behind; and ``replace`` never
moves the state backwards: under the lock it writes nothing when the stored projection
already covers a later event.

:class:`PostgresTranscriptProjectionIntents` leases and acknowledges the
``transcript_projection`` outbox intents the settlement transaction writes
(:func:`insert_transcript_projection_intent`), the pattern of the chain relay store;
:meth:`PostgresTranscriptEntries.request_projection` writes one outside a settlement (the
projector's catch-up, R4-F3).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import asyncpg

from mission_control.adapters.postgres.run_control import canonical as mc
from mission_control.adapters.postgres.run_control.canonical import SCOPE
from mission_control.application.frames.projection_trigger import (
    TRANSCRIPT_PROJECTION_DESTINATION,
    TRANSCRIPT_PROJECTION_EVENT_TYPE,
    TranscriptProjectionIntent,
    transcript_projection_intent,
)
from mission_control.application.frames.search import ProjectionMarks, TranscriptEntryReceipt
from mission_control.contracts.identities import uuid7
from mission_control.domain.frames.transcript import TranscriptEntry
from mission_control.domain.policies.errors import RunControlNotFound, RunVersionConflict

TRANSCRIPT_PROJECTION_VERSION = 2
"""Bump when the persisted entry shape changes; older rows are then never served as current."""
# Rows per set-based INSERT of `replace` (bounded statement size; a run's projection
# writes len(rows) / INSERT_CHUNK_ROWS statements inside one transaction).
INSERT_CHUNK_ROWS = 250
REQUEST_ACTOR = "mission-control-transcript-projection"


@dataclass(frozen=True, slots=True)
class TranscriptProjectionState:
    run_key: str
    projected_through_seq: int
    projected_through_frame: dict[str, Any] | None
    entry_count: int
    projection_version: int
    projected_at: datetime


def _uuid(value: object) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError:
            return None
    return None


@dataclass(frozen=True, slots=True)
class _Row:
    cursor: str
    entry_seq: int
    unit_key: str | None
    activation_id: UUID | None
    point_id: UUID | None
    parent_point_id: UUID | None
    node_key: str | None
    iteration: int | None
    cycle: int | None
    session_generation: int | None
    subordinate_ref: str | None
    source: str
    kind: str
    role: str
    canonical: bool
    at: datetime
    body_state: str
    entry: str


def _row(entry: TranscriptEntry, position: int) -> _Row:
    """The typed columns of one ``mc.transcript_entry.v2`` entry (``entry_seq`` falls back to
    the transcript position for an entry built outside a merge; ``role`` is ``unknown`` when
    the entry has none, the column being NOT NULL)."""

    return _Row(
        cursor=entry.cursor,
        entry_seq=entry.entry_seq or position,
        unit_key=entry.unit_key or None,
        activation_id=_uuid(entry.activation_id),
        point_id=_uuid(entry.point_id),
        parent_point_id=_uuid(entry.parent_point_id),
        node_key=entry.node_key or None,
        iteration=entry.iteration,
        cycle=entry.cycle,
        session_generation=entry.session_generation,
        subordinate_ref=entry.subordinate_ref or None,
        source=entry.source,
        kind=entry.kind,
        role=entry.role or "unknown",
        canonical=entry.canonical,
        at=entry.at,
        body_state=entry.body.state,
        entry=mc.dump(entry.model_dump(mode="json", exclude_none=True)),
    )


def _frame_mark(row: asyncpg.Record | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "harness_execution_id": str(row["harness_execution_id"]),
        "generation": int(row["generation"]),
        "arrival_ordinal": int(row["arrival_ordinal"]),
        # Tracing Stage 3 (R4-F1, R4-F7): deletions and late frames change the count.
        "frame_count": int(row["frame_count"]),
    }


async def live_marks(
    connection: asyncpg.Connection, args: tuple[Any, ...], run_id: UUID
) -> ProjectionMarks:
    """The run's latest ``mission_event.seq``, its latest frame by ``(observed_at,
    arrival_ordinal)`` and its frame count, in the caller's transaction."""

    seq = await connection.fetchval(
        f"SELECT coalesce(max(seq), 0) FROM mission_control.mission_event WHERE {SCOPE} "
        "AND run_id = $4",
        *args,
        run_id,
    )
    frame = await connection.fetchrow(
        f"""
        SELECT harness_execution_id, generation, arrival_ordinal,
               count(*) OVER () AS frame_count
        FROM mission_control.provider_frame
        WHERE {SCOPE} AND run_id = $4
        ORDER BY observed_at DESC, arrival_ordinal DESC
        LIMIT 1
        """,
        *args,
        run_id,
    )
    return ProjectionMarks(
        projected_through_seq=int(seq or 0), projected_through_frame=_frame_mark(frame)
    )


async def _state_row(
    connection: asyncpg.Connection, args: tuple[Any, ...], run_id: UUID
) -> asyncpg.Record | None:
    return await connection.fetchrow(
        f"""
        SELECT projected_through_seq, projected_through_frame, entry_count,
               projection_version, projected_at
        FROM mission_control.transcript_projection_state
        WHERE {SCOPE} AND run_id = $4
        """,
        *args,
        run_id,
    )


async def projection_is_current(
    connection: asyncpg.Connection, args: tuple[Any, ...], run_id: UUID
) -> bool:
    """Whether the run's persisted projection covers the live sources (this version, the
    same latest event, latest frame and frame count), in the caller's transaction."""

    state = await _state_row(connection, args, run_id)
    if state is None or int(state["projection_version"]) != TRANSCRIPT_PROJECTION_VERSION:
        return False
    marks = await live_marks(connection, args, run_id)
    stored_frame = state["projected_through_frame"]
    return int(state["projected_through_seq"]) == marks.projected_through_seq and (
        (mc.load(stored_frame) if stored_frame is not None else None)
        == marks.projected_through_frame
    )


async def _entries(
    connection: asyncpg.Connection, args: tuple[Any, ...], run_id: UUID
) -> tuple[TranscriptEntry, ...]:
    rows = await connection.fetch(
        f"""
        SELECT entry FROM mission_control.transcript_entry
        WHERE {SCOPE} AND run_id = $4
        ORDER BY entry_seq
        """,
        *args,
        run_id,
    )
    return tuple(TranscriptEntry.model_validate(mc.load(row["entry"])) for row in rows)


class PostgresTranscriptEntries:
    """``TranscriptEntryStoreWriter`` (search.py) and the transcript's ``TranscriptEntryStore``."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def live_marks(self, request_scope: str, run_key: str) -> ProjectionMarks:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, request_scope)
            run_id = await mc.run_uuid(connection, args, run_key)
            return await live_marks(connection, args, run_id)

    async def replace(
        self,
        request_scope: str,
        run_key: str,
        entries: Sequence[TranscriptEntry],
        *,
        projected_through_seq: int,
        projected_through_frame: dict[str, Any] | None,
    ) -> TranscriptEntryReceipt:
        if any(entry.run_id != run_key for entry in entries):
            raise ValueError("projected entries belong to exactly one run")
        rows = [_row(entry, position) for position, entry in enumerate(entries, start=1)]
        if len({row.cursor for row in rows}) != len(rows):
            raise ValueError("projected entries repeat a cursor")
        if len({row.entry_seq for row in rows}) != len(rows):
            raise ValueError("projected entries repeat an entry_seq")
        projected_at = datetime.now(UTC)
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, request_scope)
            run_id = await mc.run_uuid(connection, args, run_key)
            await mc.advisory_lock(connection, f"transcript-projection:{run_id}")
            # Tracing Stage 3 (R4-F8): a concurrent pass that read later marks already
            # wrote; this older one must not move the state (or the rows) backwards.
            stored = await _state_row(connection, args, run_id)
            if (
                stored is not None
                and int(stored["projection_version"]) == TRANSCRIPT_PROJECTION_VERSION
                and int(stored["projected_through_seq"]) > projected_through_seq
            ):
                frame = stored["projected_through_frame"]
                return TranscriptEntryReceipt(
                    run_id=run_key,
                    entries=int(stored["entry_count"]),
                    projected_through_seq=int(stored["projected_through_seq"]),
                    projected_through_frame=mc.load(frame) if frame is not None else None,
                    projection_version=TRANSCRIPT_PROJECTION_VERSION,
                    superseded=True,
                )
            await connection.execute(
                f"DELETE FROM mission_control.transcript_entry WHERE {SCOPE} AND run_id = $4",
                *args,
                run_id,
            )
            # One set-based INSERT per chunk (never `executemany`: its pipelined form stalled
            # mid-batch on the Windows selector loop under asyncpg 0.31, the server waiting
            # on `ClientRead` inside the open transaction).
            for first in range(0, len(rows), INSERT_CHUNK_ROWS):
                chunk = rows[first : first + INSERT_CHUNK_ROWS]
                await connection.execute(
                    """
                    INSERT INTO mission_control.transcript_entry (
                        installation_id, application_id, tenant_id, run_id, cursor, entry_seq,
                        unit_key, activation_id, point_id, parent_point_id, node_key, iteration,
                        cycle, session_generation, subordinate_ref, source, kind, role,
                        canonical, at, body_state, entry, projected_at, projection_version
                    )
                    SELECT $1::uuid, $2::text, $3::uuid, $4::uuid, c.cursor, c.entry_seq,
                           c.unit_key, c.activation_id, c.point_id, c.parent_point_id,
                           c.node_key, c.iteration, c.cycle, c.session_generation,
                           c.subordinate_ref, c.source, c.kind, c.role, c.canonical, c.at,
                           c.body_state, c.entry::jsonb, $23::timestamptz, $24::integer
                    FROM unnest(
                        $5::text[], $6::bigint[], $7::text[], $8::uuid[], $9::uuid[],
                        $10::uuid[], $11::text[], $12::bigint[], $13::bigint[], $14::bigint[],
                        $15::text[], $16::text[], $17::text[], $18::text[], $19::boolean[],
                        $20::timestamptz[], $21::text[], $22::text[]
                    ) AS c(cursor, entry_seq, unit_key, activation_id, point_id,
                           parent_point_id, node_key, iteration, cycle, session_generation,
                           subordinate_ref, source, kind, role, canonical, at, body_state,
                           entry)
                    """,
                    *args,
                    run_id,
                    [row.cursor for row in chunk],
                    [row.entry_seq for row in chunk],
                    [row.unit_key for row in chunk],
                    [row.activation_id for row in chunk],
                    [row.point_id for row in chunk],
                    [row.parent_point_id for row in chunk],
                    [row.node_key for row in chunk],
                    [row.iteration for row in chunk],
                    [row.cycle for row in chunk],
                    [row.session_generation for row in chunk],
                    [row.subordinate_ref for row in chunk],
                    [row.source for row in chunk],
                    [row.kind for row in chunk],
                    [row.role for row in chunk],
                    [row.canonical for row in chunk],
                    [row.at for row in chunk],
                    [row.body_state for row in chunk],
                    [row.entry for row in chunk],
                    projected_at,
                    TRANSCRIPT_PROJECTION_VERSION,
                )
            persisted = await connection.fetchval(
                f"SELECT count(*) FROM mission_control.transcript_entry "
                f"WHERE {SCOPE} AND run_id = $4",
                *args,
                run_id,
            )
            if int(persisted) != len(rows):
                raise RuntimeError(
                    f"transcript projection of {run_key} holds {persisted} rows after writing "
                    f"{len(rows)}: the replace is not atomic under this cluster"
                )
            await connection.execute(
                """
                INSERT INTO mission_control.transcript_projection_state (
                    installation_id, application_id, tenant_id, run_id, projected_through_seq,
                    projected_through_frame, entry_count, projection_version, projected_at
                )
                VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9)
                ON CONFLICT (installation_id, application_id, tenant_id, run_id) DO UPDATE
                SET projected_through_seq = EXCLUDED.projected_through_seq,
                    projected_through_frame = EXCLUDED.projected_through_frame,
                    entry_count = EXCLUDED.entry_count,
                    projection_version = EXCLUDED.projection_version,
                    projected_at = EXCLUDED.projected_at
                """,
                *args,
                run_id,
                projected_through_seq,
                mc.dump(projected_through_frame) if projected_through_frame is not None else None,
                len(rows),
                TRANSCRIPT_PROJECTION_VERSION,
                projected_at,
            )
        return TranscriptEntryReceipt(
            run_id=run_key,
            entries=len(rows),
            projected_through_seq=projected_through_seq,
            projected_through_frame=projected_through_frame,
            projection_version=TRANSCRIPT_PROJECTION_VERSION,
        )

    async def state(self, request_scope: str, run_key: str) -> TranscriptProjectionState | None:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, request_scope)
            try:
                run_id = await mc.run_uuid(connection, args, run_key)
            except RunControlNotFound:
                return None
            row = await _state_row(connection, args, run_id)
        if row is None:
            return None
        frame = row["projected_through_frame"]
        return TranscriptProjectionState(
            run_key=run_key,
            projected_through_seq=int(row["projected_through_seq"]),
            projected_through_frame=mc.load(frame) if frame is not None else None,
            entry_count=int(row["entry_count"]),
            projection_version=int(row["projection_version"]),
            projected_at=row["projected_at"],
        )

    async def projected_entries(
        self, request_scope: str, run_key: str
    ) -> tuple[TranscriptEntry, ...]:
        """The run's persisted rows whether or not the projection is current (F-S2-5)."""

        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, request_scope)
            try:
                run_id = await mc.run_uuid(connection, args, run_key)
            except RunControlNotFound:
                return ()
            return await _entries(connection, args, run_id)

    async def current_entries(
        self, request_scope: str, run_key: str
    ) -> tuple[TranscriptEntry, ...] | None:
        """The persisted entries when the projection covers the live sources, else ``None``
        (a run this scope cannot see is ``None`` too: the transcript service reports it)."""

        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, request_scope)
            try:
                run_id = await mc.run_uuid(connection, args, run_key)
            except RunControlNotFound:
                return None
            if not await projection_is_current(connection, args, run_id):
                return None
            return await _entries(connection, args, run_id)

    async def request_projection(
        self, request_scope: str, run_key: str, *, reason: str, not_before: datetime
    ) -> None:
        """Tracing Stage 3 (R4-F3): one ``transcript_projection`` outbox intent outside a
        settlement (the projector's catch-up, a failed pass's retry); ``reason`` names it, so
        the same reason twice writes one intent and starts one workflow."""

        intent = transcript_projection_intent(
            request_scope=request_scope, run_key=run_key, settlement_id=reason
        )
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, request_scope)
            await insert_transcript_projection_intent(
                connection, args, intent, at=not_before, actor_ref=REQUEST_ACTOR
            )


# ------------------------------------------------------------------------------------------
# The settlement-released trigger (outbox intents)
# ------------------------------------------------------------------------------------------


async def insert_transcript_projection_intent(
    connection: asyncpg.Connection,
    args: tuple[Any, ...],
    intent: TranscriptProjectionIntent,
    *,
    at: datetime,
    actor_ref: str,
    ledger_commit_id: UUID | None = None,
) -> None:
    """One ``transcript_projection`` outbox row in the caller's (settlement) transaction;
    the delivery key makes a replayed settlement write nothing."""

    await connection.execute(
        """
        INSERT INTO mission_control.outbox (
            installation_id, application_id, tenant_id, outbox_id, ledger_commit_id,
            event_id, delivery_key, destination_kind, event_type, aggregate_key,
            aggregate_version, aggregate_sequence, payload, payload_ref, delivery_state,
            attempts, next_attempt_at, version, created_at, created_by_actor_ref
        )
        VALUES ($1, $2, $3, $4, $5, NULL, $6, $7, $8, $9, NULL, NULL, $10::jsonb, NULL,
                'pending', 0, $11, 1, $11, $12)
        ON CONFLICT (installation_id, application_id, tenant_id, delivery_key) DO NOTHING
        """,
        *args,
        uuid7(),
        ledger_commit_id,
        intent.delivery_key,
        TRANSCRIPT_PROJECTION_DESTINATION,
        TRANSCRIPT_PROJECTION_EVENT_TYPE,
        intent.run_key,
        intent.model_dump_json(),
        at,
        actor_ref,
    )


class PostgresTranscriptProjectionIntents:
    """``TranscriptProjectionIntentStore``: lease and acknowledge projection intents
    (``FOR UPDATE SKIP LOCKED``, fenced by the lease owner)."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def lease(
        self,
        request_scope: str,
        *,
        lease_owner: str,
        lease_until: datetime,
        now: datetime,
        limit: int,
    ) -> tuple[TranscriptProjectionIntent, ...]:
        if not lease_owner:
            raise ValueError("outbox lease owner cannot be empty")
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, request_scope)
            rows = await connection.fetch(
                f"""
                WITH due AS (
                    SELECT outbox_id FROM mission_control.outbox
                    WHERE {SCOPE} AND destination_kind = $8
                      AND (delivery_state = 'pending'
                           OR (delivery_state = 'leased' AND lease_expires_at <= $6))
                      AND next_attempt_at <= $6
                    ORDER BY global_position
                    LIMIT $7
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE mission_control.outbox AS box
                SET delivery_state = 'leased', lease_owner = $4, lease_expires_at = $5,
                    version = box.version + 1
                FROM due
                WHERE {mc.scoped("box")} AND box.outbox_id = due.outbox_id
                RETURNING box.global_position, box.payload, box.attempts
                """,
                *args,
                lease_owner,
                lease_until,
                now,
                limit,
                TRANSCRIPT_PROJECTION_DESTINATION,
            )
        return tuple(
            TranscriptProjectionIntent.model_validate(
                {**mc.load(row["payload"]), "attempts": int(row["attempts"])}
            )
            for row in sorted(rows, key=lambda item: item["global_position"])
        )

    async def mark_delivered(
        self, request_scope: str, delivery_key: str, *, lease_owner: str, delivered_at: datetime
    ) -> None:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, request_scope)
            result = await connection.execute(
                f"""
                UPDATE mission_control.outbox
                SET attempts = attempts + 1, delivered_at = $6, delivery_state = 'delivered',
                    lease_owner = NULL, lease_expires_at = NULL, version = version + 1
                WHERE {SCOPE} AND delivery_key = $4 AND lease_owner = $5
                  AND delivery_state = 'leased'
                """,
                *args,
                delivery_key,
                lease_owner,
                delivered_at,
            )
        if result != "UPDATE 1":
            raise RunVersionConflict(f"transcript projection intent lease lost: {delivery_key}")

    async def mark_failed(
        self,
        request_scope: str,
        delivery_key: str,
        *,
        lease_owner: str,
        retry_at: datetime,
        dead: bool,
    ) -> None:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, request_scope)
            await connection.execute(
                f"""
                UPDATE mission_control.outbox
                SET attempts = attempts + 1, next_attempt_at = $6,
                    delivery_state = CASE WHEN $7 THEN 'dead' ELSE 'pending' END,
                    lease_owner = NULL, lease_expires_at = NULL, version = version + 1
                WHERE {SCOPE} AND delivery_key = $4 AND lease_owner = $5
                """,
                *args,
                delivery_key,
                lease_owner,
                retry_at,
                dead,
            )


__all__ = [
    "TRANSCRIPT_PROJECTION_VERSION",
    "PostgresTranscriptEntries",
    "PostgresTranscriptProjectionIntents",
    "TranscriptProjectionState",
    "insert_transcript_projection_intent",
    "live_marks",
    "projection_is_current",
]
