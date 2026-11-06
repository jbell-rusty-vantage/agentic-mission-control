"""Production artifact validation authority derived from SPEC-09 and MO-71 criteria.

This report records evidence and unknowns; schema validity never grants qualification.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

SEED_KEY = "mc.catalog.artifact-schemas"
SEED_VERSION = "1.0.0"
SCHEMA_REF = "schema.s0-probe-report@1"
EVIDENCE_SOURCES = [
    "docs/specs/materialization-observation-2026-10/SPEC-09-local-harness-path.md",
    "docs/specs/materialization-observation-2026-10/issues/MO-71-s0-probe-manifests-for-all-three-local-lanes.md",
]


def report_schema() -> dict[str, Any]:
    evidence = {
        "type": "object",
        "additionalProperties": False,
        "required": ["disposition", "evidence_refs"],
        "properties": {
            "disposition": {"enum": ["observed", "failed", "unknown", "unrun"]},
            "evidence_refs": {"type": "array", "items": {"type": "string", "minLength": 1}},
        },
        "if": {"properties": {"disposition": {"const": "observed"}}},
        "then": {"properties": {"evidence_refs": {"minItems": 1}}},
    }
    fields = {
        "schema_version": {"const": "mc.s0_probe_report.v1"},
        "lane_profile": {"enum": ["claude_agent_sdk", "codex", "cursor_local"]},
        # Requested and observed identity are distinct; unknown is explicit evidence.
        "requested_identity": {
            "type": "object",
            "additionalProperties": False,
            "required": ["host", "runtime", "cli", "auth_route", "model"],
            "properties": {
                name: {"type": "string", "minLength": 1}
                for name in ["host", "runtime", "cli", "auth_route", "model"]
            },
        },
    }
    for name in [
        "observed_identity",
        "configuration",
        "repository_instructions",
        "skill_delivered",
        "skill_read_back",
        "skill_exercised",
        "tool_allow",
        "tool_deny",
        "inject",
        "cancel",
        "immutable_output",
        "caller_wakeup",
        "usage",
        "cleanup",
    ]:
        fields[name] = {"$ref": "#/$defs/evidence"}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": list(fields),
        "properties": fields,
        "$defs": {"evidence": evidence},
    }


def definitions() -> list[Any]:
    from mission_control.domain.authoring.contracts import ArtifactSchemaDefinition

    return [
        ArtifactSchemaDefinition(
            logical_id="schema.s0-probe-report",
            title="S0 local harness probe report",
            description="SPEC-09/MO-71 evidence report; validation is separate from acceptance.",
            json_schema=report_schema(),
        )
    ]


def bundles(published_records: Any, seed_format: str, actor: str) -> dict[str, Any]:
    records = []
    for definition in definitions():
        records += published_records(
            definition,
            "artifact-schema",
            EVIDENCE_SOURCES,
            published_at=datetime(2026, 10, 14, tzinfo=UTC),
            revision=1,
        )
    return {
        f"common/{SEED_KEY}-{SEED_VERSION}.json": {
            "format": seed_format,
            "seed_key": SEED_KEY,
            "seed_version": SEED_VERSION,
            "component_compatibility": ">=1.4.1 <2.0.0",
            "depends_on": [],
            "actor_ref": actor,
            "description": "Published S0 artifact schema authority.",
            "records": records,
        }
    }
