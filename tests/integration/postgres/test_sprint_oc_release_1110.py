"""Exact-export family writer grants preserve source authority and forced tenant isolation."""

from pathlib import Path

import pytest

from mission_control_db_contract.deployment import plan_release, verify_release
from tests.integration.postgres.test_run2_release_141 import (
    PACKAGE,
    VERSIONS,
    disposable,
    insert_document,
    install,
    release_at,
)
from tests.integration.postgres.test_sprint_v_release_150 import (
    as_role,
    create_tenant,
    raises_sqlstate,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.common_db]
READS = (
    "output_obligation_head",
    "output_obligation_revision",
    "output_revision",
    "output_accepted_head",
    "output_submission",
    "invocation_finalization",
)


@pytest.mark.parametrize("upgrade", [False, True], ids=["fresh", "upgrade-from-1100"])
async def test_family_writer_can_seal_exports_without_source_mutation(
    tmp_path: Path, upgrade: bool
) -> None:
    successor = release_at(PACKAGE / "releases/1.11.0/component", tmp_path / "new", "ai-engineer")
    async with disposable(tmp_path, "ai-engineer") as (target, connection):
        receipts = []
        if upgrade:
            await install(
                target,
                release_at(PACKAGE / "releases/1.10.0/component", tmp_path / "old", "ai-engineer"),
            )
            receipts = await connection.fetch("SELECT * FROM mission_control.component_release")
            plan = await plan_release(target, successor, **VERSIONS)
            assert plan["plan"]["pending_migrations"] == ["0069_linked_export_family_writer"]
        await install(target, successor)
        for row in receipts:
            assert (
                await connection.fetchrow(
                    "SELECT * FROM mission_control.component_release WHERE migration_key=$1",
                    row["migration_key"],
                )
                == row
            )
        tenant = await create_tenant(connection, target)
        async with as_role(connection, target, tenant, role="mission_control_family_writer"):
            for table in READS:
                assert (
                    await connection.fetchval(f"SELECT count(*) FROM mission_control.{table}") == 0
                )
                assert await connection.fetchval(
                    "SELECT has_table_privilege(current_user,$1,'SELECT')",
                    f"mission_control.{table}",
                )
                for privilege in ("INSERT", "UPDATE", "DELETE"):
                    assert not await connection.fetchval(
                        "SELECT has_table_privilege(current_user,$1,$2)",
                        f"mission_control.{table}",
                        privilege,
                    )
            await insert_document(connection, target, tenant, "linked.export/1", "family-export")
            assert (
                await connection.fetchval("SELECT count(*) FROM mission_control.runtime_document")
                == 1
            )
            await raises_sqlstate(
                connection, "42501", "UPDATE mission_control.runtime_document SET payload='{}'"
            )
            await raises_sqlstate(
                connection, "42501", "DELETE FROM mission_control.runtime_document"
            )
            # The new INSERT grant cannot author another immutable runtime contract.
            transaction = connection.transaction()
            await transaction.start()
            try:
                import asyncpg

                with pytest.raises(asyncpg.InsufficientPrivilegeError):
                    await insert_document(
                        connection, target, tenant, "goal.verification/1", "forbidden"
                    )
            finally:
                await transaction.rollback()
        other = await create_tenant(connection, target)
        async with as_role(connection, target, other, role="mission_control_family_writer"):
            assert (
                await connection.fetchval("SELECT count(*) FROM mission_control.runtime_document")
                == 0
            )
        assert (await verify_release(target, successor, **VERSIONS))["status"] == "verified"
        assert (await install(target, successor))["applied_migrations"] == []
