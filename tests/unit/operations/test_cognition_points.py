"""`mc.cognition_point.v1` composition and the in-memory index (P1 turn 4, WP-1; 1.4.4 TR-D6:
the settlement transaction, the cross-cycle parents, the result point's budget snapshot).

Tracing Stage 3 (R1-F3): a points write that fails inside the settlement costs the points,
not the settlement: the transition and the result commit and the result point alone is the
`points_status: incomplete` marker. (R1-F7): the cross-cycle rule applies only to a point
that names no parent, within its workflow cycle."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta

import pytest

from mission_control.application.execution.cognition_points import (
    InMemoryCognitionPointRepository,
    PointBatch,
    attempt_facts,
    compose_batch,
    compose_points,
    decode_cursor,
    encode_cursor,
)
from mission_control.application.execution.operations.checkpoint_lineage import (
    CheckpointLineageService,
    InMemoryCheckpointLineageRepository,
    UnitAttempt,
    lease_holder_id,
)
from mission_control.domain.execution.checkpoint_lineage import (
    CheckpointCapture,
    CheckpointInvocationPlan,
    OperationActivityAttempt,
    cognitive_session_namespace,
    submission_invocation_id,
)
from mission_control.domain.execution.cognition_points import (
    CheckpointPoint,
    CognitionPointFilter,
    CognitionPointObservation,
    CognitionPointRecord,
    location_facts,
    point_id_for,
)
from mission_control.domain.graph_runtime.identities import (
    GoalDirectedUnitLocation,
    QualifiedCheckpointKey,
    RuntimeUnitIdentity,
    StageGraphUnitLocation,
)
from tests.fixtures.checkpoint_lineage import BINDING, SCHEMA, namespace_claim

SCOPE = "mc/0192a4f0-0000-7000-8000-00000000b10e/biotech/9287e246-224b-5814-bc00-44bb5396e0c5"
DIGEST = "sha256:" + "ab" * 32
RUN = "84341b2b-8825-57b0-9b05-c0a4497e3ae4"
NOW = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)


def goal_unit(iteration: int = 2, role: str = "executor", session: int = 1) -> RuntimeUnitIdentity:
    return RuntimeUnitIdentity(
        request_scope=SCOPE,
        belllabs_run_id=RUN,
        execution_epoch=1,
        family="goal_directed",
        unit_kind="goal_executor" if role == "executor" else "goal_verifier",
        semantic_operation_id=f"goal-iteration/{iteration}/{role}",
        semantic_attempt=1,
        location=GoalDirectedUnitLocation(
            goal_iteration=iteration,
            goal_revision_id="goal-revision:1",
            operation_role=role,  # type: ignore[arg-type]
            agent_run=iteration,
            session_generation=session,
        ),
    )


def stage_unit(
    stage: str = "review", cycle: int = 1, workflow_cycle: int = 0
) -> RuntimeUnitIdentity:
    return RuntimeUnitIdentity(
        request_scope=SCOPE,
        belllabs_run_id=RUN,
        execution_epoch=1,
        family="stage_graph",
        unit_kind="stage_operation",
        semantic_operation_id=f"stage:{stage}:cycle:{cycle}:workflow:{workflow_cycle}",
        semantic_attempt=1,
        location=StageGraphUnitLocation(
            stage_id=stage,
            mapped_instance_id="NO_MAPPED_INSTANCE",
            workflow_cycle_ordinal=workflow_cycle,
            stage_cycle_ordinal=cycle,
            operation_slot_id="main",
        ),
    )


def key(thread: str, checkpoint: str, parent: str | None) -> QualifiedCheckpointKey:
    return QualifiedCheckpointKey(
        checkpointer_ref_digest=DIGEST,
        thread_id=thread,
        checkpoint_id=checkpoint,
        parent_checkpoint_id=parent,
    )


def observations(thread: str, *, source_id: str | None) -> tuple[CognitionPointObservation, ...]:
    first = CognitionPointObservation(
        point=CheckpointPoint(key=key(thread, "cp-10", source_id)),
        parent_locator=None,
        parent_point=CheckpointPoint(key=key(thread, source_id, "cp-8")) if source_id else None,
        ordinal=10,
        source="input",
        roles=("input",),
        attempt_ref="activity-attempt:11111111-1111-5111-8111-111111111111",
        harness_execution_id="22222222-2222-4222-8222-222222222222",
        native_turn_ref="turn-ref",
        frame_keys=("k1", "k2"),
        message_count=3,
        channel_facts={"message_count": 3},
        usage_delta={"tokens.total_tokens": 20},
        seedable=True,
    )
    second = first.model_copy(
        update={
            "point": CheckpointPoint(key=key(thread, "cp-11", "cp-10")),
            "parent_locator": "cp-10",
            "parent_point": None,
            "ordinal": 11,
            "source": "loop",
            "roles": ("leaf", "result"),
            "frame_keys": ("k3",),
            "message_count": 4,
        }
    )
    return first, second


def attempt() -> OperationActivityAttempt:
    return OperationActivityAttempt(
        workflow_id="mc/run/operation/1",
        workflow_run_id="run-1",
        activity_id="1",
        attempt=1,
        worker_identity="worker-a",
        task_queue="mc.biotech.cognitive",
    )


def test_location_facts_denormalize_both_families() -> None:
    goal = location_facts(goal_unit(iteration=3, role="verifier", session=2))
    assert (goal.family, goal.node_key, goal.iteration, goal.cycle, goal.session_generation) == (
        "goal_directed",
        "verifier",
        3,
        0,
        2,
    )
    stage = location_facts(stage_unit("draft", cycle=2))
    assert (stage.family, stage.node_key, stage.iteration, stage.cycle) == (
        "stage_graph",
        "draft",
        0,
        2,
    )
    assert stage.session_generation is None


def test_compose_points_derives_ids_parents_and_attempt_facts() -> None:
    unit = goal_unit()
    facts = attempt_facts(SCOPE, unit.unit_key, 1, attempt())
    records = compose_points(
        observations("thread-a", source_id="cp-9"),
        unit=unit,
        execution_generation=1,
        lane_profile="deep_agents",
        attempt=facts,
        written_by="adapter",
        recorded_at=datetime(2026, 10, 21, tzinfo=UTC),
    )
    first, second = records
    assert first.point_id == point_id_for(RUN, unit.unit_key, 1, "checkpoint", "cp-10")
    assert first.parent_point_id is None and first.parent_locator == "cp-9"
    assert second.parent_point_id == first.point_id and second.parent_locator == "cp-10"
    assert first.attempt is not None and first.attempt.task_queue == "mc.biotech.cognitive"
    assert first.attempt.activity_attempt_observation_id.startswith("activity-attempt:")
    assert first.coordinate.harness_execution_id == "22222222-2222-4222-8222-222222222222"
    assert first.location.iteration == 2 and first.location.node_key == "executor"
    assert CognitionPointRecord.model_validate(first.model_dump(mode="json")) == first


def test_compose_points_refuses_a_locator_observed_twice() -> None:
    unit = goal_unit()
    first, _second = observations("thread-a", source_id=None)
    with pytest.raises(ValueError, match="observed twice"):
        compose_points(
            (first, first),
            unit=unit,
            execution_generation=1,
            lane_profile="deep_agents",
            attempt=None,
            written_by="adapter",
        )


@pytest.mark.asyncio
async def test_in_memory_repository_resolves_parent_turn_and_frames_and_pages() -> None:
    repository = InMemoryCognitionPointRepository()
    repository.frame_ordinals = {"k1": 7, "k2": 9, "k3": 12}
    repository.turns[("22222222-2222-4222-8222-222222222222", "turn-ref")] = ("turn-uuid", 2)
    # Iteration 1's result is already a point of the run (another unit, same thread).
    previous = goal_unit(iteration=1)
    (prior,) = compose_points(
        (
            CognitionPointObservation(
                point=CheckpointPoint(key=key("thread-a", "cp-9", "cp-8")),
                ordinal=9,
                roles=("leaf", "result"),
                seedable=True,
            ),
        ),
        unit=previous,
        execution_generation=1,
        lane_profile="deep_agents",
        attempt=None,
        written_by="adapter",
        recorded_at=datetime(2026, 10, 21, 0, 0, 1, tzinfo=UTC),
    )
    await repository.record(SCOPE, [prior], frame_keys={}, turn_refs={})
    unit = goal_unit(iteration=2)
    records = compose_points(
        observations("thread-a", source_id="cp-9"),
        unit=unit,
        execution_generation=1,
        lane_profile="deep_agents",
        attempt=None,
        written_by="adapter",
        recorded_at=datetime(2026, 10, 21, 0, 0, 2, tzinfo=UTC),
    )
    frame_keys = {records[0].point_id: ("k1", "k2"), records[1].point_id: ("k3",)}
    turn_refs = {
        record.point_id: ("22222222-2222-4222-8222-222222222222", "turn-ref") for record in records
    }
    stored = await repository.record(SCOPE, records, frame_keys=frame_keys, turn_refs=turn_refs)
    first, second = stored
    # The lineage root's parent is the previous unit's result, found by locator in the run.
    assert first.parent_point_id == prior.point_id
    assert first.frames is not None and (first.frames.from_ordinal, first.frames.to_ordinal) == (
        7,
        9,
    )
    assert second.frames is not None and second.frames.to_ordinal == 12
    assert first.turn_id == "turn-uuid" and first.coordinate.turn_no == 2
    # A replayed settlement finds its rows instead of writing twice.
    again = await repository.record(SCOPE, records, frame_keys=frame_keys, turn_refs=turn_refs)
    assert again == stored
    page = await repository.list_points(
        SCOPE, RUN, selection=CognitionPointFilter(iteration=2), limit=1, cursor=None
    )
    assert [item.coordinate.locator for item in page.entries] == ["cp-10"]
    assert page.next_cursor is not None and decode_cursor(page.next_cursor) == 1
    rest = await repository.list_points(
        SCOPE, RUN, selection=CognitionPointFilter(iteration=2), limit=1, cursor=page.next_cursor
    )
    assert [item.coordinate.locator for item in rest.entries] == ["cp-11"]
    assert rest.next_cursor is None
    results = await repository.list_points(
        SCOPE, RUN, selection=CognitionPointFilter(role="result"), limit=10, cursor=None
    )
    assert [item.coordinate.locator for item in results.entries] == ["cp-9", "cp-11"]
    other_run = await repository.list_points(
        SCOPE, "other-run", selection=CognitionPointFilter(), limit=10, cursor=None
    )
    assert other_run.entries == ()
    enriched = await repository.enrich(
        SCOPE, second.point_id, roles=("leaf", "result", "fork_seed")
    )
    assert enriched.version == 2 and "fork_seed" in enriched.roles
    assert decode_cursor(encode_cursor(5)) == 5
    with pytest.raises(ValueError):
        decode_cursor("not-a-cursor")


# --- 1.4.4 (TR-D6): the settlement transaction ---------------------------------------------


def lineage(thread: str, prefix: str) -> tuple[CognitionPointObservation, ...]:
    """Two root checkpoints of one invocation on `thread`: the input and the result."""

    root = CognitionPointObservation(
        point=CheckpointPoint(key=key(thread, f"{prefix}-a", None)),
        ordinal=0,
        source="input",
        roles=("input",),
        seedable=True,
    )
    result = CognitionPointObservation(
        point=CheckpointPoint(key=key(thread, f"{prefix}-b", f"{prefix}-a")),
        parent_locator=f"{prefix}-a",
        ordinal=1,
        source="loop",
        roles=("leaf", "result"),
        workspace_checkpoint_ref=f"workspace-candidates://{prefix}#sha256:00",
        seedable=True,
    )
    return root, result


class RaisingPointRepository(InMemoryCognitionPointRepository):
    """A point index whose batch write fails after writing part of it (`fail_marker` fails
    the one-record marker write too)."""

    def __init__(self, *, fail_marker: bool = False) -> None:
        super().__init__()
        self.fail_marker = fail_marker

    async def record(
        self,
        request_scope: str,
        records: Sequence[CognitionPointRecord],
        *,
        frame_keys: Mapping[str, tuple[str, ...]],
        turn_refs: Mapping[str, tuple[str, str]],
    ) -> tuple[CognitionPointRecord, ...]:
        if len(records) == 1 and not self.fail_marker:
            return await super().record(
                request_scope, records, frame_keys=frame_keys, turn_refs=turn_refs
            )
        await super().record(request_scope, records[:1], frame_keys={}, turn_refs={})
        raise RuntimeError("points store down")


async def settle(
    repository: InMemoryCheckpointLineageRepository,
    service: CheckpointLineageService,
    unit: RuntimeUnitIdentity,
    observed: tuple[CognitionPointObservation, ...],
    *,
    budget_snapshot: dict[str, object] | None = None,
) -> object:
    """Admit one attempt and settle it the way `operation_execution._settle` does."""

    claim = namespace_claim(unit)
    admission = await repository.record_attempt(
        unit=unit,
        execution_generation=1,
        attempt=attempt(),
        binding_id=f"binding:{unit.unit_key}:1",
        binding_digest=BINDING,
        namespace=claim,
        dispatching=True,
        observed_at=NOW,
        lease_expires_at=NOW + timedelta(minutes=5),
    )
    admitted = UnitAttempt(
        unit=unit,
        execution_generation=1,
        attempt=attempt(),
        holder=lease_holder_id(SCOPE, unit.unit_key, 1, attempt()),
        admission=admission,
        namespace=claim,
        deep_binding=None,
    )
    namespace = cognitive_session_namespace(unit, 1)
    plan = CheckpointInvocationPlan(
        request_scope=SCOPE,
        unit_key=unit.unit_key,
        execution_generation=1,
        claim_fence=admitted.fence,
        namespace=namespace,
        invocation_id=submission_invocation_id(unit.unit_key, 1),
        expected_source=None,
        checkpointer_ref_digest=DIGEST,
        binding_digest=BINDING,
        state_schema_digest=SCHEMA,
        attempt_ref=admitted.holder,
    )
    result_point = observed[-1].point
    assert isinstance(result_point, CheckpointPoint)
    capture = CheckpointCapture(
        namespace=namespace,
        invocation_id=plan.invocation_id,
        source_key=None,
        result_key=result_point.key,
        ancestry_verified=True,
        stamped_checkpoint_count=len(observed),
        redacted_summary_digest=DIGEST,
    )
    return await service.record_result(
        admitted,
        binding_id=f"binding:{unit.unit_key}:1",
        settlement_id=f"settlement:{unit.unit_key}:1",
        status="completed",
        result_manifest_ref=f"manifest:{unit.unit_key}:1",
        result_manifest_digest=DIGEST,
        result_manifest_size_bytes=64,
        plan=plan,
        capture=capture,
        points=observed,
        lane_profile="deep_agents",
        budget_snapshot=budget_snapshot,
    )


@pytest.mark.asyncio
async def test_settlement_writes_transition_result_and_points_in_one_call() -> None:
    points = InMemoryCognitionPointRepository()
    repository = InMemoryCheckpointLineageRepository(points=points)
    service = CheckpointLineageService(repository, clock=lambda: NOW)
    unit = stage_unit("draft", cycle=0)
    namespace = cognitive_session_namespace(unit, 1)
    observed = lineage(namespace, "draft")
    snapshot = {"usage": {"amounts": {"tokens.total": 7}}, "reservation_id": "reservation:x"}

    recorded = await settle(repository, service, unit, observed, budget_snapshot=snapshot)

    assert repository.transitions[(SCOPE, unit.unit_key, 1)].result_key.checkpoint_id == "draft-b"
    assert repository.results[(SCOPE, unit.unit_key, 1)] == recorded
    page = await points.list_points(
        SCOPE, RUN, selection=CognitionPointFilter(), limit=10, cursor=None
    )
    root, result = page.entries
    assert (root.coordinate.locator, result.coordinate.locator) == ("draft-a", "draft-b")
    assert {root.written_by, result.written_by} == {"adapter"}
    assert result.parent_point_id == root.point_id
    # The result point carries the settlement's usage and reservation, the attempt facts and
    # the workspace candidates the lane registered; the input point carries no snapshot.
    assert result.budget_snapshot == snapshot and root.budget_snapshot is None
    assert result.workspace_checkpoint_ref == "workspace-candidates://draft#sha256:00"
    assert result.attempt is not None and result.attempt.activity_attempt == 1
    assert service.points is points
    # A replayed settlement is the duplicate write: nothing is added or changed.
    again = await settle(repository, service, unit, observed, budget_snapshot=snapshot)
    assert again == recorded and len(points.rows) == 2


@pytest.mark.asyncio
async def test_a_points_write_failure_settles_and_leaves_the_incomplete_marker() -> None:
    """Tracing Stage 3 (R1-F3): points are evidence; the settlement commits."""

    points = RaisingPointRepository()
    repository = InMemoryCheckpointLineageRepository(points=points)
    service = CheckpointLineageService(repository, clock=lambda: NOW)
    unit = stage_unit("draft", cycle=0)
    namespace = cognitive_session_namespace(unit, 1)

    recorded = await settle(repository, service, unit, lineage(namespace, "draft"))

    assert repository.results[(SCOPE, unit.unit_key, 1)] == recorded
    assert repository.transitions[(SCOPE, unit.unit_key, 1)].result_key.checkpoint_id == "draft-b"
    head = await repository.get_namespace_head(SCOPE, namespace)
    assert head is not None and head.checkpoint_id == "draft-b"
    # The partial batch rolled back; the result point alone is the marker the reconciler reads.
    (marker,) = points.rows.values()
    assert marker.coordinate.locator == "draft-b" and "result" in marker.roles
    assert marker.parent_point_id is None
    assert marker.channel_facts["points_status"] == "incomplete"
    assert marker.channel_facts["points_write_error"] == "RuntimeError"


@pytest.mark.asyncio
async def test_a_failed_marker_still_settles_with_no_rows() -> None:
    points = RaisingPointRepository(fail_marker=True)
    repository = InMemoryCheckpointLineageRepository(points=points)
    service = CheckpointLineageService(repository, clock=lambda: NOW)
    unit = stage_unit("draft", cycle=0)

    await settle(repository, service, unit, lineage(cognitive_session_namespace(unit, 1), "draft"))

    assert (SCOPE, unit.unit_key, 1) in repository.results
    assert points.rows == {}


@pytest.mark.asyncio
async def test_observations_that_cannot_compose_cost_the_points_not_the_settlement() -> None:
    """Tracing Stage 3 (R1-F3): a locator observed twice is an adapter defect; the settlement
    commits without rows and the reconciler re-derives the generation."""

    points = InMemoryCognitionPointRepository()
    repository = InMemoryCheckpointLineageRepository(points=points)
    service = CheckpointLineageService(repository, clock=lambda: NOW)
    unit = stage_unit("draft", cycle=0)
    root, result = lineage(cognitive_session_namespace(unit, 1), "draft")

    await settle(repository, service, unit, (root, root, result))

    assert (SCOPE, unit.unit_key, 1) in repository.results
    assert points.rows == {}


@pytest.mark.asyncio
async def test_cross_cycle_parents_are_derived_from_the_location_alone() -> None:
    repository = InMemoryCognitionPointRepository()

    async def record(
        unit: RuntimeUnitIdentity, prefix: str, at: datetime
    ) -> tuple[CognitionPointRecord, ...]:
        records = compose_points(
            lineage(cognitive_session_namespace(unit, 1), prefix),
            unit=unit,
            execution_generation=1,
            lane_profile="deep_agents",
            attempt=None,
            written_by="adapter",
            recorded_at=at,
        )
        return await repository.record(SCOPE, records, frame_keys={}, turn_refs={})

    # Stage Graph: cycle 1's first point continues from cycle 0's result (`cycle_start`).
    first_root, first_result = await record(stage_unit("review", cycle=0), "c0", NOW)
    assert first_root.parent_coordinate is None and "cycle_start" not in first_root.roles
    second_root, second_result = await record(
        stage_unit("review", cycle=1), "c1", NOW + timedelta(seconds=1)
    )
    assert second_root.parent_coordinate == first_result.coordinate
    assert second_root.roles == ("input", "cycle_start")
    assert second_result.parent_point_id == second_root.point_id
    assert second_result.parent_coordinate is None and "cycle_start" not in second_result.roles
    # The latest result of the prior cycle wins: cycle 2 links to cycle 1's result, not 0's.
    third_root, _ = await record(stage_unit("review", cycle=2), "c2", NOW + timedelta(seconds=2))
    assert third_root.parent_coordinate == second_result.coordinate
    # Another stage's cycle 1 has no prior cycle of its own node: no parent, no role.
    other_root, _ = await record(stage_unit("draft", cycle=1), "d1", NOW + timedelta(seconds=3))
    assert other_root.parent_coordinate is None and "cycle_start" not in other_root.roles
    # Tracing Stage 3 (R1-F7): the prior cycle is the same workflow cycle's; workflow cycle 1's
    # stage cycle 1 does not continue from workflow cycle 0's stage cycle 0.
    next_round, _ = await record(
        stage_unit("review", cycle=1, workflow_cycle=1), "w1", NOW + timedelta(seconds=3)
    )
    assert next_round.parent_coordinate is None and "cycle_start" not in next_round.roles

    # Goal Directed: session generation 2's first point continues from generation 1's
    # result of the same role (`rollover_start`).
    g1_root, g1_result = await record(goal_unit(iteration=1, session=1), "g1", NOW)
    assert g1_root.parent_coordinate is None and "rollover_start" not in g1_root.roles
    g2_root, _ = await record(goal_unit(iteration=2, session=2), "g2", NOW + timedelta(seconds=4))
    assert g2_root.parent_coordinate == g1_result.coordinate
    assert g2_root.roles == ("input", "rollover_start")
    verifier_root, _ = await record(
        goal_unit(iteration=2, role="verifier", session=2), "v2", NOW + timedelta(seconds=5)
    )
    assert verifier_root.parent_coordinate is None


@pytest.mark.asyncio
async def test_a_point_naming_an_unrecorded_parent_gets_no_cross_cycle_parent() -> None:
    """Tracing Stage 3 (R1-F7): a first point whose parent (another unit's source) is not
    indexed yet keeps its `parent_locator` for the reconciler, never a cycle-start guess."""

    repository = InMemoryCognitionPointRepository()
    prior = compose_points(
        lineage(cognitive_session_namespace(stage_unit("review", cycle=0), 1), "c0"),
        unit=stage_unit("review", cycle=0),
        execution_generation=1,
        lane_profile="deep_agents",
        attempt=None,
        written_by="adapter",
        recorded_at=NOW,
    )
    await repository.record(SCOPE, prior, frame_keys={}, turn_refs={})
    unit = stage_unit("review", cycle=1)
    first, _second = observations(cognitive_session_namespace(unit, 1), source_id="elsewhere")
    (record,) = await repository.record(
        SCOPE,
        compose_points(
            (first,),
            unit=unit,
            execution_generation=1,
            lane_profile="deep_agents",
            attempt=None,
            written_by="adapter",
            recorded_at=NOW + timedelta(seconds=1),
        ),
        frame_keys={},
        turn_refs={},
    )
    assert record.parent_locator == "elsewhere" and record.parent_point_id is None
    assert record.parent_coordinate is None and "cycle_start" not in record.roles


def test_compose_points_snapshot_and_batch_shape() -> None:
    unit = stage_unit("draft", cycle=0)
    namespace = cognitive_session_namespace(unit, 1)
    observed = lineage(namespace, "draft")
    batch = compose_batch(
        observed,
        unit=unit,
        execution_generation=1,
        lane_profile="deep_agents",
        attempt=None,
        written_by="reconciler",
        recorded_at=NOW,
        budget_snapshot={"usage": {"amounts": {}}, "reservation_id": "r"},
    )
    root, result = batch.records
    assert batch.run_id == RUN and batch.frame_keys == {} and batch.turn_refs == {}
    assert result.budget_snapshot == {"usage": {"amounts": {}}, "reservation_id": "r"}
    assert root.budget_snapshot is None and result.written_by == "reconciler"
    other = RuntimeUnitIdentity(
        request_scope=SCOPE,
        belllabs_run_id="other-run",
        execution_epoch=1,
        family="stage_graph",
        unit_kind="stage_operation",
        semantic_operation_id="stage:draft:cycle:0",
        semantic_attempt=1,
        location=StageGraphUnitLocation(
            stage_id="draft",
            mapped_instance_id="NO_MAPPED_INSTANCE",
            workflow_cycle_ordinal=0,
            stage_cycle_ordinal=0,
            operation_slot_id="main",
        ),
    )
    (foreign,) = compose_points(
        lineage(cognitive_session_namespace(other, 1), "x")[:1],
        unit=other,
        execution_generation=1,
        lane_profile="deep_agents",
        attempt=None,
        written_by="adapter",
        recorded_at=NOW,
    )
    with pytest.raises(ValueError, match="one run"):
        PointBatch(records=(root, foreign))


# --- K1 (cross-provider control, 2026-11-05): a session lane's batch without a transition --


@pytest.mark.asyncio
async def test_a_session_cursor_batch_is_written_with_the_result_without_a_transition() -> None:
    """A Session Lane settles with no checkpoint transition (no LangGraph namespace): its
    `session_cursor` points are written in the same `record_result` as the result row,
    keyed by the lane's native session, turn and step, with the session turn resolved from
    `(harness_execution_id, native_turn_ref)` and the frame range from the provider keys."""

    from mission_control.domain.execution.cognition_points import SessionCursorPoint

    points = InMemoryCognitionPointRepository()
    points.frame_ordinals = {"bridge:run-1:4": 4, "bridge:run-1:5": 5, "bridge:run-1:11": 11}
    points.turns[("22222222-2222-4222-8222-222222222222", "run-1")] = ("turn-uuid", 1)
    repository = InMemoryCheckpointLineageRepository(points=points)
    service = CheckpointLineageService(repository, clock=lambda: NOW)
    unit = stage_unit("implement", cycle=0)
    admission = await repository.record_attempt(
        unit=unit,
        execution_generation=1,
        attempt=attempt(),
        binding_id=f"binding:{unit.unit_key}:1",
        binding_digest=BINDING,
        namespace=None,
        dispatching=True,
        observed_at=NOW,
        lease_expires_at=NOW + timedelta(minutes=5),
    )
    admitted = UnitAttempt(
        unit=unit,
        execution_generation=1,
        attempt=attempt(),
        holder=lease_holder_id(SCOPE, unit.unit_key, 1, attempt()),
        admission=admission,
        namespace=None,
        deep_binding=None,
    )

    def step(ref: str, keys: tuple[str, ...], **changes: object) -> CognitionPointObservation:
        return CognitionPointObservation.model_validate(
            {
                "point": SessionCursorPoint(session_ref="agent-1", turn_ref="run-1", step_ref=ref),
                "harness_execution_id": "22222222-2222-4222-8222-222222222222",
                "native_turn_ref": "run-1",
                "frame_keys": keys,
                "seedable": True,
                **changes,
            }
        )

    observed = (
        step("4", ("bridge:run-1:4",), ordinal=0, source="input", roles=("intermediate",)),
        step(
            "11",
            ("bridge:run-1:5", "bridge:run-1:11"),
            ordinal=1,
            source="loop",
            roles=("leaf", "result"),
            parent_locator="agent-1#run-1#4",
        ),
    )
    recorded = await service.record_result(
        admitted,
        binding_id=f"binding:{unit.unit_key}:1",
        settlement_id=f"settlement:{unit.unit_key}:1",
        status="completed",
        result_manifest_ref=f"manifest:{unit.unit_key}:1",
        result_manifest_digest=DIGEST,
        result_manifest_size_bytes=64,
        points=observed,
        lane_profile="cursor_local",
    )
    assert recorded.checkpoint_transition_id is None
    assert (SCOPE, unit.unit_key, 1) not in repository.transitions
    page = await points.list_points(
        SCOPE, RUN, selection=CognitionPointFilter(kind="session_cursor"), limit=10, cursor=None
    )
    first, result = page.entries
    assert (first.coordinate.locator, result.coordinate.locator) == (
        "agent-1#run-1#4",
        "agent-1#run-1#11",
    )
    assert first.lane_profile == "cursor_local" and result.parent_point_id == first.point_id
    assert result.turn_id == "turn-uuid" and result.coordinate.turn_no == 1
    assert result.frames is not None and (result.frames.from_ordinal, result.frames.to_ordinal) == (
        5,
        11,
    )
    assert result.attempt is not None and result.attempt.task_queue == "mc.biotech.cognitive"
    assert {row.written_by for row in page.entries} == {"adapter"}
    # A replayed settlement finds its rows instead of writing twice.
    again = await service.record_result(
        admitted,
        binding_id=f"binding:{unit.unit_key}:1",
        settlement_id=f"settlement:{unit.unit_key}:1",
        status="completed",
        result_manifest_ref=f"manifest:{unit.unit_key}:1",
        result_manifest_digest=DIGEST,
        result_manifest_size_bytes=64,
        points=observed,
        lane_profile="cursor_local",
    )
    assert again == recorded and len(points.rows) == 2
