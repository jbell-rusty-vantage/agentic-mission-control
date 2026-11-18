from __future__ import annotations

import pytest

from biotech_mission_adapters.application.schema.graph_query import (
    compile_query_intent,
    validate_query_intent,
)
from biotech_mission_adapters.domain.schema_context.errors import QueryIntentRejected
from tests.support.unit.schema.graph_query_intents import _intent


def test_exact_and_neighborhood_queries_compile_deterministically() -> None:
    intent, projection = _intent()
    validate_query_intent(intent, projection)
    cypher, parameters = compile_query_intent(intent)
    assert "MATCH (n:`Organization`)" in cypher
    assert parameters["value"] == "TruDiagnostic"

    neighborhood, projection = _intent(
        intent_id="intent-2",
        query_kind="bounded_neighborhood",
        relationship_types=("OFFERS",),
        max_depth=1,
    )
    validate_query_intent(neighborhood, projection)
    cypher, _ = compile_query_intent(neighborhood)
    assert "[r:`OFFERS`]" in cypher


@pytest.mark.parametrize(
    "updates",
    [
        {"limit": 101},
        {"max_depth": 2},
        {"labels": ("Unknown",)},
        {"requested_fields": ("unknownProperty",)},
        {"relationship_types": ("UNKNOWN_RELATIONSHIP",)},
        {"parameters": {"field": "name", "value": "x", "password": "secret"}},
        {"parameters": {"field": "name", "value": "x", "neo4j_uri": "secret"}},
        {"proposed_cypher": "CREATE (n)"},
        {"proposed_cypher": "MATCH (n) RETURN n"},
    ],
)
def test_intent_rejects_out_of_projection_or_unsafe_requests(updates) -> None:  # type: ignore[no-untyped-def]
    intent, projection = _intent(**updates)
    with pytest.raises(QueryIntentRejected):
        validate_query_intent(intent, projection)


def test_vector_intent_rejects_raw_embedding() -> None:
    intent, projection = _intent(
        query_kind="vector_search",
        parameters={"index": "ProductEmbedding", "embedding": [0.1, 0.2]},
        semantic_query_text="epigenetic product",
    )
    with pytest.raises(QueryIntentRejected):
        validate_query_intent(intent, projection)


def test_fulltext_intent_rejects_an_unobserved_index() -> None:
    intent, projection = _intent(
        query_kind="fulltext_search",
        parameters={"index": "InventedIndex", "query": "TruDiagnostic"},
    )
    with pytest.raises(QueryIntentRejected, match="not admitted and online"):
        validate_query_intent(intent, projection)
