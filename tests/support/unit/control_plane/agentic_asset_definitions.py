"""Builders, constants and fakes that other test files import.

Moved from tests/unit/control_plane/test_agentic_asset_definitions.py.
"""

from __future__ import annotations

from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import (
    CatalogPayloadRef,
    ExactDefinitionRef,
    MCPNetworkRequirement,
    MCPServerDefinition,
    MCPToolDefinition,
    SkillCompatibility,
    SkillDefinition,
    SkillFileManifestEntry,
    SourceProvenance,
)

FAKE_DIGEST = "sha256:" + "1" * 64


def payload_ref(digest: str = FAKE_DIGEST) -> CatalogPayloadRef:
    return CatalogPayloadRef(
        uri=f"s3://belllabs-catalog/{digest.removeprefix('sha256:')}",
        digest=digest,
        media_type="application/octet-stream",
        size_bytes=12,
    )


def provenance(identity: str) -> SourceProvenance:
    return SourceProvenance(
        source="local",
        locator=f".agents/skills/{identity}",
        upstream_identity=identity,
        upstream_version="1",
        license="Apache-2.0",
    )


def skill_definition() -> SkillDefinition:
    manifest = (
        SkillFileManifestEntry(
            path="SKILL.md",
            digest="sha256:" + "2" * 64,
            size_bytes=100,
        ),
    )
    return SkillDefinition(
        logical_id="skill.firecrawl-search",
        title="Firecrawl Search",
        description="Reviewed procedure for current web search through Firecrawl.",
        skill_name="firecrawl-search",
        frontmatter={"name": "firecrawl-search", "description": "Search the web."},
        body_summary="Search current public web sources and preserve citations.",
        bundle_ref=payload_ref("sha256:" + "3" * 64),
        manifest_digest=sha256_digest(manifest),
        file_manifest=manifest,
        required_capabilities=frozenset({"web.search.firecrawl"}),
        compatibility=SkillCompatibility(
            runtimes=frozenset({"python-3.12"}),
            network_capabilities=frozenset({"network.public_web"}),
        ),
        source_provenance=provenance("firecrawl-search"),
        review_status="approved",
    )


def server_definition() -> MCPServerDefinition:
    snapshot_digest = "sha256:" + "4" * 64
    return MCPServerDefinition(
        logical_id="mcp.firecrawl",
        title="Firecrawl MCP",
        description="Reviewed Firecrawl MCP server recipe.",
        transport="streamable_http",
        endpoint="https://mcp.firecrawl.dev/mcp",
        allowed_tools=frozenset({"firecrawl_search", "firecrawl_scrape"}),
        approval_policy={"firecrawl_search": "never", "firecrawl_scrape": "never"},
        network_requirements=(
            MCPNetworkRequirement(host="mcp.firecrawl.dev", port=443, protocol="https"),
        ),
        schema_snapshot_ref=payload_ref(snapshot_digest),
        schema_digest=snapshot_digest,
        source_provenance=provenance("firecrawl-mcp"),
        review_status="approved",
    )


def tool_definition(server_ref: ExactDefinitionRef) -> MCPToolDefinition:
    schema = {
        "tool_name": "firecrawl_search",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        "output_schema": {"type": "object"},
        "annotations": {"readOnlyHint": True},
    }
    return MCPToolDefinition(
        logical_id="mcp.firecrawl.firecrawl-search",
        title="Firecrawl search",
        description="Search public web sources and return cited results.",
        server_ref=server_ref,
        tool_name="firecrawl_search",
        input_schema=schema["input_schema"],
        output_schema=schema["output_schema"],
        annotations=schema["annotations"],
        schema_digest=sha256_digest(schema),
        side_effect_class="read_only",
    )
