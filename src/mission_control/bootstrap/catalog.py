"""Installation-owned catalog composition; requests cannot select credentials or scope.

FT-A3 (ADR-0025): capability search is always composed. With an embedding route it runs
hybrid; without one it runs lexical-only, so the public API never answers 503 for a
missing route.
"""

from __future__ import annotations

import logging
import sys
import tempfile
from pathlib import Path
from typing import cast

import asyncpg

from mission_control.adapters.postgres.capability.capability_search_repository import (
    PostgresCatalogSearchRepository,
)
from mission_control.adapters.postgres.control_plane.definition_repository import (
    PostgresDefinitionRepository,
)
from mission_control.application.agentic_components.repository import AgenticComponentRepository
from mission_control.application.capabilities.capability_search import CapabilitySearchService
from mission_control.application.capabilities.capability_search_repository import (
    CapabilityEmbeddingPort,
)
from mission_control.application.capabilities.catalog import CatalogService
from mission_control.application.capabilities.external_candidate_inspection import (
    ExternalCandidateInspectionService,
)
from mission_control.application.capabilities.external_capability_discovery import (
    ExternalCapabilityDiscoveryService,
)
from mission_control.bootstrap.host_projection import HOST_PROJECTORS
from mission_control.bootstrap.settings import Settings

EMBEDDING_PROFILE = "embedding.openai.text-embedding-3-small"
_LOG = logging.getLogger(__name__)


def configured_catalog_embeddings(settings: Settings) -> CapabilityEmbeddingPort | None:
    """The OpenAI embedding route, only when configuration names its Model Profile.

    Requires ``capability_embedding_profile`` to name ``embedding.openai.text-embedding-3-small``
    and the credential reference to resolve; otherwise search stays lexical.
    """
    if settings.capability_embedding_profile != EMBEDDING_PROFILE:
        return None
    from mission_control.adapters.capabilities.capability_embeddings import (
        CapabilityEmbeddingDependencyError,
        OpenAICapabilityEmbeddingAdapter,
    )

    try:
        # The tracing decorator hides embed_many's signature from protocol checkers.
        return cast(CapabilityEmbeddingPort, OpenAICapabilityEmbeddingAdapter(settings))
    except CapabilityEmbeddingDependencyError:
        _LOG.warning("catalog embedding profile is configured but its credential is not")
        return None


def compose_external_discovery(
    settings: Settings, pool: asyncpg.Pool, *, catalog_scope: str
) -> tuple[ExternalCapabilityDiscoveryService | None, ExternalCandidateInspectionService | None]:
    """External capability discovery and candidate inspection for one catalog scope, composed
    only where the deployment enables them (`external_capability_discovery_enabled`; default
    off, so a process without the flag reaches no registry and starts no subprocess).

    Discovery searches the MCP registry over HTTPS and the Agent Skills index through a pinned
    `npx skills` subprocess, and records every result as a candidate: never as a capability.
    Inspection is the static, non-installing quarantine scan (no network, no `tools/list`
    probe); it needs the repository's scanner script and is left out where that is absent.
    Both subprocesses need an event loop that can start one."""

    if not settings.external_capability_discovery_enabled:
        return None, None
    from mission_control.adapters.capabilities.mcp_registry import (
        HttpxMCPRegistryRunner,
        MCPRegistryAdapter,
    )
    from mission_control.adapters.capabilities.npx_skills_discovery import (
        AsyncioSkillDiscoverySubprocessRunner,
        NpxSkillsDiscoveryAdapter,
    )
    from mission_control.adapters.capabilities.quarantine_inspection import (
        AsyncioQuarantineSubprocessRunner,
        SanitizedCandidateMetadataPayloadProvider,
        StaticQuarantineInspectionRunner,
    )
    from mission_control.adapters.postgres.capability.external_candidates import (
        PostgresExternalCandidateInspectionRepository,
        PostgresExternalCandidateRepository,
    )
    from mission_control.application.capabilities.external_candidate_inspection import (
        InspectionBounds,
    )
    from mission_control.bootstrap.settings import PROJECT_ROOT

    workspace = Path(tempfile.gettempdir()) / "mission-control" / "external-discovery"
    candidates = PostgresExternalCandidateRepository(pool, catalog_scope=catalog_scope)
    discovery = ExternalCapabilityDiscoveryService(
        enabled=True,
        mcp_registry=MCPRegistryAdapter(
            HttpxMCPRegistryRunner(),
            base_url=settings.mcp_registry_base_url,
            api_version=settings.mcp_registry_api_version,
            timeout_seconds=settings.external_discovery_request_timeout_seconds,
            max_response_bytes=settings.external_discovery_max_output_bytes,
            max_pages=settings.external_discovery_max_pages,
            max_retries=settings.external_discovery_max_retries,
        ),
        skills=NpxSkillsDiscoveryAdapter(
            AsyncioSkillDiscoverySubprocessRunner(),
            executable=settings.npx_skills_executable,
            package_version=settings.npx_skills_package_version,
            timeout_seconds=settings.external_discovery_command_timeout_seconds,
            max_output_bytes=settings.external_discovery_max_output_bytes,
            working_directory_root=workspace / "npx",
        ),
        candidates=candidates,
        max_results=settings.external_discovery_max_results,
    )
    # The scanner is a repository script: beside the source checkout this code runs from, since
    # an installation's MISSION_CONTROL_HOME (PROJECT_ROOT) holds no scripts; else under it.
    checkout = Path(__file__).resolve().parents[3] / "scripts" / "quarantine_static_scan.py"
    scanner = (
        checkout if checkout.is_file() else PROJECT_ROOT / "scripts" / "quarantine_static_scan.py"
    )
    if not scanner.is_file():
        _LOG.warning("external candidate inspection is not composed: no scanner script")
        return discovery, None
    inspection = ExternalCandidateInspectionService(
        candidates=candidates,
        runner=StaticQuarantineInspectionRunner(
            payloads=SanitizedCandidateMetadataPayloadProvider(),
            process_runner=AsyncioQuarantineSubprocessRunner(),
            python_executable=Path(sys.executable).resolve(),
            scanner_script=scanner,
            workspace_root=workspace / "inspection",
        ),
        records=PostgresExternalCandidateInspectionRepository(pool, catalog_scope=catalog_scope),
        bounds=InspectionBounds(
            timeout_seconds=min(settings.external_discovery_command_timeout_seconds, 30),
            workspace_ttl_seconds=300,
            max_download_bytes=1_000_000,
            max_files=100,
            max_file_bytes=250_000,
            max_network_requests=0,
            max_network_destinations=1,
            max_findings=50,
            max_report_bytes=100_000,
        ),
        service_identity="mission-control-api-quarantine-inspector",
        allow_mcp_tools_list_probe=False,
    )
    return discovery, inspection


def compose_catalog_service(
    pool: asyncpg.Pool,
    *,
    request_scope: str,
    catalog_scope: str,
    embeddings: CapabilityEmbeddingPort | None = None,
    embedding_model_id: str = "text-embedding-3-small",
    embedding_dimensions: int = 1536,
    discovery: ExternalCapabilityDiscoveryService | None = None,
    inspection: ExternalCandidateInspectionService | None = None,
    components: AgenticComponentRepository | None = None,
) -> CatalogService:
    definitions = PostgresDefinitionRepository(pool, catalog_scope=catalog_scope)
    search = CapabilitySearchService(
        search=PostgresCatalogSearchRepository(pool, catalog_scope=catalog_scope),
        definitions=definitions,
        embeddings=embeddings,
        embedding_model_id=embedding_model_id if embeddings is not None else None,
        embedding_dimensions=embedding_dimensions if embeddings is not None else None,
    )
    return CatalogService(
        request_scope,
        catalog_scope,
        definitions,
        search,
        discovery,
        inspection,
        components,
        projectors=HOST_PROJECTORS,
    )
