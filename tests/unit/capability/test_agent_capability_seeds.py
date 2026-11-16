"""FT-A6: seeded MCP servers, their tools, pins, secrets and per-application admission."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from mission_control.domain.authoring.contracts import (
    MCPServerDefinition,
    MCPToolDefinition,
    PluginDefinition,
    PublishedDefinition,
)
from mission_control.domain.capabilities.catalog_entry import capability_pin
from mission_control.domain.capabilities.host_support import HostSupportStatus, LaneProfile
from mission_control.domain.capabilities.pins import CapabilityPin
from mission_control_db_contract.seeds import load_bundles

ROOT = Path(__file__).resolve().parents[3]
SEEDS = ROOT / "packages" / "mission-control-db-contract" / "seeds"
FIXTURES = ROOT / "tests" / "fixtures" / "mcp"
COMMON_KEY = "mc.catalog.agent-capabilities"
# The servers seed 1.1.0 added (2026-11-16), each with a tool list captured from the server.
RESEARCH = ("mcp.github", "mcp.context7", "mcp.knowledge-capture")
# The tools each server exposes (its allowlist where it has one).
EXPECTED_TOOLS = {
    "mcp.tavily": 5,
    "mcp.firecrawl": 27,
    "mcp.agent-browser": 12,
    "mcp.pubmed": 11,
    "mcp.biomcp": 7,
    "mcp.edgartools": 13,
    "mcp.github": 22,
    "mcp.context7": 2,
    "mcp.knowledge-capture": 19,
}
ADMISSION = {
    "common": {"mcp.tavily", "mcp.firecrawl", "mcp.agent-browser", *RESEARCH},
    "biotech": {"mcp.pubmed", "mcp.biomcp"},
    "ai-engineer": {"mcp.edgartools"},
}


def _published(directory: str) -> list[PublishedDefinition]:
    out = []
    for bundle in load_bundles([SEEDS / directory]):
        if "agent-capabilities" not in bundle["seed_key"]:
            continue
        for record in bundle["records"]:
            if record["kind"] == "asset_version":
                out.append(PublishedDefinition.model_validate(record["fields"]["manifest"]))
    return out


def _servers(directory: str) -> dict[str, MCPServerDefinition]:
    return {
        item.definition.logical_id: item.definition
        for item in _published(directory)
        if isinstance(item.definition, MCPServerDefinition)
    }


@pytest.mark.parametrize("directory", ["common", "biotech", "ai-engineer"])
def test_admission_per_application(directory: str) -> None:
    assert set(_servers(directory)) == ADMISSION[directory]


def test_every_server_lists_its_tools_and_tool_rows() -> None:
    for directory in ADMISSION:
        published = _published(directory)
        servers = _servers(directory)
        tools = [i.definition for i in published if isinstance(i.definition, MCPToolDefinition)]
        for name, server in servers.items():
            exposed = {tool.name for tool in server.exposed_tools()}
            assert len(exposed) == EXPECTED_TOOLS[name], name
            children = {tool.tool_name for tool in tools if tool.server_ref.logical_id == name}
            assert children == exposed, name


def test_spec_details_per_server() -> None:
    common = _servers("common")
    tavily = common["mcp.tavily"]
    assert tavily.package_pin == "npm:tavily-mcp@0.2.22"
    assert "tavily_feedback" not in {tool.name for tool in tavily.tools}
    assert tavily.env_refs == {"TAVILY_API_KEY": "TAVILY_API_KEY"}
    cloud = tavily.host_support.overlay(LaneProfile.CURSOR_CLOUD)
    assert cloud["url"] == "https://mcp.tavily.com/mcp/" and "?" not in str(cloud["url"])
    firecrawl = common["mcp.firecrawl"]
    assert "firecrawl_extract" not in {tool.name for tool in firecrawl.exposed_tools()}
    assert firecrawl.env == {
        "FIRECRAWL_NO_SEARCH_FEEDBACK": "1",
        "FIRECRAWL_NO_ENDPOINT_FEEDBACK": "1",
    }
    browser = common["mcp.agent-browser"]
    assert browser.secret_refs == ()
    assert browser.host_support.status("cursor_cloud") is HostSupportStatus.UNQUALIFIED
    assert "agent-browser install" in browser.description
    biotech = _servers("biotech")
    pubmed = biotech["mcp.pubmed"]
    assert pubmed.package_pin == "npm:@cyanheads/pubmed-mcp-server@2.10.20"
    assert pubmed.env == {"MCP_TRANSPORT_TYPE": "stdio"}
    assert set(pubmed.secret_refs) == {"NCBI_API_KEY", "NCBI_ADMIN_EMAIL", "UNPAYWALL_EMAIL"}
    assert all(tool.read_only_hint for tool in biotech["mcp.biomcp"].tools)
    edgar = _servers("ai-engineer")["mcp.edgartools"]
    assert edgar.launch_template == ("uvx", "--from", "edgartools[ai]==5.61.1", "edgartools-mcp")
    assert edgar.secret_refs == ("EDGAR_IDENTITY",)


def test_research_capabilities_are_new_ids_after_the_frozen_first_version() -> None:
    by_version = {
        bundle["seed_version"]: bundle
        for bundle in load_bundles([SEEDS / "common"])
        if bundle["seed_key"] == COMMON_KEY
    }
    assert set(by_version) == {"1.0.0", "1.1.0"}
    successor = by_version["1.1.0"]
    assert successor["depends_on"] == [{"seed_key": COMMON_KEY, "seed_version": "1.0.0"}]
    held = {record["logical_key"] for record in by_version["1.0.0"]["records"]}
    assert not held & {record["logical_key"] for record in successor["records"]}
    assets = [r for r in successor["records"] if r["kind"] == "asset_version"]
    assert {r["fields"]["manifest"]["ref"]["revision"] for r in assets} == {1}
    assert {r["fields"]["manifest"]["published_at"] for r in assets} == {"2026-11-16T00:00:00Z"}


def test_research_servers_are_pinned_read_only_and_captured() -> None:
    common = _servers("common")
    github = common["mcp.github"]
    assert github.launch_template == (
        "github-mcp-server",
        "stdio",
        "--read-only",
        "--toolsets=repos,issues,pull_requests",
    )
    assert github.package_pin is not None
    assert github.package_pin.startswith("oci:ghcr.io/github/github-mcp-server@sha256:")
    assert github.source_provenance.source == "mcp_registry"
    assert github.source_provenance.upstream_identity == "io.github.github/github-mcp-server"
    assert github.source_provenance.upstream_version == "2.1.0"
    assert github.source_provenance.commit_digest == "4bcdcdf8d7beee98c9448e73e257308280924cc4"
    assert github.secret_refs == ("GITHUB_PERSONAL_ACCESS_TOKEN",)
    assert github.env_refs == {"GITHUB_PERSONAL_ACCESS_TOKEN": "GITHUB_PERSONAL_ACCESS_TOKEN"}
    # Read-only is the server's own mode: it lists no write tool, so no allowlist is needed.
    assert github.tool_allowlist is None
    assert all(tool.read_only_hint is True for tool in github.tools)
    assert {tool.side_effect_class for tool in github.tools} == {"read_only"}
    assert {
        "get_file_contents",
        "get_commit",
        "list_releases",
        "get_release_by_tag",
        "issue_read",
        "pull_request_read",
        "search_code",
    } <= {tool.name for tool in github.tools}
    assert github.host_support.supports("deep_agents")
    assert github.host_support.status("cursor_cloud") is HostSupportStatus.UNQUALIFIED
    assert github.host_support.overlay(LaneProfile.CURSOR_CLOUD) == {}
    context7 = common["mcp.context7"]
    assert context7.package_pin == "npm:@upstash/context7-mcp@4.7.0"
    assert context7.launch_template == ("npx", "-y", "@upstash/context7-mcp@4.7.0")
    assert context7.source_provenance.upstream_identity == "io.github.upstash/context7"
    assert {tool.name for tool in context7.tools} == {"resolve-library-id", "query-docs"}
    assert all(tool.read_only_hint is True for tool in context7.tools)
    assert context7.env_refs == {"CONTEXT7_API_KEY": "CONTEXT7_API_KEY"}
    cloud = context7.host_support.overlay(LaneProfile.CURSOR_CLOUD)
    assert cloud["url"] == "https://mcp.context7.com/mcp"
    assert cloud["header_refs"] == {"Authorization": "CONTEXT7_API_KEY"}
    for name in RESEARCH:
        document = json.loads((FIXTURES / f"{name}.tools.json").read_bytes())
        assert document["capture_method"] == "captured"
        assert document["capture"]["tool_count"] == len(document["tools"])
        assert document["capture"]["credential"].startswith("none")
    rows = [
        item.definition
        for item in _published("common")
        if isinstance(item.definition, MCPToolDefinition)
        and item.definition.server_ref.logical_id in RESEARCH
    ]
    assert len(rows) == sum(EXPECTED_TOOLS[name] for name in RESEARCH)
    assert {row.annotations["schema_source"] for row in rows} == {"captured"}
    # A captured row carries the server's own input schema, not the transcription placeholder.
    assert all(row.input_schema != {"type": "object"} for row in rows)


def test_the_capture_server_offers_no_knowledge_write_or_issuer_tool() -> None:
    capture = _servers("common")["mcp.knowledge-capture"]
    assert capture.transport == "streamable_http" and capture.launch_template is None
    assert capture.endpoint == "http://127.0.0.1:4310/mcp"
    assert capture.header_refs == {"Authorization": "VERIFY_EXECUTOR_TOKEN"}
    assert capture.secret_refs == ("VERIFY_EXECUTOR_TOKEN",)
    assert capture.source_provenance.source == "belllabs"
    assert capture.source_provenance.upstream_version == "0.1.0-7bc4aee"
    listed = {tool.name for tool in capture.tools}
    exposed = {tool.name for tool in capture.exposed_tools()}
    assert len(listed) == 40 and capture.allowed_tools == exposed
    assert {
        "knowledge_guide",
        "schema_search",
        "source_import",
        "source_select",
        "verify_capture_source",
        "verify_capture_file",
        "verify_read_capture",
        "verify_search_capture",
        "verify_locate_quote",
        "verify_register_artifact",
    } <= exposed
    # Writes of knowledge and every tool that needs an issuer credential stay on the governed
    # knowledge tools; host-side state and file tools are withheld with them.
    withheld = listed - exposed
    assert not [
        name
        for name in exposed
        if name.startswith(("ingest_", "knowledge_operation_", "db_", "checkpoint_"))
    ]
    assert {
        "ingest_apply",
        "knowledge_operation_invoke",
        "knowledge_receipt_get",
        "knowledge_describe",
        "db_sql_readonly",
        "db_read_intent",
        "checkpoint_commit",
        "artifact_get",
        "schema_materialize",
        "source_prepare_captured",
    } <= withheld
    # The executor lists every tool and no lane narrows a server's list to an allowlist, so
    # no lane may mount it yet: a manifest pin is refused at compile until one qualifies.
    assert capture.host_support.supported_profiles() == ()
    assert capture.host_support.status("deep_agents") is HostSupportStatus.UNQUALIFIED
    assert capture.host_support.status("cursor_cloud") is HostSupportStatus.UNSUPPORTED


def test_code_research_plugin_pins_its_members_exactly() -> None:
    published = {item.ref.logical_id: item for item in _published("common")}
    plugin = published["plugin.code-research"].definition
    assert isinstance(plugin, PluginDefinition)
    assert [member.pin for member in plugin.manifest.members] == [
        capability_pin(published["mcp.context7"]),
        capability_pin(published["mcp.github"]),
    ]
    assert not any(member.optional for member in plugin.manifest.members)
    assert plugin.secret_refs == ("CONTEXT7_API_KEY", "GITHUB_PERSONAL_ACCESS_TOKEN")
    assert set(plugin.host_support.supported_profiles()) == {
        LaneProfile.DEEP_AGENTS,
        LaneProfile.CURSOR_LOCAL,
        LaneProfile.CLAUDE_AGENT_SDK,
        LaneProfile.CODEX,
    }
    assert plugin.host_support.status("cursor_cloud") is HostSupportStatus.UNQUALIFIED
    (successor,) = [
        bundle
        for bundle in load_bundles([SEEDS / "common"])
        if (bundle["seed_key"], bundle["seed_version"]) == (COMMON_KEY, "1.1.0")
    ]
    members = [r["fields"] for r in successor["records"] if r["kind"] == "capability_plugin_member"]
    assert members == [
        {
            "plugin": "agent-capability:plugin:plugin.code-research/1",
            "member": f"agent-capability:mcp-server:{name}/1",
            "position": position,
            "role": "mcp_server",
            "optional": False,
        }
        for position, name in enumerate(("mcp.context7", "mcp.github"))
    ]


def test_no_author_hosted_or_key_in_url_endpoints() -> None:
    text = "".join(path.read_text(encoding="utf-8") for path in SEEDS.rglob("*agent-capabilities*"))
    for forbidden in ("caseyjhand", "tavilyApiKey=", "mcp.firecrawl.dev/fc-", "sec-edgar-mcp"):
        assert forbidden not in text


def test_pins_parse_and_tool_digests_match_fixtures() -> None:
    for directory in ADMISSION:
        for published in _published(directory):
            pin = capability_pin(published)
            assert CapabilityPin.parse(pin.render()) == pin
            definition = published.definition
            if isinstance(definition, MCPServerDefinition):
                document = json.loads(
                    (FIXTURES / f"{definition.logical_id}.tools.json").read_bytes()
                )
                encoded = json.dumps(
                    document["tools"], sort_keys=True, separators=(",", ":"), ensure_ascii=False
                ).encode()
                import hashlib

                assert (
                    definition.tools_list_digest == "sha256:" + hashlib.sha256(encoded).hexdigest()
                )
                assert pin.version == definition.source_provenance.upstream_version


def test_seeds_validate_script_passes() -> None:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "seeds_validate.py")],
        capture_output=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode()


def test_rejected_candidates_are_recorded() -> None:
    notes = (SEEDS / "AGENT_CAPABILITY_SEED_NOTES.md").read_text(encoding="utf-8")
    for candidate in (
        "sec-edgar-mcp",
        "pubmedmcp",
        "pubmed-mcp-server",
        "key-in-URL",
        # 2026-11-16: no arXiv server is seeded; the two self-hostable candidates are recorded.
        "arxiv-mcp-server",
        "@cyanheads/arxiv-mcp-server",
    ):
        assert candidate in notes
