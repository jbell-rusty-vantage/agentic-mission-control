"""MO-12 on a disposable common database: the starter Environment Kits are seeded, searchable
with their host support, resolve by exact pin for compile, and a seeded kit's mission layer
brings a local worktree to readiness ``prepared`` with a receipt.

The common and biotech seed bundles are applied through the seed record writer; the
restricted runtime login reads them, the catalog writer projects the search documents
(lexical only, no embedding route), and the mission layer runs under the host's bash.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import asyncpg
import pytest

from mission_control.adapters.postgres.capability.capability_search_generation_repository import (
    PostgresProjectionGenerationRepository,
)
from mission_control.adapters.postgres.capability.capability_search_repository import (
    PostgresCatalogSearchRepository,
)
from mission_control.adapters.postgres.control_plane.definition_repository import (
    PostgresDefinitionRepository,
)
from mission_control.adapters.postgres.scope import apply_catalog_scope_string
from mission_control.adapters.workspaces.mission_setup import BashMissionSetupRunner
from mission_control.application.capabilities.capability_search import CapabilitySearchService
from mission_control.application.capabilities.catalog_projection import (
    CatalogProjectionInput,
    CatalogProjector,
)
from mission_control.application.capabilities.catalog_projection_generation import (
    ProjectionGenerationSpec,
    projection_source_set_digest,
)
from mission_control.application.environments.kits import (
    CatalogEnvironmentInputs,
    EnvironmentKitCatalog,
)
from mission_control.application.environments.mission_layer import MissionLayerService
from mission_control.domain.authoring.contracts import DefinitionKind, EnvironmentKitDefinition
from mission_control.domain.authoring.environment_kits import (
    MISSION_SETUP_RECEIPT,
    MissionSetupReceipt,
    ReadinessLevel,
)
from mission_control.domain.capabilities.catalog_entry import capability_pin
from mission_control.domain.capabilities.host_support import HostSupportStatus
from mission_control.domain.coordinator.contracts import CapabilitySearchRequest
from mission_control_db_contract.seeds import load_bundles, order_bundles
from tests.fixtures.capability_search_catalog import DIMENSIONS, MODEL_ID
from tests.fixtures.environment_kits import BASH, setup_environ
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.integration.postgres.catalog_common import (
    BIOTECH_CATALOG,
    SEEDS,
    apply_seed_bundle,
)
from tests.integration.postgres.catalog_common import catalog_db as catalog_db
from tests.integration.postgres.catalog_common import catalog_writer_pool as catalog_writer_pool
from tests.integration.postgres.catalog_common import runtime_pool as runtime_pool

pytestmark = pytest.mark.common_db

NOW = datetime(2026, 10, 13, tzinfo=UTC)
STARTER_KITS = {
    "envkit.python-uv",
    "envkit.node",
    "envkit.python-uv-node",
    "envkit.mission-control-dev",
    "envkit.knowledge-research",
    "envkit.biotech-backend",
}


async def _seed(database: CommonDatabase) -> None:
    bundles = [
        bundle
        for bundle in order_bundles(load_bundles([SEEDS / "common", SEEDS / "biotech"]), set())
        if not any(record["kind"].startswith("storage_") for record in bundle["records"])
    ]
    for bundle in bundles:
        await apply_seed_bundle(database, bundle)


async def _project(writer_pool: asyncpg.Pool, reader: PostgresDefinitionRepository) -> None:
    refs = await reader.list_published_definition_refs()
    spec = ProjectionGenerationSpec(
        tenant_scope="global",
        projection_generation="mo12-generation-1",
        embedding_model_id=MODEL_ID,
        embedding_dimensions=DIMENSIONS,
        search_document_format_version=1,
        selected_kinds=frozenset(ref.kind for ref in refs),
        expected_count=len(refs),
        expected_source_set_digest=projection_source_set_digest(refs),
    )
    generations = PostgresProjectionGenerationRepository(writer_pool, catalog_scope=BIOTECH_CATALOG)
    await generations.begin(spec, created_at=NOW)
    projector = CatalogProjector(
        definitions=PostgresDefinitionRepository(writer_pool, catalog_scope=BIOTECH_CATALOG),
        search=PostgresCatalogSearchRepository(writer_pool, catalog_scope=BIOTECH_CATALOG),
        embeddings=None,
        embedding_model_id=MODEL_ID,
        embedding_dimensions=DIMENSIONS,
        projection_generation=spec.projection_generation,
        clock=lambda: NOW,
    )
    await projector.project_many(tuple(CatalogProjectionInput(ref=ref) for ref in refs))
    activation = await generations.activate(spec, activated_at=NOW)
    assert activation.activated_count == len(refs)


@pytest.mark.asyncio
async def test_seeded_kits_are_searchable_resolve_by_pin_and_prepare_a_worktree(
    catalog_db: CommonDatabase,
    runtime_pool: asyncpg.Pool,
    catalog_writer_pool: asyncpg.Pool,
    tmp_path: Path,
) -> None:
    await _seed(catalog_db)
    repository = PostgresDefinitionRepository(runtime_pool, catalog_scope=BIOTECH_CATALOG)
    kits = {
        item.ref.logical_id: item
        for item in await repository.list_published_definitions()
        if item.ref.kind == DefinitionKind.ENVIRONMENT_KIT
    }
    assert set(kits) == STARTER_KITS
    async with runtime_pool.acquire() as connection, connection.transaction():
        await apply_catalog_scope_string(connection, BIOTECH_CATALOG)
        categories = await connection.fetch(
            "SELECT DISTINCT kind FROM mission_control.asset_version "
            "WHERE asset_id LIKE 'definition:environment_kit:%'"
        )
    assert [row["kind"] for row in categories] == ["profile"]

    # Searchable in the catalog, filtered by kind and by the lane profiles a kit supports.
    await _project(catalog_writer_pool, repository)
    reader = PostgresCatalogSearchRepository(runtime_pool, catalog_scope=BIOTECH_CATALOG)
    search = CapabilitySearchService(search=reader, definitions=repository)
    tenant = catalog_db.scope("tenant-1")
    response = await search.search(
        CapabilitySearchRequest(
            query="python uv environment",
            tenant_scope=tenant,
            kinds=frozenset({DefinitionKind.ENVIRONMENT_KIT}),
            host_profiles=frozenset({"codex"}),
            limit=10,
        )
    )
    hits = {hit.exact_ref.logical_id: hit for hit in response.hits if hit.exact_ref}
    assert "envkit.python-uv" in hits
    assert all(logical_id in STARTER_KITS for logical_id in hits)
    found = hits["envkit.python-uv"]
    assert found.pin == capability_pin(kits["envkit.python-uv"]).render()
    assert found.host_support is not None
    assert found.host_support.status("codex") == HostSupportStatus.SUPPORTED
    assert found.host_support.status("cursor_local") == HostSupportStatus.SUPPORTED
    assert found.host_support.status("cursor_cloud") == HostSupportStatus.UNQUALIFIED
    # Hosted base layers are unproven, so no kit matches a cursor_cloud host filter yet.
    hosted = await search.search(
        CapabilitySearchRequest(
            query="python uv environment",
            tenant_scope=tenant,
            kinds=frozenset({DefinitionKind.ENVIRONMENT_KIT}),
            host_profiles=frozenset({"cursor_cloud"}),
        )
    )
    assert hosted.hits == ()

    # Compile resolves the exact pin offline (the production EnvironmentInputsPort).
    catalog = EnvironmentKitCatalog(repository)
    pin = capability_pin(kits["envkit.knowledge-research"]).render()
    requirements = await CatalogEnvironmentInputs(catalog).kit_requirements(pin)
    assert requirements is not None
    assert {secret.name for secret in requirements.secrets} == {
        "TAVILY_API_KEY",
        "FIRECRAWL_API_KEY",
    }
    assert "mcp.firecrawl.dev" in requirements.egress

    # A local lane's bootstrap entrypoint: the seeded python-uv kit prepares a worktree.
    if BASH is None:
        pytest.skip("the mission layer runs under bash")
    python_uv = capability_pin(kits["envkit.python-uv"]).render()
    definition = await catalog.resolve(python_uv)
    assert isinstance(definition, EnvironmentKitDefinition)
    # uv finds its cache and managed interpreters through these on a Windows host.
    uv_locations = {"APPDATA", "LOCALAPPDATA", "UV_CACHE_DIR", "UV_PYTHON_INSTALL_DIR"}
    environ = setup_environ(
        **{name: value for name, value in os.environ.items() if name in uv_locations}
    )
    outcome = await MissionLayerService(catalog, BashMissionSetupRunner()).prepare(
        tmp_path, kit_pin=python_uv, environment=environ
    )
    assert outcome.readiness == ReadinessLevel.PREPARED, outcome.reasons
    receipt = MissionSetupReceipt.parse((tmp_path / MISSION_SETUP_RECEIPT).read_bytes())
    assert receipt.kit_pin == python_uv
    assert [(step.name, step.status) for step in receipt.steps] == [("deps", "skipped")]
    assert [(check.name, check.passed) for check in receipt.health] == [("python", True)]
    observed = {item.name: item.observed for item in receipt.toolchains}
    assert observed["uv"].startswith("uv ")
