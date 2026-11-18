"""Builders, constants and fakes that other test files import.

Moved from tests/unit/knowledge/test_read_intent.py.
"""

from __future__ import annotations

from typing import Any

from mission_control.contracts.knowledge_protocol import Governors, KnowledgeReadIntentRequest

GOVERNORS = Governors.model_validate(
    {
        "deadline": "2026-10-31T12:00:00Z",
        "maxItems": 64,
        "partialResults": "forbid",
        "budget": {"calls": 0, "tokens": 0, "costUsd": "0"},
    }
)


def request(**updates: Any) -> KnowledgeReadIntentRequest:
    document: dict[str, Any] = {
        "schemaVersion": "knowledge-read-intent-request.v1",
        "purpose": "discovery",
        "operations": [
            {"opId": "head", "kind": "named_query", "query": "knowledge.head", "params": {}},
            {
                "opId": "find",
                "kind": "named_query",
                "query": "entity.resolve",
                "params": {"text": "LangGraph"},
                "limit": 5,
            },
            {"opId": "where", "kind": "schema_search", "query": "entity", "limit": 3},
            {"opId": "page", "kind": "schema_get", "id": "rel:knowledge.entity"},
        ],
    }
    document.update(updates)
    return KnowledgeReadIntentRequest.model_validate(document)
