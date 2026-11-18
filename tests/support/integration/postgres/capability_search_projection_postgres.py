"""Builders, constants and fakes that other test files import.

Moved from tests/integration/postgres/test_capability_search_projection_postgres.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from mission_control.application.capabilities.capability_search_repository import (
    CapabilitySearchDocument,
)
from mission_control.application.capabilities.catalog_projection_generation import (
    ProjectionGenerationSpec,
    projection_source_set_digest,
)
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import (
    CapabilityDefinition,
    DefinitionKind,
    PublishedDefinition,
)
from mission_control.domain.coordinator.contracts import CatalogAssetStatus

NOW = datetime(2026, 10, 3, tzinfo=UTC)
DIMENSIONS = 1536
MECHANICS_MODEL = "test-only:deterministic-mechanics-vector"


def mechanics_vector(axis: int) -> tuple[float, ...]:
    """Deterministic unit basis vector: storage/ranking mechanics only, not an embedding."""
    return tuple(1.0 if index == axis else 0.0 for index in range(DIMENSIONS))


def tool(logical_id: str, description: str) -> CapabilityDefinition:
    return CapabilityDefinition(
        logical_id=logical_id,
        title=logical_id,
        description=description,
        kind="tool",
        capability_kind="tool",
        maturity="qualified",
        attachment_targets=frozenset({"agent.main"}),
    )


def document(
    published: PublishedDefinition, scope: str, generation: str, axis: int
) -> CapabilitySearchDocument:
    text = published.definition.description
    return CapabilitySearchDocument(
        search_document_id=uuid4(),
        tenant_scope=scope,
        asset_kind=published.ref.kind,
        logical_id=published.ref.logical_id,
        revision=published.ref.revision,
        source_digest=published.ref.digest,
        status=CatalogAssetStatus.PUBLISHED,
        title=published.ref.logical_id,
        description=text,
        search_text=text,
        search_text_digest=sha256_digest(text),
        embedding=mechanics_vector(axis),
        embedding_model_id=MECHANICS_MODEL,
        embedding_dimensions=DIMENSIONS,
        search_document_format_version=1,
        mongodb_document_id=f"{published.ref.logical_id}@{published.ref.revision}",
        source_published_at=published.published_at,
        indexed_at=NOW,
        projection_generation=generation,
    )


def spec(
    scope: str, generation: str, published: tuple[PublishedDefinition, ...]
) -> ProjectionGenerationSpec:
    return ProjectionGenerationSpec(
        tenant_scope=scope,
        projection_generation=generation,
        embedding_model_id=MECHANICS_MODEL,
        embedding_dimensions=DIMENSIONS,
        search_document_format_version=1,
        selected_kinds=frozenset({DefinitionKind.TOOL}),
        expected_count=len(published),
        expected_source_set_digest=projection_source_set_digest(
            tuple(item.ref for item in published)
        ),
    )
