"""Provider-neutral workspace allocation, snapshot, release and cleanup (SPEC-01 "Session
ownership" steps 1 and 8; SPEC-02 "Worktrees and snapshots"; MP-04).

Mission Control allocates the workspace; the agent does not choose whether isolation exists.
`WorkspaceAllocator.allocate` admits the policy for the lane profile, resolves the base commit
in a dedicated clone (never the developer's checkout), refuses a dirty input unless the policy
snapshots it, acquires the workspace slot exclusively through the fenced ledger and only then
materializes the worktree on the slot's unique branch. Every later write (snapshot record,
renewal, release) carries the lease's fence; a holder that was fenced out is refused.

A lease is released only after artifact custody: the caller passes the snapshot it stored.
Cleanup removes only a released lease this allocator owns, whose worktree was not handed on
to a later holder of its slot, whose snapshot was registered and whose worktree is still
exactly what that snapshot froze; `retain` never removes, a released lease without custody
keeps its failed work, and a dirty worktree is never force-deleted.

MO-05 (SPEC-03 section 2): every local lane leases through `acquire` under its binding's
policy. A reused slot (`within_run`, `within_session`) hands the worktree on in place while
it exists under this root; once the operation workflow cleaned it up (or it lives under
another lane's root) the next holder starts a fresh worktree from the custody snapshot the
slot's newest holder registered, so cleanup never loses the slot's work (a newest holder
whose worktree lives under another root without custody is refused, never silently dropped).
Under `shared_checkout` the run's first holder leases the parent, which later holders continue
in place once it is released; while it is live only a read-only helper joins it (SPEC-03
section 2), recorded on the parent lease until it leaves, and the parent's cleanup refuses
while one still works there. A holder whose worktree was handed on in place has nothing left
to clean up.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from mission_control.application.execution.harness.leases import (
    WorkspaceLease,
    WorkspaceLeaseLedger,
    lease_identity,
)
from mission_control.application.workspaces.errors import (
    CHECKPOINT_INVALID,
    WORKSPACE_CUSTODY_MISSING,
    WORKSPACE_CUSTODY_STALE,
    WORKSPACE_DIRTY_INPUT,
    WORKSPACE_NOT_OWNED,
    WORKSPACE_POLICY_UNSUPPORTED,
    WORKSPACE_SHARED_ACTIVE,
    StaleWorkspaceLease,
    WorkspaceError,
)
from mission_control.application.workspaces.policy import (
    BRANCH_SNAPSHOT_PROFILES,
    admit_policy,
    contained,
    holder_key,
    inside,
    reject_nested_root,
    slot_branch,
    slot_of,
    slot_path,
)
from mission_control.application.workspaces.ports import SourceState, WorkspaceBackend
from mission_control.application.workspaces.snapshots import (
    CapturedSnapshot,
    RestoreReceipt,
    SnapshotArtifacts,
    branch_snapshot,
    load_manifest,
    manifest_ref_of,
)
from mission_control.domain.context.snapshot_evidence import ConversationEvidence
from mission_control.domain.execution.bindings import WorkspacePolicyPin, WorkspaceSnapshot
from mission_control.domain.execution.lane_turns import CleanupOutcome
from mission_control.domain.execution.lanes import LaneProfileName


def _utc_now() -> datetime:
    return datetime.now(UTC)


class AllocationRequest(BaseModel):
    """One holder's request for a workspace (one generation of one harness execution)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_scope: str = Field(min_length=1)
    lane_profile: LaneProfileName
    harness_execution_id: UUID
    generation: int = Field(ge=1)
    run_id: str = Field(min_length=1)
    attempt_no: int = Field(ge=1)
    policy: WorkspacePolicyPin
    repository: str | None = None
    base_ref: str = Field(min_length=1)
    # A helper that only reads the live parent of a `shared_checkout` (SPEC-03 section 2).
    read_only: bool = False


class SharedWorkspaceGrant(BaseModel):
    """A `shared_checkout` participant's access to its parent's leased worktree; valid while
    the parent lease is active under the same fence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_scope: str
    parent_lease_id: UUID
    parent_fence: int
    path: str
    participant: str = Field(min_length=1)
    read_only: bool


class WorkspaceAllocator:
    def __init__(
        self,
        *,
        ledger: WorkspaceLeaseLedger,
        backend: WorkspaceBackend,
        root: Path,
        allocator_ref: str,
        clock: Callable[[], datetime] = _utc_now,
        lease_ttl: timedelta = timedelta(hours=4),
    ) -> None:
        self._ledger = ledger
        self._backend = backend
        self._root = root
        self._allocator_ref = allocator_ref
        self._clock = clock
        self._ttl = lease_ttl

    @property
    def root(self) -> Path:
        return self._root

    # --- allocation -----------------------------------------------------------------------

    async def acquire(
        self, request: AllocationRequest, *, artifacts: SnapshotArtifacts | None = None
    ) -> WorkspaceLease:
        """The workspace a local lane holder works in, as its policy declares (MO-05).

        `managed_worktree` allocates the holder's own lease. Under `shared_checkout` the run's
        first holder leases the parent worktree, which a later holder continues in place once
        the parent released it. While the parent is live a writable holder is refused
        (`WorkspaceLeaseHeld`): every local lane session writes its own packet, hook context,
        callback token and state roots at fixed paths of its worktree, and no coordination
        model is declared (SPEC-03 section 2). Only a `read_only` helper joins the live parent
        through `join_shared`; it works in the parent's lease under the parent's fence and
        leaves it with `leave_shared`.
        """

        policy = admit_policy(request.lane_profile, request.policy)
        if request.read_only:
            return await self._join_live_parent(request, policy)
        if policy.mode == "shared_checkout":
            return await self.allocate_shared_parent(request, artifacts=artifacts)
        return await self.allocate(request, artifacts=artifacts)

    async def _join_live_parent(
        self, request: AllocationRequest, policy: WorkspacePolicyPin
    ) -> WorkspaceLease:
        parent = await self._live_parent(request, policy)
        if parent is None:
            raise WorkspaceError(
                WORKSPACE_POLICY_UNSUPPORTED,
                "a read-only helper joins the live parent of a shared_checkout; none holds it",
            )
        grant = await self.join_shared(
            parent,
            participant=holder_key(
                request.lane_profile, request.harness_execution_id, request.generation
            ),
            read_only=True,
        )
        return await self.verify_grant(grant)

    async def _live_parent(
        self, request: AllocationRequest, policy: WorkspacePolicyPin
    ) -> WorkspaceLease | None:
        if policy.mode != "shared_checkout":
            return None
        slot = slot_of(
            policy,
            lane_profile=request.lane_profile,
            harness_execution_id=request.harness_execution_id,
            generation=request.generation,
            run_id=request.run_id,
        )
        active = [
            lease
            for lease in await self._ledger.slot_leases(request.request_scope, slot)
            if not lease.released
        ]
        return active[-1] if active else None

    async def allocate(
        self, request: AllocationRequest, *, artifacts: SnapshotArtifacts | None = None
    ) -> WorkspaceLease:
        policy = admit_policy(request.lane_profile, request.policy)
        if policy.mode == "provider_workspace":
            raise WorkspaceError(
                WORKSPACE_POLICY_UNSUPPORTED,
                "a provider workspace is recorded with allocate_provider_workspace",
            )
        if policy.mode == "shared_checkout":
            raise WorkspaceError(
                WORKSPACE_POLICY_UNSUPPORTED,
                "a shared_checkout participant joins its parent's lease with join_shared",
            )
        return await self._allocate_worktree(request, policy, artifacts)

    async def _allocate_worktree(
        self,
        request: AllocationRequest,
        policy: WorkspacePolicyPin,
        artifacts: SnapshotArtifacts | None,
    ) -> WorkspaceLease:
        local_source = _local_path(request.repository)
        await asyncio.to_thread(reject_nested_root, self._root, local_source)
        slot = slot_of(
            policy,
            lane_profile=request.lane_profile,
            harness_execution_id=request.harness_execution_id,
            generation=request.generation,
            run_id=request.run_id,
        )
        source = await self._backend.prepare_source(request.repository, request.base_ref)
        self._admit_source(source, policy)
        newest = _newest_holder(await self._ledger.slot_leases(request.request_scope, slot))
        prior = await asyncio.to_thread(_in_place, self._root, newest)
        carried = None if prior is not None else _custody(newest)
        if prior is None and carried is None and newest is not None and _holds_work(newest):
            raise WorkspaceError(
                WORKSPACE_CUSTODY_MISSING,
                f"the slot's work is in {newest.lease_key}'s worktree outside this root and "
                "has no custody snapshot to continue from",
            )
        if prior is not None:
            path, branch, base_commit = Path(prior.path), prior.branch, prior.base_commit
        else:
            path = slot_path(self._root, request.request_scope, slot)
            branch = slot_branch(request.request_scope, slot)
            base_commit = carried.base_commit if carried is not None else source.base_commit
        path = await asyncio.to_thread(contained, self._root, path)
        lease_id, key = lease_identity(
            request.lane_profile, request.harness_execution_id, request.generation
        )
        now = self._clock()
        claim = WorkspaceLease(
            lease_id=lease_id,
            request_scope=request.request_scope,
            lease_key=key,
            lane_profile=request.lane_profile,
            harness_execution_id=request.harness_execution_id,
            generation=request.generation,
            run_id=request.run_id,
            attempt_no=request.attempt_no,
            path=str(path),
            repository=request.repository,
            base_ref=request.base_ref,
            base_commit=base_commit,
            fence=0,
            expires_at=now + self._ttl,
            slot=slot,
            branch=branch,
            policy=policy,
            allocator_ref=self._allocator_ref,
        )
        held = await self._ledger.get(request.request_scope, lease_id)
        reacquired = held is not None and not held.released
        lease = await self._ledger.acquire(claim, now=now)
        if (reacquired or prior is not None) and await asyncio.to_thread(Path(lease.path).is_dir):
            await self._backend.verify(lease)
            return lease
        try:
            await self._backend.materialize(lease, source)
        except BaseException:
            await self._ledger.release_fenced(
                lease.request_scope,
                lease.lease_id,
                fence=lease.fence,
                patch_artifact_ref=None,
                snapshot_ref=None,
                released_at=self._clock(),
                cleanup_status="not_required",
            )
            raise
        if carried is not None:
            return await self._continue_slot_work(lease, carried, artifacts)
        if source.dirty:
            lease = await self._carry_dirty_input(lease, source, artifacts)
        return lease

    async def _continue_slot_work(
        self,
        lease: WorkspaceLease,
        prior: WorkspaceLease,
        artifacts: SnapshotArtifacts | None,
    ) -> WorkspaceLease:
        """Restore the custody snapshot the slot's newest holder registered into the fresh
        worktree; on any refusal the fresh worktree (nothing but the base) is removed."""

        assert prior.workspace_snapshot is not None and prior.workspace_snapshot_ref is not None
        manifest_ref = manifest_ref_of(prior.workspace_snapshot_ref)
        try:
            if artifacts is None or manifest_ref is None:
                raise WorkspaceError(
                    WORKSPACE_CUSTODY_MISSING, "continuing the slot's work needs its custody"
                )
            manifest = await load_manifest(prior.workspace_snapshot, manifest_ref, artifacts)
            await self._backend.restore(
                manifest, lease, artifacts, snapshot_ref=prior.workspace_snapshot_ref
            )
        except BaseException:
            await self._backend.remove(lease)
            await self._ledger.release_fenced(
                lease.request_scope,
                lease.lease_id,
                fence=lease.fence,
                patch_artifact_ref=None,
                snapshot_ref=None,
                released_at=self._clock(),
                cleanup_status="not_required",
            )
            raise
        return lease

    @staticmethod
    def _admit_source(source: SourceState, policy: WorkspacePolicyPin) -> None:
        if not source.dirty:
            return
        if policy.dirty_input == "reject":
            raise WorkspaceError(
                WORKSPACE_DIRTY_INPUT,
                f"the source checkout has {source.dirty_entries} uncommitted or untracked "
                "entries; commit them or declare dirty_input: snapshot",
            )
        if source.checkout_head != source.base_commit:
            raise WorkspaceError(
                WORKSPACE_DIRTY_INPUT,
                "a dirty checkout is snapshotted only onto its own HEAD; the requested base "
                f"{source.base_commit} is not the checkout HEAD {source.checkout_head}",
            )

    async def _carry_dirty_input(
        self, lease: WorkspaceLease, source: SourceState, artifacts: SnapshotArtifacts | None
    ) -> WorkspaceLease:
        if artifacts is None or source.checkout is None:
            raise WorkspaceError(
                WORKSPACE_DIRTY_INPUT, "snapshotting a dirty input needs artifact custody"
            )
        captured = await self._backend.capture(
            Path(source.checkout),
            lease=lease,
            artifacts=artifacts,
            name=f"workspace/{lease.lease_id}/input",
        )
        if captured.manifest is None:
            raise WorkspaceError(WORKSPACE_DIRTY_INPUT, "the dirty input produced no manifest")
        await self._backend.restore(
            captured.manifest, lease, artifacts, snapshot_ref=captured.snapshot_ref
        )
        return await self._ledger.record_snapshot(
            lease.request_scope,
            lease.lease_id,
            fence=lease.fence,
            snapshot=captured.snapshot,
            snapshot_ref=captured.snapshot_ref,
            input_snapshot=True,
        )

    async def allocate_provider_workspace(
        self, request: AllocationRequest, *, branch: str, base_commit: str
    ) -> WorkspaceLease:
        """Record a provider-hosted workspace (the provider isolates it; Mission Control holds
        the fenced record of its branch and base commit)."""

        policy = admit_policy(request.lane_profile, request.policy)
        if policy.mode != "provider_workspace":
            raise WorkspaceError(
                WORKSPACE_POLICY_UNSUPPORTED, f"{request.lane_profile} needs provider_workspace"
            )
        slot = slot_of(
            policy,
            lane_profile=request.lane_profile,
            harness_execution_id=request.harness_execution_id,
            generation=request.generation,
            run_id=request.run_id,
        )
        lease_id, key = lease_identity(
            request.lane_profile, request.harness_execution_id, request.generation
        )
        now = self._clock()
        claim = WorkspaceLease(
            lease_id=lease_id,
            request_scope=request.request_scope,
            lease_key=key,
            lane_profile=request.lane_profile,
            harness_execution_id=request.harness_execution_id,
            generation=request.generation,
            run_id=request.run_id,
            attempt_no=request.attempt_no,
            path=f"provider:{request.lane_profile}:{branch}",
            repository=request.repository,
            base_ref=request.base_ref,
            base_commit=base_commit,
            fence=0,
            expires_at=now + self._ttl,
            slot=slot,
            branch=branch,
            policy=policy,
            allocator_ref=self._allocator_ref,
        )
        return await self._ledger.acquire(claim, now=now)

    async def join_shared(
        self, parent: WorkspaceLease, *, participant: str, read_only: bool = False
    ) -> SharedWorkspaceGrant:
        """A `shared_checkout` participant joins the parent's worktree under its fence; the
        parent lease records it as active until it leaves (`leave_shared`)."""

        if parent.policy is None or parent.policy.mode != "shared_checkout":
            raise WorkspaceError(
                WORKSPACE_POLICY_UNSUPPORTED,
                "the parent lease does not declare the shared_checkout coordination model",
            )
        current = await self._current(parent)
        joined = await self._ledger.join_shared(
            current.request_scope, current.lease_id, fence=current.fence, participant=participant
        )
        return SharedWorkspaceGrant(
            request_scope=joined.request_scope,
            parent_lease_id=joined.lease_id,
            parent_fence=joined.fence,
            path=joined.path,
            participant=participant,
            read_only=read_only,
        )

    async def leave_shared(self, parent: WorkspaceLease, *, participant: str) -> WorkspaceLease:
        """The participant's session ended: it no longer works in the parent's worktree (whose
        holder may already have released it)."""

        return await self._ledger.leave_shared(
            parent.request_scope, parent.lease_id, participant=participant
        )

    async def verify_grant(self, grant: SharedWorkspaceGrant) -> WorkspaceLease:
        stored = await self._ledger.get(grant.request_scope, grant.parent_lease_id)
        if stored is None or stored.released or stored.fence != grant.parent_fence:
            raise StaleWorkspaceLease(
                str(grant.parent_lease_id), "the parent lease of this shared checkout moved on"
            )
        return stored

    async def allocate_shared_parent(
        self, request: AllocationRequest, *, artifacts: SnapshotArtifacts | None = None
    ) -> WorkspaceLease:
        """The parent of a `shared_checkout`: an exclusive worktree lease whose policy lets
        declared participants join it."""

        policy = admit_policy(request.lane_profile, request.policy)
        if policy.mode != "shared_checkout":
            raise WorkspaceError(WORKSPACE_POLICY_UNSUPPORTED, "the policy is not shared_checkout")
        return await self._allocate_worktree(request, policy, artifacts)

    # --- fenced writes ----------------------------------------------------------------------

    async def _current(self, lease: WorkspaceLease) -> WorkspaceLease:
        stored = await self._ledger.get(lease.request_scope, lease.lease_id)
        if stored is None:
            raise LookupError(f"workspace lease {lease.lease_id} is not recorded")
        if stored.released or stored.fence != lease.fence:
            raise StaleWorkspaceLease(
                lease.lease_key, f"the slot moved on (state {stored.observed_state})"
            )
        return stored

    async def renew(self, lease: WorkspaceLease) -> WorkspaceLease:
        return await self._ledger.renew(
            lease.request_scope,
            lease.lease_id,
            fence=lease.fence,
            expires_at=self._clock() + self._ttl,
        )

    async def snapshot(
        self,
        lease: WorkspaceLease,
        *,
        artifacts: SnapshotArtifacts,
        exclude: Sequence[str] = (),
    ) -> CapturedSnapshot:
        """Freeze the leased worktree and record the snapshot under the lease's fence."""

        current = await self._current(lease)
        if current.policy is not None and current.policy.mode == "provider_workspace":
            raise WorkspaceError(
                WORKSPACE_POLICY_UNSUPPORTED,
                "a provider workspace is snapshotted from its branch head "
                "(record_provider_snapshot)",
            )
        captured = await self._backend.capture(
            Path(current.path),
            lease=current,
            artifacts=artifacts,
            name=f"workspace/{current.lease_id}/f{current.fence}",
            exclude=exclude,
        )
        await self._ledger.record_snapshot(
            current.request_scope,
            current.lease_id,
            fence=current.fence,
            snapshot=captured.snapshot,
            snapshot_ref=captured.snapshot_ref,
        )
        return captured

    async def record_provider_snapshot(
        self,
        lease: WorkspaceLease,
        *,
        head_commit: str,
        conversation: ConversationEvidence | None = None,
    ) -> CapturedSnapshot:
        """Record the head commit the caller actually read back from the provider's branch."""

        current = await self._current(lease)
        if current.lane_profile not in BRANCH_SNAPSHOT_PROFILES or current.branch is None:
            raise WorkspaceError(
                WORKSPACE_POLICY_UNSUPPORTED,
                f"{current.lane_profile} does not publish a branch snapshot",
            )
        if conversation is not None and (
            conversation.origin.request_scope != current.request_scope
            or conversation.origin.run_id != current.run_id
            or conversation.origin.repository != current.repository
        ):
            raise WorkspaceError(
                CHECKPOINT_INVALID, "conversation origin differs from workspace lease"
            )
        captured = branch_snapshot(
            conversation=conversation,
            lane_profile=cast(LaneProfileName, current.lane_profile),
            branch=current.branch,
            head_commit=head_commit,
            base_commit=current.base_commit,
            producer_lease_id=current.lease_id,
            producer_generation=current.generation,
            captured_at=self._clock(),
        )
        await self._ledger.record_snapshot(
            current.request_scope,
            current.lease_id,
            fence=current.fence,
            snapshot=captured.snapshot,
            snapshot_ref=captured.snapshot_ref,
        )
        return captured

    async def restore(
        self,
        snapshot: WorkspaceSnapshot,
        snapshot_ref: str,
        target: WorkspaceLease,
        *,
        artifacts: SnapshotArtifacts,
    ) -> RestoreReceipt:
        """Re-apply a frozen snapshot into a fresh lease (a fork or a continuation target)."""

        manifest_ref = manifest_ref_of(snapshot_ref)
        if manifest_ref is None:
            raise WorkspaceError(
                CHECKPOINT_INVALID,
                f"{snapshot_ref} is not a local workspace snapshot; a provider branch "
                "snapshot is restored by starting the provider lane at its head",
            )
        current = await self._current(target)
        manifest = await load_manifest(snapshot, manifest_ref, artifacts)
        if current.base_commit != manifest.base_commit:
            raise WorkspaceError(
                CHECKPOINT_INVALID,
                f"the target lease is at {current.base_commit}, the snapshot at "
                f"{manifest.base_commit}",
            )
        return await self._backend.restore(manifest, current, artifacts, snapshot_ref=snapshot_ref)

    async def release(
        self,
        lease: WorkspaceLease,
        *,
        custody: CapturedSnapshot | None,
        patch_artifact_ref: str | None = None,
        snapshot_ref: str | None = None,
    ) -> WorkspaceLease:
        """Release after custody (`custody` is the snapshot the caller stored); `None`
        releases the slot but keeps the worktree as failed work. A lane that freezes a
        restorable snapshot of its own beside the custody (Cursor's `cursor-snapshot:`) passes
        it and its patch; they become the lease's `snapshot_ref` and `patch_artifact_ref`."""

        current = await self._current(lease)
        provider = current.policy is not None and current.policy.mode == "provider_workspace"
        if custody is not None and current.workspace_snapshot_ref != custody.snapshot_ref:
            raise WorkspaceError(
                WORKSPACE_CUSTODY_MISSING, "the custody snapshot was not recorded on this lease"
            )
        released = await self._ledger.release_fenced(
            current.request_scope,
            current.lease_id,
            fence=current.fence,
            patch_artifact_ref=patch_artifact_ref
            or (custody.snapshot.patch_artifact_ref if custody is not None else None),
            snapshot_ref=snapshot_ref or (custody.snapshot_ref if custody is not None else None),
            released_at=self._clock(),
            cleanup_status="not_required" if provider else "pending",
        )
        policy = current.policy
        if (
            custody is not None
            and policy is not None
            and policy.cleanup == "immediate"
            and not provider
        ):
            await self.cleanup(released, artifacts=None, verified=custody)
            refreshed = await self._ledger.get(released.request_scope, released.lease_id)
            return refreshed or released
        return released

    # --- cleanup ----------------------------------------------------------------------------

    async def cleanup_holder(
        self,
        *,
        request_scope: str,
        lane_profile: str,
        harness_execution_id: UUID,
        generation: int,
        artifacts: SnapshotArtifacts,
    ) -> CleanupOutcome:
        """Clean up the lease one holder generation released (the operation workflow's
        `lane.cleanup`); a holder that leased nothing has nothing to clean up."""

        lease_id, _key = lease_identity(lane_profile, harness_execution_id, generation)
        stored = await self._ledger.get(request_scope, lease_id)
        if stored is None:
            return "not_required"
        return await self.cleanup(stored, artifacts=artifacts)

    async def cleanup(
        self,
        lease: WorkspaceLease,
        *,
        artifacts: SnapshotArtifacts | None,
        verified: CapturedSnapshot | None = None,
    ) -> CleanupOutcome:
        """Remove an owned, released, custody-registered worktree that nobody reuses or still
        works in. A worktree a later holder of the slot took over in place is that holder's:
        this lease has nothing left to clean up (`not_required`)."""

        stored = await self._ledger.get(lease.request_scope, lease.lease_id)
        if stored is None:
            raise LookupError(f"workspace lease {lease.lease_id} is not recorded")
        if stored.allocator_ref != self._allocator_ref:
            raise WorkspaceError(
                WORKSPACE_NOT_OWNED, f"lease {stored.lease_key} belongs to {stored.allocator_ref}"
            )
        if not stored.released:
            raise StaleWorkspaceLease(stored.lease_key, "an active lease is not cleaned up")
        if stored.cleanup_status == "not_required":
            return "not_required"
        if stored.cleanup_status == "completed":
            return "already_removed"
        if stored.policy is not None and stored.policy.cleanup == "retain":
            return "retained"
        if stored.observed_state == "lost":
            raise WorkspaceError(
                WORKSPACE_NOT_OWNED, "a fenced-out lease's worktree belongs to its successor"
            )
        if stored.active_participants:
            raise WorkspaceError(
                WORKSPACE_SHARED_ACTIVE,
                f"shared_checkout helpers {', '.join(stored.active_participants)} still work "
                "in it; it is retained",
            )
        if stored.slot is not None and _successor_in_place(
            stored, await self._ledger.slot_leases(stored.request_scope, stored.slot)
        ):
            await self._ledger.mark_cleanup(
                stored.request_scope, stored.lease_id, status="not_required"
            )
            return "not_required"
        custody_ref = stored.workspace_snapshot_ref
        if stored.workspace_snapshot is None or custody_ref is None:
            raise WorkspaceError(
                WORKSPACE_CUSTODY_MISSING,
                "no snapshot was registered for this lease; its work is preserved",
            )
        await asyncio.to_thread(contained, self._root, Path(stored.path))
        if verified is not None and verified.snapshot_ref == custody_ref:
            manifest = verified.manifest
        else:
            manifest_ref = manifest_ref_of(custody_ref)
            if artifacts is None or manifest_ref is None:
                raise WorkspaceError(
                    WORKSPACE_CUSTODY_MISSING, "the registered snapshot cannot be read back"
                )
            manifest = await load_manifest(stored.workspace_snapshot, manifest_ref, artifacts)
        if manifest is None:
            raise WorkspaceError(WORKSPACE_CUSTODY_MISSING, "the snapshot carries no manifest")
        if await asyncio.to_thread(Path(stored.path).exists) and not await self._backend.matches(
            stored, manifest
        ):
            raise WorkspaceError(
                WORKSPACE_CUSTODY_STALE,
                "the worktree changed after its snapshot was registered; it is not removed",
            )
        await self._backend.remove(stored)
        await self._ledger.mark_cleanup(stored.request_scope, stored.lease_id, status="completed")
        return "removed"


def _local_path(repository: str | None) -> Path | None:
    if repository is None or "://" in repository or repository.startswith("git@"):
        return None
    return Path(repository)


def _newest_holder(slot_leases: tuple[WorkspaceLease, ...]) -> WorkspaceLease | None:
    """The slot's newest lease that held work (a refused materialization or continuation,
    released `not_required` without a snapshot, never did)."""

    for lease in reversed(slot_leases):
        if lease.cleanup_status != "not_required" or lease.workspace_snapshot is not None:
            return lease
    return None


def _successor_in_place(lease: WorkspaceLease, slot_leases: tuple[WorkspaceLease, ...]) -> bool:
    """Whether a later holder of the slot took `lease`'s worktree over in place."""

    newest = _newest_holder(slot_leases)
    return newest is not None and newest.lease_id != lease.lease_id and newest.path == lease.path


def _holds_work(newest: WorkspaceLease) -> bool:
    """Whether the slot's newest holder released work that was never cleaned up."""

    return newest.released and newest.cleanup_status not in {"completed", "not_required"}


def _in_place(root: Path, newest: WorkspaceLease | None) -> WorkspaceLease | None:
    """The slot's newest holder when its worktree still exists under `root` for reuse."""

    if newest is None or newest.cleanup_status in {"completed", "not_required"}:
        return None
    return newest if inside(root, Path(newest.path)) else None


def _custody(newest: WorkspaceLease | None) -> WorkspaceLease | None:
    """The slot's newest holder when it registered a local custody snapshot to continue
    from (never an older one: that would silently drop the newer holder's work)."""

    if newest is None or newest.workspace_snapshot is None:
        return None
    ref = newest.workspace_snapshot_ref
    return newest if ref is not None and manifest_ref_of(ref) is not None else None


__all__ = [
    "AllocationRequest",
    "CleanupOutcome",
    "SharedWorkspaceGrant",
    "WorkspaceAllocator",
]
