"""Builders, constants and fakes that other test files import.

Moved from tests/unit/schema/test_graph_query_intents.py.
"""

from __future__ import annotations

from datetime import UTC, datetime

from biotech_mission_adapters.domain.schema_context.contracts import QueryExecutionIntent
from biotech_mission_adapters.domain.schema_context.expansion import expand_selection
from biotech_mission_adapters.domain.schema_context.projection import build_operation_projection
from tests.schema_context_helpers import accepted, catalog


def _projection():  # type: ignore[no-untyped-def]
    value = catalog()
    admitted = accepted(value)
    expanded = expand_selection(admitted, value)
    return build_operation_projection(
        admitted,
        expanded,
        live_indexes=({"name": "OrganizationName", "state": "ONLINE"},),
    )


def _intent(**updates):  # type: ignore[no-untyped-def]
    projection = _projection()
    values = {
        "intent_id": "intent-1",
        "sequence": 1,
        "purpose": "pre_ingestion_graph_reconciliation",
        "query_kind": "exact_identity",
        "projection_id": projection.projection_id,
        "projection_digest": projection.projection_digest,
        "schema_definition_digest": projection.source_schema_digest,
        "selection_digest": projection.accepted_selection_digest,
        "goal": "Find organization",
        "coverage_obligation_ids": ("organization_identity",),
        "labels": ("Organization",),
        "relationship_types": (),
        "parameters": {"field": "name", "value": "TruDiagnostic"},
        "requested_fields": ("id", "name"),
        "limit": 5,
        "max_depth": 0,
        "stopping_evidence": "Exact identity result",
        "semantic_query_text": None,
        "proposed_cypher": None,
        "created_at": datetime.now(UTC),
    }
    values.update(updates)
    return QueryExecutionIntent(**values), projection
