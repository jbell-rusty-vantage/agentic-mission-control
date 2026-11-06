"""MO-05: every local lane leases its workspace through the MP-04 allocator under the binding's
workspace policy (SPEC-03 sections 2 and 7).

Each lane (`claude_agent_sdk`, `codex`, `cursor_local`) runs two holders of one run on a real
git repository. Under `within_run` the first holder's work is registered as custody at
`end_session`, its worktree is kept until `cleanup_workspace` (what `lane.cleanup` calls after
settlement) removes it, the snapshot is retained, and the second holder continues from it; a
worktree that changed after its snapshot is never removed. Under `shared_checkout` a second
unit's session never joins the live parent (it would overwrite the parent's per-session files);
it continues the parent's worktree in place once the parent's session ended.
No provider session is started: the lanes' workspace lifecycle is driven through the harness
protocol directly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mission_control.application.execution.harness.protocol import WorkspaceLeasingLane
from mission_control.application.workspaces.errors import (
    WORKSPACE_CUSTODY_STALE,
    WORKSPACE_LEASE_HELD,
    WorkspaceError,
)
from mission_control.application.workspaces.snapshots import (
    load_manifest,
    manifest_ref_of,
    verified_bytes,
)
from tests.fixtures.cursor_local import local_stack
from tests.fixtures.local_lane_workspaces import LANES, SHARED, WITHIN_RUN, LaneDriver


def _files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@pytest.mark.parametrize("profile", sorted(LANES))
async def test_within_run_reuse_cleanup_and_retained_snapshots(
    tmp_path: Path, profile: str
) -> None:
    lane = LANES[profile](tmp_path, WITHIN_RUN)
    assert isinstance(lane.harness, WorkspaceLeasingLane)
    root = await lane.prepare(1)
    first = await lane.lease(1)
    # The binding's manifest policy, not a lane default, decided the lease.
    assert first is not None and first.policy == WITHIN_RUN
    assert first.slot == f"run:{lane.operation.identity.run_id}" and first.branch is not None
    (root / "src").mkdir(exist_ok=True)
    (root / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "src" / "feature.py").write_text("FIRST = True\n", encoding="utf-8")
    assert await lane.end(1)

    released = await lane.lease(1)
    assert released is not None and released.released
    assert released.workspace_snapshot is not None
    assert released.workspace_snapshot_ref is not None
    # Kept for the slot until cleanup runs after settlement.
    assert released.cleanup_status == "pending" and root.is_dir()
    assert await lane.cleanup(1) == "removed"
    assert not root.exists()
    assert await lane.cleanup(1) == "already_removed"
    # The snapshot is retained: its manifest and artifacts still read back from custody.
    manifest_ref = manifest_ref_of(released.workspace_snapshot_ref)
    assert manifest_ref is not None
    manifest = await load_manifest(released.workspace_snapshot, manifest_ref, lane.artifacts)
    patch = await verified_bytes(lane.artifacts, manifest.patch, "patch")
    assert b"src/feature.py" in patch and b"VALUE = 1" in patch

    # The run's next holder continues from the snapshot in a fresh worktree of the slot.
    continued = await lane.prepare(2)
    second = await lane.lease(2)
    assert second is not None and second.slot == first.slot and second.fence > first.fence
    assert continued == root
    assert (continued / "src" / "app.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert (continued / "src" / "feature.py").read_text(encoding="utf-8") == "FIRST = True\n"
    assert await lane.end(2)

    # Work written after the registered snapshot is never force-deleted.
    (continued / "late.txt").write_text("unsnapshotted\n", encoding="utf-8")
    with pytest.raises(WorkspaceError) as kept:
        await lane.cleanup(2)
    assert kept.value.code == WORKSPACE_CUSTODY_STALE
    assert (continued / "late.txt").read_text(encoding="utf-8") == "unsnapshotted\n"


@pytest.mark.parametrize("profile", sorted(LANES))
async def test_a_writable_session_never_joins_a_live_shared_checkout_parent(
    tmp_path: Path, profile: str
) -> None:
    parent = LANES[profile](tmp_path, SHARED)
    helper = parent.another_unit("helper-unit")
    root = await parent.prepare(1)
    edit = root / "parent.py"
    edit.write_text("PARENT = True\n", encoding="utf-8")
    session_files = _files(root / ".mission")
    # The helper would rewrite the parent's packet, hook context, token and state roots.
    with pytest.raises(WorkspaceError) as held:
        await helper.prepare(1)
    assert held.value.code == WORKSPACE_LEASE_HELD
    assert _files(root / ".mission") == session_files
    assert await helper.lease(1) is None

    # Once the parent's session ended, the helper continues its worktree in place; the parent
    # handed it on and has nothing left to clean up.
    assert await parent.end(1)
    assert await helper.prepare(1) == root
    assert edit.read_text(encoding="utf-8") == "PARENT = True\n"
    assert await parent.cleanup(1) == "not_required"
    assert await helper.end(1)
    assert await helper.cleanup(1) == "removed"
    assert not root.exists()
    assert await parent.cleanup(1) == "not_required"


async def test_a_research_lease_reports_the_removal_it_had_at_release(tmp_path: Path) -> None:
    stack = local_stack(tmp_path, repository=False)
    lane = LaneDriver("cursor_local", stack.harness, stack.operation, stack.leases, stack.artifacts)
    root = await lane.prepare(1)
    lease = await lane.lease(1)
    assert lease is not None and lease.slot is None and lease.repository is None
    assert await lane.end(1)
    assert not root.exists()
    assert await lane.cleanup(1) == "already_removed"
