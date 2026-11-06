"""D5: the additive AI Engineer SDLC report-schema seed on real disposable installs.

Fresh 1.4.2 and live-history (1.3.0 receipts, then 1.4.2) installations accept
``mc.app.ai-engineer.artifact-schemas@1.0.0`` as a pure addition through the real
``mission-db`` seed engine; replay is idempotent, drift and an incompatible component are
refused with nothing written, the migration principal writes and the runtime role only reads.
"""

from __future__ import annotations

import copy
import json
import secrets
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import asyncpg
import pytest
from jsonschema import Draft202012Validator

from mission_control.adapters.postgres.control_plane.definition_repository import (
    PostgresDefinitionRepository,
)
from mission_control.adapters.postgres.scope import apply_catalog_scope_string
from mission_control.domain.authoring.contracts import ArtifactSchemaDefinition, PublishedDefinition
from mission_control_db_contract.errors import ContractError
from mission_control_db_contract.seeds import load_bundles, seed_apply, seed_plan, validate_bundle
from tests.fixtures.mission_control_common_db import admin_dsn

# The established synthetic Supabase-shaped Storage stand-in (FT-A2); it is not Supabase.
from tests.integration.postgres.test_capability_bundles_publish import SYNTHETIC_STORAGE
from tests.integration.postgres.test_run2_release_141 import (
    VERSIONS,
    disposable,
    install,
    release_at,
    retained_release_130,
)
from tests.qualification.two_project.release_install import write_target

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "packages/mission-control-db-contract"
SEEDS = PACKAGE / "seeds"
RELEASE_142 = PACKAGE / "releases/1.4.2/component"
NEW_KEY = ("mc.app.ai-engineer.artifact-schemas", "1.0.0")
NEW_PATH = SEEDS / "ai-engineer/mc.app.ai-engineer.artifact-schemas-1.0.0.json"
S0_ID = "schema.s0-probe-report"
SDLC_IDS = (
    "schema.sdlc-diagnosis-report",
    "schema.sdlc-patch-report",
    "schema.sdlc-review-report",
)
LIVE_130_RECEIPTS = (
    ROOT / "docs/qualification/two-project/supabase-blue-ocean/20261012-live-130/seed-receipts.json"
)
pytestmark = pytest.mark.common_db


def ident(bundle: dict) -> tuple[str, str]:
    return bundle["seed_key"], bundle["seed_version"]


def seed_sets() -> tuple[list[dict], dict]:
    everything = load_bundles([SEEDS / "common", SEEDS / "ai-engineer"])
    (new,) = [bundle for bundle in everything if ident(bundle) == NEW_KEY]
    return [bundle for bundle in everything if ident(bundle) != NEW_KEY], new


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


async def runtime_login(connection, target) -> tuple[str, str]:
    login, password = "mct_" + secrets.token_hex(5) + "_d5rt", secrets.token_hex(16)
    await connection.execute(
        f'CREATE ROLE "{login}" LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE '
        f"INHERIT PASSWORD '{password}' IN ROLE mission_control_runtime"
    )
    await connection.execute(f'GRANT CONNECT ON DATABASE "{target["database_name"]}" TO "{login}"')
    parsed = urlsplit(admin_dsn())
    netloc = f"{quote(login, safe='')}:{quote(password, safe='')}@127.0.0.1:{parsed.port or 5432}"
    dsn = urlunsplit(parsed._replace(netloc=netloc, path="/" + target["database_name"], query=""))
    return login, dsn


def assert_sample_reports_validate(definitions: dict[str, PublishedDefinition]) -> None:
    run = {"command": "pytest -q", "disposition": "observed", "exit_code": 0}
    run |= {"passed": 4, "failed": 0}
    unrun = {"command": "pytest -q", "disposition": "unrun", "exit_code": None}
    unrun |= {"passed": None, "failed": None}
    samples = {
        SDLC_IDS[0]: {
            "schema_version": "mc.sdlc_diagnosis_report.v1",
            "subject": {"issue": "config:<key> unresolved", "source_ref": "c49862bf"},
            "reproduction": {"disposition": "unrun", "commands": [], "evidence_refs": []},
            "root_cause": {"disposition": "unknown", "summary": ""},
            "affected_files": [],
            "evidence_refs": [],
            "disposition": "unknown",
        },
        SDLC_IDS[1]: {
            "schema_version": "mc.sdlc_patch_report.v1",
            "base_commit": "af2d24fc",
            "head_or_diff_sha256": "sha256:" + "a" * 64,
            "changed_files": ["src/mission_control/bootstrap/manifests.py"],
            "summary": "installation configuration source",
            "tests": [run, unrun],
            "risks": [],
            "evidence_refs": ["runner-tests.json"],
        },
        SDLC_IDS[2]: {
            "schema_version": "mc.sdlc_review_report.v1",
            "reviewed_diff_sha256": "sha256:" + "a" * 64,
            "reviewer_role": "subagent.mc-cognition-reviewer",
            "verdict": "approve",
            "findings": [],
            "tests_rerun": [run],
            "evidence_refs": [],
        },
    }
    for logical_id, sample in samples.items():
        definition = definitions[logical_id].definition
        assert isinstance(definition, ArtifactSchemaDefinition)
        validator = Draft202012Validator(definition.json_schema)
        assert validator.is_valid(sample), logical_id
        assert not validator.is_valid({**sample, "unexpected": True}), logical_id
    review = Draft202012Validator(definitions[SDLC_IDS[2]].definition.json_schema)
    assert not review.is_valid({**samples[SDLC_IDS[2]], "verdict": "changes_required"})
    patch = Draft202012Validator(definitions[SDLC_IDS[1]].definition.json_schema)
    assert not patch.is_valid({**samples[SDLC_IDS[1]], "tests": [{**run, "exit_code": None}]})


@pytest.mark.asyncio
async def test_fresh_install_replay_drift_and_runtime_role(tmp_path):
    release = release_at(RELEASE_142, tmp_path / "lock-142", "ai-engineer")
    prior, new = seed_sets()
    committed = published(new)
    (s0,) = published(
        validate_bundle(
            json.loads((SEEDS / "common/mc.catalog.artifact-schemas-1.0.0.json").read_bytes())
        )
    ).values()
    async with disposable(tmp_path, "ai-engineer") as (target, connection):
        assert (await install(target, release))["component_version"] == "1.4.2"
        # cognition-profiles depends on the Storage bucket seed, as on the live target.
        await connection.execute(SYNTHETIC_STORAGE)
        prior_outcomes = await apply(target, release, prior)
        assert set(prior_outcomes) == {ident(b) for b in prior}
        assert set(prior_outcomes.values()) == {"applied"}
        before_receipts, before_counts = (
            await receipts(connection),
            await catalog_counts(connection),
        )
        before_s0 = await s0_row(connection)

        # (a) pending before, applied once by the admin principal, replay after.
        planned = await plan(target, release, [*prior, new])
        assert planned.pop(NEW_KEY) == "pending"
        assert set(planned.values()) == {"replay"}
        assert (await apply(target, release, [new]))[NEW_KEY] == "applied"
        assert (await plan(target, release, [new]))[NEW_KEY] == "replay"
        after_receipts = await receipts(connection)
        new_receipt = after_receipts.pop(NEW_KEY)
        assert after_receipts == before_receipts
        assert new_receipt[0] == new["seed_digest"] and new_receipt[1] == "1.4.2"
        assert new_receipt[-1] == target["database_user"] == urlsplit(admin_dsn()).username
        delta = {k: v - before_counts[k] for k, v in (await catalog_counts(connection)).items()}
        assert delta == {
            "asset_version": 3,
            "asset_decision": 3,
            "seed_identity": 6,
            "installation_seed_receipt": 1,
        }
        assert await s0_row(connection) == before_s0

        # (c) repeat: idempotent replay, identical receipt, no rows.
        settled = await catalog_counts(connection)
        assert (await apply(target, release, [new]))[NEW_KEY] == "replay"
        assert (await receipts(connection))[NEW_KEY] == new_receipt
        assert await catalog_counts(connection) == settled

        # (d) drift: changed bytes under the same seed version conflict; nothing written.
        drifted = copy.deepcopy({k: v for k, v in new.items() if k != "seed_digest"})
        manifest = drifted["records"][0]["fields"]["manifest"]
        manifest["definition"]["description"] += " (edited)"
        drifted = validate_bundle(drifted)
        assert drifted["seed_digest"] != new["seed_digest"]
        assert (await plan(target, release, [drifted]))[NEW_KEY] == "conflict"
        with pytest.raises(ContractError, match="different digest"):
            await apply(target, release, [drifted])
        assert await catalog_counts(connection) == settled
        assert (await receipts(connection))[NEW_KEY] == new_receipt

        # (a, f) the runtime role reads the published definitions but cannot write them.
        login, runtime_dsn = await runtime_login(connection, target)
        pool = await asyncpg.create_pool(dsn=runtime_dsn, min_size=1, max_size=2)
        try:
            scope = f"mc/{target['installation_id']}/ai-engineer/catalog"
            repository = PostgresDefinitionRepository(pool, catalog_scope=scope)
            refs = {
                ref.logical_id: ref for ref in await repository.list_published_definition_refs()
            }
            assert {S0_ID, *SDLC_IDS} <= set(refs)
            for logical_id in SDLC_IDS:
                read = await repository.get(committed[logical_id].ref)
                assert read.ref == committed[logical_id].ref == refs[logical_id]
                assert read.definition == committed[logical_id].definition
                assert read.retired_at is None
            assert (await repository.get(s0.ref)).definition == s0.definition
            assert_sample_reports_validate(committed)
            asset_id = f"definition:artifact_schema:{SDLC_IDS[0]}"
            async with pool.acquire() as runtime:
                assert not await runtime.fetchval(
                    "SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user"
                )
                # Seed receipts/identities are admin-only; seeded content is never rewritten.
                for statement in (
                    "SELECT count(*) FROM mission_control.installation_seed_receipt "
                    "WHERE seed_key=$1",
                    "SELECT count(*) FROM mission_control.seed_identity WHERE logical_key=$1",
                    "UPDATE mission_control.asset_version SET manifest_digest=$1 WHERE asset_id=$1",
                    "DELETE FROM mission_control.asset_version WHERE asset_id=$1",
                ):
                    with pytest.raises(asyncpg.InsufficientPrivilegeError):
                        await runtime.execute(statement, asset_id)
                with pytest.raises(asyncpg.RestrictViolationError):
                    async with runtime.transaction():
                        await apply_catalog_scope_string(runtime, scope)
                        await runtime.execute(
                            "UPDATE mission_control.asset_version SET status='proposed', "
                            "version_no=version_no+1, updated_at=now() WHERE asset_id=$1",
                            asset_id,
                        )
            # seed-apply under the runtime principal is refused before any write.
            runtime_target = write_target(
                tmp_path / "runtime-target",
                app="ai-engineer",
                database=target["database_name"],
                server_dsn=runtime_dsn,
                installation_id=target["installation_id"],
                project_ref=target["project_ref"],
                env_name="MCDB_D5_RUNTIME_" + secrets.token_hex(4).upper(),
            )
            assert runtime_target["database_user"] == login
            fresh = copy.deepcopy({k: v for k, v in new.items() if k != "seed_digest"})
            fresh["seed_version"] = "1.0.1"
            # Refused for lack of privilege (SQLSTATE 42501), not for any other reason.
            with pytest.raises(ContractError, match=r"SQLSTATE 42501"):
                await apply(runtime_target, release, [validate_bundle(fresh)])
            assert await catalog_counts(connection) == settled
        finally:
            await pool.close()
            await connection.execute(
                f'REVOKE CONNECT ON DATABASE "{target["database_name"]}" FROM "{login}"'
            )
            await connection.execute(f'DROP ROLE "{login}"')


@pytest.mark.asyncio
async def test_live_history_upgrade_adds_purely_and_older_component_refuses(tmp_path):
    release_130 = release_at(
        retained_release_130(tmp_path / "retained-130"), tmp_path / "l130", "ai-engineer"
    )
    release = release_at(RELEASE_142, tmp_path / "lock-142", "ai-engineer")
    prior, new = seed_sets()
    live = {
        (b["seed_key"], b["seed_version"])
        for b in json.loads(LIVE_130_RECEIPTS.read_bytes())["bundles"]
    }
    async with disposable(tmp_path, "ai-engineer") as (target, connection):
        # Live history: 1.3.0 with its eleven recorded seed receipts.
        assert (await install(target, release_130))["component_version"] == "1.3.0"
        outcomes = await apply(target, release_130, [b for b in prior if ident(b) in live])
        assert set(outcomes) == live and set(outcomes.values()) == {"applied"}

        # (e) an incompatible (1.3.0) installation refuses the bundle; nothing written.
        before = await catalog_counts(connection)
        result = await seed_plan(target, release_130, [new], **VERSIONS)
        assert result["status"] == "hold" and result["bundles"][0]["status"] == "incompatible"
        with pytest.raises(ContractError, match="incompatible"):
            await apply(target, release_130, [new])
        assert await catalog_counts(connection) == before

        # (b) upgrade to 1.4.2, complete the prior set, then the new bundle is pure addition.
        assert (await install(target, release))["component_version"] == "1.4.2"
        await connection.execute(SYNTHETIC_STORAGE)
        completed = await apply(target, release, prior)
        assert {k for k, v in completed.items() if v == "replay"} == live
        before_receipts, before_counts = (
            await receipts(connection),
            await catalog_counts(connection),
        )
        planned = await plan(target, release, [*prior, new])
        assert planned.pop(NEW_KEY) == "pending"
        assert set(planned.values()) == {"replay"}
        outcomes = await apply(target, release, [*prior, new])
        assert outcomes.pop(NEW_KEY) == "applied"
        assert set(outcomes.values()) == {"replay"}
        after = await receipts(connection)
        assert after.pop(NEW_KEY)[0] == new["seed_digest"]
        assert after == before_receipts
        delta = {k: v - before_counts[k] for k, v in (await catalog_counts(connection)).items()}
        assert delta == {
            "asset_version": 3,
            "asset_decision": 3,
            "seed_identity": 6,
            "installation_seed_receipt": 1,
        }


def test_bundle_is_ai_engineer_scoped_and_absent_from_biotech_selection():
    # Seed selection is by directory (Makefile SEED_BUNDLES = common + <app>).
    assert sorted(path.relative_to(SEEDS).as_posix() for path in SEEDS.rglob(NEW_PATH.name)) == [
        "ai-engineer/" + NEW_PATH.name
    ]
    biotech = load_bundles([SEEDS / "common", SEEDS / "biotech"])
    assert NEW_KEY not in {ident(bundle) for bundle in biotech}
    assert not {
        record["logical_key"]
        for bundle in biotech
        for record in bundle["records"]
        if any(logical_id in record["logical_key"] for logical_id in SDLC_IDS)
    }
