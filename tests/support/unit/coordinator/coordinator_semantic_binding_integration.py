"""Builders, constants and fakes that other test files import.

Moved from tests/unit/coordinator/test_coordinator_semantic_binding_integration.py.
"""

from __future__ import annotations

from biotech_mission_adapters.application.schema.schema_catalog import CATALOG_GENERATOR_VERSION
from biotech_mission_adapters.application.schema.schema_context_stage_handlers import (
    SchemaContextBindingPlanInput,
    SchemaContextSemanticBindingProvider,
)
from biotech_mission_adapters.application.schema.schema_grounding_semantic_handlers import (
    SupportingGraphBindingPlanInput,
    SupportingGraphSemanticBindingProvider,
)
from biotech_mission_adapters.domain.schema_context.contracts import SchemaContextSelectionRequest
from biotech_mission_adapters.domain.schema_grounding.contracts import (
    DurableObjectRef,
    SchemaCatalogBuildRequest,
)
from mission_control.application.execution.operations.operation_execution import (
    InMemoryOperationBindingRepository,
)
from mission_control.application.execution.operations.semantic_operation_bindings import (
    SemanticOperationBindingTemplates,
    SemanticOperationExecutionBindingService,
)
from mission_control.application.programs.goal_directed import (
    InMemoryGoalOperationTemplateRepository,
)
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.execution.contracts import OperationAttemptIdentity
from tests.support.biotech.schema_grounding_services import _reconciliation_fixture
from tests.support.operations import operation_request
from tests.support.unit.coordinator.coordinator_launch_preparation import NOW, SCOPE


def _operation_template(operation_id: str):
    template = operation_request()
    return template.model_copy(
        update={
            "identity": OperationAttemptIdentity(
                run_id="{run_id}",
                operation_id=operation_id,
                operation_attempt=1,
            ),
            "request_scope": SCOPE,
            "workspace": template.workspace.model_copy(
                update={
                    "namespace_id": "workspace-namespace:{run_id}",
                    "workspace_id": f"workspace:{{run_id}}:{operation_id}",
                }
            ),
            "budget_reservation_id": f"reservation:{{run_id}}:{operation_id}",
            "idempotency_key": f"side-effect:{{run_id}}:{operation_id}",
            "prior_binding_id": None,
        }
    )


def _durable(name: str) -> DurableObjectRef:
    content = name.encode()
    digest = sha256_digest(name)
    return DurableObjectRef(
        uri=f"memory://{name}/{digest.removeprefix('sha256:')}",
        digest=digest,
        size_bytes=len(content),
        media_type="application/octet-stream",
        version_id=digest,
    )


def _schema_context_provider(
    operation_repository: InMemoryOperationBindingRepository,
) -> SchemaContextSemanticBindingProvider:
    schema = _durable("schema")
    overlay = _durable("overlay")
    report = _durable("report")
    build = SchemaCatalogBuildRequest(
        build_id="catalog-build-launch",
        idempotency_key="catalog-build-launch",
        request_scope=SCOPE,
        schema_definition_ref=schema.uri,
        schema_definition_digest=schema.digest,
        semantic_overlay_ref=overlay.uri,
        semantic_overlay_revision="1",
        semantic_overlay_digest=overlay.digest,
        catalog_schema_version="1",
        generator_version=CATALOG_GENERATOR_VERSION,
        normalization_policy_version="graphql-sdl-normalization-v1",
        publication_target="memory://catalog",
        actor_id="coordinator-1",
        authority_ref="authority:schema",
        requested_at=NOW,
    )
    selection = SchemaContextSelectionRequest(
        request_id="selection-launch",
        purpose="pre_ingestion_graph_reconciliation",
        intended_operations=("read",),
        schema_definition_ref=schema.uri,
        schema_definition_digest=schema.digest,
        catalog_digest=sha256_digest("catalog"),
        report_ref=report.uri,
        report_digest=report.digest,
        coverage_obligations=("organization_identity",),
        workspace_ref="workspace:{run_id}",
        created_at=NOW,
    )
    templates = SemanticOperationBindingTemplates(
        operations={
            operation_id: _operation_template(operation_id)
            for operation_id in ("semantic_selector", "independent_reviewer")
        }
    )
    return SchemaContextSemanticBindingProvider(
        SchemaContextBindingPlanInput(
            build_request=build,
            selection_request=selection,
            schema_definition=schema,
            semantic_overlay=overlay,
            report=report,
            operation_bindings=templates,
            created_at=NOW,
        ),
        SemanticOperationExecutionBindingService(operation_repository),
    )


async def _supporting_graph_provider(
    operation_repository: InMemoryOperationBindingRepository,
) -> SupportingGraphSemanticBindingProvider:
    request, _records, _factory = await _reconciliation_fixture()
    workspace = request.admission.workspace_binding
    grant = request.admission.graph_capability
    admission = request.admission.model_copy(
        update={
            "request_scope": SCOPE,
            "run_id": "{run_id}",
            "workspace_binding": workspace.model_copy(
                update={"request_scope": SCOPE, "run_id": "{run_id}"}
            )
            if workspace is not None
            else None,
            "graph_capability": grant.model_copy(
                update={"request_scope": SCOPE, "run_id": "{run_id}"}
            )
            if grant is not None
            else None,
        }
    )
    request = request.model_copy(
        update={"request_scope": SCOPE, "run_id": "{run_id}", "admission": admission}
    )
    return SupportingGraphSemanticBindingProvider(
        SupportingGraphBindingPlanInput(
            request=request,
            minimum_successful_intents=1,
            handoff_instructions="Resume only from immutable graph evidence.",
            operation_bindings=SemanticOperationBindingTemplates(
                operations={
                    "goal_executor": _operation_template("goal_executor"),
                    "goal_verifier": _operation_template("goal_verifier"),
                }
            ),
            created_at=NOW,
        ),
        SemanticOperationExecutionBindingService(operation_repository),
        InMemoryGoalOperationTemplateRepository(),
    )
