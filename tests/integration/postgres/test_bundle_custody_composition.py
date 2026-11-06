"""MO-01 on the common component: every production rows resolver materializes through custody.

The common and biotech seed bundles are applied through the seed record writer and the
biotech skill bundles are uploaded with ``scripts/seeds_publish_bundles.py`` into the local
digest-path store that ``CAPABILITY_BUNDLE_LOCAL_ROOT`` names. A mission/v2 node on each local
lane selects the seeded ``skill.mission-control-observe`` and the ``hook.mc-policy-template``
hook script by exact pin. Then, through the production composition:

- launch: ``compose_projection_rows`` (the launch author's rows) resolves the pins over the
  restricted runtime login and the launch resolver seals each binding from those rows;
- prepare: the lane's own composed rows (``execution_binding_rows`` / ``cursor_catalog_rows``
  over ``compose_bundle_materializer``) re-render the projection, which must reproduce the
  sealed digests, and the lane's writer puts it in a workspace.

Every file of the skill bundle and of the hook script lands with the digest its catalog row
pins. Without custody the launch author refuses with ``bundle_custody_unavailable`` at the
selecting manifest pointer, before any template is frozen for a worker.

MO-02: the same production path over a workspace that already owns its ``AGENTS.md``, a
``.claude/skills`` skill and a ``.cursor/hooks.json`` (``tests/fixtures/layering_repo.py``),
with the manifest's ``materialization.conflicts`` sealed on every binding and applied by the
lane's ``materialize_projection``: the repository's files stay, its config files are merged, and
the restore leaves them byte-identical.

MO-31: the cursor_local binding is ``mc.cursor_binding.v2``, which pins the hook script beside
the skill (closing MO-01's Cursor gap) and a whole plugin with its expansion digest: the seeded
``plugin.web-research`` expands, through ``CatalogRows`` over custody, into the members the
launch author sealed, and its Skill member lands with its pinned digests.

FIXTURE: the in-memory fast-track compile catalog (it carries the same seeds), the example
launch bindings file and stand-in run/template stores for the refusal; no provider runs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import asyncpg
import pytest

from mission_control.adapters.cursor.projection import projection_digests, verify_projection
from mission_control.adapters.postgres.control_plane.definition_repository import (
    PostgresDefinitionRepository,
)
from mission_control.adapters.storage.control_plane_payloads import InMemoryPayloadStore
from mission_control.adapters.temporal.deployment_composition import cursor_catalog_rows
from mission_control.adapters.temporal.provider_lane_composition import execution_binding_rows
from mission_control.application.agentic_components.layering import restore_repository_files
from mission_control.application.agentic_components.materialization import (
    ProjectionMaterialization,
    materialize_projection,
)
from mission_control.application.agentic_components.placement import RenderedProjectionSource
from mission_control.application.authoring.cursor_launch import CURSOR_KERNEL_HOOKS
from mission_control.application.authoring.manifest_launch_inputs import (
    AdmittedLaunch,
    ManifestBundleCustodyUnavailable,
    provider_capability_pins,
)
from mission_control.application.authoring.manifest_service import (
    CompiledMission,
    ManifestCompileService,
    ManifestProgramCompiler,
    ManifestScope,
)
from mission_control.bootstrap.bundle_custody import compose_bundle_materializer
from mission_control.bootstrap.host_projection import HOST_PROJECTORS
from mission_control.bootstrap.manifests import compose_projection_rows
from mission_control.bootstrap.settings import Settings
from mission_control.domain.agentic_components.layering import (
    ConflictPolicy,
    MaterializationPolicy,
)
from mission_control.domain.authoring.contracts import (
    HookScriptDefinition,
    PublishedDefinition,
    SkillDefinition,
)
from mission_control.domain.authoring.extensions import ExtensionRegistry
from mission_control.domain.authoring.mission_definition import MissionDefinition
from mission_control.domain.capabilities.bundles import sha256_hex
from mission_control.domain.capabilities.catalog_entry import capability_pin
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.execution.contracts import OperationExecutionRequest
from mission_control.domain.execution.lanes import CursorExecutionBinding
from mission_control_db_contract.seeds import load_bundles, order_bundles
from tests.fixtures.catalog.fast_track_catalog import fast_track_catalog
from tests.fixtures.layering_repo import REPO_FILES, repository_bytes, write_repository_files
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.integration.postgres.catalog_common import (
    BIOTECH_CATALOG,
    SEEDS,
    apply_seed_bundle,
    seeds_publish_module,
)
from tests.integration.postgres.catalog_common import catalog_db as catalog_db
from tests.integration.postgres.catalog_common import runtime_pool as runtime_pool
from tests.unit.authoring.test_manifest_cursor_launch import LOCAL
from tests.unit.authoring.test_manifest_v2_launch import (
    AT,
    SCOPE,
    bundle_selection,
    edited,
    example,
    resolver,
    stub_author,
)

pytestmark = pytest.mark.common_db

SKILL = "skill.mission-control-observe"
HOOK = "hook.mc-policy-template"
PLUGIN = "plugin.web-research"
PLUGIN_SKILL = "skill.agent-browser"
HOOKS_ROOT = ".mission/hooks"
LANE_EXAMPLES = {
    "claude_agent_sdk": example("claude_agent_sdk", "goal-loop"),
    "codex": example("codex", "goal-loop"),
    "cursor_local": LOCAL,
}
CURSOR_LANES = frozenset(CURSOR_KERNEL_HOOKS)


def custody_settings(local_root: Path | None) -> Settings:
    """A deployment with the local custody backend (or none) over the biotech catalog."""

    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        capability_bundle_backend="local",
        capability_bundle_local_root=local_root,
        capability_bundle_reader_token=None,
        mission_control_catalog_scope=BIOTECH_CATALOG,
    )


async def seeded_catalog(
    database: CommonDatabase, pool: asyncpg.Pool
) -> dict[str, PublishedDefinition]:
    """The common and biotech seeds applied; the published rows the runtime login reads."""

    for bundle in order_bundles(load_bundles([SEEDS / "common", SEEDS / "biotech"]), set()):
        if not any(record["kind"].startswith("storage_") for record in bundle["records"]):
            await apply_seed_bundle(database, bundle)
    repository = PostgresDefinitionRepository(pool, catalog_scope=BIOTECH_CATALOG)
    return {item.ref.logical_id: item for item in await repository.list_published_definitions()}


async def compiled(
    manifest_yaml: str, skill: PublishedDefinition
) -> tuple[MissionDefinition, CompiledMission]:
    definitions, search = await fast_track_catalog()
    # Frozen seed revisions remain published; add the actual selected later revision
    # rather than compiling its new pin against the fixture's historical first row.
    revisions = [
        item
        for item in await definitions.list_published_definitions()
        if item.ref.kind == skill.ref.kind and item.ref.logical_id == skill.ref.logical_id
    ]
    if not any(item.ref == skill.ref for item in revisions):
        added = await definitions.publish(
            skill.definition,
            "seed",
            AT,
            max(item.ref.revision for item in revisions),
        )
        assert added.ref == skill.ref
    service = ManifestCompileService(
        definitions=definitions,
        search=search,
        programs=ManifestProgramCompiler(definitions, ExtensionRegistry(), InMemoryPayloadStore()),
    )
    compilation = await service.compile(
        manifest_yaml, ManifestScope(request_scope=SCOPE, actor_id="owner", at=AT)
    )
    assert compilation.ok, [(item.pointer, item.message) for item in compilation.report.blockers]
    (definition,), (program,) = compilation.definitions, compilation.programs
    return definition, program


def assert_materialized(workspace: Path, published: PublishedDefinition, directory: str) -> None:
    """Every pinned file of the definition is on disk once, under ``directory``, with its digest."""

    definition = published.definition
    assert isinstance(definition, SkillDefinition | HookScriptDefinition)
    on_disk = {
        path.relative_to(workspace).as_posix(): path
        for path in workspace.rglob("*")
        if path.is_file()
    }
    for entry in definition.file_manifest:
        (relative,) = [path for path in on_disk if path.endswith(f"{directory}/{entry.path}")]
        content = on_disk[relative].read_bytes()
        assert "sha256:" + sha256_hex(content) == entry.digest, relative
        assert len(content) == entry.size_bytes, relative


async def materialized_through_production(
    lane: str,
    catalog_db: CommonDatabase,
    runtime_pool: asyncpg.Pool,
    tmp_path: Path,
    *,
    policy: str | None = None,
    repository: bool = False,
    plugin: bool = False,
) -> tuple[dict[str, PublishedDefinition], list[tuple[Path, ProjectionMaterialization]]]:
    """Launch a node selecting the seeded skill and hook (and plugin) through the production
    composition, then let each template's lane rows re-render and materialize it into its own
    workspace (seeded with the fixture repository first when ``repository``)."""

    published = await seeded_catalog(catalog_db, runtime_pool)
    settings = custody_settings(tmp_path / "bundles")
    bundles = compose_bundle_materializer(settings)
    assert bundles is not None
    report = await seeds_publish_module().publish_application("biotech", bundles.store)
    assert report["uploaded_objects"] > 0
    cursor = lane in CURSOR_LANES
    skill = capability_pin(published[SKILL]).render()
    hook = capability_pin(published[HOOK]).render()
    plugin_pin = capability_pin(published[PLUGIN]).render()
    select = bundle_selection(skill, hook)

    def change(document: dict[str, Any]) -> None:
        select(document)
        if policy is not None:
            document["mission"]["environment"]["materialization"] = {"conflicts": policy}
        if plugin:
            document["mission"]["environment"]["plugins"] = [{"pin": plugin_pin, "as": "web"}]

    definition, program = await compiled(edited(LANE_EXAMPLES[lane], change), published[SKILL])

    # Launch: the author's composed rows, then the resolver seals each binding from them.
    pins = provider_capability_pins(definition)
    assert pins == ((skill, hook, plugin_pin) if plugin else (skill, hook))
    rows = await compose_projection_rows(runtime_pool, settings=settings)(pins)
    admitted = AdmittedLaunch.from_configuration(SCOPE, "run-mo01", program.configuration)
    templates: dict[str, OperationExecutionRequest] = (
        dict(resolver().stage_templates(definition, admitted, rows=rows))
        if program.lowered.family == "StageGraph"
        else dict(resolver().goal_templates(definition, admitted, rows=rows))
    )

    # Prepare: the lane's composed rows re-render, verify against the seal and materialize.
    placed: list[tuple[Path, ProjectionMaterialization]] = []
    for key, template in templates.items():
        workspace = tmp_path / "workspaces" / key.replace("/", "-")
        workspace.mkdir(parents=True)
        if repository:
            write_repository_files(workspace)
        if cursor:
            binding = CursorExecutionBinding.carried_by(template)
            assert binding is not None and binding.schema_version == "mc.cursor_binding.v2"
            assert binding.projections.skills == (skill,)
            assert binding.projections.hook_script_pins == (hook,)
            assert binding.projections.plugin_pins == ((plugin_pin,) if plugin else ())
            assert (binding.projections.plugin_expansion_digest is not None) is plugin
            source = RenderedProjectionSource(
                cursor_catalog_rows(settings, runtime_pool, bundles),
                kernel_hooks=CURSOR_KERNEL_HOOKS[lane],
                projectors=HOST_PROJECTORS,
            )
            projection = await source.project(template, profile=lane, packet_index=None)
            verify_projection(binding, projection_digests(projection))
            expected, sealed = None, binding.materialization
        else:
            provider = ProviderExecutionBinding.carried_by(template)
            assert provider is not None and provider.lane_profile == lane
            rows_resolver = execution_binding_rows(settings, runtime_pool, bundles)
            source = RenderedProjectionSource(rows_resolver, projectors=HOST_PROJECTORS)
            projection = await source.project(template, profile=lane, packet_index=None)
            expected, sealed = provider.materialization_digest, provider.materialization
        assert sealed == (None if policy is None else MaterializationPolicy(conflicts=policy))
        materialization = materialize_projection(
            projection, workspace, expected_digest=expected, policy=sealed
        )
        placed.append((workspace, materialization))
    assert placed and len(placed) == len(templates)
    return published, placed


@pytest.mark.asyncio
@pytest.mark.parametrize("lane", sorted(LANE_EXAMPLES))
async def test_a_skill_bundle_and_hook_script_materialize_through_production_composition(
    lane: str, catalog_db: CommonDatabase, runtime_pool: asyncpg.Pool, tmp_path: Path
) -> None:
    published, placed = await materialized_through_production(
        lane, catalog_db, runtime_pool, tmp_path
    )
    for workspace, _materialization in placed:
        assert_materialized(workspace, published[HOOK], f"{HOOKS_ROOT}/{HOOK}")
        assert_materialized(workspace, published[SKILL], "skills/mission-control-observe")


@pytest.mark.asyncio
async def test_a_plugin_expands_on_cursor_local_through_production_composition(
    catalog_db: CommonDatabase, runtime_pool: asyncpg.Pool, tmp_path: Path
) -> None:
    """MO-31: `mc.cursor_binding.v2` pins the plugin whole with its expansion digest; the
    worker's `CatalogRows` re-expands it over custody to the same members (else
    `CAPABILITY_DRIFT`) and its Skill member lands with its pinned digests."""

    published, placed = await materialized_through_production(
        "cursor_local", catalog_db, runtime_pool, tmp_path, plugin=True
    )
    for workspace, _materialization in placed:
        assert_materialized(workspace, published[PLUGIN_SKILL], "skills/agent-browser")
        assert_materialized(workspace, published[HOOK], f"{HOOKS_ROOT}/{HOOK}")
        mcp = json.loads((workspace / ".cursor/mcp.json").read_text(encoding="utf-8"))
        assert {"mc-tavily", "mc-firecrawl", "mc-agent-browser"} <= set(mcp["mcpServers"])


@pytest.mark.asyncio
@pytest.mark.parametrize("lane", sorted(LANE_EXAMPLES))
async def test_production_bindings_layer_over_a_repository_that_owns_its_cognition(
    lane: str, catalog_db: CommonDatabase, runtime_pool: asyncpg.Pool, tmp_path: Path
) -> None:
    published, placed = await materialized_through_production(
        lane, catalog_db, runtime_pool, tmp_path, policy="repo_wins", repository=True
    )
    for workspace, materialization in placed:
        assert_materialized(workspace, published[SKILL], "skills/mission-control-observe")
        for path in ("AGENTS.md", ".claude/skills/repo-notes/SKILL.md"):
            assert (workspace / path).read_bytes() == REPO_FILES[path]
        receipt = materialization.layering
        assert receipt is not None and receipt.conflicts_policy is ConflictPolicy.REPO_WINS
        assert receipt.merged and not receipt.conflicts
        repo_items = {(item.kind, item.name) for item in receipt.discovered("repo")}
        mission_items = {(item.kind, item.name) for item in receipt.discovered("mission")}
        assert ("instructions", "AGENTS.md") in repo_items
        assert ("skill", "mission-control-observe") in mission_items
        restore_repository_files(workspace)
        assert repository_bytes(workspace) == dict(REPO_FILES)


@pytest.mark.asyncio
async def test_missing_custody_is_a_typed_launch_refusal(
    catalog_db: CommonDatabase, runtime_pool: asyncpg.Pool
) -> None:
    published = await seeded_catalog(catalog_db, runtime_pool)
    settings = custody_settings(None)
    assert compose_bundle_materializer(settings) is None
    definition, program = await compiled(
        edited(
            LANE_EXAMPLES["claude_agent_sdk"],
            bundle_selection(
                capability_pin(published[SKILL]).render(), capability_pin(published[HOOK]).render()
            ),
        ),
        published[SKILL],
    )
    persisted: list[dict[str, Any]] = []
    author = stub_author(
        definition,
        program,
        projection_rows=compose_projection_rows(runtime_pool, settings=settings),
        persisted=persisted,
    )
    with pytest.raises(ManifestBundleCustodyUnavailable) as refused:
        await author.bind(SCOPE, "run-mo01", family="GoalDirected")
    assert refused.value.code == "bundle_custody_unavailable"
    assert refused.value.pointer == "/mission/environment/workspace/skills/0"
    assert SKILL in refused.value.reason
    assert persisted == [], "no template is frozen for a worker to fail on"
