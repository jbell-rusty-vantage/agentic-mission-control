"""AI Engineer SDLC report schemas (owner decision D5) for the F1 diagnose/patch/review mission.

An additive app-scoped seed in its own slot; the common S0 schema bundle is untouched.
Schema validity records evidence and unknowns; it never grants acceptance or qualification.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

APP = "ai-engineer"
SEED_KEY = f"mc.app.{APP}.artifact-schemas"
SEED_VERSION = "1.0.0"
SEED_TIME = datetime(2026, 10, 18, tzinfo=UTC)
EVIDENCE_SOURCES = [
    "docs/specs/materialization-observation-2026-10/SPEC-01-environments.md",
    "docs/specs/materialization-observation-2026-10/SPEC-02-cognition.md",
    "docs/specs/materialization-observation-2026-10/RUN-2-CLAUDE-CODE-OPUS-INSTRUCTIONS-2026-10-18.md",
    "docs/specs/materialization-observation-2026-10/RUN-2-EXECUTION-SEQUENCE-2026-10-18.md",
]
DECIDED_AT = "2026-10-18T00:00:00Z"
_DIALECT = "https://json-schema.org/draft/2020-12/schema"


def _text() -> dict[str, Any]:
    return {"type": "string", "minLength": 1}


def _refs() -> dict[str, Any]:
    return {"type": "array", "items": _text()}


def _paths() -> dict[str, Any]:
    return {"type": "array", "uniqueItems": True, "items": _text()}


def _digest() -> dict[str, Any]:
    # Bare hex or ``sha256:<hex>``; regex keywords are outside the supported subset.
    return {"type": "string", "minLength": 40, "maxLength": 71}


def _strict(properties: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(properties),
        "properties": properties,
        **extra,
    }


def _when(
    name: str,
    values: list[str],
    then: dict[str, Any],
    otherwise: dict[str, Any] | None = None,
) -> dict[str, Any]:
    branch = {"if": {"properties": {name: {"enum": values}}}, "then": {"properties": then}}
    if otherwise is not None:
        branch["else"] = {"properties": otherwise}
    return branch


def _test_run() -> dict[str, Any]:
    """One test command: observed runs carry exit code and counts; otherwise all are null."""
    count = {"type": ["integer", "null"], "minimum": 0}
    return _strict(
        {
            "command": _text(),
            "disposition": {"enum": ["observed", "unknown", "unrun"]},
            "exit_code": {"type": ["integer", "null"]},
            "passed": count,
            "failed": count,
        },
        **_when(
            "disposition",
            ["observed"],
            {
                "exit_code": {"type": "integer"},
                "passed": {"type": "integer"},
                "failed": {"type": "integer"},
            },
            dict.fromkeys(("exit_code", "passed", "failed"), {"type": "null"}),
        ),
    )


def _document(
    version: str, properties: dict[str, Any], *, tests: bool = False, **extra: Any
) -> dict[str, Any]:
    document = {
        "$schema": _DIALECT,
        **_strict({"schema_version": {"const": version}, **properties}, **extra),
    }
    if tests:
        document["$defs"] = {"test_run": _test_run()}
    return document


def diagnosis_schema() -> dict[str, Any]:
    command = _strict({"command": _text(), "exit_code": {"type": ["integer", "null"]}})
    reproduction = _strict(
        {
            "disposition": {"enum": ["observed", "failed", "unknown", "unrun"]},
            "commands": {"type": "array", "items": command},
            "evidence_refs": _refs(),
        },
        # A run reproduction names every command's exit code and its evidence (S0 precedent).
        **_when(
            "disposition",
            ["observed", "failed"],
            {
                "commands": {
                    "minItems": 1,
                    "items": {"properties": {"exit_code": {"type": "integer"}}},
                },
                "evidence_refs": {"minItems": 1},
            },
        ),
    )
    root_cause = _strict(
        {
            "disposition": {"enum": ["identified", "unknown", "unrun"]},
            "summary": {"type": "string"},
        },
        **_when("disposition", ["identified"], {"summary": {"minLength": 1}}),
    )
    return _document(
        "mc.sdlc_diagnosis_report.v1",
        {
            "subject": _strict({"issue": _text(), "source_ref": _text()}),
            "reproduction": reproduction,
            "root_cause": root_cause,
            "affected_files": _paths(),
            "evidence_refs": _refs(),
            "disposition": {"enum": ["diagnosed", "not_reproduced", "unknown", "unrun"]},
        },
        **_when(
            "disposition",
            ["diagnosed"],
            {
                "affected_files": {"minItems": 1},
                "evidence_refs": {"minItems": 1},
                "root_cause": {"properties": {"disposition": {"const": "identified"}}},
                "reproduction": {"properties": {"disposition": {"enum": ["observed", "failed"]}}},
            },
        ),
    )


def patch_schema() -> dict[str, Any]:
    return _document(
        "mc.sdlc_patch_report.v1",
        {
            "base_commit": {"type": "string", "minLength": 7, "maxLength": 64},
            "head_or_diff_sha256": _digest(),
            "changed_files": {**_paths(), "minItems": 1},
            "summary": _text(),
            "tests": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/test_run"}},
            "risks": {"type": "array", "items": _text()},
            "evidence_refs": _refs(),
        },
        tests=True,
    )


def review_schema() -> dict[str, Any]:
    finding = _strict(
        {
            "severity": {"enum": ["defect", "missing_evidence", "suggestion"]},
            "file": _text(),
            "line": {"type": ["integer", "null"], "minimum": 1},
            "summary": _text(),
            "correction": {"type": "string"},
        }
    )
    return _document(
        "mc.sdlc_review_report.v1",
        {
            "reviewed_diff_sha256": _digest(),
            "reviewer_role": _text(),
            "verdict": {"enum": ["approve", "approve_with_nits", "changes_required"]},
            "findings": {"type": "array", "items": finding},
            "tests_rerun": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/test_run"}},
            "evidence_refs": _refs(),
        },
        tests=True,
        **_when("verdict", ["changes_required"], {"findings": {"minItems": 1}}),
    )


def definitions() -> list[Any]:
    from mission_control.domain.authoring.contracts import ArtifactSchemaDefinition

    note = "validation records evidence and unknowns; it is separate from acceptance."
    return [
        ArtifactSchemaDefinition(
            logical_id="schema.sdlc-diagnosis-report",
            title="SDLC diagnosis report",
            description=f"F1 diagnosis: reproduction, root cause, affected files; {note}",
            json_schema=diagnosis_schema(),
        ),
        ArtifactSchemaDefinition(
            logical_id="schema.sdlc-patch-report",
            title="SDLC patch report",
            description=f"F1 patch: base, diff digest, changed files, tests, risks; {note}",
            json_schema=patch_schema(),
        ),
        ArtifactSchemaDefinition(
            logical_id="schema.sdlc-review-report",
            title="SDLC review report",
            description=f"F1 independent review: verdict, findings, rerun tests; {note}",
            json_schema=review_schema(),
        ),
    ]


def bundles(published_records: Any, seed_format: str, actor: str) -> dict[str, Any]:
    records = []
    for definition in definitions():
        records += published_records(
            definition, "artifact-schema", EVIDENCE_SOURCES, published_at=SEED_TIME, revision=1
        )
    for record in records:
        # This bundle's own admission time; the shared generator default stays untouched.
        if record["kind"] == "asset_decision":
            record["fields"]["decided_at"] = DECIDED_AT
    return {
        f"{APP}/{SEED_KEY}-{SEED_VERSION}.json": {
            "format": seed_format,
            "seed_key": SEED_KEY,
            "seed_version": SEED_VERSION,
            "component_compatibility": ">=1.4.1 <2.0.0",
            "depends_on": [],
            "actor_ref": actor,
            "description": (
                "AI Engineer SDLC diagnosis, patch and review report schemas (owner decision "
                "D5), additive to the common S0 schema; schema validity is not acceptance."
            ),
            "records": records,
        }
    }
