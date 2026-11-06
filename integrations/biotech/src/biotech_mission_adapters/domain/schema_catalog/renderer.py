from __future__ import annotations

from biotech_mission_adapters.domain.schema_catalog.models import (
    DerivedCatalog,
    TierZeroCatalog,
    TierZeroNodeMetadata,
)


def render_tier_zero(catalog: DerivedCatalog) -> TierZeroCatalog:
    """Render a deterministic navigation surface without copying fields or SDL bodies."""
    node_metadata: dict[str, TierZeroNodeMetadata] = {}
    for name in sorted(catalog.physical.nodes):
        semantics = catalog.overlay.elements.get(f"node:{name}")
        # Governed summaries belong in discovery; full SDL documentation remains
        # in detail cards. Every physical name and endpoint is retained below.
        if semantics is not None:
            node_metadata[name] = TierZeroNodeMetadata(
                description=semantics.description,
                archetypes=semantics.archetypes,
                modules=semantics.modules,
                aliases=semantics.aliases,
            )
    relationships = {
        name: tuple(
            (
                endpoint.declaring_type,
                endpoint.field_name,
                endpoint.direction,
                endpoint.related_type,
            )
            for endpoint in relationship.endpoints
        )
        for name, relationship in sorted(catalog.physical.relationships.items())
    }
    return TierZeroCatalog(
        catalog_digest=catalog.physical.catalog_digest,
        source_digest=catalog.physical.source_digest,
        node_names=tuple(sorted(catalog.physical.nodes)),
        relationship_property_types=tuple(sorted(catalog.physical.relationship_property_types)),
        node_metadata=node_metadata,
        endpoint_columns=("declaring_type", "field", "direction", "related_type"),
        relationships=relationships,
        module_definitions=catalog.overlay.modules,
    )
