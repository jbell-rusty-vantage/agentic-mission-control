"""A lexical scan of published definitions: the answer when the Search Projection is not built.

Capability search ranks over the Search Projection. An installation whose projection was never
built (or not yet rebuilt) returns no hit for any query, although the catalog holds published
definitions. Two readers then fall back to the same plain scan of those definitions, and both
say so (`DEFINITION_SCAN` as the search mode): the Selection Workspace's `mission_search` and
the Mission Manifest compiler's resolution of a `search` capability entry.

The scan is weighted token overlap over a definition's name, title, kind and description, with
a plural folded onto its singular. It ranks, it does not admit: each caller applies its own
admission (retired rows, lane support, namespace) to what the scan returns.

`projection_answers` is the probe that tells an unbuilt projection from a query that matches
nothing: a projection that returns a published definition searched by its own title is built.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Final, Protocol

from mission_control.application.capabilities.capability_search import CapabilitySearchResponse
from mission_control.domain.authoring.contracts import PublishedDefinition
from mission_control.domain.coordinator.contracts import CapabilitySearchRequest

DEFINITION_SCAN: Final = "definition_scan"


class DefinitionSearch(Protocol):
    async def search(self, request: CapabilitySearchRequest) -> CapabilitySearchResponse: ...


def tokens(text: str) -> frozenset[str]:
    return frozenset(re.findall(r"[a-z0-9]+", text.lower()))


def stem(token: str) -> str:
    """A plural folded onto its singular (`skills` finds the kind `skill`); nothing more."""

    return token[:-1] if len(token) > 3 and token.endswith("s") else token


def score_fields(
    query_tokens: frozenset[str],
    fields: Iterable[tuple[str, str, float]],
    *,
    stemmed: bool = False,
) -> tuple[float, list[str]]:
    """Weighted token overlap: each field adds its weight once per query token it contains."""

    score = 0.0
    reasons: list[str] = []
    for label, value, weight in fields:
        words = tokens(value)
        matched = sorted(
            query_tokens & (frozenset(stem(word) for word in words) if stemmed else words)
        )
        if matched:
            score += weight * len(matched)
            reasons.append(f"{label} {value!r} matches {', '.join(matched)}")
    return score, reasons


def scan_definitions(
    rows: Iterable[PublishedDefinition], query: str
) -> list[tuple[float, PublishedDefinition, tuple[str, ...]]]:
    """The rows that share a word with the query, best first (then by name and revision),
    each with its score and why it matched."""

    query_tokens = frozenset(stem(token) for token in tokens(query))
    scored: list[tuple[float, PublishedDefinition, tuple[str, ...]]] = []
    for row in rows:
        score, reasons = score_fields(
            query_tokens,
            [
                ("name", row.ref.logical_id, 3.0),
                ("title", row.definition.title, 3.0),
                ("kind", row.ref.kind.value, 2.0),
                ("description", row.definition.description, 1.0),
            ],
            stemmed=True,
        )
        if score > 0:
            scored.append((score, row, tuple(reasons)))
    scored.sort(key=lambda item: (-item[0], item[1].ref.logical_id, item[1].ref.revision))
    return scored


async def projection_answers(
    search: DefinitionSearch, probe: PublishedDefinition, *, tenant_scope: str
) -> bool:
    """Whether the Search Projection returns a published definition searched by its own title
    (a built projection does; one that was never built returns nothing for any query)."""

    response = await search.search(
        CapabilitySearchRequest(
            query=probe.definition.title,
            kinds=frozenset({probe.ref.kind}),
            tenant_scope=tenant_scope,
            limit=1,
        )
    )
    return bool(response.hits)


__all__ = [
    "DEFINITION_SCAN",
    "DefinitionSearch",
    "projection_answers",
    "scan_definitions",
    "score_fields",
    "stem",
    "tokens",
]
