"""MO-12: the Environment Kit capability kind, its catalog row, seeds and search text."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from mission_control.adapters.postgres.control_plane.catalog_assets import ASSET_KIND
from mission_control.application.capabilities.bundle_custody import bundle_definition
from mission_control.application.environments.kits import (
    CatalogEnvironmentInputs,
    EnvironmentKitCatalog,
)
from mission_control.domain.authoring.contracts import (
    DefinitionKind,
    EnvironmentKitDefinition,
)
from mission_control.domain.authoring.environment_kits import (
    BASE_LAYER_OVERLAY,
    LOCAL_PROFILES,
    EnvironmentKitManifest,
    KitHostSupport,
)
from mission_control.domain.capabilities.bundles import build_bundle_manifest
from mission_control.domain.capabilities.catalog_entry import summarize
from mission_control.domain.capabilities.host_support import (
    AgentCapabilityKind,
    CapabilityHostSupport,
    HostSupportStatus,
)
from mission_control.domain.coordinator.search_document import (
    render_search_document,
    search_document_source,
)
from tests.fixtures.environment_kits import (
    StaticDefinitions,
    kit_document,
    kit_files,
    kit_pin,
    published_kit,
)

ROOT = Path(__file__).resolve().parents[3]
SEEDS = ROOT / "packages" / "mission-control-db-contract" / "seeds"
STARTER_KITS = {
    "envkit.python-uv",
    "envkit.node",
    "envkit.python-uv-node",
    "envkit.mission-control-dev",
    "envkit.knowledge-research",
    "envkit.biotech-backend",
}


def _module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


KITS = _module("mo12_environment_kits", SEEDS / "environment_kits.py")


# --- the manifest ---------------------------------------------------------------------------


def test_requires_parses_optional_secrets_and_host_support_maps_to_the_catalog_matrix() -> None:
    kit = EnvironmentKitManifest.model_validate(kit_document())
    assert [(item.name, item.optional) for item in kit.requires.secrets] == [
        ("FIXTURE_SETUP_TOKEN", True)
    ]
    support = kit.capability_host_support()
    # The worker's prepare step runs the entrypoint on every local lane.
    assert support.status("claude_agent_sdk") == HostSupportStatus.SUPPORTED
    assert support.status("codex") == HostSupportStatus.SUPPORTED
    assert support.status("cursor_local") == HostSupportStatus.SUPPORTED
    # Declared but unproven: hosted base layers are undrilled.
    assert support.status("cursor_cloud") == HostSupportStatus.UNQUALIFIED
    assert support.overlay("cursor_cloud") == {BASE_LAYER_OVERLAY: "mission_control"}
    assert support.overlay("claude_cloud") == {BASE_LAYER_OVERLAY: "owner"}
    assert support.status("codex_cloud") == HostSupportStatus.UNSUPPORTED
    assert support.status("deep_agents") == HostSupportStatus.UNSUPPORTED
    support.validate_for(AgentCapabilityKind.ENVIRONMENT_KIT)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"toolchains": {"ruby": "3"}}, "unknown toolchain"),
        ({"toolchains": {"python": "3.12; rm -rf /"}}, "invalid python version"),
        ({"host_support": {"deep_agents": "full"}}, "unknown kit host"),
        ({"host_support": {"local": "base_via_owner"}}, "never via owner"),
        ({"host_support": {"claude_cloud": "full"}}, "no base layer on claude_cloud"),
        ({"host_support": {"codex_cloud": "full"}}, "sync is cursor_cloud only"),
        ({"system_packages": ["jq; curl"]}, "invalid system package"),
        (
            {"mission": {"steps": [{"name": "deps", "run": "uv sync", "when": "uv.lock"}]}},
            "exists",
        ),
        (
            {"mission": {"steps": [{"name": "deps", "run": "a\nb"}]}},
            "one shell line",
        ),
        (
            {"mission": {"steps": [{"name": "a", "run": "true"}, {"name": "a", "run": "true"}]}},
            "unique",
        ),
        ({"base": {"install": "../escape.sh"}}, "unsafe bundle path"),
        ({"id": "envkit/python-uv"}, "id"),
    ],
)
def test_a_malformed_kit_is_refused(change: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        EnvironmentKitManifest.model_validate(kit_document(**change))


def test_the_kit_overlay_admits_only_the_base_layer_installer_on_hosted_profiles() -> None:
    bad = CapabilityHostSupport.model_validate(
        {"profiles": {"codex": {"status": "supported", "overlay": {BASE_LAYER_OVERLAY: "owner"}}}}
    )
    with pytest.raises(ValueError, match="unknown key"):
        bad.validate_for(AgentCapabilityKind.ENVIRONMENT_KIT)


# --- the catalog row ------------------------------------------------------------------------


def test_a_kit_bundle_publishes_an_environment_kit_definition_derived_from_kit_json() -> None:
    published = published_kit()
    definition = published.definition
    assert isinstance(definition, EnvironmentKitDefinition)
    assert definition.kind == DefinitionKind.ENVIRONMENT_KIT
    assert definition.logical_id == "envkit.fixture"
    assert definition.secret_refs == ("FIXTURE_SETUP_TOKEN",)
    assert definition.host_support == definition.kit.capability_host_support()
    assert definition.bundle_ref.uri.startswith("capability-bundles://biotech/environment_kit/")
    summary = summarize(published)
    assert summary.capability_kind == AgentCapabilityKind.ENVIRONMENT_KIT
    assert set(summary.supported_profiles) == set(LOCAL_PROFILES)
    assert summary.pin == kit_pin(published)
    # No SQL literal of its own: the row is a 'profile' asset (no migration).
    assert ASSET_KIND[DefinitionKind.ENVIRONMENT_KIT] == "profile"


def test_the_catalog_never_states_more_than_the_kit_declares() -> None:
    definition = published_kit().definition
    assert isinstance(definition, EnvironmentKitDefinition)
    payload = definition.model_dump(mode="json")
    wider = dict(payload, host_support={"profiles": {"cursor_cloud": {"status": "supported"}}})
    with pytest.raises(ValidationError, match="derived from the kit"):
        EnvironmentKitDefinition.model_validate(wider)
    with pytest.raises(ValidationError, match="required secrets"):
        EnvironmentKitDefinition.model_validate(dict(payload, secret_refs=["OTHER_KEY"]))


def test_a_kit_naming_a_base_script_its_bundle_lacks_is_refused() -> None:
    document = kit_document(base={"install": "base/install.sh"})
    files = kit_files(document)
    manifest = build_bundle_manifest(
        files,
        application_id="biotech",
        kind="environment_kit",
        capability_id=document["id"],
        version=document["version"],
    )
    with pytest.raises(ValidationError, match="lacks"):
        bundle_definition(manifest, files, {})
    complete = [*files, ("base/install.sh", b"#!/usr/bin/env bash\ntrue\n")]
    manifest = build_bundle_manifest(
        complete,
        application_id="biotech",
        kind="environment_kit",
        capability_id=document["id"],
        version=document["version"],
    )
    assert isinstance(bundle_definition(manifest, complete, {}), EnvironmentKitDefinition)


def test_kit_json_must_name_the_bundle_it_ships_in() -> None:
    document = kit_document()
    files = kit_files(document)
    manifest = build_bundle_manifest(
        files,
        application_id="biotech",
        kind="environment_kit",
        capability_id="envkit.other",
        version="1",
    )
    with pytest.raises(ValueError, match="declares envkit.fixture@1"):
        bundle_definition(manifest, files, {})


async def test_pins_resolve_exactly_and_feed_the_compile_time_environment_inputs() -> None:
    published = published_kit()
    retired = published_kit(kit_document(id="envkit.retired"), retired=True)
    catalog = EnvironmentKitCatalog(StaticDefinitions(published, retired))
    pin = kit_pin(published)
    assert await catalog.resolve(pin) == published.definition
    # Another version or digest, a retired row and a malformed pin never resolve.
    assert await catalog.resolve(pin.replace("@1#", "@2#")) is None
    assert await catalog.resolve(pin[:-1] + ("0" if pin[-1] != "0" else "1")) is None
    assert await catalog.resolve(kit_pin(retired)) is None
    assert await catalog.resolve("envkit.fixture") is None

    inputs = CatalogEnvironmentInputs(catalog, {"knowledge_services.public_url": "https://ks"})
    requirements = await inputs.kit_requirements(pin)
    assert requirements is not None
    assert requirements.egress == ("pypi.org",)
    assert await inputs.kit_requirements("envkit.missing@1#sha256:" + "a" * 64) is None
    assert await inputs.config_value("knowledge_services.public_url") == "https://ks"
    assert await inputs.config_value("unset.key") is None


def test_a_kit_is_searchable_by_its_toolchains_requirements_and_lane_profiles() -> None:
    document = kit_document(toolchains={"python": "3.12", "uv": "0.12"}, system_packages=["jq"])
    source = search_document_source(published_kit(document).definition)
    text = render_search_document(source).search_text
    for fragment in (
        "Prepare a mission workspace",
        "toolchain: python 3.12",
        "toolchain: uv 0.12",
        "system package: jq",
        "FIXTURE_SETUP_TOKEN",
        "pypi.org",
        "lane profiles: cursor_local, claude_agent_sdk, codex",
    ):
        assert fragment in text


# --- the starter kits -----------------------------------------------------------------------


@pytest.mark.parametrize("app", ["biotech", "ai-engineer"])
def test_the_starter_kits_are_published_per_application(app: str) -> None:
    entries = KITS.application_definitions(app)
    ids = {entry["definition"].logical_id for entry in entries}
    expected = STARTER_KITS if app == "biotech" else STARTER_KITS - {"envkit.biotech-backend"}
    assert ids == expected
    for entry in entries:
        definition = entry["definition"]
        assert isinstance(definition, EnvironmentKitDefinition)
        assert entry["pin"].startswith(f"{definition.logical_id}@1#sha256:")
        assert entry["manifest"].application_id == app
        assert definition.kit.host_support.get("local") == KitHostSupport.FULL
        assert definition.host_support.supports("claude_agent_sdk")


@pytest.mark.parametrize("app", ["biotech", "ai-engineer"])
def test_the_committed_kit_seed_rows_are_the_generated_definitions(app: str) -> None:
    seed = json.loads(
        (SEEDS / app / f"mc.app.{app}.environment-kits-1.0.0.json").read_text(encoding="utf-8")
    )
    rows = {
        record["fields"]["manifest"]["definition"]["logical_id"]: record["fields"]
        for record in seed["records"]
        if record["kind"] == "asset_version"
    }
    for entry in KITS.application_definitions(app):
        definition = entry["definition"]
        row = rows[definition.logical_id]
        assert row["kind"] == "profile"
        assert row["manifest"]["definition"] == definition.model_dump(mode="json")
        assert row.get("secret_refs", []) == list(definition.secret_refs)
        assert row["host_support"] == definition.host_support.model_dump(mode="json")


def test_mission_control_dev_adopts_the_owned_cursor_environment_byte_for_byte() -> None:
    (source,) = [item for item in KITS.kit_sources() if item["id"] == "envkit.mission-control-dev"]
    files = dict(source["files"])
    for relative in (
        ".cursor/environment.json",
        ".cursor/Dockerfile",
        ".cursor/scripts/cloud-install.sh",
        ".cursor/scripts/cloud-start.sh",
        ".cursor/scripts/cloud-infra.sh",
    ):
        assert files[relative] == (ROOT / relative).read_bytes().replace(b"\r\n", b"\n")
    environment = json.loads(files[".cursor/environment.json"])
    # The kit marker preflight reads (DECISIONS R24) and the entrypoint the start script runs.
    kit = EnvironmentKitManifest.model_validate(json.loads(files["kit.json"]))
    assert environment["name"] == f"mc:{kit.id}@{kit.version}"
    assert b"bash .mission/setup/run --phase start" in files[".cursor/scripts/cloud-start.sh"]
    assert kit.base.install == ".cursor/scripts/cloud-install.sh"


# --- compile against the catalog -------------------------------------------------------------


@pytest.mark.parametrize("profile", ["claude_agent_sdk", "codex", "cursor_cloud"])
def test_a_manifest_pinning_a_published_kit_compiles_through_the_catalog(profile: str) -> None:
    from tests.unit.authoring.test_manifest_v2_environment import (
        CONFIG,
        _set,
        blockers,
        compile_text,
        manifest,
    )

    requires = {
        "variables": ["LOG_LEVEL"],
        "secrets": ["FIRECRAWL_API_KEY", "OPTIONAL_TOKEN?"],
        "egress": ["pypi.org", "registry.npmjs.org"],
    }
    published = published_kit(kit_document(id="envkit.python-uv-node", requires=requires))
    pin = kit_pin(published)
    inputs = CatalogEnvironmentInputs(EnvironmentKitCatalog(StaticDefinitions(published)), CONFIG)

    text = manifest(profile, _set("mission/environment/kit/pin", pin))
    assert blockers(compile_text(text, inputs)) == {}

    # The kit's own requirements are enforced: a secret the manifest does not declare blocks.
    stricter = published_kit(
        kit_document(
            id="envkit.python-uv-node",
            requires={**requires, "secrets": [*requires["secrets"], "TAVILY_API_KEY"]},
        )
    )
    inputs = CatalogEnvironmentInputs(EnvironmentKitCatalog(StaticDefinitions(stricter)), CONFIG)
    text = manifest(profile, _set("mission/environment/kit/pin", kit_pin(stricter)))
    assert blockers(compile_text(text, inputs)) == {
        "/mission/environment/secrets": "kit_requirement_unmet"
    }
