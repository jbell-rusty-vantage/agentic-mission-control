"""Offline structure, closure and provenance checks for the catalog seed bundles."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path
from types import ModuleType

import pytest
from pydantic import ValidationError

from mission_control.application.programs.artifact_validation import supported_schema
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import (
    ArtifactSchemaDefinition,
    MCPToolDefinition,
    PublishedDefinition,
)
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
    # The router bundle manifest regenerated from the guide; 1.0.2 is frozen.
    ("mc.catalog.approved-assets", "1.0.3"),
    ("mc.catalog.agent-capabilities", "1.0.0"),
    # The research capabilities (GitHub, Context7, the capture server, plugin.code-research)
    # as new ids, after the applied, frozen 1.0.0.
    ("mc.catalog.agent-capabilities", "1.1.0"),
    # Revision 2 of the capture server and its tool rows; 1.1.0 is frozen.
    ("mc.catalog.agent-capabilities", "1.2.0"),
    # Revision 3, recaptured at Knowledge Services 1a451fd; 1.2.0 is frozen.
    ("mc.catalog.agent-capabilities", "1.3.0"),
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
# What a secret value looks like. A captured MCP tool's own prose (its description and the
# annotation text of its input schema) is quoted from the server's `tools/list`, where words
# such as "password" are ordinary English; that prose is held to this pattern only.
SECRET_VALUE_SHAPED = re.compile(
    r"(postgres(ql)?://|bearer [a-z0-9]|-----BEGIN|\b(sk|fc|tvly|ghp|github_pat)[-_][a-z0-9]{8})",
    re.IGNORECASE,
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
        # The target's database variable was renamed (plane-qualified names); 1.0.1 is frozen.
        ("mc.app.bindings", "1.0.2"),
    ]
    agent = [("mc.catalog.agent-capabilities", "1.0.0"), (APP_AGENT_KEYS[app], "1.0.0")]
    # The research capabilities: new common ids, after the frozen common 1.0.0.
    # 1.2.0: revision 2 of the capture server (supported on deep_agents), after the frozen 1.1.0.
    # 1.3.0: revision 3 of the capture server (the chain tools allowlisted), after the frozen 1.2.0.
    research = [
        ("mc.catalog.agent-capabilities", "1.1.0"),
        ("mc.catalog.agent-capabilities", "1.2.0"),
        ("mc.catalog.agent-capabilities", "1.3.0"),
    ]
    # FT-A7: skills, the policy hook and the plugin are per application.
    # 1.0.5: the coordinator bundles regenerated from the guide and the imported method skills.
    # 1.0.6: the method skills re-imported at Knowledge Services 1a451fd and AI Engineer 080e9f0.
    # 1.0.7: mission-control-author 0.4.1, whose guide pages say when a promised output can be
    # delivered.
    skill_versions = ("1.0.0", "1.0.1", "1.0.2", "1.0.3", "1.0.4", "1.0.5", "1.0.6", "1.0.7")
    skills = [(f"mc.app.{app}.agent-skills", version) for version in skill_versions]
    # MO-12: starter Environment Kits, per application like the skills.
    kits = [(f"mc.app.{app}.environment-kits", "1.0.0")]
    observation = [
        (f"mc.app.{app}.{name}", "1.0.0")
        for name in ("cognition-profiles", "signal-skills", "watchers")
    ]
    # Revision 2 of the knowledge and mixed plugins, over the skills agent-skills 1.0.5 publishes.
    observation.append((f"mc.app.{app}.cognition-profiles", "1.0.1"))
    # Revision 3 of the knowledge plugin, with the capture server agent-capabilities 1.2.0
    # publishes at revision 2.
    observation.append((f"mc.app.{app}.cognition-profiles", "1.0.2"))
    # Revision 4: the re-imported method skills and the capture server revision 3.
    observation.append((f"mc.app.{app}.cognition-profiles", "1.0.3"))
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
        # The router manifest regenerated from the guide, after the frozen 1.0.2.
        ("mc.catalog.approved-assets", "1.0.3"),
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
        + research
        + skills
        + kits
        + observation
        + storage
        + successors
        + artifact_schemas
        + knowledge
    )
    assert position_of(keys, research[0]) > position_of(keys, agent[0])
    assert position_of(keys, successors[0]) > position_of(keys, base[2])
    assert position_of(keys, successors[1]) > position_of(keys, base[0])
    assert position_of(keys, successors[2]) > position_of(keys, successors[1])
    assert position_of(keys, successors[3]) > position_of(keys, successors[0])
    assert position_of(keys, successors[5]) > position_of(keys, base[1])
    assert position_of(keys, successors[8]) > position_of(keys, successors[3])
    # The revision 2 plugins apply after the skills they pin and after their own 1.0.0.
    assert position_of(keys, observation[3]) > position_of(keys, skills[5])
    assert position_of(keys, observation[3]) > position_of(keys, observation[0])
    # The revision 3 knowledge plugin applies after its 1.0.1 and after the capture server.
    assert position_of(keys, observation[4]) > position_of(keys, observation[3])
    assert position_of(keys, observation[4]) > position_of(keys, research[1])
    assert position_of(keys, research[1]) > position_of(keys, research[0])
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
    frozen, approved, current = (item["records"][0]["fields"] for item in bindings)
    assert (frozen["version"], approved["version"], current["version"]) == ("1", "2", "3")
    binding = current["manifest"]
    assert binding["application_id"] == app
    assert binding["approved_tenant_actor_mappings"] == []
    # The approved target has no unresolved operator fields; 1.0.0 recorded the placeholders.
    assert binding["unresolved_operator_fields"] == []
    assert approved["manifest"]["unresolved_operator_fields"] == []
    assert frozen["manifest"]["unresolved_operator_fields"]
    # Each version supersedes the one before it and applies after it; the current one records
    # the target file as it is now, and differs from the frozen 1.0.1 only in those facts.
    assert (approved["manifest"]["supersedes"], binding["supersedes"]) == (
        f"app-binding:{app}@1",
        f"app-binding:{app}@2",
    )
    assert {"seed_key": "mc.app.bindings", "seed_version": "1.0.1"} in bindings[2]["depends_on"]
    target = (ROOT / "deployments" / app / "target.toml").read_bytes().replace(b"\r\n", b"\n")
    assert binding["target_sha256"] == "sha256:" + hashlib.sha256(target).hexdigest()
    changed = {key for key in binding if binding[key] != approved["manifest"][key]}
    assert changed == {"secret_reference_names", "supersedes", "target_sha256"}
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


def test_current_approved_assets_hold_the_router_manifest_and_no_coordinator_skill() -> None:
    """1.0.3 publishes the router bundle manifest at its present version and nothing else: the
    coordinator skill (retired by ADR-0033) was seeded once, by the frozen 1.0.0, and its
    source is an archive, not a live skill directory."""

    generator = _generator()
    by_version = {
        bundle["seed_version"]: bundle
        for bundle in _bundles("common")
        if bundle["seed_key"] == "mc.catalog.approved-assets"
    }
    frozen = ("1.0.0", "1.0.1", "1.0.2")
    current = by_version["1.0.3"]
    assert current["depends_on"] == [
        {"seed_key": "mc.catalog.approved-assets", "seed_version": "1.0.2"}
    ]
    held = {
        record["logical_key"] for version in frozen for record in by_version[version]["records"]
    }
    assert not held & {record["logical_key"] for record in current["records"]}
    (asset,) = [record for record in current["records"] if record["kind"] == "asset_version"]
    router = json.loads((ROOT / "skills" / "mission-control" / "manifest.json").read_bytes())
    assert asset["logical_key"] == f"skill-bundle-manifest:mission-control/{router['version']}"
    assert asset["fields"]["manifest"] == router
    assert "mission-control-coordinator" not in json.dumps(current["records"])
    for version in frozen:
        generator.frozen_bundle(f"common/mc.catalog.approved-assets-{version}.json")
    assert not (ROOT / ".agents" / "skills" / "mission-control-coordinator").exists()
    archive = SEEDS.parent / "bundle-sources" / "approved-assets-1.0.0"
    assert (archive / ".agents" / "skills" / "mission-control-coordinator" / "SKILL.md").is_file()


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
        scanned, prose = _split_tool_prose(bundle)
        text = json.dumps(scanned)
        # Secret reference NAMES (e.g. TAVILY_API_KEY) are allowed; values never are.
        for name in _secret_ref_names(bundle):
            text = text.replace(name, "SECRET_REF_NAME")
        assert not SECRET_LIKE.search(text), bundle["seed_key"]
        assert not [item for item in prose if SECRET_VALUE_SHAPED.search(item)], bundle["seed_key"]
        _assert_no_seeded_runtime_facts(bundle)


def _split_tool_prose(bundle: dict) -> tuple[dict, list[str]]:
    """The bundle with each MCP tool's own prose blanked, and that prose.

    The prose is what a server's `tools/list` says about a tool: a published MCP Tool's
    description, the tool descriptions an MCP Server definition lists, and the `description`
    and `title` annotation strings inside a tool's input or output schema. Names, enum values,
    defaults and everything else stay in the strictly scanned copy.
    """
    copy = json.loads(json.dumps(bundle))
    prose: list[str] = []

    def take(holder: dict, key: str) -> None:
        if isinstance(holder.get(key), str):
            prose.append(holder[key])
            holder[key] = ""

    def annotations(schema: object) -> None:
        if isinstance(schema, dict):
            take(schema, "description")
            take(schema, "title")
            for child in schema.values():
                annotations(child)
        elif isinstance(schema, list):
            for child in schema:
                annotations(child)

    for record in copy["records"]:
        if record["kind"] != "asset_version":
            continue
        definition = record["fields"].get("manifest", {}).get("definition")
        if not isinstance(definition, dict):
            continue
        if definition.get("kind") == "mcp_tool":
            take(definition, "description")
            annotations(definition.get("input_schema"))
            annotations(definition.get("output_schema"))
        elif definition.get("kind") == "mcp_server":
            for tool in definition.get("tools", ()):
                take(tool, "description")
    return copy, prose


def test_tool_prose_is_still_scanned_for_secret_values() -> None:
    """A captured description may say "password"; it may never carry a value, and nothing but
    a tool's own prose is exempt from the strict scan."""

    (bundle,) = [
        b
        for b in _bundles("common")
        if (b["seed_key"], b["seed_version"]) == ("mc.catalog.agent-capabilities", "1.1.0")
    ]
    scanned, prose = _split_tool_prose(bundle)
    assert any("password" in item for item in prose)
    assert SECRET_LIKE.search(json.dumps(bundle)) and not SECRET_LIKE.search(
        re.sub("|".join(sorted(_secret_ref_names(bundle))), "SECRET_REF_NAME", json.dumps(scanned))
    )
    assert SECRET_VALUE_SHAPED.search("Authorization: Bearer abc123")
    assert SECRET_VALUE_SHAPED.search("use sk-abcdefgh12345678 here")
    assert not SECRET_VALUE_SHAPED.search("login fails after password reset")
    changed = json.loads(json.dumps(bundle))
    tool = next(
        record["fields"]["manifest"]["definition"]
        for record in changed["records"]
        if record["kind"] == "asset_version"
        and record["fields"]["manifest"]["definition"]["kind"] == "mcp_tool"
    )
    tool["tool_name"] = "password_reader"
    assert SECRET_LIKE.search(json.dumps(_split_tool_prose(changed)[0]))


def _assert_no_seeded_runtime_facts(bundle: dict) -> None:
    """Schema property names declare shapes; they are never runtime ledger records.

    Only a typed published Artifact Schema's validated JSON Schema and a typed published MCP
    Tool's input and output schemas get declaration-name handling. Their other metadata and
    any non-schema seed payload remain fully checked. Secret-value scanning above still covers
    the schema documents (annotation prose under its own pattern).
    """
    forbidden = {"embedding", "mission_run", "usage", "receipt"}
    schema_roots = set()
    for record in bundle["records"]:
        if record["kind"] != "asset_version":
            continue
        manifest = record["fields"].get("manifest", {})
        kind = manifest.get("definition", {}).get("kind")
        if kind == "mcp_tool":
            published = PublishedDefinition.model_validate(manifest)
            assert isinstance(published.definition, MCPToolDefinition)
            for field in ("input_schema", "output_schema"):
                if isinstance(manifest["definition"].get(field), dict):
                    schema_roots.add(id(manifest["definition"][field]))
            continue
        if kind != "artifact_schema":
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
            # knowledge-tools 1.1.0/1.2.0 carry submit_output at revision 2 (OVE-170), and
            # agent-capabilities 1.2.0 and 1.3.0 the capture server and its tool rows at
            # revisions 2 and 3.
            capture = published.ref.logical_id.startswith("mcp.knowledge-capture")
            allowed = (
                {"1", "2"}
                if published.ref.logical_id == "tool.knowledge-submit-output"
                else {"1", "2", "3"}
                if capture
                else {"1"}
            )
            assert fields["version"] == str(published.ref.revision)
            assert fields["version"] in allowed
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
