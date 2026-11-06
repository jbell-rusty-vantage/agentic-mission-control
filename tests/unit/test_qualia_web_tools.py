from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from mission_control.adapters.capabilities.browser_subprocess import BrowserSubprocessResult
from mission_control.adapters.deep_agents.browser_tool import (
    GRANTED_NETWORK_HOSTS,
    granted_network_hosts,
)
from mission_control.adapters.deep_agents.knowledge_tools import CURRENT_INVOCATION
from mission_control.application.knowledge.toolset import LiveInvocation
from mission_control.domain.authoring.canonical import sha256_digest
from tests.fixtures.qualia_web_tools import (
    ALLOWED_HOSTS,
    SEED_URLS,
    WebCallBudget,
    WebToolRefused,
    allowed_url,
    build_qualia_web_tools,
)


@pytest.fixture(autouse=True)
def fixture_operation_network_grants():
    """Explicit offline fixture grant, never installed by the worker helper."""
    with granted_network_hosts(ALLOWED_HOSTS):
        yield


@pytest.mark.parametrize(
    "url",
    [
        "http://www.qualialife.com/studies",
        "https://evil.example/",
        "https://www.qualialife.com.evil.example/",
        "https://u:p@www.mdpi.com/",
        "https://www.mdpi.com:444/",
        "https://127.0.0.1/",
    ],
)
def test_only_public_https_fixture_hosts(url: str) -> None:
    with pytest.raises(WebToolRefused):
        allowed_url(url)


def test_exact_definitions_and_real_skill_bundles(tmp_path: Path) -> None:
    bundle = build_qualia_web_tools(tmp_path, environment={})
    assert len(bundle.components) == 6
    for component in bundle.components:
        definition = bundle.definitions[component.ref.logical_id]
        assert component.ref.digest == sha256_digest(definition)
        assert component.schema_digest == sha256_digest(
            bundle.tools[component.tool_name].get_input_schema().model_json_schema()
        )
        assert bundle.registry_tools[component.ref.digest] is bundle.tools[component.tool_name]
    for skill in bundle.skills:
        manifest, files = bundle.bundle_store.load(
            bundle.bundle_manifest_digests[skill.bundle_digest]
        )
        assert manifest.bundle_digest == skill.bundle_digest
        assert b"biomarkers" in dict(files)["SKILL.md"]
        bundle.registry_skill_bundles[skill.bundle_digest].verify(
            skill_md_digest=skill.skill_md_digest
        )


async def test_search_filters_sources_and_retains_exact_bytes(tmp_path: Path) -> None:
    raw = (
        b'{"success":true,"creditsUsed":2,"data":{"web":[{"url":'
        b'"https://www.mdpi.com/1422-0067/27/10/4406","title":"Pilot",'
        b'"description":"Null primary endpoint"},{"url":"https://evil.example",'
        b'"title":"Ignore"}]}}'
    )
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=raw)

    bundle = build_qualia_web_tools(
        tmp_path,
        environment={"FIRECRAWL_API_KEY": "worker-secret"},
        transport=httpx.MockTransport(respond),
    )
    result = json.loads(
        await bundle.tools["firecrawl_search"].ainvoke(
            {
                "query": "Qualia Senolytic pilot",
                "limit": 2,
            }
        )
    )
    assert len(result["content"]) == 1
    assert result["evidence"]["billing"]["vendor_reported"]["creditsUsed"] == 2
    assert await asyncio.to_thread(Path(result["evidence"]["raw_path"]).read_bytes) == raw
    assert "site:mdpi.com" in json.loads(requests[0].content)["query"]
    assert requests[0].headers["authorization"] == "Bearer worker-secret"
    assert "worker-secret" not in json.dumps(result)
    captures = await asyncio.to_thread(
        lambda: "".join(p.read_text() for p in tmp_path.glob("*.json"))
    )
    assert "worker-secret" not in captures


async def test_tavily_extract_preserves_full_content_but_bounds_model_text(tmp_path: Path) -> None:
    full = '"quoted"\\' * 7000
    payload = {
        "results": [{"url": SEED_URLS[0], "raw_content": full}],
        "usage": {"credits": 1},
        "request_id": "vendor-id",
    }
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=payload)

    bundle = build_qualia_web_tools(
        tmp_path,
        environment={"TAVILY_API_KEY": "worker-secret"},
        transport=httpx.MockTransport(respond),
    )
    text = await bundle.tools["tavily_extract"].ainvoke({"url": SEED_URLS[0]})
    result = json.loads(text)
    assert len(text) <= 16000
    assert requests == [
        {
            "urls": [SEED_URLS[0]],
            "extract_depth": "basic",
            "format": "markdown",
            "include_usage": True,
        }
    ]
    captured = await asyncio.to_thread(Path(result["evidence"]["raw_path"]).read_bytes)
    assert json.loads(captured) == payload
    assert result["model_excerpt_truncated"] is True


async def test_invalid_query_and_url_never_spend(tmp_path: Path) -> None:
    bundle = build_qualia_web_tools(tmp_path, environment={"FIRECRAWL_API_KEY": "key"})
    with pytest.raises(ValidationError):
        await bundle.tools["firecrawl_search"].ainvoke({"query": "x" * 401})
    with pytest.raises(ValidationError):
        await bundle.tools["firecrawl_search"].ainvoke({"query": "Qualia", "limit": 4})
    with pytest.raises(WebToolRefused):
        await bundle.tools["firecrawl_scrape"].ainvoke({"url": "https://evil.example/"})
    assert bundle.worker.budget.calls == {}


async def test_budget_refuses_retries_and_does_not_expose_vendor_errors(tmp_path: Path) -> None:
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(429, json={"error": "private vendor details"})

    bundle = build_qualia_web_tools(
        tmp_path,
        environment={"TAVILY_API_KEY": "key"},
        budget=WebCallBudget(max_calls=1),
        transport=httpx.MockTransport(respond),
    )
    error = json.loads(await bundle.tools["tavily_search"].ainvoke({"query": "Qualia"}))
    assert error["recoverable"] is True
    assert error["error"]["code"] == "vendor_http_429"
    assert "private vendor details" not in json.dumps(error)
    with pytest.raises(WebToolRefused, match="budget exhausted"):
        await bundle.tools["tavily_search"].ainvoke({"query": "Qualia"})
    assert len(requests) == 1


@pytest.mark.parametrize("url", SEED_URLS[2:])
async def test_tavily_publisher_extract_uses_one_advanced_request(tmp_path: Path, url: str) -> None:
    requests = []
    raw = json.dumps(
        {
            "results": [{"url": url, "raw_content": "Exact primary study outcomes."}],
            "failed_results": [],
            "usage": {"credits": 1},
        }
    ).encode()

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, content=raw)

    bundle = build_qualia_web_tools(
        tmp_path,
        environment={"TAVILY_API_KEY": "worker-secret"},
        transport=httpx.MockTransport(respond),
    )
    result = json.loads(await bundle.tools["tavily_extract"].ainvoke({"url": url}))
    assert len(requests) == 1
    assert requests[0]["extract_depth"] == "advanced"
    record = result["evidence"]
    assert record["source_usable"] is True and record["complete"] is True
    assert record["request_options"]["extract_depth"] == "advanced"
    assert await asyncio.to_thread(Path(record["raw_path"]).read_bytes) == raw
    assert bundle.worker.budget.calls == {"tavily_extract": 1}
    read = json.loads(
        await bundle.tools["source_read"].ainvoke({"capture_id": record["capture_id"]})
    )
    assert read["content"] == "Exact primary study outcomes."
    assert read["source_document_sha256"] == (
        "sha256:" + hashlib.sha256(b"Exact primary study outcomes.").hexdigest()
    )


@pytest.mark.parametrize("failure", ["unavailable", "missing_text", "wrong_url", "invalid_json"])
async def test_tavily_failed_source_returns_repair_feedback_and_cannot_be_cited(
    tmp_path: Path, failure: str
) -> None:
    url = SEED_URLS[2]
    payload = {
        "results": [],
        "failed_results": [{"url": url, "error": "Failed to fetch url"}],
        "usage": {"credits": 0},
    }
    expected = "source_unavailable"
    if failure == "missing_text":
        payload["results"] = [{"url": url, "raw_content": " "}]
        expected = "source_text_missing"
    elif failure == "wrong_url":
        payload["results"] = [{"url": SEED_URLS[3], "raw_content": "Different study"}]
        expected = "source_identity_mismatch"
    elif failure == "invalid_json":
        expected = "invalid_vendor_response"
    raw = (
        b"not JSON private vendor details"
        if failure == "invalid_json"
        else json.dumps(payload).encode()
    )
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=raw)

    bundle = build_qualia_web_tools(
        tmp_path,
        environment={"TAVILY_API_KEY": "worker-secret"},
        transport=httpx.MockTransport(respond),
    )
    result = json.loads(await bundle.tools["tavily_extract"].ainvoke({"url": url}))
    assert result["recoverable"] is True and result["ok"] is False
    assert result["error"]["code"] == expected
    assert result["content"] == []
    assert "private vendor details" not in json.dumps(result)
    record = result["evidence"]
    assert record["complete"] is True and record["source_usable"] is False
    assert await asyncio.to_thread(Path(record["raw_path"]).read_bytes) == raw
    assert record["billing"]["reservation_usd"] == 0.25
    if failure != "invalid_json":
        assert record["billing"]["vendor_reported"]["usage"]["credits"] == 0
    with pytest.raises(WebToolRefused, match="integrity"):
        await bundle.tools["source_read"].ainvoke({"capture_id": record["capture_id"]})
    assert len(requests) == 1


@pytest.mark.parametrize("query", ["site:mdpi.com", "(site:mdpi.com OR site:medrxiv.org)"])
async def test_tavily_site_only_query_has_actionable_feedback_without_spending(
    tmp_path: Path, query: str
) -> None:
    def unexpected(_request: httpx.Request) -> httpx.Response:
        pytest.fail("Site-only query must be repaired before contacting the vendor")

    bundle = build_qualia_web_tools(
        tmp_path,
        environment={"TAVILY_API_KEY": "key"},
        transport=httpx.MockTransport(unexpected),
    )
    result = json.loads(await bundle.tools["tavily_search"].ainvoke({"query": query}))
    assert result["error"]["code"] == "query_terms_required"
    assert result["evidence"] is None
    assert bundle.worker.budget.calls == {}


@pytest.mark.parametrize("status", [400, 429, 500])
async def test_tavily_vendor_http_failure_is_repairable_without_hidden_retries(
    tmp_path: Path, status: int
) -> None:
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status, json={"detail": {"error": "private vendor details"}})

    bundle = build_qualia_web_tools(
        tmp_path,
        environment={"TAVILY_API_KEY": "key"},
        transport=httpx.MockTransport(respond),
    )
    result = json.loads(await bundle.tools["tavily_search"].ainvoke({"query": "Qualia study"}))
    assert result["error"]["code"] == f"vendor_http_{status}"
    assert result["recoverable"] is True
    assert "private vendor details" not in json.dumps(result)
    assert result["evidence"]["http_status"] == status
    assert len(requests) == 1


@pytest.mark.parametrize("status", [401, 402, 403])
async def test_tavily_auth_and_account_refusals_stay_fatal(tmp_path: Path, status: int) -> None:
    bundle = build_qualia_web_tools(
        tmp_path,
        environment={"TAVILY_API_KEY": "key"},
        transport=httpx.MockTransport(lambda _request: httpx.Response(status, json={})),
    )
    with pytest.raises(WebToolRefused, match=f"HTTP {status}"):
        await bundle.tools["tavily_search"].ainvoke({"query": "Qualia study"})
    assert bundle.worker.budget.calls == {"tavily_search": 1}


async def test_tavily_transport_failure_is_retained_without_private_exception(
    tmp_path: Path,
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("private worker-secret", request=request)

    bundle = build_qualia_web_tools(
        tmp_path,
        environment={"TAVILY_API_KEY": "worker-secret"},
        transport=httpx.MockTransport(respond),
    )
    result = json.loads(await bundle.tools["tavily_extract"].ainvoke({"url": SEED_URLS[2]}))
    assert result["error"]["code"] == "vendor_transport"
    assert result["evidence"]["complete"] is False
    assert result["evidence"]["source_usable"] is False
    assert "worker-secret" not in json.dumps(result)
    assert bundle.worker.budget.calls == {"tavily_extract": 1}


async def test_browser_uses_existing_governed_cli_and_records_commands(tmp_path: Path) -> None:
    node, entrypoint = tmp_path / "node", tmp_path / "agent-browser.js"
    node.touch()
    entrypoint.touch()
    requests = []

    class Runner:
        async def run(self, request):
            requests.append(request)
            args = request.arguments
            value = SEED_URLS[0] if "url" in args else "page content"
            return BrowserSubprocessResult(0, json.dumps({"data": value}).encode(), b"")

    bundle = build_qualia_web_tools(
        tmp_path / "evidence",
        environment={"FIRECRAWL_API_KEY": "private"},
        node_executable=node,
        browser_entrypoint=entrypoint,
        browser_runner=Runner(),
    )

    async def resolver(_host):
        return ("8.8.8.8",)

    bundle.worker.browser._resolver = resolver
    with granted_network_hosts(ALLOWED_HOSTS):
        result = json.loads(await bundle.tools["agent_browser_page"].ainvoke({"url": SEED_URLS[0]}))
    assert len(requests) == 5  # open, final URL, title, text, close
    assert all("--allowed-domains" in request.arguments for request in requests)
    assert all("FIRECRAWL_API_KEY" not in request.environment for request in requests)
    assert await asyncio.to_thread(Path(result["evidence"]["raw_path"]).is_file)
    with granted_network_hosts(frozenset()):
        with pytest.raises(RuntimeError, match="granted network hosts"):
            await bundle.tools["agent_browser_page"].ainvoke({"url": SEED_URLS[0]})
    assert len(requests) == 5


async def test_shared_budget_reopens_and_retains_failed_call_reservation(tmp_path: Path) -> None:
    ledger = tmp_path / "mission-web.jsonl"
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(429, json={"success": False, "creditsUsed": 3})

    def build(attempt: str):
        return build_qualia_web_tools(
            tmp_path / attempt,
            environment={"FIRECRAWL_API_KEY": "key"},
            transport=httpx.MockTransport(respond),
            budget=WebCallBudget(max_calls=2, max_reserved_usd=0.50, ledger_path=ledger),
        )

    first = build("attempt-one")
    with pytest.raises(WebToolRefused, match="HTTP 429"):
        await first.tools["firecrawl_search"].ainvoke({"query": "Qualia study"})
    second = build("attempt-two")
    assert second.worker.budget.calls == {"firecrawl_search": 1}
    assert second.worker.budget.reserved_usd == 0.25
    with pytest.raises(WebToolRefused, match="HTTP 429"):
        await second.tools["firecrawl_search"].ainvoke({"query": "Qualia study"})
    third = build("attempt-three")
    with pytest.raises(WebToolRefused, match="budget exhausted"):
        await third.tools["firecrawl_search"].ainvoke({"query": "Qualia study"})
    assert len(calls) == 2
    assert third.worker.budget.reserved_usd == 0.50
    rows = await asyncio.to_thread(
        lambda: [json.loads(line) for line in ledger.read_text().splitlines()]
    )
    assert len(rows) == 2
    assert all(row["reserved_usd"] == "0.25" for row in rows)
    metadata = await asyncio.to_thread(
        lambda: json.loads(next((tmp_path / "attempt-one").glob("*.json")).read_text())
    )
    assert metadata["billing"]["vendor_reported"]["creditsUsed"] == 3
    assert metadata["billing"]["actual_usd"] is None
    assert metadata["billing"]["reservation_usd"] == 0.25


async def test_shared_budget_serializes_multiple_worker_instances(tmp_path: Path) -> None:
    ledger = tmp_path / "mission-web.jsonl"
    workers = [WebCallBudget(max_calls=3, ledger_path=ledger) for _ in range(8)]
    results = await asyncio.gather(
        *(worker.admit("firecrawl_scrape") for worker in workers),
        return_exceptions=True,
    )
    assert sum(result is None for result in results) == 3
    assert sum(isinstance(result, WebToolRefused) for result in results) == 5
    reopened = await asyncio.to_thread(WebCallBudget, max_calls=3, ledger_path=ledger)
    assert reopened.calls == {"firecrawl_scrape": 3}
    assert reopened.reserved_usd == 0.75


@pytest.mark.parametrize("damage", [b"", b'{"partial":', b"{}\n"])
def test_shared_budget_corruption_fails_closed(tmp_path: Path, damage: bytes) -> None:
    ledger = tmp_path / "mission-web.jsonl"
    ledger.write_bytes(damage)
    with pytest.raises(WebToolRefused, match="ledger is corrupt"):
        WebCallBudget(ledger_path=ledger)


async def test_shared_budget_rejects_tampering_and_limit_changes(tmp_path: Path) -> None:
    ledger = tmp_path / "mission-web.jsonl"
    budget = WebCallBudget(ledger_path=ledger)
    await budget.admit("tavily_extract")
    with pytest.raises(WebToolRefused, match="limits changed"):
        await asyncio.to_thread(WebCallBudget, max_calls=21, ledger_path=ledger)
    raw = await asyncio.to_thread(ledger.read_bytes)
    await asyncio.to_thread(ledger.write_bytes, raw.replace(b'"sequence": 1', b'"sequence": 2'))
    with pytest.raises(WebToolRefused, match="ledger is corrupt"):
        await budget.admit("tavily_extract")


async def test_explicit_per_tool_amendment_preserves_spend_and_global_ceiling(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "mission-web.jsonl"
    first = WebCallBudget(
        max_calls=5, max_calls_per_tool=2, max_reserved_usd=1.25, ledger_path=ledger
    )
    await first.admit("firecrawl_scrape")
    await first.admit("firecrawl_scrape")
    original = ledger.read_bytes()
    with pytest.raises(WebToolRefused, match="limits changed"):
        WebCallBudget(max_calls=5, max_calls_per_tool=4, max_reserved_usd=1.25, ledger_path=ledger)
    amended = WebCallBudget(
        max_calls=5,
        max_calls_per_tool=4,
        prior_max_calls_per_tool=2,
        max_reserved_usd=1.25,
        ledger_path=ledger,
    )
    await amended.admit("firecrawl_scrape")
    await amended.admit("firecrawl_scrape")
    with pytest.raises(WebToolRefused, match="budget exhausted"):
        await amended.admit("firecrawl_scrape")
    await amended.admit("tavily_extract")
    with pytest.raises(WebToolRefused, match="budget exhausted"):
        await amended.admit("tavily_extract")
    assert ledger.read_bytes().startswith(original)
    assert amended.calls == {"firecrawl_scrape": 4, "tavily_extract": 1}
    assert amended.reserved_usd == 1.25
    with pytest.raises(WebToolRefused, match="limits changed"):
        WebCallBudget(
            max_calls=6,
            max_calls_per_tool=4,
            prior_max_calls_per_tool=2,
            max_reserved_usd=1.50,
            ledger_path=ledger,
        )
    with pytest.raises(WebToolRefused, match="limits changed"):
        WebCallBudget(max_calls=5, max_calls_per_tool=2, max_reserved_usd=1.25, ledger_path=ledger)


async def test_explicit_shared_allowance_amendment_retains_all_prior_policies(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "mission-web.jsonl"
    first = WebCallBudget(
        max_calls=2, max_calls_per_tool=1, max_reserved_usd=0.50, ledger_path=ledger
    )
    await first.admit("firecrawl_scrape")
    second = WebCallBudget(
        max_calls=2,
        max_calls_per_tool=2,
        prior_max_calls_per_tool=1,
        max_reserved_usd=0.50,
        ledger_path=ledger,
    )
    await second.admit("firecrawl_scrape")
    original = ledger.read_bytes()
    history = (first._limits(), second._limits())
    amended = WebCallBudget(
        max_calls=4,
        max_calls_per_tool=3,
        max_reserved_usd=1,
        prior_limit_policies=history,
        ledger_path=ledger,
    )
    assert amended.reserved_usd == 0.50
    await amended.admit("firecrawl_scrape")
    await amended.admit("tavily_extract")
    assert ledger.read_bytes().startswith(original)
    assert amended.reserved_usd == 1
    with pytest.raises(WebToolRefused, match="budget exhausted"):
        await amended.admit("tavily_extract")
    with pytest.raises(WebToolRefused, match="limits changed"):
        await second.admit("tavily_extract")
    with pytest.raises(ValueError, match="monotonically"):
        WebCallBudget(
            max_calls=4,
            max_calls_per_tool=3,
            max_reserved_usd=1,
            prior_limit_policies=history[::-1],
            ledger_path=ledger,
        )


async def test_source_reader_reaches_late_results_without_another_vendor_call(
    tmp_path: Path,
) -> None:
    text = "Introduction. " * 3000 + "Primary outcomes: no significant change.\nFunding: Qualia."
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "markdown": text,
                    "metadata": {"sourceURL": SEED_URLS[2]},
                },
            },
        )

    bundle = build_qualia_web_tools(
        tmp_path,
        environment={"FIRECRAWL_API_KEY": "key"},
        transport=httpx.MockTransport(respond),
    )
    capture = json.loads(await bundle.tools["firecrawl_scrape"].ainvoke({"url": SEED_URLS[2]}))
    result = json.loads(
        await bundle.tools["source_read"].ainvoke(
            {
                "capture_id": capture["evidence"]["capture_id"],
                "find": "Primary outcomes",
                "max_chars": 40,
            }
        )
    )
    assert result["offset_chars"] == text.index("Primary outcomes")
    assert result["content"] == text[result["offset_chars"] : result["end_offset_chars"]]
    assert result["next_offset_chars"] == result["end_offset_chars"]
    assert result["evidence"]["raw_sha256"] == capture["evidence"]["raw_sha256"]
    assert result["total_chars"] == len(text)
    assert len(requests) == 1
    assert bundle.worker.budget.calls == {"firecrawl_scrape": 1}
    # A new worker can still read captures already registered under the private directory.
    reopened = build_qualia_web_tools(tmp_path, environment={})
    page = json.loads(
        await reopened.tools["source_read"].ainvoke(
            {
                "capture_id": capture["evidence"]["capture_id"],
                "offset_chars": result["next_offset_chars"],
            }
        )
    )
    assert page["content"] == text[result["next_offset_chars"] :]
    missing = json.loads(
        await reopened.tools["source_read"].ainvoke(
            {
                "capture_id": capture["evidence"]["capture_id"],
                "find": "phrase absent from paper",
            }
        )
    )
    assert missing["match_offset_chars"] == -1
    assert missing["content"] == ""


async def test_source_reader_refuses_arbitrary_paths_and_tampered_bytes(tmp_path: Path) -> None:
    bundle = build_qualia_web_tools(tmp_path, environment={})
    for args in ({"capture_id": "../../secrets"}, {"capture_id": "a" * 32, "max_chars": 12001}):
        with pytest.raises(ValidationError):
            await bundle.tools["source_read"].ainvoke(args)
    with pytest.raises(WebToolRefused, match="missing"):
        await bundle.tools["source_read"].ainvoke({"capture_id": "a" * 32})
    record = bundle.worker.evidence.save(
        "firecrawl_scrape",
        b'{"data":{"markdown":"Study"}}',
        {
            "complete": True,
            "requested_url": SEED_URLS[2],
            "http_status": 200,
        },
    )
    await asyncio.to_thread(Path(record["raw_path"]).write_bytes, b"tampered")
    with pytest.raises(WebToolRefused, match="integrity"):
        await bundle.tools["source_read"].ainvoke({"capture_id": record["capture_id"]})


async def test_source_reader_bounds_escaped_json_without_changing_offsets(tmp_path: Path) -> None:
    bundle = build_qualia_web_tools(tmp_path, environment={})
    text = '"\\' * 15000
    record = bundle.worker.evidence.save(
        "firecrawl_scrape",
        json.dumps({"data": {"markdown": text}}).encode(),
        {"complete": True, "requested_url": SEED_URLS[2], "http_status": 200},
    )
    rendered = await bundle.tools["source_read"].ainvoke(
        {
            "capture_id": record["capture_id"],
            "offset_chars": 17,
            "max_chars": 12000,
        }
    )
    result = json.loads(rendered)
    assert len(rendered) <= 16000
    assert result["offset_chars"] == 17
    assert 17 < result["next_offset_chars"] < 12017
    assert result["content"] == text[17 : result["next_offset_chars"]]
    assert result["model_excerpt_truncated"] is True


async def test_actual_operation_grants_gate_every_vendor_tool_before_spend(tmp_path: Path) -> None:
    bundle = build_qualia_web_tools(
        tmp_path,
        environment={"FIRECRAWL_API_KEY": "key", "TAVILY_API_KEY": "key"},
    )
    token = GRANTED_NETWORK_HOSTS.set(None)
    try:
        for name, args in (
            ("firecrawl_search", {"query": "Qualia"}),
            ("tavily_search", {"query": "Qualia"}),
            ("firecrawl_scrape", {"url": SEED_URLS[0]}),
            ("tavily_extract", {"url": SEED_URLS[0]}),
        ):
            with pytest.raises(WebToolRefused, match="network grant"):
                await bundle.tools[name].ainvoke(args)
    finally:
        GRANTED_NETWORK_HOSTS.reset(token)
    with granted_network_hosts(frozenset({"www.mdpi.com"})):
        with pytest.raises(WebToolRefused, match="granted network hosts"):
            await bundle.tools["firecrawl_scrape"].ainvoke({"url": SEED_URLS[0]})
    assert bundle.worker.budget.calls == {}


async def test_search_scope_and_capture_provenance_follow_current_invocation(
    tmp_path: Path,
) -> None:
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "success": True,
                "results": [
                    {"url": SEED_URLS[2], "content": "Granted MDPI source"},
                    {"url": SEED_URLS[0], "content": "Allowed globally but ungranted now"},
                ],
            },
        )

    bundle = build_qualia_web_tools(
        tmp_path,
        environment={"TAVILY_API_KEY": "key"},
        transport=httpx.MockTransport(respond),
    )
    live = LiveInvocation(
        request_scope="offline-scope",
        run_id="derived-run",
        operation_id="discover",
        operation_attempt=2,
        execution_generation=3,
        lane="deep_agents",
        position="discover",
    )
    token = CURRENT_INVOCATION.set(live)
    try:
        with granted_network_hosts(frozenset({"www.mdpi.com"})):
            result = json.loads(await bundle.tools["tavily_search"].ainvoke({"query": "Qualia"}))
        threaded = await asyncio.to_thread(
            bundle.worker.evidence.save,
            "threaded-test",
            b"actual bytes",
            {},
        )
    finally:
        CURRENT_INVOCATION.reset(token)
    assert requests[0]["include_domains"] == ["www.mdpi.com"]
    assert [item["url"] for item in result["content"]] == [SEED_URLS[2]]
    assert result["evidence"]["invocation"]["run_id"] == "derived-run"
    assert threaded["invocation"]["operation_attempt"] == 2
    assert threaded["invocation"]["execution_generation"] == 3


def test_retained_skill_custody_keeps_exact_refs_with_fresh_capture_directory(tmp_path):
    origin = tmp_path / "source"
    initial = build_qualia_web_tools(origin, environment={})
    original_bytes = {
        p.relative_to(origin): p.read_bytes() for p in origin.rglob("*") if p.is_file()
    }
    retry = build_qualia_web_tools(tmp_path / "retry", environment={}, skill_custody_root=origin)
    assert retry.worker.evidence.directory == (tmp_path / "retry").resolve()
    assert retry.skills == initial.skills
    for skill in retry.skills:
        assert retry.definitions[skill.ref.logical_id] == initial.definitions[skill.ref.logical_id]
        retry.registry_skill_bundles[skill.bundle_digest].verify(
            skill_md_digest=skill.skill_md_digest
        )
    assert original_bytes == {
        p.relative_to(origin): p.read_bytes() for p in origin.rglob("*") if p.is_file()
    }


def test_retained_skill_custody_refuses_changed_original_skill_bytes(tmp_path):
    origin = tmp_path / "source"
    build_qualia_web_tools(origin, environment={})
    source = origin / "skill-sources/qualia-firecrawl-research/SKILL.md"
    source.write_bytes(source.read_bytes() + b"tampered")
    with pytest.raises(WebToolRefused, match="Retained skill bytes"):
        build_qualia_web_tools(tmp_path / "retry", environment={}, skill_custody_root=origin)
