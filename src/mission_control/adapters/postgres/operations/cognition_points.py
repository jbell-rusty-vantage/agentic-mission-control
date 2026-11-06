"""`mission_control.cognition_point` (migration 0045, `mc.cognition_point.v1`; 1.4.4 columns).

Insert-only for the settlement (a replay finds its rows), column-limited enrichment for the
reconciler and the frame writer, scoped reads for the operator API. At write time the
repository resolves what the lane could not know: the parent point by locator within the
run (the expected source another unit settled), the cross-cycle parent (`cycle_start`,
`rollover_start`: the prior cycle's or session generation's result point, P3.8), the session
turn by the frame writer's native identity, and the frame range from the provider keys
recorded while the step ran. The settlement writes its rows through `record_points_in` on
the lineage repository's connection, inside the transition's transaction (TR-D6); `record`
is the same write under a transaction of its own (the reconciler, the fork seed). The full
record travels in the `record` column; the typed columns exist for filters and the guard.
The runtime role never deletes a point.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import asyncpg

from mission_control.adapters.postgres.run_control import canonical as mc
from mission_control.adapters.postgres.run_control.canonical import SCOPE
from mission_control.application.execution.cognition_points import (
    PointBatch,
    cross_cycle_parent,
    decode_cursor,
    encode_cursor,
    page_size,
    with_cross_cycle_parent,
)
from mission_control.domain.execution.cognition_points import (
    CheckpointPoint,
    CognitionPointFilter,
    CognitionPointPage,
    CognitionPointRecord,
    FrameRange,
    frame_range_of,
    frames_of_point,
)

POINT_ACTOR = "mission-control-operation-runtime"
DEFAULT_RESTORE_LEVEL = "R3"
_ENRICHABLE = frozenset(
    {
        "parent_point_id",
        # Tracing Stage 3 (R2-14): the reconciler completes a budget-bounded walk's rows.
        "parent_locator",
        "parent_coordinate",
        "roles",
        "turn_id",
        "frames",
        "budget_snapshot",
        "workspace_checkpoint_ref",
        "seedable",
        "written_by",
        "coordinate",
        "attempt",
        "message_count",
        "channel_facts",
        "files_digest",
        "usage_delta",
        "restore_level",
        "history",
    }
)


class PostgresCognitionPointRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def record(
        self,
        request_scope: str,
        records: Sequence[CognitionPointRecord],
        *,
        frame_keys: Mapping[str, tuple[str, ...]],
        turn_refs: Mapping[str, tuple[str, str]],
    ) -> tuple[CognitionPointRecord, ...]:
        if not records:
            return ()
        stored: list[CognitionPointRecord] = []
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, request_scope)
            runs: dict[str, UUID] = {}
            thread_frames = _ThreadFrames()
            for record in records:
                run_key = record.coordinate.run_id
                if run_key not in runs:
                    runs[run_key] = (await mc.require_run(connection, args, run_key))["run_id"]
                stored.append(
                    await _record_one(
                        connection,
                        args,
                        runs[run_key],
                        record,
                        frame_keys=frame_keys.get(record.point_id, ()),
                        turn_ref=turn_refs.get(record.point_id),
                        thread_frames=thread_frames,
                    )
                )
        return tuple(stored)

    async def list_points(
        self,
        request_scope: str,
        run_id: str,
        *,
        selection: CognitionPointFilter,
        limit: int,
        cursor: str | None,
    ) -> CognitionPointPage:
        offset = decode_cursor(cursor)
        size = page_size(limit)
        clauses: list[str] = []
        values: list[Any] = []

        def where(column: str, value: Any, *, cast: str = "") -> None:
            values.append(value)
            clauses.append(f"AND {column} = ${len(values) + 4}{cast}")

        if selection.unit_key is not None:
            where("unit_key", selection.unit_key)
        if selection.execution_generation is not None:
            where("execution_generation", selection.execution_generation)
        if selection.node_key is not None:
            where("node_key", selection.node_key)
        if selection.iteration is not None:
            where("iteration", selection.iteration)
        if selection.cycle is not None:
            where("cycle", selection.cycle)
        if selection.session_generation is not None:
            where("session_generation", selection.session_generation)
        if selection.kind is not None:
            where("point_kind", selection.kind)
        if selection.role is not None:
            values.append(selection.role)
            clauses.append(f"AND ${len(values) + 4} = ANY(roles)")
        if selection.seedable_only:
            clauses.append("AND seedable")
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, request_scope)
            run = await mc.require_run(connection, args, run_id)
            rows = await connection.fetch(
                f"""
                SELECT record FROM mission_control.cognition_point
                WHERE {SCOPE} AND run_id = $4 {" ".join(clauses)}
                ORDER BY recorded_at, unit_key, execution_generation,
                         ordinal NULLS FIRST, point_locator
                LIMIT {size + 1} OFFSET {offset}
                """,
                *args,
                run["run_id"],
                *values,
            )
        entries = [CognitionPointRecord.model_validate(_load(row["record"])) for row in rows]
        next_cursor = encode_cursor(offset + size) if len(entries) > size else None
        return CognitionPointPage(
            run_id=run_id, entries=tuple(entries[:size]), next_cursor=next_cursor
        )

    async def get_point(self, request_scope: str, point_id: str) -> CognitionPointRecord | None:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, request_scope)
            return await _fetch(connection, args, point_id)

    async def find_point(
        self, request_scope: str, run_id: str, *, kind: str, locator: str
    ) -> CognitionPointRecord | None:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, request_scope)
            run = await mc.require_run(connection, args, run_id)
            return await _find(connection, args, run["run_id"], kind, locator)

    async def enrich(
        self, request_scope: str, point_id: str, **changes: object
    ) -> CognitionPointRecord:
        unknown = sorted(set(changes) - _ENRICHABLE)
        if unknown:
            raise ValueError(f"cognition point fields are not enrichable: {unknown}")
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, request_scope)
            current = await _fetch(connection, args, point_id, lock=True)
            if current is None:
                raise LookupError(f"cognition point {point_id} is not recorded")
            updated = current.model_copy(update={**changes, "version": current.version + 1})
            now = datetime.now(UTC)
            await connection.execute(
                f"""
                UPDATE mission_control.cognition_point
                SET parent_point_id = $5::uuid, parent_coordinate = $6::jsonb, roles = $7::text[],
                    turn_id = $8::uuid, frame_from_ordinal = $9, frame_to_ordinal = $10,
                    budget_snapshot = $11::jsonb, workspace_checkpoint_ref = $12,
                    seedable = $13, written_by = $14, record = $15::jsonb,
                    message_count = $16, channel_facts = $17::jsonb, files_digest = $18,
                    usage_delta = $19::jsonb, turn_no = $20, harness_execution_id = $21::uuid,
                    version = $22, updated_at = $23, subordinate_ref = $24, restore_level = $25
                WHERE {SCOPE} AND point_id = $4::uuid
                """,
                *args,
                point_id,
                updated.parent_point_id,
                _dump(updated.parent_coordinate.model_dump(mode="json"))
                if updated.parent_coordinate is not None
                else None,
                list(updated.roles),
                updated.turn_id,
                updated.frames.from_ordinal if updated.frames is not None else None,
                updated.frames.to_ordinal if updated.frames is not None else None,
                _dump(updated.budget_snapshot) if updated.budget_snapshot is not None else None,
                updated.workspace_checkpoint_ref,
                updated.seedable,
                updated.written_by,
                _dump(updated.model_dump(mode="json")),
                updated.message_count,
                _dump(updated.channel_facts),
                updated.files_digest,
                _dump(updated.usage_delta),
                updated.coordinate.turn_no,
                updated.coordinate.harness_execution_id,
                updated.version,
                now,
                updated.subordinate_ref,
                updated.restore_level or DEFAULT_RESTORE_LEVEL,
            )
        return updated


async def record_points_in(
    connection: asyncpg.Connection,
    args: tuple[Any, ...],
    run_id: UUID,
    batch: PointBatch,
) -> tuple[CognitionPointRecord, ...]:
    """Write a settlement's point batch on the caller's connection and transaction (TR-D6).

    Idempotent: a point already recorded (`ON CONFLICT (…, point_id) DO NOTHING`, pre-checked
    by id) is returned as stored. Any failure propagates so the caller's transaction (the
    transition and the result) rolls back with it.
    """

    stored: list[CognitionPointRecord] = []
    # Tracing Stage 3 (R1-F13): the thread's frames are read once per batch, not per point.
    thread_frames = _ThreadFrames()
    for record in batch.records:
        stored.append(
            await _record_one(
                connection,
                args,
                run_id,
                record,
                frame_keys=batch.frame_keys.get(record.point_id, ()),
                turn_ref=batch.turn_refs.get(record.point_id),
                thread_frames=thread_frames,
            )
        )
    return tuple(stored)


async def record_marker_in(
    connection: asyncpg.Connection,
    args: tuple[Any, ...],
    run_id: UUID,
    record: CognitionPointRecord,
) -> None:
    """Tracing Stage 3 (R1-F3): insert one point exactly as given (no parent, turn or frame
    resolution): the `points_status: incomplete` marker of a settlement whose points write
    failed. Idempotent by point id."""

    await _insert(connection, args, run_id, record)


class _ThreadFrames:
    """`provider_frame` rows of a root thread within one execution, read once per write."""

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], list[_KeyedRow]] = {}

    async def rows(
        self, connection: asyncpg.Connection, args: tuple[Any, ...], execution: str, thread: str
    ) -> list[_KeyedRow]:
        key = (execution, thread)
        if key not in self._rows:
            rows = await connection.fetch(
                f"""
                SELECT provider_key, arrival_ordinal FROM mission_control.provider_frame
                WHERE {SCOPE} AND harness_execution_id = $4::uuid
                  AND starts_with(provider_key, $5::text)
                """,
                *args,
                execution,
                f"{thread}::",
            )
            self._rows[key] = [_KeyedRow(row) for row in rows]
        return self._rows[key]


async def _record_one(
    connection: asyncpg.Connection,
    args: tuple[Any, ...],
    run_id: UUID,
    record: CognitionPointRecord,
    *,
    frame_keys: tuple[str, ...],
    turn_ref: tuple[str, str] | None,
    thread_frames: _ThreadFrames,
) -> CognitionPointRecord:
    existing = await _fetch(connection, args, record.point_id)
    if existing is not None:
        return existing
    resolved = await _resolve(
        connection,
        args,
        run_id,
        record,
        frame_keys=frame_keys,
        turn_ref=turn_ref,
        thread_frames=thread_frames,
    )
    await _insert(connection, args, run_id, resolved)
    return resolved


async def _resolve(
    connection: asyncpg.Connection,
    args: tuple[Any, ...],
    run_id: UUID,
    record: CognitionPointRecord,
    *,
    frame_keys: tuple[str, ...],
    turn_ref: tuple[str, str] | None,
    thread_frames: _ThreadFrames,
) -> CognitionPointRecord:
    update: dict[str, object] = {}
    if record.parent_point_id is None and record.parent_locator is not None:
        parent = await _find(
            connection, args, run_id, record.coordinate.kind, record.parent_locator
        )
        if parent is not None:
            update["parent_point_id"] = parent.point_id
    if "parent_point_id" not in update:
        cross = cross_cycle_parent(record)
        if cross is not None:
            role, selection = cross
            prior = await _latest(connection, args, run_id, selection)
            if prior is not None:
                linked = with_cross_cycle_parent(record, role, prior)
                update["parent_coordinate"] = linked.parent_coordinate
                update["roles"] = linked.roles
    execution = record.coordinate.harness_execution_id
    if frame_keys and execution is not None and record.frames is None:
        row = await connection.fetchrow(
            f"""
            SELECT min(arrival_ordinal) AS lo, max(arrival_ordinal) AS hi
            FROM mission_control.provider_frame
            WHERE {SCOPE} AND harness_execution_id = $4::uuid AND provider_key = ANY($5::text[])
            """,
            *args,
            execution,
            list(frame_keys),
        )
        if row is not None and row["lo"] is not None:
            update["frames"] = FrameRange(from_ordinal=int(row["lo"]), to_ordinal=int(row["hi"]))
    point = record.coordinate.point
    if (
        "frames" not in update
        and record.frames is None
        and execution is not None
        and isinstance(point, CheckpointPoint)
        and point.key.checkpoint_ns == ""
    ):
        # Tracing Stage 2 (F-S2-6): the recorder of a replacement turn (an
        # `interrupt_and_inject`) never saw the interrupted turn's frames, so those points
        # come without keys; the frames are stored and the key rule the reconciler applies
        # finds them, so the settlement writes the range and a reconcile has nothing to add.
        rows = await thread_frames.rows(connection, args, execution, point.key.thread_id)
        derived = frame_range_of(frames_of_point(record, rows))
        if derived is not None:
            update["frames"] = derived
    if turn_ref is not None:
        # The session row is keyed by the native session (a shared Goal Directed role thread
        # spans executions), so the turn is found by session ref and native turn ref, with the
        # execution the frame writer recorded on the turn's frames as a tie-breaker.
        session_ref = (
            record.coordinate.point.key.thread_id
            if isinstance(record.coordinate.point, CheckpointPoint)
            else record.coordinate.point.locator.split("#", 1)[0]
        )
        turn = await connection.fetchrow(
            """
            SELECT st.turn_id, st.turn_no
            FROM mission_control.session_turn st
            JOIN mission_control.agent_session s
              ON s.installation_id = st.installation_id
             AND s.application_id = st.application_id
             AND s.tenant_id = st.tenant_id
             AND s.session_id = st.session_id
            WHERE st.installation_id = $1 AND st.application_id = $2 AND st.tenant_id = $3
              AND s.native_session_ref = $4 AND st.native_turn_ref = $5
            ORDER BY (s.harness_execution_id = $6::uuid) DESC, st.turn_no DESC LIMIT 1
            """,
            *args,
            session_ref,
            turn_ref[1],
            turn_ref[0],
        )
        if turn is not None:
            update["turn_id"] = str(turn["turn_id"])
            update["coordinate"] = record.coordinate.model_copy(
                update={"turn_no": int(turn["turn_no"])}
            )
    return record.model_copy(update=update) if update else record


async def _insert(
    connection: asyncpg.Connection,
    args: tuple[Any, ...],
    run_id: UUID,
    record: CognitionPointRecord,
) -> None:
    coordinate = record.coordinate
    location = record.location
    attempt = record.attempt
    now = datetime.now(UTC)
    await connection.execute(
        """
        INSERT INTO mission_control.cognition_point (
            installation_id, application_id, tenant_id, point_id, run_id, unit_key,
            execution_generation, family, node_key, iteration, cycle, session_generation,
            lane_profile, point_kind, point_locator, point_ref, parent_point_id,
            parent_coordinate, ordinal, source, roles, harness_execution_id, turn_id, turn_no,
            activity_attempt_observation_id, temporal_workflow_id, temporal_run_id,
            temporal_activity_id, activity_attempt, task_queue, frame_from_ordinal,
            frame_to_ordinal, message_count, channel_facts, files_digest, usage_delta,
            budget_snapshot, workspace_checkpoint_ref, seedable, written_by, record, version,
            recorded_at, created_at, updated_at, created_by_actor_ref,
            subordinate_ref, restore_level
        )
        VALUES ($1, $2, $3, $4::uuid, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15,
                $16::jsonb, $17::uuid, $18::jsonb, $19, $20, $21::text[], $22::uuid, $23::uuid,
                $24, $25::uuid, $26, $27, $28, $29, $30, $31, $32, $33, $34::jsonb, $35,
                $36::jsonb, $37::jsonb, $38, $39, $40, $41::jsonb, $42, $43, $44, $44, $45,
                $46, $47)
        ON CONFLICT (installation_id, application_id, tenant_id, point_id) DO NOTHING
        """,
        *args,
        record.point_id,
        run_id,
        coordinate.unit_key,
        coordinate.execution_generation,
        location.family,
        location.node_key,
        location.iteration,
        location.cycle,
        location.session_generation,
        record.lane_profile,
        coordinate.kind,
        coordinate.locator,
        _dump(coordinate.point.model_dump(mode="json")),
        record.parent_point_id,
        _dump(record.parent_coordinate.model_dump(mode="json"))
        if record.parent_coordinate is not None
        else None,
        record.ordinal,
        record.source,
        list(record.roles),
        coordinate.harness_execution_id,
        record.turn_id,
        coordinate.turn_no,
        _uuid_or_none(attempt.activity_attempt_observation_id) if attempt is not None else None,
        attempt.temporal_workflow_id if attempt is not None else None,
        attempt.temporal_run_id if attempt is not None else None,
        attempt.temporal_activity_id if attempt is not None else None,
        attempt.activity_attempt if attempt is not None else None,
        attempt.task_queue if attempt is not None else None,
        record.frames.from_ordinal if record.frames is not None else None,
        record.frames.to_ordinal if record.frames is not None else None,
        record.message_count,
        _dump(record.channel_facts),
        record.files_digest,
        _dump(record.usage_delta),
        _dump(record.budget_snapshot) if record.budget_snapshot is not None else None,
        record.workspace_checkpoint_ref,
        record.seedable,
        record.written_by,
        _dump(record.model_dump(mode="json")),
        record.version,
        record.recorded_at,
        now,
        POINT_ACTOR,
        record.subordinate_ref,
        record.restore_level or DEFAULT_RESTORE_LEVEL,
    )


async def _latest(
    connection: asyncpg.Connection,
    args: tuple[Any, ...],
    run_id: UUID,
    selection: CognitionPointFilter,
) -> CognitionPointRecord | None:
    """The newest point of the run matching the cross-cycle selection (node, cycle or
    session generation, role), by recording time then step: the prior cycle's result."""

    assert selection.node_key is not None and selection.role is not None
    clauses: list[str] = []
    values: list[Any] = []
    if selection.iteration is not None:
        # Tracing Stage 3 (R1-F7): the prior cycle of the same workflow cycle.
        values.append(selection.iteration)
        clauses.append(f"AND iteration = ${len(values) + 6}")
    if selection.cycle is not None:
        values.append(selection.cycle)
        clauses.append(f"AND cycle = ${len(values) + 6}")
    if selection.session_generation is not None:
        values.append(selection.session_generation)
        clauses.append(f"AND session_generation = ${len(values) + 6}")
    row = await connection.fetchrow(
        f"""
        SELECT record FROM mission_control.cognition_point
        WHERE {SCOPE} AND run_id = $4 AND node_key = $5 AND $6 = ANY(roles)
          {" ".join(clauses)}
        ORDER BY recorded_at DESC, ordinal DESC NULLS LAST, point_locator DESC
        LIMIT 1
        """,
        *args,
        run_id,
        selection.node_key,
        selection.role,
        *values,
    )
    return CognitionPointRecord.model_validate(_load(row["record"])) if row is not None else None


async def _fetch(
    connection: asyncpg.Connection, args: tuple[Any, ...], point_id: str, *, lock: bool = False
) -> CognitionPointRecord | None:
    row = await connection.fetchrow(
        f"""
        SELECT record FROM mission_control.cognition_point
        WHERE {SCOPE} AND point_id = $4::uuid {"FOR UPDATE" if lock else ""}
        """,
        *args,
        point_id,
    )
    return CognitionPointRecord.model_validate(_load(row["record"])) if row is not None else None


async def _find(
    connection: asyncpg.Connection, args: tuple[Any, ...], run_id: UUID, kind: str, locator: str
) -> CognitionPointRecord | None:
    row = await connection.fetchrow(
        f"""
        SELECT record FROM mission_control.cognition_point
        WHERE {SCOPE} AND run_id = $4 AND point_kind = $5 AND point_locator = $6
        ORDER BY recorded_at LIMIT 1
        """,
        *args,
        run_id,
        kind,
        locator,
    )
    return CognitionPointRecord.model_validate(_load(row["record"])) if row is not None else None


class _KeyedRow:
    """A `provider_frame` row as the key rule reads it (`KeyedFrame`)."""

    __slots__ = ("arrival_ordinal", "provider_key")

    def __init__(self, row: asyncpg.Record) -> None:
        self.provider_key = str(row["provider_key"])
        self.arrival_ordinal = int(row["arrival_ordinal"])


def _uuid_or_none(value: str) -> str | None:
    """Attempt observation ids are `activity-attempt:<uuid5>`; the column holds the uuid."""

    candidate = value.rsplit(":", 1)[-1]
    try:
        return str(UUID(candidate))
    except ValueError:
        return None


def _dump(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _load(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


__all__ = [
    "DEFAULT_RESTORE_LEVEL",
    "POINT_ACTOR",
    "PostgresCognitionPointRepository",
    "record_marker_in",
    "record_points_in",
]
