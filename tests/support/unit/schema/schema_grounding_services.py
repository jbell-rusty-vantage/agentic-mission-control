"""Builders, constants and fakes that other test files import.

Moved from integrations/biotech/tests/schema/test_schema_grounding_services.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from biotech_mission_adapters.application.schema.schema_context_derivation import (
    SchemaContextDerivationService,
)
from biotech_mission_adapters.application.schema.schema_grounding_repository import (
    InMemorySchemaGroundingRecordRepository,
)
from biotech_mission_adapters.domain.schema_context.canonicalization import sha256_digest
from biotech_mission_adapters.domain.schema_context.contracts import (
    QueryExecutionIntent,
    QueryExecutionResult,
)
from biotech_mission_adapters.domain.schema_grounding.contracts import (
    GraphAdmissionRequest,
    GraphCapabilityGrant,
    SchemaDeploymentManifestRef,
    SchemaWorkspaceBindingRef,
    SupportingGraphReconciliationRequest,
)
from tests.schema_context_helpers import accepted, catalog

NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)


class _Executor:
    def __init__(self) -> None:
        self.calls = 0
        self.closed = False

    async def execute(self, intent: QueryExecutionIntent, _projection: Any) -> QueryExecutionResult:
        self.calls += 1
        logical: dict[str, Any] = {
            "result_id": f"result-{intent.intent_id}",
            "intent_id": intent.intent_id,
            "intent_digest": sha256_digest(intent.model_dump(mode="json")),
            "query_kind": intent.query_kind,
            "status": "succeeded",
            "compiled_cypher": "MATCH (n:Organization {name: $value}) RETURN n LIMIT $limit",
            "redacted_parameters": {"limit": intent.limit},
            "columns": ("entity",),
            "records": ({"entity": {"id": "org-1", "name": "TruDiagnostic"}},),
            "record_count": 1,
            "truncated": False,
            "elapsed_ms": 1,
            "database": "neo4j",
            "server_info": {"agent": "test"},
            "diagnostics": (),
            "error_type": None,
            "started_at": NOW,
            "finished_at": NOW,
        }
        return QueryExecutionResult(
            **logical,
            result_digest=sha256_digest(
                {**logical, "started_at": NOW.isoformat(), "finished_at": NOW.isoformat()}
            ),
        )

    async def close(self) -> None:
        self.closed = True


class _ExecutorFactory:
    def __init__(self) -> None:
        self.calls = 0
        self.executor = _Executor()

    async def create(
        self,
        _admission: GraphAdmissionRequest,
        _decision: Any,
    ) -> _Executor:
        self.calls += 1
        return self.executor


async def _reconciliation_fixture(
    *,
    deployment: bool = True,
    capability: bool = True,
) -> tuple[
    SupportingGraphReconciliationRequest,
    InMemorySchemaGroundingRecordRepository,
    _ExecutorFactory,
]:
    value = catalog()
    records = InMemorySchemaGroundingRecordRepository()
    derivation = await SchemaContextDerivationService().derive(
        request_scope="tenant-1",
        run_id="run-reconciliation",
        accepted=accepted(value),
        catalog=value,
        derived_at=NOW,
    )
    workspace = SchemaWorkspaceBindingRef(
        binding_id="binding-1",
        binding_digest="sha256:" + "b" * 64,
        request_scope="tenant-1",
        run_id="run-reconciliation",
        workspace_id="workspace-1",
        slot_name="graph_query_runtime",
        catalog_build_id="catalog-build-1",
        catalog_digest=value.catalog_digest,
        resource_manifest_digest="sha256:" + "d" * 64,
        profile="graph-query-runtime",
        purpose="read_query_reconciliation",
        read_only=True,
        issuer_authority_ref="issue-13:schema-workspace-materialization",
        materializer_version="issue-13-materializer-v1",
        created_at=NOW,
    )
    manifest = (
        SchemaDeploymentManifestRef(
            manifest_id="manifest-1",
            manifest_digest="sha256:" + "c" * 64,
            environment="production",
            database="neo4j",
            schema_definition_ref=value.source_ref,
            deployed_sdl_digest=value.source_digest,
            deployment_id="deployment-1",
            issuer_authority_ref="issue-12:graph-schema-deployment",
            active=True,
            revoked=False,
            issued_at=NOW,
        )
        if deployment
        else None
    )
    grant = GraphCapabilityGrant(
        grant_id="grant-1",
        grant_digest="sha256:" + "a" * 64,
        request_scope="tenant-1",
        run_id="run-reconciliation",
        environment="production",
        database="neo4j",
        purpose="read_query_reconciliation",
        admitted=capability,
        query_kinds=frozenset({"exact_identity"}),
        allowed_node_labels=frozenset({"Organization"}),
        allowed_relationship_types=frozenset(),
        maximum_limit=10,
        maximum_traversal_depth=1,
        secret_ref="secret:neo4j-readonly:v1",
        budget_reservation_id="reservation:graph-reads",
        sensitive_data_policy_ref="policy:sensitive-data:v1",
        decided_by_authority_ref="graph-authority:read-capability",
        decided_at=NOW,
    )
    admission = GraphAdmissionRequest(
        request_scope="tenant-1",
        run_id="run-reconciliation",
        purpose="read_query_reconciliation",
        environment="production",
        database="neo4j",
        deployment_id="deployment-1",
        catalog_build_id="catalog-build-1",
        schema_definition_ref=value.source_ref,
        schema_definition_digest=value.source_digest,
        catalog_digest=value.catalog_digest,
        resource_manifest_digest="sha256:" + "d" * 64,
        projection_id=derivation.projection.projection_id,
        projection_digest=derivation.projection.projection_digest,
        deployment_manifest=manifest,
        workspace_binding=workspace,
        graph_capability=grant,
        requested_at=NOW,
    )
    intent = QueryExecutionIntent(
        intent_id="intent-1",
        sequence=1,
        purpose="pre_ingestion_graph_reconciliation",
        query_kind="exact_identity",
        projection_id=derivation.projection.projection_id,
        projection_digest=derivation.projection.projection_digest,
        schema_definition_digest=derivation.projection.source_schema_digest,
        selection_digest=derivation.projection.accepted_selection_digest,
        goal="Locate TruDiagnostic by exact name.",
        coverage_obligation_ids=("organization_identity",),
        labels=("Organization",),
        relationship_types=(),
        parameters={"field": "name", "value": "TruDiagnostic"},
        requested_fields=("id", "name"),
        limit=5,
        max_depth=0,
        stopping_evidence="One exact match or a valid zero result.",
        created_at=NOW,
    )
    factory = _ExecutorFactory()
    return (
        SupportingGraphReconciliationRequest(
            reconciliation_id="reconciliation-1",
            request_scope="tenant-1",
            run_id="run-reconciliation",
            question="Which existing organization matches TruDiagnostic?",
            admission=admission,
            projection=derivation.projection,
            intents=(intent,),
            maximum_intents=5,
            created_at=NOW,
        ),
        records,
        factory,
    )
