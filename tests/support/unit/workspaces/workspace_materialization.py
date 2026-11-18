"""Builders, constants and fakes that other test files import.

Moved from tests/unit/workspaces/test_workspace_materialization.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256

from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import DefinitionKind, ExactDefinitionRef
from mission_control.domain.execution.contracts import (
    MaterializedWorkspace,
    WorkspaceMaterializationRequest,
    WorkspaceOwner,
    WorkspaceOwnerKind,
    WorkspaceSlotBinding,
)

INPUT = b"immutable governed input"
INPUT_DIGEST = f"sha256:{sha256(INPUT).hexdigest()}"
RUNTIME_DIGEST = sha256_digest("workspace-runtime")
IMAGE_DIGEST = sha256_digest("workspace-image")
CONTRACT_DIGEST = sha256_digest("workflow-workspace-contract")


class RecordingProvisioner:
    def __init__(self) -> None:
        self.inputs: dict[str, bytes] = {}

    async def provision(self, request, manifest, durable_inputs):
        self.inputs = dict(durable_inputs)
        return MaterializedWorkspace(
            workspace_id=request.workspace_id,
            namespace_id=request.namespace_id,
            provider=request.provider,
            runtime_digest=request.runtime_digest,
            image_digest=request.image_digest,
            mount_manifest_digest=manifest.manifest_digest,
            manifest_revision=manifest.revision,
        )


def owner(
    owner_id: str = "stage:research",
    kind: WorkspaceOwnerKind = WorkspaceOwnerKind.STAGE,
    parent_owner_id: str | None = None,
) -> WorkspaceOwner:
    return WorkspaceOwner(
        kind=kind,
        owner_id=owner_id,
        parent_owner_id=parent_owner_id,
    )


def request(
    *,
    workspace_id: str = "workspace-1",
    write_owner: WorkspaceOwner | None = None,
) -> WorkspaceMaterializationRequest:
    return WorkspaceMaterializationRequest(
        namespace_id="run-workspace:run-1",
        workspace_id=workspace_id,
        provider="conformance-filesystem",
        template_ref=ExactDefinitionRef(
            kind=DefinitionKind.WORKSPACE_TEMPLATE,
            logical_id="generic-workspace",
            revision=1,
            digest=sha256_digest("generic-workspace@1"),
        ),
        workflow_contract_digest=CONTRACT_DIGEST,
        slots=(
            WorkspaceSlotBinding(
                slot_name="input",
                logical_path="/workspace/input/source.md",
                access="read_only",
                owner=owner("run:run-1", WorkspaceOwnerKind.RUN),
                durable_ref="artifact:input-1",
                content_digest=INPUT_DIGEST,
            ),
            WorkspaceSlotBinding(
                slot_name="output",
                logical_path="/workspace/output",
                access="exclusive_write",
                owner=write_owner or owner(),
            ),
        ),
        runtime_digest=RUNTIME_DIGEST,
        image_digest=IMAGE_DIGEST,
        created_at=datetime(2026, 7, 20, 18, 0, tzinfo=UTC),
    )
