"""Deterministically (re)generate the minimal Mission Control catalog seed bundles.

Every record is derived from a definition or artifact that exists in this repository;
nothing is invented. Run from the Mission Control repository root (``SEEDS`` =
``packages/mission-control-db-contract/seeds``):

    uv run --no-sync python SEEDS/generate_catalog_seeds.py --check
    uv run --no-sync python SEEDS/generate_catalog_seeds.py --write

``--check`` fails when a committed bundle differs from what the sources produce (a source
changed without a new seed version). Bundles never contain secrets, tenants/actors/grants
for real users, missions, runs, receipts, usage or embeddings.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
SEEDS_ROOT = Path(__file__).resolve().parent
SEED_FORMAT = "mission-control-seed/v1"
COMPATIBILITY = ">=1.0.0 <2.0.0"
SEED_ACTOR = "seed:mission-control-catalog"
SEED_TIME = datetime(2026, 10, 3, tzinfo=UTC)
SEED_TIME_TEXT = "2026-10-03T00:00:00Z"
POLICY_REF = "mission-control.seed-admission/1"
APPS = ("biotech", "ai-engineer")


def _sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _canonical_digest(value: Any) -> str:
    """Digest of compact sorted JSON (mission_control_db_contract.canonical.digest_value)."""
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _repo_file(relative: str) -> bytes:
    # Line-ending normalized so digests do not depend on the checkout platform.
    return (REPO_ROOT / relative).read_bytes().replace(b"\r\n", b"\n")


def _admit(logical_key: str, asset_key: str, evidence: list[str]) -> dict[str, Any]:
    return {
        "kind": "asset_decision",
        "logical_key": logical_key,
        "fields": {
            "asset_version": asset_key,
            "decision": "admit",
            "disposition": "seeded-from-reviewed-source",
            "actor_ref": SEED_ACTOR,
            "evidence_refs": evidence,
            "policy_ref": POLICY_REF,
            "decided_at": SEED_TIME_TEXT,
        },
    }


def _asset(
    logical_key: str,
    *,
    asset_id: str,
    version: str,
    kind: str,
    contract: str,
    manifest_ref: str,
    manifest: dict[str, Any],
    manifest_digest: str | None = None,
    host_support: dict[str, Any] | None = None,
    secret_refs: list[str] | None = None,
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "asset_id": asset_id,
        "version": version,
        "kind": kind,
        "contract": contract,
        "manifest_ref": manifest_ref,
        "manifest_digest": manifest_digest or _canonical_digest(manifest),
        "manifest": manifest,
        "required_compatibility": [COMPATIBILITY],
        "status": "admitted",
    }
    # Agent-composition rows (migration 0025) carry their host-support matrix and secret
    # reference names; older rows omit both so their bundles stay byte-identical.
    if host_support is not None:
        fields["host_support"] = host_support
    if secret_refs:
        fields["secret_refs"] = secret_refs
    return {"kind": "asset_version", "logical_key": logical_key, "fields": fields}


def _published_definition_records(
    definition: Any,
    key_prefix: str,
    evidence: list[str],
    *,
    published_at: datetime = SEED_TIME,
    revision: int = 1,
) -> list[dict[str, Any]]:
    """Asset rows readable by PostgresDefinitionRepository (versioned revision, exact digest)."""
    from mission_control.adapters.postgres.control_plane.catalog_assets import (
        ASSET_KIND,
        PUBLISHED_DEFINITION_CONTRACT,
        definition_asset_id,
        definition_manifest_ref,
    )
    from mission_control.domain.authoring.canonical import (
        canonical_data,
        sha256_digest,
        stable_json_dump,
    )
    from mission_control.domain.authoring.contracts import ExactDefinitionRef, PublishedDefinition

    ref = ExactDefinitionRef(
        kind=definition.kind,
        logical_id=definition.logical_id,
        revision=revision,
        digest=sha256_digest(definition),
    )
    published = PublishedDefinition(
        ref=ref, definition=definition, published_at=published_at, published_by=SEED_ACTOR
    )
    manifest = canonical_data(stable_json_dump(published))["payload"]
    # Seed logical keys admit no underscore, so mcp_server/mcp_tool are spelled with hyphens.
    asset_key = (
        f"{key_prefix}:{definition.kind.value.replace('_', '-')}:{definition.logical_id}/{revision}"
    )
    host_support = getattr(definition, "host_support", None)
    support = (
        host_support.model_dump(mode="json")
        if host_support is not None and host_support.profiles
        else None
    )
    return [
        _asset(
            asset_key,
            asset_id=definition_asset_id(definition.kind, definition.logical_id),
            version=str(revision),
            kind=ASSET_KIND[definition.kind],
            contract=PUBLISHED_DEFINITION_CONTRACT,
            manifest_ref=definition_manifest_ref(definition.kind, definition.logical_id, revision),
            manifest=manifest,
            manifest_digest=sha256_digest(manifest),
            host_support=support,
            secret_refs=list(getattr(definition, "secret_refs", ())),
        ),
        _admit(asset_key + ":admit", asset_key, evidence),
    ]


class _NameRecorder:
    def __getattr__(self, name: str) -> str:
        return name


def workflow_parity(asset_version: str = "1") -> dict[str, Any]:
    from mission_control.adapters.temporal.registration.activities import coordinator_activities
    from mission_control.adapters.temporal.registration.workflows import coordinator_workflows

    sources = [
        "src/mission_control/domain/authoring/contracts.py",
        "src/mission_control/adapters/temporal/registration/workflows.py",
        "src/mission_control/adapters/temporal/registration/activities.py",
    ]
    records: list[dict[str, Any]] = []
    for family, slug, blueprint in (
        ("StageGraph", "stagegraph", "StageGraphBlueprint"),
        ("GoalDirected", "goal-directed", "GoalDirectedBlueprint"),
    ):
        manifest = {
            "vocabulary": "mission-control.workflow-family/1",
            "family": family,
            "blueprint_contract": f"mission_control.domain.authoring.contracts.{blueprint}",
            "temporal_workflows": sorted(item.__name__ for item in coordinator_workflows(family)),
            "temporal_activities": sorted(coordinator_activities(family, _NameRecorder())),
            "source_refs": sources,
        }
        key = f"workflow-family:{slug}/{asset_version}"
        records.append(
            _asset(
                key,
                asset_id=f"workflow-family:{slug}",
                version=asset_version,
                kind="policy",
                contract="mission-control.workflow-family/1",
                manifest_ref=f"repo://src/mission_control/adapters/temporal/registration#{family}",
                manifest=manifest,
            )
        )
        records.append(_admit(key + ":admit", key, sources))
    return {
        "format": SEED_FORMAT,
        "seed_key": "mc.catalog.workflow-parity",
        "seed_version": "1.0.0",
        "component_compatibility": COMPATIBILITY,
        "depends_on": [],
        "actor_ref": SEED_ACTOR,
        "description": (
            "Workflow-family vocabulary actually registered by the validator/compiler and the "
            "Temporal worker: StageGraph and GoalDirected only. No product Workflow Types "
            "(those are application-owned), no missions or runs."
        ),
        "records": records,
    }


WORKFLOW_PARITY_FROZEN = "common/mc.catalog.workflow-parity-1.0.0.json"


def workflow_parity_successor() -> dict[str, Any]:
    """Current registration as new asset versions; prior seed bytes stay frozen."""
    current = workflow_parity(asset_version="6")
    return {
        **current,
        "seed_version": "1.0.5",
        "depends_on": [{"seed_key": "mc.catalog.workflow-parity", "seed_version": "1.0.4"}],
        "description": (
            "Successor of mc.catalog.workflow-parity@1.0.4 (frozen): StageGraph and "
            "GoalDirected registration including the nested-program activities and workflows "
            "(OVE-176 WI-13), as asset version 6. No product Workflow Types, missions or runs."
        ),
    }


def runtime_profiles(asset_version: str = "1") -> dict[str, Any]:
    descriptor_path = "packages/mission-control-db-contract/runtime/descriptor.json"
    descriptor_bytes = _repo_file(descriptor_path)
    descriptor = json.loads(descriptor_bytes)
    graphs_path = "agent_server/langgraph.json"
    graphs_bytes = _repo_file(graphs_path)
    graphs = json.loads(graphs_bytes)
    persistence = {
        "profile": "mission-control.runtime-persistence/1",
        "descriptor_ref": descriptor_path,
        "descriptor_sha256": _sha256_bytes(descriptor_bytes),
        "descriptor_schema": descriptor["descriptor_schema"],
        "schema": descriptor["schema"],
        "role": descriptor["role"],
        "pins": descriptor["pins"],
    }
    server = {
        "profile": "mission-control.agent-server-graphs/1",
        "config_ref": graphs_path,
        "config_sha256": _sha256_bytes(graphs_bytes),
        "graphs": graphs["graphs"],
        "python_version": graphs["python_version"],
        "production_native_persistence": "unqualified",
    }
    records: list[dict[str, Any]] = []
    for key, asset_id, contract, ref, manifest in (
        (
            f"runtime-persistence:langgraph-postgres/{asset_version}",
            "runtime-persistence:langgraph-postgres",
            "mission-control.runtime-persistence/1",
            "repo://" + descriptor_path,
            persistence,
        ),
        (
            f"agent-server:graph-pins/{asset_version}",
            "agent-server:graph-pins",
            "mission-control.agent-server-graphs/1",
            "repo://" + graphs_path,
            server,
        ),
    ):
        records.append(
            _asset(
                key,
                asset_id=asset_id,
                version=asset_version,
                kind="profile",
                contract=contract,
                manifest_ref=ref,
                manifest=manifest,
            )
        )
        records.append(_admit(key + ":admit", key, [ref.removeprefix("repo://")]))
    return {
        "format": SEED_FORMAT,
        "seed_key": "mc.catalog.runtime-profiles",
        "seed_version": "1.0.0",
        "component_compatibility": COMPATIBILITY,
        "depends_on": [{"seed_key": "mc.catalog.workflow-parity", "seed_version": "1.0.0"}],
        "actor_ref": SEED_ACTOR,
        "description": (
            "Pinned runtime persistence descriptor and Agent Server graph pins as present in this "
            "repository. Pins only; no provider, model route or credential is seeded."
        ),
        "records": records,
    }


def runtime_profiles_successor() -> dict[str, Any]:
    """Current graph pins as new asset versions; the applied 1.0.0 bytes stay frozen."""
    current = runtime_profiles(asset_version="2")
    return {
        **current,
        "seed_version": "1.0.1",
        "depends_on": [{"seed_key": "mc.catalog.runtime-profiles", "seed_version": "1.0.0"}],
        "description": (
            "Successor of mc.catalog.runtime-profiles@1.0.0 (frozen): the runtime persistence "
            "descriptor and Agent Server graph pins including the sealed async child graph "
            "(Sprint OC WI-23), as asset version 2. Pins only; no provider, model route or "
            "credential is seeded."
        ),
    }


def approved_assets() -> dict[str, Any]:
    from mission_control.application.coordinator.coordinator_surface_promotion import (
        build_coordinator_surface,
    )

    skill_root = ".agents/skills/mission-control-coordinator"
    skill, prompt = build_coordinator_surface(REPO_ROOT / skill_root)
    evidence = [
        "src/mission_control/application/coordinator/coordinator_surface_promotion.py",
        skill_root,
    ]
    records = _published_definition_records(skill, "definition", evidence)
    records += _published_definition_records(prompt, "definition", evidence)
    manifest_path = "skills/mission-control/manifest.json"
    bundle = json.loads(_repo_file(manifest_path))
    key = f"skill-bundle-manifest:{bundle['name']}/{bundle['version']}"
    records.append(
        _asset(
            key,
            asset_id=f"skill-bundle-manifest:{bundle['name']}",
            version=bundle["version"],
            kind="skill",
            contract=bundle["schema_version"],
            manifest_ref="repo://" + manifest_path,
            manifest=bundle,
        )
    )
    records.append(_admit(key + ":admit", key, [manifest_path]))
    return {
        "format": SEED_FORMAT,
        "seed_key": "mc.catalog.approved-assets",
        "seed_version": "1.0.0",
        "component_compatibility": COMPATIBILITY,
        "depends_on": [{"seed_key": "mc.catalog.runtime-profiles", "seed_version": "1.0.0"}],
        "actor_ref": SEED_ACTOR,
        "description": (
            "Reviewed assets that exist in this repository: skill.mission-control-coordinator and "
            "prompt.coordinator.propose-workflow (published-definition revision 1) and the "
            "canonical skills/mission-control bundle manifest. Skill bytes are not uploaded here; "
            "remote byte admission remains a separate capability-bundles registration."
        ),
        "records": records,
    }


# Applied seed bytes are immutable. `mc.app.bindings@1.0.0` was applied to both live
# projects on 2026-10-03 while targets still held operator placeholders; it is frozen here
# by file SHA-256 and never regenerated. Later target facts ship as a new seed version
# with a new asset version, so nothing is overwritten.
FROZEN_BUNDLES = {
    # Recorded by hand with submit_output revision 2 (OVE-170, 2026-10-29); frozen when 1.2.0
    # added knowledge_read_intent (OVE-204 slice 4).
    "common/mc.catalog.knowledge-tools-1.1.0.json": (
        "0adf290a6488e43451e43e58d4ebc16f56f1c93bd564a6ff946cabea4215ed8a"
    ),
    # Applied to both Sprint OC remotes (W0); frozen when 1.0.1 added the WI-08 W2 schemas.
    "common/mc.catalog.artifact-schemas-1.0.0.json": (
        "403f5c2128ace752bcdc0ba2f1e8a999d42a6b0315bff7e89d337768461d6838"
    ),
    # Applied live to AI Engineer on 2026-10-18 (Run 2 close-out, D5).
    "ai-engineer/mc.app.ai-engineer.artifact-schemas-1.0.0.json": (
        "22e9ed163b313156892ca2c07cea7a971f8cd15e96a28872b514d8c1196830c2"
    ),
    # Applied to both Sprint OC remotes on 2026-10-28 (W0); 1.0.1 adds the WI-23 graph.
    "common/mc.catalog.runtime-profiles-1.0.0.json": (
        "127f79d18226baab0c6fa99a11aea215198a6d3bb1799e09bc59c70022788db8"
    ),
    # Applied to both Sprint OC remotes (W1, OVE-169 D15); frozen when 1.0.5 recorded the
    # nested-program registration (OVE-176 WI-13).
    "common/mc.catalog.workflow-parity-1.0.4.json": (
        "92c990882f9ab6d4ec8fb51f0cce1e610e33b1668969adc4cf1bd86d9559c117"
    ),
    # Applied to both Sprint OC remotes with 1.7.0 (W0); frozen when 1.0.4 recorded the
    # root's family failure terminalization activity (OVE-169 W1 D15).
    "common/mc.catalog.workflow-parity-1.0.3.json": (
        "9dccfa2c6abada4d920121f824f8a23368bf934e8b1572a27014d85819e890c0"
    ),
    "common/mc.catalog.workflow-parity-1.0.2.json": (
        "7c7c5c7fe9bd2e978b4b43d6c6094406dde35d9ad39a813bf0e57bd0df26f35a"
    ),
    # The Model Catalog authoring guidance (author 0.3.2, Sprint OC R7, OVE-201), frozen when
    # 1.0.4 shipped the per-application knowledge charter skills (OVE-204 slice 6).
    "biotech/mc.app.biotech.agent-skills-1.0.3.json": (
        "139fc72afda9faf55ec427615f4bc16ed430c80aea45fdf2ea5fefa4b5ace925"
    ),
    "ai-engineer/mc.app.ai-engineer.agent-skills-1.0.3.json": (
        "5285435b30dc163a3e0f411f4917828490b49e1a047975d1d007c207cb04b7de"
    ),
    # The Run 2 skill successor (author and observe 0.3.1), frozen when 1.0.3 shipped the
    # Model Catalog authoring guidance (Sprint OC R7, OVE-201).
    "biotech/mc.app.biotech.agent-skills-1.0.2.json": (
        "3471e24ef28e46035fe5ea655cc32068af31cd231583963901f9d4c0369c9d5d"
    ),
    "ai-engineer/mc.app.ai-engineer.agent-skills-1.0.2.json": (
        "7d0b7d95049aee6b240284cc18fa3309c0996889b65c626fe966725446433044"
    ),
    "biotech/mc.app.biotech.agent-skills-1.0.1.json": (
        "7c3cd13ca7a87a60478c6a10b09828dab5df040c8d78d5938a8ba5a8d4c64f85"
    ),
    "ai-engineer/mc.app.ai-engineer.agent-skills-1.0.1.json": (
        "9a6cbadb6f8cf66038391db87c1b5275465182b1a15ebe4c88b74b0012eb8cef"
    ),
    "common/mc.catalog.approved-assets-1.0.1.json": (
        "ff21d0c9026345eeefbcf81d2f0110e7737b4bd848ff410e75d0b465e6dd009c"
    ),
    "biotech/mc.app.biotech.agent-skills-1.0.0.json": (
        "29743578f31a220a1330d22642256b3741b733abb0248926c62d982a4d656280"
    ),
    "ai-engineer/mc.app.ai-engineer.agent-skills-1.0.0.json": (
        "38dab7d6d508cee67e6093965e31381e97d3bbf85f88d1912b0ae619a3b0a832"
    ),
    # Preserve the Human Gate registration snapshot when terminal result activity wiring
    # advances. Existing receipts must remain reproducible regardless of apply status.
    "common/mc.catalog.workflow-parity-1.0.1.json": (
        "2504aafca510ccb17803e113460a8853bb3a43d1b02b27795a647de260a471cb"
    ),
    # A dependency of the applied approved-assets 1.0.0 (2026-10-03); the registered families
    # moved on (MP-10 Human Gate workflow), so the successor 1.0.1 carries asset version 2.
    "common/mc.catalog.workflow-parity-1.0.0.json": (
        "9305587bbfeff823835e7f0ad9ea1ecdb54bf5a403e0006a28568af0d164b739"
    ),
    # Applied to both live projects on 2026-10-03 (seed digest sha256:f45e04f9...). Its
    # sources moved on (FT-A1 relabelled the coordinator skill kind, the router manifest is
    # newer), so the successor below carries only the logical keys 1.0.0 does not hold.
    "common/mc.catalog.approved-assets-1.0.0.json": (
        "7c0e1f497726f776aeafc943b3eda9207c6c932b1529e37b44dae2b6b464ec1b"
    ),
    "biotech/mc.app.bindings-1.0.0.json": (
        "4cc5c1203b0fd0b9cabc8e0ebcaba2662cda427a4e5f4b876eb2f9b7790802c4"
    ),
    "ai-engineer/mc.app.bindings-1.0.0.json": (
        "a1364312eac8ad4fd2512888d1312f5eb574f8e261476dc339923fc9d4f493cb"
    ),
}
CURRENT_BINDING = ("1.0.1", "2")  # (seed_version, asset version)


def frozen_bundle(relative: str) -> dict[str, Any]:
    payload = (SEEDS_ROOT / relative).read_bytes()
    if _sha256_bytes(payload) != "sha256:" + FROZEN_BUNDLES[relative]:
        raise SystemExit(f"frozen applied seed bundle changed: {relative}")
    return dict(json.loads(payload))


APPROVED_ASSETS_FROZEN = "common/mc.catalog.approved-assets-1.0.0.json"


def approved_assets_successor() -> dict[str, Any]:
    """`mc.catalog.approved-assets@1.0.2`: the approved-asset records whose logical keys the
    applied 1.0.0 bundle does not hold (today the newer `skills/mission-control` manifest).

    Records 1.0.0 already holds are never re-emitted, even when their sources changed: an
    applied logical key with different bytes is a seed conflict. A changed definition needs
    a new definition revision (an owner decision), not new bytes under revision 1.
    """

    frozen = frozen_bundle(APPROVED_ASSETS_FROZEN)
    previous = frozen_bundle("common/mc.catalog.approved-assets-1.0.1.json")
    held = {record["logical_key"] for bundle in (frozen, previous) for record in bundle["records"]}
    current = approved_assets()
    return {
        **current,
        "seed_version": "1.0.2",
        "depends_on": [{"seed_key": "mc.catalog.approved-assets", "seed_version": "1.0.1"}],
        "description": (
            "Successor of mc.catalog.approved-assets@1.0.1 (applied, frozen): the reviewed "
            "approved assets whose logical keys neither applied version holds, including the "
            "canonical "
            "skills/mission-control bundle manifest at its present version. The coordinator "
            "skill and prompt definitions stay at the applied revision 1."
        ),
        "records": [record for record in current["records"] if record["logical_key"] not in held],
    }


def app_bindings(app: str) -> dict[str, Any]:
    seed_version, asset_version = CURRENT_BINDING
    target_path = f"deployments/{app}/target.toml"
    target_bytes = _repo_file(target_path)
    target = tomllib.loads(target_bytes.decode("utf-8"))["target"]
    unresolved = sorted(
        name
        for name, value in target.items()
        if isinstance(value, str) and value.startswith("REPLACE")
    )
    manifest = {
        "binding": "mission-control.app-binding/1",
        "application_id": target["application_id"],
        "project_label": target["project_label"],
        "project_ref": target["project_ref"],
        "installation_id": target["installation_id"],
        "target_ref": target_path,
        "target_sha256": _sha256_bytes(target_bytes),
        "secret_reference_names": {"migration_database_url_env": target["database_url_env"]},
        "common_catalog_seeds": [
            "mc.catalog.workflow-parity@1.0.0",
            "mc.catalog.runtime-profiles@1.0.0",
            "mc.catalog.approved-assets@1.0.0",
        ],
        "unresolved_operator_fields": unresolved,
        "approved_tenant_actor_mappings": [],
        "supersedes": f"app-binding:{app}@1",
    }
    key = f"app-binding:{app}/{asset_version}"
    return {
        "format": SEED_FORMAT,
        "seed_key": "mc.app.bindings",
        "seed_version": seed_version,
        "component_compatibility": COMPATIBILITY,
        "depends_on": [
            {"seed_key": "mc.catalog.approved-assets", "seed_version": "1.0.0"},
            {"seed_key": "mc.app.bindings", "seed_version": "1.0.0"},
        ],
        "actor_ref": SEED_ACTOR,
        "description": (
            f"Installation binding for app '{app}': identity facts copied from {target_path} and "
            "secret reference NAMES only. No tenant/actor mapping or grant is seeded until "
            "owner-approved (approved_tenant_actor_mappings is a documented empty placeholder)."
        ),
        "records": [
            _asset(
                key,
                asset_id=f"app-binding:{app}",
                version=asset_version,
                kind="profile",
                contract="mission-control.app-binding/1",
                manifest_ref="repo://" + target_path,
                manifest=manifest,
            ),
            _admit(key + ":admit", key, [target_path]),
        ],
    }


def qualification_parity() -> dict[str, Any]:
    from mission_control.domain.authoring.fixtures import (
        GENERIC_GOAL_DIRECTED,
        GENERIC_STAGE_GRAPH,
    )

    evidence = ["src/mission_control/domain/authoring/fixtures.py"]
    records: list[dict[str, Any]] = [
        {
            "kind": "tenant",
            "logical_key": "qualification:mission-control-parity",
            "fields": {
                "external_tenant_ref": "qualification:mission-control-parity",
                "state": "active",
                "qualification_fixture": True,
            },
        }
    ]
    records += _published_definition_records(GENERIC_STAGE_GRAPH, "qualification", evidence)
    records += _published_definition_records(GENERIC_GOAL_DIRECTED, "qualification", evidence)
    return {
        "format": SEED_FORMAT,
        "seed_key": "mc.qualification.parity",
        "seed_version": "1.0.0",
        "component_compatibility": COMPATIBILITY,
        "depends_on": [{"seed_key": "mc.catalog.workflow-parity", "seed_version": "1.0.0"}],
        "actor_ref": SEED_ACTOR,
        "description": (
            "OPT-IN SYNTHETIC QUALIFICATION FIXTURE. A clearly labeled qualification tenant "
            "(qualification_fixture=true) and the deterministic generic StageGraph/GoalDirected "
            "contract-fixture blueprints. Not production provider support, not real usage; no "
            "actors, grants, missions, runs or receipts."
        ),
        "records": records,
    }


def agent_capabilities() -> dict[str, dict[str, Any]]:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "mc_seed_agent_capabilities", SEEDS_ROOT / "agent_capabilities.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def published(definition: Any, key_prefix: str, evidence: list[str]) -> list[dict[str, Any]]:
        return _published_definition_records(
            definition, key_prefix, evidence, published_at=module.AGENT_SEED_TIME
        )

    return dict(module.bundles(published, SEED_FORMAT, COMPATIBILITY, SEED_ACTOR))


def agent_skills() -> dict[str, dict[str, Any]]:
    """FT-A7: per-application skill bundles, the policy hook and the web-research plugin."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "mc_seed_agent_skills", SEEDS_ROOT / "agent_skills.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def published(
        definition: Any, key_prefix: str, evidence: list[str], *, revision: int = 1
    ) -> list[dict[str, Any]]:
        return _published_definition_records(
            definition,
            key_prefix,
            evidence,
            published_at=module.AGENT_SKILL_SEED_TIME,
            revision=revision,
        )

    return dict(module.bundles(published, SEED_FORMAT, COMPATIBILITY, SEED_ACTOR))


def environment_kits() -> dict[str, dict[str, Any]]:
    """MO-12: per-application starter Environment Kits."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "mc_seed_environment_kits", SEEDS_ROOT / "environment_kits.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def published(definition: Any, key_prefix: str, evidence: list[str]) -> list[dict[str, Any]]:
        return _published_definition_records(
            definition, key_prefix, evidence, published_at=module.ENVIRONMENT_KIT_SEED_TIME
        )

    return dict(module.bundles(published, SEED_FORMAT, COMPATIBILITY, SEED_ACTOR))


def cognition_profiles() -> dict[str, dict[str, Any]]:
    """MO-35: portable task-family Cognition Profiles, independently versioned."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "mc_seed_cognition_profiles", SEEDS_ROOT / "cognition_profiles.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def published(definition: Any, key_prefix: str, evidence: list[str]) -> list[dict[str, Any]]:
        return _published_definition_records(
            definition, key_prefix, evidence, published_at=module.SEED_TIME
        )

    return dict(module.bundles(published, SEED_FORMAT, COMPATIBILITY, SEED_ACTOR))


def signal_skills() -> dict[str, dict[str, Any]]:
    """MO-44: portable signal skill bundles, independently versioned."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "mc_seed_signal_skills", SEEDS_ROOT / "signal_skills.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return dict(module.bundles())


def storage_capability_bundles() -> dict[str, Any]:
    """FT-A2 / ADR-0024: the private capability-bundles bucket and its four policies.

    ``${application_id}`` resolves to the target application at apply time, so one common
    bundle scopes every policy to that application's top-level prefix.
    """

    def policy(key: str, command: str, role: str, *, restrictive: bool = False) -> dict:
        fields: dict[str, Any] = {
            "bucket_id": "capability-bundles",
            "policy": f"mc_capability_bundles_{key.replace('-', '_')}",
            "command": command,
            "capability_role": role,
        }
        if restrictive:
            fields["restrictive"] = True
        return {
            "kind": "storage_policy",
            "logical_key": f"storage:capability-bundles:{key}",
            "fields": fields,
        }

    return {
        "format": SEED_FORMAT,
        "seed_key": "mc.storage.capability-bundles",
        "seed_version": "1.0.0",
        "component_compatibility": COMPATIBILITY,
        "depends_on": [],
        "actor_ref": SEED_ACTOR,
        "description": (
            "Private capability-bundles bucket (50 MiB per object, any MIME type) and its "
            "storage.objects policies, each scoped to the application's top-level prefix: "
            "publisher INSERT, publisher SELECT (verify before treating an existing path as "
            "published), reader SELECT (signed download URLs), and a restrictive prefix guard. "
            "No UPDATE or DELETE policy exists, so a digest path is never overwritten. "
            "Targets without the Storage schema report this bundle blocked."
        ),
        "records": [
            {
                "kind": "storage_bucket",
                "logical_key": "storage:capability-bundles",
                "fields": {
                    "bucket_id": "capability-bundles",
                    "public": False,
                    "file_size_limit": 52_428_800,
                },
            },
            policy("publisher-insert", "INSERT", "publisher"),
            policy("publisher-select", "SELECT", "publisher"),
            policy("reader-select", "SELECT", "reader"),
            policy("application-prefix-guard", "ALL", "*", restrictive=True),
        ],
    }


def storage_mission_payloads() -> dict[str, Any]:
    """OVE-204 slice 7: the private mission-payloads bucket behind `S3ArtifactPayloadStore`.

    Mission Control reaches it through the Supabase Storage S3 endpoint with the project's S3
    access keys (service role, which bypasses RLS), so it carries no ``storage.objects`` policy:
    no client role can list, read or write it.
    """

    return {
        "format": SEED_FORMAT,
        "seed_key": "mc.storage.mission-payloads",
        "seed_version": "1.0.0",
        "component_compatibility": COMPATIBILITY,
        "depends_on": [],
        "actor_ref": SEED_ACTOR,
        "description": (
            "Private mission-payloads bucket (50 MiB per object, any MIME type) for the "
            "content-addressed artifact and context payloads Mission Control stages through "
            "the S3-compatible Storage endpoint with service-role S3 keys. No storage.objects "
            "policy grants a client role any access. Targets without the Storage schema "
            "report this bundle blocked."
        ),
        "records": [
            {
                "kind": "storage_bucket",
                "logical_key": "storage:mission-payloads",
                "fields": {
                    "bucket_id": "mission-payloads",
                    "public": False,
                    "file_size_limit": 52_428_800,
                },
            }
        ],
    }


def build_bundles() -> dict[str, dict[str, Any]]:
    bundles = {
        "common/mc.catalog.workflow-parity-1.0.5.json": workflow_parity_successor(),
        "common/mc.catalog.runtime-profiles-1.0.1.json": runtime_profiles_successor(),
        "common/mc.catalog.approved-assets-1.0.2.json": approved_assets_successor(),
        "qualification/mc.qualification.parity-1.0.0.json": qualification_parity(),
    }
    for relative in FROZEN_BUNDLES:
        bundles[relative] = frozen_bundle(relative)
    for app in APPS:
        bundles[f"{app}/mc.app.bindings-{CURRENT_BINDING[0]}.json"] = app_bindings(app)
    bundles.update(agent_capabilities())
    bundles.update(agent_skills())
    bundles.update(environment_kits())
    bundles.update(cognition_profiles())
    bundles.update(signal_skills())
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "mc_watcher_library", SEEDS_ROOT / "watcher_library.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    bundles.update(
        module.bundles(
            lambda definition, prefix, evidence: _published_definition_records(
                definition, prefix, evidence, published_at=module.SEED_TIME
            ),
            SEED_FORMAT,
            COMPATIBILITY,
            SEED_ACTOR,
        )
    )
    artifact_spec = importlib.util.spec_from_file_location(
        "mc_artifact_schemas", SEEDS_ROOT / "artifact_schemas.py"
    )
    assert artifact_spec is not None and artifact_spec.loader is not None
    artifact_module = importlib.util.module_from_spec(artifact_spec)
    artifact_spec.loader.exec_module(artifact_module)
    bundles.update(artifact_module.bundles(_published_definition_records, SEED_FORMAT, SEED_ACTOR))
    # D5: AI Engineer SDLC report schemas, an additive app-scoped bundle in its own slot.
    sdlc_spec = importlib.util.spec_from_file_location(
        "mc_sdlc_report_schemas", SEEDS_ROOT / "sdlc_report_schemas.py"
    )
    assert sdlc_spec is not None and sdlc_spec.loader is not None
    sdlc_module = importlib.util.module_from_spec(sdlc_spec)
    sdlc_spec.loader.exec_module(sdlc_module)
    bundles.update(sdlc_module.bundles(_published_definition_records, SEED_FORMAT, SEED_ACTOR))
    # OVE-171 / WI-08: the W2 graph-variant schemas, a successor version of the common schema
    # seed in its own file (the applied 1.0.0 bytes stay as they are).
    graph_spec = importlib.util.spec_from_file_location(
        "mc_graph_route_schemas", SEEDS_ROOT / "graph_route_schemas.py"
    )
    assert graph_spec is not None and graph_spec.loader is not None
    graph_module = importlib.util.module_from_spec(graph_spec)
    graph_spec.loader.exec_module(graph_module)
    bundles.update(graph_module.bundles(_published_definition_records, SEED_FORMAT, SEED_ACTOR))
    # A frozen applied bundle is its recorded bytes, never a regeneration from moved sources.
    bundles.update(
        {relative: frozen_bundle(relative) for relative in FROZEN_BUNDLES if relative in bundles}
    )
    bundles["common/mc.storage.capability-bundles-1.0.0.json"] = storage_capability_bundles()
    bundles["common/mc.storage.mission-payloads-1.0.0.json"] = storage_mission_payloads()
    # Sprint V SV-16: the knowledge tools as catalog tool capability rows (1.0.0, the
    # recorded 1.1.0 and 1.2.0 with knowledge_read_intent, OVE-204 slice 4).
    knowledge_spec = importlib.util.spec_from_file_location(
        "mc_knowledge_tools", SEEDS_ROOT / "knowledge_tools.py"
    )
    assert knowledge_spec is not None and knowledge_spec.loader is not None
    knowledge_module = importlib.util.module_from_spec(knowledge_spec)
    knowledge_spec.loader.exec_module(knowledge_module)
    bundles.update(
        knowledge_module.bundles(
            lambda definition, prefix, evidence, published_at=knowledge_module.SEED_TIME: (
                _published_definition_records(
                    definition, prefix, evidence, published_at=published_at
                )
            ),
            SEED_FORMAT,
            COMPATIBILITY,
            SEED_ACTOR,
        )
    )
    return bundles


def encode(bundle: dict[str, Any]) -> bytes:
    return (json.dumps(bundle, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args()
    drift = []
    for relative, bundle in build_bundles().items():
        path = SEEDS_ROOT / relative
        payload = encode(bundle)
        if args.write:
            if relative in FROZEN_BUNDLES:
                continue  # applied bytes are never rewritten
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        elif not path.exists() or json.loads(path.read_bytes()) != bundle:
            drift.append(relative)
    if drift:
        print("seed bundles drifted from their sources: " + ", ".join(drift), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
