"""WP-TR-4 (TRACING-PROPOSAL §P5): the precise fork's policy and preparation, in memory.

Frontier closure under `close` and `strict` (TR-D12), the start position of the derived run
(TR-D13), the Goal Directed reuse by iteration under the minted revision (TR-D14) and the
message delivery decided by the seed (P5.1), over the fork fixtures and the tracing blueprint
(`S1 -> S2 -> {S3, S4}`). Tracing Stage 3 adds the refusals and defaults of the adversarial
review: an unclosed frontier is recorded unclosed (R2-15), every stage outside the closure
starts at the source's cycle (R2-7/8), the Goal Directed position checks (R2-4, R2-5, R2-9,
R2-10), the seed checks (R2-6, R2-13), the re-taken snapshot (R2-11) and the source baseline
default (F-S2-10).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from tests.fixtures.rrm009_production_stack import tracing_stage_blueprint
from tests.fixtures.run_forks import (
    NOW,
    fork_actor,
    fork_command,
    technical_snapshot,
)

from mission_control.application.execution.cognition_points import (
    InMemoryCognitionPointRepository,
)
from mission_control.application.execution.operations.checkpoint_lineage import (
    InMemoryCheckpointLineageRepository,
)
from mission_control.application.recovery.cognitive_seed import CognitiveSeedService
from mission_control.application.recovery.run_forks import (
    ForkCommand,
    ForkRejected,
    InMemoryRunSnapshotRepository,
    SemanticForkService,
    _fork_position,
    _message_delivery,
)
from mission_control.contracts.contracts import ContentRef, InlineText
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import StageGraphBlueprint
from mission_control.domain.execution.cognition_points import (
    CheckpointPoint,
    CognitionCoordinate,
    CognitionPointRecord,
    location_facts,
    point_id_for,
)
from mission_control.domain.graph_runtime.identities import (
    GoalDirectedUnitLocation,
    QualifiedCheckpointKey,
    RuntimeUnitIdentity,
)
from mission_control.domain.policies.forks import (
    BudgetFrontier,
    CognitiveSeed,
    FamilyPosition,
    ForkAt,
    ForkPatchChange,
    ReuseCandidate,
    RunSnapshotManifest,
    compute_reuse_decisions,
    derived_goal_revision_id,
    derived_unit_identity,
    snapshot_id_for,
)
from mission_control.domain.programs.contracts import (
    ExecutionIdentity,
    StageCandidateIdentity,
    StageExecutionIdentity,
    StageGraphStartPosition,
)
from mission_control.domain.programs.dependencies import closed_frontier, stage_descendants
from mission_control.domain.programs.interpreter import (
    StageGraphExecutionError,
    StageGraphInterpreter,
)
from mission_control.domain.programs.runtime_units import goal_runtime_unit, stage_runtime_unit

SCOPE = "tenant-1"
SOURCE = "run-source"
DIGEST = "sha256:" + "a" * 64


def stage_unit(stage_id: str, cycle: int) -> RuntimeUnitIdentity:
    return stage_runtime_unit(
        SCOPE,
        StageExecutionIdentity(
            run_id=SOURCE,
            execution_epoch=1,
            candidate=StageCandidateIdentity(
                stage_id=stage_id,
                mapped_instance_presence=0,
                mapped_instance_id="NO_MAPPED_INSTANCE",
                workflow_cycle_ordinal=0,
                stage_cycle_ordinal=cycle,
                operation_slot_id="execute",
            ),
            semantic_attempt=1,
        ),
    )


def goal_unit(
    iteration: int, role: str, agent_run: int, *, revision: str, session: int = 1
) -> RuntimeUnitIdentity:
    return goal_runtime_unit(
        request_scope=SCOPE,
        run_id=SOURCE,
        execution_epoch=1,
        operation_id=f"goal-iteration:{iteration}:{role}",
        operation_attempt=1,
        goal_iteration=iteration,
        goal_revision_id=revision,
        operation_role=role,  # type: ignore[arg-type]
        agent_run=agent_run,
        session_generation=session,
    )


def candidate(unit: RuntimeUnitIdentity, name: str) -> ReuseCandidate:
    return ReuseCandidate(
        unit=unit,
        unit_key=unit.unit_key,
        execution_generation=1,
        binding_id=f"binding:{name}",
        binding_digest=sha256_digest(f"binding:{name}"),
        state_schema_digest=sha256_digest("schema"),
        settlement_id=f"settlement:{name}",
        result_manifest_ref=f"s3://technical/{name}/manifest",
        result_manifest_digest=sha256_digest(f"manifest:{name}"),
        result_manifest_size_bytes=128,
        result_checkpoint=QualifiedCheckpointKey(
            checkpointer_ref_digest=DIGEST,
            thread_id=f"thread:{name}",
            checkpoint_ns="",
            checkpoint_id=f"result-{name}",
            parent_checkpoint_id=None,
        ),
    )


class StaticBlueprints:
    def __init__(self, blueprint: StageGraphBlueprint | None) -> None:
        self.blueprint = blueprint
        self.calls = 0

    async def stage_blueprint(self, request_scope: str, snapshot: RunSnapshotManifest) -> Any:
        self.calls += 1
        return self.blueprint


class NoSaga:
    """The saga's preparation reads (prepare never forks): no persisted request, and the
    source run's admitted baseline (F-S2-10)."""

    def __init__(self, baseline: dict[str, int] | None = None) -> None:
        self.baseline = baseline
        self.persisted: Any = None

    async def fork(self, request: Any) -> Any:
        raise AssertionError("prepare never runs the saga")

    async def persisted_request(self, request_scope: str, request_id: str) -> Any:
        return self.persisted

    async def source_baseline(self, request_scope: str, run_id: str) -> dict[str, int] | None:
        return self.baseline


def tracing_snapshot(
    *cycles: tuple[str, int],
    objective: str | None = None,
    objectives: dict[str, str] | None = None,
) -> RunSnapshotManifest:
    """A Stage Graph snapshot of the tracing run with one settled candidate per (stage, cycle)."""

    candidates = tuple(
        candidate(stage_unit(stage, cycle), f"{stage}-c{cycle}") for stage, cycle in cycles
    )
    snapshot = technical_snapshot(SOURCE, request_scope=SCOPE, candidates=candidates)
    reached: dict[str, int] = {}
    for stage, cycle in cycles:
        reached[stage] = max(reached.get(stage, 0), cycle)
    position = snapshot.family_position.model_copy(
        update={
            "accepted_stage_ids": tuple(sorted(reached)),
            "stage_cycle_ordinals": reached,
            "stage_objectives": {
                **({"S2": objective} if objective else {}),
                **(objectives or {}),
            },
        }
    )
    values = snapshot.model_dump(mode="python", exclude={"snapshot_digest", "schema_version"})
    values["family_position"] = position
    return RunSnapshotManifest.create(**values)


def goal_snapshot(
    revision: str, *iterations: int, revisions: dict[int, str] | None = None
) -> RunSnapshotManifest:
    """A Goal Directed snapshot whose executor and verifier of each iteration settled
    (`revisions[iteration]` overrides the revision an iteration ran under; the head runs
    under `revision`)."""

    from tests.unit.run_control.test_run_control import request as run_request

    candidates = []
    agent_run = 1
    for iteration in iterations:
        for role in ("executor", "verifier"):
            candidates.append(
                candidate(
                    goal_unit(
                        iteration,
                        role,
                        agent_run,
                        revision=(revisions or {}).get(iteration, revision),
                    ),
                    f"i{iteration}-{role}",
                )
            )
            agent_run += 1
    admitted = run_request(request_scope=SCOPE)
    boundary_ref = "family-head:goal_directed:goal.2.verifier.1"
    return RunSnapshotManifest.create(
        snapshot_id=snapshot_id_for(SCOPE, SOURCE, 3, boundary_ref),
        request_scope=SCOPE,
        source_run_id=SOURCE,
        execution_epoch=1,
        family="goal_directed",
        projection_version=3,
        run_phase="active",
        effective_configuration_digest=admitted.effective_configuration_digest,
        workflow_type_ref=admitted.workflow_type_ref,
        input_manifest=admitted.input_manifest,
        obligation_revision="obligations:1",
        evidence_frontier_digest=sha256_digest("frontier"),
        boundary_kind="goal_verifier_settled",
        boundary_ref=boundary_ref,
        family_position=FamilyPosition(
            family="goal_directed",
            family_kind="goal_directed",
            family_version=4,
            head_mutation_id="goal.2.verifier.1",
            head_mutation_kind="decision",
            head_mutation_fingerprint=sha256_digest("head"),
            goal_revision_id=revision,
            goal_revision_digest=sha256_digest(revision),
            goal_iteration=max(iterations),
            head_operation_role="verifier",
        ),
        reuse_candidates=tuple(sorted(candidates, key=lambda item: item.unit_key)),
        budget_frontier=BudgetFrontier(
            account_id=f"budget-account:{SOURCE}",
            limits=admitted.budget_envelope.dimensions,
            reservation_ids=("baseline",),
        ),
        taken_at=NOW,
    )


def service(
    blueprint: StageGraphBlueprint | None,
    *,
    baseline: dict[str, int] | None = None,
    reader: bool = True,
) -> tuple[SemanticForkService, StaticBlueprints]:
    snapshots = InMemoryRunSnapshotRepository()
    blueprints = StaticBlueprints(blueprint)
    return (
        SemanticForkService(
            snapshots=snapshots,
            saga=NoSaga(baseline),  # type: ignore[arg-type]
            blueprints=blueprints if reader else None,
        ),
        blueprints,
    )


async def prepared(
    forks: SemanticForkService, snapshot: RunSnapshotManifest, command: ForkCommand
) -> Any:
    await forks._snapshots.put(snapshot)  # type: ignore[attr-defined]
    return await forks.prepare(command)


# --- The closure rule ------------------------------------------------------------------------


def test_stage_descendants_follow_every_consumer_edge() -> None:
    blueprint = tracing_stage_blueprint()
    assert stage_descendants(blueprint, ["S2"]) == frozenset({"S3", "S4"})
    assert stage_descendants(blueprint, ["S1"]) == frozenset({"S2", "S3", "S4"})
    assert stage_descendants(blueprint, ["S4"]) == frozenset()
    assert closed_frontier(blueprint, ["S2"]) == frozenset({"S2", "S3", "S4"})
    # The interpreter's own invalidation uses the same map.
    interpreter = StageGraphInterpreter(blueprint, effective_max_concurrency=1)
    assert interpreter.descendants == {
        "S1": frozenset({"S2", "S3", "S4"}),
        "S2": frozenset({"S3", "S4"}),
        "S3": frozenset(),
        "S4": frozenset(),
    }


@pytest.mark.asyncio
async def test_close_records_the_closure_and_reuses_only_the_stages_outside_it() -> None:
    forks, reader = service(tracing_stage_blueprint())
    snapshot = tracing_snapshot(("S1", 0), ("S2", 0), ("S2", 1), ("S2", 2), ("S3", 2), ("S4", 2))
    request = await prepared(forks, snapshot, fork_command(snapshot, invalidation_frontier=("S2",)))
    assert reader.calls == 1
    assert request.frontier_requested == ("S2",)
    assert request.frontier_closed == ("S2", "S3", "S4")
    assert request.patch.invalidation_frontier == ("S2", "S3", "S4")
    decisions = {item.source_unit_key: item.decision for item in request.reuse_decisions}
    assert decisions[stage_unit("S1", 0).unit_key] == "reuse"
    assert all(
        decision == "invalidated"
        for key, decision in decisions.items()
        if key != stage_unit("S1", 0).unit_key
    )
    assert request.at is None and request.start_position is None
    assert request.message_delivery == "none"


@pytest.mark.asyncio
async def test_strict_refuses_a_frontier_narrower_than_its_closure() -> None:
    forks, _reader = service(tracing_stage_blueprint())
    snapshot = tracing_snapshot(("S1", 0), ("S2", 0), ("S3", 0), ("S4", 0))
    command = fork_command(snapshot, invalidation_frontier=("S2",)).model_copy(
        update={"frontier_policy": "strict"}
    )
    with pytest.raises(ForkRejected) as refused:
        await prepared(forks, snapshot, command)
    assert refused.value.code == "frontier_not_closed"
    assert refused.value.reasons == ("S3", "S4")
    # A closed frontier passes under `strict` unchanged.
    closed = fork_command(snapshot, invalidation_frontier=("S2", "S3", "S4")).model_copy(
        update={"frontier_policy": "strict"}
    )
    request = await prepared(forks, snapshot, closed)
    assert request.frontier_closed == ("S2", "S3", "S4")


@pytest.mark.asyncio
async def test_without_a_blueprint_the_frontier_is_recorded_unclosed() -> None:
    """Tracing Stage 3 (R2-15): nothing was closed, so the receipt says so; the patch keeps
    the requested frontier, and `strict` cannot be honoured."""

    for forks, _reader in (service(None), service(tracing_stage_blueprint(), reader=False)):
        snapshot = tracing_snapshot(("S1", 0), ("S2", 0), ("S3", 0))
        request = await prepared(
            forks, snapshot, fork_command(snapshot, invalidation_frontier=("S2",))
        )
        assert request.frontier_requested == ("S2",)
        assert request.frontier_closed == ()
        assert request.patch.invalidation_frontier == ("S2",)
        strict = fork_command(snapshot, invalidation_frontier=("S2",)).model_copy(
            update={"frontier_policy": "strict"}
        )
        with pytest.raises(ForkRejected) as refused:
            await prepared(forks, snapshot, strict)
        assert refused.value.code == "frontier_closure_unavailable"


# --- The fork position and the start position -------------------------------------------------


@pytest.mark.asyncio
async def test_at_places_the_derived_stage_at_the_cycle_with_the_source_objective() -> None:
    forks, _reader = service(tracing_stage_blueprint())
    snapshot = tracing_snapshot(
        ("S1", 0), ("S2", 0), ("S2", 1), ("S2", 2), ("S3", 2), ("S4", 2), objective="cycle two"
    )
    command = fork_command(snapshot).model_copy(update={"at": ForkAt(stage="S2", cycle=2)})
    request = await prepared(forks, snapshot, command)
    assert request.at == ForkAt(stage="S2", cycle=2)
    assert request.frontier_requested == ("S2",)
    assert request.frontier_closed == ("S2", "S3", "S4")
    assert request.start_position is not None
    assert request.start_position.workflow_cycle_ordinal == 0
    assert request.start_position.stage_cycle_ordinals == {"S2": 2}
    assert request.start_position.stage_objectives == {"S2": "cycle two"}
    # A cycle the source never reached is refused.
    beyond = fork_command(snapshot).model_copy(update={"at": ForkAt(stage="S2", cycle=3)})
    with pytest.raises(ForkRejected) as refused:
        await prepared(forks, snapshot, beyond)
    assert refused.value.code == "fork_position_unavailable"
    # Tracing Stage 3 (R2-8): the snapshot holds the current cycle's objective only, so an
    # older cycle after the first is refused rather than started without its objective.
    earlier = fork_command(snapshot).model_copy(update={"at": ForkAt(stage="S2", cycle=1)})
    with pytest.raises(ForkRejected) as refused:
        await prepared(forks, snapshot, earlier)
    assert refused.value.code == "fork_position_unavailable"
    assert refused.value.reasons == ("current:2", "requested:1")
    # Cycle 0 runs the stage's own objective: no override is needed.
    first = fork_command(snapshot).model_copy(update={"at": ForkAt(stage="S2", cycle=0)})
    request = await prepared(forks, snapshot, first)
    assert request.start_position is not None
    assert request.start_position.stage_cycle_ordinals == {"S2": 0}
    assert request.start_position.stage_objectives == {}


@pytest.mark.asyncio
async def test_stages_outside_the_closure_start_at_the_source_cycle_with_its_objective() -> None:
    """Tracing Stage 3 (R2-7): a reused upstream stage that cycled is placed at the cycle the
    source holds it at, with that cycle's objective, instead of restarting at cycle 0."""

    forks, _reader = service(tracing_stage_blueprint())
    snapshot = tracing_snapshot(
        ("S1", 0),
        ("S1", 1),
        ("S2", 0),
        ("S3", 0),
        ("S4", 0),
        objectives={"S1": "s1 cycle one"},
    )
    command = fork_command(snapshot).model_copy(update={"at": ForkAt(stage="S2", cycle=0)})
    request = await prepared(forks, snapshot, command)
    assert request.frontier_closed == ("S2", "S3", "S4")
    assert request.start_position is not None
    assert request.start_position.stage_cycle_ordinals == {"S1": 1, "S2": 0}
    assert request.start_position.stage_objectives == {"S1": "s1 cycle one"}
    decisions = {item.source_unit_key: item.decision for item in request.reuse_decisions}
    assert decisions[stage_unit("S1", 1).unit_key] == "reuse"


@pytest.mark.asyncio
async def test_a_goal_directed_position_is_refused_on_a_stage_graph_run() -> None:
    forks, _reader = service(tracing_stage_blueprint())
    snapshot = tracing_snapshot(("S1", 0), ("S2", 0))
    command = fork_command(snapshot).model_copy(update={"at": ForkAt(iteration=2)})
    with pytest.raises(ForkRejected) as refused:
        await prepared(forks, snapshot, command)
    assert refused.value.code == "invalid_patch"


def test_fork_at_names_one_family() -> None:
    with pytest.raises(ValueError):
        ForkAt()
    with pytest.raises(ValueError):
        ForkAt(stage="S2")
    with pytest.raises(ValueError):
        ForkAt(stage="S2", cycle=1, iteration=2)
    assert ForkAt(stage="S2", cycle=0).family == "stage_graph"
    assert ForkAt(iteration=3).family == "goal_directed"
    assert ForkAt(iteration=3, session_generation=2).session_generation == 2


def test_initial_projection_starts_the_stage_at_the_cycle() -> None:
    interpreter = StageGraphInterpreter(tracing_stage_blueprint(), effective_max_concurrency=1)
    identity = ExecutionIdentity(run_id="run-derived", execution_epoch=1)
    start = StageGraphStartPosition(
        workflow_cycle_ordinal=0, stage_cycle_ordinals={"S2": 2}, stage_objectives={"S2": "two"}
    )
    projection = interpreter.initial_projection(identity, run_version=1, start=start)
    by_stage = {item.candidate.stage_id: item for item in projection.stages.values()}
    assert by_stage["S2"].candidate.stage_cycle_ordinal == 2
    assert by_stage["S2"].objective_override == "two"
    assert by_stage["S1"].candidate.stage_cycle_ordinal == 0
    assert by_stage["S3"].objective_override is None
    assert projection.workflow_cycle_ordinal == 0
    plain = interpreter.initial_projection(identity, run_version=1)
    assert all(item.candidate.stage_cycle_ordinal == 0 for item in plain.stages.values())
    with pytest.raises(StageGraphExecutionError, match="unknown stages"):
        interpreter.initial_projection(
            identity, run_version=1, start=StageGraphStartPosition(stage_cycle_ordinals={"S9": 1})
        )
    with pytest.raises(StageGraphExecutionError, match="exceeds its policy"):
        interpreter.initial_projection(
            identity, run_version=1, start=StageGraphStartPosition(stage_cycle_ordinals={"S1": 1})
        )


# --- Goal Directed: reuse by iteration under the minted revision ------------------------------


@pytest.mark.asyncio
async def test_goal_directed_fork_at_an_iteration_reuses_earlier_iterations() -> None:
    forks, _reader = service(None)
    snapshot = goal_snapshot("goal-revision:source", 1, 2)
    command = fork_command(snapshot).model_copy(update={"at": ForkAt(iteration=2)})
    request = await prepared(forks, snapshot, command)
    minted = derived_goal_revision_id("goal-revision:source", request.derived_run_id)
    assert request.derived_goal_revision_id == minted
    by_source = {item.source_unit_key: item for item in request.reuse_decisions}
    for role, agent_run in (("executor", 1), ("verifier", 2)):
        unit = goal_unit(1, role, agent_run, revision="goal-revision:source")
        decision = by_source[unit.unit_key]
        assert decision.decision == "reuse"
        assert decision.reason == "settled_iteration_before_fork_position"
        location = decision.derived_unit.location
        assert isinstance(location, GoalDirectedUnitLocation)
        assert location.goal_revision_id == minted
        assert decision.derived_unit == derived_unit_identity(
            unit, request.derived_run_id, goal_revision_id=minted
        )
    for role, agent_run in (("executor", 3), ("verifier", 4)):
        unit = goal_unit(2, role, agent_run, revision="goal-revision:source")
        assert by_source[unit.unit_key].decision == "invalidated"
        assert by_source[unit.unit_key].reason == "at_or_after_fork_position"
    assert request.start_position is not None
    assert request.start_position.goal_iteration == 2
    assert request.start_position.session_generation == 1
    assert request.start_position.agent_run == 3


@pytest.mark.asyncio
async def test_goal_directed_whole_run_patch_cannot_start_after_iteration_one() -> None:
    """Tracing Stage 3 (R2-4): a new goal objective (`goal.objective`, which invalidates `*`)
    re-runs every iteration, so a fork at iteration 3 with it is refused; at iteration 1 it
    starts the derived run there with the new objective."""

    forks, _reader = service(None)
    snapshot = goal_snapshot("goal-revision:source", 1, 2, 3)
    patch = ForkPatchChange(path="goal.objective", value="Stop after one more revision.")
    command = fork_command(snapshot, changes=(patch,), invalidation_frontier=("*",))
    with pytest.raises(ForkRejected) as refused:
        await prepared(forks, snapshot, command.model_copy(update={"at": ForkAt(iteration=3)}))
    assert refused.value.code == "fork_position_unavailable"
    assert refused.value.reasons[0] == "whole_run_patch"
    assert "executor@1" in refused.value.reasons and "verifier@2" in refused.value.reasons
    request = await prepared(
        forks, snapshot, command.model_copy(update={"at": ForkAt(iteration=1)})
    )
    assert request.start_position is not None
    assert (request.start_position.goal_iteration, request.start_position.agent_run) == (1, 1)
    assert {item.decision for item in request.reuse_decisions} == {"invalidated"}


@pytest.mark.asyncio
async def test_goal_directed_position_must_be_reached_under_one_revision() -> None:
    """Tracing Stage 3 (R2-10, R2-5): an iteration the source never reached is refused, and so
    is a fork above an iteration that ran under another accepted revision."""

    forks, _reader = service(None)
    snapshot = goal_snapshot("goal-revision:source", 1, 2)
    with pytest.raises(ForkRejected) as refused:
        await prepared(
            forks, snapshot, fork_command(snapshot).model_copy(update={"at": ForkAt(iteration=3)})
        )
    assert refused.value.code == "fork_position_unavailable"
    assert refused.value.reasons == ("reached:2",)
    forks, _reader = service(None)
    revised = goal_snapshot("goal-revision:r2", 1, 2, 3, revisions={1: "goal-revision:r1"})
    with pytest.raises(ForkRejected) as refused:
        await prepared(
            forks, revised, fork_command(revised).model_copy(update={"at": ForkAt(iteration=3)})
        )
    assert refused.value.code == "fork_position_unavailable"
    assert refused.value.reasons == ("iteration:1",)
    # At iteration 1 nothing is reused, so no revision below it can differ.
    request = await prepared(
        forks, revised, fork_command(revised).model_copy(update={"at": ForkAt(iteration=1)})
    )
    assert request.start_position is not None and request.start_position.goal_iteration == 1


def goal_point(
    *, role: str = "executor", session: int = 1, locator_digest: str | None = None
) -> CognitionPointRecord:
    unit = goal_unit(2, role, 3, revision="goal-revision:source", session=session)
    key = QualifiedCheckpointKey(
        checkpointer_ref_digest=DIGEST,
        thread_id="belllabs/goal/thread",
        checkpoint_ns="",
        checkpoint_id="point-2",
        parent_checkpoint_id="point-1",
        saver_locator_digest=locator_digest,
    )
    return CognitionPointRecord(
        point_id=point_id_for(SOURCE, unit.unit_key, 1, "checkpoint", key.checkpoint_id),
        coordinate=CognitionCoordinate(
            run_id=SOURCE,
            unit_key=unit.unit_key,
            execution_generation=1,
            point=CheckpointPoint(key=key),
        ),
        lane_profile="deep_agents",
        location=location_facts(unit),
        roles=("intermediate",),
        seedable=True,
        written_by="adapter",
        recorded_at=NOW,
    )


def test_a_goal_directed_at_defaults_to_and_must_match_the_seed_session() -> None:
    """Tracing Stage 3 (R2-9)."""

    snapshot = goal_snapshot("goal-revision:source", 1, 2)
    seed = goal_point(session=2)
    assert _fork_position(snapshot, None, seed) == ForkAt(iteration=2, session_generation=2)
    assert _fork_position(snapshot, ForkAt(iteration=2), seed) == ForkAt(
        iteration=2, session_generation=2
    )
    with pytest.raises(ForkRejected) as refused:
        _fork_position(snapshot, ForkAt(iteration=2, session_generation=1), seed)
    assert refused.value.code == "invalid_patch"
    assert refused.value.reasons == ("iteration:2,session:2",)


class _SeedRunner:
    async def seed_fork(self, request: Any) -> Any:
        raise AssertionError("resolve never copies")


async def resolved(record: CognitionPointRecord, seed_key: QualifiedCheckpointKey) -> Any:
    points = InMemoryCognitionPointRepository()
    await points.record(SCOPE, [record], frame_keys={}, turn_refs={})
    seeds = CognitiveSeedService(
        points=points,
        lineage=InMemoryCheckpointLineageRepository(),
        time_travel=lambda: None,
        seed_runner=_SeedRunner(),
    )
    return await seeds.resolve(
        SCOPE, SOURCE, CognitiveSeed(unit_key=record.coordinate.unit_key, checkpoint=seed_key)
    )


@pytest.mark.asyncio
async def test_a_seed_matches_its_point_whatever_the_locator_and_never_a_verifier() -> None:
    """Tracing Stage 3 (R2-13, R2-6): the saver locator digest is not part of the checkpoint
    identity; a Goal Directed verifier point is not seedable by a fork."""

    located = goal_point(locator_digest="sha256:" + "b" * 64)
    point = located.coordinate.point
    assert isinstance(point, CheckpointPoint)
    bare = point.key.model_copy(update={"saver_locator_digest": None})
    assert (await resolved(located, bare)).point_id == located.point_id
    assert (await resolved(goal_point(), point.key)).point_id == located.point_id
    verifier = goal_point(role="verifier")
    verifier_point = verifier.coordinate.point
    assert isinstance(verifier_point, CheckpointPoint)
    with pytest.raises(ForkRejected) as refused:
        await resolved(verifier, verifier_point.key)
    assert refused.value.code == "cognitive_seed_not_supported"
    assert refused.value.reasons[-1] == "verifier"


@pytest.mark.asyncio
async def test_a_fork_holds_the_source_baseline_unless_a_dimension_is_overridden() -> None:
    """F-S2-10 (owner decision 2026-10-22, "default to source")."""

    forks, _reader = service(tracing_stage_blueprint(), baseline={"tokens.total": 40})
    snapshot = tracing_snapshot(("S1", 0), ("S2", 0))
    request = await prepared(forks, snapshot, fork_command(snapshot, baseline_reservations={}))
    assert request.target.budget_envelope.baseline_reservations == {"tokens.total": 40}
    request = await prepared(
        forks, snapshot, fork_command(snapshot, baseline_reservations={"tokens.total": 12})
    )
    assert request.target.budget_envelope.baseline_reservations == {"tokens.total": 12}
    # A replay of a fork reserved before the default keeps the baseline it recorded.
    saga = forks._saga  # type: ignore[attr-defined]
    saga.persisted = request
    replay = await prepared(forks, snapshot, fork_command(snapshot, baseline_reservations={}))
    assert replay.target.budget_envelope.baseline_reservations == {"tokens.total": 12}


@pytest.mark.asyncio
async def test_a_retaken_pre_1_4_4_snapshot_is_the_sealed_one() -> None:
    """Tracing Stage 3 (R2-11): the same version and boundary re-taken after the upgrade
    differs only by the stage positions; the sealed snapshot stands."""

    current = tracing_snapshot(("S1", 0), ("S2", 1), objective="two")
    values = current.model_dump(mode="python", exclude={"snapshot_digest", "schema_version"})
    values["family_position"] = current.family_position.model_copy(
        update={"stage_cycle_ordinals": {}, "stage_objectives": {}}
    )
    sealed = RunSnapshotManifest.create(**values)
    assert sealed.snapshot_id == current.snapshot_id
    assert sealed.snapshot_digest != current.snapshot_digest
    snapshots = InMemoryRunSnapshotRepository()
    assert await snapshots.put(sealed) == sealed
    assert await snapshots.put(current) == sealed
    # Any other difference is still a conflict.
    other = current.model_copy(update={"run_phase": "paused"})
    values = other.model_dump(mode="python", exclude={"snapshot_digest", "schema_version"})
    with pytest.raises(ForkRejected) as refused:
        await snapshots.put(RunSnapshotManifest.create(**values))
    assert refused.value.code == "snapshot_digest_conflict"


def test_goal_directed_units_stay_not_reusable_without_a_position() -> None:
    snapshot = goal_snapshot("goal-revision:source", 1, 2)
    decisions = compute_reuse_decisions(
        snapshot, fork_request_id="fork-1", derived_run_id="run-derived", frontier=frozenset()
    )
    assert {item.decision for item in decisions} == {"not_reusable"}
    assert {item.reason for item in decisions} == {"goal_revision_identity_is_run_bound"}


def test_derived_goal_revision_id_is_deterministic_and_run_bound() -> None:
    first = derived_goal_revision_id("rev", "run-a")
    assert first == derived_goal_revision_id("rev", "run-a")
    assert first != derived_goal_revision_id("rev", "run-b")
    assert first.startswith("sha256:")


# --- Message delivery -------------------------------------------------------------------------


def test_message_delivery_is_decided_by_the_seed() -> None:
    snapshot = tracing_snapshot(("S1", 0), ("S2", 0))
    seed = CognitiveSeed(
        unit_key=stage_unit("S2", 0).unit_key,
        checkpoint=QualifiedCheckpointKey(
            checkpointer_ref_digest=DIGEST,
            thread_id="thread",
            checkpoint_ns="",
            checkpoint_id="point",
            parent_checkpoint_id=None,
        ),
    )
    inline = InlineText(text="Prefer companies with CLIA labs.")
    ref = ContentRef(artifact_ref="artifact:1", content_digest=sha256_digest("x"))
    base = fork_command(snapshot, actor=fork_actor(), requested_at_offset=timedelta(0))
    assert _message_delivery(base) == (None, "none")
    assert _message_delivery(base.model_copy(update={"message": inline})) == (None, "mailbox")
    seeded = base.model_copy(update={"cognitive_seed": seed, "message": inline})
    assert _message_delivery(seeded) == (inline.text, "seed_head")
    assert _message_delivery(base.model_copy(update={"cognitive_seed": seed, "message": ref})) == (
        None,
        "mailbox",
    )
