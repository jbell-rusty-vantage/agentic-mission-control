"""Offline structure, closure and provenance checks for the catalog seed bundles."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from types import ModuleType

import pytest
from pydantic import ValidationError

from mission_control.application.programs.artifact_validation import supported_schema
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import ArtifactSchemaDefinition, PublishedDefinition
from mission_control_db_contract.errors import ContractError
from mission_control_db_contract.seeds import load_bundles, order_bundles, validate_bundle

ROOT = Path(__file__).resolve().parents[3]
SEEDS = ROOT / "packages" / "mission-control-db-contract" / "seeds"
EXPECTED = {
    ("mc.catalog.workflow-parity", "1.0.0"),
    ("mc.catalog.workflow-parity", "1.0.1"),
    ("mc.catalog.workflow-parity", "1.0.2"),
    ("mc.catalog.workflow-parity", "1.0.3"),
    ("mc.catalog.workflow-parity", "1.0.4"),
    ("mc.catalog.workflow-parity", "1.0.5"),
    ("mc.catalog.runtime-profiles", "1.0.0"),
    ("mc.catalog.runtime-profiles", "1.0.1"),
    ("mc.catalog.artifact-schemas", "1.0.0"),
    # OVE-171 WI-08: the W2 graph-variant schemas, a successor of the applied, frozen 1.0.0.
    ("mc.catalog.artifact-schemas", "1.0.1"),
    ("mc.catalog.approved-assets", "1.0.0"),
    ("mc.catalog.approved-assets", "1.0.1"),
    ("mc.catalog.approved-assets", "1.0.2"),
    ("mc.catalog.agent-capabilities", "1.0.0"),
    ("mc.catalog.knowledge-tools", "1.0.0"),
    # OVE-170 submit_output revision 2 (recorded), then OVE-204 slice 4 knowledge_read_intent.
    ("mc.catalog.knowledge-tools", "1.1.0"),
    ("mc.catalog.knowledge-tools", "1.2.0"),
    ("mc.storage.capability-bundles", "1.0.0"),
    # OVE-204 slice 7: the private payload bucket (no client policies).
    ("mc.storage.mission-payloads", "1.0.0"),
    ("mc.qualification.parity", "1.0.0"),
}
STORAGE_KINDS = {"storage_bucket", "storage_policy"}
APP_AGENT_KEYS = {
    "biotech": "mc.app.biotech.agent-capabilities",
    "ai-engineer": "mc.app.ai-engineer.agent-capabilities",
}
SECRET_LIKE = re.compile(
    r"(postgres(ql)?://|password|passwd|secret_value|api[_-]?key|bearer |-----BEGIN)", re.IGNORECASE
)


def _generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "generate_catalog_seeds", SEEDS / "generate_catalog_seeds.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bundles(*directories: str) -> list[dict]:
    return load_bundles([SEEDS / directory for directory in directories])


def test_committed_bundles_match_their_repository_sources() -> None:
    generated = _generator().build_bundles()
    committed = {
        path.relative_to(SEEDS).as_posix(): json.loads(path.read_bytes())
        for path in sorted(SEEDS.rglob("*.json"))
    }
    assert committed == generated, "regenerate with generate_catalog_seeds.py --write"


@pytest.mark.parametrize("app", ["biotech", "ai-engineer"])
def test_each_app_installation_set_is_valid_and_dependency_closed(app: str) -> None:
    bundles = _bundles("common", app)
    ordered = order_bundles(bundles, already_applied=set())
    keys = [(item["seed_key"], item["seed_version"]) for item in ordered]
    base = [
        ("mc.catalog.workflow-parity", "1.0.0"),
        ("mc.catalog.runtime-profiles", "1.0.0"),
        ("mc.catalog.approved-assets", "1.0.0"),
        ("mc.app.bindings", "1.0.0"),
        ("mc.app.bindings", "1.0.1"),
    ]
    agent = [("mc.catalog.agent-capabilities", "1.0.0"), (APP_AGENT_KEYS[app], "1.0.0")]
    # FT-A7: skills, the policy hook and the plugin are per application.
    skill_versions = ("1.0.0", "1.0.1", "1.0.2", "1.0.3", "1.0.4")
    skills = [(f"mc.app.{app}.agent-skills", version) for version in skill_versions]
    # MO-12: starter Environment Kits, per application like the skills.
    kits = [(f"mc.app.{app}.environment-kits", "1.0.0")]
    observation = [
        (f"mc.app.{app}.{name}", "1.0.0")
        for name in ("cognition-profiles", "signal-skills", "watchers")
    ]
    storage = [("mc.storage.capability-bundles", "1.0.0"), ("mc.storage.mission-payloads", "1.0.0")]
    # Succession of the applied, frozen approved-assets@1.0.0 (new logical keys only).
    successors = [
        ("mc.catalog.approved-assets", "1.0.1"),
        ("mc.catalog.workflow-parity", "1.0.1"),
        ("mc.catalog.workflow-parity", "1.0.2"),
        ("mc.catalog.approved-assets", "1.0.2"),
        ("mc.catalog.workflow-parity", "1.0.3"),
        # OVE-169 W1 D15: the root's family failure terminalization, after the frozen 1.0.3.
        ("mc.catalog.workflow-parity", "1.0.4"),
        # OVE-176 WI-13: the nested-program registration, after the applied, frozen 1.0.4.
        ("mc.catalog.workflow-parity", "1.0.5"),
        # Sprint OC WI-23: the sealed async child graph pin, after the applied, frozen 1.0.0.
        ("mc.catalog.runtime-profiles", "1.0.1"),
    ]
    artifact_schemas = [
        ("mc.catalog.artifact-schemas", "1.0.0"),
        ("mc.catalog.artifact-schemas", "1.0.1"),
    ]
    # Sprint V SV-16: the knowledge tools as catalog tool rows (common); 1.2.0 (OVE-204 slice 4,
    # knowledge_read_intent) succeeds the recorded 1.1.0.
    knowledge = [
        ("mc.catalog.knowledge-tools", "1.0.0"),
        ("mc.catalog.knowledge-tools", "1.1.0"),
        ("mc.catalog.knowledge-tools", "1.2.0"),
    ]
    # D5: the SDLC report schemas are an additive AI Engineer-only slot.
    if app == "ai-engineer":
        artifact_schemas.append(("mc.app.ai-engineer.artifact-schemas", "1.0.0"))
    assert sorted(keys) == sorted(
        base
        + agent
        + skills
        + kits
        + observation
        + storage
        + successors
        + artifact_schemas
        + knowledge
    )
    assert position_of(keys, successors[0]) > position_of(keys, base[2])
    assert position_of(keys, successors[1]) > position_of(keys, base[0])
    assert position_of(keys, successors[2]) > position_of(keys, successors[1])
    assert position_of(keys, successors[3]) > position_of(keys, successors[0])
    assert position_of(keys, successors[5]) > position_of(keys, base[1])
    assert position_of(keys, knowledge[2]) > position_of(keys, knowledge[1])
    # The schema successor applies after the frozen 1.0.0 it depends on.
    assert position_of(keys, artifact_schemas[1]) > position_of(keys, artifact_schemas[0])
    assert [key for key in keys if key in base] == base
    position = {key: index for index, key in enumerate(keys)}
    assert (
        position[("mc.catalog.approved-assets", "1.0.0")]
        < position[agent[0]]
        < position[agent[1]]
        < position[skills[0]]
    )
    bindings = [item for item in ordered if item["seed_key"] == "mc.app.bindings"]
    frozen, current = (item["records"][0]["fields"] for item in bindings)
    assert (frozen["version"], current["version"]) == ("1", "2")
    binding = current["manifest"]
    assert binding["application_id"] == app
    assert binding["approved_tenant_actor_mappings"] == []
    # The approved target has no unresolved operator fields; 1.0.0 recorded the placeholders.
    assert binding["unresolved_operator_fields"] == []
    assert frozen["manifest"]["unresolved_operator_fields"]
    # Common catalog bytes are one shared copy; only the app binding differs.
    assert _bundles("common") == [
        item
        for item in bundles
        if item["seed_key"]
        not in {
            "mc.app.bindings",
            APP_AGENT_KEYS[app],
            f"mc.app.{app}.agent-skills",
            f"mc.app.{app}.environment-kits",
            f"mc.app.{app}.cognition-profiles",
            f"mc.app.{app}.signal-skills",
            f"mc.app.{app}.watchers",
            f"mc.app.{app}.artifact-schemas",
        }
    ]


def position_of(keys: list[tuple[str, str]], key: tuple[str, str]) -> int:
    return keys.index(key)


def test_approved_assets_successor_never_rewrites_an_applied_logical_key() -> None:
    (frozen,) = [
        b
        for b in _bundles("common")
        if (b["seed_key"], b["seed_version"]) == ("mc.catalog.approved-assets", "1.0.0")
    ]
    (successor,) = [
        b
        for b in _bundles("common")
        if (b["seed_key"], b["seed_version"]) == ("mc.catalog.approved-assets", "1.0.1")
    ]
    # The live 2026-10-03 receipts record this digest for 1.0.0; its bytes are immutable.
    assert frozen["seed_digest"] == (
        "sha256:f45e04f9a68ad5569304691fab2de48befa6dc017076b9bc8c3c557d5a1d3dd6"
    )
    held = {record["logical_key"] for record in frozen["records"]}
    assert successor["records"]
    assert not held & {record["logical_key"] for record in successor["records"]}
    assert {"seed_key": "mc.catalog.approved-assets", "seed_version": "1.0.0"} in successor[
        "depends_on"
    ]


def test_workflow_parity_successor_never_rewrites_an_applied_logical_key() -> None:
    by_version = {
        b["seed_version"]: b
        for b in _bundles("common")
        if b["seed_key"] == "mc.catalog.workflow-parity"
    }
    frozen, successor = by_version["1.0.0"], by_version["1.0.1"]
    held = {record["logical_key"] for record in frozen["records"]}
    assert successor["records"]
    assert not held & {record["logical_key"] for record in successor["records"]}
    assert {"seed_key": "mc.catalog.workflow-parity", "seed_version": "1.0.0"} in successor[
        "depends_on"
    ]
    # The families as the worker registers them now include the Human Gate workflow.
    families = [r for r in successor["records"] if r["kind"] == "asset_version"]
    assert all(
        "HumanGateWorkflow" in record["fields"]["manifest"]["temporal_workflows"]
        for record in families
    )


def test_current_workflow_parity_adds_result_materialization_without_rewriting_history() -> None:
    generator = _generator()
    by_version = {
        bundle["seed_version"]: bundle
        for bundle in _bundles("common")
        if bundle["seed_key"] == "mc.catalog.workflow-parity"
    }
    current = by_version["1.0.2"]
    prior_keys = {
        record["logical_key"]
        for version in ("1.0.0", "1.0.1")
        for record in by_version[version]["records"]
    }
    assert not prior_keys & {record["logical_key"] for record in current["records"]}
    assert current["depends_on"] == [
        {"seed_key": "mc.catalog.workflow-parity", "seed_version": "1.0.1"}
    ]
    assert {k: v for k, v in current.items() if k != "seed_digest"} == generator.frozen_bundle(
        "common/mc.catalog.workflow-parity-1.0.2.json"
    )
    for record in current["records"]:
        if record["kind"] == "asset_version":
            assert record["fields"]["version"] == "3"
            assert (
                "materialize_workflow_result" in record["fields"]["manifest"]["temporal_activities"]
            )
    # The generator validates the frozen file hash; this also covers missing/altered bytes.
    assert (
        generator.frozen_bundle("common/mc.catalog.workflow-parity-1.0.1.json")["seed_version"]
        == "1.0.1"
    )
    frozen = by_version["1.0.3"]
    assert frozen["depends_on"] == [
        {"seed_key": "mc.catalog.workflow-parity", "seed_version": "1.0.2"}
    ]
    assert {k: v for k, v in frozen.items() if k != "seed_digest"} == generator.frozen_bundle(
        "common/mc.catalog.workflow-parity-1.0.3.json"
    )
    assert not {row["logical_key"] for row in current["records"]}.intersection(
        row["logical_key"] for row in frozen["records"]
    )
    # OVE-169 W1 D15: the current registration (with the root's family failure
    # terminalization) is the successor's asset version 5; no applied key is rewritten.
    d15 = by_version["1.0.4"]
    assert d15["depends_on"] == [
        {"seed_key": "mc.catalog.workflow-parity", "seed_version": "1.0.3"}
    ]
    assert {k: v for k, v in d15.items() if k != "seed_digest"} == generator.frozen_bundle(
        "common/mc.catalog.workflow-parity-1.0.4.json"
    )
    for record in d15["records"]:
        if record["kind"] == "asset_version":
            assert (
                "terminalize_failed_family" in record["fields"]["manifest"]["temporal_activities"]
            )
    # OVE-176 WI-13: the current registration (nested programs) is the successor's asset
    # version 6, after the applied, frozen 1.0.4; no applied key is rewritten.
    successor = by_version["1.0.5"]
    assert successor["depends_on"] == [
        {"seed_key": "mc.catalog.workflow-parity", "seed_version": "1.0.4"}
    ]
    assert successor["records"] == generator.workflow_parity(asset_version="6")["records"]
    applied = {
        row["logical_key"]
        for version in ("1.0.0", "1.0.1", "1.0.2", "1.0.3", "1.0.4")
        for row in by_version[version]["records"]
    }
    assert not applied & {row["logical_key"] for row in successor["records"]}


def test_qualification_bundle_is_opt_in_and_closes_over_common() -> None:
    with pytest.raises(ContractError, match="neither supplied nor applied"):
        order_bundles(_bundles("qualification"), already_applied=set())
    ordered = order_bundles(_bundles("common", "qualification"), already_applied=set())
    assert {(item["seed_key"], item["seed_version"]) for item in ordered} == EXPECTED
    qualification = next(item for item in ordered if item["seed_key"] == "mc.qualification.parity")
    (tenant,) = [record for record in qualification["records"] if record["kind"] == "tenant"]
    assert tenant["fields"]["qualification_fixture"] is True
    assert "SYNTHETIC QUALIFICATION FIXTURE" in qualification["description"]


def test_bundles_seed_no_fabricated_authority_usage_or_secrets() -> None:
    for bundle in _bundles("common", "biotech", "ai-engineer", "qualification"):
        kinds = {record["kind"] for record in bundle["records"]}
        if bundle["seed_key"] == "mc.storage.capability-bundles":
            assert kinds == STORAGE_KINDS
            policies = [r["fields"] for r in bundle["records"] if r["kind"] == "storage_policy"]
            assert len(policies) == 4
            assert {p["command"] for p in policies} == {"INSERT", "SELECT", "ALL"}
            continue
        if bundle["seed_key"] == "mc.storage.mission-payloads":
            (bucket,) = bundle["records"]
            assert bucket["kind"] == "storage_bucket"
            assert bucket["fields"] == {
                "bucket_id": "mission-payloads",
                "public": False,
                "file_size_limit": 52_428_800,
            }
            continue
        # No actor bindings, actor grants or capability grants without owner approval
        # (FT-A7 plugin expansion rows are catalog structure, not authority).
        assert kinds <= {
            "tenant",
            "asset_version",
            "asset_decision",
            "capability_plugin_member",
        }, bundle["seed_key"]
        if bundle["seed_key"] != "mc.qualification.parity":
            assert "tenant" not in kinds
        assets = {r["logical_key"] for r in bundle["records"] if r["kind"] == "asset_version"}
        decisions = [r for r in bundle["records"] if r["kind"] == "asset_decision"]
        assert {d["fields"]["asset_version"] for d in decisions} == assets
        assert all(d["fields"]["decision"] == "admit" for d in decisions)
        text = json.dumps(bundle)
        # Secret reference NAMES (e.g. TAVILY_API_KEY) are allowed; values never are.
        for name in _secret_ref_names(bundle):
            text = text.replace(name, "SECRET_REF_NAME")
        assert not SECRET_LIKE.search(text), bundle["seed_key"]
        _assert_no_seeded_runtime_facts(bundle)


def _assert_no_seeded_runtime_facts(bundle: dict) -> None:
    """Schema property names declare shapes; they are never runtime ledger records.

    Only a typed published Artifact Schema's validated JSON Schema gets declaration-name
    handling. Its other metadata and any non-schema seed payload remain fully checked.
    Secret-value scanning above still covers the complete unmodified schema document.
    """
    forbidden = {"embedding", "mission_run", "usage", "receipt"}
    schema_roots = set()
    for record in bundle["records"]:
        if record["kind"] != "asset_version":
            continue
        manifest = record["fields"].get("manifest", {})
        if manifest.get("definition", {}).get("kind") != "artifact_schema":
            continue
        published = PublishedDefinition.model_validate(manifest)
        assert isinstance(published.definition, ArtifactSchemaDefinition)
        assert supported_schema(published.definition.json_schema)
        schema_roots.add(id(manifest["definition"]["json_schema"]))

    def visit(value: object, *, schema: bool = False, declaration_names: bool = False) -> None:
        schema = schema or id(value) in schema_roots
        if isinstance(value, dict):
            for key, child in value.items():
                assert declaration_names or key not in forbidden, key
                names = schema and key in {
                    "properties",
                    "$defs",
                    "definitions",
                    "dependentSchemas",
                    "required",
                }
                visit(child, schema=schema, declaration_names=names)
        elif isinstance(value, list):
            for child in value:
                visit(child, schema=schema, declaration_names=declaration_names)
        elif isinstance(value, str):
            assert declaration_names or value not in forbidden, value

    visit(bundle)


@pytest.mark.parametrize("field", ["embedding", "mission_run", "usage", "receipt"])
def test_runtime_fact_guard_rejects_actual_seed_payloads(field: str) -> None:
    (bundle,) = [
        b
        for b in _bundles("common")
        if (b["seed_key"], b["seed_version"]) == ("mc.catalog.artifact-schemas", "1.0.0")
    ]
    _assert_no_seeded_runtime_facts(bundle)  # The real usage property declaration is permitted.
    changed = json.loads(json.dumps(bundle))
    asset = next(record for record in changed["records"] if record["kind"] == "asset_version")
    asset["fields"]["manifest"][field] = {"amount": 1}
    # Unknown fields may be refused by the typed published envelope before traversal.
    with pytest.raises((ValidationError, AssertionError)):
        _assert_no_seeded_runtime_facts(changed)


@pytest.mark.parametrize("location", ["schema_root", "schema_annotation", "record_kind"])
def test_schema_declarations_do_not_allow_runtime_facts_elsewhere(location: str) -> None:
    (bundle,) = [
        b
        for b in _bundles("common")
        if (b["seed_key"], b["seed_version"]) == ("mc.catalog.artifact-schemas", "1.0.0")
    ]
    changed = json.loads(json.dumps(bundle))
    asset = next(record for record in changed["records"] if record["kind"] == "asset_version")
    schema = asset["fields"]["manifest"]["definition"]["json_schema"]
    if location == "schema_root":
        schema["usage"] = {"amount": 1}
    elif location == "schema_annotation":
        schema["x-runtime"] = {"usage": {"amount": 1}}
    else:
        asset["kind"] = "usage"
    with pytest.raises(AssertionError):
        _assert_no_seeded_runtime_facts(changed)


def _secret_ref_names(bundle: dict) -> set[str]:
    names: set[str] = set()
    for record in bundle["records"]:
        fields = record["fields"]
        names.update(fields.get("secret_refs", ()))
        definition = fields.get("manifest", {}).get("definition", {})
        names.update(definition.get("secret_refs", ()))
        names.update(definition.get("env_refs", {}))
        names.update(definition.get("env_refs", {}).values())
    return {name for name in names if re.fullmatch(r"[A-Z][A-Z0-9_]*", name)}


def test_published_definition_assets_are_exact_and_repository_readable() -> None:
    from mission_control.adapters.postgres.control_plane.catalog_assets import (
        PUBLISHED_DEFINITION_CONTRACT,
        definition_asset_id,
    )

    seen = set()
    for bundle in _bundles("common", "qualification"):
        for record in bundle["records"]:
            fields = record["fields"]
            if record["kind"] != "asset_version":
                continue
            if fields["contract"] != PUBLISHED_DEFINITION_CONTRACT:
                continue
            published = PublishedDefinition.model_validate(fields["manifest"])
            assert fields["manifest_digest"] == sha256_digest(fields["manifest"])
            assert published.ref.digest == sha256_digest(published.definition)
            assert fields["asset_id"] == definition_asset_id(
                published.ref.kind, published.ref.logical_id
            )
            # knowledge-tools 1.1.0/1.2.0 carry submit_output at revision 2 (OVE-170).
            revision = "2" if published.ref.logical_id == "tool.knowledge-submit-output" else "1"
            assert fields["version"] == str(published.ref.revision)
            assert fields["version"] in {"1", revision}
            seen.add(published.ref.logical_id)
    assert {
        "skill.mission-control-coordinator",
        "prompt.coordinator.propose-workflow",
        "fixture.generic-stage-graph",
        "fixture.generic-goal-directed",
        "mcp.tavily",
        "mcp.firecrawl",
        "mcp.agent-browser",
    } <= seen


def test_changed_bytes_change_the_seed_digest() -> None:
    (bundle,) = [
        b
        for b in _bundles("common")
        if (b["seed_key"], b["seed_version"]) == ("mc.catalog.workflow-parity", "1.0.0")
    ]
    original = {key: value for key, value in bundle.items() if key != "seed_digest"}
    changed = json.loads(json.dumps(original))
    changed["records"][0]["fields"]["manifest"]["family"] = "Invented"
    assert validate_bundle(changed)["seed_digest"] != bundle["seed_digest"]
    assert validate_bundle(original)["seed_digest"] == bundle["seed_digest"]


@pytest.mark.parametrize(
    ("app", "project"),
    [("biotech", "biotech-research-ingestion"), ("ai-engineer", "supabase-blue-ocean")],
)
def test_every_applied_seed_matches_recorded_live_130_receipts(app: str, project: str) -> None:
    from mission_control_db_contract.canonical import digest_value

    receipt_path = (
        ROOT / "docs/qualification/two-project" / project / "20261012-live-130/seed-receipts.json"
    )
    receipts = json.loads(receipt_path.read_bytes())["bundles"]
    assert len(receipts) == 11
    for item in receipts:
        name = f"{item['seed_key']}-{item['seed_version']}.json"
        paths = [SEEDS / sub / name for sub in ("common", app) if (SEEDS / sub / name).is_file()]
        assert len(paths) == 1
        assert digest_value(json.loads(paths[0].read_bytes())) == item["receipt"]["seed_digest"]
