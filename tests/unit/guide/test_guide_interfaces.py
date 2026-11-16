"""The guide's three transports answer alike: HTTP routes, missionctl and MCP.

`GET /guide`, `/guide/{topic}` and `/describe` behind the authenticated principal, the CLI's
`guide` and `describe` over the same app (Markdown by default, the envelope with `--json`), and
the `mission_guide` / `mission_describe` MCP tools, page resources and interview prompt in
their envelope. One page is the same text on every transport once it is asked for in the same
vocabulary; a refusal is typed on each.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from fastmcp import Client, Context, FastMCP

import mission_control.interfaces.cli.main as cli
from mission_control.application.authoring.control_plane_repository import (
    InMemoryDefinitionRepository,
)
from mission_control.application.guide.pages import INDEX, TOPIC_IDS
from mission_control.interfaces.cli.guide import describe_markdown
from mission_control.interfaces.http.guide import router as guide_router
from mission_control.interfaces.mcp.coordinator_server import (
    CoordinatorPrincipal,
    _principal_call,
)
from mission_control.interfaces.mcp.guide_tools import (
    GUIDE_RESOURCE_PREFIX,
    INTERVIEW_PROMPT,
    ScopedGuide,
    register_guide_tools,
)
from tests.fixtures.catalog_http import INSTALLATION, TENANT, CatalogHarness, catalog_harness
from tests.unit.guide.support import stub_guide
from tests.unit.selection.test_selection_workspace import RESEARCH, _pin


@pytest.fixture
def harness() -> CatalogHarness:
    harness = catalog_harness(InMemoryDefinitionRepository(), None)
    harness.app.include_router(guide_router)
    harness.app.state.mission_control_guides = {(INSTALLATION, "biotech", TENANT): stub_guide()}
    return harness


def _url(path: str) -> str:
    return f"/v1/applications/biotech/{path}"


def run_cli(
    harness: CatalogHarness,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *argv: str,
) -> tuple[int, str]:
    monkeypatch.setenv("MISSION_CONTROL_TOKEN", "test-token")
    monkeypatch.setattr(cli.httpx, "Client", lambda **_kwargs: TestClient(harness.app))
    status = cli.main([*argv, "--application", "biotech"])
    return status, capsys.readouterr().out


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
    server = FastMCP("guide test")
    guide = harness.app.state.mission_control_guides[(INSTALLATION, "biotech", TENANT)]
    register_guide_tools(
        server,
        ScopedGuide({harness.tenant_scope: guide}),
        Resolver(harness.tenant_scope, permissions),
        call=_principal_call,
    )
    return server


async def test_the_start_page_is_one_text_on_http_cli_and_mcp(
    harness: CatalogHarness,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from_http = harness.client.get(_url("guide"), params={"surface": "mcp"})
    assert from_http.status_code == 200, from_http.text
    async with Client(_server(harness, frozenset({"catalog.read"}))) as mcp:
        from_mcp = await mcp.call_tool("mission_guide", {})
    assert from_mcp.data["ok"] is True, from_mcp.data
    assert from_mcp.data["data"] == from_http.json()
    assert from_http.json()["topic"] == INDEX and from_http.json()["surface"] == "mcp"

    # The HTTP route speaks routes by default; missionctl asks for its own commands.
    assert "`POST missions:start`" in harness.client.get(_url("guide")).json()["markdown"]
    status, markdown = run_cli(harness, monkeypatch, capsys, "guide")
    in_cli_words = harness.client.get(_url("guide"), params={"surface": "cli"}).json()
    assert status == 0 and markdown.strip() == in_cli_words["markdown"]
    assert "`missionctl mission start`" in markdown and markdown.startswith("# ")
    status, enveloped = run_cli(harness, monkeypatch, capsys, "guide", "--json")
    assert status == 0 and json.loads(enveloped) == in_cli_words


async def test_every_topic_is_served_on_every_transport(
    harness: CatalogHarness,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async with Client(_server(harness, frozenset({"catalog.read"}))) as mcp:
        for topic in TOPIC_IDS:
            from_http = harness.client.get(_url(f"guide/{topic}"), params={"surface": "mcp"})
            from_mcp = await mcp.call_tool("mission_guide", {"topic": topic})
            assert from_http.status_code == 200, (topic, from_http.text)
            assert from_mcp.data["data"] == from_http.json(), topic
    status, markdown = run_cli(harness, monkeypatch, capsys, "guide", "interview")
    assert status == 0 and "## 3. The brief, and where each part goes" in markdown
    assert "`missionctl workspace check`" in markdown


async def test_describe_parity_and_the_cli_rendering(
    harness: CatalogHarness,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    refs = ["lane:deep_agents", "model:producer.default", "tool:mission_run_fork", _pin(RESEARCH)]
    async with Client(_server(harness, frozenset({"catalog.read"}))) as mcp:
        for ref in refs:
            from_http = harness.client.get(_url("describe"), params={"ref": ref})
            from_mcp = await mcp.call_tool("mission_describe", {"ref": ref})
            assert from_http.status_code == 200, (ref, from_http.text)
            assert from_mcp.data["ok"] is True and from_mcp.data["data"] == from_http.json(), ref
    lane = harness.client.get(_url("describe"), params={"ref": "lane:deep_agents"}).json()
    assert {"controls", "delivery_semantics", "time_travel"} <= set(lane["data"])

    status, enveloped = run_cli(
        harness, monkeypatch, capsys, "describe", "lane:deep_agents", "--json"
    )
    assert status == 0 and json.loads(enveloped) == lane
    status, markdown = run_cli(harness, monkeypatch, capsys, "describe", "tool:mission_run_fork")
    fork = harness.client.get(_url("describe"), params={"ref": "tool:mission_run_fork"}).json()
    assert status == 0 and markdown.strip() == describe_markdown(fork)
    # The notes read as Markdown; the schema and the example are one JSON block.
    assert markdown.startswith("# mission_run_fork: fork a run")
    assert "`sponsorship_ref`" in markdown and '"example"' in markdown and "```json" in markdown


async def test_refusals_are_typed_on_every_transport(
    harness: CatalogHarness,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    unknown_topic = harness.client.get(_url("guide/pricing"))
    unknown_ref = harness.client.get(_url("describe"), params={"ref": "everything"})
    not_found = harness.client.get(_url("describe"), params={"ref": "lane:nowhere"})
    bad_surface = harness.client.get(_url("guide"), params={"surface": "telegram"})

    assert unknown_topic.status_code == 404
    assert unknown_topic.json()["detail"]["code"] == "guide_topic_unknown"
    assert unknown_topic.json()["detail"]["valid"] == list(TOPIC_IDS)
    assert unknown_ref.status_code == 422
    assert unknown_ref.json()["detail"]["code"] == "describe_ref_unknown"
    assert "lane:<profile>" in unknown_ref.json()["detail"]["valid"]
    assert not_found.status_code == 404
    assert not_found.json()["detail"]["valid"] == ["lane:claude_agent_sdk", "lane:deep_agents"]
    assert bad_surface.status_code == 422

    async with Client(_server(harness, frozenset({"catalog.read"}))) as mcp:
        topic = await mcp.call_tool("mission_guide", {"topic": "pricing"})
        ref = await mcp.call_tool("mission_describe", {"ref": "everything"})
        lane = await mcp.call_tool("mission_describe", {"ref": "lane:nowhere"})
    assert topic.data["ok"] is False and topic.data["error"]["code"] == "INVALID_ARGUMENT"
    assert "interview" in topic.data["error"]["details"]["valid"]
    assert ref.data["error"]["details"]["reason"] == "unknown_ref"
    assert "tool:<name>" in ref.data["error"]["details"]["valid"]
    assert lane.data["error"]["code"] == "NOT_FOUND"

    status, out = run_cli(harness, monkeypatch, capsys, "guide", "pricing")
    assert status == 2 and json.loads(out)["detail"]["code"] == "guide_topic_unknown"
    status, out = run_cli(harness, monkeypatch, capsys, "describe", "everything")
    assert status == 2 and json.loads(out)["detail"]["code"] == "describe_ref_unknown"


async def test_the_pages_are_resources_and_the_interview_is_a_prompt(
    harness: CatalogHarness,
) -> None:
    interview = harness.client.get(_url("guide/interview"), params={"surface": "mcp"}).json()
    async with Client(_server(harness, frozenset({"catalog.read"}))) as mcp:
        resources = {str(item.uri) for item in await mcp.list_resources()}
        read = await mcp.read_resource(f"{GUIDE_RESOURCE_PREFIX}interview")
        start = await mcp.read_resource(f"{GUIDE_RESOURCE_PREFIX}{INDEX}")
        prompt = await mcp.get_prompt(INTERVIEW_PROMPT)

    assert resources == {f"{GUIDE_RESOURCE_PREFIX}{name}" for name in (INDEX, *TOPIC_IDS)}
    assert read[0].text == interview["markdown"]  # type: ignore[union-attr]
    assert "You are the Coordinator" in start[0].text  # type: ignore[union-attr]
    message: Any = prompt.messages[0].content
    assert message.text == interview["markdown"]


async def test_reads_need_catalog_read(harness: CatalogHarness) -> None:
    async with Client(_server(harness, frozenset({"workflow_run.read"}))) as mcp:
        denied = await mcp.call_tool("mission_guide", {})
        described = await mcp.call_tool("mission_describe", {"ref": "lane:deep_agents"})
    assert denied.data["ok"] is False and denied.data["error"]["code"] == "FORBIDDEN"
    assert described.data["error"]["code"] == "FORBIDDEN"

    harness.app.state.mission_control_guides = {}
    unavailable = harness.client.get(_url("guide"))
    assert unavailable.status_code == 503
    assert unavailable.json()["detail"]["code"] == "guide_unavailable"

    reader = catalog_harness(InMemoryDefinitionRepository(), None, frozenset({"workflow_run.read"}))
    reader.app.include_router(guide_router)
    reader.app.state.mission_control_guides = {(INSTALLATION, "biotech", TENANT): stub_guide()}
    forbidden = reader.client.get(_url("describe"), params={"ref": "lane:deep_agents"})
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"]["code"] == "catalog_permission_denied"
