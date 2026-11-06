"""1.14.0: cross-provider control lane describes (0073, OVE-224, ADR-0069).

Every Session Lane now declares its `time_travel` cells; 0073 revises exactly the profiles whose
describe moved since 1.13.0, each UPDATE guarded by the prior literal. Fresh install and upgrade
from 1.13.0 keep every earlier receipt, plan exactly the one new migration, verify, replay as a
no-op, and leave `lane_profile.describe` equal to the declared matrices.
"""

import json
from pathlib import Path

import pytest

from mission_control.application.execution.harness.describe import DECLARED_LANE_MATRICES
from mission_control_db_contract.deployment import plan_release, verify_release
from tests.integration.postgres.test_run2_release_141 import (
    PACKAGE,
    VERSIONS,
    disposable,
    install,
    release_at,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.common_db]
NEW = ["0073_cross_provider_lane_describes"]


@pytest.mark.parametrize("upgrade", [False, True], ids=["fresh", "upgrade-from-1130"])
async def test_release_1140_refreshes_lane_describes_additively(
    tmp_path: Path, upgrade: bool
) -> None:
    successor = release_at(PACKAGE / "releases/1.14.0/component", tmp_path / "new", "ai-engineer")
    async with disposable(tmp_path, "ai-engineer") as (target, connection):
        receipts = []
        if upgrade:
            await install(
                target,
                release_at(PACKAGE / "releases/1.13.0/component", tmp_path / "old", "ai-engineer"),
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
        rows = await connection.fetch(
            "SELECT lane_profile, describe, qualified FROM mission_control.lane_profile"
        )
        persisted = {
            row["lane_profile"]: (
                json.loads(row["describe"]) if isinstance(row["describe"], str) else row["describe"]
            )
            for row in rows
        }
        declared = {
            profile: describe.model_dump(mode="json")
            for profile, describe in DECLARED_LANE_MATRICES.items()
        }
        assert persisted == declared
        for profile, document in persisted.items():
            assert ("time_travel" in document) == (declared[profile].get("time_travel") is not None)
        assert {row["lane_profile"] for row in rows if row["qualified"]} == {"deep_agents"}
        assert (await verify_release(target, successor, **VERSIONS))["status"] == "verified"
        assert (await install(target, successor))["applied_migrations"] == []
