"""C3: the Transcript on HTTP, CLI and MCP returns the same entries under the same scope."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from fastmcp import Client, FastMCP

from mission_control.interfaces.cli import main as cli
from mission_control.interfaces.mcp.coordinator_server import CoordinatorPrincipal, _principal_call
from mission_control.interfaces.mcp.transcript_tools import (
    TRANSCRIPT_TOOL,
    ScopedTranscripts,
    register_transcript_tools,
)
from tests.fixtures.transcripts import (
    RUN_KEY,
    SECRET_VALUE,
)
from tests.support.ids import SCOPE
from tests.support.unit.frames.transcript_interfaces import (
    _cli_transport,
    http_app,
    transcript_service,
)

PATH = f"/v1/applications/biotech/runs/{RUN_KEY}/transcript"


def test_http_jsonl_markdown_json_and_errors() -> None:
    client = TestClient(http_app())
    jsonl = client.get(PATH)
    assert jsonl.status_code == 200
    assert jsonl.headers["content-type"].startswith("application/x-ndjson")
    lines = [json.loads(line) for line in jsonl.text.splitlines()]
    assert len(lines) == 15 and all(
        line["schema_version"] == "mc.transcript_entry.v2" for line in lines
    )
    assert [line["entry_seq"] for line in lines] == list(range(1, 16))
    next_cursor = jsonl.headers["x-transcript-next-cursor"]
    assert next_cursor == lines[-1]["cursor"]
    assert SECRET_VALUE not in jsonl.text
    markdown = client.get(PATH, headers={"Accept": "text/markdown"})
    assert markdown.headers["content-type"].startswith("text/markdown")
    assert markdown.text.startswith(f"# Transcript · run {RUN_KEY}")
    page = client.get(PATH, params={"format": "json", "canonical_only": "true", "limit": 2})
    body = page.json()
    assert len(body["entries"]) == 2 and body["has_more"] is True
    newer = client.get(PATH, params={"since": lines[11]["cursor"]})
    assert [json.loads(line)["cursor"] for line in newer.text.splitlines()] == [
        line["cursor"] for line in lines[12:]
    ]
    expired = client.get(PATH, params={"since": "garbage"})
    assert expired.status_code == 409 and expired.json()["detail"]["code"] == "CURSOR_EXPIRED"
    assert client.get(PATH.replace(RUN_KEY, "missing")).status_code == 404
    assert client.get(PATH, params={"full": "true"}).status_code == 501
    denied = TestClient(http_app(permissions=frozenset())).get(PATH)
    assert denied.status_code == 403
    other_app = TestClient(http_app()).get(PATH.replace("/biotech/", "/ai-engineer/"))
    assert other_app.status_code == 403


def test_http_frames_tail_is_sse_labelled_non_canonical() -> None:
    client = TestClient(http_app())
    response = client.get(
        f"/v1/applications/biotech/runs/{RUN_KEY}/frames/tail",
        params={"timeout": 0.2, "poll": 0.05},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    frames = [event for event in events if event.get("source") == "provider_frame"]
    assert len(frames) == 8 and all(event["canonical"] is False for event in frames)
    assert events[-1]["reason"] == "timeout" and events[-1]["canonical"] is False


@pytest.fixture
def cli_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MISSION_CONTROL_TOKEN", "token")
    monkeypatch.setenv("MISSION_CONTROL_APPLICATION_ID", "biotech")
    monkeypatch.setattr(cli.httpx, "Client", _cli_transport(http_app()))


def test_cli_transcript_formats_cursor_errors_and_follow_timeout(
    cli_env: None, capsysbinary: pytest.CaptureFixture[bytes]
) -> None:
    assert cli.main(["run", "transcript", RUN_KEY, "--format", "md"]) == 0
    out = capsysbinary.readouterr().out.decode("utf-8")
    assert out.startswith(f"# Transcript · run {RUN_KEY}") and "✓" in out
    assert cli.main(["run", "transcript", RUN_KEY, "--canonical-only", "--limit", "3"]) == 0
    lines = capsysbinary.readouterr().out.decode("utf-8").splitlines()
    assert len(lines) == 3 and all(json.loads(line)["canonical"] for line in lines)
    assert cli.main(["run", "transcript", RUN_KEY, "--since", "nope"]) == 2
    assert "CURSOR_EXPIRED" in capsysbinary.readouterr().out.decode("utf-8")
    assert cli.main(["run", "transcript", RUN_KEY, "--follow", "--wait", "0.3"]) == 6
    captured = capsysbinary.readouterr()
    assert len(captured.out.decode("utf-8").splitlines()) == 15, "follow prints once"
    assert b"wait_timeout" in captured.err
    assert cli.main(["run", "frames", RUN_KEY, "--tail", "--wait", "0.2", "--until-end"]) == 6
    tail = [json.loads(line) for line in capsysbinary.readouterr().out.decode().splitlines()]
    assert tail[-1]["event"] == "end" and all(item["canonical"] is False for item in tail)


@pytest.mark.asyncio
async def test_mcp_tool_and_resource_return_the_http_entries_read_only() -> None:
    principal = CoordinatorPrincipal(
        actor_id="coordinator",
        tenant_scope=SCOPE,
        roles=frozenset(),
        permissions=frozenset({"workflow.result.read"}),
        request_scope=SCOPE,
    )

    class Principals:
        async def resolve(self, context: Any) -> CoordinatorPrincipal:
            del context
            return principal

    server = FastMCP("transcript-test")
    register_transcript_tools(
        server, ScopedTranscripts({SCOPE: transcript_service()}), Principals(), call=_principal_call
    )
    http_lines = [json.loads(line) for line in TestClient(http_app()).get(PATH).text.splitlines()]
    async with Client(server) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        assert tools[TRANSCRIPT_TOOL].annotations is not None
        assert tools[TRANSCRIPT_TOOL].annotations.readOnlyHint is True
        result = await client.call_tool(TRANSCRIPT_TOOL, {"run_id": RUN_KEY, "format": "json"})
        envelope = result.structured_content
        assert envelope is not None and envelope["ok"] is True
        mcp_entries = envelope["data"]["entries"]
        assert [entry["cursor"] for entry in mcp_entries] == [line["cursor"] for line in http_lines]
        resource = await client.read_resource(
            f"mc://applications/biotech/runs/{RUN_KEY}/transcript?since={http_lines[11]['cursor']}"
        )
        text = resource[0].text  # type: ignore[union-attr]
        assert [json.loads(line)["cursor"] for line in text.splitlines()] == [
            line["cursor"] for line in http_lines[12:]
        ]
        with pytest.raises(Exception, match="application scope denied|denied"):
            await client.read_resource(f"mc://applications/ai-engineer/runs/{RUN_KEY}/transcript")


def test_cli_transcript_follows_has_more_up_to_the_limit(
    cli_env: None, capsysbinary: pytest.CaptureFixture[bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tracing Stage 3 (R4-F11): pages the server marks `X-Transcript-Has-More` are read on,
    in pages of at most the route cap, until `--limit` entries; Markdown keeps one header."""

    monkeypatch.setattr(cli, "TRANSCRIPT_PAGE_LIMIT", 4)
    assert cli.main(["run", "transcript", RUN_KEY, "--limit", "10"]) == 0
    lines = capsysbinary.readouterr().out.decode("utf-8").splitlines()
    assert len(lines) == 10
    cursors = [json.loads(line)["cursor"] for line in lines]
    assert cursors == sorted(cursors) and len(set(cursors)) == 10
    assert cli.main(["run", "transcript", RUN_KEY, "--limit", "100"]) == 0
    assert len(capsysbinary.readouterr().out.decode("utf-8").splitlines()) == 15
    assert cli.main(["run", "transcript", RUN_KEY, "--limit", "100", "--format", "md"]) == 0
    markdown = capsysbinary.readouterr().out.decode("utf-8")
    assert markdown.count(f"# Transcript · run {RUN_KEY}") == 1
    assert markdown.count("_Legend:") == 1


def test_cli_points_pages_under_the_route_cap(capsys: pytest.CaptureFixture[str]) -> None:
    """Tracing Stage 3 (R4-F12): `run points --limit` above the route's 500 is read in pages
    of at most 500 by `next_cursor` and printed as one page."""

    import argparse

    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        seen.append(params)
        limit = int(params["limit"])
        if limit > 500:
            return httpx.Response(422, json={"detail": {"code": "invalid_points_query"}})
        start = int(params.get("cursor", "0"))
        rows = [{"point_id": f"p{index}"} for index in range(start, min(start + limit, 1_200))]
        following = start + len(rows)
        return httpx.Response(
            200,
            json={
                "application_id": "biotech",
                "entries": rows,
                "next_cursor": str(following) if following < 1_200 else None,
            },
        )

    transport = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://mc.test")
    client = cli.MissionClient(transport, "biotech")
    args = argparse.Namespace(
        run_id=RUN_KEY, reconcile=False, seedable=False, limit=1_100, cursor=None
    )
    assert cli.run_points(client, args) == 0
    page = json.loads(capsys.readouterr().out)
    assert len(page["entries"]) == 1_100 and page["next_cursor"] == "1100"
    assert [int(item["limit"]) for item in seen] == [500, 500, 100]
    assert cli.run_points(client, argparse.Namespace(**{**vars(args), "limit": 5_000})) == 0
    assert len(json.loads(capsys.readouterr().out)["entries"]) == 1_200


async def test_the_mcp_tool_answers_structured_entries_by_default_one_small_page() -> None:
    """With no `format` the tool returns entries an agent reads without unescaping a string of
    JSON Lines, 20 a page; JSON Lines and Markdown stay options."""

    principal = CoordinatorPrincipal(
        actor_id="coordinator",
        tenant_scope=SCOPE,
        roles=frozenset(),
        permissions=frozenset({"workflow.result.read"}),
        request_scope=SCOPE,
    )

    class Principals:
        async def resolve(self, context: Any) -> CoordinatorPrincipal:
            del context
            return principal

    server = FastMCP("transcript-default-test")
    register_transcript_tools(
        server, ScopedTranscripts({SCOPE: transcript_service()}), Principals(), call=_principal_call
    )
    async with Client(server) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        default = await client.call_tool(TRANSCRIPT_TOOL, {"run_id": RUN_KEY})
        lines = await client.call_tool(TRANSCRIPT_TOOL, {"run_id": RUN_KEY, "format": "jsonl"})
        first = await client.call_tool(TRANSCRIPT_TOOL, {"run_id": RUN_KEY, "limit": 3})

    schema = tools[TRANSCRIPT_TOOL].inputSchema["properties"]
    assert schema["format"]["default"] == "json" and schema["limit"]["default"] == 20
    data = default.structured_content["data"]  # type: ignore[index]
    assert data["format"] == "json" and "content" not in data
    assert isinstance(data["entries"], list) and 0 < len(data["entries"]) <= 20
    assert {"cursor", "kind"} <= set(data["entries"][0])
    as_lines = lines.structured_content["data"]  # type: ignore[index]
    assert as_lines["format"] == "jsonl" and "entries" not in as_lines
    assert [json.loads(line)["cursor"] for line in as_lines["content"].splitlines()] == [
        entry["cursor"] for entry in data["entries"]
    ]
    page = first.structured_content["data"]  # type: ignore[index]
    assert len(page["entries"]) == 3 and page["has_more"] is True and page["next_cursor"]
