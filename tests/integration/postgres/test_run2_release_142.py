"""Actual 1.4.2 installer proof; prior releases and their proof remain immutable."""

from __future__ import annotations

from uuid import uuid4

import pytest

from mission_control_db_contract.deployment import apply_release, plan_release, verify_release
from mission_control_db_contract.errors import ContractError
from tests.integration.postgres.test_run2_release_141 import (
    PACKAGE,
    VERSIONS,
    assert_runtime_security,
    disposable,
    insert_document,
    install,
    release_at,
    retained_release_130,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.common_db]
SUCCESSOR = PACKAGE / "releases/1.4.2/component"
SIGNATURE = "mission_control.ingress_mission_request(uuid,text,text,uuid,text,text,text,jsonb)"
MIGRATION = "0044_ingress_mission_request_idempotency"


async def function_metadata(connection):
    return await connection.fetchrow(
        "SELECT oid,proowner,proacl,prosecdef,proconfig FROM pg_proc WHERE oid=$1::regprocedure",
        SIGNATURE,
    )


async def preserve_document(connection, target):
    tenant = uuid4()
    await connection.execute(
        "INSERT INTO mission_control.tenant "
        "(installation_id,application_id,tenant_id,external_tenant_ref,state,"
        "qualification_fixture,created_at,created_by_actor_ref) "
        "VALUES ($1::uuid,$2,$3,'release-142-preserved','active',true,now(),'fixture:successor')",
        target["installation_id"],
        target["application_id"],
        tenant,
    )
    await insert_document(connection, target, tenant, "operation.binding/1", "before-upgrade")
    row = await connection.fetchrow(
        "SELECT * FROM mission_control.runtime_document WHERE tenant_id=$1", tenant
    )
    assert row is not None
    return tenant, row


async def preserve_inbox_receipt(connection, target, tenant):
    """Installer preservation fixture; restricted request semantics have separate PG proof."""
    ingress_id = uuid4()
    await connection.execute(
        "INSERT INTO mission_control.ingress_inbox "
        "(installation_id,application_id,tenant_id,ingress_id,received_at,trust_tier,kind,"
        "credential_ref,dedupe_key,body_sha256,payload,state,attempts) "
        "VALUES ($1::uuid,$2,$3,$4,now(),'launch_token','mission_request',"
        "'fixture:preserved','preserved-key',$5,'{\"manifest_ref\":\"fixture:manifest\"}',"
        "'pending',0)",
        target["installation_id"],
        target["application_id"],
        tenant,
        ingress_id,
        "sha256:" + "b" * 64,
    )
    return await connection.fetchrow(
        "SELECT * FROM mission_control.ingress_inbox WHERE ingress_id=$1", ingress_id
    )


@pytest.mark.parametrize(
    "upgrade", [None, "1.4.1", "1.3.0"], ids=["fresh", "upgrade-from-141", "upgrade-from-130"]
)
async def test_release_142_installs_and_preserves_history_security_and_data(tmp_path, upgrade):
    app = "ai-engineer" if upgrade == "1.3.0" else "biotech"
    successor = release_at(SUCCESSOR, tmp_path / "successor-lock", app)
    async with disposable(tmp_path, app) as (target, connection):
        before_receipts = []
        document = receipt = metadata = None
        if upgrade:
            component = (
                retained_release_130(tmp_path / "retained-130")
                if upgrade == "1.3.0"
                else PACKAGE / "releases/1.4.1/component"
            )
            previous = release_at(component, tmp_path / "previous-lock", app)
            await install(target, previous)
            assert (await verify_release(target, previous, **VERSIONS))["status"] == "verified"
            before_receipts = await connection.fetch(
                "SELECT * FROM mission_control.component_release ORDER BY migration_key"
            )
            tenant, document = await preserve_document(connection, target)
            if upgrade == "1.4.1":
                receipt = await preserve_inbox_receipt(connection, target, tenant)
                metadata = await function_metadata(connection)

        result = await install(target, successor)
        assert result["component_version"] == "1.4.2"
        if upgrade:
            expected = [MIGRATION]
            if upgrade == "1.3.0":
                expected = [
                    "0035_signal_ingress",
                    "0036_hosted_agent_api_lane_profiles",
                    "0037_environment_preparation",
                    "0038_owner_prerequisites",
                    "0040_implemented_lane_describes",
                    "0041_placement_capacity",
                    "0042_codex_01621_lane_describe",
                    "0043_cursor_cost_observation_contract",
                    MIGRATION,
                ]
            assert result["applied_migrations"] == expected
        else:
            assert result["applied_migrations"][-1] == MIGRATION
        for row in before_receipts:
            assert (
                await connection.fetchrow(
                    "SELECT * FROM mission_control.component_release WHERE migration_key=$1",
                    row["migration_key"],
                )
                == row
            )
        if document is not None:
            assert (
                await connection.fetchrow(
                    "SELECT * FROM mission_control.runtime_document WHERE runtime_document_id=$1",
                    document["runtime_document_id"],
                )
                == document
            )
        if receipt is not None:
            assert (
                await connection.fetchrow(
                    "SELECT * FROM mission_control.ingress_inbox WHERE ingress_id=$1",
                    receipt["ingress_id"],
                )
                == receipt
            )
        installed_metadata = await function_metadata(connection)
        if metadata is not None:
            assert installed_metadata == metadata
        assert installed_metadata["prosecdef"]
        assert installed_metadata["proconfig"] == ["search_path=pg_catalog"]
        assert await connection.fetchval(
            "SELECT has_function_privilege('mission_control_ingress',$1,'EXECUTE')", SIGNATURE
        )
        assert not await connection.fetchval(
            "SELECT EXISTS (SELECT FROM pg_proc p, "
            "LATERAL aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a "
            "WHERE p.oid=$1::regprocedure AND a.grantee=0 AND a.privilege_type='EXECUTE')",
            SIGNATURE,
        )
        assert (await verify_release(target, successor, **VERSIONS))["status"] == "verified"
        assert (await install(target, successor))["applied_migrations"] == []
        await assert_runtime_security(connection, target)
        assert (await verify_release(target, successor, **VERSIONS))["status"] == "verified"


async def test_release_142_refuses_function_security_drift_without_partial_upgrade(tmp_path):
    successor = release_at(SUCCESSOR, tmp_path / "successor-lock")
    previous = release_at(PACKAGE / "releases/1.4.1/component", tmp_path / "previous-lock")
    async with disposable(tmp_path) as (target, connection):
        await install(target, previous)
        before_receipts = await connection.fetch(
            "SELECT * FROM mission_control.component_release ORDER BY migration_key"
        )
        await connection.execute(f"ALTER FUNCTION {SIGNATURE} SECURITY INVOKER")
        drifted_metadata = await function_metadata(connection)
        plan = await plan_release(target, successor, **VERSIONS)
        assert plan["plan"]["holds"]
        with pytest.raises(ContractError):
            await apply_release(
                target,
                successor,
                confirmation=f"{target['project_ref']}:{target['installation_id']}",
                expected_plan_digest=plan["plan_digest"],
                **VERSIONS,
            )
        assert await function_metadata(connection) == drifted_metadata
        assert (
            await connection.fetchval(
                "SELECT schema_component_version FROM mission_control.application_installation"
            )
            == "1.4.1"
        )
        assert (
            await connection.fetch(
                "SELECT * FROM mission_control.component_release ORDER BY migration_key"
            )
            == before_receipts
        )
