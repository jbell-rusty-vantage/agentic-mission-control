"""Actual 1.9.0 installer proof (Sprint OC W1 / OVE-169).

1.9.0 is the built 1.8.0 prefix plus 0066 (WI-07: the assessment subject guard admits a member a
collection revision lists) and 0067 (W1 defect D22: the `knowledge_operation_handle` operation
check is the exact set Mission Control records a handle for). Fresh install and upgrade from 1.8.0
with preserved receipts and handle rows; on 1.8.0 a `report.observe` handle (the live auditor
census KS accepted in W1 session 6) is refused by `knowledge_operation_handle_operation_check`,
after the upgrade every operation in `RECORDED_HANDLE_OPERATIONS` records under the restricted
runtime role while the control operations stay refused; verify, an idempotent re-apply and the
runtime security baseline. 0066's behaviour is proven through the output-contract store in
``test_wi07_collections_postgres.py``. Prior releases stay immutable.
"""

from __future__ import annotations

import pytest

from mission_control.application.knowledge.operations import RECORDED_HANDLE_OPERATIONS
from mission_control.contracts.knowledge_protocol import EFFECTFUL_OPERATIONS
from mission_control_db_contract.deployment import verify_release
from tests.integration.postgres.test_run2_release_141 import (
    PACKAGE,
    VERSIONS,
    assert_runtime_security,
    disposable,
    install,
    release_at,
)
from tests.integration.postgres.test_sprint_v_release_150 import (
    as_role,
    create_tenant,
    raises_sqlstate,
)
from tests.integration.postgres.test_sprint_v_release_160 import (
    HANDLE_INSERT,
    MISSION_ID,
    RUN_ID,
    wire_handle,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.common_db]
SUCCESSOR = PACKAGE / "releases/1.9.0/component"
PREVIOUS = PACKAGE / "releases/1.8.0/component"
NEW = ["0066_collection_member_assessments", "0067_knowledge_handle_trusted_operations"]
CONTROL = ("knowledge.describe", "operation.get", "operation.cancel", "receipt.get")
TABLE = "mission_control.knowledge_operation_handle"


def handle_args(scope: tuple, operation: str, key: str) -> tuple:
    from uuid import uuid4

    effect_key = f"effect:{key}" if operation in EFFECTFUL_OPERATIONS else None
    return (
        *scope,
        uuid4(),
        operation,
        f"request:{key}",
        f"op-{key}",
        wire_handle(f"op-{key}"),
        effect_key,
        MISSION_ID,
        RUN_ID,
        "queued",
        0,
    )


@pytest.mark.parametrize("upgrade", [None, "1.8.0"], ids=["fresh", "upgrade-from-180"])
async def test_release_190_records_every_handle_operation_and_admits_collection_members(
    tmp_path, upgrade
):
    successor = release_at(SUCCESSOR, tmp_path / "successor-lock", "ai-engineer")
    async with disposable(tmp_path, "ai-engineer") as (target, connection):
        before = []
        tenant = None
        if upgrade:
            await install(target, release_at(PREVIOUS, tmp_path / "previous-lock", "ai-engineer"))
            before = await connection.fetch(
                "SELECT * FROM mission_control.component_release ORDER BY migration_key"
            )
            tenant = await create_tenant(connection, target)
            scope = (target["installation_id"], target["application_id"], tenant)
            async with as_role(connection, target, tenant):
                # A 1.6.0 operation records on 1.8.0 and survives the upgrade unchanged.
                await connection.execute(HANDLE_INSERT, *handle_args(scope, "verify.claims", "v"))
            # W1 D22 reproduced: the KS-accepted auditor observation cannot be recorded.
            async with as_role(connection, target, tenant):
                refused = await raises_sqlstate(
                    connection, "23514", HANDLE_INSERT, *handle_args(scope, "report.observe", "o")
                )
            assert refused.constraint_name == "knowledge_operation_handle_operation_check"
            kept = await connection.fetch(f"SELECT * FROM {TABLE} ORDER BY handle_id")

        result = await install(target, successor)
        assert result["component_version"] == "1.9.0"
        if upgrade:
            assert result["applied_migrations"] == NEW
            assert await connection.fetch(f"SELECT * FROM {TABLE} ORDER BY handle_id") == kept
        else:
            assert result["applied_migrations"][-2:] == NEW
            assert "0065" not in " ".join(result["applied_migrations"])
        for row in before:
            assert (
                await connection.fetchrow(
                    "SELECT * FROM mission_control.component_release WHERE migration_key=$1",
                    row["migration_key"],
                )
                == row
            )

        tenant = tenant or await create_tenant(connection, target)
        scope = (target["installation_id"], target["application_id"], tenant)
        for number, operation in enumerate(sorted(RECORDED_HANDLE_OPERATIONS)):
            async with as_role(connection, target, tenant):
                await connection.execute(
                    HANDLE_INSERT, *handle_args(scope, operation, f"{number}-{operation}")
                )
        recorded = {
            row["operation"]
            for row in await connection.fetch(
                f"SELECT operation FROM {TABLE} WHERE tenant_id=$1", tenant
            )
        }
        assert recorded >= RECORDED_HANDLE_OPERATIONS
        for operation in CONTROL:
            async with as_role(connection, target, tenant):
                await raises_sqlstate(
                    connection, "23514", HANDLE_INSERT, *handle_args(scope, operation, operation)
                )
        # The effect-key rule is unchanged: a trusted assessment handle names no effect key.
        bad = list(handle_args(scope, "report.seal", "seal-with-key"))
        bad[8] = "effect:not-an-effect"
        async with as_role(connection, target, tenant):
            await raises_sqlstate(connection, "23514", HANDLE_INSERT, *bad)

        check = await connection.fetchval(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname='knowledge_operation_handle_operation_check'"
        )
        assert all(f"'{name}'" in check for name in RECORDED_HANDLE_OPERATIONS)
        assert not any(f"'{name}'" in check for name in CONTROL)
        guard = await connection.fetchval(
            "SELECT pg_get_functiondef('mission_control.output_assessment_subject_guard()'"
            "::regprocedure)"
        )
        assert "revision.form = 'collection'" in guard and "$.members" in guard
        assert await connection.fetchval(
            "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE oid=$1::regclass",
            TABLE,
        )
        assert not await connection.fetchval(
            "SELECT has_table_privilege('mission_control_runtime', $1, 'DELETE')", TABLE
        )
        assert (await verify_release(target, successor, **VERSIONS))["status"] == "verified"
        assert (await install(target, successor))["applied_migrations"] == []
        await assert_runtime_security(connection, target)
