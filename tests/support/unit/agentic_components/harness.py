"""Builders, constants and fakes that other test files import.

Moved from tests/unit/agentic_components/test_harness.py.
"""

from __future__ import annotations

from mission_control.domain.agentic_components.contracts import (
    AgentHost,
    AgenticComponentRelease,
    Architecture,
    ComponentCoordinate,
    ComponentDescription,
    ComponentKind,
    HostCompatibility,
    MCPRuntimeBinding,
    OperatingSystem,
    ReadinessProbe,
    SecretEnvironmentBinding,
    SourcePin,
    TrustStage,
)
from mission_control.domain.authoring.contracts import DefinitionKind, ExactDefinitionRef

DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64


DIGEST_D = "sha256:" + "d" * 64


def compatibility(host: AgentHost) -> HostCompatibility:
    config_paths = {
        AgentHost.CURSOR: ".cursor/mcp.json",
        AgentHost.CODEX: ".codex/config.toml",
        AgentHost.CLAUDE_CODE: ".mcp.json",
        AgentHost.AGENT_FRAMEWORK: "agent-framework.json",
    }
    return HostCompatibility(
        host=host,
        adapter_version="1",
        operating_systems=frozenset({OperatingSystem.LINUX, OperatingSystem.WINDOWS}),
        architectures=frozenset({Architecture.AMD64}),
        project_config_path=config_paths[host],
    )


def source(digest: str) -> SourcePin:
    return SourcePin(
        registry="mcp_official",
        locator="https://registry.modelcontextprotocol.io/v0.1/servers/example",
        upstream_identity="io.example/server",
        upstream_version="1.2.3",
        source_digest=digest,
        evidence_ref="evidence:registry:example",
    )


def mcp_release(
    *,
    digest: str = DIGEST_A,
    trust_stage: TrustStage = TrustStage.QUALIFIED,
) -> AgenticComponentRelease:
    return AgenticComponentRelease(
        coordinate=ComponentCoordinate(
            component_id="mcp.io.example.server",
            version="1.2.3",
            digest=digest,
        ),
        kind=ComponentKind.MCP_SERVER,
        description=ComponentDescription(
            title="Biomedical literature server",
            summary="Search reviewed biomedical literature sources.",
            capabilities=frozenset({"literature.search", "paper.retrieve"}),
            tags=frozenset({"biomedical", "research"}),
            biotech_domains=frozenset({"longevity"}),
        ),
        definition_ref=ExactDefinitionRef(
            kind=DefinitionKind.MCP_SERVER,
            logical_id="mcp.io.example.server",
            revision=3,
            digest=DIGEST_D,
        ),
        source=source(digest),
        compatibility=(
            compatibility(AgentHost.CURSOR),
            compatibility(AgentHost.CODEX),
            compatibility(AgentHost.CLAUDE_CODE),
        ),
        trust_stage=trust_stage,
        mcp=MCPRuntimeBinding(
            server_name="biomedical",
            transport="stdio",
            command="npx",
            arguments=("--yes", "@example/biomedical-mcp@1.2.3"),
            secret_environment=(
                SecretEnvironmentBinding(
                    environment_name="LITERATURE_API_KEY",
                    secret_ref="vault:biotech/literature-api-key",
                ),
            ),
            allowed_tools=frozenset({"search_papers", "get_paper"}),
            schema_digest=DIGEST_B,
            readiness_probe=ReadinessProbe(
                kind="mcp_initialize_and_list_tools",
                timeout_seconds=20,
                expected_schema_digest=DIGEST_B,
            ),
        ),
    )
