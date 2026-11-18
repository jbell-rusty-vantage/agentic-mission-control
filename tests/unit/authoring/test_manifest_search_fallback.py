"""A manifest `search` entry resolves where the Search Projection is not built.

The compiler ranks a `search` capability entry over the Search Projection. An installation
whose projection was never built answers no hit for any query, although the catalog holds the
published definitions every `pin` resolves against. The compiler then scans those definitions
itself, as `mission_search` does, and the resolution says which mode answered
(`search_mode`). A projection that is built keeps its own answer, an empty one included.
In memory: the seeded fast-track catalog, the real compile service.
"""

from __future__ import annotations

from typing import Any

import pytest

from mission_control.application.authoring.manifest_service import ManifestCompileService
from mission_control.application.capabilities.capability_search import CapabilitySearchResponse
from mission_control.application.capabilities.definition_scan import (
    DEFINITION_SCAN,
    projection_answers,
    scan_definitions,
)
from mission_control.domain.authoring.contracts import DefinitionKind
from mission_control.domain.coordinator.contracts import CapabilitySearchRequest
from tests.support.manifests.compile import minimal, reasons, scope, service, text
from tests.support.manifests.seeded_catalog import fast_track_catalog


class UnbuiltProjection:
    """A Search Projection that was never built: no hit for any query, its own title included."""

    def __init__(self) -> None:
        self.requests: list[CapabilitySearchRequest] = []

    async def search(self, request: CapabilitySearchRequest) -> CapabilitySearchResponse:
        self.requests.append(request)
        return CapabilitySearchResponse(hits=())

    def max_fused_score(self, mode: Any) -> float:
        return 1.0


async def _unbuilt() -> tuple[ManifestCompileService, UnbuiltProjection]:
    definitions, _search = await fast_track_catalog()
    projection = UnbuiltProjection()
    return ManifestCompileService(definitions=definitions, search=projection), projection  # type: ignore[arg-type]


def _search_entries(compilation: Any) -> list[Any]:
    assert compilation.resolution is not None
    return [item for item in compilation.resolution.resolved if "search" in item.request]


@pytest.mark.asyncio
async def test_an_unbuilt_projection_is_answered_by_a_scan_and_the_resolution_says_so() -> None:
    compile_service, projection = await _unbuilt()

    compilation = await compile_service.compile(text(minimal()), scope())

    (entry,) = _search_entries(compilation)
    assert entry.blocker is None and entry.result is not None
    assert entry.search_mode == DEFINITION_SCAN
    # The scan resolves the entry to the capability its words name, as a pin would.
    assert entry.result.kind == "mcp_server" and "pubmed" in entry.result.capability_id
    assert entry.result.pin in entry.candidates
    assert ("/mission/environment/capabilities/0", "search_no_admitted_hits") not in reasons(
        compilation
    )
    warning = next(item for item in compilation.report.warnings if item.reason == DEFINITION_SCAN)
    assert warning.pointer == "/mission/environment/capabilities/0"
    assert "search index is not built" in warning.message and entry.result.pin in warning.message
    # The projection was asked first, then probed with the scan's top row by its own title.
    assert projection.requests[0].query == "pubmed literature retrieval"
    assert len(projection.requests) == 2 and projection.requests[1].limit == 1
    assert compilation.resolution.model_dump(mode="json")["resolved"][0]["search_mode"] == (
        DEFINITION_SCAN
    )


@pytest.mark.asyncio
async def test_a_built_projection_keeps_its_own_answer_and_names_its_mode() -> None:
    compile_service, _, recording = await service()
    document = minimal()
    document["mission"]["environment"]["capabilities"].append(
        {"search": "quantum widget calibration", "kind": "mcp_server", "as": "widget"}
    )

    compilation = await compile_service.compile(text(document), scope())

    found, missing = _search_entries(compilation)
    # The projection answered: its own mode, and no scan warning.
    assert found.result is not None and found.search_mode == "lexical"
    assert DEFINITION_SCAN not in {item.reason for item in compilation.report.warnings}
    # A query that matches nothing stays a typed blocker, under the projection's mode.
    assert missing.result is None and missing.search_mode == "lexical"
    assert missing.blocker is not None and missing.blocker.reason == "search_no_admitted_hits"
    assert recording.requests


@pytest.mark.asyncio
async def test_a_scan_admits_only_what_a_pin_could_name() -> None:
    compile_service, _projection = await _unbuilt()
    document = minimal()
    # No published definition shares a word with the query: the entry stays blocked.
    document["mission"]["environment"]["capabilities"].append(
        {"search": "quantum widget calibration", "kind": "mcp_server", "as": "widget"}
    )
    # The MCP server exists, but not on the lane the entry requires.
    document["mission"]["environment"]["capabilities"].append(
        {
            "search": "pubmed literature retrieval",
            "kind": "mcp_server",
            "as": "elsewhere",
            "require": ["cursor_cloud"],
        }
    )

    compilation = await compile_service.compile(text(document), scope())

    resolved, unmatched, unsupported = _search_entries(compilation)
    assert resolved.result is not None and resolved.search_mode == DEFINITION_SCAN
    assert unmatched.result is None and unmatched.blocker is not None
    assert unmatched.blocker.reason == "search_no_admitted_hits"
    assert unsupported.blocker is not None or (
        unsupported.result is not None and "cursor_cloud" in unsupported.result.supported_profiles
    )


@pytest.mark.asyncio
async def test_the_scan_and_the_probe_are_the_ones_the_selection_workspace_uses() -> None:
    definitions, search = await fast_track_catalog()
    rows = [
        row
        for row in await definitions.list_published_definitions()
        if row.ref.kind is DefinitionKind.MCP_SERVER
    ]

    scored = scan_definitions(rows, "pubmed literature retrieval")

    assert scored and scored[0][0] >= scored[-1][0]
    assert "pubmed" in scored[0][1].ref.logical_id
    assert all(score > 0 and reasons_ for score, _row, reasons_ in scored)
    assert scan_definitions(rows, "quantum widget calibration") == []
    # The seeded projection answers a definition searched by its own title; an unbuilt one
    # answers nothing.
    assert await projection_answers(search, scored[0][1], tenant_scope="global")
    assert not await projection_answers(UnbuiltProjection(), scored[0][1], tenant_scope="global")
