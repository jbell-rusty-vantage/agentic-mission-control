"""1.13.0: nested program activations (0071) and native plan decision columns (0072).

W1 D31 (2026-11-02): the runtime already reads both, so they ship as one additive minor on the
built 1.12.0 prefix. Fresh install and upgrade from 1.12.0 keep every earlier receipt, plan
exactly the two new migrations, verify, and replay as a no-op. Table behaviour is proven by
`test_wi13_nested_activations_postgres.py` and `test_native_plan_decisions_postgres.py`.
"""

from pathlib import Path

import pytest

from mission_control_db_contract.deployment import plan_release, verify_release
from tests.integration.postgres.test_run2_release_141 import (
    PACKAGE,
    VERSIONS,
    disposable,
    install,
    release_at,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.common_db]
NEW = ["0071_nested_program_activations", "0072_native_plan_decisions"]


@pytest.mark.parametrize("upgrade", [False, True], ids=["fresh", "upgrade-from-1120"])
async def test_release_1130_installs_and_upgrades_additively(tmp_path: Path, upgrade: bool) -> None:
    successor = release_at(PACKAGE / "releases/1.13.0/component", tmp_path / "new", "ai-engineer")
    async with disposable(tmp_path, "ai-engineer") as (target, connection):
        receipts = []
        if upgrade:
            await install(
                target,
                release_at(PACKAGE / "releases/1.12.0/component", tmp_path / "old", "ai-engineer"),
            )
            receipts = await connection.fetch("SELECT * FROM mission_control.component_release")
            plan = await plan_release(target, successor, **VERSIONS)
            assert plan["plan"]["pending_migrations"] == NEW
        await install(target, successor)
        for row in receipts:
            assert (
                await connection.fetchrow(
                    "SELECT * FROM mission_control.component_release WHERE migration_key=$1",
                    row["migration_key"],
                )
                == row
            )
        keys = {
            row["migration_key"]
            for row in await connection.fetch(
                "SELECT migration_key FROM mission_control.component_release"
            )
        }
        assert set(NEW) <= keys
        columns = {
            row["column_name"]
            for row in await connection.fetch(
                "SELECT column_name FROM information_schema.columns WHERE table_schema = "
                "'mission_control' AND table_name = 'knowledge_use_decision'"
            )
        }
        assert {"subject_ref", "invocation_ref", "decision_digest"} <= columns
        assert await connection.fetchval("SELECT to_regclass('mission_control.nested_activation')")
        assert (await verify_release(target, successor, **VERSIONS))["status"] == "verified"
        assert (await install(target, successor))["applied_migrations"] == []
