"""MP-09: the cloud harness runs on `WorkspaceAllocator.allocate_provider_workspace` (MP-04)
and produces the `branch:<branch>@<sha>` snapshot (ADR-0037); a fresh worker reattaches by
native identity, rehydrates what the process lost and resumes from the persisted cursor
(FIXTURE Cloud API, bare git remote, in-memory ledger).
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from mission_control.adapters.cursor.bridge import ProviderTransient
from mission_control.adapters.cursor.cloud import CURSOR_CLOUD_POLICY, run_branch
from mission_control.adapters.cursor.workspace import git
from mission_control.application.execution.harness.lane_turns import LaneTurnService
from mission_control.application.execution.harness.protocol import NativeTurnLost
from mission_control.application.execution.harness.sessions import WorkerSessionManager
from mission_control.application.resolution.registries import LaneRegistry
from mission_control.domain.execution.lanes import (
    CursorExecutionBinding,
    ObserveRequest,
    ReattachRequest,
    SnapshotRequest,
)
from tests.fixtures.cursor_cloud import cloud_stack
from tests.fixtures.cursor_controls import harness_fields, started_session
from tests.unit.cursor.support import (
    dispatch_record,
    frames_of,
    fresh_cloud_harness,
    heid_of,
    identity,
    lanes_for,
    send_key,
    send_request,
    signals,
    turn,
)

PROFILE = "cursor_cloud"


def _branch_head(stack, branch: str) -> str:  # type: ignore[no-untyped-def]
    return git("rev-parse", branch, cwd=stack.remote).strip()


async def test_prepare_records_the_provider_workspace_and_end_session_releases_after_custody(
    tmp_path: Path,
) -> None:
    stack = cloud_stack(tmp_path)
    lanes = lanes_for(stack)
    result = await lanes.service.turn(turn(stack, PROFILE), signals(lanes, stack, PROFILE))
    assert result.done and result.closing_facts is not None
    assert stack.leases is not None
    (lease,) = stack.leases._leases.values()
    branch = run_branch(
        CursorExecutionBinding.carried_by(stack.operation),
        stack.operation.identity.run_id,
        stack.operation.identity.operation_id,
    )  # type: ignore[arg-type]
    head = _branch_head(stack, branch)
    assert lease.lane_profile == PROFILE and lease.branch == branch
    assert lease.policy == CURSOR_CLOUD_POLICY and lease.path.startswith("provider:cursor_cloud:")
    assert lease.released and lease.cleanup_status == "not_required"
    assert lease.snapshot_ref == f"branch:{branch}@{head}"
    assert lease.workspace_snapshot is not None
    assert lease.workspace_snapshot.head_commit == head
    assert lease.workspace_snapshot.base_commit == lease.base_commit
    assert lease.workspace_snapshot.emulated is True
    evidence = lease.workspace_snapshot.conversation
    assert evidence is not None and evidence.disposition == "missing"
    assert evidence.origin.restore_ref == lease.snapshot_ref
    assert evidence.origin.run_id == lease.run_id
    assert evidence.origin.session_ref in stack.api.agents
    assert evidence.origin.run_ref == stack.api.run_id
    assert "provider:uncommitted-state-not-captured" in lease.workspace_snapshot.exclusions
    manifest = next(
        json.loads(content)
        for name, content, _m in stack.artifacts.staged.values()
        if name.endswith("session-manifest.json")
    )
    assert manifest["workspace_snapshot_ref"] == lease.snapshot_ref
    assert manifest["workspace_lease_id"] == str(lease.lease_id)
    assert manifest["head"] == head


@pytest.mark.parametrize("moving", ["branch", "native", "missing"])
async def test_conversation_capture_checks_second_head_and_native_anchor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    moving: str,
) -> None:
    stack = cloud_stack(tmp_path)
    heid, handle = await started_session(stack)
    assert handle.native_session_ref is not None
    branch = stack.harness.session_branch(heid)[1]
    initial_head = _branch_head(stack, branch)
    if moving == "branch":
        monkeypatch.setattr(
            stack.harness._publisher, "head", AsyncMock(side_effect=[initial_head, "f" * 40])
        )
    elif moving == "native":
        initial = dict(stack.api.agents[handle.native_session_ref])
        monkeypatch.setattr(
            stack.client,
            "get_agent",
            AsyncMock(side_effect=[initial, {**initial, "latestRunId": "foreign-run"}]),
        )
    else:
        monkeypatch.setattr(stack.client, "conversation", AsyncMock(return_value=None))
    request = SnapshotRequest(
        **harness_fields(stack.operation, heid, PROFILE), session=handle, reason="custody"
    )
    if moving != "missing":
        with pytest.raises(NativeTurnLost, match="origin moved"):
            await stack.harness.snapshot(request)
        assert stack.leases is not None
        assert all(lease.workspace_snapshot is None for lease in stack.leases._leases.values())
    else:
        await stack.harness.snapshot(request)
        assert stack.leases is not None
        stored = next(iter(stack.leases._leases.values())).workspace_snapshot
        assert stored is not None and stored.conversation is not None
        assert stored.conversation.disposition == "missing"
        assert stored.conversation.content_bytes < 2048
    assert _branch_head(stack, branch) == initial_head, (
        "capture never publishes or edits the source branch"
    )


async def test_snapshot_records_the_branch_head_on_the_lease_while_the_run_is_live(
    tmp_path: Path,
) -> None:
    stack = cloud_stack(tmp_path)
    heid, handle = await started_session(stack)
    manifest = await stack.harness.snapshot(
        SnapshotRequest(
            **harness_fields(stack.operation, heid, PROFILE), session=handle, reason="t"
        )
    )
    assert manifest.emulated and manifest.kind == "branch"
    assert manifest.refs[0].startswith("branch:")
    lease = stack.harness.session_lease(heid)
    assert lease is not None and f"workspace-lease:{lease.lease_id}" in manifest.refs
    assert stack.leases is not None
    stored = next(iter(stack.leases._leases.values()))
    assert stored.snapshot_ref == manifest.refs[0] and not stored.released


async def test_a_fresh_worker_reattaches_rehydrates_resumes_the_cursor_and_ends_the_session(
    tmp_path: Path,
) -> None:
    stack = cloud_stack(tmp_path, api_changes={"cut_after": "4"})
    lanes = lanes_for(stack)
    ident = identity(stack, PROFILE)
    heid = heid_of(stack, PROFILE)
    first = await lanes.service.turn(turn(stack, PROFILE), signals(lanes, stack, PROFILE))
    assert not first.done and first.cursor == f"{stack.api.run_id}@4"
    assert first.native.session_ref is not None

    # A new process: a harness with no session memory and a service over the same stores.
    # It is a different worker owner, so the MP-06 ownership fence admits it only after the
    # first owner's session lease has expired (a live foreign lease is refused; see
    # test_mp06_dispatch_recovery). Its clock therefore runs past that lease.
    old_owner = await lanes.states.load(ident.request_scope, ident.harness_execution_id)
    assert old_owner is not None and old_owner.owner is not None
    expired = old_owner.owner.lease_expires_at + timedelta(seconds=1)
    fresh = fresh_cloud_harness(stack, tmp_path / "mirrors-2")
    service = LaneTurnService(
        lanes=LaneRegistry([fresh], allow_unqualified=True),
        boundary=lanes.boundary,
        frames=lanes.frames,
        states=lanes.states,
        clock=lambda: expired,
        sessions=WorkerSessionManager(owner_ref="worker-fresh", min_lease=timedelta(seconds=1)),
    )
    second = await service.turn(
        turn(stack, PROFILE, phase="resume", cursor=first.cursor, segment_no=2),
        signals(lanes, stack, PROFILE),
    )
    assert second.done and second.closing_facts is not None
    assert second.closing_facts.native_status == "finished"
    assert second.closing_facts.patch_ref is not None
    assert stack.api.stream_requests == [None, "4"], "resumed from the persisted cursor"
    assert len(stack.api.creates) == 1 and stack.api.archived == [first.native.session_ref]
    receipt = fresh.rehydration_receipt(heid)
    assert receipt == (), "the session was released at settlement"
    state = await lanes.states.load(ident.request_scope, ident.harness_execution_id)
    assert state is not None and state.native_turn_ref == stack.api.run_id
    # The takeover fenced the first owner: a new owner with a higher epoch.
    assert state.owner is not None and state.owner.owner_ref == "worker-fresh"
    assert state.owner.epoch > old_owner.owner.epoch
    assert state.owner.previous_owner_ref == old_owner.owner.owner_ref
    frames = frames_of(lanes, stack, PROFILE)
    keys = [frame.provider_key for frame in frames]
    assert len(keys) == len(set(keys))
    assert stack.leases is not None
    (lease,) = stack.leases._leases.values()
    assert lease.released and lease.snapshot_ref is not None
    assert lease.snapshot_ref.startswith("branch:")


async def test_reattach_rehydrates_branch_projection_and_lease_without_republishing(
    tmp_path: Path,
) -> None:
    from mission_control.domain.execution.lanes import ReattachRequest

    stack = cloud_stack(tmp_path)
    heid, handle = await started_session(stack)
    assert handle.native_session_ref is not None
    branch = run_branch(
        CursorExecutionBinding.carried_by(stack.operation),
        stack.operation.identity.run_id,
        stack.operation.identity.operation_id,
    )  # type: ignore[arg-type]
    head_before = _branch_head(stack, branch)
    fresh = fresh_cloud_harness(stack, tmp_path / "mirrors-2")
    fresh.stage(heid, stack.operation)
    resumed = await fresh.reattach(
        ReattachRequest(
            **harness_fields(stack.operation, heid, PROFILE),
            native_session_ref=handle.native_session_ref,
            native_turn_ref=stack.api.run_id,
        )
    )
    assert set(fresh.rehydration_receipt(heid)) == {"branch", "projection", "workspace_lease"}
    assert resumed.native_details["rehydrated"] == "branch,projection,workspace_lease"
    assert resumed.native_details["cloud_branch"] == f"{branch}@{head_before}"
    assert _branch_head(stack, branch) == head_before, "resolved on the remote, not re-published"
    lease = fresh.session_lease(heid)
    assert lease is not None and lease.branch == branch
    assert stack.leases is not None and len(stack.leases._leases) == 1


async def test_cloud_history_requires_authoritative_terminal_record(tmp_path, monkeypatch):
    from mission_control.domain.execution.history_reconciliation import (
        HistoryReplayComplete,
        HistoryReplayIncomplete,
    )
    from mission_control.domain.execution.lanes import ObserveRequest, TurnHandle

    stack = cloud_stack(tmp_path)
    heid, session = await started_session(stack)
    request = ObserveRequest(
        **harness_fields(stack.operation, heid, PROFILE),
        turn=TurnHandle(session=session, turn_no=1, native_turn_ref=stack.api.run_id),
    )
    monkeypatch.setattr(stack.harness, "_read_turn", AsyncMock(return_value={"status": "running"}))
    with pytest.raises(HistoryReplayIncomplete):
        _ = [frame async for frame in stack.harness.reconcile_history(request)]
    monkeypatch.setattr(stack.harness, "_read_turn", AsyncMock(return_value={"status": "finished"}))
    replay = [frame async for frame in stack.harness.reconcile_history(request)]
    assert replay[0].terminal and isinstance(replay[-1], HistoryReplayComplete)


@pytest.mark.parametrize("recovered", [False, True])
async def test_custody_tracks_latest_acknowledged_run_after_later_send(
    tmp_path: Path, recovered: bool
) -> None:
    stack = cloud_stack(tmp_path)
    heid, handle = await started_session(stack)
    assert handle.native_session_ref is not None
    native = handle.native_session_ref
    first = await stack.harness.send_turn(send_request(stack, PROFILE, heid, native, 1))
    frames = [
        frame
        async for frame in stack.harness.observe(
            ObserveRequest(**harness_fields(stack.operation, heid, PROFILE), turn=first)
        )
    ]
    assert frames[-1].terminal
    await stack.harness.reattach(
        ReattachRequest(
            **harness_fields(stack.operation, heid, PROFILE),
            native_session_ref=native,
            native_turn_ref=first.native_turn_ref,
        )
    )
    second = send_request(stack, PROFILE, heid, native, 2)
    if recovered:
        stack.api.lose_run_responses = 1
        with pytest.raises(ProviderTransient):
            await stack.harness.send_turn(second)
        lookup = await stack.harness.reconcile_dispatch(
            dispatch_record(stack, kind="send", key=send_key(heid, 2), turn_no=2),
            session=handle,
        )
        assert lookup.outcome == "found"
        current_run = lookup.native_ref
    else:
        current_run = (await stack.harness.send_turn(second)).native_turn_ref
    assert current_run and current_run != first.native_turn_ref
    assert stack.api.agents[native]["latestRunId"] == current_run
    request = SnapshotRequest(
        **harness_fields(stack.operation, heid, PROFILE), session=handle, reason="custody"
    )
    await stack.harness.snapshot(request)
    assert stack.leases is not None
    (lease,) = stack.leases._leases.values()
    captured = lease.workspace_snapshot
    assert captured is not None and captured.conversation is not None
    assert captured.conversation.origin.session_ref == native
    assert captured.conversation.origin.run_ref == current_run
    assert len(stack.api.created_runs) == 2, "custody/reconciliation never creates another run"
    stack.api.agents[native]["latestRunId"] = "foreign-run"
    with pytest.raises(NativeTurnLost, match="no longer the acknowledged native run"):
        await stack.harness.snapshot(request)
    assert next(iter(stack.leases._leases.values())).workspace_snapshot == captured
    assert not next(iter(stack.leases._leases.values())).released
