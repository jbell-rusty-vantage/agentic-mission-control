"""The point reconciler over the in-memory repositories and a fake lane (TR-D6, P3.1).

A settled unit generation whose point rows are missing is re-derived through the lane's
`collect_points`, its frame ranges resolved from the frame store by provider key, and
recorded with `written_by = reconciler`; a complete generation is left alone; a saver that
cannot be read lands in `saver_unreachable`; pruned rows are counted, never re-derived.
Tracing Stage 3 completes a bounded walk's rows from the re-walk, keeps a walk over nested
subagent frames incomplete (R2-14) and links a row whose parent locator now resolves (R1-F7).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid5

import pytest

from mission_control.application.execution.cognition_points import (
    InMemoryCognitionPointRepository,
    compose_batch,
)
from mission_control.application.execution.harness.time_travel import TimeTravelRegistry
from mission_control.application.execution.operations.checkpoint_lineage import (
    InMemoryCheckpointLineageRepository,
)
from mission_control.application.execution.operations.point_reconciliation import (
    PointReconciler,
    PointReconciliationDenied,
    PointsReconciliation,
)
from mission_control.domain.execution.checkpoint_lineage import (
    CheckpointLineageInDoubt,
    cognitive_session_namespace,
    submission_invocation_id,
)
from mission_control.domain.execution.cognition_points import (
    CheckpointPoint,
    CognitionPointFilter,
    CognitionPointObservation,
)
from mission_control.domain.frames.contracts import (
    FrameKind,
    FrameScope,
    LaneProfile,
    ProviderFrame,
)
from mission_control.domain.graph_runtime.identities import (
    QualifiedCheckpointKey,
    RuntimeUnitIdentity,
    StageGraphUnitLocation,
)
from mission_control.domain.policies.contracts import ActorContext
from tests.fixtures.checkpoint_lineage import (
    BINDING,
    activity_attempt,
    namespace_claim,
    transition,
    unit_result,
)

SCOPE = "mc/0192a4f0-0000-7000-8000-00000000b10e/biotech/9287e246-224b-5814-bc00-44bb5396e0c5"
RUN = "84341b2b-8825-57b0-9b05-c0a4497e3ae4"
RUN_UUID = UUID("84341b2b-8825-57b0-9b05-c0a4497e3ae4")
DIGEST = "sha256:" + "c" * 64  # the fixture's CHECKPOINTER digest
NOW = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
ACTOR = ActorContext(actor_id="operator", permissions=frozenset({"workflow_run.reconcile_unit"}))
EXECUTION = UUID("22222222-2222-4222-8222-222222222222")


def stage_unit(stage: str, cycle: int = 0) -> RuntimeUnitIdentity:
    return RuntimeUnitIdentity(
        request_scope=SCOPE,
        belllabs_run_id=RUN,
        execution_epoch=1,
        family="stage_graph",
        unit_kind="stage_operation",
        semantic_operation_id=f"stage:{stage}:cycle:{cycle}",
        semantic_attempt=1,
        location=StageGraphUnitLocation(
            stage_id=stage,
            mapped_instance_id="NO_MAPPED_INSTANCE",
            workflow_cycle_ordinal=0,
            stage_cycle_ordinal=cycle,
            operation_slot_id="main",
        ),
    )


def observations(thread: str, prefix: str) -> tuple[CognitionPointObservation, ...]:
    """What the lane's walk yields for a two-checkpoint invocation (result `{prefix}-b`)."""

    return (
        CognitionPointObservation(
            point=CheckpointPoint(
                key=QualifiedCheckpointKey(
                    checkpointer_ref_digest=DIGEST, thread_id=thread, checkpoint_id=f"{prefix}-a"
                )
            ),
            ordinal=0,
            source="input",
            roles=("input",),
            message_count=1,
            seedable=True,
        ),
        CognitionPointObservation(
            point=CheckpointPoint(
                key=QualifiedCheckpointKey(
                    checkpointer_ref_digest=DIGEST,
                    thread_id=thread,
                    checkpoint_id=f"{prefix}-b",
                    parent_checkpoint_id=f"{prefix}-a",
                )
            ),
            parent_locator=f"{prefix}-a",
            ordinal=1,
            source="loop",
            roles=("leaf", "result"),
            message_count=2,
            seedable=True,
        ),
    )


class FakeLane:
    """`TimeTravelLane` whose `collect_points` answers from a script, or fails per result."""

    lane_profile = "deep_agents"

    def __init__(self) -> None:
        self.scripted: dict[str, tuple[CognitionPointObservation, ...]] = {}
        self.unreachable: set[str] = set()
        self.calls: list[tuple[str, str | None, str]] = []

    async def read_as_of(self, record: Any) -> Any:
        raise NotImplementedError

    async def seed_fork(self, request: Any) -> Any:
        raise NotImplementedError

    async def collect_points(
        self,
        *,
        namespace: str,
        checkpointer_ref_digest: str,
        source_locator: str | None,
        result_locator: str,
    ) -> tuple[CognitionPointObservation, ...]:
        assert checkpointer_ref_digest == DIGEST
        self.calls.append((namespace, source_locator, result_locator))
        if result_locator in self.unreachable:
            raise CheckpointLineageInDoubt("the saver is unreachable", reason="missing_checkpoint")
        return self.scripted[result_locator]


class FakeFrames:
    def __init__(self, frames: tuple[ProviderFrame, ...] = ()) -> None:
        self.frames = frames

    async def frames_for_run(
        self, request_scope: str, run_id: UUID, *, closing_only: bool = False, limit: int = 10_000
    ) -> tuple[ProviderFrame, ...]:
        assert request_scope == SCOPE and run_id == RUN_UUID
        return self.frames

    async def frames_for_execution(self, *args: Any, **kwargs: Any) -> tuple[ProviderFrame, ...]:
        raise NotImplementedError

    async def current_generation(self, *args: Any, **kwargs: Any) -> int | None:
        raise NotImplementedError


class FakeRuns:
    async def run_identity(self, request_scope: str, run_key: str) -> UUID | None:
        return RUN_UUID if run_key == RUN else None


def frame(
    thread: str,
    ordinal: int,
    *,
    step: int | None,
    checkpoint_id: str = "",
    kind: FrameKind = FrameKind.MESSAGE_DELTA,
    turn: str | None = None,
) -> ProviderFrame:
    """A Deep Agents frame keyed `thread::checkpoint_id:step:item:kind`."""

    key = f"{thread}::{checkpoint_id}:{'' if step is None else step}:item-{ordinal}:{kind.value}"
    return ProviderFrame(
        frame_id=uuid5(RUN_UUID, f"frame:{ordinal}"),
        scope=FrameScope.from_request_scope(SCOPE),
        run_id=RUN_UUID,
        activation_id=uuid5(RUN_UUID, "activation"),
        attempt_no=1,
        harness_execution_id=EXECUTION,
        generation=1,
        lane_profile=LaneProfile.DEEP_AGENTS,
        native_session_ref=thread,
        native_turn_ref=turn,
        provider_key=key,
        arrival_ordinal=ordinal,
        observed_at=NOW + timedelta(seconds=ordinal),
        kind=kind,
        closing=kind == FrameKind.RUN_RESULT,
        body_digest="sha256:" + "0" * 64,
        body_bytes=2,
        body_media_type="application/json",
        body_excerpt="{}",
        raw_kind="fixture",
    )


class World:
    def __init__(self) -> None:
        self.points = InMemoryCognitionPointRepository()
        self.lineage = InMemoryCheckpointLineageRepository(points=self.points)
        self.lane = FakeLane()
        self.frames = FakeFrames()
        self.reconciler = PointReconciler(
            lineage=self.lineage,
            points=self.points,
            time_travel=TimeTravelRegistry({"deep_agents": self.lane}),  # type: ignore[dict-item]
            frames=self.frames,
            runs=FakeRuns(),
            clock=lambda: NOW + timedelta(minutes=1),
        )

    async def settle(
        self, unit: RuntimeUnitIdentity, prefix: str, *, with_points: bool
    ) -> tuple[CognitionPointObservation, ...]:
        """Admit and settle one generation; `with_points` writes its rows, else leaves the gap."""

        await self.lineage.record_attempt(
            unit=unit,
            execution_generation=1,
            attempt=activity_attempt(1),
            binding_id=f"binding:{unit.unit_key}:1",
            binding_digest=BINDING,
            namespace=namespace_claim(unit),
            dispatching=True,
            observed_at=NOW,
            lease_expires_at=NOW + timedelta(minutes=5),
        )
        thread = cognitive_session_namespace(unit, 1)
        observed = observations(thread, prefix)
        linked = transition(unit, source=None, result_id=f"{prefix}-b")
        linked = linked.model_copy(
            update={
                "result_key": linked.result_key.model_copy(
                    update={"parent_checkpoint_id": f"{prefix}-a"}
                )
            }
        )
        batch = (
            compose_batch(
                observed,
                unit=unit,
                execution_generation=1,
                lane_profile="deep_agents",
                attempt=None,
                written_by="adapter",
                recorded_at=NOW,
            )
            if with_points
            else None
        )
        await self.lineage.record_result(
            unit_result(unit, fence=1, transition_id=linked.transition_id),
            transition=linked,
            points=batch,
        )
        self.lane.scripted[f"{prefix}-b"] = observed
        return observed

    async def rows(self, unit: RuntimeUnitIdentity) -> list[Any]:
        page = await self.points.list_points(
            SCOPE,
            RUN,
            selection=CognitionPointFilter(unit_key=unit.unit_key),
            limit=50,
            cursor=None,
        )
        return list(page.entries)

    async def reconcile(self, unit_key: str | None = None) -> PointsReconciliation:
        return await self.reconciler.reconcile(SCOPE, RUN, unit_key=unit_key, actor=ACTOR)


@pytest.mark.asyncio
async def test_missing_points_are_rederived_with_frame_ranges_and_written_by_reconciler() -> None:
    world = World()
    draft = stage_unit("draft")
    await world.settle(draft, "d", with_points=False)
    thread = cognitive_session_namespace(draft, 1)
    turn = submission_invocation_id(draft.unit_key, 1)
    world.frames.frames = (
        frame(thread, 1, step=0, turn=turn),
        frame(thread, 2, step=0, turn=turn),
        frame(thread, 3, step=1, turn=turn),
        frame(thread, 4, step=None, checkpoint_id="d-b", kind=FrameKind.RUN_RESULT, turn=turn),
        frame("another-thread", 5, step=1, turn=turn),
    )
    assert await world.rows(draft) == []

    outcome = await world.reconcile()

    assert outcome == PointsReconciliation(
        run_id=RUN, generations_checked=1, points_added=2, frame_ranges_filled=2
    )
    assert world.lane.calls == [(thread, None, "d-b")]
    root, result = await world.rows(draft)
    assert (root.coordinate.locator, result.coordinate.locator) == ("d-a", "d-b")
    assert {root.written_by, result.written_by} == {"reconciler"}
    assert result.parent_point_id == root.point_id
    assert (root.frames.from_ordinal, root.frames.to_ordinal) == (1, 2)
    assert (result.frames.from_ordinal, result.frames.to_ordinal) == (3, 4)
    assert root.coordinate.harness_execution_id == str(EXECUTION)
    assert root.attempt is not None and root.attempt.activity_attempt == 1
    assert root.location.node_key == "draft" and root.lane_profile == "deep_agents"
    # Idempotent: a second pass finds the rows and adds nothing.
    again = await world.reconcile()
    assert again == PointsReconciliation(run_id=RUN, generations_checked=1)
    assert len(world.lane.calls) == 1


@pytest.mark.asyncio
async def test_a_complete_generation_is_left_untouched() -> None:
    world = World()
    draft = stage_unit("draft")
    await world.settle(draft, "d", with_points=True)
    before = await world.rows(draft)

    outcome = await world.reconcile()

    assert outcome == PointsReconciliation(run_id=RUN, generations_checked=1)
    assert await world.rows(draft) == before
    assert {row.written_by for row in before} == {"adapter"}
    assert world.lane.calls == []


@pytest.mark.asyncio
async def test_an_unreachable_saver_is_reported_per_unit_never_raised() -> None:
    world = World()
    draft, review = stage_unit("draft"), stage_unit("review")
    await world.settle(draft, "d", with_points=False)
    await world.settle(review, "r", with_points=False)
    world.lane.unreachable.add("d-b")

    outcome = await world.reconcile()

    assert outcome.generations_checked == 2
    assert outcome.saver_unreachable == (draft.unit_key,)
    assert outcome.points_added == 2
    assert await world.rows(draft) == []
    assert [row.coordinate.locator for row in await world.rows(review)] == ["r-a", "r-b"]


@pytest.mark.asyncio
async def test_frame_ranges_of_existing_rows_are_filled_and_parents_recomputed() -> None:
    world = World()
    first = stage_unit("review", cycle=0)
    second = stage_unit("review", cycle=1)
    # Cycle 1 settled (with rows) before cycle 0's result was indexed: its root has no parent.
    await world.settle(second, "c1", with_points=True)
    await world.settle(first, "c0", with_points=True)
    root, result = await world.rows(second)
    assert root.parent_coordinate is None and root.frames is None
    thread = cognitive_session_namespace(second, 1)
    turn = submission_invocation_id(second.unit_key, 1)
    world.frames.frames = (frame(thread, 7, step=1, turn=turn), frame(thread, 8, step=1, turn=turn))

    outcome = await world.reconcile(unit_key=second.unit_key)

    assert outcome == PointsReconciliation(run_id=RUN, generations_checked=1, frame_ranges_filled=1)
    root, result = await world.rows(second)
    assert result.frames is not None and (result.frames.from_ordinal, result.frames.to_ordinal) == (
        7,
        8,
    )
    assert root.frames is None  # no frame of step 0 exists: nothing invented
    prior = (await world.rows(first))[1]
    assert root.parent_coordinate == prior.coordinate and "cycle_start" in root.roles
    assert world.lane.calls == []


@pytest.mark.asyncio
async def test_pruned_rows_are_counted_and_never_rederived() -> None:
    world = World()
    draft = stage_unit("draft")
    await world.settle(draft, "d", with_points=True)
    for row in await world.rows(draft):
        await world.points.enrich(SCOPE, row.point_id, pruned_at=NOW)

    outcome = await world.reconcile()

    assert outcome == PointsReconciliation(run_id=RUN, generations_checked=1, pruned=2)
    assert world.lane.calls == []


@pytest.mark.asyncio
async def test_reconcile_requires_the_reconcile_permission_and_narrows_by_unit() -> None:
    world = World()
    draft, review = stage_unit("draft"), stage_unit("review")
    await world.settle(draft, "d", with_points=False)
    await world.settle(review, "r", with_points=False)
    with pytest.raises(PointReconciliationDenied):
        await world.reconciler.reconcile(
            SCOPE,
            RUN,
            actor=ActorContext(actor_id="reader", permissions=frozenset({"workflow_run.read"})),
        )
    outcome = await world.reconcile(unit_key=review.unit_key)
    assert outcome.generations_checked == 1 and outcome.points_added == 2
    assert await world.rows(draft) == []
    assert await world.reconcile() == PointsReconciliation(
        run_id=RUN, generations_checked=2, points_added=2
    )


# --- 1.4.4 (P6.1): a budget-bounded settlement walk is completed by the reconciler ----------


@pytest.mark.asyncio
async def test_an_incomplete_settlement_walk_is_completed_and_the_result_point_cleared() -> None:
    world = World()
    draft = stage_unit("draft")
    observed = await world.settle(draft, "d", with_points=True)
    rows = await world.rows(draft)
    result = next(row for row in rows if "result" in row.roles)
    root = next(row for row in rows if "input" in row.roles)
    # The settlement ran out of budget after the result point: the root row is missing and
    # the result records the gap (what `walk_points` writes under `budget_seconds`).
    world.points.rows.pop((SCOPE, root.point_id))
    await world.points.enrich(
        SCOPE,
        result.point_id,
        channel_facts={**result.channel_facts, "points_status": "incomplete", "points_walked": 1},
    )
    assert [row.coordinate.locator for row in await world.rows(draft)] == ["d-b"]

    outcome = await world.reconcile()

    assert outcome.points_added == 1
    assert outcome.walks_completed == (draft.unit_key,)
    assert outcome.saver_unreachable == ()
    assert world.lane.calls == [(cognitive_session_namespace(draft, 1), None, "d-b")]
    after = {row.coordinate.locator: row for row in await world.rows(draft)}
    assert set(after) == {"d-a", "d-b"}
    assert after["d-b"].channel_facts["points_status"] == "complete"
    assert after["d-b"].point_id == result.point_id
    assert after["d-a"].written_by == "reconciler"
    assert after["d-b"].parent_point_id == after["d-a"].point_id
    assert len(observed) == 2
    # Idempotent: a complete generation is left alone.
    again = await world.reconcile()
    assert again.points_added == 0 and again.walks_completed == ()
    assert len(world.lane.calls) == 1


# --- Tracing Stage 3 (R2-14, R1-F7) -------------------------------------------------------


async def _bounded_walk(world: World, unit: RuntimeUnitIdentity, prefix: str) -> Any:
    """Settle `unit` and leave its rows the way a budget-bounded walk writes them: the root
    missing, the result with no parent link and no usage delta, marked incomplete."""

    observed = await world.settle(unit, prefix, with_points=True)
    world.lane.scripted[f"{prefix}-b"] = (
        observed[0],
        observed[1].model_copy(update={"usage_delta": {"tokens.total_tokens": 9}}),
    )
    rows = await world.rows(unit)
    result = next(row for row in rows if "result" in row.roles)
    root = next(row for row in rows if "input" in row.roles)
    world.points.rows.pop((SCOPE, root.point_id))
    world.points.rows[(SCOPE, result.point_id)] = result.model_copy(
        update={
            "parent_point_id": None,
            "parent_locator": None,
            "usage_delta": {},
            "roles": ("result",),
            "channel_facts": {**result.channel_facts, "points_status": "incomplete"},
        }
    )
    return result


@pytest.mark.asyncio
async def test_a_bounded_walks_rows_are_completed_from_the_rewalk() -> None:
    """The result row the bounded walk wrote gets its parent link, walk roles and usage delta
    from the re-walk (explicit enrichment; the insert stays insert-only)."""

    world = World()
    draft = stage_unit("draft")
    result = await _bounded_walk(world, draft, "d")

    outcome = await world.reconcile()

    assert outcome.points_added == 1 and outcome.walks_completed == (draft.unit_key,)
    after = {row.coordinate.locator: row for row in await world.rows(draft)}
    completed = after["d-b"]
    assert completed.point_id == result.point_id
    assert completed.parent_locator == "d-a"
    assert completed.parent_point_id == after["d-a"].point_id
    assert completed.roles == ("result", "leaf")
    assert completed.usage_delta == {"tokens.total_tokens": 9}
    assert completed.channel_facts["points_status"] == "complete"


@pytest.mark.asyncio
async def test_a_bounded_walk_over_nested_subagent_frames_stays_incomplete() -> None:
    """The re-walk is the root lineage only; nested-namespace frames of the turn mean sync
    subagent points it cannot attribute, so the walk is not marked complete."""

    world = World()
    draft = stage_unit("draft")
    await _bounded_walk(world, draft, "d")
    thread = cognitive_session_namespace(draft, 1)
    turn = submission_invocation_id(draft.unit_key, 1)
    nested = frame(thread, 9, step=2, turn=turn)
    world.frames.frames = (
        nested.model_copy(
            update={"provider_key": f"{thread}:tools:task-1:child-cp:2:item-9:message_delta"}
        ),
    )

    outcome = await world.reconcile()

    assert outcome.points_added == 1 and outcome.walks_completed == ()
    after = {row.coordinate.locator: row for row in await world.rows(draft)}
    assert after["d-b"].channel_facts["points_status"] == "incomplete"
    assert after["d-b"].parent_point_id == after["d-a"].point_id


@pytest.mark.asyncio
async def test_a_parent_locator_that_now_resolves_links_the_row() -> None:
    """R1-F7: a point recorded before its parent (another unit's settled source) gets the
    parent's id once the index holds it."""

    world = World()
    draft, review = stage_unit("draft"), stage_unit("review")
    observed = await world.settle(review, "r", with_points=True)
    root = next(row for row in await world.rows(review) if "input" in row.roles)
    world.points.rows[(SCOPE, root.point_id)] = root.model_copy(
        update={"parent_locator": "d-b", "parent_point_id": None}
    )
    await world.settle(draft, "d", with_points=True)
    assert len(observed) == 2

    await world.reconcile(unit_key=review.unit_key)

    linked = next(row for row in await world.rows(review) if "input" in row.roles)
    source = next(row for row in await world.rows(draft) if "result" in row.roles)
    assert linked.parent_point_id == source.point_id
    assert linked.parent_coordinate is None and "cycle_start" not in linked.roles
