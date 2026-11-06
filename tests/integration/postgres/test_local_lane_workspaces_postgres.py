"""MO-05 on a disposable PostgreSQL 17: the `codex` / `cursor_local` workspace leaser over the
real lease ledger (runtime role, forced RLS; no new DDL, the custody ref lives in `detail`).

The binding's `within_run` policy decides the lease; release registers the allocator's custody
snapshot beside the lane's own restorable snapshot and patch; cleanup after settlement removes
the worktree and keeps both snapshots on record; the run's next holder continues from the
retained custody in a fresh worktree of the slot. A live `shared_checkout` parent refuses a
writable holder and records a read-only helper until it leaves; its cleanup refuses meanwhile.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from mission_control.adapters.cursor.workspace import GitWorktreeLeaser
from mission_control.adapters.postgres.lanes.workspace_leases import PostgresWorkspaceLeaseStore
from mission_control.application.execution.harness.leases import WorkspaceLease
from mission_control.application.workspaces.errors import (
    WORKSPACE_LEASE_HELD,
    WORKSPACE_SHARED_ACTIVE,
    WorkspaceError,
)
from mission_control.application.workspaces.service import AllocationRequest
from tests.fixtures.local_lane_workspaces import SHARED, WITHIN_RUN
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.integration.postgres.runtime_common import common_db  # noqa: F401
from tests.unit.workspaces.workspace_fixtures import MemoryArtifacts, make_primary, present

pytestmark = pytest.mark.common_db
LANE_SNAPSHOT = "payload://codex-local/workspace-snapshot.json"
LANE_PATCH = "payload://codex-local/patch.diff"


async def test_custody_beside_the_lane_snapshot_cleanup_and_continuation(
    common_db: CommonDatabase,  # noqa: F811
    tmp_path: Path,
) -> None:
    pool = await common_db.pool("mission_control_runtime")
    try:
        store = PostgresWorkspaceLeaseStore(pool)
        scope = common_db.scope("tenant-1")
        primary = make_primary(tmp_path / "primary")
        leaser = GitWorktreeLeaser(
            store, lease_root=tmp_path / "leases", artifacts=MemoryArtifacts()
        )
        run = f"run-{uuid4()}"
        first_holder = uuid4()

        async def acquire(holder: UUID) -> WorkspaceLease:
            return await leaser.acquire(
                request_scope=scope,
                lane_profile="codex",
                harness_execution_id=holder,
                generation=1,
                run_id=run,
                attempt_no=1,
                repository=str(primary),
                base_ref="main",
                policy=WITHIN_RUN,
            )

        lease = await acquire(first_holder)
        assert lease.policy == WITHIN_RUN and lease.slot == f"run:{run}"
        root = Path(lease.path)
        (root / "a.txt").write_bytes(b"agent work\n")
        await leaser.release(lease, patch_artifact_ref=LANE_PATCH, snapshot_ref=LANE_SNAPSHOT)

        stored = await store.get(scope, lease.lease_id)
        assert stored is not None and stored.released and stored.cleanup_status == "pending"
        assert (stored.snapshot_ref, stored.patch_artifact_ref) == (LANE_SNAPSHOT, LANE_PATCH)
        assert stored.workspace_snapshot is not None
        assert stored.workspace_snapshot_ref is not None
        assert stored.workspace_snapshot_ref.startswith("workspace-snapshot:")
        # A fork of the run still restores the lane's own snapshot.
        assert await store.sandbox_snapshot_refs(scope, run) == (LANE_SNAPSHOT,)
        assert await asyncio.to_thread(root.is_dir)

        cleaned = await leaser.cleanup(
            request_scope=scope,
            lane_profile="codex",
            harness_execution_id=first_holder,
            generation=1,
        )
        assert cleaned == "removed" and not present(root)
        final = await store.get(scope, lease.lease_id)
        assert final is not None and final.cleanup_status == "completed"
        assert final.workspace_snapshot_ref == stored.workspace_snapshot_ref
        assert final.snapshot_ref == LANE_SNAPSHOT

        second = await acquire(uuid4())
        assert second.path == lease.path and second.fence == lease.fence + 1
        assert (root / "a.txt").read_bytes() == b"agent work\n"
    finally:
        await pool.close()


async def test_a_live_shared_checkout_parent_admits_only_read_only_helpers(
    common_db: CommonDatabase,  # noqa: F811
    tmp_path: Path,
) -> None:
    pool = await common_db.pool("mission_control_runtime")
    try:
        store = PostgresWorkspaceLeaseStore(pool)
        scope = common_db.scope("tenant-1")
        primary = make_primary(tmp_path / "primary")
        leaser = GitWorktreeLeaser(
            store, lease_root=tmp_path / "leases", artifacts=MemoryArtifacts()
        )
        run = f"run-{uuid4()}"
        parent_id, helper_id = uuid4(), uuid4()

        def holder(heid: UUID, *, read_only: bool) -> AllocationRequest:
            return AllocationRequest(
                request_scope=scope,
                lane_profile="codex",
                harness_execution_id=heid,
                generation=1,
                run_id=run,
                attempt_no=1,
                policy=SHARED,
                repository=str(primary),
                base_ref="main",
                read_only=read_only,
            )

        async def clean(heid: UUID) -> str:
            return await leaser.cleanup(
                request_scope=scope,
                lane_profile="codex",
                harness_execution_id=heid,
                generation=1,
            )

        parent = await leaser.allocator.acquire(holder(parent_id, read_only=False))
        with pytest.raises(WorkspaceError) as writer:
            await leaser.allocator.acquire(holder(uuid4(), read_only=False))
        assert writer.value.code == WORKSPACE_LEASE_HELD
        joined = await leaser.allocator.acquire(holder(helper_id, read_only=True))
        helper_key = f"codex:{helper_id}:1"
        assert joined.lease_id == parent.lease_id and joined.fence == parent.fence
        assert joined.participants == {helper_key: "active"}
        await leaser.release(parent, patch_artifact_ref=LANE_PATCH)

        with pytest.raises(WorkspaceError) as retained:
            await clean(parent_id)
        assert retained.value.code == WORKSPACE_SHARED_ACTIVE and present(parent.path)
        left = await leaser.allocator.leave_shared(joined, participant=helper_key)
        assert left.released and left.participants == {helper_key: "left"}
        assert await clean(helper_id) == "not_required"
        assert await clean(parent_id) == "removed" and not present(parent.path)
    finally:
        await pool.close()
