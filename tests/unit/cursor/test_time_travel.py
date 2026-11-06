"""Cursor time travel (cross-provider control, 2026-11-05): `read_as_of` at R2, `seed_fork` at
R2 (idempotent), `collect_points`, and the derived unit's `prepare`/`start` honouring the
seed head (the snapshot restored into a fresh lease, the hydration transcript prefixed to the
first turn). FIXTURE bridge and API only; no Cursor agent is created.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from mission_control.adapters.cursor.time_travel import (
    HYDRATION_HEADER,
    SEED_SNAPSHOT_REF,
    SEED_TRANSCRIPT_REF,
    CursorTimeTravel,
    cursor_time_travel_lanes,
)
from mission_control.application.execution.harness.lane_turns import LaneExecutionIdentity
from mission_control.application.execution.harness.time_travel import (
    ForkSeedRequest,
    ScopedTimeTravelLane,
    TimeTravelRegistry,
    TimeTravelUnsupported,
)
from mission_control.domain.execution.cognition_points import (
    CognitionPointRecord,
    SessionCursorPoint,
    WorkspaceSnapshotPoint,
)
from mission_control.domain.execution.lanes import LaneSeedHead, PrepareRequest, StartRequest
from tests.fixtures.cursor_controls import harness_fields
from tests.fixtures.cursor_local import local_stack
from tests.fixtures.lane_turns import SCOPE, cursor_operation
from tests.unit.cursor.test_cognition_points import settled_points, unit_changes


def _steps(rows: tuple[CognitionPointRecord, ...]) -> list[CognitionPointRecord]:
    return [row for row in rows if isinstance(row.coordinate.point, SessionCursorPoint)]


async def _local(tmp_path: Path) -> tuple[Any, tuple[CognitionPointRecord, ...], Any]:
    stack = local_stack(tmp_path, operation_changes=unit_changes(cursor_operation()))
    rows, _identity, lanes = await settled_points(stack, "cursor_local")
    return stack, rows, lanes


async def test_read_as_of_reconstructs_the_transcript_and_lists_the_turn_snapshot_files(
    tmp_path: Path,
) -> None:
    stack, rows, lanes = await _local(tmp_path)
    lane = CursorTimeTravel("cursor_local", lanes.frames, snapshots=stack.artifacts)
    assert isinstance(lane, ScopedTimeTravelLane)
    registry = TimeTravelRegistry().register_all([lane])
    with pytest.raises(TimeTravelUnsupported, match="request_scope_unbound"):
        await lane.read_as_of(rows[0])
    bound = registry.lane("cursor_local", request_scope=SCOPE)
    steps = _steps(rows)

    # An intermediate point: the transcript up to the first tool completion (offset 5).
    first = await bound.read_as_of(steps[0])
    assert first.history == "reconstructed" and first.restore_level == "R2"
    roles = [message.role for message in first.state.messages]
    assert roles == ["assistant", "assistant", "tool"], roles
    assert first.state.messages[1].tool_calls[0].name == "read"
    assert (
        first.state.messages[2].name == "read"
        and first.state.messages[2].tool_call_id == "call-read-1"
    )
    assert any("turn's close" in item for item in first.state.withheld)
    assert first.usage_to_point == {}
    # The result point: the whole turn, the final text once, the usage, the snapshot files.
    result = await bound.read_as_of(steps[-1])
    texts = [message.text for message in result.state.messages if message.role == "assistant"]
    assert texts.count("Tests pass; the report is in outputs/report.md.") == 1
    assert result.usage_to_point["tokens.total"] == 2242
    assert (
        result.restore_level == "R2"
        and result.state.channels["workspace_snapshot"]["kind"] == "cursor_snapshot"
    )
    paths = {item.path for item in result.state.files}
    assert "outputs/report.md" in paths and all(
        item.digest.startswith("sha256:") for item in result.state.files
    )
    assert result.state.stamps["snapshot_ref"] == steps[-1].workspace_checkpoint_ref
    # Without a snapshot store the files are withheld and the read is honest about R1.
    bare = CursorTimeTravel("cursor_local", lanes.frames).for_scope(SCOPE)
    thin = await bare.read_as_of(steps[-1])
    assert thin.restore_level == "R1" and thin.state.files == ()
    assert any("no snapshot store" in item for item in thin.state.withheld)


async def test_collect_points_refolds_the_generation_with_the_settlement_ids(
    tmp_path: Path,
) -> None:
    _stack, rows, lanes = await _local(tmp_path)
    lane = CursorTimeTravel("cursor_local", lanes.frames).for_scope(SCOPE)
    steps = _steps(rows)
    heid = steps[0].coordinate.harness_execution_id
    assert heid is not None
    observed = await lane.collect_points(
        namespace=heid,
        checkpointer_ref_digest="1",
        source_locator=None,
        result_locator=steps[-1].coordinate.locator,
    )
    assert [item.locator for item in observed] == [row.coordinate.locator for row in steps]
    assert observed[-1].roles == ("leaf", "result") and observed[0].parent_locator is None


async def test_seed_fork_stages_the_transcript_names_the_snapshot_and_is_idempotent(
    tmp_path: Path,
) -> None:
    stack, rows, lanes = await _local(tmp_path)
    lane = CursorTimeTravel("cursor_local", lanes.frames, snapshots=stack.artifacts)
    steps = _steps(rows)
    source = steps[2]  # the assistant message at offset 8
    request = ForkSeedRequest(
        source=source,
        derived_run_id="run-derived",
        derived_unit_key=source.coordinate.unit_key,
        derived_namespace="belllabs/derived",
        derived_invocation_id="invocation-1",
        fork_request_id="fork-1",
        message="Now also write the changelog.",
        request_scope=SCOPE,
    )
    receipt = await lane.seed_fork(request)
    assert (receipt.restore_level, receipt.history, receipt.copied_checkpoints) == (
        "R2",
        "reconstructed",
        0,
    )
    derived = receipt.derived.point
    assert isinstance(derived, WorkspaceSnapshotPoint)
    assert derived.snapshot_ref == source.channel_facts["turn_snapshot_ref"]
    assert receipt.native_artifacts[SEED_SNAPSHOT_REF] == derived.snapshot_ref
    assert receipt.native_artifacts["seed_head"] == "injected_message"
    transcript = stack.artifacts.staged[receipt.native_artifacts[SEED_TRANSCRIPT_REF]][1].decode()
    assert transcript.startswith(HYDRATION_HEADER)
    assert "[assistant -> tool read (call-read-1)]" in transcript
    assert "[tool shell (call-shell-1)]" in transcript
    assert "Tests pass; the report is in outputs/report.md." in transcript
    assert transcript.rstrip().endswith("[operator] Now also write the changelog.")
    assert "sk-fixture-secret" not in transcript
    # The same fork request seeds once; a repeat is the same receipt, nothing re-staged.
    staged = len(stack.artifacts.staged)
    assert await lane.seed_fork(request) == receipt and len(stack.artifacts.staged) == staged
    # The source frames and snapshot are untouched: the source lease's snapshot ref stands.
    (lease,) = stack.leases._leases.values()
    assert lease.snapshot_ref == derived.snapshot_ref


async def test_a_derived_lease_restores_the_seed_snapshot_and_the_first_turn_is_hydrated(
    tmp_path: Path,
) -> None:
    stack, rows, lanes = await _local(tmp_path)
    lane = CursorTimeTravel("cursor_local", lanes.frames, snapshots=stack.artifacts)
    source = _steps(rows)[-1]
    receipt = await lane.seed_fork(
        ForkSeedRequest(
            source=source,
            derived_run_id="run-derived",
            derived_unit_key=source.coordinate.unit_key,
            derived_namespace="belllabs/derived",
            derived_invocation_id="invocation-1",
            fork_request_id="fork-2",
            request_scope=SCOPE,
        )
    )
    head = LaneSeedHead(
        source_run_id=source.coordinate.run_id,
        source_unit_key=source.coordinate.unit_key,
        source_execution_generation=1,
        point_kind=source.coordinate.kind,
        point_locator=source.coordinate.locator,
        point=source.coordinate.point.model_dump(mode="json"),
        restore_level=receipt.restore_level,
        history="reconstructed",
        native_artifacts=receipt.native_artifacts,
        fork_request_id="fork-2",
    )
    # The derived run: a fresh stack sharing the artifact store (the snapshot bytes).
    derived = local_stack(
        tmp_path / "derived",
        artifacts=stack.artifacts,
        launcher_changes={"agent_base": "agent-forked-0001"},
    )
    operation = derived.operation
    heid = str(LaneExecutionIdentity.of(operation, "cursor_local", 1).harness_execution_id)
    fields = harness_fields(operation, heid, "cursor_local")
    derived.harness.stage(heid, operation)
    prepared = await derived.harness.prepare(
        PrepareRequest(
            **fields,
            run_id=operation.identity.run_id,
            operation_id=operation.identity.operation_id,
            attempt_no=1,
            seed=head,
        )
    )
    root = Path(derived.harness.lease_path(heid))
    assert (root / "outputs" / "report.md").read_text(encoding="utf-8").startswith("# Report")
    assert (root / "src" / "feature.py").is_file(), "the source agent's patch is restored"
    session = await derived.harness.start(StartRequest(**fields, prepared=prepared, seed=head))
    assert session.native_session_ref is not None
    from mission_control.domain.execution.lanes import SendTurnRequest, SessionHandle

    sent = await derived.harness.send_turn(
        SendTurnRequest(
            **{**fields, "idempotency_key": f"{heid}:1:turn:1"},
            session=SessionHandle(
                lane_profile="cursor_local",
                harness_execution_id=heid,
                generation=1,
                native_session_ref=session.native_session_ref,
            ),
            turn_no=1,
            instruction_ref=f"operation:{operation.identity.semantic_key}:turn:1",
        )
    )
    assert sent.native_turn_ref is not None
    (_key, text) = derived.launcher.sends[-1]
    assert text.startswith(HYDRATION_HEADER) and "[tool shell (call-shell-1)]" in text
    # The unit's own instruction follows the transcript (the hydration turn carries both).
    from mission_control.adapters.cursor.local import turn_text

    assert text.rstrip().endswith(turn_text(operation).rstrip())
    # A second send is not hydrated again.
    assert derived.harness._sessions[heid].seed_applied


def test_the_lane_factory_builds_both_profiles(tmp_path: Path) -> None:
    stack = local_stack(tmp_path)
    local, cloud = cursor_time_travel_lanes(frames=stack.frames, snapshots=stack.artifacts)
    assert (local.lane_profile, cloud.lane_profile) == ("cursor_local", "cursor_cloud")
    with pytest.raises(ValueError):
        CursorTimeTravel("deep_agents", stack.frames)
