"""Agent-capability seed definitions (FT-A6, SPEC-01 "Seeds"): MCP servers and their tools.

Imported by ``generate_catalog_seeds.py``. Every server is a published ``MCPServerDefinition``
(revision 1) with exact package pins, secret references by NAME only, the tool list from
``tests/fixtures/mcp/<id>.tools.json`` (``tools_list_digest`` = digest of that list) and a
``mc.capability_host_support.v1`` matrix; each tool is an ``MCPToolDefinition`` child row.
Admission per application is the bundle a server is in: common (both applications), biotech
or ai-engineer. Rejected candidates and their reasons are in AGENT_CAPABILITY_SEED_NOTES.md.

Versions: 1.0.0 is generated from :data:`SERVERS` (its common bundle is applied and frozen by
bytes in ``generate_catalog_seeds.FROZEN_BUNDLES``). 1.1.0 (2026-11-16, common) adds new ids
only, from :data:`RESEARCH_SERVERS` and :data:`CODE_RESEARCH_PLUGIN`: ``mcp.github`` and
``mcp.context7`` with tool lists captured from the servers run locally at an exact version,
``mcp.knowledge-capture`` (the Knowledge Services executor's capture, source, schema and guide
tools over Streamable HTTP, captured from a running executor) and ``plugin.code-research``
over the first two. Every binding traces to the dated provider note :data:`RESEARCH_NOTE`.
1.1.0 is frozen by bytes too. 1.2.0 (2026-11-16, common) publishes revision 2 of
``mcp.knowledge-capture`` and of its allowlisted tool rows from :data:`CAPTURE_SERVER`: the
same server and allowlist, supported on the ``deep_agents`` lane.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "mcp"
AGENT_SEED_TIME = datetime(2026, 10, 7, tzinfo=UTC)
COMMON_KEY = "mc.catalog.agent-capabilities"
APP_KEYS = {
    "biotech": "mc.app.biotech.agent-capabilities",
    "ai-engineer": "mc.app.ai-engineer.agent-capabilities",
}
SEED_VERSION = "1.0.0"

PROFILES = ("deep_agents", "cursor_local", "cursor_cloud", "claude_agent_sdk", "codex")


def _support(
    *,
    unqualified: tuple[str, ...] = (),
    unsupported: tuple[str, ...] = (),
    overlays: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    profiles: dict[str, Any] = {}
    for profile in PROFILES:
        entry: dict[str, Any] = {
            "status": "unsupported"
            if profile in unsupported
            else "unqualified"
            if profile in unqualified
            else "supported",
        }
        if overlays and profile in overlays:
            entry["overlay"] = overlays[profile]
        profiles[profile] = entry
    return {"schema_version": "mc.capability_host_support.v1", "profiles": profiles}


def _remote(url: str, secret: str) -> dict[str, Any]:
    return {"transport": "streamable_http", "url": url, "header_refs": {"Authorization": secret}}


_SELF_HOSTED = {"transport": "streamable_http", "url_ref": "MCP_SELF_HOSTED_URL"}

SERVERS: tuple[dict[str, Any], ...] = (
    {
        "id": "mcp.tavily",
        "bundle": "common",
        "title": "Tavily web search, extract, crawl, map and research",
        "description": (
            "Tavily MCP: web search, page extraction, crawl, site map and multi-source research. "
            "Keyless mode supports search and extract only. Cloud lanes use the remote endpoint "
            "with an Authorization header carrying the key reference (never the key-in-URL form)."
        ),
        "upstream": ("tavily-mcp", "0.2.22", "https://github.com/tavily-ai/tavily-mcp", "MIT"),
        "package_pin": "npm:tavily-mcp@0.2.22",
        "launch": ["npx", "-y", "tavily-mcp@0.2.22"],
        "secret_refs": ["TAVILY_API_KEY"],
        "env_refs": {"TAVILY_API_KEY": "TAVILY_API_KEY"},
        "host_support": _support(
            overlays={"cursor_cloud": _remote("https://mcp.tavily.com/mcp/", "TAVILY_API_KEY")}
        ),
        "tags": ["web", "search", "research", "extract", "crawl"],
    },
    {
        "id": "mcp.firecrawl",
        "bundle": "common",
        "title": "Firecrawl scrape, search, crawl, parse, research papers and monitors",
        "description": (
            "Firecrawl MCP: scrape pages to markdown or JSON, web and developer and government "
            "search, crawl and map sites, parse documents, research paper index (PubMed, bioRxiv, "
            "medRxiv, arXiv), agent research and change monitors. firecrawl_extract is deprecated "
            "and excluded by the tool allowlist; feedback tools are disabled by environment."
        ),
        "upstream": (
            "firecrawl-mcp",
            "3.28.2",
            "https://github.com/firecrawl/firecrawl-mcp-server",
            "MIT",
        ),
        "package_pin": "npm:firecrawl-mcp@3.28.2",
        "launch": ["npx", "-y", "firecrawl-mcp@3.28.2"],
        "env": {"FIRECRAWL_NO_SEARCH_FEEDBACK": "1", "FIRECRAWL_NO_ENDPOINT_FEEDBACK": "1"},
        "secret_refs": ["FIRECRAWL_API_KEY"],
        "env_refs": {"FIRECRAWL_API_KEY": "FIRECRAWL_API_KEY"},
        "exclude_tools": ["firecrawl_extract"],
        "host_support": _support(
            overlays={
                "cursor_cloud": _remote("https://mcp.firecrawl.dev/v2/mcp", "FIRECRAWL_API_KEY")
            }
        ),
        "tags": ["web", "scrape", "search", "crawl", "papers", "research", "parse"],
    },
    {
        "id": "mcp.agent-browser",
        "bundle": "common",
        "title": "agent-browser real browser automation (core tool profile)",
        "description": (
            "Vercel agent-browser MCP server (agent-browser mcp --tools core): open pages, "
            "accessibility snapshots with element refs, click, fill, type, press, wait, "
            "screenshot and evaluate. No secrets. Environment Profile requirement: run "
            "`agent-browser install` (Chrome for Testing) before first use. cursor_cloud is "
            "unqualified."
        ),
        "upstream": (
            "agent-browser",
            "0.38.2",
            "https://github.com/vercel-labs/agent-browser",
            "Apache-2.0",
        ),
        "package_pin": "npm:agent-browser@0.38.2",
        "launch": ["agent-browser", "mcp", "--tools", "core"],
        "secret_refs": [],
        "env_refs": {},
        "host_support": _support(unqualified=("cursor_cloud",)),
        "tags": ["browser", "automation", "web", "testing", "ui"],
    },
    {
        "id": "mcp.pubmed",
        "bundle": "biotech",
        "title": "PubMed literature search, fetch, full text, citations and MeSH",
        "description": (
            "cyanheads PubMed MCP server: PubMed and Europe PMC literature retrieval, article "
            "metadata and full text, citation formatting, related articles, spell check, MeSH "
            "lookup and identifier conversion (biomedical literature). Requires Node >= 24 or "
            "Bun >= 1.4. NCBI allows 3 requests/s without NCBI_API_KEY, 10 with it. Cloud lanes "
            "need a self-hosted Streamable HTTP endpoint; the author's public endpoint is never "
            "referenced."
        ),
        "upstream": (
            "@cyanheads/pubmed-mcp-server",
            "2.10.20",
            "https://github.com/cyanheads/pubmed-mcp-server",
            "Apache-2.0",
        ),
        "package_pin": "npm:@cyanheads/pubmed-mcp-server@2.10.20",
        "launch": ["npx", "-y", "@cyanheads/pubmed-mcp-server@2.10.20"],
        "env": {"MCP_TRANSPORT_TYPE": "stdio"},
        "secret_refs": ["NCBI_API_KEY", "NCBI_ADMIN_EMAIL", "UNPAYWALL_EMAIL"],
        "env_refs": {
            "NCBI_API_KEY": "NCBI_API_KEY",
            "NCBI_ADMIN_EMAIL": "NCBI_ADMIN_EMAIL",
            "UNPAYWALL_EMAIL": "UNPAYWALL_EMAIL",
        },
        "host_support": _support(
            unqualified=("cursor_cloud",), overlays={"cursor_cloud": _SELF_HOSTED}
        ),
        "tags": ["pubmed", "literature", "biomedical", "papers", "citations", "mesh"],
    },
    {
        "id": "mcp.biomcp",
        "bundle": "biotech",
        "title": "BioMCP biomedical search across literature, trials, variants and genes",
        "description": (
            "GenomOncology BioMCP (biomcp serve): seven read-only tools pivoting across "
            "literature (PubMed, PubTator3, Europe PMC), clinical trials, variants (ClinVar, "
            "ClinGen) and genes. Optional secret refs: NCBI_API_KEY, S2_API_KEY, "
            "OPENFDA_API_KEY, NCI_API_KEY, ONCOKB_TOKEN, ALPHAGENOME_API_KEY, DISGENET_API_KEY. "
            "Cloud lanes need biomcp serve-http self-hosted."
        ),
        "upstream": ("biomcp-cli", "0.9.1", "https://github.com/genomoncology/biomcp", "MIT"),
        "package_pin": "pypi:biomcp-cli==0.9.1",
        "launch": ["biomcp", "serve"],
        "secret_refs": [
            "NCBI_API_KEY",
            "S2_API_KEY",
            "OPENFDA_API_KEY",
            "NCI_API_KEY",
            "ONCOKB_TOKEN",
            "ALPHAGENOME_API_KEY",
            "DISGENET_API_KEY",
        ],
        "env_refs": {},
        "host_support": _support(
            unqualified=("cursor_cloud",), overlays={"cursor_cloud": _SELF_HOSTED}
        ),
        "tags": ["biomedical", "variants", "genes", "clinical-trials", "literature"],
    },
    {
        "id": "mcp.edgartools",
        "bundle": "ai-engineer",
        "title": "edgartools SEC EDGAR filings, financials and ownership",
        "description": (
            "edgartools MCP server (uvx --from edgartools[ai]==5.61.1 edgartools-mcp): SEC "
            "EDGAR company profiles, filings, full-text search, XBRL financial trends, insider "
            "and institutional ownership, funds and proxy compensation (sec filings). SEC "
            "requires a declared identity (EDGAR_IDENTITY) and allows 10 requests/s. Cloud lanes "
            "need the streamable-http transport self-hosted."
        ),
        "upstream": ("edgartools", "5.61.1", "https://github.com/dgunning/edgartools", "MIT"),
        "package_pin": "pypi:edgartools[ai]==5.61.1",
        "launch": ["uvx", "--from", "edgartools[ai]==5.61.1", "edgartools-mcp"],
        "secret_refs": ["EDGAR_IDENTITY"],
        "env_refs": {"EDGAR_IDENTITY": "EDGAR_IDENTITY"},
        "host_support": _support(
            unqualified=("cursor_cloud",), overlays={"cursor_cloud": _SELF_HOSTED}
        ),
        "tags": ["sec", "edgar", "filings", "financials", "ownership"],
    },
)

# --- Seed 1.1.0 (2026-11-16): research capabilities -----------------------------------------
# New capability ids only. Identity, version, transport, authentication, read-only
# configuration and each tool list are evidenced in RESEARCH_NOTE; nothing here is inferred.
RESEARCH_SEED_VERSION = "1.1.0"
RESEARCH_SEED_TIME = datetime(2026, 11, 16, tzinfo=UTC)
RESEARCH_NOTE = (
    "docs/specs/provider-consolidation-2026-10/providers/research-capabilities/"
    "RESEARCH-CAPABILITIES-SURFACE-2026-11-16.md"
)
_MCP_REGISTRY = "https://registry.modelcontextprotocol.io/v0/servers"
_KNOWLEDGE_SERVICES = "https://github.com/jbell-rusty-vantage/agent-knowledge-services"
_KNOWLEDGE_SERVICES_COMMIT = "7bc4aeec77c645f41bb0f550f6a9626c3ef24cf0"
_WORKER_PROFILES = ("deep_agents", "cursor_local", "claude_agent_sdk", "codex")

RESEARCH_SERVERS: tuple[dict[str, Any], ...] = (
    {
        "id": "mcp.github",
        "title": "GitHub read-only: files at a commit, releases, issues, pull requests, search",
        "description": (
            "GitHub's official MCP server in read-only mode with the repos, issues and "
            "pull_requests toolsets (github-mcp-server stdio --read-only "
            "--toolsets=repos,issues,pull_requests): file contents at a ref or commit, "
            "commits, branches, tags and releases, issue and pull request reads, and code, "
            "commit, issue, pull request and repository search. The server lists no write tool "
            "in this configuration. GITHUB_PERSONAL_ACCESS_TOKEN names a read-only token. "
            "cursor_cloud is unqualified: the remote endpoint selects these toolsets and "
            "read-only mode through the X-MCP-Toolsets and X-MCP-Readonly request headers, "
            "which a host overlay cannot carry."
        ),
        "upstream": (
            "io.github.github/github-mcp-server",
            "2.1.0",
            f"{_MCP_REGISTRY}/io.github.github%2Fgithub-mcp-server/versions/2.1.0",
            "MIT",
        ),
        "provenance_source": "mcp_registry",
        "commit_digest": "4bcdcdf8d7beee98c9448e73e257308280924cc4",
        "package_pin": (
            "oci:ghcr.io/github/github-mcp-server@"
            "sha256:f6056fc10bfffcc8c81a6417a2e9ca12808647e8dd6049642a4feaadee0e0f8a"
        ),
        "launch": [
            "github-mcp-server",
            "stdio",
            "--read-only",
            "--toolsets=repos,issues,pull_requests",
        ],
        "secret_refs": ["GITHUB_PERSONAL_ACCESS_TOKEN"],
        "env_refs": {"GITHUB_PERSONAL_ACCESS_TOKEN": "GITHUB_PERSONAL_ACCESS_TOKEN"},
        "host_support": _support(unqualified=("cursor_cloud",)),
    },
    {
        "id": "mcp.context7",
        "title": "Context7 library documentation lookup (a secondary mirror)",
        "description": (
            "Context7 MCP: resolve a library name to a Context7 library id, then query that "
            "library's documentation and code examples. A secondary mirror of upstream "
            "documentation: use it to find which upstream page or file states something, then "
            "read the upstream at a pinned release. Both tools are read-only. "
            "CONTEXT7_API_KEY is optional upstream (higher rate limits, private repositories). "
            "cursor_cloud is unqualified: its overlay names the remote endpoint with an "
            "Authorization header carrying the key reference, whose tool list was not captured."
        ),
        "upstream": (
            "io.github.upstash/context7",
            "4.7.0",
            f"{_MCP_REGISTRY}/io.github.upstash%2Fcontext7/versions/4.7.0",
            "MIT",
        ),
        "provenance_source": "mcp_registry",
        "package_pin": "npm:@upstash/context7-mcp@4.7.0",
        "launch": ["npx", "-y", "@upstash/context7-mcp@4.7.0"],
        "secret_refs": ["CONTEXT7_API_KEY"],
        "env_refs": {"CONTEXT7_API_KEY": "CONTEXT7_API_KEY"},
        "host_support": _support(
            unqualified=("cursor_cloud",),
            overlays={"cursor_cloud": _remote("https://mcp.context7.com/mcp", "CONTEXT7_API_KEY")},
        ),
    },
    {
        "id": "mcp.knowledge-capture",
        "title": "Knowledge Services evidence capture: capture, locate, source and schema tools",
        "description": (
            "The Knowledge Services executor's MCP endpoint (Streamable HTTP, /mcp) narrowed to "
            "evidence work: capture a URL or a file as exact bytes, read and search a capture, "
            "locate a quote that occurs once, export a fragment, register and read artifacts, "
            "record source discovery and lead selection, read the schema workspace and the "
            "guidance. The allowlist leaves out every tool that writes knowledge or needs an "
            "issuer credential (ingest_*, knowledge_operation_*, knowledge_receipt_get, "
            "knowledge_describe, db_*, checkpoint_*, artifact_get, schema_materialize, "
            "source_prepare_captured). The endpoint is the executor's local default; a "
            "deployment binds its own. VERIFY_EXECUTOR_TOKEN names the token the executor "
            "expects on the Authorization header. Unqualified on every worker-hosted lane: the "
            "executor lists all of its tools and no lane narrows a server's tool list to this "
            "allowlist yet."
        ),
        "transport": "streamable_http",
        "endpoint": "http://127.0.0.1:4310/mcp",
        "header_refs": {"Authorization": "VERIFY_EXECUTOR_TOKEN"},
        "upstream": (
            "knowledge-services/verification-executor",
            "0.1.0-7bc4aee",
            f"{_KNOWLEDGE_SERVICES}/tree/{_KNOWLEDGE_SERVICES_COMMIT}/apps/verification-executor",
            "proprietary",
        ),
        "provenance_source": "belllabs",
        "commit_digest": _KNOWLEDGE_SERVICES_COMMIT,
        "package_pin": (
            f"git:{_KNOWLEDGE_SERVICES}@{_KNOWLEDGE_SERVICES_COMMIT}#apps/verification-executor"
        ),
        "secret_refs": ["VERIFY_EXECUTOR_TOKEN"],
        "env_refs": {},
        "allow_tools": [
            "knowledge_guide",
            "schema_get",
            "schema_manifest",
            "schema_search",
            "source_attempt",
            "source_discover",
            "source_import",
            "source_reconcile",
            "source_select",
            "verify_capture_file",
            "verify_capture_fragment",
            "verify_capture_source",
            "verify_get_artifact",
            "verify_list_captures",
            "verify_locate_quote",
            "verify_read_capture",
            "verify_register_artifact",
            "verify_search_capture",
            "verify_supported_media_types",
        ],
        "host_support": _support(unqualified=_WORKER_PROFILES, unsupported=("cursor_cloud",)),
    },
)
# One pin for a question about a library or a repository: Context7 for a first look, then
# GitHub for the file at the release's commit (the order the research method routes them).
CODE_RESEARCH_PLUGIN: dict[str, Any] = {
    "id": "plugin.code-research",
    "title": "Code research plugin (Context7, GitHub read-only)",
    "description": (
        "Composition of exact pins for questions about a library or a repository: Context7 "
        "for a first look at a library's documentation and the upstream file it names, and "
        "GitHub's official server in read-only mode for the file at a release's commit, "
        "releases, issues, pull requests and code search. No install command or marketplace "
        "reference."
    ),
    "members": ("mcp.context7", "mcp.github"),
}

# --- Seed 1.2.0 (2026-11-16): the capture server on the Deep Agents lane -------------------
# Revision 2 of `mcp.knowledge-capture` only: the same server, endpoint, authentication and
# 19-tool allowlist, now `supported` on `deep_agents`. Two changes made that true (the note's
# IP-009 and IP-008): the Deep Agents materializer attaches only the bound tools of a server
# bound with an allowlist tool filter, and a worker's pin file can describe a remote
# Streamable HTTP server. The other worker-hosted lanes stay `unqualified` (no proof that
# their host projection narrows this server's list) and cursor_cloud `unsupported`.
# `mcp.github` and `mcp.context7` stay at revision 1: their rows already declare the worker
# lanes supported, and the pin file now describes both forms (an executable, a node module).
CAPTURE_SEED_VERSION = "1.2.0"
CAPTURE_REVISION = 2
CAPTURE_SERVER: dict[str, Any] = {
    **next(spec for spec in RESEARCH_SERVERS if spec["id"] == "mcp.knowledge-capture"),
    "description": (
        "The Knowledge Services executor's MCP endpoint (Streamable HTTP, /mcp) narrowed to "
        "evidence work: capture a URL or a file as exact bytes, read and search a capture, "
        "locate a quote that occurs once, export a fragment, register and read artifacts, "
        "record source discovery and lead selection, read the schema workspace and the "
        "guidance. The allowlist leaves out every tool that writes knowledge or needs an "
        "issuer credential (ingest_*, knowledge_operation_*, knowledge_receipt_get, "
        "knowledge_describe, db_*, checkpoint_*, artifact_get, schema_materialize, "
        "source_prepare_captured). The endpoint is the executor's local default; a "
        "deployment binds its own (MCP_SERVER_ENDPOINTS). VERIFY_EXECUTOR_TOKEN names the "
        "token the executor expects on the Authorization header. Supported on the Deep "
        "Agents lane: the executor lists all of its tools, and the lane attaches only this "
        "allowlist, refusing a missing tool or a changed input schema. Unqualified on the "
        "other worker-hosted lanes, where narrowing this server's list is not proven."
    ),
    "host_support": _support(
        unqualified=("cursor_local", "claude_agent_sdk", "codex"), unsupported=("cursor_cloud",)
    ),
}


def served_research_specs() -> dict[str, dict[str, Any]]:
    """``capability_id -> spec`` of each research server at its newest seeded revision: the
    rows a worker's pin file is written from (``scripts/pin_research_capabilities.py``)."""

    specs = {spec["id"]: spec for spec in RESEARCH_SERVERS}
    specs[CAPTURE_SERVER["id"]] = CAPTURE_SERVER
    return specs


def _lf(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def tools_list_digest(tools: list[dict[str, Any]]) -> str:
    """Digest of the canonical ``tools`` list (sorted keys, compact) of a tools fixture."""
    encoded = json.dumps(tools, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return _sha256(encoded.encode("utf-8"))


def fixture(server_id: str) -> tuple[dict[str, Any], bytes]:
    path = FIXTURES / f"{server_id}.tools.json"
    payload = _lf(path)
    return json.loads(payload), payload


def server_definition(spec: dict[str, Any]) -> Any:
    from mission_control.domain.authoring.contracts import MCPServerDefinition

    document, payload = fixture(spec["id"])
    tools = document["tools"]
    names = [tool["name"] for tool in tools]
    excluded = set(spec.get("exclude_tools", ()))
    if "allow_tools" in spec:
        # An explicit allowlist: everything else the server lists is excluded.
        unknown = sorted(set(spec["allow_tools"]) - set(names))
        if unknown:
            raise ValueError(f"{spec['id']} allows tools its server does not list: {unknown}")
        excluded = set(names) - set(spec["allow_tools"])
    package, version, locator, license_name = spec["upstream"]
    # A remote server has an endpoint and header references in place of a launch template.
    transport = spec.get("transport", "stdio")
    recipe: dict[str, Any] = (
        {"launch_template": spec["launch"]}
        if transport == "stdio"
        else {"endpoint": spec["endpoint"], "header_refs": spec.get("header_refs", {})}
    )
    provenance: dict[str, Any] = (
        {"commit_digest": spec["commit_digest"]} if "commit_digest" in spec else {}
    )
    return MCPServerDefinition.model_validate(
        {
            "logical_id": spec["id"],
            "title": spec["title"],
            "description": spec["description"],
            "transport": transport,
            **recipe,
            "allowed_tools": [name for name in names if name not in excluded],
            "schema_snapshot_ref": {
                "uri": f"repo://tests/fixtures/mcp/{spec['id']}.tools.json",
                "digest": _sha256(payload),
                "media_type": "application/json",
                "size_bytes": len(payload),
            },
            "schema_digest": tools_list_digest(tools),
            "source_provenance": {
                "source": spec.get("provenance_source", "git"),
                "locator": locator,
                "upstream_identity": package,
                "upstream_version": version,
                "license": license_name,
                **provenance,
            },
            "review_status": "approved",
            "maturity": "experimental",
            "host_support": spec["host_support"],
            "secret_refs": spec["secret_refs"],
            "env": spec.get("env", {}),
            "env_refs": spec["env_refs"],
            "package_pin": spec["package_pin"],
            "tools": [
                {
                    "name": tool["name"],
                    "description": tool["description"],
                    "side_effect_class": tool["side_effect_class"],
                    "read_only_hint": tool["read_only_hint"],
                }
                for tool in tools
            ],
            "tools_list_digest": tools_list_digest(tools),
            "tool_allowlist": sorted(name for name in names if name not in excluded)
            if excluded
            else None,
        }
    )


def tool_definitions(server: Any, server_ref: Any) -> list[Any]:
    from mission_control.domain.authoring.contracts import MCPToolDefinition

    document, _ = fixture(server.logical_id)
    definitions = []
    for tool in document["tools"]:
        if server.tool_allowlist is not None and tool["name"] not in server.tool_allowlist:
            continue
        slug = tool["name"].replace("_", "-").lower()
        definitions.append(
            MCPToolDefinition.model_validate(
                {
                    "logical_id": f"{server.logical_id}.tool.{slug}",
                    "title": tool["name"],
                    "description": tool["description"] or tool["name"],
                    "server_ref": server_ref.model_dump(mode="json"),
                    "tool_name": tool["name"],
                    "input_schema": tool["input_schema"],
                    "annotations": {
                        "readOnlyHint": tool["read_only_hint"],
                        "schema_source": document["capture_method"],
                    },
                    "schema_digest": tools_list_digest([tool]),
                    "side_effect_class": tool["side_effect_class"],
                    "maturity": "experimental",
                }
            )
        )
    return definitions


def bundles(published_records: Any, seed_format: str, compatibility: str, actor: str) -> dict:
    """Seed bundles: common (both applications) plus one per application."""
    from mission_control.domain.authoring.canonical import sha256_digest
    from mission_control.domain.authoring.contracts import DefinitionKind, ExactDefinitionRef

    grouped: dict[str, list[dict[str, Any]]] = {"common": [], "biotech": [], "ai-engineer": []}
    for spec in SERVERS:
        server = server_definition(spec)
        evidence = [
            "packages/mission-control-db-contract/seeds/agent_capabilities.py",
            f"tests/fixtures/mcp/{spec['id']}.tools.json",
            "docs/specs/fast-track-2026-10/research/seed-capabilities-and-formats.md",
        ]
        records = published_records(server, "agent-capability", evidence)
        server_ref = ExactDefinitionRef(
            kind=DefinitionKind.MCP_SERVER,
            logical_id=server.logical_id,
            revision=1,
            digest=sha256_digest(server),
        )
        for tool in tool_definitions(server, server_ref):
            records += published_records(tool, "agent-capability", evidence)
        grouped[spec["bundle"]] += records
    common = {
        "format": seed_format,
        "seed_key": COMMON_KEY,
        "seed_version": SEED_VERSION,
        "component_compatibility": compatibility,
        "depends_on": [{"seed_key": "mc.catalog.approved-assets", "seed_version": "1.0.0"}],
        "actor_ref": actor,
        "description": (
            "Agent-capability MCP servers admitted in every application (FT-A6): Tavily, "
            "Firecrawl and agent-browser, each a published MCP Server definition with exact "
            "package pins, secret reference NAMES only, host_support and one MCP Tool row per "
            "tool. Requires migration 0025 (agent-composition kinds). Tool lists are "
            "transcribed fixtures (capture_method=transcribed) until re-captured live."
        ),
        "records": grouped["common"],
    }
    result = {f"common/{COMMON_KEY}-{SEED_VERSION}.json": common}
    for app, key in APP_KEYS.items():
        names = ", ".join(spec["id"] for spec in SERVERS if spec["bundle"] == app)
        result[f"{app}/{key}-{SEED_VERSION}.json"] = {
            "format": seed_format,
            "seed_key": key,
            "seed_version": SEED_VERSION,
            "component_compatibility": compatibility,
            "depends_on": [{"seed_key": COMMON_KEY, "seed_version": SEED_VERSION}],
            "actor_ref": actor,
            "description": (
                f"Agent-capability MCP servers admitted only in '{app}' (FT-A6): {names}. "
                "Secret reference NAMES only; requires migration 0025."
            ),
            "records": grouped[app],
        }
    result[f"common/{COMMON_KEY}-{RESEARCH_SEED_VERSION}.json"] = research_bundle(
        published_records, seed_format, compatibility, actor
    )
    result[f"common/{COMMON_KEY}-{CAPTURE_SEED_VERSION}.json"] = capture_bundle(
        published_records, seed_format, compatibility, actor
    )
    return result


def capture_server_ref() -> Any:
    """The exact ref of ``mcp.knowledge-capture`` revision 2 (seed 1.2.0)."""
    from mission_control.domain.authoring.canonical import sha256_digest
    from mission_control.domain.authoring.contracts import DefinitionKind, ExactDefinitionRef

    server = server_definition(CAPTURE_SERVER)
    return ExactDefinitionRef(
        kind=DefinitionKind.MCP_SERVER,
        logical_id=server.logical_id,
        revision=CAPTURE_REVISION,
        digest=sha256_digest(server),
    )


def capture_pin() -> str:
    """The Capability Pin of ``mcp.knowledge-capture`` revision 2."""

    return f"{CAPTURE_SERVER['id']}@{CAPTURE_SERVER['upstream'][1]}#{capture_server_ref().digest}"


def capture_bundle(
    published_records: Any, seed_format: str, compatibility: str, actor: str
) -> dict[str, Any]:
    """Seed 1.2.0 (common): revision 2 of ``mcp.knowledge-capture`` and of its 19 allowlisted
    MCP Tool rows (each names the server revision it belongs to). No earlier record is
    repeated: revision 1 stays admitted, and ``@latest`` resolves to revision 2."""

    server = server_definition(CAPTURE_SERVER)
    evidence = [
        "packages/mission-control-db-contract/seeds/agent_capabilities.py",
        f"tests/fixtures/mcp/{CAPTURE_SERVER['id']}.tools.json",
        RESEARCH_NOTE,
    ]
    records: list[dict[str, Any]] = published_records(
        server, "agent-capability", evidence, RESEARCH_SEED_TIME, revision=CAPTURE_REVISION
    )
    for tool in tool_definitions(server, capture_server_ref()):
        records += published_records(
            tool, "agent-capability", evidence, RESEARCH_SEED_TIME, revision=CAPTURE_REVISION
        )
    for record in records:
        if record["kind"] == "asset_decision":
            record["fields"]["decided_at"] = "2026-11-16T00:00:00Z"
    return {
        "format": seed_format,
        "seed_key": COMMON_KEY,
        "seed_version": CAPTURE_SEED_VERSION,
        "component_compatibility": compatibility,
        "depends_on": [{"seed_key": COMMON_KEY, "seed_version": RESEARCH_SEED_VERSION}],
        "actor_ref": actor,
        "description": (
            f"Revision {CAPTURE_REVISION} of {CAPTURE_SERVER['id']} and of its "
            f"{len(CAPTURE_SERVER['allow_tools'])} allowlisted MCP Tool rows: the same "
            "server, endpoint, authentication and allowlist as revision 1, now supported on "
            "the deep_agents lane, which attaches only the allowlisted tools of a server that "
            "lists more and whose workers can pin a remote Streamable HTTP server. The other "
            "worker-hosted lanes stay unqualified and cursor_cloud unsupported. mcp.github, "
            "mcp.context7 and plugin.code-research are unchanged at revision 1. No "
            f"{RESEARCH_SEED_VERSION} record is repeated."
        ),
        "records": records,
    }


def research_pins() -> dict[str, str]:
    """``capability_id -> Capability Pin`` of every server seed 1.1.0 publishes."""
    from mission_control.domain.authoring.canonical import sha256_digest

    return {
        spec["id"]: f"{spec['id']}@{spec['upstream'][1]}#{sha256_digest(server_definition(spec))}"
        for spec in RESEARCH_SERVERS
    }


def code_research_plugin() -> Any:
    """``plugin.code-research``: exact pins of its member servers. Its host support is what
    every member supports and its secret references are the members' own."""
    from mission_control.domain.authoring.contracts import PluginDefinition
    from mission_control.domain.capabilities.host_support import CapabilityHostSupport
    from mission_control.domain.capabilities.plugins import PluginManifest

    pins = research_pins()
    specs = {spec["id"]: spec for spec in RESEARCH_SERVERS}
    members = CODE_RESEARCH_PLUGIN["members"]
    manifest = PluginManifest.model_validate(
        {"members": [{"pin": pins[member], "role": "mcp_server"} for member in members]}
    )
    return PluginDefinition.model_validate(
        {
            "logical_id": CODE_RESEARCH_PLUGIN["id"],
            "title": CODE_RESEARCH_PLUGIN["title"],
            "description": CODE_RESEARCH_PLUGIN["description"],
            "manifest": manifest.model_dump(mode="json"),
            "host_support": manifest.host_support(
                lambda pin: CapabilityHostSupport.model_validate(
                    specs[pin.capability_id]["host_support"]
                )
            ).model_dump(mode="json"),
            "secret_refs": sorted(
                {ref for member in members for ref in specs[member]["secret_refs"]}
            ),
        }
    )


def research_bundle(
    published_records: Any, seed_format: str, compatibility: str, actor: str
) -> dict[str, Any]:
    """Seed 1.1.0 (common): the research servers, one MCP Tool row per allowlisted tool, and
    ``plugin.code-research`` with its member rows. It holds no 1.0.0 logical key."""
    from mission_control.domain.authoring.canonical import sha256_digest
    from mission_control.domain.authoring.contracts import DefinitionKind, ExactDefinitionRef

    records: list[dict[str, Any]] = []
    for spec in RESEARCH_SERVERS:
        server = server_definition(spec)
        evidence = [
            "packages/mission-control-db-contract/seeds/agent_capabilities.py",
            f"tests/fixtures/mcp/{spec['id']}.tools.json",
            RESEARCH_NOTE,
        ]
        records += published_records(server, "agent-capability", evidence, RESEARCH_SEED_TIME)
        server_ref = ExactDefinitionRef(
            kind=DefinitionKind.MCP_SERVER,
            logical_id=server.logical_id,
            revision=1,
            digest=sha256_digest(server),
        )
        for tool in tool_definitions(server, server_ref):
            records += published_records(tool, "agent-capability", evidence, RESEARCH_SEED_TIME)
    plugin = code_research_plugin()
    plugin_key = f"agent-capability:plugin:{plugin.logical_id}/1"
    records += published_records(
        plugin,
        "agent-capability",
        ["packages/mission-control-db-contract/seeds/agent_capabilities.py", RESEARCH_NOTE],
        RESEARCH_SEED_TIME,
    )
    for position, member in enumerate(plugin.manifest.members):
        records.append(
            {
                "kind": "capability_plugin_member",
                "logical_key": f"{plugin_key}:member:{position}",
                "fields": {
                    "plugin": plugin_key,
                    "member": f"agent-capability:mcp-server:{member.pin.capability_id}/1",
                    "position": position,
                    "role": member.role.value,
                    "optional": member.optional,
                },
            }
        )
    for record in records:
        if record["kind"] == "asset_decision":
            record["fields"]["decided_at"] = "2026-11-16T00:00:00Z"
    names = ", ".join(spec["id"] for spec in RESEARCH_SERVERS)
    return {
        "format": seed_format,
        "seed_key": COMMON_KEY,
        "seed_version": RESEARCH_SEED_VERSION,
        "component_compatibility": compatibility,
        "depends_on": [{"seed_key": COMMON_KEY, "seed_version": SEED_VERSION}],
        "actor_ref": actor,
        "description": (
            f"Research capabilities admitted in every application (new ids only): {names} and "
            f"{CODE_RESEARCH_PLUGIN['id']} over the first two. Each server is a published MCP "
            "Server definition with an exact source pin, secret reference NAMES only, "
            "host_support and one MCP Tool row per allowlisted tool; the tool lists are "
            "captured fixtures (capture_method=captured), the GitHub and Context7 ones from "
            "the servers run locally at the pinned version without a credential and the "
            "capture server's from a running Knowledge Services executor. No "
            f"{SEED_VERSION} record is repeated."
        ),
        "records": records,
    }


def seed_pins() -> dict[str, str]:
    """``capability_id -> Capability Pin`` for every seeded server (upstream version, digest)."""
    from mission_control.domain.authoring.canonical import sha256_digest

    pins = {}
    for spec in SERVERS:
        server = server_definition(spec)
        pins[spec["id"]] = f"{spec['id']}@{spec['upstream'][1]}#{sha256_digest(server)}"
    return pins
