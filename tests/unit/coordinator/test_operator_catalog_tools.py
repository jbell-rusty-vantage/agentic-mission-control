"""External discovery, candidate inspection and pinning on the operator MCP server.

The four tools call the tenant's `CatalogService` exactly as the HTTP catalog routes do, behind
the same permissions (`catalog.read`, `capability.discover`, `capability.inspect`). Each is
registered only where the service composes what it needs; a discovered candidate is recorded
as a candidate and is never a capability. In memory: the seeded fast-track catalog with its
real search, and fakes for the external registries (no network, no subprocess).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastmcp import Client, Context, FastMCP

from mission_control.application.capabilities.catalog import CatalogService
from mission_control.application.capabilities.external_candidate_repository import (
    ExternalCandidateNotFound,
)
from mission_control.application.capabilities.external_capability_discovery import (
    ExternalDiscoveryBatch,
    ExternalDiscoveryCandidate,
    ExternalDiscoveryEvidence,
)
from mission_control.interfaces.mcp.catalog_tools import (
    DISCOVER_MCP_TOOL,
    DISCOVER_SKILLS_TOOL,
    DISCOVERY_TOOL_NAMES,
    INSPECT_TOOL,
    PIN_TOOL,
    ScopedCatalog,
    register_catalog_tools,
)
from mission_control.interfaces.mcp.coordinator_server import CoordinatorPrincipal, _principal_call
from tests.fixtures.catalog.fast_track_catalog import fast_track_catalog

SCOPE = "mc/00000000-0000-4000-8000-000000000001/biotech/00000000-0000-4000-8000-000000000002"
AT = datetime(2026, 11, 16, 12, tzinfo=UTC)
DIGEST = "sha256:" + "a" * 64
CANDIDATE = "candidate:" + DIGEST
ALL = frozenset({"catalog.read", "capability.discover", "capability.inspect"})


class FakeDiscovery:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int, str | None]] = []
        self.fail: Exception | None = None

    def _batch(self, source: str, query: str) -> ExternalDiscoveryBatch:
        return ExternalDiscoveryBatch(
            source=source,  # type: ignore[arg-type]
            candidates=(
                ExternalDiscoveryCandidate(
                    candidate_id=CANDIDATE,
                    source=source,  # type: ignore[arg-type]
                    upstream_identity="io.example/files",
                    locator="https://registry.example/servers/files",
                    discovered_at=AT,
                    query=query,
                    raw_response_digest=DIGEST,
                ),
            ),
            evidence=(
                ExternalDiscoveryEvidence(
                    source=source,  # type: ignore[arg-type]
                    source_version="v0.1",
                    query=query,
                    retrieved_at=AT,
                    raw_response_digest=DIGEST,
                    raw_response_size_bytes=10,
                ),
            ),
        )

    async def discover_mcp_servers(self, query: str, *, limit: int = 10) -> ExternalDiscoveryBatch:
        if self.fail is not None:
            raise self.fail
        self.calls.append(("mcp", query, limit, None))
        return self._batch("mcp_registry", query)

    async def discover_agent_skills(
        self, query: str, *, limit: int = 10, owner: str | None = None
    ) -> ExternalDiscoveryBatch:
        if self.fail is not None:
            raise self.fail
        self.calls.append(("skills", query, limit, owner))
        return self._batch("npx_skills", query)


class FakeInspection:
    def __init__(self) -> None:
        self.requests: list[tuple[Any, Any]] = []

    async def inspect(self, principal: Any, request: Any) -> Any:
        self.requests.append((principal, request))
        if request.candidate_id != CANDIDATE:
            raise ExternalCandidateNotFound(request.candidate_id)
        return SimpleNamespace(
            model_dump=lambda mode="json": {
                "candidate_id": request.candidate_id,
                "decision": "needs_review",
                "installed": False,
            }
        )


class Resolver:
    def __init__(self, permissions: frozenset[str]) -> None:
        self.principal = CoordinatorPrincipal(
            actor_id="coordinator-1",
            tenant_scope=SCOPE,
            roles=frozenset(),
            permissions=permissions,
            request_scope=SCOPE,
        )

    async def resolve(self, _context: Context) -> CoordinatorPrincipal:
        return self.principal


async def _service(**composed: Any) -> CatalogService:
    definitions, search = await fast_track_catalog()
    return replace(
        CatalogService(SCOPE, "global", definitions, search=search),  # type: ignore[arg-type]
        **composed,
    )


def _server(service: CatalogService, permissions: frozenset[str] = ALL) -> FastMCP:
    server = FastMCP("catalog tools test")
    register_catalog_tools(
        server, ScopedCatalog({SCOPE: service}), Resolver(permissions), call=_principal_call
    )
    return server


def _data(result: Any) -> dict[str, Any]:
    envelope = result.structured_content
    assert envelope is not None and envelope["ok"] is True, envelope
    return dict(envelope["data"])


def _error(result: Any) -> dict[str, Any]:
    envelope = result.structured_content
    assert envelope is not None and envelope["ok"] is False, envelope
    return dict(envelope["error"])


async def test_tools_register_only_where_the_service_composes_them() -> None:
    search_only = await _service()
    everything = await _service(discovery=FakeDiscovery(), inspection=FakeInspection())

    async with Client(_server(search_only)) as mcp:
        bare = {tool.name for tool in await mcp.list_tools()}
    async with Client(_server(everything)) as mcp:
        listed = {tool.name: tool for tool in await mcp.list_tools()}

    assert bare == {PIN_TOOL}
    assert set(listed) == set(DISCOVERY_TOOL_NAMES)
    # Every description states the rule: discovered is not runnable.
    said = {name: " ".join((tool.description or "").split()) for name, tool in listed.items()}
    for name in (DISCOVER_MCP_TOOL, DISCOVER_SKILLS_TOOL):
        assert "Discovered is not runnable" in said[name], name
        assert listed[name].annotations.openWorldHint is True  # type: ignore[union-attr]
    assert "installs and admits nothing" in said[INSPECT_TOOL]
    assert listed[PIN_TOOL].annotations.readOnlyHint is True  # type: ignore[union-attr]


async def test_pin_resolves_one_capability_of_the_catalog() -> None:
    async with Client(_server(await _service())) as mcp:
        pinned = _data(
            await mcp.call_tool(
                PIN_TOOL, {"query": "pubmed literature retrieval", "kinds": ["mcp_server"]}
            )
        )
        missing = _error(await mcp.call_tool(PIN_TOOL, {"query": "quantum widget calibration zzz"}))
        bad_kind = await mcp.call_tool(PIN_TOOL, {"query": "pubmed", "kinds": ["nonsense"]})

    assert "pubmed" in pinned["pin"] and "#sha256:" in pinned["pin"]
    assert pinned["search_mode"] == "lexical" and pinned["candidates"]
    assert missing["code"] == "CAPABILITY_NOT_FOUND"
    assert bad_kind.structured_content["error"]["code"] == "INVALID_ARGUMENT"  # type: ignore[index]


async def test_discovery_records_candidates_and_inspection_reads_one() -> None:
    discovery, inspection = FakeDiscovery(), FakeInspection()
    service = await _service(discovery=discovery, inspection=inspection)

    async with Client(_server(service)) as mcp:
        servers = _data(await mcp.call_tool(DISCOVER_MCP_TOOL, {"query": "filesystem"}))
        skills = _data(
            await mcp.call_tool(
                DISCOVER_SKILLS_TOOL, {"query": "file analysis", "limit": 3, "owner": "acme"}
            )
        )
        report = _data(await mcp.call_tool(INSPECT_TOOL, {"candidate_id": CANDIDATE}))
        unknown = _error(
            await mcp.call_tool(INSPECT_TOOL, {"candidate_id": "candidate:sha256:" + "b" * 64})
        )

    assert discovery.calls == [
        ("mcp", "filesystem", 10, None),
        ("skills", "file analysis", 3, "acme"),
    ]
    # A candidate is untrusted, uninspected and promoted to nothing: it cannot run.
    (candidate,) = servers["candidates"]
    assert candidate["trust_tier"] == "untrusted" and candidate["promoted_ref"] is None
    assert candidate["inspection_status"] == "not_inspected"
    assert skills["source"] == "npx_skills"
    assert report == {"candidate_id": CANDIDATE, "decision": "needs_review", "installed": False}
    principal, request = inspection.requests[0]
    assert principal.actor_id == "coordinator-1" and principal.tenant_scope == SCOPE
    assert principal.roles == frozenset({"coordinator_planner"})
    assert request.candidate_id == CANDIDATE and request.requested_capabilities == frozenset()
    assert unknown["code"] == "NOT_FOUND" and "discover first" in unknown["message"]


@pytest.mark.parametrize(
    ("tool", "arguments", "permission"),
    [
        (PIN_TOOL, {"query": "pubmed"}, "catalog.read"),
        (DISCOVER_MCP_TOOL, {"query": "filesystem"}, "capability.discover"),
        (DISCOVER_SKILLS_TOOL, {"query": "filesystem"}, "capability.discover"),
        (INSPECT_TOOL, {"candidate_id": CANDIDATE}, "capability.inspect"),
    ],
)
async def test_each_tool_needs_the_permission_its_route_needs(
    tool: str, arguments: dict[str, Any], permission: str
) -> None:
    discovery, inspection = FakeDiscovery(), FakeInspection()
    service = await _service(discovery=discovery, inspection=inspection)

    async with Client(_server(service, ALL - {permission})) as mcp:
        refused = _error(await mcp.call_tool(tool, arguments))

    assert refused["code"] == "FORBIDDEN" and permission in refused["message"]
    assert refused["details"] == {"required": permission}
    assert discovery.calls == [] and inspection.requests == []


async def test_a_registry_that_does_not_answer_is_a_dependency_never_an_empty_result() -> None:
    discovery = FakeDiscovery()
    discovery.fail = RuntimeError("the registry timed out")
    service = await _service(discovery=discovery, inspection=FakeInspection())
    other_scope = Resolver(ALL)
    other_scope.principal = replace(other_scope.principal, request_scope=SCOPE + "x")

    async with Client(_server(service)) as mcp:
        unavailable = _error(await mcp.call_tool(DISCOVER_MCP_TOOL, {"query": "filesystem"}))
        # asyncio raises a bare NotImplementedError where the loop cannot start a subprocess.
        discovery.fail = NotImplementedError()
        no_subprocess = _error(await mcp.call_tool(DISCOVER_SKILLS_TOOL, {"query": "pdf"}))
    server = FastMCP("other scope")
    register_catalog_tools(
        server, ScopedCatalog({SCOPE: service}), other_scope, call=_principal_call
    )
    async with Client(server) as mcp:
        foreign = _error(await mcp.call_tool(PIN_TOOL, {"query": "pubmed"}))

    assert unavailable["code"] == "DEPENDENCY_UNAVAILABLE"
    assert unavailable["message"] == (
        "MCP server discovery did not answer (RuntimeError): the registry timed out"
    )
    assert no_subprocess["code"] == "DEPENDENCY_UNAVAILABLE"
    assert no_subprocess["message"].startswith("agent-skill discovery starts a subprocess")
    assert "event loop cannot start one" in no_subprocess["message"]
    assert foreign["code"] == "FORBIDDEN"
