"""Cached bridges and custody operations must not outlive their workspace ownership."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest

from mission_control.adapters.cursor.controls import CursorSessionHydrator, CursorWorkspaceSnapshots
from mission_control.application.context.continuation import HydrationRequest, WorkspaceSnapshot
from mission_control.application.execution.harness.leases import WorkspaceLease, lease_identity
from mission_control.application.execution.harness.protocol import NativeTurnLost
from mission_control.domain.execution.lanes import (
    EndSessionRequest,
    PreparedSession,
    ReattachRequest,
    SnapshotRequest,
    StartRequest,
)
from tests.fixtures.cursor_controls import harness_fields, started_session
from tests.fixtures.cursor_local import LocalStack, local_stack
from tests.unit.cursor.support import send_request
from tests.unit.cursor.test_local_reconcile_and_rehydration import _fresh


async def _replace_holder(stack: LocalStack, heid: str) -> WorkspaceLease:
    lease = stack.harness._sessions[heid].lease
    assert lease is not None and lease.slot is not None
    now = datetime.now(UTC)
    await stack.leases.release_fenced(
        lease.request_scope,
        lease.lease_id,
        fence=lease.fence,
        patch_artifact_ref="payload://prior-custody",
        snapshot_ref=None,
        released_at=now,
        cleanup_status="pending",
    )
    successor_id = uuid4()
    lease_id, key = lease_identity("cursor_local", successor_id, 1)
    return await stack.leases.acquire(
        lease.model_copy(
            update={
                "lease_id": lease_id,
                "lease_key": key,
                "harness_execution_id": successor_id,
                "expires_at": now + timedelta(hours=4),
            }
        ),
        now=now,
    )


@pytest.mark.parametrize(
    "action", ["send", "start", "reattach", "snapshot", "continuation_snapshot", "end", "open"]
)
async def test_cached_session_cannot_touch_a_replacement_holder(
    tmp_path: Path, action: str
) -> None:
    stack = local_stack(tmp_path)
    heid, handle = await started_session(stack)
    assert handle.native_session_ref is not None
    successor = await _replace_holder(stack, heid)
    marker = Path(successor.path) / ".cursor" / "hooks.json"
    marker.write_text("replacement holder hooks", encoding="utf-8")
    staged_before = dict(stack.artifacts.staged)
    fields = harness_fields(stack.operation, heid)

    with pytest.raises(NativeTurnLost, match="no longer held"):
        if action == "send":
            await stack.harness.send_turn(
                send_request(stack, "cursor_local", heid, handle.native_session_ref, 1)
            )
        elif action == "start":
            await stack.harness.start(
                StartRequest(
                    **fields,
                    prepared=PreparedSession(
                        lane_profile="cursor_local", harness_execution_id=heid, generation=1
                    ),
                )
            )
        elif action == "reattach":
            await stack.harness.reattach(
                ReattachRequest(**fields, native_session_ref=handle.native_session_ref)
            )
        elif action == "snapshot":
            await stack.harness.snapshot(
                SnapshotRequest(**fields, session=handle, reason="stale checkpoint")
            )
        elif action == "continuation_snapshot":
            await CursorWorkspaceSnapshots(stack.harness, stack.artifacts).snapshot(
                request_scope=successor.request_scope,
                run_key=successor.run_id,
                session_ref=handle.native_session_ref,
                roots=(".mission",),
            )
        elif action == "end":
            await stack.harness.end_session(
                EndSessionRequest(**fields, session=handle, reason="stale cleanup")
            )
        else:
            await stack.harness.open_bridge(heid)

    assert marker.read_text(encoding="utf-8") == "replacement holder hooks"
    assert stack.artifacts.staged == staged_before
    assert not stack.launcher.sends
    assert not (Path(successor.path) / ".mission" / "turns").exists()
    assert not stack.launcher.closed
    assert stack.launcher.bridges_closed == 0
    assert len(stack.launcher.launches) == 1
    assert await stack.leases.get(successor.request_scope, successor.lease_id) == successor


async def test_recovery_renews_expired_owned_lease_and_keeps_the_same_native_run(
    tmp_path: Path,
) -> None:
    stack = local_stack(tmp_path)
    heid, handle = await started_session(stack)
    assert handle.native_session_ref is not None
    sent = await stack.harness.send_turn(
        send_request(stack, "cursor_local", heid, handle.native_session_ref, 1)
    )
    lease = stack.harness._sessions[heid].lease
    assert lease is not None
    later = lease.expires_at + timedelta(minutes=1)
    stack.harness._leaser.allocator._clock = lambda: later
    fresh = _fresh(stack)
    fresh.stage(heid, stack.operation)
    resumed = await fresh.reattach(
        ReattachRequest(
            **harness_fields(stack.operation, heid),
            native_session_ref=handle.native_session_ref,
            native_turn_ref=sent.native_turn_ref,
        )
    )
    renewed = await stack.leases.get(lease.request_scope, lease.lease_id)
    assert renewed is not None and renewed.expires_at > later
    assert renewed.fence == lease.fence
    assert resumed.native_session_ref == handle.native_session_ref
    assert fresh._sessions[heid].run_id == sent.native_turn_ref
    assert len(stack.launcher.sends) == 1


async def test_cached_lease_cannot_be_borrowed_by_another_generation(tmp_path: Path) -> None:
    stack = local_stack(tmp_path)
    heid, handle = await started_session(stack)
    assert handle.native_session_ref is not None
    lease = stack.harness._sessions[heid].lease
    request = send_request(stack, "cursor_local", heid, handle.native_session_ref, 1)
    with pytest.raises(NativeTurnLost, match="session generation"):
        await stack.harness.send_turn(request.model_copy(update={"generation": 2}))
    assert lease is not None
    assert await stack.leases.get(lease.request_scope, lease.lease_id) == lease
    assert not stack.launcher.sends


async def test_foreign_scope_is_rejected_without_renewing_the_lease(tmp_path: Path) -> None:
    stack = local_stack(tmp_path)
    heid, handle = await started_session(stack)
    assert handle.native_session_ref is not None
    lease = stack.harness._sessions[heid].lease
    request = send_request(stack, "cursor_local", heid, handle.native_session_ref, 1)
    request = request.model_copy(
        update={"scope": request.scope.model_copy(update={"tenant_id": "another-tenant"})}
    )
    with pytest.raises(NativeTurnLost, match="does not match"):
        await stack.harness.send_turn(request)
    assert lease is not None
    assert await stack.leases.get(lease.request_scope, lease.lease_id) == lease
    assert not stack.launcher.sends


async def test_continuation_refuses_stale_holder_before_restoring_files(tmp_path: Path) -> None:
    stack = local_stack(tmp_path)
    heid, handle = await started_session(stack)
    successor = await _replace_holder(stack, heid)
    marker = Path(successor.path) / ".mission" / "context.md"
    marker.parent.mkdir(parents=True, exist_ok=True)
    if marker.exists():
        marker.chmod(0o644)
    marker.write_text("replacement context", encoding="utf-8")
    # Hydration must reject ownership before it needs the sealed checkpoint or packet.
    request = Mock(spec=HydrationRequest)
    request.source_session_ref = handle.native_session_ref
    request.snapshot = WorkspaceSnapshot(snapshot_ref="snapshot://prior")
    request.mission_files = {".mission/context.md": "stale continuation context"}
    with pytest.raises(NativeTurnLost, match="no longer held"):
        await CursorSessionHydrator(stack.harness).hydrate(request)
    assert marker.read_text(encoding="utf-8") == "replacement context"
    assert len(stack.launcher.created) == 1
