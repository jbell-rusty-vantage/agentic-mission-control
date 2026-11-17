"""Cognition Profile seeds are searchable, manifest-selectable and portable (MO-35)."""

import importlib.util
import json
from pathlib import Path

import pytest

from mission_control.application.capabilities.capability_search import CapabilitySearchService
from mission_control.bootstrap.host_projection import HOST_PROJECTORS
from mission_control.domain.agentic_components.projection import (
    BundleFile,
    ProjectionError,
    ResolvedCapability,
)
from mission_control.domain.authoring.contracts import (
    DefinitionKind,
    PluginDefinition,
    PublishedDefinition,
)
from mission_control.domain.authoring.manifest import load_manifest_yaml
from mission_control.domain.authoring.manifest_v2 import parse_manifest_any
from mission_control.domain.capabilities.host_support import (
    UNQUALIFIED_BY_DEFAULT,
    HostSupportStatus,
    LaneProfile,
)
from mission_control.domain.capabilities.pins import CapabilityPin
from mission_control.domain.coordinator.contracts import CapabilitySearchRequest
from mission_control_db_contract.seeds import load_bundles, order_bundles
from tests.fixtures.capability_search_catalog import build_catalog

ROOT = Path(__file__).resolve().parents[3]
SEEDS = ROOT / "packages/mission-control-db-contract/seeds"


def _module(name: str, filename: str):  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(name, SEEDS / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PROFILES = _module("mo35_profiles", "cognition_profiles.py")
GENERATOR = _module("mo35_generator", "generate_catalog_seeds.py")
# The eight-line knowledge skills revision 1 of the knowledge family mounted.
EIGHT_LINE_KNOWLEDGE = {
    f"skill.mc-cognition-{name}"
    for name in ("research", "cite-and-verify", "ingest", "knowledge-services")
}
SDLC = {f"skill.mc-cognition-{name}" for name in ("tdd", "code-review", "pr", "diagnosing-bugs")}
HOSTED = set(UNQUALIFIED_BY_DEFAULT)


@pytest.mark.parametrize("app", PROFILES.APPS)
def test_seed_members_are_exact_and_bounded_and_manifest_selectable(app: str) -> None:
    plugins = PROFILES.current_profiles(app)
    assert {entry["definition"].title for entry in plugins} == {
        "cognition/sdlc",
        "cognition/knowledge",
        "cognition/mixed",
    }
    for entry in plugins:
        plugin = entry["definition"]
        members = []
        for member, (selected, _key) in zip(plugin.manifest.members, entry["members"], strict=True):
            assert selected["pin"] == member.pin.render()
            files = (
                ()
                if selected["source"] is None
                else tuple(
                    BundleFile(path=path, content=data)
                    for path, data in selected["source"]["files"]
                )
            )
            members.append(
                ResolvedCapability(pin=member.pin, definition=selected["definition"], files=files)
            )
        row = ResolvedCapability(
            pin=CapabilityPin.parse(entry["pin"]), definition=plugin, members=tuple(members)
        )
        # A profile projects on every lane its matrix does not exclude, and is refused on the
        # others: the Biotech charter row declares the worker-hosted profiles only, so the
        # revision 2 plugins that pin it are unsupported on the provider-hosted ones.
        excluded = {
            lane
            for lane in LaneProfile
            if plugin.host_support.status(lane) is HostSupportStatus.UNSUPPORTED
        }
        # Revisions 3 and 4 of the knowledge family also pin the capture server, which no cloud
        # lane can reach, so they are unsupported on cursor_cloud too in both applications.
        expected = (
            HOSTED | {LaneProfile.CURSOR_CLOUD}
            if entry["revision"] in (3, 4)
            else HOSTED
            if (app, entry["revision"]) == ("biotech", 2)
            else set()
        )
        assert excluded == expected
        for lane in LaneProfile:
            if lane in excluded:
                with pytest.raises(ProjectionError, match="declares no support"):
                    HOST_PROJECTORS.render((row,), lane, "Preserve repository instructions.")
                continue
            projected = HOST_PROJECTORS.render((row,), lane, "Preserve repository instructions.")
            assert not projected.report.overflow
        assert len([m for m in plugin.manifest.members if m.role.value == "subagent"]) <= 4
        document = load_manifest_yaml(
            (ROOT / "tests/fixtures/manifests/minimal-stage-graph.yml").read_text()
        )
        document["manifest"] = "mission/v2"
        document["mission"]["application"] = app
        document["mission"]["environment"]["plugins"] = [{"pin": entry["pin"]}]
        assert parse_manifest_any(document).mission.environment.plugins[0].pin == entry["pin"]
        family = plugin.logical_id.removeprefix("plugin.cognition-")
        example = ROOT / "deployments/cognition-profiles" / f"{app}-{family}.mission.yml"
        authored = parse_manifest_any(load_manifest_yaml(example.read_text()))
        assert authored.mission.environment.plugins[0].pin == entry["pin"]
    bundles = load_bundles(
        [
            SEEDS / app / f"{PROFILES.APP_KEYS[app]}-{version}.json"
            for version in PROFILES.SEED_VERSIONS
        ]
    )
    assert len(bundles) == len(PROFILES.SEED_VERSIONS)


@pytest.mark.parametrize("family", ["sdlc", "knowledge", "mixed"])
async def test_catalog_search_finds_each_profile(family: str) -> None:
    definitions, search, _ = await build_catalog(directories=("ai-engineer",))
    service = CapabilitySearchService(search=search, definitions=definitions)
    response = await service.search(
        CapabilitySearchRequest(
            query=f"cognition/{family}",
            kinds=frozenset({DefinitionKind.PLUGIN}),
            tenant_scope="ai-engineer",
            limit=10,
        )
    )
    assert f"plugin.cognition-{family}" in {hit.exact_ref.logical_id for hit in response.hits}


def test_new_seed_json_agrees_with_sources_and_frozen_skills_are_untouched() -> None:
    for app in PROFILES.APPS:
        relative = f"{app}/{PROFILES.APP_KEYS[app]}-1.0.0.json"
        # Frozen by bytes since 1.0.1; its sources still produce the same definitions.
        payload = GENERATOR.frozen_bundle(relative)
        asset_definitions = [
            PublishedDefinition.model_validate(record["fields"]["manifest"]).definition
            for record in payload["records"]
            if record["kind"] == "asset_version"
        ]
        assert asset_definitions == [
            entry["definition"] for entry in PROFILES.application_definitions(app)
        ]


@pytest.mark.parametrize("app", PROFILES.APPS)
def test_revision_two_of_the_knowledge_family_mounts_the_method_skills(app: str) -> None:
    """Seed 1.0.1: `plugin.cognition-knowledge` and `plugin.cognition-mixed` at revision 2
    compose the imported research and evidence skills and the application's charter in place of
    the four eight-line knowledge skills; `plugin.cognition-sdlc` is not published again."""

    relative = f"{app}/{PROFILES.APP_KEYS[app]}-1.0.1.json"
    committed = json.loads((SEEDS / relative).read_bytes())
    # Frozen by bytes since 1.0.2 published revision 3 of the knowledge plugin.
    assert committed == GENERATOR.frozen_bundle(relative)
    assert committed["depends_on"] == [
        {"seed_key": f"mc.app.{app}.cognition-profiles", "seed_version": "1.0.0"},
        {"seed_key": f"mc.app.{app}.agent-skills", "seed_version": "1.0.5"},
    ]
    published = {
        row["fields"]["manifest"]["definition"]["logical_id"]: PublishedDefinition.model_validate(
            row["fields"]["manifest"]
        )
        for row in committed["records"]
        if row["kind"] == "asset_version"
    }
    assert set(published) == {"plugin.cognition-knowledge", "plugin.cognition-mixed"}
    charter = f"skill.{app}-knowledge-charter"
    method = ["skill.knowledge-research", "skill.knowledge-verify", charter]
    expected = {
        "plugin.cognition-knowledge": (set(), ["source-verifier", "summarizer"]),
        "plugin.cognition-mixed": (
            SDLC,
            ["reviewer", "test-runner", "source-verifier", "summarizer"],
        ),
    }
    # The rows of the agent-skill seed that was current when 1.0.1 shipped (1.0.5, frozen
    # since 1.0.6 re-imported the method skills).
    skill_pins = {
        entry["definition"].logical_id: entry["pin"]
        for entry in PROFILES._skills().definitions_as_of(app, "1.0.5")
    }
    for logical_id, (sdlc, agents) in expected.items():
        item = published[logical_id]
        plugin = item.definition
        assert isinstance(plugin, PluginDefinition)
        assert item.ref.revision == 2
        skills = [m.pin.capability_id for m in plugin.manifest.members if m.role.value == "skill"]
        assert set(skills) == sdlc | set(method)
        assert skills[-3:] == method
        assert not EIGHT_LINE_KNOWLEDGE & set(skills)
        assert [
            m.pin.capability_id for m in plugin.manifest.members if m.role.value == "subagent"
        ] == [f"subagent.mc-cognition-{name}" for name in agents]
        # Exact pins of the rows the agent-skill seeds publish for this application.
        for member in plugin.manifest.members:
            if member.pin.capability_id in method:
                assert member.pin.render() == skill_pins[member.pin.capability_id]
        # The intersection of its members' support: the worker-hosted profiles, and on the
        # provider-hosted ones what its weakest member declares (the imported skills are
        # unqualified there; the Biotech charter row does not declare them).
        assert set(plugin.host_support.supported_profiles()) == set(LaneProfile) - HOSTED
        hosted = {plugin.host_support.status(lane) for lane in HOSTED}
        assert hosted == {
            HostSupportStatus.UNQUALIFIED if app == "ai-engineer" else HostSupportStatus.UNSUPPORTED
        }
        assert len(plugin.description.splitlines()) == 1
    # Each member row names a row inside the dependency closure of this application's seeds.
    order_bundles(load_bundles([SEEDS / "common", SEEDS / app]), already_applied=set())
    rows = [row for row in committed["records"] if row["kind"] == "capability_plugin_member"]
    knowledge = [row for row in rows if row["fields"]["plugin"].endswith("cognition-knowledge/2")]
    assert [row["fields"]["member"] for row in knowledge][:2] == [
        "agent-skill:skill:skill.knowledge-research/1",
        "agent-skill:skill:skill.knowledge-verify/1",
    ]
    assert knowledge[2]["fields"]["member"] == (
        f"agent-skill:skill:{charter}/{2 if app == 'ai-engineer' else 1}"
    )


def _plugin(relative: str, logical_id: str) -> PublishedDefinition:
    (item,) = [
        PublishedDefinition.model_validate(row["fields"]["manifest"])
        for row in GENERATOR.frozen_bundle(relative)["records"]
        if row["kind"] == "asset_version"
        and row["fields"]["manifest"]["ref"]["logical_id"] == logical_id
    ]
    return item


@pytest.mark.parametrize("app", PROFILES.APPS)
def test_revision_three_of_the_knowledge_family_also_mounts_the_capture_server(app: str) -> None:
    """Seed 1.0.2: `plugin.cognition-knowledge` at revision 3 is revision 2 plus the evidence
    capture server at its revision 2, by exact pin, between the skills and the subagents. The
    mission that mounts the research method ("capture every source you rely on") mounts the
    capture tools with it. Supported where the capture server is: `deep_agents`. Frozen by bytes
    since 1.0.3 published revision 4."""

    relative = f"{app}/{PROFILES.APP_KEYS[app]}-1.0.2.json"
    committed = json.loads((SEEDS / relative).read_bytes())
    assert committed == GENERATOR.frozen_bundle(relative)
    assert committed["depends_on"] == [
        {"seed_key": f"mc.app.{app}.cognition-profiles", "seed_version": "1.0.1"},
        {"seed_key": f"mc.app.{app}.agent-skills", "seed_version": "1.0.5"},
        {"seed_key": "mc.catalog.agent-capabilities", "seed_version": "1.2.0"},
    ]
    item = _plugin(relative, "plugin.cognition-knowledge")
    plugin = item.definition
    assert isinstance(plugin, PluginDefinition)
    assert item.ref.revision == 3
    prior = _plugin(
        f"{app}/{PROFILES.APP_KEYS[app]}-1.0.1.json", "plugin.cognition-knowledge"
    ).definition
    assert isinstance(prior, PluginDefinition)
    capture_pin = PROFILES._capabilities().capture_pin(2)
    added = [m for m in plugin.manifest.members if m not in prior.manifest.members]
    assert [(m.pin.render(), m.role.value, m.optional) for m in added] == [
        (capture_pin, "mcp_server", False)
    ]
    assert [m for m in plugin.manifest.members if m.role.value != "mcp_server"] == list(
        prior.manifest.members
    )
    assert plugin.host_support.supported_profiles() == (LaneProfile.DEEP_AGENTS,)
    rows = [row for row in committed["records"] if row["kind"] == "capability_plugin_member"]
    assert [row["fields"]["member"] for row in rows if row["fields"]["role"] == "mcp_server"] == [
        "agent-capability:mcp-server:mcp.knowledge-capture/2"
    ]


@pytest.mark.parametrize("app", PROFILES.APPS)
def test_revision_four_of_the_knowledge_family_mounts_the_chain_method_and_tools(
    app: str,
) -> None:
    """Seed 1.0.3: `plugin.cognition-knowledge` at revision 4 has revision 3's member shape
    over the method skills re-imported at Knowledge Services 1a451fd (agent-skills 1.0.6) and
    the capture server at revision 3 (agent-capabilities 1.3.0), whose allowlist carries the
    tools that method names. The mission that mounts the research method mounts the tools it
    routes a capture through: source_prepare_captured, evidence_units and chain_write."""

    relative = f"{app}/{PROFILES.APP_KEYS[app]}-1.0.3.json"
    committed = json.loads((SEEDS / relative).read_bytes())
    assert committed == GENERATOR.cognition_profiles()[relative]
    assert committed["depends_on"] == [
        {"seed_key": f"mc.app.{app}.cognition-profiles", "seed_version": "1.0.2"},
        {"seed_key": f"mc.app.{app}.agent-skills", "seed_version": "1.0.6"},
        {"seed_key": "mc.catalog.agent-capabilities", "seed_version": "1.3.0"},
    ]
    (item,) = [
        PublishedDefinition.model_validate(row["fields"]["manifest"])
        for row in committed["records"]
        if row["kind"] == "asset_version"
    ]
    plugin = item.definition
    assert isinstance(plugin, PluginDefinition)
    assert (item.ref.logical_id, item.ref.revision) == ("plugin.cognition-knowledge", 4)
    third = _plugin(
        f"{app}/{PROFILES.APP_KEYS[app]}-1.0.2.json", "plugin.cognition-knowledge"
    ).definition
    assert isinstance(third, PluginDefinition)
    assert [m.role.value for m in plugin.manifest.members] == [
        m.role.value for m in third.manifest.members
    ]
    assert [m.pin.capability_id for m in plugin.manifest.members] == [
        m.pin.capability_id for m in third.manifest.members
    ]
    skills = PROFILES._skills()
    current = {
        entry["definition"].logical_id: entry["pin"]
        for entry in skills.application_definitions(app)
    }
    charter = f"skill.{app}-knowledge-charter"
    for member in plugin.manifest.members:
        if member.role.value == "skill":
            assert member.pin.render() == current[member.pin.capability_id]
    (capture,) = [m for m in plugin.manifest.members if m.role.value == "mcp_server"]
    capabilities = PROFILES._capabilities()
    assert capture.pin.render() == capabilities.capture_pin(3)
    server = capabilities.server_definition(capabilities.CAPTURE_SERVER_R3)
    assert {"source_prepare_captured", "evidence_units", "chain_write"} <= set(
        server.tool_allowlist or ()
    )
    research = next(
        entry
        for entry in skills.application_definitions(app)
        if entry["definition"].logical_id == "skill.knowledge-research"
    )
    text = b"".join(content for _path, content in research["source"]["files"]).decode("utf-8")
    for tool in ("source_prepare_captured", "evidence_units", "chain_write"):
        assert tool in text
    assert plugin.host_support.supported_profiles() == (LaneProfile.DEEP_AGENTS,)
    assert plugin.host_support.status("cursor_cloud") is HostSupportStatus.UNSUPPORTED
    assert plugin.secret_refs == ("VERIFY_EXECUTOR_TOKEN",)
    assert len(plugin.description.splitlines()) == 1
    order_bundles(load_bundles([SEEDS / "common", SEEDS / app]), already_applied=set())
    rows = [row for row in committed["records"] if row["kind"] == "capability_plugin_member"]
    members = [row["fields"]["member"] for row in rows]
    assert members[:3] == [
        "agent-skill:skill:skill.knowledge-research/2",
        "agent-skill:skill:skill.knowledge-verify/2",
        f"agent-skill:skill:{charter}/{3 if app == 'ai-engineer' else 1}",
    ]
    assert [row["fields"]["member"] for row in rows if row["fields"]["role"] == "mcp_server"] == [
        "agent-capability:mcp-server:mcp.knowledge-capture/3"
    ]
    assert {row["fields"]["plugin"] for row in rows} == {
        "cognition-profile:plugin:plugin.cognition-knowledge/4"
    }
