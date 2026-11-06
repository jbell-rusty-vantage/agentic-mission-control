"""P5a: a plugin selected on a claude/codex lane is pinned whole, like the Cursor binding.

Compile expands a selected plugin into its members (``.../plugins/0/members/<n>``); the plugin's
projection row carries those members and the Host Projection (``HostProjectors.render``) expands
them. The launch author pins the plugin alone in ``mc.execution_binding.v2`` (a member pinned
beside it would be expanded twice and refused as a duplicate at render), the worker's
``ProviderBindingRows`` re-resolves the plugin row and ``prepare`` renders every member exactly
once under the sealed
digest. A member the author also selects explicitly beside its plugin stays a refused
duplicate naming both selections.

Offline: the fixture catalog (with the seeded ``plugin.cognition-sdlc``: four Skills and two
subagent profiles) and the seeded Skill bundles in a local digest-path custody store.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from mission_control.application.agentic_components.materialization import projection_digest
from mission_control.application.agentic_components.placement import RenderedProjectionSource
from mission_control.application.authoring.manifest_launch_inputs import (
    ManifestLaunchBindingError,
    provider_capability_pins,
)
from mission_control.application.authoring.provider_launch import (
    CatalogProjectionRows,
    ProviderBindingRows,
    binding_capability_pins,
)
from mission_control.application.capabilities.bundle_custody import BundleMaterializer
from mission_control.bootstrap.bundle_custody import compose_bundle_materializer
from mission_control.bootstrap.host_projection import HOST_PROJECTORS
from mission_control.bootstrap.settings import Settings
from mission_control.domain.authoring.contracts import PluginDefinition
from mission_control.domain.capabilities.catalog_entry import capability_pin
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from tests.fixtures.catalog.fast_track_catalog import fast_track_catalog
from tests.unit.authoring.test_manifest_cursor_launch import seeds_publish_module
from tests.unit.authoring.test_manifest_v2_launch import (
    SCOPE,
    compiled_ok,
    edited,
    example,
    stub_author,
)

PLUGIN = "plugin.cognition-sdlc"
REVIEWER = "subagent.mc-cognition-reviewer"
PROFILES = ("claude_agent_sdk", "codex")
MEMBER_SKILLS = (
    "mc-cognition-code-review",
    "mc-cognition-diagnosing-bugs",
    "mc-cognition-pr",
    "mc-cognition-tdd",
)
MEMBER_AGENTS = ("mc-reviewer", "mc-test-runner")  # the subagent profiles' rendered names
HOST_DIRS = {
    "claude_agent_sdk": (".claude/skills", ".claude/agents", ".md"),
    "codex": (".agents/skills", ".codex/agents", ".toml"),
}


@pytest.fixture(scope="module")
def custody(tmp_path_factory: pytest.TempPathFactory) -> BundleMaterializer:
    """The seeded Skill bundles (biotech digests, which the fixture catalog carries) in a local
    digest-path store, read through the composed local custody."""

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


def _published() -> tuple[Any, dict[str, Any]]:
    definitions, _search = asyncio.run(fast_track_catalog())
    rows = asyncio.run(definitions.list_published_definitions())
    return definitions, {item.ref.logical_id: item for item in rows}


def _plugin_only(plugin: str, *, explicit: str | None = None) -> Any:
    """Select only the plugin mission-wide (optionally one of its members explicitly too).
    Goal Loop criteria are accepted by human review and outputs are optional, so a launch
    reaches its capability rows."""

    def change(document: dict[str, Any]) -> None:
        mission = document["mission"]
        mission["environment"]["plugins"] = [{"pin": plugin}]
        if explicit is not None:
            mission["environment"]["agents"] = [{"pin": explicit, "as": "reviewer"}]
        for goal in mission["goals"]:
            for criterion in goal["criteria"]:
                criterion["acceptance"] = {"human": "review_accept"}
        for output in mission["program"]["outputs"]:
            output["enforcement"] = "optional"

    return change


def _launch(
    profile: str, custody: BundleMaterializer, *, explicit_member: bool = False
) -> tuple[dict[str, Any], str, tuple[str, ...], Any]:
    """Compile a Goal Loop on ``profile`` selecting the plugin, then run the launch author
    (``bind``: projection rows through custody, then the resolver) as ``missions:start`` does."""

    definitions, published = _published()
    plugin = published[PLUGIN]
    assert isinstance(plugin.definition, PluginDefinition)
    plugin_pin = capability_pin(plugin).render()
    members = tuple(member.pin.render() for member in plugin.definition.manifest.members)
    reviewer = next(item for item in members if item.startswith(f"{REVIEWER}@"))
    change = _plugin_only(plugin_pin, explicit=reviewer if explicit_member else None)
    compilation = compiled_ok(edited(example(profile, "goal-loop"), change))
    (definition,), (program,) = compilation.definitions, compilation.programs
    # Compile lists the plugin and the members it expanded.
    pointers = {
        item.pointer
        for item in definition.capabilities
        if item.pointer.startswith("/mission/environment/plugins/0")
    }
    assert pointers == {
        "/mission/environment/plugins/0",
        *(f"/mission/environment/plugins/0/members/{index}" for index in range(len(members))),
    } - ({"/mission/environment/plugins/0/members/4"} if explicit_member else set())
    persisted: list[dict[str, Any]] = []
    author = stub_author(
        definition,
        program,
        projection_rows=CatalogProjectionRows(definitions, bundles=custody),
        persisted=persisted,
    )
    templates = asyncio.run(author.bind(SCOPE, "run-p5a", family="GoalDirected"))
    return templates, plugin_pin, members, (definitions, definition)


@pytest.mark.parametrize("profile", PROFILES)
def test_a_plugin_only_selection_pins_the_plugin_whole_and_renders_each_member_once(
    profile: str, custody: BundleMaterializer
) -> None:
    templates, plugin_pin, members, (definitions, definition) = _launch(profile, custody)
    # The launch asks only for the plugin row: it carries and expands its members.
    assert provider_capability_pins(definition) == (plugin_pin,)
    assert sorted(item.partition("@")[0] for item in members) == sorted(
        (
            *(f"skill.{name}" for name in MEMBER_SKILLS),
            REVIEWER,
            "subagent.mc-cognition-test-runner",
        )
    )
    for role in ("executor", "verifier"):
        template = templates[role]
        binding = ProviderExecutionBinding.carried_by(template)
        assert binding is not None and binding.lane_profile == profile
        capability_keys = [key for key in binding.pins if key.startswith("capability.")]
        assert capability_keys == [f"capability.plugin.{PLUGIN}"]
        assert binding_capability_pins(binding.pins) == (plugin_pin,)

        # Prepare: the worker re-resolves the plugin row and recomputes the sealed digest.
        asked: list[tuple[str, ...]] = []
        catalog = CatalogProjectionRows(definitions, bundles=custody)

        async def port(pins: Any, catalog: Any = catalog, asked: Any = asked) -> Any:
            asked.append(tuple(pins))
            return await catalog(pins)

        worker = RenderedProjectionSource(ProviderBindingRows(port), projectors=HOST_PROJECTORS)
        projection = asyncio.run(worker.project(template, profile=profile, packet_index=None))
        assert asked == [(plugin_pin,)]
        assert projection_digest(projection) == binding.materialization_digest
        ((expanded, taken),) = projection.report.plugin_expansions
        assert expanded == plugin_pin and taken == members
        assert projection.report.skipped_members == ()

        # Every member lands exactly once: the four Skills and both subagent profiles (beside
        # them only the lane's kernel files, such as the `mc-signals` telemetry Skill).
        paths = Counter(item.path for item in projection.files)
        assert all(count == 1 for count in paths.values())
        skills_root, agents_root, suffix = HOST_DIRS[profile]
        skill_dirs = Counter(
            Path(path).parent.name
            for path in paths
            if path.startswith(f"{skills_root}/") and Path(path).name == "SKILL.md"
        )
        assert {name: skill_dirs[name] for name in MEMBER_SKILLS} == dict.fromkeys(MEMBER_SKILLS, 1)
        assert set(skill_dirs) - set(MEMBER_SKILLS) <= {"mc-signals"}
        agent_files = sorted(path for path in paths if path.startswith(f"{agents_root}/"))
        assert agent_files == [f"{agents_root}/{name}{suffix}" for name in MEMBER_AGENTS]


def test_a_member_selected_beside_its_plugin_is_refused_as_a_duplicate_naming_both(
    custody: BundleMaterializer,
) -> None:
    """Selecting a plugin and one of its members explicitly is an authoring error: the
    explicit member stays pinned, the plugin expands it again and render refuses it."""

    with pytest.raises(ManifestLaunchBindingError) as refused:
        _launch("claude_agent_sdk", custody, explicit_member=True)
    message = str(refused.value)
    assert refused.value.pointer == "/mission/environment/lane"
    assert "capability selected more than once" in message
    assert f"{REVIEWER}@" in message and f"{PLUGIN}@" in message
