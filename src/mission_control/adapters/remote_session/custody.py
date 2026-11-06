"""Custody of what a remote session writes (ADR-0052, ADR-0037; MP-04 `provider_workspace`).

A Remote Session Lane's workspace lives at the provider (a Cursor cloud VM, a Managed Agents
or Agents API sandbox). Mission Control never holds its bytes; it holds the fenced record of
the branch the session works on: the lease is allocated with the branch and its base commit,
the branch head read back from the remote is recorded as the snapshot `branch:<branch>@<sha>`
(the ref a fork restores from), and the lease is released only after the patch, the artifacts
and that head are in custody. The same holder re-acquiring its active lease gets it back
unchanged, so a retried prepare or a reattach is idempotent; a slot held by another generation
fences this one out and the turn is lost, never shared.

Providers that hand work back as a `git bundle` rather than a pushed branch verify and push it
first; the recorded head is the same branch fact either way.
"""

from __future__ import annotations

from uuid import UUID

from mission_control.application.execution.harness.lane_turns import LaneExecutionIdentity
from mission_control.application.execution.harness.leases import WorkspaceLease
from mission_control.application.execution.harness.protocol import NativeTurnLost
from mission_control.application.workspaces.errors import WorkspaceError, WorkspaceLeaseHeld
from mission_control.application.workspaces.service import AllocationRequest, WorkspaceAllocator
from mission_control.application.workspaces.snapshots import (
    BRANCH_SNAPSHOT_REF_PREFIX,
    CapturedSnapshot,
)
from mission_control.domain.context.snapshot_evidence import ConversationEvidence
from mission_control.domain.execution.bindings import WorkspacePolicyPin
from mission_control.domain.execution.lanes import LaneProfileName


def parse_branch_snapshot(ref: str) -> tuple[str, str] | None:
    """`(branch, head)` of a `branch:<branch>@<sha>` ref, or None for any other ref."""

    if not ref.startswith(BRANCH_SNAPSHOT_REF_PREFIX):
        return None
    branch, separator, head = ref.removeprefix(BRANCH_SNAPSHOT_REF_PREFIX).rpartition("@")
    return (branch, head) if separator and branch and head else None


class ProviderWorkspaceCustody:
    """The provider workspace lease of one lane profile, when an allocator is composed."""

    def __init__(
        self,
        workspaces: WorkspaceAllocator | None,
        *,
        lane_profile: LaneProfileName,
        policy: WorkspacePolicyPin,
    ) -> None:
        self._workspaces = workspaces
        self._lane_profile = lane_profile
        self._policy = policy

    @property
    def composed(self) -> bool:
        return self._workspaces is not None

    async def allocate(
        self,
        identity: LaneExecutionIdentity,
        *,
        harness_execution_id: str,
        generation: int,
        run_id: str,
        repository: str,
        base_ref: str,
        branch: str,
        base_commit: str,
        attempt_no: int | None = None,
    ) -> WorkspaceLease | None:
        """The fenced record of the session's branch (None when no allocator is composed)."""

        if self._workspaces is None:
            return None
        try:
            return await self._workspaces.allocate_provider_workspace(
                AllocationRequest(
                    request_scope=identity.request_scope,
                    lane_profile=self._lane_profile,
                    harness_execution_id=UUID(harness_execution_id),
                    generation=generation,
                    run_id=run_id,
                    attempt_no=attempt_no or identity.attempt_no,
                    policy=self._policy,
                    repository=repository,
                    base_ref=base_ref,
                ),
                branch=branch,
                base_commit=base_commit,
            )
        except WorkspaceLeaseHeld as error:
            raise NativeTurnLost(f"the run branch workspace is held elsewhere: {error}") from error

    async def record_head(
        self,
        lease: WorkspaceLease | None,
        head_commit: str,
        *,
        conversation: ConversationEvidence | None = None,
    ) -> CapturedSnapshot | None:
        """The branch head read back from the remote, recorded on the lease."""

        if self._workspaces is None or lease is None:
            return None
        try:
            return await self._workspaces.record_provider_snapshot(
                lease, head_commit=head_commit, conversation=conversation
            )
        except WorkspaceError as error:
            raise NativeTurnLost(f"the provider workspace snapshot was refused: {error}") from error

    async def release(
        self, lease: WorkspaceLease | None, custody: CapturedSnapshot | None
    ) -> WorkspaceLease | None:
        """Release after custody; the provider keeps its workspace, nothing is deleted here."""

        if self._workspaces is None or lease is None:
            return lease
        return await self._workspaces.release(lease, custody=custody)


__all__ = ["ProviderWorkspaceCustody", "parse_branch_snapshot"]
