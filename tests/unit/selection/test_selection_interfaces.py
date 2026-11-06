"""The Selection Workspace's three transports answer alike: HTTP routes, missionctl and MCP.

`POST /selection/search` and `/selection/check` behind the authenticated principal, the CLI's
`search` and `workspace check` (JSON and YAML drafts, exit 6 on a refused draft) over the same
app, and the `mission_search` / `selection_check` MCP tools in their envelope.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from fastmcp import Client, Context, FastMCP

import mission_control.interfaces.cli.main as cli
from mission_control.application.authoring.control_plane_repository import (
    InMemoryDefinitionRepository,
)
from mission_control.interfaces.http.selection import router as selection_router
from mission_control.interfaces.mcp.coordinator_server import (
    CoordinatorPrincipal,
    _principal_call,
)
from mission_control.interfaces.mcp.selection_tools import (
    ScopedSelection,
    register_selection_tools,
)
from tests.fixtures.catalog_http import INSTALLATION, TENANT, CatalogHarness, catalog_harness
from tests.unit.selection.test_selection_workspace import (
    NARROW_WORKFLOW,
    RESEARCH,
    _pin,
    _workspace,
)


@pytest.fixture
def harness() -> CatalogHarness:
    harness = catalog_harness(InMemoryDefinitionRepository(), None)
    harness.app.include_router(selection_router)
    harness.app.state.mission_control_selection_workspaces = {
        (INSTALLATION, "biotech", TENANT): _workspace(application_id="biotech")
    }
    return harness


def _url(path: str) -> str:
    return f"/v1/applications/biotech/selection/{path}"


def run_cli(
    harness: CatalogHarness,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *argv: str,
) -> tuple[int, dict[str, Any]]:
    monkeypatch.setenv("MISSION_CONTROL_TOKEN", "test-token")
    monkeypatch.setattr(cli.httpx, "Client", lambda **_kwargs: TestClient(harness.app))
    status = cli.main([*argv, "--application", "biotech", "--json"])
    out = capsys.readouterr().out.strip().splitlines()
    return status, json.loads(out[-1]) if out else {}


class Resolver:
    def __init__(self, request_scope: str, permissions: frozenset[str]) -> None:
        self.principal = CoordinatorPrincipal(
            actor_id="coordinator-1",
            tenant_scope=request_scope,
            roles=frozenset({"coordinator_planner"}),
            permissions=permissions,
            request_scope=request_scope,
        )

    async def resolve(self, _context: Context) -> CoordinatorPrincipal:
        return self.principal


def _server(harness: CatalogHarness, permissions: frozenset[str]) -> FastMCP:
    server = FastMCP("selection test")
    workspace = harness.app.state.mission_control_selection_workspaces[
        (INSTALLATION, "biotech", TENANT)
    ]
    register_selection_tools(
        server,
        ScopedSelection({harness.tenant_scope: workspace}),
        Resolver(harness.tenant_scope, permissions),
        call=_principal_call,
    )
    return server


async def test_search_parity_across_http_cli_and_mcp(
    harness: CatalogHarness,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    body = {"query": "research harness", "facets": ["capability", "lane"]}
    from_http = harness.client.post(_url("search"), json=body)
    assert from_http.status_code == 200, from_http.text
    status, from_cli = run_cli(
        harness,
        monkeypatch,
        capsys,
        "search",
        "research harness",
        "--facet",
        "capability",
        "--facet",
        "lane",
    )
    async with Client(_server(harness, frozenset({"catalog.read"}))) as mcp:
        from_mcp = await mcp.call_tool(
            "mission_search", {"query": "research harness", "facets": ["capability", "lane"]}
        )

    refs = [hit["ref"] for hit in from_http.json()["hits"]]
    assert _pin(RESEARCH) in refs and "lane:deep_agents" in refs
    assert status == 0 and [hit["ref"] for hit in from_cli["hits"]] == refs
    assert from_mcp.data["ok"] is True, from_mcp.data
    assert [hit["ref"] for hit in from_mcp.data["data"]["hits"]] == refs


async def test_check_parity_and_the_blocked_exit(
    harness: CatalogHarness,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    refused = {
        "lane_profile": "deep_agents",
        "model_profile": "producer.default",
        "family": "StageGraph",
        "data_class": "internal",
        "capabilities": [_pin(RESEARCH)],
        "workflow_type": _pin(NARROW_WORKFLOW),
    }
    from_http = harness.client.post(_url("check"), json=refused).json()
    assert from_http["admissible"] is False
    assert [item["code"] for item in from_http["refusals"]] == ["AUTHORITY_CEILING_EXCEEDED"]

    draft = tmp_path / "draft.yaml"
    draft.write_text(
        "\n".join(
            [
                "lane_profile: deep_agents",
                "model_profile: producer.default",
                "family: StageGraph",
                "data_class: internal",
                "capabilities:",
                f"  - '{_pin(RESEARCH)}'",
                f"workflow_type: '{_pin(NARROW_WORKFLOW)}'",
            ]
        ),
        encoding="utf-8",
    )
    status, from_cli = run_cli(harness, monkeypatch, capsys, "workspace", "check", str(draft))
    assert status == 6 and from_cli["refusals"] == from_http["refusals"]

    admissible = tmp_path / "draft.json"
    admissible.write_text(json.dumps({**refused, "workflow_type": None}), encoding="utf-8")
    status, from_cli = run_cli(harness, monkeypatch, capsys, "workspace", "check", str(admissible))
    assert status == 0 and from_cli["admissible"] is True

    async with Client(_server(harness, frozenset({"catalog.read"}))) as mcp:
        from_mcp = await mcp.call_tool("selection_check", {"draft": refused})
        invalid = await mcp.call_tool("selection_check", {"draft": {"lane_profile": "x"}})
    assert from_mcp.data["data"]["refusals"] == from_http["refusals"]
    assert invalid.data["ok"] is False and invalid.data["error"]["code"] == "INVALID_ARGUMENT"


async def test_reads_need_catalog_read(harness: CatalogHarness) -> None:
    async with Client(_server(harness, frozenset({"workflow_run.read"}))) as mcp:
        denied = await mcp.call_tool("mission_search", {"query": "lane"})
    assert denied.data["ok"] is False and denied.data["error"]["code"] == "FORBIDDEN"

    harness.app.state.mission_control_selection_workspaces = {}
    unavailable = harness.client.post(_url("search"), json={"query": "lane"})
    assert unavailable.status_code == 503
    assert unavailable.json()["detail"]["code"] == "selection_unavailable"
