"""FT-A7 on the common component: seeded skills, plugin members and materialization.

The common and biotech seed bundles (agent capabilities and agent skills included) are
applied through the seed record writer; the restricted runtime login then reads the
published ``skill.mission-control-observe`` row, its bytes come back from a storage fake
holding exactly what ``scripts/seeds_publish_bundles.py`` uploaded, verified against the
row's manifest digest, and a Deep Agents binding pinning the bundle mounts it under
``/skills`` with a read-only filesystem permission. A tampered object is refused with
``CAPABILITY_DRIFT``. ``plugin.web-research`` has its four ``capability_plugin_member`` rows
and ``catalog inspect --pin`` lists the members.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import asyncpg
import pytest
from deepagents.backends import StateBackend

from mission_control.adapters.capabilities.local_bundle_store import (
    FilesystemBundleFetcher,
    FilesystemBundleObjectStore,
)
from mission_control.adapters.deep_agents.adapter import _permissions
from mission_control.adapters.deep_agents.materializer import (
    ExactComponentRegistry,
    ExactDeepAgentMaterializer,
    ResolvedSkillBundle,
)
from mission_control.adapters.postgres.control_plane.definition_repository import (
    PostgresDefinitionRepository,
)
from mission_control.adapters.postgres.scope import apply_catalog_scope_string
from mission_control.application.capabilities.bundle_custody import fetch_definition_bundle
from mission_control.application.capabilities.catalog import inspect_pin
from mission_control.domain.authoring.contracts import SkillDefinition
from mission_control.domain.capabilities.bundles import CapabilityDrift
from mission_control.domain.capabilities.catalog_entry import capability_pin
from mission_control_db_contract.seeds import load_bundles, order_bundles
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.integration.postgres.catalog_common import (
    BIOTECH_CATALOG,
    SEEDS,
    apply_seed_bundle,
    seeds_publish_module,
)
from tests.integration.postgres.catalog_common import catalog_db as catalog_db
from tests.integration.postgres.catalog_common import runtime_pool as runtime_pool

pytestmark = pytest.mark.common_db


@pytest.mark.asyncio
async def test_seeded_skill_mounts_read_only_and_tampering_is_refused(
    catalog_db: CommonDatabase, runtime_pool: asyncpg.Pool, tmp_path: Path
) -> None:
    bundles = [
        bundle
        for bundle in order_bundles(load_bundles([SEEDS / "common", SEEDS / "biotech"]), set())
        if not any(record["kind"].startswith("storage_") for record in bundle["records"])
    ]
    for bundle in bundles:
        await apply_seed_bundle(catalog_db, bundle)
    skills = next(b for b in bundles if b["seed_key"] == "mc.app.biotech.agent-skills")
    replay = await apply_seed_bundle(catalog_db, skills)
    assert replay["created"] == 0 and replay["reused"] == len(skills["records"])

    repository = PostgresDefinitionRepository(runtime_pool, catalog_scope=BIOTECH_CATALOG)
    published = {
        item.ref.logical_id: item for item in await repository.list_published_definitions()
    }
    assert {
        "skill.agent-browser",
        "skill.biomcp",
        "skill.mission-control-observe",
        "hook.mc-policy-template",
        "plugin.web-research",
    } <= set(published)
    assert "skill.edgartools" not in published  # ai-engineer only

    # Plugin expansion rows pin each member's exact manifest digest.
    async with runtime_pool.acquire() as connection, connection.transaction():
        await apply_catalog_scope_string(connection, BIOTECH_CATALOG)
        members = await connection.fetch(
            "SELECT pm.position, pm.member_asset_id, pm.role, pm.optional, "
            "pm.member_digest = member.manifest_digest AS pinned "
            "FROM mission_control.capability_plugin_member pm "
            "JOIN mission_control.asset_version member "
            "ON member.installation_id = pm.installation_id "
            "AND member.application_id = pm.application_id "
            "AND member.asset_id = pm.member_asset_id AND member.version = pm.member_version "
            "WHERE pm.plugin_asset_id = 'definition:plugin:plugin.web-research' "
            "ORDER BY pm.position"
        )
    assert [(row["member_asset_id"], row["role"], row["optional"]) for row in members] == [
        ("definition:mcp_server:mcp.tavily", "mcp_server", False),
        ("definition:mcp_server:mcp.firecrawl", "mcp_server", False),
        ("definition:skill:skill.agent-browser", "skill", False),
        ("definition:mcp_server:mcp.agent-browser", "mcp_server", True),
    ]
    assert all(row["pinned"] for row in members)
    plugin_pin = capability_pin(published["plugin.web-research"]).render()
    inspection = await inspect_pin(repository, plugin_pin)
    assert [member.pin.split("@")[0] for member in inspection.plugin_members] == [
        "mcp.tavily",
        "mcp.firecrawl",
        "skill.agent-browser",
        "mcp.agent-browser",
    ]
    assert all(member.found for member in inspection.plugin_members)

    # Custody: the publish path uploads the biotech bundles into the storage fake.
    store = FilesystemBundleObjectStore(tmp_path / "bucket")
    report = await seeds_publish_module().publish_application("biotech", store)
    assert report["uploaded_objects"] > 0

    observe = published["skill.mission-control-observe"].definition
    assert isinstance(observe, SkillDefinition)
    manifest, files = await fetch_definition_bundle(observe, store, FilesystemBundleFetcher(store))
    from mission_control.adapters.capabilities.capability_bundles import (
        bundle_digest,
        bytes_digest,
    )

    digest = bundle_digest(files)
    component = SimpleNamespace(
        bundle_digest=digest,
        skill_md_digest=bytes_digest(dict(files)["SKILL.md"]),
        mount_root="/skills/mission-control-observe",
    )
    materializer = ExactDeepAgentMaterializer(
        ExactComponentRegistry(
            model_factories={},
            skill_bundles={digest: ResolvedSkillBundle(digest, files, "bytes_v1")},
        )
    )
    sources, state_files, _rows = await materializer._mount_skills(
        SimpleNamespace(skills=[component]),  # type: ignore[arg-type]
        StateBackend(),
    )
    assert sources == ("/skills",)
    assert set(state_files) == {
        f"/skills/mission-control-observe/{entry.path}" for entry in manifest.files
    }
    read_only = _permissions(
        SimpleNamespace(  # type: ignore[arg-type]
            skills=[component],
            workspace=SimpleNamespace(read_mounts=(), exclusive_write_paths=("/outputs",)),
        )
    )[0]
    assert read_only.operations == ["read"] and read_only.mode == "allow"
    assert read_only.paths == ["/skills/mission-control-observe"]

    # A tampered object never materializes.
    object_path = store.path_for(f"{manifest.object_prefix}/SKILL.md")
    original = object_path.read_bytes()
    tampered = original + b"\nTAMPERED-BUNDLE\n"
    assert tampered != original
    object_path.write_bytes(tampered)
    with pytest.raises(CapabilityDrift):
        await fetch_definition_bundle(observe, store, FilesystemBundleFetcher(store))
