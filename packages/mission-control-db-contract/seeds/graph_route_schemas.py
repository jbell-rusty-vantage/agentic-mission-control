"""Sprint OC W2 graph-variant schemas (OVE-171 / WI-08): the structured outputs whose typed facts
drive the W2 route and Revisit Region fixtures (`tests/fixtures/manifests/sprint-oc-w2/`).

A successor of `mc.catalog.artifact-schemas@1.0.0` in its own file: the applied 1.0.0 bytes are
untouched and this version carries only the new logical keys. Schema validity records evidence;
it never grants acceptance.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

SEED_KEY = "mc.catalog.artifact-schemas"
SEED_VERSION = "1.0.1"
PREVIOUS_VERSION = "1.0.0"
SEED_TIME = datetime(2026, 10, 29, tzinfo=UTC)
DECIDED_AT = "2026-10-29T00:00:00Z"
EVIDENCE_SOURCES = [
    "mission-control-general/general-mission-control/OUTPUT-CONTRACTS.md",
    "mission-control-general/workflow-types/01-STAGE_GRAPH.md",
    "docs/specs/provider-consolidation-2026-10/sprint-oc/PROOFS.md",
]
_DIALECT = "https://json-schema.org/draft/2020-12/schema"


def _object(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "$schema": _DIALECT,
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": properties,
    }


def triage_verdict_schema() -> dict[str, Any]:
    return _object(
        {
            "severity": {"enum": ["high", "normal"]},
            "source_count": {"type": "integer", "minimum": 0, "maximum": 1000},
            "rationale": {"type": "string", "maxLength": 2000},
        },
        ["severity", "source_count"],
    )


def scan_flag_schema() -> dict[str, Any]:
    return _object(
        {"flagged": {"type": "boolean"}, "note": {"type": "string", "maxLength": 2000}},
        ["flagged"],
    )


def critique_verdict_schema() -> dict[str, Any]:
    return _object(
        {
            "approved": {"type": "boolean"},
            "score": {"type": "integer", "minimum": 0, "maximum": 100},
            "findings": {
                "type": "array",
                "maxItems": 32,
                "items": {"type": "string", "minLength": 1, "maxLength": 1000},
            },
        },
        ["approved", "score"],
    )


def definitions() -> list[Any]:
    from mission_control.domain.authoring.contracts import ArtifactSchemaDefinition

    note = "facts are read by the host from accepted validated bytes; validity is not acceptance"
    return [
        ArtifactSchemaDefinition(
            logical_id="schema.w2-triage-verdict",
            title="W2 triage verdict",
            description=f"First-match route facts severity and source_count; {note}",
            json_schema=triage_verdict_schema(),
        ),
        ArtifactSchemaDefinition(
            logical_id="schema.w2-scan-flag",
            title="W2 scan flag",
            description=f"All-matching route fact flagged; {note}",
            json_schema=scan_flag_schema(),
        ),
        ArtifactSchemaDefinition(
            logical_id="schema.w2-critique-verdict",
            title="W2 critique verdict",
            description=f"Revisit Region stop fact approved and progress fact score; {note}",
            json_schema=critique_verdict_schema(),
        ),
    ]


def bundles(published_records: Any, seed_format: str, actor: str) -> dict[str, Any]:
    records = []
    for definition in definitions():
        records += published_records(
            definition, "artifact-schema", EVIDENCE_SOURCES, published_at=SEED_TIME, revision=1
        )
    for record in records:
        if record["kind"] == "asset_decision":
            record["fields"]["decided_at"] = DECIDED_AT
    return {
        f"common/{SEED_KEY}-{SEED_VERSION}.json": {
            "format": seed_format,
            "seed_key": SEED_KEY,
            "seed_version": SEED_VERSION,
            "component_compatibility": ">=1.4.1 <2.0.0",
            "depends_on": [{"seed_key": SEED_KEY, "seed_version": PREVIOUS_VERSION}],
            "actor_ref": actor,
            "description": (
                "Successor of mc.catalog.artifact-schemas@1.0.0 (applied bytes untouched): the "
                "Sprint OC W2 graph-variant schemas schema.w2-triage-verdict@1, "
                "schema.w2-scan-flag@1 and schema.w2-critique-verdict@1 (WI-08 route and "
                "Revisit Region facts); schema validity is not acceptance."
            ),
            "records": records,
        }
    }
