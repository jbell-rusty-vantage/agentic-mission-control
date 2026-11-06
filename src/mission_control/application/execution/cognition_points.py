"""Cognition points: the kernel index of provider lifecycles (P1 turn 4, `mc.cognition_point.v1`).

Ports and the pure composition of point records. The lane returns
`CognitionPointObservation`s with its `RuntimeResult`; the operation settlement composes them
into a `PointBatch` (records with the run, unit location, attempt and writer, plus the frame
keys and turn refs the repository resolves) and the lineage repository stores the batch in
the same transaction as the transition and result, resolving the parent point, the session
turn, the frame range and the cross-cycle parent (`cycle_start`, `rollover_start`) from what
it already holds. Reads page the table; nothing here opens a provider saver (that is the
lane's `read_as_of`).

Tracing Stage 3 (R1-F3): points are evidence. A points write that fails inside the
settlement is rolled back on its own (a savepoint), the transition and the result commit,
and the result point alone is written as the `points_status: incomplete` marker
(`points_write_failed_marker`) that `run inspect` reports and the reconciler repairs.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from mission_control.domain.execution.checkpoint_lineage import (
    OperationActivityAttempt,
    activity_attempt_observation_id,
)
from mission_control.domain.execution.cognition_points import (
    AttemptFacts,
    CognitionCoordinate,
    CognitionPointFilter,
    CognitionPointObservation,
    CognitionPointPage,
    CognitionPointRecord,
    FrameRange,
    PointRole,
    PointWriter,
    location_facts,
    point_id_for,
)
from mission_control.domain.graph_runtime.identities import RuntimeUnitIdentity

DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 500


@dataclass(frozen=True)
class PointBatch:
    """What one settlement writes to the point index, in the settlement's transaction.

    `frame_keys[point_id]` are the provider keys of the frames recorded while the point's
    step ran; `turn_refs[point_id] = (harness_execution_id, native_turn_ref)` names the
    session turn. Every record belongs to one run (the settlement's).
    """

    records: tuple[CognitionPointRecord, ...]
    frame_keys: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    turn_refs: Mapping[str, tuple[str, str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        runs = {record.coordinate.run_id for record in self.records}
        if len(runs) > 1:
            raise ValueError("a point batch belongs to one run")

    @property
    def run_id(self) -> str | None:
        return self.records[0].coordinate.run_id if self.records else None


class CognitionPointRepository(Protocol):
    """The `cognition_point` table: idempotent inserts, enrichment, scoped reads."""

    async def record(
        self,
        request_scope: str,
        records: Sequence[CognitionPointRecord],
        *,
        frame_keys: Mapping[str, tuple[str, ...]],
        turn_refs: Mapping[str, tuple[str, str]],
    ) -> tuple[CognitionPointRecord, ...]:
        """Insert every record once (a replay returns the stored rows), resolving each
        record's parent point from its locator within the run, its session turn from
        `turn_refs[point_id] = (harness_execution_id, native_turn_ref)` and its frame range
        from the provider keys in `frame_keys[point_id]`."""
        ...

    async def list_points(
        self,
        request_scope: str,
        run_id: str,
        *,
        selection: CognitionPointFilter,
        limit: int,
        cursor: str | None,
    ) -> CognitionPointPage: ...

    async def get_point(self, request_scope: str, point_id: str) -> CognitionPointRecord | None: ...

    async def find_point(
        self, request_scope: str, run_id: str, *, kind: str, locator: str
    ) -> CognitionPointRecord | None: ...

    async def enrich(
        self, request_scope: str, point_id: str, **changes: object
    ) -> CognitionPointRecord:
        """Apply enrichment fields (`roles`, `parent_point_id`, `parent_coordinate`, `turn_id`,
        `frames`, `budget_snapshot`, `workspace_checkpoint_ref`, `seedable`, `written_by`),
        advancing the row version by one."""
        ...


def attempt_facts(
    request_scope: str, unit_key: str, execution_generation: int, attempt: OperationActivityAttempt
) -> AttemptFacts:
    return AttemptFacts(
        activity_attempt_observation_id=activity_attempt_observation_id(
            request_scope, unit_key, execution_generation, attempt
        ),
        temporal_workflow_id=attempt.workflow_id,
        temporal_run_id=attempt.workflow_run_id,
        temporal_activity_id=attempt.activity_id,
        activity_attempt=attempt.attempt,
        task_queue=attempt.task_queue,
    )


def compose_points(
    observations: Sequence[CognitionPointObservation],
    *,
    unit: RuntimeUnitIdentity,
    execution_generation: int,
    lane_profile: str,
    attempt: AttemptFacts | None,
    written_by: PointWriter,
    recorded_at: datetime | None = None,
    budget_snapshot: Mapping[str, Any] | None = None,
    parents: Mapping[str, CognitionCoordinate] | None = None,
) -> tuple[CognitionPointRecord, ...]:
    """Pure: the records a settlement writes for one unit generation's observations.

    A parent inside the same unit generation is derived (`parent_locator`); a parent outside it
    (`parent_point`) is resolved by the repository against the run's rows; `parents[locator]`
    names a parent coordinate the caller already knows (a fork's source result point).
    `budget_snapshot` (the settlement's usage and reservation) lands on the result point.
    Duplicated locators are an adapter defect and refused.
    """

    now = recorded_at or datetime.now(UTC)
    location = location_facts(unit)
    records: list[CognitionPointRecord] = []
    seen: set[str] = set()
    for observation in observations:
        locator = observation.locator
        if locator in seen:
            raise ValueError(f"cognition point {locator} observed twice in one invocation")
        seen.add(locator)
        parent_coordinate = parents.get(locator) if parents else None
        # K1 (2026-11-05): a parent of another kind inside the same generation (a session
        # lane's `workspace_snapshot` under its result `session_cursor` point) names it as
        # `parent_point` beside `parent_locator`; the id is derived with the parent's kind.
        parent_kind = (
            observation.parent_point.kind
            if observation.parent_point is not None
            else observation.point.kind
        )
        parent_id = (
            point_id_for(
                unit.belllabs_run_id,
                unit.unit_key,
                execution_generation,
                parent_kind,
                observation.parent_locator,
            )
            if observation.parent_locator is not None
            else None
        )
        records.append(
            CognitionPointRecord(
                point_id=point_id_for(
                    unit.belllabs_run_id,
                    unit.unit_key,
                    execution_generation,
                    observation.point.kind,
                    locator,
                ),
                coordinate=CognitionCoordinate(
                    run_id=unit.belllabs_run_id,
                    unit_key=unit.unit_key,
                    execution_generation=execution_generation,
                    harness_execution_id=observation.harness_execution_id,
                    point=observation.point,
                ),
                lane_profile=lane_profile,
                location=location,
                parent_point_id=parent_id,
                parent_locator=(
                    observation.parent_locator
                    if observation.parent_locator is not None
                    else observation.parent_point.locator
                    if observation.parent_point is not None
                    else None
                ),
                parent_coordinate=parent_coordinate,
                ordinal=observation.ordinal,
                source=observation.source,
                roles=observation.roles,
                attempt=attempt,
                message_count=observation.message_count,
                channel_facts=dict(observation.channel_facts),
                files_digest=observation.files_digest,
                usage_delta=dict(observation.usage_delta),
                budget_snapshot=(
                    dict(budget_snapshot)
                    if budget_snapshot is not None and "result" in observation.roles
                    else None
                ),
                workspace_checkpoint_ref=observation.workspace_checkpoint_ref,
                seedable=observation.seedable,
                written_by=written_by,
                recorded_at=now,
            )
        )
    return tuple(records)


def compose_batch(
    observations: Sequence[CognitionPointObservation],
    *,
    unit: RuntimeUnitIdentity,
    execution_generation: int,
    lane_profile: str,
    attempt: AttemptFacts | None,
    written_by: PointWriter,
    recorded_at: datetime | None = None,
    budget_snapshot: Mapping[str, Any] | None = None,
    parents: Mapping[str, CognitionCoordinate] | None = None,
) -> PointBatch:
    """The records plus the frame keys and turn refs the repository resolves at write time."""

    records = compose_points(
        observations,
        unit=unit,
        execution_generation=execution_generation,
        lane_profile=lane_profile,
        attempt=attempt,
        written_by=written_by,
        recorded_at=recorded_at,
        budget_snapshot=budget_snapshot,
        parents=parents,
    )
    by_id = {
        record.point_id: observation
        for record, observation in zip(records, observations, strict=True)
    }
    return PointBatch(
        records=records,
        frame_keys={
            point_id: item.frame_keys for point_id, item in by_id.items() if item.frame_keys
        },
        turn_refs={
            point_id: (item.harness_execution_id, item.native_turn_ref)
            for point_id, item in by_id.items()
            if item.harness_execution_id is not None and item.native_turn_ref is not None
        },
    )


def points_write_failed_marker(
    batch: PointBatch, error: BaseException
) -> CognitionPointRecord | None:
    """Tracing Stage 3 (R1-F3): the result point of a batch whose write failed, as the
    `points_status: incomplete` marker (no parent link, so it inserts on its own); None
    when the batch has no result point (the reconciler then finds the generation bare)."""

    result = next((record for record in reversed(batch.records) if "result" in record.roles), None)
    if result is None:
        return None
    return result.model_copy(
        update={
            "parent_point_id": None,
            "channel_facts": {
                **result.channel_facts,
                "points_status": "incomplete",
                "points_write_error": type(error).__name__,
            },
        }
    )


def cross_cycle_parent(
    record: CognitionPointRecord,
) -> tuple[PointRole, CognitionPointFilter] | None:
    """P3.8: the role and the selection of the prior cycle's (or generation's) result point.

    A record without any parent (no `parent_point_id`, no `parent_locator`, no
    `parent_coordinate`) whose location is a Stage Graph cycle after the first, or a Goal
    Directed session generation after the first, continues from the latest `result` point of
    the previous cycle or generation of the same node. Deterministic from the location alone;
    `None` when the rule does not apply.
    """

    if record.parent_point_id is not None or record.parent_coordinate is not None:
        return None
    # Tracing Stage 3 (R1-F7): a point that names its parent by locator has a parent (another
    # unit's settled source the index may not hold yet); the reconciler links it later.
    if record.parent_locator is not None:
        return None
    location = record.location
    if location.family == "stage_graph" and location.cycle > 0:
        # The prior cycle of the same stage in the same workflow cycle (R1-F7).
        return "cycle_start", CognitionPointFilter(
            node_key=location.node_key,
            iteration=location.iteration,
            cycle=location.cycle - 1,
            role="result",
        )
    if (
        location.family == "goal_directed"
        and location.session_generation is not None
        and location.session_generation > 1
    ):
        return "rollover_start", CognitionPointFilter(
            node_key=location.node_key,
            session_generation=location.session_generation - 1,
            role="result",
        )
    return None


def with_cross_cycle_parent(
    record: CognitionPointRecord, role: PointRole, parent: CognitionPointRecord
) -> CognitionPointRecord:
    roles = record.roles if role in record.roles else (*record.roles, role)
    return record.model_copy(update={"parent_coordinate": parent.coordinate, "roles": roles})


def latest_point(records: Sequence[CognitionPointRecord]) -> CognitionPointRecord | None:
    """The newest row of a selection: by recording time, then step (the Postgres order)."""

    if not records:
        return None
    return max(
        records,
        key=lambda item: (
            item.recorded_at,
            item.ordinal if item.ordinal is not None else -1,
            item.coordinate.locator,
        ),
    )


def page_size(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_PAGE_SIZE
    return min(max(limit, 1), MAX_PAGE_SIZE)


def encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(json.dumps({"o": offset}).encode("utf-8")).decode("ascii")


def decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")))
        offset = int(payload["o"])
    except (ValueError, KeyError, TypeError) as error:
        raise ValueError("invalid cognition point cursor") from error
    if offset < 0:
        raise ValueError("invalid cognition point cursor")
    return offset


def matches(record: CognitionPointRecord, selection: CognitionPointFilter) -> bool:
    coordinate = record.coordinate
    location = record.location
    return (
        (selection.unit_key is None or coordinate.unit_key == selection.unit_key)
        and (
            selection.execution_generation is None
            or coordinate.execution_generation == selection.execution_generation
        )
        and (selection.node_key is None or location.node_key == selection.node_key)
        and (selection.iteration is None or location.iteration == selection.iteration)
        and (selection.cycle is None or location.cycle == selection.cycle)
        and (
            selection.session_generation is None
            or location.session_generation == selection.session_generation
        )
        and (selection.kind is None or coordinate.kind == selection.kind)
        and (selection.role is None or selection.role in record.roles)
        and (not selection.seedable_only or record.seedable)
    )


def ordered(records: Sequence[CognitionPointRecord]) -> list[CognitionPointRecord]:
    """The listing order: by recording time, then step, then locator (stable across pages)."""

    return sorted(
        records,
        key=lambda item: (
            item.recorded_at,
            item.coordinate.unit_key,
            item.coordinate.execution_generation,
            item.ordinal if item.ordinal is not None else -1,
            item.coordinate.locator,
        ),
    )


class InMemoryCognitionPointRepository:
    """The port over a dict; mirrors the Postgres adapter's resolution rules."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], CognitionPointRecord] = {}
        self.frame_ordinals: dict[str, int] = {}  # provider key -> arrival ordinal (tests seed)
        self.turns: dict[tuple[str, str], tuple[str, int]] = {}  # (execution, turn ref) -> id, no

    async def record(
        self,
        request_scope: str,
        records: Sequence[CognitionPointRecord],
        *,
        frame_keys: Mapping[str, tuple[str, ...]],
        turn_refs: Mapping[str, tuple[str, str]],
    ) -> tuple[CognitionPointRecord, ...]:
        stored: list[CognitionPointRecord] = []
        for record in records:
            key = (request_scope, record.point_id)
            existing = self.rows.get(key)
            if existing is not None:
                stored.append(existing)
                continue
            update: dict[str, object] = {}
            if record.parent_point_id is None and record.parent_locator is not None:
                parent = await self.find_point(
                    request_scope,
                    record.coordinate.run_id,
                    kind=record.coordinate.kind,
                    locator=record.parent_locator,
                )
                if parent is not None:
                    update["parent_point_id"] = parent.point_id
            if "parent_point_id" not in update:
                cross = cross_cycle_parent(record)
                if cross is not None:
                    role, selection = cross
                    prior = latest_point(
                        [
                            row
                            for (scope, _), row in self.rows.items()
                            if scope == request_scope
                            and row.coordinate.run_id == record.coordinate.run_id
                            and matches(row, selection)
                        ]
                    )
                    if prior is not None:
                        linked = with_cross_cycle_parent(record, role, prior)
                        update["parent_coordinate"] = linked.parent_coordinate
                        update["roles"] = linked.roles
            ordinals = sorted(
                self.frame_ordinals[frame]
                for frame in frame_keys.get(record.point_id, ())
                if frame in self.frame_ordinals
            )
            if ordinals and record.frames is None:
                update["frames"] = FrameRange(from_ordinal=ordinals[0], to_ordinal=ordinals[-1])
            turn = turn_refs.get(record.point_id)
            if turn is not None and turn in self.turns:
                turn_id, turn_no = self.turns[turn]
                update["turn_id"] = turn_id
                update["coordinate"] = record.coordinate.model_copy(update={"turn_no": turn_no})
            row = record.model_copy(update=update)
            self.rows[key] = row
            stored.append(row)
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
        rows = ordered(
            [
                row
                for (scope, _), row in self.rows.items()
                if scope == request_scope
                and row.coordinate.run_id == run_id
                and matches(row, selection)
            ]
        )
        size = page_size(limit)
        entries = rows[offset : offset + size]
        next_cursor = encode_cursor(offset + size) if offset + size < len(rows) else None
        return CognitionPointPage(run_id=run_id, entries=tuple(entries), next_cursor=next_cursor)

    async def get_point(self, request_scope: str, point_id: str) -> CognitionPointRecord | None:
        return self.rows.get((request_scope, point_id))

    async def find_point(
        self, request_scope: str, run_id: str, *, kind: str, locator: str
    ) -> CognitionPointRecord | None:
        for (scope, _), row in self.rows.items():
            if (
                scope == request_scope
                and row.coordinate.run_id == run_id
                and row.coordinate.kind == kind
                and row.coordinate.locator == locator
            ):
                return row
        return None

    async def enrich(
        self, request_scope: str, point_id: str, **changes: object
    ) -> CognitionPointRecord:
        row = self.rows[(request_scope, point_id)]
        updated = row.model_copy(update={**changes, "version": row.version + 1})
        self.rows[(request_scope, point_id)] = updated
        return updated


__all__ = [
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "CognitionPointRepository",
    "InMemoryCognitionPointRepository",
    "PointBatch",
    "attempt_facts",
    "compose_batch",
    "compose_points",
    "cross_cycle_parent",
    "decode_cursor",
    "encode_cursor",
    "latest_point",
    "matches",
    "ordered",
    "page_size",
    "points_write_failed_marker",
    "with_cross_cycle_parent",
]
