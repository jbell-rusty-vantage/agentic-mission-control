"""K1 (cross-provider control, 2026-11-05) on the common component: a Session Lane's
`session_cursor` and `workspace_snapshot` points are written by `record_result` without a
checkpoint transition (no LangGraph namespace), in the result's transaction, with the frame
range resolved from the provider keys of the generation's persisted frames and the session
turn from `(harness_execution_id, native_turn_ref)`; a replayed settlement adds nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from mission_control.adapters.postgres.frames.repository import PostgresFrameRepository
from mission_control.adapters.postgres.operations.checkpoint_lineage import (
    PostgresCheckpointLineageRepository,
)
from mission_control.adapters.postgres.operations.cognition_points import (
    PostgresCognitionPointRepository,
)
from mission_control.application.execution.cognition_points import compose_batch
from mission_control.application.execution.operations.checkpoint_lineage import (
    UnitAttempt,
    lease_holder_id,
)
from mission_control.application.frames.kinds import classify
from mission_control.application.frames.writer import FrameWriter
from mission_control.domain.execution.checkpoint_lineage import (
    UnitResultObservation,
    unit_result_observation_id,
)
from mission_control.domain.execution.cognition_points import (
    CognitionPointFilter,
    CognitionPointObservation,
    SessionCursorPoint,
    WorkspaceSnapshotPoint,
)
from mission_control.domain.frames.contracts import FrameObservation, LaneProfile
from tests.fixtures.checkpoint_lineage import LINEAGE_NOW, activity_attempt, namespace_claim
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.integration.postgres.frames_common import admit_unit_attempt
from tests.integration.postgres.runtime_common import common_db as common_db

pytestmark = pytest.mark.common_db

AGENT = "agent-pg-1"
RUN = "run-pg-1"


def _frame(key: str, raw_kind: str, body: dict[str, object]) -> FrameObservation:
    return FrameObservation(
        provider_key=key,
        raw_kind=raw_kind,
        kind=classify(LaneProfile.CURSOR_LOCAL, raw_kind, body).kind,
        body=body,
        native_turn_ref=RUN,
        native_session_ref=AGENT,
    )


@pytest.mark.asyncio
async def test_a_session_cursor_batch_settles_with_its_frame_ranges_and_turn(
    common_db: CommonDatabase,
) -> None:
    pool = await common_db.pool(max_size=4)
    try:
        admitted = await admit_unit_attempt(pool, common_db)
        scope = admitted.unit.request_scope
        frames = PostgresFrameRepository(pool)
        start = admitted.start(lane=LaneProfile.CURSOR_LOCAL, native_session_ref=AGENT)
        handle = await frames.open_execution(start)
        writer = FrameWriter(frames, handle)
        for key, raw_kind, body in (
            (f"bridge:{RUN}:1", "system", {"subtype": "init"}),
            (f"bridge:{RUN}:2", "tool_call", {"callId": "c1", "name": "read", "status": "running"}),
            (
                f"bridge:{RUN}:3",
                "tool_call",
                {"callId": "c1", "name": "read", "status": "completed"},
            ),
            (f"bridge:{RUN}:4", "assistant", {"message": {"role": "assistant", "content": "done"}}),
            (f"bridge:{RUN}:5", "RunResult", {"status": "finished", "result": "done"}),
        ):
            await writer.write([_frame(key, raw_kind, body)])
        repository = PostgresCheckpointLineageRepository(pool)
        unit = admitted.unit
        attempt = activity_attempt(1, workflow_id=f"operation/{unit.unit_key}")
        # The lane settlement re-observes the admitted attempt (`admit_attempt`) with the
        # generation's own binding; the result below carries no transition.
        claim = namespace_claim(unit)
        admission = await repository.record_attempt(
            unit=unit,
            execution_generation=1,
            attempt=attempt,
            binding_id=f"binding:{unit.unit_key}:1",
            binding_digest=claim.binding_digest,
            namespace=claim,
            dispatching=True,
            observed_at=LINEAGE_NOW,
            lease_expires_at=LINEAGE_NOW + timedelta(minutes=5),
        )
        unit_attempt = UnitAttempt(
            unit=unit,
            execution_generation=1,
            attempt=attempt,
            holder=lease_holder_id(scope, unit.unit_key, 1, attempt),
            admission=admission,
            namespace=claim,
            deep_binding=None,
        )
        heid = str(start.harness_execution_id)

        def step(ref: str, keys: tuple[str, ...], **changes: object) -> CognitionPointObservation:
            return CognitionPointObservation.model_validate(
                {
                    "point": SessionCursorPoint(session_ref=AGENT, turn_ref=RUN, step_ref=ref),
                    "harness_execution_id": heid,
                    "native_turn_ref": RUN,
                    "frame_keys": keys,
                    "seedable": True,
                    **changes,
                }
            )

        result_point = step(
            "5",
            (f"bridge:{RUN}:5",),
            ordinal=2,
            source="loop",
            roles=("leaf", "result"),
            parent_locator=f"{AGENT}#{RUN}#4",
            workspace_checkpoint_ref="cursor-snapshot:payload://pg",
        )
        observed = (
            step(
                "3",
                (f"bridge:{RUN}:1", f"bridge:{RUN}:2", f"bridge:{RUN}:3"),
                ordinal=0,
                source="input",
                roles=("intermediate",),
            ),
            step(
                "4",
                (f"bridge:{RUN}:4",),
                ordinal=1,
                source="loop",
                roles=("intermediate",),
                parent_locator=f"{AGENT}#{RUN}#3",
            ),
            result_point,
            CognitionPointObservation(
                point=WorkspaceSnapshotPoint(
                    snapshot_ref="cursor-snapshot:payload://pg", session_ref=AGENT, turn_ref=RUN
                ),
                parent_locator=result_point.locator,
                parent_point=result_point.point,
                ordinal=3,
                source="loop",
                harness_execution_id=heid,
                native_turn_ref=RUN,
                seedable=True,
            ),
        )
        batch = compose_batch(
            observed,
            unit=unit,
            execution_generation=1,
            lane_profile="cursor_local",
            attempt=None,
            written_by="adapter",
            recorded_at=datetime(2026, 11, 5, 12, 0, tzinfo=UTC),
        )
        result = UnitResultObservation(
            observation_id=unit_result_observation_id(scope, unit.unit_key, 1),
            request_scope=scope,
            unit_key=unit.unit_key,
            execution_generation=1,
            claim_fence=unit_attempt.fence,
            binding_id=f"binding:{unit.unit_key}:1",
            settlement_id=f"settlement:{unit.unit_key}:1",
            status="completed",
            result_manifest_ref=f"manifest:{unit.unit_key}:1",
            result_manifest_digest="sha256:" + "cd" * 32,
            result_manifest_size_bytes=64,
            checkpoint_transition_id=None,
            observed_at=LINEAGE_NOW,
        )
        recorded = await repository.record_result(result, transition=None, points=batch)
        assert recorded.checkpoint_transition_id is None
        points = PostgresCognitionPointRepository(pool)
        page = await points.list_points(
            scope, admitted.run_key, selection=CognitionPointFilter(), limit=20, cursor=None
        )
        rows = page.entries
        assert [row.coordinate.locator for row in rows] == [
            f"{AGENT}#{RUN}#3",
            f"{AGENT}#{RUN}#4",
            f"{AGENT}#{RUN}#5",
            "cursor-snapshot:payload://pg",
        ]
        assert {row.written_by for row in rows} == {"adapter"}
        assert all(row.lane_profile == "cursor_local" for row in rows)
        first, second, third, snapshot = rows
        assert first.frames is not None and (
            first.frames.from_ordinal,
            first.frames.to_ordinal,
        ) == (1, 3)
        assert second.frames is not None and second.frames.from_ordinal == 4
        assert third.frames is not None and third.frames.to_ordinal == 5
        assert [row.parent_point_id for row in (second, third, snapshot)] == [
            first.point_id,
            second.point_id,
            third.point_id,
        ]
        # The session turn resolves from `(harness_execution_id, native_turn_ref)` once the
        # `lane.turn` service recorded it (`_turn_started`); this direct proof writes no
        # `session_turn` row, so the rows keep `turn_id = None` honestly.
        assert first.turn_id is None
        assert third.workspace_checkpoint_ref == "cursor-snapshot:payload://pg"
        assert isinstance(snapshot.coordinate.point, WorkspaceSnapshotPoint)
        # The frames of the result row join its point (transcript joinability).
        again = await repository.record_result(result, transition=None, points=batch)
        assert again == recorded
        assert (
            len(
                (
                    await points.list_points(
                        scope,
                        admitted.run_key,
                        selection=CognitionPointFilter(),
                        limit=20,
                        cursor=None,
                    )
                ).entries
            )
            == 4
        )
    finally:
        await pool.close()
