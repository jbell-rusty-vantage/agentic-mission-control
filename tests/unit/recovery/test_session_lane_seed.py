"""K2 (cross-provider control, 2026-11-05): a seeded fork of a Session Lane point.

A `session_cursor` point of a lane that declares `time_travel.fork` at R2 is admitted as a
cognitive seed; the lane's `seed_fork` is bound to the fork's request scope and returns a
non-checkpoint head; the service skips the LangGraph namespace head and records the lane's
`mc.lane_seed_head.v1` in the derived run's `fork_seed` point (`channel_facts.seed_head`)
with the receipt's restore level and history. A lane that declares no fork level is refused.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from tests.fixtures.checkpoint_lineage import stage_unit
from tests.unit.recovery.test_seeded_fork_saga import saga
from tests.unit.runtime.test_runtime_recovery_stage3 import DERIVED_RUN, SOURCE_RUN, fork_request

from mission_control.application.execution.cognition_points import (
    InMemoryCognitionPointRepository,
)
from mission_control.application.execution.harness.time_travel import (
    ForkSeedReceipt,
    ForkSeedRequest,
    TimeTravelRegistry,
)
from mission_control.application.execution.operations.checkpoint_lineage import (
    InMemoryCheckpointLineageRepository,
)
from mission_control.application.recovery.cognitive_seed import CognitiveSeedService
from mission_control.domain.execution.cognition_points import (
    CognitionCoordinate,
    CognitionPointFilter,
    CognitionPointRecord,
    SessionCursorPoint,
    WorkspaceSnapshotPoint,
    location_facts,
    point_id_for,
)
from mission_control.domain.execution.lanes import LaneSeedHead
from mission_control.domain.policies.forks import (
    CognitivePointSeed,
    ForkRejected,
    ForkReuseDecision,
    RunForkPatch,
    RunForkReceipt,
    RunForkRequest,
)

SCOPE = "tenant-1"
NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
SOURCE_UNIT = stage_unit(
    request_scope=SCOPE, run_id=SOURCE_RUN, operation_id="stage:implement", stage_id="implement"
)
DERIVED_UNIT = stage_unit(
    request_scope=SCOPE, run_id=DERIVED_RUN, operation_id="stage:implement", stage_id="implement"
)
HEID = "22222222-2222-4222-8222-222222222222"


def source_record(lane_profile: str = "cursor_local") -> CognitionPointRecord:
    point = SessionCursorPoint(session_ref="agent-1", turn_ref="run-1", step_ref="11")
    return CognitionPointRecord(
        point_id=point_id_for(SOURCE_RUN, SOURCE_UNIT.unit_key, 1, point.kind, point.locator),
        coordinate=CognitionCoordinate(
            run_id=SOURCE_RUN,
            unit_key=SOURCE_UNIT.unit_key,
            execution_generation=1,
            harness_execution_id=HEID,
            turn_no=1,
            point=point,
        ),
        lane_profile=lane_profile,  # type: ignore[arg-type]
        location=location_facts(SOURCE_UNIT),
        ordinal=3,
        source="loop",
        roles=("leaf", "result"),
        message_count=2,
        channel_facts={"turn_snapshot_ref": "cursor-snapshot:payload://7/manifest"},
        workspace_checkpoint_ref="cursor-snapshot:payload://7/manifest",
        seedable=True,
        written_by="adapter",
        recorded_at=NOW,
    )


class FakeCursorTimeTravel:
    """A session lane's time travel: scope-bound reads, a non-checkpoint seed head."""

    def __init__(self, profile: str = "cursor_local", scope: str | None = None) -> None:
        self._profile = profile
        self.scope = scope
        self.requests: list[ForkSeedRequest] = []

    @property
    def lane_profile(self) -> str:
        return self._profile

    def for_scope(self, request_scope: str) -> FakeCursorTimeTravel:
        bound = FakeCursorTimeTravel(self._profile, request_scope)
        bound.requests = self.requests
        return bound

    async def read_as_of(self, record: Any) -> Any:
        raise AssertionError("not read here")

    async def collect_points(self, **kwargs: Any) -> Any:
        raise AssertionError("not collected here")

    async def seed_fork(self, request: ForkSeedRequest) -> ForkSeedReceipt:
        assert self.scope == SCOPE and request.request_scope == SCOPE
        self.requests.append(request)
        point = request.source.coordinate.point
        assert isinstance(point, SessionCursorPoint)
        return ForkSeedReceipt(
            restore_level="R2",
            history="reconstructed",
            derived=CognitionCoordinate(
                run_id=request.derived_run_id,
                unit_key=request.derived_unit_key,
                execution_generation=1,
                point=WorkspaceSnapshotPoint(
                    snapshot_ref="cursor-snapshot:payload://7/manifest",
                    session_ref=point.session_ref,
                    turn_ref=point.turn_ref,
                ),
            ),
            copied_checkpoints=0,
            native_artifacts={
                "snapshot_ref": "cursor-snapshot:payload://7/manifest",
                "transcript_ref": "payload://9/transcript.md",
                "source_session_ref": point.session_ref,
                "seed_head_message_count": "3" if request.message else "2",
            },
        )


def seeded_request(record: CognitionPointRecord, *, message: str | None = None) -> RunForkRequest:
    base = fork_request()
    patch = RunForkPatch.create(
        source_snapshot_id=base.patch.source_snapshot_id,
        source_snapshot_digest=base.patch.source_snapshot_digest,
        target_admission_request_ref=base.patch.target_admission_request_ref,
        cognitive_seed=CognitivePointSeed(
            unit_key=record.coordinate.unit_key, point=record.coordinate.point
        ),
    )
    decision = ForkReuseDecision(
        fork_request_id="fork-1",
        request_scope=SCOPE,
        source_run_id=SOURCE_RUN,
        derived_run_id=DERIVED_RUN,
        source_unit_key=SOURCE_UNIT.unit_key,
        derived_unit=DERIVED_UNIT,
        derived_unit_key=DERIVED_UNIT.unit_key,
        decision="invalidated",
        reason="fork frontier",
    )
    changes: dict[str, Any] = {"patch": patch, "reuse_decisions": (decision,)}
    if message is not None:
        changes.update(message_text=message, message_delivery="seed_head")
    return base.model_copy(update=changes)


async def seeded(
    record: CognitionPointRecord, *, message: str | None = None
) -> tuple[
    InMemoryCognitionPointRepository, InMemoryCheckpointLineageRepository, FakeCursorTimeTravel
]:
    points = InMemoryCognitionPointRepository()
    await points.record(SCOPE, [record], frame_keys={}, turn_refs={})
    lineage = InMemoryCheckpointLineageRepository()
    lane = FakeCursorTimeTravel(record.lane_profile)
    seeds = CognitiveSeedService(
        points=points,
        lineage=lineage,
        time_travel=TimeTravelRegistry({record.lane_profile: lane}),
        clock=lambda: NOW,
    )
    service, _repository = saga()
    request = seeded_request(record, message=message)

    async def before_receipt(req: RunForkRequest, receipt: RunForkReceipt) -> None:
        await seeds.seed(req, receipt)

    await service.fork(request, before_receipt=before_receipt)
    return points, lineage, lane


@pytest.mark.asyncio
async def test_a_session_lane_seed_records_the_lane_seed_head_and_no_namespace_head() -> None:
    points, lineage, lane = await seeded(source_record(), message="continue from here")

    (request,) = lane.requests
    assert request.request_scope == SCOPE and request.message == "continue from here"
    assert lineage.namespaces == {}, "no LangGraph namespace is seeded for a session lane"
    page = await points.list_points(
        SCOPE, DERIVED_RUN, selection=CognitionPointFilter(role="fork_seed"), limit=10, cursor=None
    )
    (seed,) = page.entries
    assert seed.lane_profile == "cursor_local" and seed.written_by == "fork_seed"
    assert (seed.restore_level, seed.history) == ("R2", "reconstructed")
    assert isinstance(seed.coordinate.point, WorkspaceSnapshotPoint)
    assert (
        seed.parent_coordinate is not None and seed.parent_coordinate.locator == "agent-1#run-1#11"
    )
    assert seed.message_count == 3, "the lane reported the injected head's message count"
    head = LaneSeedHead.model_validate(seed.channel_facts["seed_head"])
    assert (head.source_run_id, head.source_unit_key, head.source_execution_generation) == (
        SOURCE_RUN,
        SOURCE_UNIT.unit_key,
        1,
    )
    assert (head.point_kind, head.point_locator) == ("session_cursor", "agent-1#run-1#11")
    assert SessionCursorPoint.model_validate(head.point).step_ref == "11"
    assert (head.restore_level, head.history) == ("R2", "reconstructed")
    assert head.native_artifacts["transcript_ref"] == "payload://9/transcript.md"
    assert head.message == "continue from here" and head.fork_request_id == "fork-1"


@pytest.mark.asyncio
async def test_a_lane_without_a_declared_fork_level_is_refused() -> None:
    record = source_record("claude_cloud")
    points = InMemoryCognitionPointRepository()
    await points.record(SCOPE, [record], frame_keys={}, turn_refs={})
    seeds = CognitiveSeedService(
        points=points,
        lineage=InMemoryCheckpointLineageRepository(),
        time_travel=TimeTravelRegistry({"claude_cloud": FakeCursorTimeTravel("claude_cloud")}),
    )
    with pytest.raises(ForkRejected) as refused:
        await seeds.resolve(
            SCOPE,
            SOURCE_RUN,
            CognitivePointSeed(unit_key=record.coordinate.unit_key, point=record.coordinate.point),
        )
    assert refused.value.code == "cognitive_seed_not_supported"
    assert "R1 or above" in str(refused.value)
