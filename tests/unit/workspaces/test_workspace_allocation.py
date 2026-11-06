"""MP-04 allocation on real git repositories: dedicated clones, unique branches, path
containment, dirty-input policy, reuse bounds, custody-gated cleanup and provider workspaces."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from mission_control.adapters.cursor.cloud import parse_branch_snapshot
from mission_control.adapters.cursor.git_workspaces import run_git
from mission_control.adapters.workspaces.git_workspaces import GitWorkspaceBackend
from mission_control.application.execution.harness.leases import StaleWorkspaceLease
from mission_control.application.workspaces.errors import (
    CHECKPOINT_INVALID,
    WORKSPACE_BRANCH_COLLISION,
    WORKSPACE_CUSTODY_MISSING,
    WORKSPACE_CUSTODY_STALE,
    WORKSPACE_DIRTY_INPUT,
    WORKSPACE_LEASE_HELD,
    WORKSPACE_NOT_OWNED,
    WORKSPACE_PATH_ESCAPE,
    WORKSPACE_PATH_OCCUPIED,
    WORKSPACE_POLICY_UNSUPPORTED,
    WORKSPACE_SHARED_ACTIVE,
    WorkspaceError,
)
from mission_control.application.workspaces.policy import (
    admit_policy,
    holder_key,
    slot_branch,
    slot_of,
    slot_path,
)
from mission_control.application.workspaces.service import AllocationRequest, WorkspaceAllocator
from tests.unit.workspaces.workspace_fixtures import (
    SCOPE,
    commit,
    git,
    link,
    policy,
    porcelain,
    present,
    request,
    stack,
    within,
)


def _index_digest(checkout: Path) -> str:
    return hashlib.sha256((checkout / ".git" / "index").read_bytes()).hexdigest()


async def test_a_managed_worktree_comes_from_a_dedicated_clone_on_a_unique_branch(
    tmp_path: Path,
) -> None:
    s = stack(tmp_path)
    primary_worktrees = git("worktree", "list", "--porcelain", cwd=s.primary)
    lease = await s.allocator.allocate(request(s.primary))
    root = Path(lease.path)
    assert within(root, s.root)
    assert lease.base_commit == git("rev-parse", "main", cwd=s.primary).strip()
    assert git("rev-parse", "HEAD", cwd=root).strip() == lease.base_commit
    assert lease.branch is not None and lease.branch.startswith("mc/ws/")
    assert git("symbolic-ref", "--short", "HEAD", cwd=root).strip() == lease.branch
    common = Path(git("rev-parse", "--git-common-dir", cwd=root).strip())
    assert (root / common).resolve().is_relative_to((s.root / "_clones").resolve())
    # The developer's checkout gained no worktree, branch or index write.
    assert git("worktree", "list", "--porcelain", cwd=s.primary) == primary_worktrees
    assert lease.branch not in git("branch", "--list", cwd=s.primary)
    assert lease.fence == 1 and lease.slot == "run:run-1"


async def test_a_dirty_primary_checkout_is_refused_and_left_untouched(tmp_path: Path) -> None:
    s = stack(tmp_path)
    (s.primary / "a.txt").write_bytes(b"uncommitted\n")
    (s.primary / "scratch.txt").write_bytes(b"untracked\n")
    status, index = porcelain(s.primary), _index_digest(s.primary)
    with pytest.raises(WorkspaceError) as dirty:
        await s.allocator.allocate(request(s.primary))
    assert dirty.value.code == WORKSPACE_DIRTY_INPUT
    assert porcelain(s.primary) == status and _index_digest(s.primary) == index
    assert s.ledger._leases == {}


async def test_a_declared_dirty_snapshot_carries_the_checkout_without_touching_it(
    tmp_path: Path,
) -> None:
    s = stack(tmp_path)
    (s.primary / "b.txt").write_bytes(b"staged in the checkout\n")
    git("add", "b.txt", cwd=s.primary)
    (s.primary / "a.txt").write_bytes(b"unstaged in the checkout\n")
    (s.primary / "new.txt").write_bytes(b"untracked in the checkout\n")
    status, index = porcelain(s.primary), _index_digest(s.primary)
    lease = await s.allocator.allocate(
        request(s.primary, policy=policy(dirty_input="snapshot")), artifacts=s.artifacts
    )
    assert porcelain(s.primary) == status and _index_digest(s.primary) == index
    root = Path(lease.path)
    assert porcelain(root) == status
    assert (root / "a.txt").read_bytes() == b"unstaged in the checkout\n"
    assert git("show", ":b.txt", cwd=root) == "staged in the checkout\n"
    assert lease.input_snapshot_ref is not None
    assert lease.input_snapshot_ref.startswith("workspace-snapshot:")
    # Without custody, or onto a base that is not the checkout's HEAD, it is refused.
    with pytest.raises(WorkspaceError) as no_custody:
        await s.allocator.allocate(
            request(s.primary, run_id="run-2", policy=policy(dirty_input="snapshot"))
        )
    assert no_custody.value.code == WORKSPACE_DIRTY_INPUT
    base = git("rev-parse", "HEAD", cwd=s.primary).strip()
    git("stash", "--quiet", "--include-untracked", cwd=s.primary)
    (s.primary / "z.txt").write_bytes(b"z\n")
    git("add", "z.txt", cwd=s.primary)
    commit(s.primary, "next")
    git("stash", "pop", "--quiet", cwd=s.primary)
    with pytest.raises(WorkspaceError) as elsewhere:
        await s.allocator.allocate(
            request(
                s.primary, run_id="run-3", base_ref=base, policy=policy(dirty_input="snapshot")
            ),
            artifacts=s.artifacts,
        )
    assert elsewhere.value.code == WORKSPACE_DIRTY_INPUT


async def test_a_branch_collision_is_refused_and_does_not_strand_the_slot(tmp_path: Path) -> None:
    s = stack(tmp_path)
    first = await s.allocator.allocate(request(s.primary, run_id="run-warm"))
    clone = (
        Path(first.path) / Path(git("rev-parse", "--git-common-dir", cwd=Path(first.path)).strip())
    ).resolve()
    branch = slot_branch(SCOPE, "run:run-taken")
    run_git("branch", branch, first.base_commit, cwd=clone)
    with pytest.raises(WorkspaceError) as collision:
        await s.allocator.allocate(request(s.primary, run_id="run-taken"))
    assert collision.value.code == WORKSPACE_BRANCH_COLLISION
    (stranded,) = await s.ledger.slot_leases(SCOPE, "run:run-taken")
    assert stranded.released and stranded.cleanup_status == "not_required"
    # The pre-existing branch was neither moved nor reused.
    assert run_git("rev-parse", branch, cwd=clone).decode().strip() == first.base_commit


async def test_paths_that_resolve_out_of_the_root_are_refused(tmp_path: Path) -> None:
    s = stack(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    s.root.mkdir(parents=True)
    # The slot's first path component under the root is a link out of it.
    escaping = slot_path(s.root, SCOPE, "run:run-escape").relative_to(s.root.resolve())
    link(outside, s.root / escaping.parts[0])
    with pytest.raises(WorkspaceError) as escaped:
        await s.allocator.allocate(request(s.primary, run_id="run-escape"))
    assert escaped.value.code == WORKSPACE_PATH_ESCAPE
    assert list(outside.iterdir()) == []
    nested = WorkspaceAllocator(
        ledger=s.ledger, backend=s.backend, root=s.primary / ".leases", allocator_ref="x"
    )
    with pytest.raises(WorkspaceError) as inside:
        await nested.allocate(request(s.primary))
    assert inside.value.code == WORKSPACE_PATH_ESCAPE
    occupied = slot_path(s.root, SCOPE, "run:run-occupied")
    occupied.mkdir(parents=True)
    (occupied / "user-file.txt").write_bytes(b"not ours\n")
    with pytest.raises(WorkspaceError) as taken:
        await s.allocator.allocate(request(s.primary, run_id="run-occupied"))
    assert taken.value.code == WORKSPACE_PATH_OCCUPIED
    assert (occupied / "user-file.txt").read_bytes() == b"not ours\n"


async def test_within_run_reuse_hands_the_worktree_on_one_holder_at_a_time(
    tmp_path: Path,
) -> None:
    s = stack(tmp_path)
    first = await s.allocator.allocate(request(s.primary))
    (Path(first.path) / "progress.txt").write_bytes(b"step one\n")
    with pytest.raises(WorkspaceError) as held:
        await s.allocator.allocate(request(s.primary))
    assert held.value.code == WORKSPACE_LEASE_HELD
    custody = await s.allocator.snapshot(first, artifacts=s.artifacts)
    await s.allocator.release(first, custody=custody)
    second = await s.allocator.allocate(request(s.primary))
    assert (second.path, second.branch, second.fence) == (first.path, first.branch, 2)
    assert (Path(second.path) / "progress.txt").read_bytes() == b"step one\n"
    # The first holder's worktree now belongs to the second: no late writes, and nothing left
    # for the first holder to clean up, before or after the second removed it.
    with pytest.raises(StaleWorkspaceLease):
        await s.allocator.snapshot(first, artifacts=s.artifacts)
    assert await s.allocator.cleanup(first, artifacts=s.artifacts) == "not_required"
    handed_on = await s.ledger.get(SCOPE, first.lease_id)
    assert handed_on is not None and handed_on.cleanup_status == "not_required"
    assert present(second.path)
    custody = await s.allocator.snapshot(second, artifacts=s.artifacts)
    released = await s.allocator.release(second, custody=custody)
    assert await s.allocator.cleanup(released, artifacts=s.artifacts) == "removed"
    assert await s.allocator.cleanup(first, artifacts=s.artifacts) == "not_required"


async def test_cleanup_removes_only_an_owned_released_and_registered_worktree(
    tmp_path: Path,
) -> None:
    s = stack(tmp_path)
    lease = await s.allocator.allocate(request(s.primary, policy=policy(reuse="none")))
    root = Path(lease.path)
    (root / "work.txt").write_bytes(b"agent output\n")
    with pytest.raises(StaleWorkspaceLease):
        await s.allocator.cleanup(lease, artifacts=s.artifacts)
    custody = await s.allocator.snapshot(lease, artifacts=s.artifacts)
    released = await s.allocator.release(lease, custody=custody)
    stranger = WorkspaceAllocator(
        ledger=s.ledger, backend=s.backend, root=s.root, allocator_ref="worker-b"
    )
    with pytest.raises(WorkspaceError) as foreign:
        await stranger.cleanup(released, artifacts=s.artifacts)
    assert foreign.value.code == WORKSPACE_NOT_OWNED
    (root / "late.txt").write_bytes(b"written after custody\n")
    with pytest.raises(WorkspaceError) as changed:
        await s.allocator.cleanup(released, artifacts=s.artifacts)
    assert changed.value.code == WORKSPACE_CUSTODY_STALE
    assert (root / "late.txt").exists()
    (root / "late.txt").unlink()
    assert await s.allocator.cleanup(released, artifacts=s.artifacts) == "removed"
    assert not present(root)
    clone = s.backend.clone_path(str(s.primary))
    assert lease.branch is not None
    assert run_git("branch", "--list", lease.branch, cwd=clone) == b""
    assert await s.allocator.cleanup(released, artifacts=s.artifacts) == "already_removed"


async def test_failed_work_without_custody_and_retained_leases_are_kept(tmp_path: Path) -> None:
    s = stack(tmp_path)
    failed = await s.allocator.allocate(request(s.primary, run_id="run-failed"))
    (Path(failed.path) / "partial.txt").write_bytes(b"half done\n")
    released = await s.allocator.release(failed, custody=None)
    with pytest.raises(WorkspaceError) as missing:
        await s.allocator.cleanup(released, artifacts=s.artifacts)
    assert missing.value.code == WORKSPACE_CUSTODY_MISSING
    assert (Path(failed.path) / "partial.txt").exists()
    kept = await s.allocator.allocate(
        request(s.primary, run_id="run-kept", policy=policy(cleanup="retain"))
    )
    custody = await s.allocator.snapshot(kept, artifacts=s.artifacts)
    released_kept = await s.allocator.release(kept, custody=custody)
    assert await s.allocator.cleanup(released_kept, artifacts=s.artifacts) == "retained"
    assert present(kept.path)


async def test_immediate_cleanup_runs_at_release_after_custody(tmp_path: Path) -> None:
    s = stack(tmp_path)
    lease = await s.allocator.allocate(
        request(s.primary, policy=policy(reuse="none", cleanup="immediate"))
    )
    (Path(lease.path) / "x.txt").write_bytes(b"x\n")
    custody = await s.allocator.snapshot(lease, artifacts=s.artifacts)
    released = await s.allocator.release(lease, custody=custody)
    assert released.cleanup_status == "completed" and not present(lease.path)
    assert released.snapshot_ref == custody.snapshot_ref
    assert released.patch_artifact_ref == custody.snapshot.patch_artifact_ref


async def test_a_holder_fenced_out_after_expiry_cannot_write(tmp_path: Path) -> None:
    s = stack(tmp_path)
    stale = await s.allocator.allocate(request(s.primary))
    s.clock.advance(timedelta(hours=5))
    successor = await s.allocator.allocate(request(s.primary))
    assert successor.fence == stale.fence + 1 and successor.path == stale.path
    lost = await s.ledger.get(SCOPE, stale.lease_id)
    assert lost is not None and lost.observed_state == "lost"
    assert lost.lost_to == successor.lease_id
    for write in (
        s.allocator.renew(stale),
        s.allocator.snapshot(stale, artifacts=s.artifacts),
        s.allocator.release(stale, custody=None),
    ):
        with pytest.raises(StaleWorkspaceLease):
            await write
    with pytest.raises(WorkspaceError) as successor_owns:
        await s.allocator.cleanup(lost, artifacts=s.artifacts)
    assert successor_owns.value.code == WORKSPACE_NOT_OWNED
    assert present(successor.path)


async def test_provider_workspaces_record_the_actual_branch_head(tmp_path: Path) -> None:
    s = stack(tmp_path)
    heid = uuid4()
    lease = await s.allocator.allocate_provider_workspace(
        request(
            "https://example.invalid/repo.git",
            lane_profile="cursor_cloud",
            harness_execution_id=heid,
            policy=policy(mode="provider_workspace", reuse="within_session"),
        ),
        branch="mc/run-1",
        base_commit="1" * 40,
    )
    with pytest.raises(WorkspaceError) as local:
        await s.allocator.snapshot(lease, artifacts=s.artifacts)
    assert local.value.code == WORKSPACE_POLICY_UNSUPPORTED
    captured = await s.allocator.record_provider_snapshot(lease, head_commit="2" * 40)
    assert parse_branch_snapshot(captured.snapshot_ref) == ("mc/run-1", "2" * 40)
    assert captured.snapshot.head_commit == "2" * 40
    assert captured.snapshot.base_commit == "1" * 40
    assert captured.snapshot.patch_artifact_ref is None
    released = await s.allocator.release(lease, custody=captured)
    assert released.cleanup_status == "not_required"
    assert await s.allocator.cleanup(released, artifacts=s.artifacts) == "not_required"


@pytest.mark.parametrize("profile", ["claude_cloud", "codex_cloud"])
async def test_unqualified_hosted_profiles_are_refused_not_emulated(
    tmp_path: Path, profile: str
) -> None:
    s = stack(tmp_path)
    for mode in ("provider_workspace", "managed_worktree", "shared_checkout"):
        with pytest.raises(WorkspaceError) as refused:
            admit_policy(profile, policy(mode=mode))
        assert refused.value.code == WORKSPACE_POLICY_UNSUPPORTED
    with pytest.raises(WorkspaceError):
        await s.allocator.allocate_provider_workspace(
            request(
                "https://example.invalid/repo.git",
                lane_profile=profile,
                policy=policy(mode="provider_workspace"),
            ),
            branch="b",
            base_commit="1" * 40,
        )
    assert s.ledger._leases == {} and not s.root.exists()


def test_the_mode_matrix_matches_placement() -> None:
    assert admit_policy("cursor_cloud", policy(mode="provider_workspace"))
    for local in ("cursor_local", "claude_agent_sdk", "codex"):
        assert admit_policy(local, policy())
        with pytest.raises(WorkspaceError):
            admit_policy(local, policy(mode="provider_workspace"))
    with pytest.raises(WorkspaceError):
        admit_policy("cursor_cloud", policy())
    with pytest.raises(WorkspaceError):
        admit_policy("codex", policy(mode="shared_checkout", reuse="none"))
    with pytest.raises(WorkspaceError):
        admit_policy("codex", policy(cleanup="immediate"))
    heid = uuid4()
    assert (
        slot_of(
            policy(reuse="none"),
            lane_profile="codex",
            harness_execution_id=heid,
            generation=2,
            run_id="r",
        )
        == f"holder:codex:{heid}:2"
    )
    assert (
        slot_of(
            policy(reuse="within_session"),
            lane_profile="codex",
            harness_execution_id=heid,
            generation=2,
            run_id="r",
        )
        == f"session:codex:{heid}"
    )


async def test_shared_checkout_participants_hold_the_parent_fence(tmp_path: Path) -> None:
    s = stack(tmp_path)
    parent = await s.allocator.allocate_shared_parent(
        request(s.primary, policy=policy(mode="shared_checkout"))
    )
    grant = await s.allocator.join_shared(parent, participant="subagent-1", read_only=True)
    assert grant.path == parent.path and grant.parent_fence == parent.fence
    recorded = await s.ledger.get(SCOPE, parent.lease_id)
    assert recorded is not None and recorded.active_participants == ("subagent-1",)
    assert (await s.allocator.verify_grant(grant)).lease_id == parent.lease_id
    with pytest.raises(WorkspaceError) as direct:
        await s.allocator.allocate(request(s.primary, policy=policy(mode="shared_checkout")))
    assert direct.value.code == WORKSPACE_POLICY_UNSUPPORTED
    exclusive = await s.allocator.allocate(request(s.primary, run_id="run-exclusive"))
    with pytest.raises(WorkspaceError):
        await s.allocator.join_shared(exclusive, participant="subagent-2")
    await s.allocator.release(parent, custody=None)
    with pytest.raises(StaleWorkspaceLease):
        await s.allocator.verify_grant(grant)


# --- MO-05: the lanes' entry point, reuse after cleanup, shared checkouts ----------------------


async def test_a_cleaned_slot_continues_from_its_retained_custody_snapshot(
    tmp_path: Path,
) -> None:
    s = stack(tmp_path)
    first = await s.allocator.acquire(request(s.primary), artifacts=s.artifacts)
    root = Path(first.path)
    (root / "a.txt").write_bytes(b"edited by the first holder\n")
    (root / "b.txt").write_bytes(b"staged by the first holder\n")
    git("add", "b.txt", cwd=root)
    (root / "notes.txt").write_bytes(b"untracked\n")
    state = porcelain(root)
    custody = await s.allocator.snapshot(first, artifacts=s.artifacts)
    released = await s.allocator.release(first, custody=custody)
    assert released.workspace_snapshot_ref == custody.snapshot_ref == released.snapshot_ref
    assert await s.allocator.cleanup(released, artifacts=s.artifacts) == "removed"
    assert not present(root)

    second = await s.allocator.acquire(request(s.primary), artifacts=s.artifacts)
    assert (second.path, second.branch, second.fence) == (first.path, first.branch, 2)
    assert porcelain(root) == state
    assert (root / "a.txt").read_bytes() == b"edited by the first holder\n"
    assert git("show", ":b.txt", cwd=root) == "staged by the first holder\n"
    # The first holder's record and snapshot artifacts are retained.
    kept = await s.ledger.get(SCOPE, first.lease_id)
    assert kept is not None and kept.workspace_snapshot_ref == custody.snapshot_ref
    assert custody.manifest_ref is not None and custody.manifest_ref in s.artifacts.staged


async def test_a_holder_under_another_root_continues_from_custody(tmp_path: Path) -> None:
    s = stack(tmp_path)
    first = await s.allocator.acquire(request(s.primary), artifacts=s.artifacts)
    (Path(first.path) / "a.txt").write_bytes(b"work of the first lane\n")
    custody = await s.allocator.snapshot(first, artifacts=s.artifacts)
    released = await s.allocator.release(first, custody=custody)
    other_root = tmp_path / "other-lane"
    other = WorkspaceAllocator(
        ledger=s.ledger,
        backend=GitWorkspaceBackend(other_root),
        root=other_root,
        allocator_ref="worker-b",
    )
    second = await other.acquire(request(s.primary, lane_profile="codex"), artifacts=s.artifacts)
    assert within(second.path, other_root)
    assert (Path(second.path) / "a.txt").read_bytes() == b"work of the first lane\n"
    # The first worktree was not handed on in place: its own allocator still removes it.
    assert await s.allocator.cleanup(released, artifacts=s.artifacts) == "removed"
    assert present(second.path)


async def test_a_refused_continuation_keeps_the_slot_work_for_the_next_holder(
    tmp_path: Path,
) -> None:
    s = stack(tmp_path)
    first = await s.allocator.acquire(request(s.primary), artifacts=s.artifacts)
    (Path(first.path) / "a.txt").write_bytes(b"precious\n")
    custody = await s.allocator.snapshot(first, artifacts=s.artifacts)
    released = await s.allocator.release(first, custody=custody)
    assert await s.allocator.cleanup(released, artifacts=s.artifacts) == "removed"
    assert custody.manifest_ref is not None
    manifest = s.artifacts.staged.pop(custody.manifest_ref)
    with pytest.raises(WorkspaceError) as refused:
        await s.allocator.acquire(request(s.primary), artifacts=s.artifacts)
    assert refused.value.code == CHECKPOINT_INVALID
    # The fresh worktree is gone and the refused lease never held work.
    assert not present(first.path)
    refused_lease = (await s.ledger.slot_leases(SCOPE, "run:run-1"))[-1]
    assert refused_lease.released and refused_lease.cleanup_status == "not_required"
    s.artifacts.staged[custody.manifest_ref] = manifest
    third = await s.allocator.acquire(request(s.primary), artifacts=s.artifacts)
    assert (Path(third.path) / "a.txt").read_bytes() == b"precious\n"


async def test_a_writable_holder_never_joins_a_live_shared_checkout_parent(
    tmp_path: Path,
) -> None:
    s = stack(tmp_path)
    shared = policy(mode="shared_checkout")
    parent = await s.allocator.acquire(request(s.primary, policy=shared))
    work = Path(parent.path) / "a.txt"
    work.write_bytes(b"the parent's work\n")
    with pytest.raises(WorkspaceError) as held:
        await s.allocator.acquire(request(s.primary, policy=shared))
    assert held.value.code == WORKSPACE_LEASE_HELD
    assert work.read_bytes() == b"the parent's work\n"
    custody = await s.allocator.snapshot(parent, artifacts=s.artifacts)
    released = await s.allocator.release(parent, custody=custody)
    # Once the parent released it, the next writable holder continues it in place.
    successor = await s.allocator.acquire(request(s.primary, policy=shared))
    assert (successor.path, successor.fence) == (parent.path, parent.fence + 1)
    assert work.read_bytes() == b"the parent's work\n"
    assert await s.allocator.cleanup(released, artifacts=s.artifacts) == "not_required"
    assert present(successor.path)


async def test_read_only_helpers_join_a_live_shared_checkout_parent(tmp_path: Path) -> None:
    s = stack(tmp_path)
    shared = policy(mode="shared_checkout")
    parent_id, helper_id = uuid4(), uuid4()

    def helper() -> AllocationRequest:
        return request(s.primary, harness_execution_id=helper_id, policy=shared, read_only=True)

    async def clean(holder: UUID) -> str:
        return await s.allocator.cleanup_holder(
            request_scope=SCOPE,
            lane_profile="claude_agent_sdk",
            harness_execution_id=holder,
            generation=1,
            artifacts=s.artifacts,
        )

    with pytest.raises(WorkspaceError) as no_parent:
        await s.allocator.acquire(helper())
    assert no_parent.value.code == WORKSPACE_POLICY_UNSUPPORTED
    parent = await s.allocator.acquire(
        request(s.primary, harness_execution_id=parent_id, policy=shared)
    )
    joined = await s.allocator.acquire(helper())
    helper_key = holder_key("claude_agent_sdk", helper_id, 1)
    assert joined.lease_id == parent.lease_id and joined.fence == parent.fence
    assert joined.active_participants == (helper_key,)
    assert await clean(helper_id) == "not_required"
    custody = await s.allocator.snapshot(parent, artifacts=s.artifacts)
    await s.allocator.release(parent, custody=custody)
    # The parent settled first: its worktree is retained while the helper still reads it.
    with pytest.raises(WorkspaceError) as retained:
        await clean(parent_id)
    assert retained.value.code == WORKSPACE_SHARED_ACTIVE and present(parent.path)
    left = await s.allocator.leave_shared(joined, participant=helper_key)
    assert not left.active_participants
    assert await clean(parent_id) == "removed"
    assert not present(parent.path)


async def test_a_slot_holder_outside_this_root_without_custody_is_never_dropped(
    tmp_path: Path,
) -> None:
    s = stack(tmp_path)
    first = await s.allocator.acquire(request(s.primary), artifacts=s.artifacts)
    (Path(first.path) / "a.txt").write_bytes(b"released without custody\n")
    await s.allocator.release(first, custody=None)
    other_root = tmp_path / "other-lane"
    other = WorkspaceAllocator(
        ledger=s.ledger,
        backend=GitWorkspaceBackend(other_root),
        root=other_root,
        allocator_ref="worker-b",
    )
    with pytest.raises(WorkspaceError) as refused:
        await other.acquire(request(s.primary, lane_profile="codex"), artifacts=s.artifacts)
    assert refused.value.code == WORKSPACE_CUSTODY_MISSING
    assert (Path(first.path) / "a.txt").read_bytes() == b"released without custody\n"
    assert len(await s.ledger.slot_leases(SCOPE, "run:run-1")) == 1


async def test_a_restarted_worker_on_the_same_root_cleans_what_it_released(
    tmp_path: Path,
) -> None:
    root = tmp_path / "leases"
    s = stack(tmp_path, owner=GitWorkspaceBackend(root).owner_ref)
    lease = await s.allocator.acquire(request(s.primary), artifacts=s.artifacts)
    custody = await s.allocator.snapshot(lease, artifacts=s.artifacts)
    released = await s.allocator.release(lease, custody=custody)
    restarted = GitWorkspaceBackend(root)
    successor = WorkspaceAllocator(
        ledger=s.ledger, backend=restarted, root=root, allocator_ref=restarted.owner_ref
    )
    assert await successor.cleanup(released, artifacts=s.artifacts) == "removed"
    assert GitWorkspaceBackend(tmp_path / "elsewhere").owner_ref != restarted.owner_ref


@pytest.mark.parametrize("profile", ["claude_managed", "codex_agents"])
def test_api_workspace_admits_bundle_custody_without_snapshot_control(profile: str) -> None:
    from mission_control.application.execution.harness.describe import declared_matrix

    assert admit_policy(profile, policy(mode="provider_workspace"))
    assert declared_matrix(profile).controls["snapshot"] in {"unsupported", "unqualified"}
    with pytest.raises(WorkspaceError):
        admit_policy(profile, policy(mode="managed_worktree"))
