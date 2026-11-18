from __future__ import annotations

import asyncio
import json

import pytest
from tests.schema_context_helpers import SDL, accepted, catalog
from tests.support.biotech.schema_grounding_services import NOW, _reconciliation_fixture

from biotech_mission_adapters.application.schema.schema_catalog import CATALOG_GENERATOR_VERSION
from biotech_mission_adapters.application.schema.schema_catalog_build import (
    SchemaCatalogBuildService,
)
from biotech_mission_adapters.application.schema.schema_context_derivation import (
    SchemaContextDerivationService,
)
from biotech_mission_adapters.application.schema.schema_grounding_repository import (
    InMemorySchemaGroundingRecordRepository,
)
from biotech_mission_adapters.application.schema.schema_workspace_binding import (
    SchemaGraphAdmissionService,
)
from biotech_mission_adapters.application.schema.supporting_graph_reconciliation import (
    SupportingGraphReconciliationWorkflow,
)
from biotech_mission_adapters.domain.schema_context.canonicalization import sha256_digest
from biotech_mission_adapters.domain.schema_grounding.contracts import (
    SchemaCatalogBuildRequest,
)
from biotech_mission_adapters.domain.schema_grounding.errors import SchemaSourceDigestMismatch
from mission_control.adapters.storage.control_plane_payloads import InMemoryPayloadStore

EMPTY_OVERLAY = json.dumps(
    {"overlay_version": "1", "modules": [], "elements": {}},
    sort_keys=True,
).encode()


def _build_request(
    *,
    build_id: str = "catalog-build-1",
    source_ref: str = "s3://schemas/example/schema.graphql?versionId=1",
    source_digest: str | None = None,
) -> SchemaCatalogBuildRequest:
    return SchemaCatalogBuildRequest(
        build_id=build_id,
        idempotency_key=f"idempotency:{build_id}",
        request_scope="tenant-1",
        schema_definition_ref=source_ref,
        schema_definition_digest=source_digest or sha256_digest(SDL),
        schema_definition_media_type="application/graphql",
        semantic_overlay_ref="schema-overlay:empty:v1",
        semantic_overlay_revision="1",
        semantic_overlay_digest=sha256_digest(EMPTY_OVERLAY),
        candidate_seed_ref="artifact:report-seed:v1",
        candidate_seed_digest=sha256_digest(b"Organization offers Product"),
        catalog_schema_version="1",
        generator_version=CATALOG_GENERATOR_VERSION,
        normalization_policy_version="graphql-sdl-normalization-v1",
        publication_target="object-storage:schema-catalogs",
        actor_id="schema-publisher",
        authority_ref="authority:schema-catalog-publisher",
        requested_at=NOW,
    )


@pytest.mark.asyncio
async def test_catalog_build_is_content_addressed_idempotent_and_concurrency_safe() -> None:
    records = InMemorySchemaGroundingRecordRepository()
    payloads = InMemoryPayloadStore()
    service = SchemaCatalogBuildService(records, payloads)
    request = _build_request()

    first, second = await asyncio.gather(
        service.build(
            request,
            schema_definition=SDL,
            semantic_overlay=EMPTY_OVERLAY,
            report_seed=b"Organization offers Product",
        ),
        service.build(
            request,
            schema_definition=SDL,
            semantic_overlay=EMPTY_OVERLAY,
            report_seed=b"Organization offers Product",
        ),
    )
    replay = await service.build(
        request,
        schema_definition=SDL,
        semantic_overlay=EMPTY_OVERLAY,
        report_seed=b"Organization offers Product",
    )

    assert first == second == replay
    assert first.status == "published"
    assert first.bundle is not None
    assert first.bundle.digest.startswith("sha256:")
    assert first.resource_count == len(first.resources)
    assert first.tier0_size_bytes < 50 * 1024
    assert {"selection-tier0", "selection-candidates"} <= set(first.profiles)


@pytest.mark.asyncio
async def test_catalog_replay_authenticates_supplied_bytes_before_returning_record() -> None:
    service = SchemaCatalogBuildService(
        InMemorySchemaGroundingRecordRepository(),
        InMemoryPayloadStore(),
    )
    request = _build_request()
    await service.build(
        request,
        schema_definition=SDL,
        semantic_overlay=EMPTY_OVERLAY,
        report_seed=b"Organization offers Product",
    )

    with pytest.raises(SchemaSourceDigestMismatch):
        await service.build(
            request,
            schema_definition=b"type Substituted { id: ID! }",
            semantic_overlay=EMPTY_OVERLAY,
            report_seed=b"Organization offers Product",
        )


@pytest.mark.asyncio
async def test_catalog_physical_and_logical_digests_ignore_source_location() -> None:
    records = InMemorySchemaGroundingRecordRepository()
    service = SchemaCatalogBuildService(records, InMemoryPayloadStore())

    first = await service.build(
        _build_request(
            build_id="catalog-build-a",
            source_ref="s3://one/schema.graphql",
        ).model_copy(update={"candidate_seed_ref": None, "candidate_seed_digest": None}),
        schema_definition=SDL,
        semantic_overlay=EMPTY_OVERLAY,
    )
    second = await service.build(
        _build_request(
            build_id="catalog-build-b",
            source_ref="s3://two/schema.graphql",
        ).model_copy(update={"candidate_seed_ref": None, "candidate_seed_digest": None}),
        schema_definition=SDL,
        semantic_overlay=EMPTY_OVERLAY,
    )

    assert first.physical_schema_digest == second.physical_schema_digest
    assert first.catalog_digest == second.catalog_digest


@pytest.mark.asyncio
async def test_catalog_digest_mismatch_fails_before_publication_and_persists_rejection() -> None:
    records = InMemorySchemaGroundingRecordRepository()
    service = SchemaCatalogBuildService(records, InMemoryPayloadStore())
    request = _build_request(source_digest="sha256:" + "f" * 64).model_copy(
        update={"candidate_seed_ref": None, "candidate_seed_digest": None}
    )

    with pytest.raises(SchemaSourceDigestMismatch):
        await service.build(
            request,
            schema_definition=SDL,
            semantic_overlay=EMPTY_OVERLAY,
        )

    rejected = await service.get("tenant-1", request.build_id)
    assert rejected.status == "rejected"
    assert rejected.bundle is None
    assert rejected.diagnostics == ("SchemaSourceDigestMismatch",)


@pytest.mark.asyncio
async def test_derivation_persists_closure_and_purpose_bound_projection() -> None:
    value = catalog()
    records = InMemorySchemaGroundingRecordRepository()
    service = SchemaContextDerivationService(records)
    result = await service.derive(
        request_scope="tenant-1",
        run_id="run-1",
        accepted=accepted(value),
        catalog=value,
        derived_at=NOW,
    )

    assert result.expanded_slice.accepted_selection_digest == result.accepted_selection_digest
    assert result.projection.purpose == "read_query_reconciliation"
    assert set(result.projection.allowed_node_labels) == {"Organization", "Product"}
    persisted = await records.list_for_run("tenant-1", "run-1")
    assert {item.record_type for item in persisted} == {
        "expanded_slice",
        "operation_projection",
    }

    with pytest.raises(ValueError, match="cannot be reused"):
        await service.derive(
            request_scope="tenant-1",
            run_id="run-2",
            accepted=accepted(value),
            catalog=value,
            purpose="graph_mutation",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("deployment", "capability", "failure_code"),
    [
        (False, True, "deployment_manifest_missing"),
        (True, False, "graph_capability_denied"),
    ],
)
async def test_graph_gate_denial_prevents_executor_creation(
    deployment: bool,
    capability: bool,
    failure_code: str,
) -> None:
    request, records, factory = await _reconciliation_fixture(
        deployment=deployment,
        capability=capability,
    )
    workflow = SupportingGraphReconciliationWorkflow(
        admission=SchemaGraphAdmissionService(records),
        executor_factory=factory,
        records=records,
    )

    result = await workflow.run(request, completed_at=NOW)

    assert result.status == "rejected"
    assert result.admission_decision.failure_code == failure_code
    assert factory.calls == 0


@pytest.mark.asyncio
async def test_graph_gate_rejects_resource_manifest_substitution() -> None:
    request, records, factory = await _reconciliation_fixture()
    request = request.model_copy(
        update={
            "admission": request.admission.model_copy(
                update={"resource_manifest_digest": "sha256:" + "e" * 64}
            )
        }
    )
    workflow = SupportingGraphReconciliationWorkflow(
        admission=SchemaGraphAdmissionService(records),
        executor_factory=factory,
        records=records,
    )

    result = await workflow.run(request)

    assert result.status == "rejected"
    assert result.admission_decision.failure_code == "workspace_profile_invalid"
    assert factory.calls == 0


@pytest.mark.asyncio
async def test_supporting_reconciliation_persists_exact_intent_result_evidence() -> None:
    request, records, factory = await _reconciliation_fixture()
    workflow = SupportingGraphReconciliationWorkflow(
        admission=SchemaGraphAdmissionService(records),
        executor_factory=factory,
        records=records,
    )

    result = await workflow.run(request, completed_at=NOW)
    replay = await workflow.run(request)

    assert result.status == "completed"
    assert replay == result
    assert result.successful_count == 1
    assert result.intent_result_references == result.evidence.intent_result_references
    assert factory.calls == 1
    assert factory.executor.calls == 1
    assert factory.executor.closed
    record_types = {
        record.record_type
        for record in await records.list_for_run("tenant-1", "run-reconciliation")
    }
    assert {
        "compatibility_decision",
        "workspace_binding",
        "query_intent",
        "query_result",
        "reconciliation",
        "evaluation",
    } <= record_types
