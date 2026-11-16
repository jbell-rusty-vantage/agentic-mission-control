"""FT-A7: seeded skill bundles, the policy hook and the web-research plugin.

Rows are per application (the custody manifest names its application, so digests and object
prefixes differ per application); bytes are the committed sources; pins equal what the
catalog computes; plugin members are exact pins with an intersected host support; the
publish path uploads once through FT-A2 custody and refuses tampered objects.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path
from typing import Any

import pytest

from mission_control.adapters.capabilities.local_bundle_store import (
    FilesystemBundleFetcher,
    FilesystemBundleObjectStore,
)
from mission_control.application.capabilities.bundle_custody import (
    BundleCustodyConflict,
    fetch_definition_bundle,
)
from mission_control.domain.authoring.contracts import (
    HookScriptDefinition,
    PluginDefinition,
    PublishedDefinition,
    SkillDefinition,
)
from mission_control.domain.capabilities.bundles import (
    CapabilityDrift,
    computed_hash,
    parse_skill_frontmatter,
)
from mission_control.domain.capabilities.catalog_entry import capability_pin
from mission_control.domain.capabilities.host_support import (
    UNQUALIFIED_BY_DEFAULT,
    HostSupportStatus,
    LaneProfile,
)
from mission_control_db_contract.seeds import load_bundles

ROOT = Path(__file__).resolve().parents[3]
SEEDS = ROOT / "packages" / "mission-control-db-contract" / "seeds"
NAME_RULE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?$")
LOCAL_PROFILES = set(LaneProfile) - set(UNQUALIFIED_BY_DEFAULT)
MISSION_CONTROL = {
    "skill.mission-control",
    "skill.mission-control-author",
    "skill.mission-control-catalog",
    "skill.mission-control-compose",
    "skill.mission-control-intervene",
    "skill.mission-control-observe",
}
# Application-scoped knowledge charters (seed 1.0.4): each admitted to its own application only.
CHARTERS = {
    "biotech": "skill.biotech-knowledge-charter",
    "ai-engineer": "skill.ai-engineer-knowledge-charter",
}
# Method skills imported from Knowledge Services (seed 1.0.5): admitted to both applications.
KNOWLEDGE_SERVICES = {
    "skill.knowledge-research",
    "skill.knowledge-verify",
    "skill.knowledge-acquisition-and-vetting",
    "skill.knowledge-verification",
    "skill.knowledge-ingest",
    "skill.knowledge-db",
    "skill.schema-explore",
}
# Imported from the AI Engineer service (seed 1.0.5): admitted to that application only.
AI_ENGINEER_SERVICE = {CHARTERS["ai-engineer"], "skill.content-authoring"}
ADMISSION = {
    "biotech": MISSION_CONTROL
    | KNOWLEDGE_SERVICES
    | {
        "skill.agent-browser",
        "skill.biomcp",
        "hook.mc-policy-template",
        "plugin.web-research",
        CHARTERS["biotech"],
    },
    "ai-engineer": MISSION_CONTROL
    | KNOWLEDGE_SERVICES
    | AI_ENGINEER_SERVICE
    | {
        "skill.agent-browser",
        "skill.edgartools",
        "hook.mc-policy-template",
        "plugin.web-research",
    },
}
# The catalog revision seed 1.0.5 gives each regenerated coordinator bundle, with its version.
COORDINATOR_REVISIONS = {
    "skill.mission-control": ("3", "0.6.0"),
    "skill.mission-control-author": ("5", "0.4.0"),
    "skill.mission-control-catalog": ("2", "0.3.0"),
    "skill.mission-control-compose": ("2", "0.3.0"),
    "skill.mission-control-intervene": ("2", "0.6.0"),
    "skill.mission-control-observe": ("4", "0.4.0"),
}


def _module(name: str, relative: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SKILLS = _module("ft_a7_agent_skills", "packages/mission-control-db-contract/seeds/agent_skills.py")
GENERATOR = _module(
    "ft_a7_generator", "packages/mission-control-db-contract/seeds/generate_catalog_seeds.py"
)
PUBLISH = _module("ft_a7_publish", "scripts/seeds_publish_bundles.py")


def _published(app: str) -> dict[str, PublishedDefinition]:
    bundles = sorted(
        (
            item
            for item in load_bundles([SEEDS / app])
            if item["seed_key"] == f"mc.app.{app}.agent-skills"
        ),
        key=lambda item: tuple(map(int, item["seed_version"].split("."))),
    )
    return {
        record["fields"]["manifest"]["definition"][
            "logical_id"
        ]: PublishedDefinition.model_validate(record["fields"]["manifest"])
        for bundle in bundles
        for record in bundle["records"]
        if record["kind"] == "asset_version"
    }


def test_committed_agent_skill_bundles_match_their_sources() -> None:
    for relative, bundle in GENERATOR.agent_skills().items():
        committed = json.loads((SEEDS / relative).read_bytes())
        assert committed == bundle, f"regenerate {relative} with generate_catalog_seeds"


@pytest.mark.parametrize("app", ["biotech", "ai-engineer"])
def test_admission_per_application(app: str) -> None:
    assert set(_published(app)) == ADMISSION[app]


@pytest.mark.parametrize("app", ["biotech", "ai-engineer"])
def test_rows_pin_custody_paths_and_catalog_pins(app: str) -> None:
    published = _published(app)
    index = {item["capability_id"]: item for item in SKILLS.custody_index(app)}
    for logical_id, item in published.items():
        pin = capability_pin(item).render()
        entry = next(
            entry
            for entry in SKILLS.application_definitions(app)
            if entry["definition"].logical_id == logical_id
        )
        assert entry["pin"] == pin
        definition = item.definition
        if isinstance(definition, SkillDefinition | HookScriptDefinition):
            custody = index[logical_id]
            assert definition.bundle_ref is not None
            assert definition.bundle_ref.uri == f"capability-bundles://{custody['object_prefix']}"
            assert custody["object_prefix"].startswith(f"{app}/")
            assert definition.manifest_digest == custody["manifest_digest"]
            # every row is supported on the five worker-hosted lane profiles; the provider-
            # hosted profiles are never assumed supported (MP-01, `UNQUALIFIED_BY_DEFAULT`)
            assert set(definition.host_support.supported_profiles()) == LOCAL_PROFILES


def test_upstream_captures_are_verbatim_and_follow_the_frontmatter_rules() -> None:
    stub = ROOT / "tests" / "fixtures" / "skills" / "agent-browser" / "SKILL.md"
    payload = stub.read_bytes()
    # The git blob id of skills/agent-browser/SKILL.md at v0.38.2 (commit 39a74c70).
    blob = hashlib.sha1(b"blob %d\0" % len(payload) + payload).hexdigest()  # noqa: S324
    assert blob == "dc9bb54a22e9cd7ad9c982a0fe5ae2e204751b12"
    assert b"agent-browser skills get core" in payload
    for name in ("agent-browser", "biomcp"):
        frontmatter = parse_skill_frontmatter(
            (ROOT / "tests" / "fixtures" / "skills" / name / "SKILL.md").read_bytes()
        )
        assert frontmatter["name"] == name and NAME_RULE.fullmatch(name)
        assert 1 <= len(frontmatter["description"]) <= 1024
    # Upstream edgartools 5.61.1 declares `name: EdgarTools` (recorded, kept verbatim); the
    # catalog's skill name is the directory name.
    edgar = parse_skill_frontmatter(
        (ROOT / "tests" / "fixtures" / "skills" / "edgartools" / "SKILL.md").read_bytes()
    )
    assert edgar["name"] == "EdgarTools"
    edgar_md = (ROOT / "tests" / "fixtures" / "skills" / "edgartools" / "SKILL.md").read_bytes()
    edgar_blob = hashlib.sha1(b"blob %d\0" % len(edgar_md) + edgar_md).hexdigest()  # noqa: S324
    assert edgar_blob == "f8f236c433adeff3d7387dbbdc7d6af762db5ab7"  # edgar/ai/skills/core
    definition = _published("ai-engineer")["skill.edgartools"].definition
    assert isinstance(definition, SkillDefinition) and definition.skill_name == "edgartools"
    assert NAME_RULE.fullmatch(definition.skill_name)


def test_mission_control_bundles_carry_the_skills_manifest_digests() -> None:
    # The bundles `skills/` holds: the router family and the Biotech charter. The AI Engineer
    # charter is an imported copy since seed 1.0.5 and has no `skills/` manifest.
    for source in SKILLS.bundle_sources():
        if source["id"] not in MISSION_CONTROL | {CHARTERS["biotech"]}:
            continue
        name = source["id"].removeprefix("skill.")
        manifest = json.loads((ROOT / "skills" / name / "manifest.json").read_text("utf-8"))
        assert manifest["name"] == name and source["version"] == manifest["version"]
        files = dict(source["files"])
        for path, digest in manifest["files"].items():
            assert "sha256:" + hashlib.sha256(files[path]).hexdigest() == digest, path
        custody = SKILLS.bundle_manifest(source, "biotech")
        assert custody.computed_hash == computed_hash(source["files"])
        assert NAME_RULE.fullmatch(name)


@pytest.mark.parametrize("app", ["biotech", "ai-engineer"])
def test_hook_and_plugin_rows(app: str) -> None:
    published = _published(app)
    hook = published["hook.mc-policy-template"].definition
    assert isinstance(hook, HookScriptDefinition)
    assert [event.value for event in hook.events] == ["before_shell", "before_tool"]
    assert hook.fail_closed and hook.entrypoint == "policy.py"
    plugin = published["plugin.web-research"].definition
    assert isinstance(plugin, PluginDefinition)
    members = {member.pin.capability_id: member for member in plugin.manifest.members}
    assert list(members) == [
        "mcp.tavily",
        "mcp.firecrawl",
        "skill.agent-browser",
        "mcp.agent-browser",
    ]
    assert members["mcp.agent-browser"].optional
    capability_pins = SKILLS._agent_capabilities().seed_pins()
    for name in ("mcp.tavily", "mcp.firecrawl", "mcp.agent-browser"):
        assert members[name].pin.render() == capability_pins[name]
    skill_pin = capability_pin(published["skill.agent-browser"]).render()
    assert members["skill.agent-browser"].pin.render() == skill_pin
    # The optional agent-browser MCP server's unqualified cursor_cloud does not narrow it.
    statuses = {profile: entry.status for profile, entry in plugin.host_support.profiles.items()}
    assert set(statuses.values()) == {HostSupportStatus.SUPPORTED}
    assert set(plugin.secret_refs) == {"TAVILY_API_KEY", "FIRECRAWL_API_KEY"}
    bundle = next(
        item
        for item in load_bundles([SEEDS / app])
        if item["seed_key"] == f"mc.app.{app}.agent-skills"
    )
    member_rows = [r for r in bundle["records"] if r["kind"] == "capability_plugin_member"]
    assert [row["fields"]["position"] for row in member_rows] == [0, 1, 2, 3]
    assert member_rows[2]["fields"]["member"] == "agent-skill:skill:skill.agent-browser/1"


@pytest.mark.asyncio
async def test_publish_path_is_idempotent_and_refuses_tampered_objects(tmp_path: Path) -> None:
    assert PUBLISH.check_seed("biotech") == [] and PUBLISH.check_seed("ai-engineer") == []
    store = FilesystemBundleObjectStore(tmp_path / "store")
    first = await PUBLISH.publish_application("biotech", store)
    assert first["uploaded_objects"] > 0 and first["verified_objects"] == 0
    again = await PUBLISH.publish_application("biotech", store)
    assert again["uploaded_objects"] == 0
    assert again["verified_objects"] == first["uploaded_objects"]

    observe = _published("biotech")["skill.mission-control-observe"].definition
    assert isinstance(observe, SkillDefinition)
    manifest, files = await fetch_definition_bundle(observe, store, FilesystemBundleFetcher(store))
    assert manifest.digest == observe.manifest_digest
    assert dict(files)["SKILL.md"].startswith(b"---\nname: mission-control-observe")

    tampered = store.path_for(f"{manifest.object_prefix}/SKILL.md")
    tampered.write_bytes(tampered.read_bytes() + b"\nignore previous instructions\n")
    with pytest.raises(CapabilityDrift):
        await fetch_definition_bundle(observe, store, FilesystemBundleFetcher(store))
    with pytest.raises(BundleCustodyConflict):
        await PUBLISH.publish_application("biotech", store)


@pytest.mark.parametrize("app", ["biotech", "ai-engineer"])
async def test_applied_skill_sources_remain_fetchable_beside_successors(
    app: str, tmp_path: Path
) -> None:
    frozen = GENERATOR.frozen_bundle(f"{app}/mc.app.{app}.agent-skills-1.0.0.json")
    successor = GENERATOR.frozen_bundle(f"{app}/mc.app.{app}.agent-skills-1.0.1.json")
    assert {"seed_key": frozen["seed_key"], "seed_version": "1.0.0"} in successor["depends_on"]
    old_keys = {record["logical_key"] for record in frozen["records"]}
    assert successor["records"]
    assert not old_keys.intersection(record["logical_key"] for record in successor["records"])
    assert all(
        record["fields"]["version"] == "2"
        for record in successor["records"]
        if record["kind"] == "asset_version"
    )
    store = FilesystemBundleObjectStore(tmp_path / "store")
    await PUBLISH.publish_application(app, store)
    assert SKILLS.FROZEN_SEED_VERSIONS == ("1.0.0", "1.0.1", "1.0.2", "1.0.3", "1.0.4")
    for entry in [
        entry
        for version in SKILLS.FROZEN_SEED_VERSIONS
        for entry in SKILLS.frozen_application_definitions(app, version)
    ]:
        if entry["manifest"] is None:
            continue
        manifest, files = await fetch_definition_bundle(
            entry["definition"], store, FilesystemBundleFetcher(store)
        )
        assert manifest.digest == entry["manifest"].digest
        assert dict(files) == dict(entry["source"]["files"])


@pytest.mark.parametrize("app", ["biotech", "ai-engineer"])
def test_run2_skill_successor_uses_new_revision_and_source_version(app: str) -> None:
    # Frozen since 1.0.3 (OC-R7): its bytes are pinned and its sources archived.
    successor = GENERATOR.frozen_bundle(f"{app}/mc.app.{app}.agent-skills-1.0.2.json")
    assert successor["depends_on"] == [
        {"seed_key": f"mc.app.{app}.agent-skills", "seed_version": "1.0.1"}
    ]
    records = [row for row in successor["records"] if row["kind"] == "asset_version"]
    assert len(records) == 2
    for row in records:
        assert row["fields"]["version"] == "3"
        definition = row["fields"]["manifest"]["definition"]
        assert definition["source_provenance"]["upstream_version"] == "0.3.1"


@pytest.mark.parametrize("app", ["biotech", "ai-engineer"])
def test_model_catalog_guidance_ships_as_the_author_skill_successor(app: str) -> None:
    """OC-R7 N5: `mission-control-author` 0.3.2 (choose a Model Catalog profile the lane routes)
    is revision 4 in seed 1.0.3; every other bundle keeps its earlier revision and bytes.
    Frozen since 1.0.4: its bytes are pinned and its sources archived."""

    successor = GENERATOR.frozen_bundle(f"{app}/mc.app.{app}.agent-skills-1.0.3.json")
    assert successor["depends_on"] == [
        {"seed_key": f"mc.app.{app}.agent-skills", "seed_version": "1.0.2"}
    ]
    (row,) = [row for row in successor["records"] if row["kind"] == "asset_version"]
    assert row["fields"]["version"] == "4"
    definition = row["fields"]["manifest"]["definition"]
    assert definition["logical_id"] == "skill.mission-control-author"
    assert definition["source_provenance"]["upstream_version"] == "0.3.2"
    (archived,) = SKILLS.frozen_application_definitions(app, "1.0.3")
    store_files = dict(archived["source"]["files"])
    assert b"missionctl model list --json" in store_files["SKILL.md"]
    assert (
        b"model: { profile: producer.default }"
        in (store_files["references/manifest-cheatsheet.md"])
    )
    assert archived["definition"].manifest_digest == definition["manifest_digest"]


def _frozen_files(app: str, version: str, logical_id: str) -> dict[str, bytes]:
    """The archived bytes of one bundle a frozen seed version published."""

    return dict(
        next(
            entry["source"]["files"]
            for entry in SKILLS.frozen_application_definitions(app, version)
            if entry["definition"].logical_id == logical_id
        )
    )


@pytest.mark.parametrize("app", ["biotech", "ai-engineer"])
def test_knowledge_charter_ships_at_revision_one_in_its_application_only(app: str) -> None:
    """OVE-204 slice 6: seed 1.0.4 publishes the application's knowledge charter as a new skill
    id (revision 1, `0.1.0` from `skills/`); the other application's seed never carries it.
    Frozen since 1.0.5: its bytes are pinned and its sources archived."""

    successor = GENERATOR.frozen_bundle(f"{app}/mc.app.{app}.agent-skills-1.0.4.json")
    assert successor["depends_on"] == [
        {"seed_key": f"mc.app.{app}.agent-skills", "seed_version": "1.0.3"}
    ]
    (row,) = [row for row in successor["records"] if row["kind"] == "asset_version"]
    assert row["fields"]["version"] == "1"
    definition = row["fields"]["manifest"]["definition"]
    assert definition["logical_id"] == CHARTERS[app]
    assert definition["source_provenance"]["upstream_version"] == "0.1.0"
    assert definition["source_provenance"]["locator"] == (
        f"repo://skills/{CHARTERS[app].removeprefix('skill.')}"
    )
    assert definition["maturity"] == "experimental"
    other = next(name for name in CHARTERS if name != app)
    assert CHARTERS[other] not in _published(app)
    assert CHARTERS[app] not in _published(other)
    files = _frozen_files(app, "1.0.4", CHARTERS[app])
    assert set(files) == {
        "SKILL.md",
        "manifest.json",
        "references/ingestion-guide.md",
        "references/research-procedure.md",
    }
    frontmatter = parse_skill_frontmatter(files["SKILL.md"])
    assert frontmatter["name"] == CHARTERS[app].removeprefix("skill.")
    assert 1 <= len(frontmatter["description"]) <= 1024


def _imports() -> dict[str, dict[str, Any]]:
    return {f"skill.{name}": record for name, record in SKILLS.imported_records().items()}


@pytest.mark.parametrize("app", ["biotech", "ai-engineer"])
def test_seed_105_publishes_the_regenerated_coordinator_bundles_and_the_imports(app: str) -> None:
    """Seed 1.0.5: each coordinator bundle at its next revision, each imported method skill as
    a new id, and the AI Engineer charter as the next revision of its id. Nothing a frozen
    version holds is published again, and the retired coordinator skill is not in it."""

    successor = GENERATOR.agent_skills()[f"{app}/mc.app.{app}.agent-skills-1.0.5.json"]
    assert successor["depends_on"] == [
        {"seed_key": f"mc.app.{app}.agent-skills", "seed_version": "1.0.4"}
    ]
    rows = {
        row["fields"]["manifest"]["definition"]["logical_id"]: row
        for row in successor["records"]
        if row["kind"] == "asset_version"
    }
    imported = KNOWLEDGE_SERVICES | (AI_ENGINEER_SERVICE if app == "ai-engineer" else set())
    assert set(rows) == MISSION_CONTROL | imported
    assert "skill.mission-control-coordinator" not in rows
    for logical_id, (revision, version) in COORDINATOR_REVISIONS.items():
        definition = rows[logical_id]["fields"]["manifest"]["definition"]
        assert rows[logical_id]["fields"]["version"] == revision
        assert definition["source_provenance"]["upstream_version"] == version
    held = {
        record["logical_key"]
        for version in SKILLS.FROZEN_SEED_VERSIONS
        for record in GENERATOR.frozen_bundle(f"{app}/mc.app.{app}.agent-skills-{version}.json")[
            "records"
        ]
    }
    assert not held & {record["logical_key"] for record in successor["records"]}
    records = _imports()
    for logical_id in imported:
        row, record = rows[logical_id], records[logical_id]
        definition = row["fields"]["manifest"]["definition"]
        # A new id is revision 1; the charter succeeds the 0.1.0 row seed 1.0.4 published.
        assert row["fields"]["version"] == ("2" if logical_id == CHARTERS["ai-engineer"] else "1")
        assert definition["description"] == record["description"]
        assert 1 <= len(definition["description"]) <= 1024
        assert "\n" not in definition["description"]
        provenance = definition["source_provenance"]
        origin = record["source"]
        assert provenance == {
            "source": "belllabs",
            "locator": f"{origin['repository']}/tree/{origin['commit']}/{origin['path']}",
            "upstream_identity": f"{origin['name']}/{logical_id.removeprefix('skill.')}",
            "upstream_version": record["version"],
            "commit_digest": origin["commit"],
            "license": "proprietary",
        }
        assert record["version"].endswith("-" + origin["commit"][:7])
        assert definition["maturity"] == "experimental"
        assert capability_pin(_published(app)[logical_id]).version == record["version"]


def test_imported_bundles_are_the_recorded_bytes_and_nothing_else() -> None:
    """A published import is its custody copy: every file the record lists with its sha256, no
    file Mission Control added, the upstream frontmatter name as the catalog skill name."""

    records = _imports()
    sources = {
        source["id"]: source for source in SKILLS.bundle_sources() if source["id"] in records
    }
    assert set(sources) == set(records) == KNOWLEDGE_SERVICES | AI_ENGINEER_SERVICE
    for logical_id, source in sources.items():
        record = records[logical_id]
        assert source["version"] == record["version"]
        assert source["directory"] == record["directory"]
        assert sorted(
            (path, "sha256:" + hashlib.sha256(content).hexdigest(), len(content))
            for path, content in source["files"]
        ) == sorted((row["path"], row["sha256"], row["size_bytes"]) for row in record["files"])
        assert "manifest.json" not in dict(source["files"])
        (app, *_rest) = source["apps"]
        definition = _published(app)[logical_id].definition
        assert isinstance(definition, SkillDefinition)
        assert definition.skill_name == logical_id.removeprefix("skill.")
        assert NAME_RULE.fullmatch(definition.skill_name)
        assert {entry.path: entry.digest for entry in definition.file_manifest} == {
            row["path"]: row["sha256"] for row in record["files"]
        }


def test_the_stale_ai_engineer_charter_is_no_longer_a_live_source() -> None:
    """The 0.1.0 charter Mission Control wrote left `skills/`: its bytes are the archive of the
    frozen seed 1.0.4, and the latest row of its id is the imported copy."""

    assert not (ROOT / "skills" / "ai-engineer-knowledge-charter").exists()
    stale = _frozen_files("ai-engineer", "1.0.4", CHARTERS["ai-engineer"])
    assert b"version" in stale["manifest.json"]
    latest = _published("ai-engineer")[CHARTERS["ai-engineer"]]
    assert latest.ref.revision == 2
    assert latest.definition.source_provenance.source == "belllabs"
    assert latest.definition.source_provenance.upstream_identity == (
        "ai-engineer-service/ai-engineer-knowledge-charter"
    )


def test_charter_admission_follows_the_application_profile_rule() -> None:
    """The profile load check admits `skill.<app>-knowledge-charter` for `<app>` only; the seed
    admits each charter to exactly that application, and each profile names its charter."""

    from mission_control.bootstrap.application_profiles import (
        charter_skill_id,
        load_application_profile,
    )

    charters = dict(SKILLS.APPLICATION_SKILLS) | {
        name: apps
        for name, (_version, apps) in SKILLS.IMPORTED_SKILLS.items()
        if name.endswith("-knowledge-charter")
    }
    assert set(charters) == {name.removeprefix("skill.") for name in CHARTERS.values()}
    for name, apps in charters.items():
        (app,) = apps
        assert f"skill.{name}" == charter_skill_id(app) == CHARTERS[app]
        profile = load_application_profile(ROOT / "deployments", app).profile
        assert profile.knowledge.charter_skill == CHARTERS[app]
