"""The committed production bundle supplies S0 schema authority."""

import importlib.util
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from mission_control.application.programs.artifact_validation import supported_schema
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import ArtifactSchemaDefinition, PublishedDefinition

ROOT = Path(__file__).resolve().parents[3]
SEEDS = ROOT / "packages/mission-control-db-contract/seeds"


def production_record():
    bundle = json.loads((SEEDS / "common/mc.catalog.artifact-schemas-1.0.0.json").read_text())
    asset = next(row for row in bundle["records"] if row["kind"] == "asset_version")
    return PublishedDefinition.model_validate(asset["fields"]["manifest"])


def test_production_schema_seed_has_exact_authority_and_deterministic_generation():
    record = production_record()
    assert isinstance(record.definition, ArtifactSchemaDefinition)
    assert f"{record.ref.logical_id}@{record.ref.revision}" == "schema.s0-probe-report@1"
    assert record.ref.digest == sha256_digest(record.definition)
    assert supported_schema(record.definition.json_schema)
    spec = importlib.util.spec_from_file_location(
        "artifact_generator", SEEDS / "generate_catalog_seeds.py"
    )
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    generated = generator.build_bundles()["common/mc.catalog.artifact-schemas-1.0.0.json"]
    assert (
        generator.encode(generated)
        == (SEEDS / "common/mc.catalog.artifact-schemas-1.0.0.json").read_bytes()
    )


def test_s0_schema_requires_criteria_and_evidence_without_claiming_qualification():
    schema = production_record().definition.json_schema
    validator = Draft202012Validator(schema)
    report = {name: {"disposition": "unrun", "evidence_refs": []} for name in schema["required"]}
    report.update(
        schema_version="mc.s0_probe_report.v1",
        lane_profile="codex",
        requested_identity=dict.fromkeys(
            ["host", "runtime", "cli", "auth_route", "model"], "explicit-fixture-request"
        ),
    )
    assert validator.is_valid(report), "valid unknown evidence is not acceptance"
    del report["skill_exercised"]
    assert not validator.is_valid(report)
    report["skill_exercised"] = {"disposition": "observed", "evidence_refs": []}
    assert not validator.is_valid(report), "an observation requires its receipt reference"
