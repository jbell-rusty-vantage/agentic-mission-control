"""Builders, constants and fakes that other test files import.

Moved from tests/integration/postgres/test_ai_engineer_report_schema_seed.py.
"""

from __future__ import annotations

from pathlib import Path

import asyncpg

from mission_control.domain.authoring.contracts import PublishedDefinition
from mission_control_db_contract.seeds import seed_apply, seed_plan
from tests.support.integration.postgres.run2_release_141 import VERSIONS

ROOT = Path(__file__).resolve().parents[4]
PACKAGE = ROOT / "packages/mission-control-db-contract"
SEEDS = PACKAGE / "seeds"
RELEASE_142 = PACKAGE / "releases/1.4.2/component"


S0_ID = "schema.s0-probe-report"


def ident(bundle: dict) -> tuple[str, str]:
    return bundle["seed_key"], bundle["seed_version"]


def published(bundle: dict) -> dict[str, PublishedDefinition]:
    result = {}
    for record in bundle["records"]:
        if record["kind"] == "asset_version":
            definition = PublishedDefinition.model_validate(record["fields"]["manifest"])
            result[definition.ref.logical_id] = definition
    return result


def confirm(target: dict) -> str:
    return f"{target['project_ref']}:{target['installation_id']}"


async def apply(target, release, bundles) -> dict[tuple[str, str], str]:
    result = await seed_apply(target, release, bundles, confirmation=confirm(target), **VERSIONS)
    return {(b["seed_key"], b["seed_version"]): b["outcome"] for b in result["bundles"]}


async def plan(target, release, bundles) -> dict[tuple[str, str], str]:
    result = await seed_plan(target, release, bundles, **VERSIONS)
    return {(b["seed_key"], b["seed_version"]): b["status"] for b in result["bundles"]}


async def receipts(connection) -> dict[tuple[str, str], tuple]:
    rows = await connection.fetch(
        "SELECT seed_key,seed_version,seed_digest,component_version,record_counts::text AS counts,"
        "applied_at,applied_by FROM mission_control.installation_seed_receipt"
    )
    return {(row["seed_key"], row["seed_version"]): tuple(row.values())[2:] for row in rows}


async def catalog_counts(connection) -> dict[str, int]:
    tables = ("asset_version", "asset_decision", "seed_identity", "installation_seed_receipt")
    return {
        table: await connection.fetchval(f"SELECT count(*) FROM mission_control.{table}")
        for table in tables
    }


async def s0_row(connection) -> asyncpg.Record:
    return await connection.fetchrow(
        "SELECT asset_version_id,manifest_digest,manifest::text AS manifest,status,version_no,"
        "updated_at FROM mission_control.asset_version WHERE asset_id=$1",
        f"definition:artifact_schema:{S0_ID}",
    )
