"""Builders, constants and fakes that other test files import.

Moved from tests/integration/postgres/test_artifact_promotion_postgres_integration.py.
"""

from __future__ import annotations

from mission_control.application.artifacts.artifact_promotion import artifact_durable_reference
from mission_control.domain.execution.contracts import (
    ArtifactMetadataRevision,
    ArtifactPromotionState,
)
from tests.fixtures.mission_control_common_db import canonical_scope
from tests.support.unit.workspaces.artifact_promotion import CONTENT_DIGEST, NOW, OWNER


def admitted_revision(run_id: str, request_scope: str | None = None) -> ArtifactMetadataRevision:
    scope = request_scope or canonical_scope("tenant-1")
    return ArtifactMetadataRevision(
        promotion_id="promotion:postgres-artifact",
        artifact_id="artifact:postgres-integration",
        intent_key="intent:postgres-integration",
        promotion_identity="sha256:" + "a" * 64,
        revision=4,
        state=ArtifactPromotionState.ADMITTED,
        request_scope=scope,
        run_id=run_id,
        semantic_attempt_key=f"{run_id}:operation:research:attempt:1",
        producer_binding_id="binding:postgres-integration",
        namespace_id=f"workspace-namespace:{run_id}",
        workspace_id=f"workspace:{run_id}",
        output_slot="report",
        logical_path="/workspace/output/report.md",
        owner=OWNER,
        candidate_id="candidate:postgres-integration",
        content_digest=CONTENT_DIGEST,
        media_type="text/markdown",
        size_bytes=57,
        permission_ref="permission:integration@1",
        permission_outcome="allowed",
        output_contract_ref="operation:generic-research@1",
        object_ref="s3://test-artifacts/sha256/content",
        manifest_revision=3,
        durable_reference=artifact_durable_reference(
            scope, run_id, "artifact:postgres-integration"
        ),
        recorded_at=NOW,
    )
