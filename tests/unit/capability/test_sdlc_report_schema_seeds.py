"""The committed AI Engineer bundle supplies the D5 SDLC report-schema authority."""

import copy
import importlib.util
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from mission_control.application.programs.artifact_validation import supported_schema
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import ArtifactSchemaDefinition, PublishedDefinition

ROOT = Path(__file__).resolve().parents[3]
SEEDS = ROOT / "packages/mission-control-db-contract/seeds"
RELATIVE = "ai-engineer/mc.app.ai-engineer.artifact-schemas-1.0.0.json"
DIAGNOSIS, PATCH, REVIEW = (
    "schema.sdlc-diagnosis-report",
    "schema.sdlc-patch-report",
    "schema.sdlc-review-report",
)
RUN = {"command": "pytest -q", "disposition": "observed", "exit_code": 0, "passed": 4, "failed": 0}
UNRUN = {"command": "pytest -q", "disposition": "unrun", "exit_code": None}
UNRUN |= {"passed": None, "failed": None}
SAMPLES = {
    DIAGNOSIS: {
        "schema_version": "mc.sdlc_diagnosis_report.v1",
        "subject": {"issue": "config:<key> unresolved", "source_ref": "c49862bf"},
        "reproduction": {
            "disposition": "observed",
            "commands": [{"command": "pytest -q tests/unit", "exit_code": 1}],
            "evidence_refs": ["runner-tests.json"],
        },
        "root_cause": {"disposition": "identified", "summary": "no configuration source"},
        "affected_files": ["src/mission_control/bootstrap/manifests.py"],
        "evidence_refs": ["prepared-source.json"],
        "disposition": "diagnosed",
    },
    PATCH: {
        "schema_version": "mc.sdlc_patch_report.v1",
        "base_commit": "af2d24fc",
        "head_or_diff_sha256": "sha256:" + "a" * 64,
        "changed_files": ["src/mission_control/bootstrap/manifests.py"],
        "summary": "installation configuration source",
        "tests": [RUN, UNRUN],
        "risks": [],
        "evidence_refs": ["runner-tests.json"],
    },
    REVIEW: {
        "schema_version": "mc.sdlc_review_report.v1",
        "reviewed_diff_sha256": "sha256:" + "a" * 64,
        "reviewer_role": "subagent.mc-cognition-reviewer",
        "verdict": "approve",
        "findings": [],
        "tests_rerun": [RUN],
        "evidence_refs": [],
    },
}


def records() -> dict[str, PublishedDefinition]:
    bundle = json.loads((SEEDS / RELATIVE).read_text(encoding="utf-8"))
    result = {}
    for row in bundle["records"]:
        if row["kind"] == "asset_version":
            published = PublishedDefinition.model_validate(row["fields"]["manifest"])
            result[published.ref.logical_id] = published
    return result


def validator(logical_id: str) -> Draft202012Validator:
    definition = records()[logical_id].definition
    assert isinstance(definition, ArtifactSchemaDefinition)
    return Draft202012Validator(definition.json_schema)


def changed(logical_id: str, path: tuple, value: object) -> dict:
    sample = copy.deepcopy(SAMPLES[logical_id])
    node = sample
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return sample


def test_schema_seed_has_exact_authority_and_deterministic_generation():
    published = records()
    assert {f"{ref.ref.logical_id}@{ref.ref.revision}" for ref in published.values()} == {
        f"{DIAGNOSIS}@1",
        f"{PATCH}@1",
        f"{REVIEW}@1",
    }
    for record in published.values():
        assert isinstance(record.definition, ArtifactSchemaDefinition)
        assert record.ref.digest == sha256_digest(record.definition)
        assert supported_schema(record.definition.json_schema)
        assert record.definition.json_schema["additionalProperties"] is False
    spec = importlib.util.spec_from_file_location(
        "sdlc_generator", SEEDS / "generate_catalog_seeds.py"
    )
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    assert generator.encode(generator.build_bundles()[RELATIVE]) == (SEEDS / RELATIVE).read_bytes()


@pytest.mark.parametrize("logical_id", [DIAGNOSIS, PATCH, REVIEW])
def test_valid_reports_and_explicit_unknowns_validate(logical_id):
    check = validator(logical_id)
    assert check.is_valid(SAMPLES[logical_id])
    assert not check.is_valid({**SAMPLES[logical_id], "unexpected": True})
    assert not check.is_valid({**SAMPLES[logical_id], "schema_version": "other.v1"})
    unknown = {
        "schema_version": "mc.sdlc_diagnosis_report.v1",
        "subject": SAMPLES[DIAGNOSIS]["subject"],
        "reproduction": {"disposition": "unrun", "commands": [], "evidence_refs": []},
        "root_cause": {"disposition": "unknown", "summary": ""},
        "affected_files": [],
        "evidence_refs": [],
        "disposition": "unknown",
    }
    assert validator(DIAGNOSIS).is_valid(unknown), "valid unknown evidence is not acceptance"


@pytest.mark.parametrize(
    ("logical_id", "path", "value"),
    [
        # 1. A test that did not run carries no exit code or counts.
        (PATCH, ("tests", 1, "exit_code"), 0),
        (PATCH, ("tests", 1, "passed"), 5),
        (REVIEW, ("tests_rerun", 0), {**RUN, "disposition": "unknown"}),
        (PATCH, ("tests", 0, "exit_code"), None),
        # 2. A diagnosis needs an identified root cause and a run reproduction.
        (DIAGNOSIS, ("root_cause", "disposition"), "unknown"),
        (
            DIAGNOSIS,
            ("reproduction",),
            {"disposition": "unrun", "commands": [], "evidence_refs": []},
        ),
        (DIAGNOSIS, ("root_cause", "summary"), ""),
        (DIAGNOSIS, ("affected_files",), []),
        # 3. A run reproduction names exit codes and evidence.
        (DIAGNOSIS, ("reproduction", "commands", 0, "exit_code"), None),
        (DIAGNOSIS, ("reproduction", "evidence_refs"), []),
        (DIAGNOSIS, ("reproduction", "commands"), []),
        # 4. Absent tests are explicit unrun entries, never an empty list.
        (PATCH, ("tests",), []),
        (REVIEW, ("tests_rerun",), []),
        # Review verdicts and findings stay typed.
        (REVIEW, ("verdict",), "changes_required"),
        (REVIEW, ("verdict",), "lgtm"),
        (
            REVIEW,
            ("findings",),
            [{"severity": "blocker", "file": "a.py", "line": 1, "summary": "s", "correction": ""}],
        ),
    ],
)
def test_reports_without_their_evidence_are_refused(logical_id, path, value):
    assert not validator(logical_id).is_valid(changed(logical_id, path, value))
