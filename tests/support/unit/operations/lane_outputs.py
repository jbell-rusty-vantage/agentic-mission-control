"""Builders, constants and fakes that other test files import.

Moved from tests/unit/operations/test_lane_outputs.py.
"""

from __future__ import annotations

from typing import Any

from mission_control.application.artifacts.workspace_candidates import (
    InMemoryWorkspaceCandidateContents,
    WorkspaceCandidateCaptureService,
)
from mission_control.application.artifacts.workspace_materialization import (
    BindingWorkspaceMaterializer,
    InMemoryDurableWorkspaceInputs,
    InMemoryWorkspaceManifestRepository,
    WorkspaceMaterializationService,
)
from mission_control.application.execution.operations.lane_outputs import (
    WorkspaceCandidateLaneOutputs,
)
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.execution.contracts import (
    MaterializedWorkspace,
    OperationExecutionRequest,
    WorkspaceOwner,
    WorkspaceOwnerKind,
    WorkspaceSlotBinding,
)
from tests.support.operations import operation_request

OWNER = WorkspaceOwner(kind=WorkspaceOwnerKind.STAGE, owner_id="stage:patch")


def compiled(*paths: str) -> OperationExecutionRequest:
    """The base operation with compiled writable slots (what a manifest template carries)."""

    base = operation_request()
    workspace = base.workspace.model_copy(
        update={
            "workflow_contract_digest": sha256_digest("contract"),
            "exclusive_write_paths": paths,
            "slot_bindings": tuple(
                WorkspaceSlotBinding(
                    slot_name=f"slot{index}",
                    logical_path=path,
                    access="exclusive_write",
                    owner=OWNER,
                )
                for index, path in enumerate(paths)
            ),
        }
    )
    return base.model_copy(update={"workspace": workspace})


class _Provisioner:
    async def provision(self, request: Any, manifest: Any, durable_inputs: Any) -> Any:
        return MaterializedWorkspace(
            workspace_id=request.workspace_id,
            namespace_id=request.namespace_id,
            provider=request.provider,
            runtime_digest=request.runtime_digest,
            image_digest=request.image_digest,
            mount_manifest_digest=manifest.manifest_digest,
            manifest_revision=manifest.revision,
        )


def custody() -> tuple[WorkspaceCandidateLaneOutputs, InMemoryWorkspaceCandidateContents]:
    materializer = WorkspaceMaterializationService(
        manifests=InMemoryWorkspaceManifestRepository(),
        provisioner=_Provisioner(),
        durable_inputs=InMemoryDurableWorkspaceInputs(),
    )
    contents = InMemoryWorkspaceCandidateContents()
    port = WorkspaceCandidateLaneOutputs(
        workspaces=BindingWorkspaceMaterializer(materializer),
        candidates=WorkspaceCandidateCaptureService(materializer=materializer, contents=contents),
    )
    return port, contents
