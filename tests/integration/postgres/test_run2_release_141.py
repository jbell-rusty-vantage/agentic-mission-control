"""Real installer proof for the canonical 1.4.1 successor on fresh mct_* databases."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import asyncpg
import pytest

from mission_control.application.execution.harness.describe import declared_matrix
from mission_control_db_contract.deployment import apply_release, plan_release, verify_release
from mission_control_db_contract.errors import ContractError
from mission_control_db_contract.integrity import load_release
from mission_control_db_contract.release import write_lock
from mission_control_db_contract.seeds import load_bundles, seed_apply, seed_plan
from tests.fixtures.mission_control_common_db import admin_dsn
from tests.qualification.two_project.release_install import write_target

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "packages/mission-control-db-contract"
SUCCESSOR = PACKAGE / "releases/1.4.1/component"
VERSIONS = {
    "reader_version": "mission-control-runtime/1",
    "writer_version": "mission-control-runtime/1",
}
CONTRACTS = (
    "goal.revision/1",
    "goal.iteration/1",
    "goal.handoff/1",
    "goal.verification/1",
    "goal.template/1",
    "stagegraph.template/1",
    "operation.binding/1",
    "operation.binding-index/1",
    "operation.settlement/1",
    "operation.claim/1",
    "mc.cursor-cost-observation/1",
)
pytestmark = [pytest.mark.asyncio, pytest.mark.common_db]


def release_at(component, temporary, app="biotech"):
    lock = write_lock(component, temporary, app)
    return load_release(Path(lock["lock_path"]), component)


def retained_release_130(destination):
    """Restore exact applied bytes, not a newly built prefix carrying the same version."""
    commit = "a3a784411d09074baf1d2c3f34d6640f320e155f"

    def retained(path):
        return subprocess.run(
            ["git", "show", f"{commit}:{path}"], cwd=ROOT, capture_output=True, check=True
        ).stdout

    lock = json.loads(retained("deployments/ai-engineer/release.lock.json"))
    assert lock["component_version"] == "1.3.0"
    assert lock["files"]["manifest.json"] == (
        "5bdb7563eb6b6b7182bad9bbbc99ea0d66c36cf638d2d5320f04f58610e08810"
    )
    component = destination / "component"
    for name, digest in lock["files"].items():
        payload = retained(f"packages/mission-control-db-contract/component/{name}")
        assert hashlib.sha256(payload).hexdigest() == digest
        output = component / name
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(payload)
    descriptor = retained("packages/mission-control-db-contract/runtime/descriptor.json")
    manifest = json.loads((component / "manifest.json").read_bytes())
    assert hashlib.sha256(descriptor).hexdigest() == manifest["runtime_descriptor"]["sha256"]
    (destination / "runtime").mkdir()
    (destination / "runtime/descriptor.json").write_bytes(descriptor)
    return component


@asynccontextmanager
async def disposable(tmp_path, app="biotech") -> AsyncIterator[tuple]:
    server = admin_dsn()
    name = "mct_" + secrets.token_hex(5)
    env_name = "MCDB_SUCCESSOR_" + secrets.token_hex(5).upper()
    admin = await asyncpg.connect(server)
    connection = None
    try:
        await admin.execute(f'CREATE DATABASE "{name}"')
        connection = await asyncpg.connect(urlunsplit(urlsplit(server)._replace(path="/" + name)))
        await connection.execute(
            "CREATE SCHEMA extensions; CREATE EXTENSION vector SCHEMA extensions; "
            "CREATE EXTENSION pg_trgm SCHEMA extensions"
        )
        target = write_target(
            tmp_path,
            app=app,
            database=name,
            server_dsn=server,
            installation_id=str(uuid4()),
            project_ref="disposable-" + name.replace("_", "-"),
            env_name=env_name,
        )
        yield target, connection
    finally:
        if connection is not None:
            await connection.close()
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.close()
        os.environ.pop(env_name, None)


async def install(target, release):
    plan = await plan_release(target, release, **VERSIONS)
    assert plan["plan"]["holds"] == []
    return await apply_release(
        target,
        release,
        confirmation=f"{target['project_ref']}:{target['installation_id']}",
        expected_plan_digest=plan["plan_digest"],
        **VERSIONS,
    )


async def context(connection, target, tenant):
    await connection.execute(
        "SELECT set_config('mc.installation_id',$1,true), "
        "set_config('mc.application_id',$2,true), set_config('mc.tenant_id',$3,true)",
        target["installation_id"],
        target["application_id"],
        str(tenant),
    )


async def insert_document(connection, target, tenant, contract, identity):
    await connection.execute(
        "INSERT INTO mission_control.runtime_document "
        "(installation_id,application_id,tenant_id,runtime_document_id,contract,identity,"
        "payload,digest,recorded_at,created_at,created_by_actor_ref) "
        "VALUES ($1::uuid,$2,$3,$4,$5,$6,'{}',$7,now(),now(),'fixture:successor')",
        target["installation_id"],
        target["application_id"],
        tenant,
        uuid4(),
        contract,
        identity,
        "sha256:" + "a" * 64,
    )


async def assert_runtime_security(connection, target):
    tenant = uuid4()
    await connection.execute(
        "INSERT INTO mission_control.tenant "
        "(installation_id,application_id,tenant_id,external_tenant_ref,state,"
        "qualification_fixture,created_at,created_by_actor_ref) "
        "VALUES ($1::uuid,$2,$3,'release-test','active',true,now(),'fixture:successor')",
        target["installation_id"],
        target["application_id"],
        tenant,
    )
    async with connection.transaction():
        await connection.execute("SET LOCAL ROLE mission_control_runtime")
        assert not await connection.fetchval(
            "SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user"
        )
        assert (
            await connection.fetchval("SELECT count(*) FROM mission_control.runtime_document") == 0
        )
        await context(connection, target, tenant)
        for contract in CONTRACTS:
            await insert_document(connection, target, tenant, contract, contract)
        assert (
            await connection.fetchval("SELECT count(*) FROM mission_control.runtime_document") == 11
        )
        for contract, identity, error in (
            ("unreviewed/1", "bad", asyncpg.CheckViolationError),
            (CONTRACTS[-1], CONTRACTS[-1], asyncpg.UniqueViolationError),
        ):
            with pytest.raises(error):
                async with connection.transaction():
                    await insert_document(connection, target, tenant, contract, identity)
        await context(connection, target, uuid4())
        assert (
            await connection.fetchval("SELECT count(*) FROM mission_control.runtime_document") == 0
        )
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            async with connection.transaction():
                await insert_document(connection, target, tenant, CONTRACTS[-1], "cross-tenant")
    # Owner mutations still meet the immutable guard; runtime has no mutation grants.
    for table in ("runtime_document", "lane_profile"):
        assert await connection.fetchval(
            "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE oid=$1::regclass",
            "mission_control." + table,
        )
        assert (
            await connection.fetchval(
                "SELECT tgenabled FROM pg_trigger WHERE tgrelid=$1::regclass AND tgname=$2",
                "mission_control." + table,
                table + "_immutable",
            )
            == b"O"
        )
        with pytest.raises(asyncpg.RestrictViolationError):
            async with connection.transaction():
                await connection.execute(f"DELETE FROM mission_control.{table}")


@pytest.mark.parametrize(
    "upgrade", [None, "1.4.0", "1.3.0"], ids=["fresh", "upgrade-from-140", "upgrade-from-130"]
)
async def test_successor_install_upgrade_seed_replay_and_security(tmp_path, upgrade):
    app = "ai-engineer" if upgrade == "1.3.0" else "biotech"
    successor = release_at(SUCCESSOR, tmp_path / "successor-lock", app)
    previous_component = (
        retained_release_130(tmp_path / "retained-130")
        if upgrade == "1.3.0"
        else PACKAGE / "component"
    )
    previous = release_at(previous_component, tmp_path / "previous-lock", app)
    bundles = load_bundles([PACKAGE / "seeds/common/mc.catalog.artifact-schemas-1.0.0.json"])
    async with disposable(tmp_path, app) as (target, connection):
        if upgrade:
            await install(target, previous)
            assert (await verify_release(target, previous, **VERSIONS))["status"] == "verified"
            rejected = await seed_plan(target, previous, bundles, **VERSIONS)
            assert rejected["status"] == "hold"
            assert rejected["bundles"][0]["status"] == "incompatible"
            before_receipts = await connection.fetch(
                "SELECT migration_key,migration_digest,component_version "
                "FROM mission_control.component_release ORDER BY migration_key"
            )
        result = await install(target, successor)
        assert result["component_version"] == "1.4.1"
        assert (await verify_release(target, successor, **VERSIONS))["status"] == "verified"
        if upgrade:
            expected = [
                "0042_codex_01621_lane_describe",
                "0043_cursor_cost_observation_contract",
            ]
            if upgrade == "1.3.0":
                expected = [
                    "0035_signal_ingress",
                    "0036_hosted_agent_api_lane_profiles",
                    "0037_environment_preparation",
                    "0038_owner_prerequisites",
                    "0040_implemented_lane_describes",
                    "0041_placement_capacity",
                    *expected,
                ]
            assert result["applied_migrations"] == expected
            for row in before_receipts:
                assert (
                    await connection.fetchrow(
                        "SELECT migration_key,migration_digest,component_version "
                        "FROM mission_control.component_release WHERE migration_key=$1",
                        row["migration_key"],
                    )
                    == row
                )
        assert (await install(target, successor))["applied_migrations"] == []
        row = await connection.fetchrow(
            "SELECT describe,qualified,qualification_ref,qualified_at "
            "FROM mission_control.lane_profile WHERE lane_profile='codex'"
        )
        assert json.loads(row["describe"]) == declared_matrix("codex").model_dump(mode="json")
        assert (
            row["qualified"] is False
            and row["qualification_ref"] is None
            and row["qualified_at"] is None
        )
        assert (
            "mc.catalog.artifact-schemas" in successor.manifest["seed_compatibility"]["seed_keys"]
        )
        for expected in ("applied", "replay"):
            seeded = await seed_apply(
                target,
                successor,
                bundles,
                confirmation=f"{target['project_ref']}:{target['installation_id']}",
                **VERSIONS,
            )
            assert seeded["bundles"][0]["outcome"] == expected
        await assert_runtime_security(connection, target)
        assert (await verify_release(target, successor, **VERSIONS))["status"] == "verified"


@pytest.mark.parametrize("drift", ["describe", "constraint"])
async def test_successor_refuses_drift_without_partial_upgrade(tmp_path, drift):
    successor = release_at(SUCCESSOR, tmp_path / "successor-lock")
    previous = release_at(PACKAGE / "component", tmp_path / "previous-lock")
    async with disposable(tmp_path) as (target, connection):
        await install(target, previous)
        if drift == "describe":
            await connection.execute(
                "ALTER TABLE mission_control.lane_profile DISABLE TRIGGER lane_profile_immutable; "
                "UPDATE mission_control.lane_profile "
                "SET describe=jsonb_set(describe,'{versions,codex_cli}','\"unreviewed\"') "
                "WHERE lane_profile='codex'; "
                "ALTER TABLE mission_control.lane_profile ENABLE TRIGGER lane_profile_immutable"
            )
        else:
            await connection.execute(
                "ALTER TABLE mission_control.runtime_document "
                "DROP CONSTRAINT runtime_document_contract_check"
            )
        plan = await plan_release(target, successor, **VERSIONS)
        if drift == "constraint":
            assert plan["plan"]["holds"]
        with pytest.raises(ContractError):
            await apply_release(
                target,
                successor,
                confirmation=f"{target['project_ref']}:{target['installation_id']}",
                expected_plan_digest=plan["plan_digest"],
                **VERSIONS,
            )
        assert (
            await connection.fetchval(
                "SELECT schema_component_version FROM mission_control.application_installation"
            )
            == "1.4.0"
        )
        assert (
            await connection.fetchval(
                "SELECT count(*) FROM mission_control.component_release "
                "WHERE migration_key LIKE '0042%' OR migration_key LIKE '0043%'"
            )
            == 0
        )
        assert await connection.fetchval(
            "SELECT relforcerowsecurity FROM pg_class "
            "WHERE oid='mission_control.lane_profile'::regclass"
        )
        assert (
            await connection.fetchval(
                "SELECT tgenabled FROM pg_trigger WHERE tgname='lane_profile_immutable'"
            )
            == b"O"
        )
