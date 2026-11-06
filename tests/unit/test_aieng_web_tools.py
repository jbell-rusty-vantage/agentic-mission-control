from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest

from mission_control.adapters.deep_agents.browser_tool import granted_network_hosts
from tests.fixtures.aieng_web_tools import AIENG_HOSTS, AIENG_SEEDS, build_aieng_web_tools
from tests.fixtures.qualia_web_tools import WebCallBudget, WebToolRefused

SHA = "e21ce33d4486899069dda55254e6ec56e874a854"
ATOM = """<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2503.13657v3</id>
    <title>Why Do Multi-Agent
      LLM Systems Fail?</title>
    <published>2025-03-17T17:00:00Z</published>
    <updated>2025-10-26T23:25:18Z</updated>
    <summary>We introduce MAST-Data, a dataset of 1600+ annotated traces.</summary>
    <author><name>Mert Cemri</name></author>
    <author><name>Ion Stoica</name></author>
  </entry>
</feed>"""


@pytest.fixture(autouse=True)
def fixture_operation_network_grants():
    with granted_network_hosts(AIENG_HOSTS):
        yield


def tools_for(tmp_path: Path, respond, environment=None):
    return build_aieng_web_tools(
        tmp_path / "web",
        environment=(
            {"CONTEXT7_API_KEY": "c7", "GITHUB_TOKEN": "gh"} if environment is None else environment
        ),
        transport=httpx.MockTransport(respond),
        budget=WebCallBudget(max_calls=20, max_calls_per_tool=6),
    )


def test_exact_definitions_and_skills_without_network(tmp_path: Path) -> None:
    web = build_aieng_web_tools(tmp_path / "web", environment={})
    names = {component.tool_name for component in web.components}
    assert {"github_file", "arxiv_abs", "context7_docs", "firecrawl_search"} <= names
    assert all(c.ref.logical_id.startswith("tool.aieng.") for c in web.components)
    assert {skill.skill_name for skill in web.skills} == {
        "aieng-firecrawl-research",
        "aieng-tavily-research",
    }
    again = build_aieng_web_tools(tmp_path / "other", environment={})
    assert [c.ref.digest for c in web.components] == [c.ref.digest for c in again.components]


async def test_github_file_pins_the_resolved_commit_and_is_citable(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/commits/main"):
            assert request.headers["accept"] == "application/vnd.github.sha"
            return httpx.Response(200, content=SHA.encode())
        assert request.url.params["ref"] == SHA
        assert request.headers["authorization"] == "Bearer gh"
        return httpx.Response(200, content=b"# Deep Agents\n\nUse the task tool for subagents.\n")

    web = tools_for(tmp_path, respond)
    result = json.loads(
        await web.tools["github_file"].ainvoke(
            {"owner": "langchain-ai", "repo": "deepagents", "path": "README.md", "ref": "main"}
        )
    )
    evidence = result["evidence"]
    assert evidence["requested_url"] == (
        f"https://github.com/langchain-ai/deepagents/blob/{SHA}/README.md"
    )
    assert evidence["repository_commit"] == SHA
    assert "task tool" in result["content"]["text"]
    read = json.loads(
        await web.tools["source_read"].ainvoke(
            {"capture_id": evidence["capture_id"], "find": "task tool"}
        )
    )
    assert read["content"].startswith("task tool")
    raw = (tmp_path / "web" / f"{evidence['capture_id']}.response.bin").read_bytes()
    envelope = json.loads(raw)
    assert base64.b64decode(envelope["vendor_response_base64"]).startswith(b"# Deep Agents")
    assert len(calls) == 2 and web.worker.budget.calls == {
        "github_commit_ref": 1,
        "github_file": 1,
    }


async def test_arxiv_abs_cites_the_exact_returned_version(tmp_path: Path) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "export.arxiv.org"
        return httpx.Response(200, content=ATOM.encode())

    web = tools_for(tmp_path, respond)
    result = json.loads(await web.tools["arxiv_abs"].ainvoke({"arxiv_id": "2503.13657"}))
    assert result["evidence"]["requested_url"] == "https://arxiv.org/abs/2503.13657v3"
    text = result["content"]["text"]
    assert "Title: Why Do Multi-Agent LLM Systems Fail?" in text
    assert "Authors: Mert Cemri, Ion Stoica" in text
    assert "Abstract: We introduce MAST-Data" in text


async def test_discovery_results_are_retained_but_never_citable(tmp_path: Path) -> None:
    web = tools_for(tmp_path, lambda _request: httpx.Response(200, content=ATOM.encode()))
    result = json.loads(await web.tools["arxiv_search"].ainvoke({"query": "multi-agent failure"}))
    assert result["citable"] is False
    assert result["content"][0]["url"] == "https://arxiv.org/abs/2503.13657v3"
    with pytest.raises(WebToolRefused):
        web.worker.evidence.read_source(
            __import__(
                "tests.fixtures.qualia_web_tools", fromlist=["SourceReadInput"]
            ).SourceReadInput(capture_id=result["evidence"]["capture_id"])
        )


async def test_context7_docs_record_upstream_sources(tmp_path: Path) -> None:
    body = b"### Subagents\n\nSource: https://github.com/langchain-ai/deepagents/blob/main/README.md\n\ntext\n"

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer c7"
        assert request.url.params["type"] == "txt"
        return httpx.Response(200, content=body)

    web = tools_for(tmp_path, respond)
    result = json.loads(
        await web.tools["context7_docs"].ainvoke(
            {"library_id": "/langchain-ai/deepagents", "topic": "subagents"}
        )
    )
    evidence = result["evidence"]
    assert evidence["requested_url"].startswith(
        "https://context7.com/langchain-ai/deepagents/llms.txt?topic=subagents"
    )
    assert evidence["context7_upstream_sources"] == [
        "https://github.com/langchain-ai/deepagents/blob/main/README.md"
    ]


async def test_failures_are_repairable_and_credential_refusals_fatal(tmp_path: Path) -> None:
    web = tools_for(tmp_path, lambda _request: httpx.Response(404, json={"message": "nope"}))
    result = json.loads(
        await web.tools["github_repository"].ainvoke({"owner": "x", "repo": "missing"})
    )
    assert result["ok"] is False and result["recoverable"] is True
    assert "nope" not in json.dumps(result)
    refused = tools_for(tmp_path / "b", lambda _request: httpx.Response(401, json={}))
    with pytest.raises(WebToolRefused):
        await refused.worker.github_repository("x", "y")
    absent = tools_for(tmp_path / "c", lambda _request: httpx.Response(200), environment={})
    with pytest.raises(WebToolRefused):
        await absent.worker.context7_docs("/a/b", "topic")


async def test_operation_grant_narrows_sources_before_spending(tmp_path: Path) -> None:
    web = tools_for(tmp_path, lambda _request: pytest.fail("no vendor call expected"))
    with granted_network_hosts(frozenset({"arxiv.org"})), pytest.raises(WebToolRefused):
        await web.worker.github_repository("langchain-ai", "deepagents")
    assert web.worker.budget.calls == {}


def test_seeds_are_within_the_policy() -> None:
    from tests.fixtures.aieng_web_tools import AIENG_SOURCES

    for url in AIENG_SEEDS:
        assert AIENG_SOURCES.allowed_url(url) == url
