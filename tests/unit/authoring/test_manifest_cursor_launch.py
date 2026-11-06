"""The production manifest launch author seals ``mc.cursor_binding.v2`` for the Cursor lanes.

- The checked Cursor v2 examples (``tests/fixtures/manifests/multi-provider/cursor-*``)
  compile with the fast-track fixture catalog and author, per ``cursor_local`` /
  ``cursor_cloud`` stage or Goal Loop role, an exact sealed ``CursorExecutionBinding`` routed to
  the lane's task queue from ``providers.cursor_*`` of
  ``deployments/examples/manifest-launch-bindings.multi-provider.codex-0.162.1.example.json``.
- The pinned projection digests are exactly those the Cursor harness re-renders at ``prepare``:
  the adapter's own ``RenderedProjectionSource`` over its own ``CatalogRows`` (both over the
  same fixture catalog) passes ``verify_projection`` for the sealed binding.
- mission/v1 Cursor nodes (Missions 2 and 3) launch through the same author with their hook
  scripts and plugin on ``mc.cursor_binding.v2`` (MO-31); what the binding cannot carry
  (deterministic executors) is refused at the manifest pointer that selected it. As authored,
  both missions' independent verifiers run on Deep Agents and are refused there too (no
  sandbox profile; no Deep Agents launch binding for the inherited subagent profiles, hook
  scripts and plugins), so the Cursor launches move the verifier onto the Cursor lane.

Offline: fixture catalog, in-memory compiler, the seeded Skill bundles in a local custody store;
no provider is contacted.
"""

from __future__ import annotations

import asyncio
import copy
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from mission_control.adapters.cursor import bridge
from mission_control.adapters.cursor.projection import (
    CatalogRows,
    projection_digests,
    verify_projection,
)
from mission_control.application.agentic_components.placement import (
    MISSION_CONTEXT_POINTER,
    LaneProjectionError,
    RenderedProjectionSource,
    operating_contract,
)
from mission_control.application.authoring.cursor_launch import (
    CURSOR_KERNEL_HOOKS,
    REQUIRED_CURSOR_PINS,
    cursor_projection_digests,
)
from mission_control.application.authoring.manifest_launch_inputs import (
    AdmittedLaunch,
    ManifestLaunchBindingError,
    ManifestLaunchBindings,
    provider_capability_pins,
)
from mission_control.application.authoring.provider_launch import (
    CatalogProjectionRows,
    ProviderLanes,
)
from mission_control.application.capabilities.bundle_custody import BundleMaterializer
from mission_control.application.capabilities.catalog import (
    find_published_by_pin,
    resolved_capability,
)
from mission_control.bootstrap.bundle_custody import compose_bundle_materializer
from mission_control.bootstrap.host_projection import HOST_PROJECTORS
from mission_control.bootstrap.settings import Settings
from mission_control.domain.agentic_components.projection import (
    DEFAULT_KERNEL_HOOKS,
    BundleFile,
    HostProjection,
    ResolvedCapability,
)
from mission_control.domain.authoring.contracts import HookScriptDefinition
from mission_control.domain.authoring.manifest import canonical_manifest_bytes, load_manifest_yaml
from mission_control.domain.authoring.mission_definition import MissionDefinition
from mission_control.domain.capabilities.pins import CapabilityPin
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.execution.contracts import (
    DeepAgentExecutionBinding,
    OperationExecutionRequest,
    OperationWorkflowRequest,
)
from mission_control.domain.execution.lanes import CursorExecutionBinding, WorkspacePolicyPin
from tests.fixtures.catalog.fast_track_catalog import fast_track_catalog
from tests.fixtures.mission_control_common_db import canonical_scope
from tests.fixtures.projections.rows import (
    fixture_rows,
    hook_row,
    skill_row,
    tavily_row,
    verifier_row,
)
from tests.unit.authoring.test_manifest_v2_launch import (
    BINDINGS,
    EXAMPLES,
    SCOPE,
    V1_BINDINGS,
    bindings,
    compile_yaml,
    compiled_ok,
    edited,
    resolver,
    templates_of,
)

ROOT = Path(__file__).resolve().parents[3]
MISSIONS = ROOT / "tests/fixtures/manifests/fast-track"
LOCAL = EXAMPLES / "cursor-local.stage-graph.mission.yml"
CLOUD = EXAMPLES / "cursor-cloud.goal-loop.mission.yml"
PROFILE_OF = {LOCAL: "cursor_local", CLOUD: "cursor_cloud"}


def seeds_publish_module() -> Any:
    """``scripts/seeds_publish_bundles.py`` (FT-A7 custody upload of the agent-skill seeds)."""

    spec = importlib.util.spec_from_file_location(
        "mo31_publish", ROOT / "scripts" / "seeds_publish_bundles.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def cursor_templates(path: Path, bound: ManifestLaunchBindings | None = None) -> dict[str, Any]:
    compilation = compiled_ok(path.read_text(encoding="utf-8"))
    templates: dict[str, Any] = {}
    for definition, program in zip(compilation.definitions, compilation.programs, strict=True):
        templates.update(templates_of(program, definition, bound))
    return templates


def _refused(text: str, bound: ManifestLaunchBindings | None = None, **rows: Any) -> Any:
    compilation = compiled_ok(text)
    (definition,), (program,) = compilation.definitions, compilation.programs
    admitted = AdmittedLaunch.from_configuration(SCOPE, "run-cursor", program.configuration)
    target = resolver(bound)
    with pytest.raises(ManifestLaunchBindingError) as raised:
        if program.lowered.family == "StageGraph":
            target.stage_templates(definition, admitted, rows=rows.get("rows"))
        else:
            target.goal_templates(definition, admitted, rows=rows.get("rows"))
    return raised.value


def _without_lane(profile: str, **changes: Any) -> ManifestLaunchBindings:
    bound = bindings()
    assert bound.providers is not None
    lane = getattr(bound.providers, profile)
    return bound.model_copy(
        update={
            "providers": bound.providers.model_copy(
                update={
                    profile: type(lane).model_validate(
                        {**lane.model_dump(mode="python"), **changes}
                    )
                }
            )
        }
    )


# --- The checked examples: sealed, routed, exact -------------------------------------------------


@pytest.mark.parametrize("path", [LOCAL, CLOUD], ids=lambda item: item.name)
def test_each_cursor_example_authors_sealed_cursor_bindings(path: Path) -> None:
    profile = PROFILE_OF[path]
    providers = bindings().providers
    assert providers is not None
    lane = providers.cursor(profile)
    assert lane is not None
    cursor_units = 0
    for key, template in cursor_templates(path).items():
        if template.execution_runtime == "deep_agent":
            assert (
                CursorExecutionBinding.carried_by(template) is None
                and DeepAgentExecutionBinding.carried_by(template) is not None
            )
            continue
        cursor_units += 1
        binding = CursorExecutionBinding.carried_by(template)
        assert isinstance(binding, CursorExecutionBinding), key
        assert template.execution_runtime == "cursor" and template.lane_profile == profile
        assert (
            ProviderExecutionBinding.carried_by(template) is None
            and DeepAgentExecutionBinding.carried_by(template) is None
        )
        assert template.native_placement is None and template.secret_refs == ()
        # Sealed: the digest is the content's, and a re-validation from the stored JSON holds.
        assert binding.binding_digest == binding.computed_digest()
        stored = OperationExecutionRequest.model_validate(template.model_dump(mode="json"))
        assert CursorExecutionBinding.carried_by(stored) == binding
        assert binding.lane_profile == profile and binding.pins == REQUIRED_CURSOR_PINS
        assert binding.schema_version == "mc.cursor_binding.v2"
        assert binding.model_id == lane.model_profiles["cursor.default"].model_id
        assert template.model_policy.provider == "cursor"
        assert template.model_policy.model == binding.model_id
        assert binding.task_queue == lane.task_queue
        workflow = OperationWorkflowRequest(
            semantic_attempt_id=template.identity.semantic_key,
            operation_kind="bound_operation",
            operation=template,
        )
        assert workflow.activity_task_queue == lane.task_queue, key
        assert binding.workspace.base_ref == "main" and binding.workspace.branch_prefix == "mc/"
        if profile == "cursor_local":
            assert binding.workspace.repo_url == "/srv/repos/mission-control-fixture"
            assert binding.hook_callback is not None and binding.cloud is None
            # MO-05: the lane leases under the manifest's admitted workspace policy.
            assert binding.workspace.policy == WorkspacePolicyPin(
                mode="managed_worktree",
                reuse="within_run",
                dirty_input="reject",
                cleanup="retain_until_artifacts_registered",
            )
            # Narrowed by the node: wall_clock 1h < 2h; continuation.max_session_turns 12 < 16.
            assert (binding.budgets.wall_clock_s, binding.budgets.max_turns) == (3600, 12)
        else:
            assert (
                binding.workspace.repo_url == "https://github.com/Overton77/mission-control-fixture"
            )
            assert binding.cloud == lane.environments["cursor-cloud.default"].options  # type: ignore[union-attr]
            assert binding.hook_callback is None and binding.workspace.policy is None
            assert binding.budgets == lane.budgets
        # No capability selected: the Kernel Hooks (local only) and the operating contract.
        rendered = HOST_PROJECTORS.render(
            (), profile, operating_contract(template), None, CURSOR_KERNEL_HOOKS[profile]
        )
        verify_projection(binding, projection_digests(rendered))
    assert cursor_units >= 2


def test_templates_are_deterministic() -> None:
    assert cursor_templates(LOCAL) == cursor_templates(LOCAL)
    assert cursor_templates(CLOUD) == cursor_templates(CLOUD)


# --- The digest the harness recomputes at `prepare` ----------------------------------------------


def _with_catalog_capabilities(document: dict[str, Any]) -> None:
    """Mission-wide Cursor capabilities (the Deep Agents node, which would inherit them
    without a Deep Agents component binding, is dropped)."""

    program = document["mission"]["program"]
    if program["behavior"] == "stage_graph":
        program["nodes"] = [node for node in program["nodes"] if node["key"] != "summarize"]
    environment = document["mission"]["environment"]
    environment["capabilities"] = [
        {"search": "tavily web search extract", "kind": "mcp_server", "as": "tavily"}
    ]
    environment["agents"] = [
        {"search": "literature verifier subagent", "kind": "subagent_profile", "as": "checker"}
    ]


@pytest.mark.parametrize("path", [LOCAL, CLOUD], ids=lambda item: item.name)
def test_the_sealed_projection_is_what_the_harness_renders_at_prepare(path: Path) -> None:
    """Author side: `CatalogProjectionRows` (the composed resolver); worker side: the adapter's
    `RenderedProjectionSource(CatalogRows(...))` with the composed Kernel Hooks per profile.
    Both read the same catalog; `verify_projection` accepts the sealed binding."""

    profile = PROFILE_OF[path]
    compilation = compiled_ok(edited(path, _with_catalog_capabilities))
    definitions, _search = asyncio.run(fast_track_catalog())
    for definition, program in zip(compilation.definitions, compilation.programs, strict=True):
        pins = provider_capability_pins(definition)
        assert len(pins) == 2, pins
        rows = asyncio.run(CatalogProjectionRows(definitions, bundles=None)(pins))
        admitted = AdmittedLaunch.from_configuration(SCOPE, "run-cursor", program.configuration)
        target = resolver()
        templates = (
            target.stage_templates(definition, admitted, rows=rows)
            if program.lowered.family == "StageGraph"
            else target.goal_templates(definition, admitted, rows=rows)
        )
        sealed = [
            item
            for item in templates.values()
            if CursorExecutionBinding.carried_by(item) is not None
        ]
        assert sealed
        for template in sealed:
            binding = CursorExecutionBinding.carried_by(template)
            assert binding is not None
            (mcp,) = binding.projections.mcp_servers
            (agent,) = binding.inline_subagents
            assert mcp.startswith("mcp.tavily@") and agent.startswith("subagent.")
            assert binding.projections.skills == ()
            worker = RenderedProjectionSource(
                CatalogRows(definitions, bundles=None),
                kernel_hooks=CURSOR_KERNEL_HOOKS[profile],
                projectors=HOST_PROJECTORS,
            )
            projection = asyncio.run(worker.project(template, profile=profile, packet_index=None))
            verify_projection(binding, projection_digests(projection))
            assert any(item.path.startswith(".cursor/agents/") for item in projection.files)
            # A binding sealed without the capabilities differs: the digests pin the rows.
            empty = HOST_PROJECTORS.render(
                (), profile, operating_contract(template), None, CURSOR_KERNEL_HOOKS[profile]
            )
            assert projection_digests(empty)["agents_digest"] != binding.projections.agents_digest


def test_the_application_digests_are_the_adapters() -> None:
    for rows in ((skill_row(), tavily_row(), verifier_row()), fixture_rows()):
        for profile in ("cursor_local", "cursor_cloud"):
            for kernel in (DEFAULT_KERNEL_HOOKS, ()):
                projection = HOST_PROJECTORS.render(rows, profile, "contract", None, kernel)
                digests = cursor_projection_digests(projection)
                assert digests == projection_digests(projection)
                plugins = bool(projection.report.plugin_expansions)
                assert ("plugin_expansion_digest" in digests) is plugins
    template = cursor_templates(LOCAL)["diagnose/execute/default"]
    assert MISSION_CONTEXT_POINTER in operating_contract(template)
    # The composed harnesses: Kernel Hooks on cursor_local, none on cursor_cloud.
    assert CURSOR_KERNEL_HOOKS == {"cursor_local": DEFAULT_KERNEL_HOOKS, "cursor_cloud": ()}
    # The pins are the composed adapter's versions.
    assert REQUIRED_CURSOR_PINS.cursor_sdk == bridge.CURSOR_SDK_PIN
    assert REQUIRED_CURSOR_PINS.bridge == bridge.CURSOR_SDK_PIN
    assert REQUIRED_CURSOR_PINS.protocol == bridge.BRIDGE_PROTOCOL
    assert REQUIRED_CURSOR_PINS.cloud_api == "v1"


# --- mission/v1: Missions 2 and 3 ---------------------------------------------------------------


def _mission(name: str, change: Any) -> str:
    document = load_manifest_yaml((MISSIONS / name).read_text(encoding="utf-8"))
    change(document)
    return canonical_manifest_bytes(document).decode("utf-8")


def _v1_cloud_bound() -> ManifestLaunchBindings:
    bound = bindings()
    assert bound.providers is not None and bound.providers.cursor_cloud is not None
    repositories = {
        **bound.providers.cursor_cloud.repositories,
        "https://github.com/Overton77/biotech-research-notes": {
            "repo_url": "https://github.com/Overton77/biotech-research-notes",
            "base_refs": ["main"],
        },
    }
    lane = type(bound.providers.cursor_cloud).model_validate(
        {**bound.providers.cursor_cloud.model_dump(mode="python"), "repositories": repositories}
    )
    return _fast_track_models(
        bound.model_copy(
            update={"providers": bound.providers.model_copy(update={"cursor_cloud": lane})}
        )
    )


def _v1_local_bound() -> ManifestLaunchBindings:
    return _fast_track_models(
        _without_lane(
            "cursor_local",
            repositories={
                r"C:\Users\Pinda\Proyectos\Biotech\mission-control": {
                    "repo_url": "/srv/repos/mission-control",
                    "base_refs": ("main",),
                }
            },
        )
    )


def _fast_track_models(bound: ManifestLaunchBindings) -> ManifestLaunchBindings:
    """FIXTURE: the fast-track missions (and their golden resolutions) predate the Model Catalog
    and still name `frontier.default`; the example binds catalog names (OC-R7), so the Deep Agents
    verifiers launch on its `producer.default` entry under the fast-track name."""

    return bound.model_copy(
        update={
            "model_profiles": {
                **bound.model_profiles,
                "frontier.default": bound.model_profiles["producer.default"],
            }
        }
    )


@pytest.fixture(scope="module")
def custody(tmp_path_factory: pytest.TempPathFactory) -> BundleMaterializer:
    """The seeded Skill bundles (biotech digests, which the fixture catalog carries) uploaded
    into a local digest-path store, read through the composed local custody."""

    bundles = compose_bundle_materializer(
        Settings(  # type: ignore[call-arg]
            _env_file=None,
            capability_bundle_backend="local",
            capability_bundle_local_root=tmp_path_factory.mktemp("custody"),
            capability_bundle_reader_token=None,
        )
    )
    assert bundles is not None
    report = asyncio.run(seeds_publish_module().publish_application("biotech", bundles.store))
    assert report["uploaded_objects"] > 0
    return bundles


async def _fixture_rows(
    definitions: Any, bundles: BundleMaterializer, pins: tuple[str, ...]
) -> dict[str, ResolvedCapability]:
    """The composed rows (catalog + custody), except for the fast-track hook stand-ins: FIXTURE,
    they carry no custody bundle and each manifest entry digests the entry path's own text, so
    those are their pinned bytes."""

    rows: dict[str, ResolvedCapability] = {}
    for text in pins:
        pin = CapabilityPin.parse(text)
        published = await find_published_by_pin(definitions, pin)
        assert published is not None, text
        stand_in = published.definition
        if isinstance(stand_in, HookScriptDefinition) and stand_in.bundle_ref is None:
            files = tuple(
                BundleFile(path=entry.path, content=entry.path.encode("utf-8"))
                for entry in stand_in.file_manifest
            )
            rows[text] = ResolvedCapability(pin=pin, definition=stand_in, files=files)
        else:
            rows[text] = await resolved_capability(definitions, pin, bundles=bundles)
    return rows


def _pinned_rows(rows: dict[str, ResolvedCapability]) -> Any:
    """The worker's rows resolver over the same rows, in the binding's ``projected_pins`` order
    (what ``CatalogRows`` resolves; the PostgreSQL proof runs ``CatalogRows`` itself)."""

    async def resolve(operation: OperationExecutionRequest) -> tuple[ResolvedCapability, ...]:
        binding = CursorExecutionBinding.carried_by(operation)
        assert binding is not None
        return tuple(rows[text] for text in binding.projected_pins())

    return resolve


def _launched_on_cursor(
    text: str,
    bound: ManifestLaunchBindings,
    bundles: BundleMaterializer,
    scope: str = SCOPE,
) -> tuple[dict[str, OperationExecutionRequest], dict[str, ResolvedCapability]]:
    compilation = compile_yaml(text, scope)
    assert compilation.ok, [(item.pointer, item.message) for item in compilation.report.blockers]
    (definition,), (program,) = compilation.definitions, compilation.programs
    assert definition.program.selections is None
    definitions, _search = asyncio.run(fast_track_catalog())
    rows = asyncio.run(_fixture_rows(definitions, bundles, provider_capability_pins(definition)))
    admitted = AdmittedLaunch.from_configuration(scope, "run-v1", program.configuration)
    templates = resolver(bound).goal_templates(definition, admitted, rows=rows)
    return dict(templates), rows


def _rendered_at_prepare(
    template: OperationExecutionRequest, rows: dict[str, ResolvedCapability]
) -> HostProjection:
    binding = CursorExecutionBinding.carried_by(template)
    assert binding is not None
    profile = binding.lane_profile
    worker = RenderedProjectionSource(
        _pinned_rows(rows), kernel_hooks=CURSOR_KERNEL_HOOKS[profile], projectors=HOST_PROJECTORS
    )
    projection = asyncio.run(worker.project(template, profile=profile, packet_index=None))
    verify_projection(binding, projection_digests(projection))
    return projection


def _mission_two_member(document: dict[str, Any]) -> None:
    """FIXTURE transform: Mission 2's research member alone, in the test scope's application,
    its independent verifier still on Deep Agents as authored. Its fixture-only
    literature-review Skill has no custody bundle and is dropped (the seeded
    `skill.mission-control-observe` stays)."""

    (research,) = [item for item in document["missions"] if item["key"] == "research"]
    research["application"] = "ai-engineer"
    workspace = research["environment"]["workspace"]
    workspace["skills"] = [item for item in workspace["skills"] if "pin" in item]
    document.pop("missions")
    document.pop("links")
    document["mission"] = research


def _mission_two_research(document: dict[str, Any]) -> None:
    """FIXTURE transform: `_mission_two_member` with its independent verifier moved onto the
    mission's Cursor lane: on Deep Agents, as authored, it is refused (see
    `test_the_deep_agents_verifiers_as_authored_are_refused`)."""

    _mission_two_member(document)
    document["mission"]["program"]["verifier"].pop("environment")


def test_mission_two_research_launches_on_cursor_cloud_with_its_hook(
    custody: BundleMaterializer,
) -> None:
    """mission/v1 has no selections: the deployment's reviewed `v1_environment` applies and
    the worker's Cursor credential is the binding's. Its hook script is pinned on the
    `mc.cursor_binding.v2` (MO-31) and the worker re-renders the sealed digests."""

    text = _mission("02-research-ingestion-cursor-cloud-chain.yml", _mission_two_research)
    templates, rows = _launched_on_cursor(text, _v1_cloud_bound(), custody)
    executor = CursorExecutionBinding.carried_by(templates["executor"])
    assert executor is not None and executor.lane_profile == "cursor_cloud"
    assert executor.schema_version == "mc.cursor_binding.v2"
    assert executor.workspace.repo_url == "https://github.com/Overton77/biotech-research-notes"
    (skill,) = executor.projections.skills
    (hook,) = executor.projections.hook_script_pins
    assert skill.startswith("skill.mission-control-observe@")
    assert hook.startswith("hook.citation-check@")
    assert len(executor.projections.mcp_servers) == 2 and len(executor.inline_subagents) == 1
    assert executor.projections.plugin_pins == ()
    assert executor.projections.plugin_expansion_digest is None
    projection = _rendered_at_prepare(templates["executor"], rows)
    # Catalog command hooks (no Kernel Hooks on cursor_cloud), on events Cursor Cloud runs,
    # beside the Telemetry Hook Pack's own entries (SPEC-04 section 4.2).
    hooks = json.loads(projection.file(".cursor/hooks.json").content)["hooks"]
    commands = [item["command"] for items in hooks.values() for item in items]
    catalog = {
        event
        for event, items in hooks.items()
        if any("hook.citation-check" in item["command"] for item in items)
    }
    assert catalog == {"postToolUse", "afterFileEdit", "stop"}
    assert all(
        "hook.citation-check" in command or command.startswith("python .mission/hooks/signal ")
        for command in commands
    )
    assert projection.file(".mission/hooks/hook.citation-check/hook.py")
    assert projection.file(".cursor/skills/mission-control-observe/SKILL.md")
    # The independent verifier is its own sealed unit on the same lane and admission.
    verifier = CursorExecutionBinding.carried_by(templates["verifier"])
    assert verifier is not None and verifier.projections == executor.projections


def test_a_v1_cloud_node_without_a_reviewed_v1_environment_is_refused() -> None:
    bound = _v1_cloud_bound()
    assert bound.providers is not None and bound.providers.cursor_cloud is not None
    lane = type(bound.providers.cursor_cloud).model_validate(
        {**bound.providers.cursor_cloud.model_dump(mode="python"), "v1_environment": None}
    )
    unbound = bound.model_copy(
        update={"providers": bound.providers.model_copy(update={"cursor_cloud": lane})}
    )
    text = _mission("02-research-ingestion-cursor-cloud-chain.yml", _mission_two_research)
    refused = _refused(text, unbound)
    assert refused.pointer == "/mission/environment/lane"
    assert "v1_environment" in str(refused)


MISSION_THREE = "03-codebase-feature-cursor-local.yml"
AI_ENGINEER = canonical_scope("tenant-1", "ai-engineer")


def _mission_three_executors_removed(document: dict[str, Any]) -> None:
    """FIXTURE transform: Mission 3 without its two deterministic executors (governed tools
    have no Cursor projection; see the refusal test), its verifier still on Deep Agents."""

    mission = document["mission"]
    executors = {item["as"] for item in mission["environment"].pop("capabilities")}
    program = mission["program"]
    program["action_space"] = [item for item in program["action_space"] if item not in executors]


def _mission_three_without_executors(document: dict[str, Any]) -> None:
    """FIXTURE transform: `_mission_three_executors_removed` with its independent verifier
    moved onto the mission's Cursor lane: on Deep Agents, as authored, it is refused (see
    `test_the_deep_agents_verifiers_as_authored_are_refused`)."""

    _mission_three_executors_removed(document)
    document["mission"]["program"]["verifier"].pop("environment")


def test_mission_three_launches_on_cursor_local_with_its_hook_and_plugin(
    custody: BundleMaterializer,
) -> None:
    text = _mission(MISSION_THREE, _mission_three_without_executors)
    templates, rows = _launched_on_cursor(text, _v1_local_bound(), custody, AI_ENGINEER)
    executor = CursorExecutionBinding.carried_by(templates["executor"])
    assert executor is not None and executor.lane_profile == "cursor_local"
    assert executor.schema_version == "mc.cursor_binding.v2"
    projections = executor.projections
    (hook,) = projections.hook_script_pins
    (plugin,) = projections.plugin_pins
    assert hook.startswith("hook.shell-policy@") and plugin.startswith("plugin.agent-browser@")
    # The plugin is pinned whole: the members compile expanded from it are not pinned again.
    (skill,) = projections.skills
    assert skill.startswith("skill.mission-control-observe@")
    assert projections.mcp_servers == () and len(executor.inline_subagents) == 1
    projection = _rendered_at_prepare(templates["executor"], rows)
    ((expanded, members),) = projection.report.plugin_expansions
    assert expanded == plugin
    assert [item.partition("@")[0] for item in members] == [
        "skill.agent-browser",
        "mcp.agent-browser",
    ]
    assert projection.file(".cursor/skills/agent-browser/SKILL.md")
    # Kernel Hooks first, then the fail-closed catalog shell policy on beforeShellExecution.
    hooks = json.loads(projection.file(".cursor/hooks.json").content)["hooks"]
    shell = hooks["beforeShellExecution"]
    assert all(item["failClosed"] is True for item in shell)
    assert "hook.shell-policy" in shell[-1]["command"]
    assert all("kernel.py" in item["command"] for item in shell[:-1])
    # The plugin expansion is pinned: a binding sealed with another expansion is drift.
    drifted = executor.model_copy(
        update={
            "projections": projections.model_copy(
                update={"plugin_expansion_digest": "sha256:" + "0" * 64}
            )
        }
    )
    with pytest.raises(LaneProjectionError, match="plugin_expansion_digest"):
        verify_projection(drifted, projection_digests(projection))


def test_mission_three_as_authored_is_refused_at_its_deterministic_executors() -> None:
    """Mission 3 (cursor_local, v1) as authored: its repository must be bound, then its
    deterministic executors are refused (governed tools have no Cursor projection), while the
    hook and the plugin before them bind."""

    text = (MISSIONS / MISSION_THREE).read_text(encoding="utf-8")
    compilation = compile_yaml(text, AI_ENGINEER)
    assert compilation.ok
    refused = _refused_in(compilation, None)
    assert refused.pointer == "/mission/environment/workspace/repo"
    refused = _refused_in(compilation, _v1_local_bound())
    assert refused.pointer == "/mission/environment/capabilities/0"
    assert "deterministic_executor has no cursor_local launch binding" in str(refused)


def _verifier_sandboxed(document: dict[str, Any]) -> None:
    """FIXTURE: a sandbox profile the example deployment binds, on the verifier environment."""

    document["mission"]["program"]["verifier"]["environment"]["sandbox"] = {
        "profile": "research.standard"
    }


def _bindable_kinds_dropped(document: dict[str, Any]) -> None:
    """FIXTURE: no MCP servers and no Skills, the kinds a deployment can bind on Deep Agents
    (mc.manifest_launch_bindings.v1 capabilities; the example file binds none)."""

    mission = document["mission"]
    dropped = {item["as"] for item in mission["environment"].pop("capabilities", ())}
    mission["environment"]["workspace"].pop("skills")
    program = mission["program"]
    program["action_space"] = [item for item in program["action_space"] if item not in dropped]


def _hooks_dropped(document: dict[str, Any]) -> None:
    """FIXTURE: no hook scripts or plugins either, so the inherited subagent profile is
    reached; the action space loses the aliases those entries provided."""

    mission = document["mission"]
    dropped = {
        item.get("as")
        for group in ("hooks", "plugins")
        for item in mission["environment"].pop(group, ()) or ()
        if isinstance(item, dict)
    }
    program = mission["program"]
    program["action_space"] = [item for item in program["action_space"] if item not in dropped]


@pytest.mark.parametrize(
    ("name", "member", "bound", "scope"),
    [
        (
            "02-research-ingestion-cursor-cloud-chain.yml",
            _mission_two_member,
            _v1_cloud_bound,
            SCOPE,
        ),
        (MISSION_THREE, _mission_three_executors_removed, _v1_local_bound, AI_ENGINEER),
    ],
    ids=["mission-2", "mission-3"],
)
def test_the_deep_agents_verifiers_as_authored_are_refused(
    custody: BundleMaterializer,
    name: str,
    member: Any,
    bound: Any,
    scope: str,
) -> None:
    """Both missions author `verifier: {independent: true, environment: {lane: deep_agents}}`.
    The Cursor executor binds; the Deep Agents verifier inherits the mission environment and
    is refused, in order: no sandbox profile; then the inherited MCP servers and Skills, which
    the example deployment binds no component for; then the inherited hook scripts, which no
    Deep Agents launch binding can carry (nor plugins). With those dropped, the inherited
    subagent profile launches: the Deep Agents lane adapter reads it from its catalog row and
    seals it as an exact child (P1-S3)."""

    def refused(*changes: Any) -> ManifestLaunchBindingError:
        def change(document: dict[str, Any]) -> None:
            for item in (member, *changes):
                item(document)

        with pytest.raises(ManifestLaunchBindingError) as raised:
            _launched_on_cursor(_mission(name, change), bound(), custody, scope)
        return raised.value

    first = refused()
    assert first.pointer == "/mission/environment/sandbox/profile"
    assert "no sandbox profile is bound" in str(first)
    second = refused(_verifier_sandboxed)
    assert second.pointer.startswith(
        ("/mission/environment/capabilities/", "/mission/environment/workspace/skills/")
    )
    assert "has no deployment component binding" in str(second)
    third = refused(_verifier_sandboxed, _bindable_kinds_dropped)
    assert third.pointer == "/mission/environment/hooks/0"
    assert " hook " in str(third)
    assert "plugins and context bundles have no Deep Agents launch binding" in str(third)

    # With nothing left that the lane refuses, the inherited subagent profile is read from
    # its catalog row and becomes an exact in-process child, with a signed receipt.
    def launched(document: dict[str, Any]) -> None:
        for item in (member, _verifier_sandboxed, _bindable_kinds_dropped, _hooks_dropped):
            item(document)

    templates, _rows = _launched_on_cursor(_mission(name, launched), bound(), custody, scope)
    verifier = DeepAgentExecutionBinding.carried_by(templates["verifier"])
    assert verifier is not None
    assert [child.name for child in verifier.sync_subagents] == [
        item.name
        for item in (
            verifier.materialization_receipt.items if verifier.materialization_receipt else ()
        )
        if item.kind == "subagent"
    ]
    assert len(verifier.sync_subagents) == 1
    child = verifier.sync_subagents[0]
    assert child.system_prompt is not None
    assert verifier.cognitive_state_schema.subagent_slices[0].slice_id == child.state_slice_id


def _hooks_only_dropped(document: dict[str, Any]) -> None:
    """FIXTURE: no hook scripts, the plugin kept (the action space loses the hook aliases)."""

    mission = document["mission"]
    dropped = {item.get("as") for item in mission["environment"].pop("hooks", ()) or ()}
    program = mission["program"]
    program["action_space"] = [item for item in program["action_space"] if item not in dropped]


def test_a_deep_agents_node_plugin_is_refused_at_its_row(custody: BundleMaterializer) -> None:
    """OC-R1: a node-level plugin has no Deep Agents launch binding; the refusal names the
    plugin row and its pin, after the hook scripts, as before the resolution seam."""

    def change(document: dict[str, Any]) -> None:
        for item in (
            _mission_three_executors_removed,
            _verifier_sandboxed,
            _bindable_kinds_dropped,
            _hooks_only_dropped,
        ):
            item(document)

    with pytest.raises(ManifestLaunchBindingError) as raised:
        _launched_on_cursor(
            _mission(MISSION_THREE, change), _v1_local_bound(), custody, AI_ENGINEER
        )
    assert raised.value.pointer == "/mission/environment/plugins/0"
    assert str(raised.value).split(": ", 1)[1].startswith("plugin ")
    assert "plugins and context bundles have no Deep Agents launch binding" in str(raised.value)


def _refused_in(compilation: Any, bound: ManifestLaunchBindings | None) -> Any:
    (definition,), (program,) = compilation.definitions, compilation.programs
    admitted = AdmittedLaunch.from_configuration(AI_ENGINEER, "run-v1", program.configuration)
    with pytest.raises(ManifestLaunchBindingError) as raised:
        resolver(bound).goal_templates(definition, admitted)
    return raised.value


# --- Refusals name the manifest pointer ----------------------------------------------------------


def test_a_bindings_file_without_cursor_entries_refuses_at_the_lane() -> None:
    for path in (LOCAL, CLOUD):
        for bound in (
            ManifestLaunchBindings.load(V1_BINDINGS),
            bindings().model_copy(update={"providers": ProviderLanes()}),
        ):
            refused = _refused(path.read_text(encoding="utf-8"), bound)
            assert refused.pointer == "/mission/environment/lane"
            assert f"providers.{PROFILE_OF[path]}" in str(refused)


@pytest.mark.parametrize(
    ("path", "section", "pointer"),
    [
        (LOCAL, "model_profiles", "/mission/environment/model/profile"),
        (LOCAL, "auth_profiles", "/mission/environment/auth/profile"),
        (LOCAL, "host_profiles", "/mission/environment/execution_environment/profile"),
        (LOCAL, "repositories", "/mission/environment/workspace/repo"),
        (CLOUD, "model_profiles", "/mission/environment/model/profile"),
        (CLOUD, "auth_profiles", "/mission/environment/auth/profile"),
        (CLOUD, "repositories", "/mission/environment/workspace/repo"),
    ],
)
def test_an_unbound_selection_fails_at_its_manifest_pointer(
    path: Path, section: str, pointer: str
) -> None:
    refused = _refused(path.read_text("utf-8"), _without_lane(PROFILE_OF[path], **{section: {}}))
    assert refused.pointer == pointer, refused


def test_an_unbound_cloud_environment_or_revision_fails_at_its_pointer() -> None:
    bound = bindings()
    assert bound.providers is not None and bound.providers.cursor_cloud is not None
    lane = bound.providers.cursor_cloud
    unbound = _without_lane("cursor_cloud", environments={}, v1_environment=None)
    refused = _refused(CLOUD.read_text("utf-8"), unbound)
    assert refused.pointer == "/mission/environment/execution_environment/environment_ref"

    def pinned(document: dict[str, Any]) -> None:
        execution = document["mission"]["environment"]["execution_environment"]
        execution["expected_revision"] = "sha256:" + "1" * 64

    refused = _refused(edited(CLOUD, pinned))
    assert refused.pointer == "/mission/environment/execution_environment/expected_revision"
    assert lane.environments["cursor-cloud.default"].environment.expected_revision in str(refused)


def test_a_disallowed_ref_and_an_unmapped_model_setting_fail_at_their_pointers() -> None:
    def feature_branch(document: dict[str, Any]) -> None:
        document["mission"]["environment"]["workspace"]["repo"]["ref"] = "feature/x"

    refused = _refused(edited(LOCAL, feature_branch))
    assert refused.pointer == "/mission/environment/workspace/repo/ref"

    def effort(document: dict[str, Any]) -> None:
        document["mission"]["environment"]["model"]["settings"] = {"reasoning": {"effort": "high"}}

    refused = _refused(edited(CLOUD, effort))
    assert refused.pointer == "/mission/environment/model/settings/reasoning/effort"


def test_a_selected_capability_needs_its_projection_row() -> None:
    refused = _refused(edited(LOCAL, _with_catalog_capabilities))
    assert refused.pointer == "/mission/environment/capabilities/0"
    assert "no projection row" in str(refused)


def test_a_selection_without_a_kind_takes_the_slot_of_its_resolved_row() -> None:
    """A capability selected without a declared kind is classified by its resolved row: a
    hook script row lands in the binding's hook-script pins."""

    compilation = compiled_ok(edited(LOCAL, _with_catalog_capabilities))
    (definition,) = compilation.definitions
    pins = provider_capability_pins(definition)
    rows = {pins[0]: hook_row(), pins[1]: verifier_row()}
    # Strip the declared kinds: only the row can classify the selection now.
    stripped = MissionDefinition.model_validate(
        {
            **definition.model_dump(mode="json"),
            "capabilities": [
                {**item, "kind": None}
                for item in definition.model_dump(mode="json")["capabilities"]
            ],
        }
    )
    (program,) = compilation.programs
    admitted = AdmittedLaunch.from_configuration(SCOPE, "run-cursor", program.configuration)
    templates = resolver().stage_templates(stripped, admitted, rows=rows)
    sealed = [
        CursorExecutionBinding.carried_by(item)
        for item in templates.values()
        if CursorExecutionBinding.carried_by(item)
    ]
    assert sealed
    for binding in sealed:
        assert binding.projections.hook_script_pins == (pins[0],)
        assert binding.inline_subagents == (pins[1],)
        assert binding.projections.mcp_servers == ()


# --- The deployment file -------------------------------------------------------------------------


def test_the_bindings_file_pins_the_composed_cursor_adapter_additively() -> None:
    document = json.loads(BINDINGS.read_text(encoding="utf-8"))
    loaded = ManifestLaunchBindings.model_validate(document)
    assert loaded.providers is not None
    assert loaded.providers.cursor("cursor_local") is not None
    assert (
        loaded.providers.cursor("codex") is None and loaded.providers.lane("cursor_local") is None
    )

    wrong_pin = copy.deepcopy(document)
    wrong_pin["providers"]["cursor_local"]["pins"]["cursor_sdk"] = "1.0.36"
    with pytest.raises(ValueError, match="1.0.37"):
        ManifestLaunchBindings.model_validate(wrong_pin)

    no_callback = copy.deepcopy(document)
    no_callback["providers"]["cursor_local"].pop("hook_callback")
    with pytest.raises(ValueError):
        ManifestLaunchBindings.model_validate(no_callback)

    misnamed = copy.deepcopy(document)
    environments = misnamed["providers"]["cursor_cloud"]["environments"]
    environments["other"] = environments.pop("cursor-cloud.default")
    with pytest.raises(ValueError):
        ManifestLaunchBindings.model_validate(misnamed)

    swapped = copy.deepcopy(document)
    swapped["providers"]["cursor_local"] = document["providers"]["codex"]
    with pytest.raises(ValueError):
        ManifestLaunchBindings.model_validate(swapped)

    # Additive: a v2 file without Cursor entries dumps without them; a v1 file is unchanged.
    without = copy.deepcopy(document)
    for profile in ("cursor_local", "cursor_cloud"):
        without["providers"].pop(profile)
    dumped = ManifestLaunchBindings.model_validate(without).model_dump(mode="json")
    assert set(dumped["providers"]) == {"claude_agent_sdk", "codex"}
    v1 = ManifestLaunchBindings.load(V1_BINDINGS)
    assert v1.providers is None and "providers" not in v1.model_dump(mode="json")
    assert ManifestLaunchBindings.model_validate(loaded.model_dump(mode="json")) == loaded
