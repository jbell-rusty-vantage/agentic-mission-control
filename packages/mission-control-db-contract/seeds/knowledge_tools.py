"""Sprint V SV-16: the six knowledge tools as catalog ``tool`` capability rows (ADR-0020/0023).

Imported by ``generate_catalog_seeds.py``. Each row is a published ``CapabilityDefinition``
(kind ``tool``, capability kind ``tool``, revision 1) naming one lane-neutral knowledge tool
of ``mission_control.application.knowledge.toolset``; a mission manifest names it as
``{search: ..., kind: tool, as: ...}`` or by exact pin, and the deployment's
``mc.manifest_launch_bindings`` capability binding maps the row's digest to the exact Deep
Agents tool component the worker registers (``knowledge_launch_bindings``). The rows carry no
secret, endpoint or credential: the binding, issuer and audience are deployment settings.
Common bundle: both applications reach their own knowledge binding through the same tools.

Versions: 1.0.0 is generated from :data:`TOOLS`; 1.1.0 (``submit_output`` revision 2, OVE-170)
is its recorded bytes; 1.2.0 (OVE-204 slice 4) is 1.1.0's records plus the
``knowledge_read_intent`` row (:data:`READ_INTENT_TOOL`), depending on 1.1.0.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SEED_KEY = "mc.catalog.knowledge-tools"
BASE_VERSION = "1.0.0"
RECORDED_VERSION = "1.1.0"
SEED_VERSION = "1.2.0"
SEED_TIME = datetime(2026, 10, 25, tzinfo=UTC)
READ_INTENT_TIME = datetime(2026, 10, 31, tzinfo=UTC)
COMMON = Path(__file__).resolve().parent / "common"
KEY_PREFIX = "knowledge-tool"
EVIDENCE = [
    "src/mission_control/application/knowledge/toolset.py",
    "src/mission_control/adapters/deep_agents/knowledge_tools.py",
    "docs/specs/provider-consolidation-2026-10/SPRINT-V-DESIGN.md#8-agent-surface-reports-and-observability",
]
TOOLS: tuple[tuple[str, str, str], ...] = (
    (
        "knowledge_read",
        "Exact knowledge read",
        "Resolve one exact report revision (handle and digest) through the application "
        "knowledge binding; returns an operation handle and the exact package reference.",
    ),
    (
        "knowledge_apply",
        "Governed knowledge apply",
        "Apply one host-recorded use decision exactly once through the application binding: "
        "the agent names the decision handle, the host supplies the exact use; journaled "
        "before dispatch and settled by its receipt or its reported delivery.",
    ),
    (
        "report_register",
        "Research report registration",
        "Register a research report draft with the application knowledge service; returns "
        "the receipt and the exact report handle.",
    ),
    (
        "report_derive",
        "Report derivation",
        "Derive exact domain proposals from a registered report revision (asynchronous handle).",
    ),
    (
        "verify_claims",
        "Claim verification",
        "Verify claims against evidence through the knowledge service (asynchronous handle "
        "with progress and findings).",
    ),
    (
        "submit_output",
        "Output submission",
        "Submit the exact handles or paths that fulfil one output obligation; a selected "
        "report is assessed independently under the host.",
    ),
)


# OVE-204 slice 4: the recorded discovery read, published in 1.2.0.
READ_INTENT_TOOL: tuple[str, str, str] = (
    "knowledge_read_intent",
    "Recorded knowledge read",
    "Read the application knowledge store for discovery through the knowledge gateway: "
    "allowlisted named queries, schema search and schema pages from one consistent snapshot, "
    "each with its content digest; every read is recorded as a retained read observation and "
    "is never a use decision or verified evidence.",
)
READ_INTENT_EVIDENCE = [
    *EVIDENCE,
    "src/mission_control/application/knowledge/read_intent.py",
    "tests/unit/knowledge/test_read_intent.py",
]


def logical_id(tool_name: str) -> str:
    """``knowledge_read`` -> ``tool.knowledge-read``; ``report_register`` ->
    ``tool.knowledge-report-register`` (the catalog capability id a manifest pins)."""

    return "tool.knowledge-" + tool_name.removeprefix("knowledge_").replace("_", "-")


def definitions(tools: tuple[tuple[str, str, str], ...] = TOOLS) -> list[Any]:
    from mission_control.domain.authoring.contracts import (
        CapabilityDefinition,
        CapabilityKind,
        DefinitionKind,
    )

    return [
        CapabilityDefinition(
            kind=DefinitionKind.TOOL,
            logical_id=logical_id(name),
            title=title,
            description=description,
            capability_kind=CapabilityKind.TOOL,
            maturity="experimental",
            attachment_targets=frozenset({"agent"}),
        )
        for name, title, description in tools
    ]


def _recorded(version: str) -> dict[str, Any]:
    """A published version's recorded bytes (never regenerated from moved sources)."""

    path = COMMON / f"{SEED_KEY}-{version}.json"
    return dict(json.loads(path.read_text(encoding="utf-8")))


def bundles(published: Any, seed_format: str, compatibility: str, actor: str) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for definition in definitions():
        records.extend(published(definition, KEY_PREFIX, EVIDENCE))
    recorded = _recorded(RECORDED_VERSION)
    read_intent: list[dict[str, Any]] = []
    for definition in definitions((READ_INTENT_TOOL,)):
        read_intent.extend(
            published(definition, KEY_PREFIX, READ_INTENT_EVIDENCE, READ_INTENT_TIME)
        )
    for record in read_intent:
        if record["kind"] == "asset_decision":
            record["fields"]["decided_at"] = "2026-10-31T00:00:00Z"
    return {
        f"common/{SEED_KEY}-{RECORDED_VERSION}.json": recorded,
        f"common/{SEED_KEY}-{SEED_VERSION}.json": {
            "format": seed_format,
            "seed_key": SEED_KEY,
            "seed_version": SEED_VERSION,
            "component_compatibility": compatibility,
            "depends_on": [{"seed_key": SEED_KEY, "seed_version": RECORDED_VERSION}],
            "actor_ref": actor,
            "description": (
                "Knowledge tools 1.1.0 plus knowledge_read_intent (OVE-204 slice 4), the "
                "recorded discovery read, as catalog tool capability rows; the deployment binds "
                "each row's digest to its exact Deep Agents tool component."
            ),
            "records": [*recorded["records"], *read_intent],
        },
        f"common/{SEED_KEY}-{BASE_VERSION}.json": {
            "format": seed_format,
            "seed_key": SEED_KEY,
            "seed_version": BASE_VERSION,
            "component_compatibility": compatibility,
            "depends_on": [],
            "actor_ref": actor,
            "description": (
                "Sprint V knowledge tools (knowledge_read, knowledge_apply, report_register, "
                "report_derive, verify_claims, submit_output) as catalog tool capability rows; "
                "the deployment binds each row's digest to its exact Deep Agents tool component."
            ),
            "records": records,
        },
    }
