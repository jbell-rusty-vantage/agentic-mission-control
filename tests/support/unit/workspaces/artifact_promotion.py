"""Builders, constants and fakes that other test files import.

Moved from tests/unit/workspaces/test_artifact_promotion.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256

from mission_control.adapters.storage.artifact_payloads import InMemoryArtifactPayloadStore
from mission_control.application.artifacts.artifact_promotion import (
    ArtifactPromotionService,
    InMemoryArtifactDurableReferences,
    InMemoryArtifactMetadataRepository,
    StaticArtifactValidationAuthority,
)
from mission_control.application.artifacts.workspace_materialization import (
    InMemoryDurableWorkspaceInputs,
    InMemoryWorkspaceManifestRepository,
    WorkspaceMaterializationService,
)
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.execution.contracts import (
    ArtifactCheckEvidence,
    ArtifactPromotionRequest,
    WorkspaceMaterializationRequest,
    WorkspaceOwner,
    WorkspaceOwnerKind,
    WorkspaceSlotBinding,
)
from tests.support.operations import operation_request, service_fixture
from tests.support.unit.workspaces.workspace_materialization import RecordingProvisioner

CONTENT = b"# Generic research\n\nInitial finding.\n\nPatched conclusion.\n"
CONTENT_DIGEST = f"sha256:{sha256(CONTENT).hexdigest()}"
OWNER = WorkspaceOwner(kind=WorkspaceOwnerKind.STAGE, owner_id="stage:generic-research")
NOW = datetime(2026, 7, 20, 19, 0, tzinfo=UTC)


async def promotion_fixture(payloads=None, durable=None, metadata=None):
    operation_service, bindings, *_ = service_fixture()
    base = operation_request()
    contract_digest = sha256_digest("generic-workspace-contract@1")
    slot = WorkspaceSlotBinding(
        slot_name="report",
        logical_path="/workspace/output",
        access="exclusive_write",
        owner=OWNER,
    )
    request = base.model_copy(
        update={
            "capability_grant": base.capability_grant.model_copy(
                update={
                    "capabilities": base.capability_grant.capabilities | {"artifact.promote"},
                    "data_scope_refs": frozenset(
                        {
                            "permission:generic-research@1",
                            "digest:" + CONTENT_DIGEST,
                            "finding:failure",
                        }
                    ),
                }
            ),
            "workspace": base.workspace.model_copy(
                update={
                    "workflow_contract_digest": contract_digest,
                    "slot_bindings": (slot,),
                    "exclusive_write_paths": (slot.logical_path,),
                }
            ),
        }
    )
    result = await operation_service.execute(request)
    assert result.status == "completed"

    workspace_repository = InMemoryWorkspaceManifestRepository()
    workspaces = WorkspaceMaterializationService(
        manifests=workspace_repository,
        provisioner=RecordingProvisioner(),
        durable_inputs=InMemoryDurableWorkspaceInputs(),
    )
    await workspaces.materialize(
        WorkspaceMaterializationRequest(
            namespace_id=request.workspace.namespace_id,
            workspace_id=request.workspace.workspace_id,
            provider=request.workspace.provider,
            template_ref=request.workspace.template_ref,
            workflow_contract_digest=contract_digest,
            slots=(slot,),
            runtime_digest=request.workspace.runtime_digest,
            image_digest=request.workspace.image_digest,
            created_at=NOW,
        )
    )
    await workspaces.register_candidate(
        namespace_id=request.workspace.namespace_id,
        workspace_id=request.workspace.workspace_id,
        slot_name=slot.slot_name,
        logical_path="/workspace/output/report.md",
        owner=OWNER,
        candidate_id="candidate:report",
        content=CONTENT,
        content_digest=CONTENT_DIGEST,
        media_type="text/markdown",
        recorded_at=NOW,
    )
    metadata = metadata or InMemoryArtifactMetadataRepository()
    durable = durable or InMemoryArtifactDurableReferences()
    service = ArtifactPromotionService(
        bindings=bindings,
        metadata=metadata,
        payloads=payloads or InMemoryArtifactPayloadStore(),
        workspaces=workspaces,
        durable_references=durable,
        validation_authority=StaticArtifactValidationAuthority(
            permission_outcomes={
                (
                    "operation:sandbox-agent@1",
                    "permission:generic-research@1",
                ): "allowed"
            },
            check_outcomes={
                (
                    "operation:sandbox-agent@1",
                    "content-integrity",
                    "digest:" + CONTENT_DIGEST,
                ): "passed",
                (
                    "operation:sandbox-agent@1",
                    "declared-policy-check",
                    "finding:failure",
                ): "failed",
            },
            required_check_ids={"operation:sandbox-agent@1": frozenset({"content-integrity"})},
        ),
    )
    promotion = ArtifactPromotionRequest(
        request_scope=request.request_scope,
        binding_id=result.binding_id,
        namespace_id=request.workspace.namespace_id,
        workspace_id=request.workspace.workspace_id,
        output_slot=slot.slot_name,
        logical_path="/workspace/output/report.md",
        owner=OWNER,
        candidate_id="candidate:report",
        content_digest=CONTENT_DIGEST,
        media_type="text/markdown",
        size_bytes=len(CONTENT),
        permission_ref="permission:generic-research@1",
        permission_outcome="allowed",
        output_contract_ref=request.operation_contract_ref,
        checks=(
            ArtifactCheckEvidence(
                check_id="content-integrity",
                outcome="passed",
                evidence_ref="digest:" + CONTENT_DIGEST,
            ),
        ),
        requested_at=NOW,
    )
    return service, metadata, durable, workspaces, promotion
