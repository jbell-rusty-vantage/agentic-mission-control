"""Cognition Profile seeds are searchable, manifest-selectable and portable (MO-35)."""

import importlib.util
import json
from pathlib import Path

import pytest

from mission_control.application.capabilities.capability_search import CapabilitySearchService
from mission_control.bootstrap.host_projection import HOST_PROJECTORS
from mission_control.domain.agentic_components.projection import BundleFile, ResolvedCapability
from mission_control.domain.authoring.contracts import (
    DefinitionKind,
    PluginDefinition,
    PublishedDefinition,
)
from mission_control.domain.authoring.manifest import load_manifest_yaml
from mission_control.domain.authoring.manifest_v2 import parse_manifest_any
from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.capabilities.pins import CapabilityPin
from mission_control.domain.coordinator.contracts import CapabilitySearchRequest
from mission_control_db_contract.seeds import load_bundles
from tests.fixtures.capability_search_catalog import build_catalog

ROOT = Path(__file__).resolve().parents[3]
SEEDS = ROOT / "packages/mission-control-db-contract/seeds"
spec = importlib.util.spec_from_file_location("mo35_profiles", SEEDS / "cognition_profiles.py")
assert spec is not None and spec.loader is not None
PROFILES = importlib.util.module_from_spec(spec)
spec.loader.exec_module(PROFILES)


@pytest.mark.parametrize("app", PROFILES.APPS)
def test_seed_members_are_exact_and_bounded_and_manifest_selectable(app: str) -> None:
    entries = PROFILES.application_definitions(app)
    by_pin = {entry["pin"]: entry for entry in entries}
    plugins = [entry for entry in entries if isinstance(entry["definition"], PluginDefinition)]
    assert {entry["definition"].title for entry in plugins} == {
        "cognition/sdlc",
        "cognition/knowledge",
        "cognition/mixed",
    }
    for entry in plugins:
        plugin = entry["definition"]
        members = []
        for member in plugin.manifest.members:
            selected = by_pin[member.pin.render()]
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
        for lane in LaneProfile:
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
    bundles = load_bundles([SEEDS / app / f"{PROFILES.APP_KEYS[app]}-1.0.0.json"])
    assert len(bundles) == 1


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
        payload = json.loads((SEEDS / app / f"{PROFILES.APP_KEYS[app]}-1.0.0.json").read_bytes())
        asset_definitions = [
            PublishedDefinition.model_validate(record["fields"]["manifest"]).definition
            for record in payload["records"]
            if record["kind"] == "asset_version"
        ]
        assert asset_definitions == [
            entry["definition"] for entry in PROFILES.application_definitions(app)
        ]
