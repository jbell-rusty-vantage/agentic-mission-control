from __future__ import annotations

from hashlib import sha256

import pytest

from mission_control.adapters.storage.filesystem_workspace import (
    FilesystemWorkspaceProvisioner,
    is_read_only,
)
from mission_control.application.artifacts.workspace_materialization import (
    InMemoryDurableWorkspaceInputs,
    InMemoryWorkspaceManifestRepository,
    WorkspaceMaterializationService,
)
from mission_control.domain.execution.contracts import (
    WorkspaceOwnerKind,
)
from mission_control.domain.execution.errors import (
    UndeclaredWorkspacePath,
    WorkspaceDigestMismatch,
    WorkspaceSlotConflict,
)
from mission_control.domain.execution.materialization import (
    verify_workspace_manifest,
)
from tests.support.unit.workspaces.workspace_materialization import (
    INPUT,
    RecordingProvisioner,
    owner,
    request,
)


def service(
    repository: InMemoryWorkspaceManifestRepository | None = None,
    *,
    values: dict[str, bytes] | None = None,
) -> tuple[WorkspaceMaterializationService, RecordingProvisioner]:
    provisioner = RecordingProvisioner()
    return (
        WorkspaceMaterializationService(
            manifests=repository or InMemoryWorkspaceManifestRepository(),
            provisioner=provisioner,
            durable_inputs=InMemoryDurableWorkspaceInputs(
                values if values is not None else {"artifact:input-1": INPUT}
            ),
        ),
        provisioner,
    )


async def test_materializes_exact_slots_and_records_immutable_lineage() -> None:
    materializer, provisioner = service()

    workspace = await materializer.materialize(request())
    replayed = await materializer.materialize(request())
    manifest = await materializer.current_manifest("run-workspace:run-1", "workspace-1")

    assert workspace == replayed
    assert workspace.manifest_revision == 1
    assert provisioner.inputs == {"/workspace/input/source.md": INPUT}
    assert tuple(entry.kind for entry in manifest.entries) == ("durable_input",)
    assert manifest.slots[1].owner.kind == WorkspaceOwnerKind.STAGE


async def test_parallel_workspaces_cannot_claim_the_same_writable_slot() -> None:
    repository = InMemoryWorkspaceManifestRepository()
    first, _ = service(repository)
    second, _ = service(repository)
    await first.materialize(request())

    with pytest.raises(WorkspaceSlotConflict):
        await second.materialize(
            request(workspace_id="workspace-2", write_owner=owner("agent:other"))
        )
    nested = request(
        workspace_id="workspace-3",
        write_owner=owner("agent:nested"),
    )
    nested = nested.model_copy(
        update={
            "slots": (
                nested.slots[0],
                nested.slots[1].model_copy(update={"logical_path": "/workspace/output/child"}),
            )
        }
    )
    with pytest.raises(WorkspaceSlotConflict):
        await second.materialize(nested)


async def test_delegate_requires_parent_and_receives_private_owner() -> None:
    with pytest.raises(ValueError, match="explicit parent"):
        owner("delegate:one", WorkspaceOwnerKind.DELEGATE)

    delegate = owner(
        "delegate:one",
        WorkspaceOwnerKind.DELEGATE,
        parent_owner_id="agent:parent",
    )
    materializer, _ = service()
    await materializer.materialize(request(write_owner=delegate))
    manifest = await materializer.current_manifest("run-workspace:run-1", "workspace-1")
    assert manifest.slots[1].owner == delegate


async def test_digest_mismatch_and_undeclared_candidate_fail_closed() -> None:
    materializer, _ = service(values={"artifact:input-1": b"tampered"})
    with pytest.raises(WorkspaceDigestMismatch):
        await materializer.materialize(request())

    valid, _ = service()
    await valid.materialize(request())
    with pytest.raises(UndeclaredWorkspacePath):
        await valid.register_candidate(
            namespace_id="run-workspace:run-1",
            workspace_id="workspace-1",
            slot_name="other",
            logical_path="/workspace/output/other.md",
            owner=owner(),
            candidate_id="candidate-1",
            content=b"report",
            content_digest=f"sha256:{sha256(b'report').hexdigest()}",
            media_type="text/markdown",
        )


async def test_candidate_registration_is_digest_verified_and_retry_safe() -> None:
    materializer, _ = service()
    await materializer.materialize(request())
    content = b"# Research report\n"
    digest = f"sha256:{sha256(content).hexdigest()}"

    manifest = await materializer.register_candidate(
        namespace_id="run-workspace:run-1",
        workspace_id="workspace-1",
        slot_name="output",
        logical_path="/workspace/output/report.md",
        owner=owner(),
        candidate_id="candidate-1",
        content=content,
        content_digest=digest,
        media_type="text/markdown",
    )
    replayed = await materializer.register_candidate(
        namespace_id="run-workspace:run-1",
        workspace_id="workspace-1",
        slot_name="output",
        logical_path="/workspace/output/report.md",
        owner=owner(),
        candidate_id="candidate-1",
        content=content,
        content_digest=digest,
        media_type="text/markdown",
    )
    rematerialized = await materializer.materialize(request())

    assert manifest == replayed
    assert manifest.revision == 2
    assert manifest.entries[-1].kind == "local_candidate"
    assert rematerialized.manifest_revision == 2
    with pytest.raises(WorkspaceDigestMismatch):
        verify_workspace_manifest(
            manifest.model_copy(update={"manifest_digest": "sha256:" + "0" * 64})
        )


async def test_real_filesystem_mounts_inputs_read_only_and_hides_host_identity(
    tmp_path,
) -> None:
    provisioner = FilesystemWorkspaceProvisioner(tmp_path)
    materializer = WorkspaceMaterializationService(
        manifests=InMemoryWorkspaceManifestRepository(),
        provisioner=provisioner,
        durable_inputs=InMemoryDurableWorkspaceInputs({"artifact:input-1": INPUT}),
    )
    workspace = await materializer.materialize(request())
    manifest = await materializer.current_manifest("run-workspace:run-1", "workspace-1")
    mounted = provisioner.governed_host_path(manifest, "/workspace/input/source.md")
    output = provisioner.write_candidate(manifest, "/workspace/output/report.md", b"first draft")

    assert mounted.read_bytes() == INPUT
    assert is_read_only(mounted)
    assert output.read_bytes() == b"first draft"
    assert str(tmp_path) not in workspace.model_dump_json()
    assert str(tmp_path) not in manifest.model_dump_json()
    with pytest.raises(UndeclaredWorkspacePath):
        provisioner.governed_host_path(manifest, "/workspace/unmapped.txt")
