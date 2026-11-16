"""The guide's three transports answer alike: HTTP routes, missionctl and MCP.

`GET /guide`, `/guide/{topic}` and `/describe` behind the authenticated principal, the CLI's
`guide` and `describe` over the same app (Markdown by default, the envelope with `--json`), and
the `mission_guide` / `mission_describe` MCP tools, page resources and interview prompt. One
page is the same text on every transport once it is asked for in the same vocabulary: the MCP
tool's text content is the page's Markdown and its structured content is the envelope the route
returns. A describe answer that is prose arrives the same way; one that is data stays
structured. A refusal is typed on each.
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
    server_tool_listing,
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


def _text(result: Any) -> str:
    """A tool result's text content: what an agent reads."""

    return "".join(getattr(part, "text", "") for part in result.content)


def _envelope(result: Any) -> dict[str, Any]:
    """A tool result's structured content, which is also its text when it is a refusal."""

    envelope: dict[str, Any] = result.structured_content
    assert json.loads(_text(result)) == envelope
    return envelope


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
    envelope = from_mcp.structured_content
    assert envelope is not None and envelope["ok"] is True, envelope
    assert envelope["data"] == from_http.json()
    assert from_http.json()["topic"] == INDEX and from_http.json()["surface"] == "mcp"
    # The page arrives as Markdown: the text content is the page itself, not escaped JSON.
    assert _text(from_mcp) == from_http.json()["markdown"]
    assert _text(from_mcp).startswith("# Mission Control: start here\n\nYou are the Coordinator")

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
            assert from_mcp.structured_content["data"] == from_http.json(), topic  # type: ignore[index]
            assert _text(from_mcp) == from_http.json()["markdown"], topic
            assert _text(from_mcp).startswith("# "), topic
    status, markdown = run_cli(harness, monkeypatch, capsys, "guide", "interview")
    assert status == 0 and "## 3. The brief, and where each part goes" in markdown
    assert "`missionctl workspace check`" in markdown


async def test_describe_parity_and_the_cli_rendering(
    harness: CatalogHarness,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    server = _server(harness, frozenset({"catalog.read"}))
    # The API hands the HTTP route the listing of the MCP server it mounts.
    harness.app.state.mission_control_tool_listing = await server_tool_listing(server)
    data = ["lane:deep_agents", "model:producer.default", "sandbox:research.standard"]
    data.append(_pin(RESEARCH))
    prose = ["tool:mission_run_fork", "tool:mission_describe", "template:smallest", "manifest"]
    prose.append("manifest:Goal")
    async with Client(server) as mcp:
        for ref in (*data, *prose):
            from_http = harness.client.get(_url("describe"), params={"ref": ref})
            from_mcp = await mcp.call_tool("mission_describe", {"ref": ref})
            assert from_http.status_code == 200, (ref, from_http.text)
            envelope = from_mcp.structured_content
            assert envelope is not None and envelope["ok"] is True, (ref, envelope)
            assert envelope["data"] == from_http.json(), ref
            if ref in prose:
                # A prose answer arrives as Markdown, the same Markdown the route carries.
                assert _text(from_mcp) == from_http.json()["markdown"], ref
                assert _text(from_mcp).startswith("#"), ref
            else:
                # A data answer stays structured: the envelope as JSON text.
                assert "markdown" not in from_http.json(), ref
                assert json.loads(_text(from_mcp)) == envelope, ref
    lane = harness.client.get(_url("describe"), params={"ref": "lane:deep_agents"}).json()
    assert {"controls", "delivery_semantics", "time_travel"} <= set(lane["data"])
    # A typed tool is described from the server's own listing on both transports.
    described = harness.client.get(_url("describe"), params={"ref": "tool:mission_describe"})
    assert described.json()["data"]["input_schema"]["required"] == ["ref"]
    assert "Everything about one thing" in described.json()["data"]["description"]

    status, enveloped = run_cli(
        harness, monkeypatch, capsys, "describe", "lane:deep_agents", "--json"
    )
    assert status == 0 and json.loads(enveloped) == lane
    status, markdown = run_cli(harness, monkeypatch, capsys, "describe", "lane:deep_agents")
    assert status == 0 and markdown.strip() == describe_markdown(lane)
    assert markdown.startswith("# deep_agents\n\n```json")
    status, markdown = run_cli(harness, monkeypatch, capsys, "describe", "tool:mission_run_fork")
    fork = harness.client.get(_url("describe"), params={"ref": "tool:mission_run_fork"}).json()
    assert status == 0 and markdown.strip() == fork["markdown"] == describe_markdown(fork)
    # The notes read as Markdown; the request schema and the example are JSON blocks.
    assert markdown.startswith("# `mission_run_fork`")
    assert "## mission_run_fork: fork a run" in markdown
    assert "`sponsorship_ref`" in markdown and "## Example" in markdown and "```json" in markdown
    status, markdown = run_cli(harness, monkeypatch, capsys, "describe", "template:smallest")
    assert status == 0 and markdown.startswith("# Template `smallest`") and "```yaml" in markdown
    status, markdown = run_cli(harness, monkeypatch, capsys, "describe", "manifest")
    assert status == 0 and markdown.startswith("# Mission Manifest reference")


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
        topic = _envelope(await mcp.call_tool("mission_guide", {"topic": "pricing"}))
        ref = _envelope(await mcp.call_tool("mission_describe", {"ref": "everything"}))
        lane = _envelope(await mcp.call_tool("mission_describe", {"ref": "lane:nowhere"}))
        tool = _envelope(await mcp.call_tool("mission_describe", {"ref": "tool:nowhere"}))
    assert topic["ok"] is False and topic["error"]["code"] == "INVALID_ARGUMENT"
    assert "interview" in topic["error"]["details"]["valid"]
    assert ref["error"]["details"]["reason"] == "unknown_ref"
    assert "tool:<name>" in ref["error"]["details"]["valid"]
    assert "template:<id>" in ref["error"]["details"]["valid"]
    assert lane["error"]["code"] == "NOT_FOUND"
    # An unknown tool names the tools of the server it was asked on.
    assert tool["error"]["code"] == "NOT_FOUND"
    assert "tool:mission_guide" in tool["error"]["details"]["valid"]

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
        denied = _envelope(await mcp.call_tool("mission_guide", {}))
        described = _envelope(await mcp.call_tool("mission_describe", {"ref": "lane:deep_agents"}))
    assert denied["ok"] is False and denied["error"]["code"] == "FORBIDDEN"
    assert described["error"]["code"] == "FORBIDDEN"

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
