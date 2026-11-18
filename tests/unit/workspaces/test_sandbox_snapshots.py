from __future__ import annotations

from datetime import timedelta

import pytest

from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.execution.errors import (
    SnapshotAuthorityError,
    SnapshotCompatibilityError,
    SnapshotMigrationRequired,
    SnapshotPayloadMismatch,
)
from tests.support.unit.workspaces.sandbox_snapshots import (
    ARCHIVE,
    NOW,
    clone_request,
    create_request,
    service,
)


async def test_snapshot_is_content_addressed_immutable_and_idempotent() -> None:
    snapshots, repository, payloads, sandbox, authority = service()

    first = await snapshots.create(create_request())
    replayed = await snapshots.create(create_request())

    assert first == replayed
    assert sandbox.captures == 1
    assert authority.creation_checks == 1
    assert first.payload.object_ref.endswith(first.payload.content_digest.removeprefix("sha256:"))
    assert await repository.get_snapshot("snapshot-1") == first
    assert "OPENAI_API_KEY" not in first.model_dump_json()
    assert payloads.payloads[first.payload.object_ref] == ARCHIVE


async def test_restore_twice_creates_distinct_clone_lineage_without_live_resources() -> None:
    snapshots, repository, _payloads, sandbox, _authority = service()
    source = await snapshots.create(create_request())

    first = await snapshots.clone_restore(clone_request("workspace-clone-1", "clone-1"))
    second = await snapshots.clone_restore(clone_request("workspace-clone-2", "clone-2"))
    replayed = await snapshots.clone_restore(clone_request("workspace-clone-1", "clone-1"))

    assert replayed == first
    assert first.workspace.workspace_id != second.workspace.workspace_id
    assert first.parent_snapshot_id == second.parent_snapshot_id == source.snapshot_id
    assert first.parent_workspace_id == second.parent_workspace_id == "workspace-source"
    assert first.live_resources_restored == second.live_resources_restored == ()
    assert first.artifact_promotion_required is True
    assert first.resources.secret_names == ("OPENAI_API_KEY",)
    assert sandbox.clones == ["workspace-clone-1", "workspace-clone-2"]
    assert await repository.get_snapshot(source.snapshot_id) == source
    assert (await repository.get_clone("clone-1")).target_workspace_id == "workspace-clone-1"  # type: ignore[union-attr]


async def test_restore_rejects_tampered_payload_before_provider_clone() -> None:
    snapshots, _repository, payloads, sandbox, _authority = service()
    snapshot = await snapshots.create(create_request())
    payloads.payloads[snapshot.payload.object_ref] = b"tampered"

    with pytest.raises(SnapshotPayloadMismatch):
        await snapshots.clone_restore(clone_request("workspace-clone-1", "clone-1"))

    assert sandbox.clones == []


async def test_restore_rejects_incompatible_runtime_as_new_migration_operation() -> None:
    snapshots, _repository, _payloads, sandbox, _authority = service()
    await snapshots.create(create_request())
    request = clone_request("workspace-clone-1", "clone-1").model_copy(
        update={"runtime_digest": sha256_digest("different-runtime")}
    )

    with pytest.raises(SnapshotMigrationRequired, match="new semantic operation"):
        await snapshots.clone_restore(request)

    assert sandbox.clones == []


async def test_restore_revalidates_present_authority_before_payload_or_clone() -> None:
    snapshots, _repository, _payloads, sandbox, authority = service()
    await snapshots.create(create_request())
    authority.revoked = True

    with pytest.raises(SnapshotAuthorityError):
        await snapshots.clone_restore(clone_request("workspace-clone-1", "clone-1"))

    assert authority.restore_checks == 1
    assert sandbox.clones == []


async def test_restore_uses_trusted_time_and_rejects_cross_scope() -> None:
    snapshots, _repository, _payloads, sandbox, _authority = service()
    await snapshots.create(create_request())
    expired = clone_request("workspace-clone-1", "clone-1").model_copy(
        update={"requested_at": NOW - timedelta(days=365)}
    )
    snapshots._clock = lambda: NOW + timedelta(days=31)

    with pytest.raises(SnapshotCompatibilityError, match="retention has expired"):
        await snapshots.clone_restore(expired)

    cross_scope = clone_request("workspace-clone-2", "clone-2").model_copy(
        update={"request_scope": "tenant:other"}
    )
    snapshots._clock = lambda: NOW + timedelta(hours=1)
    with pytest.raises(SnapshotCompatibilityError, match="scope"):
        await snapshots.clone_restore(cross_scope)
    assert sandbox.clones == []
