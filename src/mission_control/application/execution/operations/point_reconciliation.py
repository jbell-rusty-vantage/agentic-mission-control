"""The point reconciler (TRACING-PROPOSAL P3.1, TR-D6): `mc.points_reconciliation.v1`.

A settlement writes its transition, its result and its cognition points in one transaction,
so a crash leaves nothing partial. What can still leave the index short is a settlement
that committed before 1.4.4, a test fault (`MISSION_CONTROL_TEST_POINTS_FAULT=skip`), or a
remote saver that answered too late for the frame ranges. The reconciler walks every unit
generation of a run whose checkpoint transition exists and, for each one whose point rows
are missing (none at all) or lack a frame range although frames of the step exist,
re-derives the points through the lane's `TimeTravelLane.collect_points` (the same walk the
settlement folds, over the registered saver), resolves frame ranges from the frame store by
provider key, and records the rows with `written_by = reconciler` (idempotent by point id).
Rows the pruning session marked (`pruned_at`) are reported as `pruned`, never re-derived. A
saver that cannot be read for a unit is reported in `saver_unreachable`, never raised.

Tracing Stage 3 (R2-14): the re-walk is the root lineage only (sync subagents' nested
namespaces need the live recorder), so a budget-bounded walk whose turn wrote nested-namespace
frames stays `incomplete` instead of being marked complete; the rows the bounded walk wrote
(no parent link, an empty usage delta) are completed from the re-walk by explicit
enrichment, never by re-inserting them. Every row whose `parent_locator` now resolves gets
its `parent_point_id` (R1-F7).

Frame ranges without the live recorder: a Deep Agents provider key carries the root
checkpoint id (the finish frames) or the LangGraph step (the streamed deltas); frames whose
key names the point's checkpoint or step, on the same thread and turn, make its range. Whole
`updates` frames carry neither, so a re-derived range is the streamed part of the step only;
the outcome counts what it could fill.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Final, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from mission_control.application.execution.cognition_points import (
    CognitionPointRepository,
    attempt_facts,
    compose_batch,
    cross_cycle_parent,
    latest_point,
    with_cross_cycle_parent,
)
from mission_control.application.execution.harness.time_travel import (
    TimeTravelRegistry,
    TimeTravelUnsupported,
)
from mission_control.application.execution.operations.checkpoint_lineage import (
    CheckpointLineageRepository,
    SettledGeneration,
)
from mission_control.application.frames.sink import FrameReader
from mission_control.domain.execution.checkpoint_lineage import CheckpointLineageError
from mission_control.domain.execution.cognition_points import (
    AttemptFacts,
    CheckpointPoint,
    CognitionPointFilter,
    CognitionPointObservation,
    CognitionPointRecord,
    deep_agents_key_facts,
    frame_range_of,
    frames_of_point,
)
from mission_control.domain.execution.lanes import DEFAULT_LANE_PROFILE
from mission_control.domain.frames.contracts import ProviderFrame
from mission_control.domain.policies.contracts import ActorContext

logger = logging.getLogger(__name__)

POINTS_RECONCILIATION_SCHEMA: Final = "mc.points_reconciliation.v1"
RECONCILE_PERMISSION: Final = "workflow_run.reconcile_unit"
MAX_ROWS_PER_GENERATION: Final = 500


class PointsReconciliation(BaseModel):
    """`mc.points_reconciliation.v1`: what one reconcile pass checked and repaired."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["mc.points_reconciliation.v1"] = POINTS_RECONCILIATION_SCHEMA
    run_id: str = Field(min_length=1, max_length=512)
    generations_checked: int = Field(default=0, ge=0)
    points_added: int = Field(default=0, ge=0)
    frame_ranges_filled: int = Field(default=0, ge=0)
    pruned: int = Field(default=0, ge=0)
    saver_unreachable: tuple[str, ...] = ()
    # 1.4.4 (P6.1): generations whose budget-bounded settlement walk was completed here.
    walks_completed: tuple[str, ...] = ()


class PointReconciliationDenied(PermissionError):
    """The actor lacks `workflow_run.reconcile_unit`."""


class RunIdentityReader(Protocol):
    """The run key -> run UUID read the frame store needs (the mission event reader has it)."""

    async def run_identity(self, request_scope: str, run_key: str) -> UUID | None: ...


class PointReconciler:
    def __init__(
        self,
        *,
        lineage: CheckpointLineageRepository,
        points: CognitionPointRepository,
        time_travel: TimeTravelRegistry | Callable[[], TimeTravelRegistry | None] | None,
        frames: FrameReader | None = None,
        runs: RunIdentityReader | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._lineage = lineage
        self._points = points
        self._time_travel = time_travel
        self._frames = frames
        self._runs = runs
        self._clock = clock or (lambda: datetime.now(UTC))

    async def reconcile(
        self,
        request_scope: str,
        run_id: str,
        *,
        unit_key: str | None = None,
        actor: ActorContext,
    ) -> PointsReconciliation:
        if RECONCILE_PERMISSION not in actor.permissions:
            raise PointReconciliationDenied(f"{RECONCILE_PERMISSION} required")
        generations = [
            item
            for item in await self._lineage.list_run_generations(request_scope, run_id)
            if unit_key is None or item.unit.unit_key == unit_key
        ]
        frames = await self._run_frames(request_scope, run_id) if generations else ()
        outcome = _Outcome()
        for generation in generations:
            await self._reconcile_generation(request_scope, run_id, generation, frames, outcome)
        return PointsReconciliation(
            run_id=run_id,
            generations_checked=len(generations),
            points_added=outcome.added,
            frame_ranges_filled=outcome.filled,
            pruned=outcome.pruned,
            saver_unreachable=tuple(outcome.unreachable),
            walks_completed=tuple(outcome.completed),
        )

    async def _reconcile_generation(
        self,
        request_scope: str,
        run_id: str,
        generation: SettledGeneration,
        frames: Sequence[ProviderFrame],
        outcome: _Outcome,
    ) -> None:
        existing = await self._rows(request_scope, run_id, generation)
        outcome.pruned += sum(1 for row in existing if row.pruned_at is not None)
        live = [row for row in existing if row.pruned_at is None]
        thread_frames = _turn_frames(
            frames, generation.transition.namespace, generation.transition.invocation_id
        )
        # 1.4.4 (P6.1): a result point that records a budget-bounded walk is re-walked
        # whole; the rows it already holds keep their ids and the gap is filled.
        incomplete = [
            row
            for row in live
            if "result" in row.roles and row.channel_facts.get("points_status") == "incomplete"
        ]
        if not existing or incomplete:
            try:
                stored, completed_rows = await self._rederive(
                    request_scope, generation, existing, thread_frames
                )
            except Exception as error:
                # A saver read failing (typed or in a provider-specific way) is a saver
                # problem for this unit: reported, never raised across the run.
                typed = isinstance(error, CheckpointLineageError | TimeTravelUnsupported | OSError)
                logger.warning(
                    "points of %s generation %s could not be re-derived: %s",
                    generation.unit.unit_key,
                    generation.transition.execution_generation,
                    error,
                    exc_info=not typed,
                )
                outcome.unreachable.append(generation.unit.unit_key)
                return
            outcome.added += len(stored)
            outcome.filled += sum(1 for row in stored if row.frames is not None)
            nested = _nested_namespace_frames(
                frames, generation.transition.namespace, generation.transition.invocation_id
            )
            if incomplete and nested and not any(_is_nested(row) for row in live):
                # Tracing Stage 3 (R2-14): the turn ran sync subagents whose nested points
                # only the live recorder can attribute; the walk stays incomplete.
                logger.warning(
                    "points of %s generation %s: the root lineage is complete, %d nested "
                    "subagent frame(s) have no points; the walk stays incomplete",
                    generation.unit.unit_key,
                    generation.transition.execution_generation,
                    len(nested),
                )
            else:
                for row in incomplete:
                    facts = {**row.channel_facts, "points_status": "complete"}
                    await self._points.enrich(request_scope, row.point_id, channel_facts=facts)
                if incomplete:
                    outcome.completed.append(generation.unit.unit_key)
            replaced = {row.point_id for row in (*stored, *completed_rows)}
            live = [
                *(row for row in live if row.point_id not in replaced),
                *stored,
                *completed_rows,
            ]
        else:
            # Existing rows are never re-walked through the saver: a missing range is
            # filled from the keys alone, and a step whose frames carry no key facts
            # keeps `frames = None` rather than an invented range.
            for row in live:
                if row.frames is not None:
                    continue
                derived = frame_range_of(frames_of_point(row, thread_frames))
                if derived is None:
                    continue
                await self._points.enrich(request_scope, row.point_id, frames=derived)
                outcome.filled += 1
        await self._recompute_parents(request_scope, run_id, live)

    # --- one generation -------------------------------------------------------------------

    async def _rederive(
        self,
        request_scope: str,
        generation: SettledGeneration,
        existing: Sequence[CognitionPointRecord],
        thread_frames: Sequence[ProviderFrame],
    ) -> tuple[tuple[CognitionPointRecord, ...], tuple[CognitionPointRecord, ...]]:
        """The rows the re-walk added, and the existing rows of a bounded walk it completed."""

        transition = generation.transition
        unit = generation.unit
        lane_profile = self._lane_profile(existing, thread_frames)
        registry = TimeTravelRegistry.resolve(self._time_travel)
        if registry is None or not registry.supports(lane_profile):
            raise TimeTravelUnsupported(lane_profile)
        lane = registry.lane(lane_profile, request_scope=request_scope)
        execution = _execution_of(thread_frames)
        if lane_profile == DEFAULT_LANE_PROFILE:
            observed = await lane.collect_points(
                namespace=transition.namespace,
                checkpointer_ref_digest=transition.result_key.checkpointer_ref_digest,
                source_locator=(
                    transition.source_key.checkpoint_id
                    if transition.source_key is not None
                    else None
                ),
                result_locator=transition.result_key.checkpoint_id,
            )
        else:
            # K3 convention for session lanes (non-checkpoint points): the namespace is the
            # harness execution id, the "checkpointer digest" the generation, the result
            # locator the settled result row's (the lane re-folds its persisted frames).
            execution = execution or next(
                (
                    row.coordinate.harness_execution_id
                    for row in existing
                    if row.coordinate.harness_execution_id is not None
                ),
                None,
            )
            if execution is None:
                raise TimeTravelUnsupported(lane_profile, reason="harness_execution_unknown")
            result_row = next((row for row in existing if "result" in row.roles), None)
            observed = await lane.collect_points(
                namespace=execution,
                checkpointer_ref_digest=str(transition.execution_generation),
                source_locator=None,
                result_locator=result_row.coordinate.locator if result_row else "",
            )
        attempt = await self._attempt(request_scope, generation)
        attributed = attribute_frames(observed, thread_frames)
        observations: list[CognitionPointObservation] = []
        for observation in observed:
            keys = tuple(frame.provider_key for frame in attributed.get(observation.locator, ()))
            observations.append(
                observation.model_copy(
                    update={
                        "attempt_ref": attempt[1] if attempt is not None else None,
                        "native_turn_ref": transition.invocation_id,
                        "harness_execution_id": execution,
                        "frame_keys": keys,
                    }
                )
            )
        batch = compose_batch(
            observations,
            unit=unit,
            execution_generation=transition.execution_generation,
            lane_profile=lane_profile,
            attempt=attempt[0] if attempt is not None else None,
            written_by="reconciler",
            recorded_at=self._clock(),
        )
        records = tuple(
            record.model_copy(update={"frames": derived})
            if (derived := frame_range_of(attributed.get(record.coordinate.locator, ())))
            is not None
            else record
            for record in batch.records
        )
        known = {row.point_id: row for row in existing}
        stored = await self._points.record(
            request_scope, records, frame_keys=batch.frame_keys, turn_refs=batch.turn_refs
        )
        completed: list[CognitionPointRecord] = []
        for record in records:
            prior = known.get(record.point_id)
            if prior is None or prior.pruned_at is not None:
                continue
            changes = _walk_completion(prior, record)
            if changes:
                completed.append(
                    await self._points.enrich(request_scope, record.point_id, **changes)
                )
        return tuple(row for row in stored if row.point_id not in known), tuple(completed)

    async def _recompute_parents(
        self, request_scope: str, run_id: str, rows: Sequence[CognitionPointRecord]
    ) -> None:
        """P8: a point without any parent whose location is not the first cycle or
        generation gets its `cycle_start` / `rollover_start` parent now that the prior
        result may have settled; a point whose `parent_locator` names a row the index now
        holds gets that row as its `parent_point_id` (Tracing Stage 3, R1-F7)."""

        for row in rows:
            if row.parent_point_id is None and row.parent_locator is not None:
                parent = await self._points.find_point(
                    request_scope, run_id, kind=row.coordinate.kind, locator=row.parent_locator
                )
                if parent is not None and parent.point_id != row.point_id:
                    await self._points.enrich(
                        request_scope, row.point_id, parent_point_id=parent.point_id
                    )
                continue
            cross = cross_cycle_parent(row)
            if cross is None:
                continue
            role, selection = cross
            page = await self._points.list_points(
                request_scope,
                run_id,
                selection=selection,
                limit=MAX_ROWS_PER_GENERATION,
                cursor=None,
            )
            prior = latest_point(page.entries)
            if prior is None:
                continue
            linked = with_cross_cycle_parent(row, role, prior)
            await self._points.enrich(
                request_scope,
                row.point_id,
                parent_coordinate=linked.parent_coordinate,
                roles=linked.roles,
            )

    async def _rows(
        self, request_scope: str, run_id: str, generation: SettledGeneration
    ) -> tuple[CognitionPointRecord, ...]:
        page = await self._points.list_points(
            request_scope,
            run_id,
            selection=CognitionPointFilter(
                unit_key=generation.unit.unit_key,
                execution_generation=generation.transition.execution_generation,
            ),
            limit=MAX_ROWS_PER_GENERATION,
            cursor=None,
        )
        return page.entries

    async def _attempt(
        self, request_scope: str, generation: SettledGeneration
    ) -> tuple[AttemptFacts, str] | None:
        """The attempt facts and the holder ref of the generation's last dispatching attempt."""

        attempts = [
            item
            for item in await self._lineage.list_attempts(request_scope, generation.unit.unit_key)
            if item.execution_generation == generation.transition.execution_generation
        ]
        dispatching = [item for item in attempts if item.dispatching] or attempts
        if not dispatching:
            return None
        last = max(dispatching, key=lambda item: item.attempt.attempt)
        facts = attempt_facts(
            request_scope,
            generation.unit.unit_key,
            generation.transition.execution_generation,
            last.attempt,
        )
        return facts, last.observation_id

    async def _run_frames(self, request_scope: str, run_id: str) -> tuple[ProviderFrame, ...]:
        if self._frames is None or self._runs is None:
            return ()
        identity = await self._runs.run_identity(request_scope, run_id)
        if identity is None:
            return ()
        return await self._frames.frames_for_run(request_scope, identity)

    @staticmethod
    def _lane_profile(
        existing: Sequence[CognitionPointRecord], frames: Sequence[ProviderFrame]
    ) -> str:
        if existing:
            return existing[0].lane_profile
        if frames:
            return frames[0].lane_profile.value
        return DEFAULT_LANE_PROFILE


class _Outcome:
    """What one reconcile pass counted, across its generations."""

    def __init__(self) -> None:
        self.added = 0
        self.filled = 0
        self.pruned = 0
        self.unreachable: list[str] = []
        self.completed: list[str] = []


def _walk_completion(
    prior: CognitionPointRecord, derived: CognitionPointRecord
) -> dict[str, object]:
    """Tracing Stage 3 (R2-14): what a bounded walk's row lacks and the whole re-walk knows
    (the parent link, its walk roles, the usage delta). A row that already has them keeps
    them; enrichment never removes what the settlement recorded."""

    changes: dict[str, object] = {}
    if prior.parent_locator is None and derived.parent_locator is not None:
        changes["parent_locator"] = derived.parent_locator
        if prior.parent_point_id is None and derived.parent_point_id is not None:
            changes["parent_point_id"] = derived.parent_point_id
    missing_roles = tuple(role for role in derived.roles if role not in prior.roles)
    if missing_roles:
        changes["roles"] = (*prior.roles, *missing_roles)
    if not prior.usage_delta and derived.usage_delta:
        changes["usage_delta"] = dict(derived.usage_delta)
    return changes


def _is_nested(row: CognitionPointRecord) -> bool:
    point = row.coordinate.point
    return isinstance(point, CheckpointPoint) and not point.key.is_root


def _nested_namespace_frames(
    frames: Sequence[ProviderFrame], thread: str, invocation_id: str
) -> tuple[ProviderFrame, ...]:
    """Frames of the thread's turn written in a nested (sync subagent) namespace: their key
    is `thread:<ns>:...`, a root frame's `thread::...`."""

    return tuple(
        frame
        for frame in frames
        if frame.provider_key.startswith(f"{thread}:")
        and not frame.provider_key.startswith(f"{thread}::")
        and (frame.native_turn_ref is None or frame.native_turn_ref == invocation_id)
    )


# --- frame attribution without the live recorder ------------------------------------------


def _turn_frames(
    frames: Sequence[ProviderFrame], thread: str, invocation_id: str
) -> tuple[ProviderFrame, ...]:
    """Root-namespace frames of the thread's turn, from the execution that recorded the
    most recent of them (arrival ordinals are per execution and generation)."""

    prefix = f"{thread}::"
    candidates = [
        frame
        for frame in frames
        if frame.provider_key.startswith(prefix)
        and (frame.native_turn_ref is None or frame.native_turn_ref == invocation_id)
    ]
    if not candidates:
        return ()
    latest = max(candidates, key=lambda frame: (frame.observed_at, frame.arrival_ordinal))
    return tuple(
        frame
        for frame in candidates
        if frame.harness_execution_id == latest.harness_execution_id
        and frame.generation == latest.generation
    )


def _execution_of(frames: Sequence[ProviderFrame]) -> str | None:
    return str(frames[0].harness_execution_id) if frames else None


def attribute_frames(
    observed: Sequence[CognitionPointObservation], frames: Sequence[ProviderFrame]
) -> dict[str, tuple[ProviderFrame, ...]]:
    """The frames of each point of one walk (oldest first), keyed by locator.

    By key first: since 1.4.4 every Deep Agents provider key carries the last root
    checkpoint the recorder had seen (the point the frame followed), the step of a streamed
    delta, and the result checkpoint on the finish frames; frames keyed before any checkpoint
    are the input point's begin frames. When no frame of the thread carries a checkpoint
    (frames recorded before 1.4.4), the fallback is time: the frames observed after the
    previous point's checkpoint `ts` and up to this point's belong to this step, the rest to
    the result point. The two rules are never joined (a stream part is consumed after the
    checkpoint it belongs to was created, so time brackets would double-count).
    """

    ordered = sorted(frames, key=lambda frame: frame.arrival_ordinal)
    result: dict[str, list[ProviderFrame]] = {point.locator: [] for point in observed}
    seen: dict[str, set[str]] = {point.locator: set() for point in observed}
    for point in observed:
        for frame in frames_of_point(point, frames):
            if frame.provider_key not in seen[point.locator]:
                seen[point.locator].add(frame.provider_key)
                result[point.locator].append(frame)
    first = observed[0] if observed else None
    keyed = False
    if first is not None and isinstance(first.point, CheckpointPoint):
        thread = first.point.key.thread_id
        for frame in ordered:
            facts = deep_agents_key_facts(frame.provider_key, thread)
            if facts is None:
                continue
            checkpoint_id, step = facts
            if checkpoint_id:
                keyed = True
            elif not step and not any(frame.provider_key in keys for keys in seen.values()):
                # Recorded before the first checkpoint and before any step: the begin
                # frames of the input point.
                seen[first.locator].add(frame.provider_key)
                result[first.locator].append(frame)
    timed = [] if keyed else [point for point in observed if point.native_observed_at is not None]
    if timed:
        previous = None
        for index, point in enumerate(timed):
            upper = point.native_observed_at
            last = index == len(timed) - 1
            for frame in ordered:
                at = frame.observed_at
                if previous is not None and at <= previous:
                    continue
                if not last and upper is not None and at > upper:
                    continue
                if frame.provider_key not in seen[point.locator]:
                    seen[point.locator].add(frame.provider_key)
                    result[point.locator].append(frame)
            previous = upper
    return {
        locator: tuple(sorted(items, key=lambda frame: frame.arrival_ordinal))
        for locator, items in result.items()
    }


__all__ = [
    "POINTS_RECONCILIATION_SCHEMA",
    "RECONCILE_PERMISSION",
    "PointReconciler",
    "PointReconciliationDenied",
    "PointsReconciliation",
    "RunIdentityReader",
    "attribute_frames",
]
