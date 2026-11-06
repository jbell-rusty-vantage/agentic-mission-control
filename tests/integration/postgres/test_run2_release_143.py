"""Actual 1.4.3 installer proof (cognition points, lane describe subagent fields); prior
releases and their proof remain immutable."""

from __future__ import annotations

import json

import pytest

from mission_control.application.execution.harness.describe import DECLARED_LANE_MATRICES
from mission_control_db_contract.deployment import apply_release, plan_release, verify_release
from mission_control_db_contract.errors import ContractError
from tests.integration.postgres.test_run2_release_141 import (
    PACKAGE,
    VERSIONS,
    assert_runtime_security,
    disposable,
    install,
    release_at,
    retained_release_130,
)
from tests.integration.postgres.test_run2_release_142 import preserve_document

pytestmark = [pytest.mark.asyncio, pytest.mark.common_db]
SUCCESSOR = PACKAGE / "releases/1.4.3/component"
PREVIOUS = PACKAGE / "releases/1.4.2/component"
MIGRATIONS = ["0045_cognition_points", "0046_lane_describe_subagent_fields"]


async def persisted_describes(connection) -> dict[str, dict]:
    rows = await connection.fetch("SELECT lane_profile, describe FROM mission_control.lane_profile")
    return {row["lane_profile"]: json.loads(row["describe"]) for row in rows}


@pytest.mark.parametrize(
    "upgrade", [None, "1.4.2", "1.3.0"], ids=["fresh", "upgrade-from-142", "upgrade-from-130"]
)
async def test_release_143_installs_points_and_describe_fields(tmp_path, upgrade):
    app = "ai-engineer" if upgrade == "1.3.0" else "biotech"
    successor = release_at(SUCCESSOR, tmp_path / "successor-lock", app)
    async with disposable(tmp_path, app) as (target, connection):
        before_receipts = []
        document = None
        if upgrade:
            component = (
                retained_release_130(tmp_path / "retained-130") if upgrade == "1.3.0" else PREVIOUS
            )
            previous = release_at(component, tmp_path / "previous-lock", app)
            await install(target, previous)
            before_receipts = await connection.fetch(
                "SELECT * FROM mission_control.component_release ORDER BY migration_key"
            )
            _tenant, document = await preserve_document(connection, target)
            for describe in (await persisted_describes(connection)).values():
                assert "fields" not in describe["subagents"]
                assert "time_travel" not in describe

        result = await install(target, successor)
        assert result["component_version"] == "1.4.3"
        if upgrade == "1.4.2":
            assert result["applied_migrations"] == MIGRATIONS
        elif upgrade == "1.3.0":
            assert result["applied_migrations"][-2:] == MIGRATIONS
        else:
            assert result["applied_migrations"][-2:] == MIGRATIONS
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
        # Every persisted describe is exactly the declared one, fields and time travel included.
        persisted = await persisted_describes(connection)
        assert persisted == {
            profile: describe.model_dump(mode="json")
            for profile, describe in DECLARED_LANE_MATRICES.items()
        }
        assert persisted["deep_agents"]["qualified"] is True
        assert persisted["deep_agents"]["time_travel"] == {"read": "R3", "fork": "R3"}
        assert all(describe["subagents"]["fields"] for describe in persisted.values())
        # The new table and columns exist with their guards and grants.
        assert await connection.fetchval(
            "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class "
            "WHERE oid = 'mission_control.cognition_point'::regclass"
        )
        assert await connection.fetchval(
            "SELECT has_table_privilege('mission_control_runtime', "
            "'mission_control.cognition_point', 'INSERT')"
        )
        assert not await connection.fetchval(
            "SELECT has_table_privilege('mission_control_runtime', "
            "'mission_control.cognition_point', 'DELETE')"
        )
        assert await connection.fetchval(
            "SELECT has_column_privilege('mission_control_runtime', "
            "'mission_control.agent_session', 'checkpoint_namespace', 'UPDATE')"
        )
        for table, column in (
            ("session_turn", "point_ref"),
            ("activity_attempt_observation", "task_queue"),
        ):
            assert await connection.fetchval(
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema="
                "'mission_control' AND table_name=$1 AND column_name=$2)",
                table,
                column,
            )
        assert (await verify_release(target, successor, **VERSIONS))["status"] == "verified"
        assert (await install(target, successor))["applied_migrations"] == []
        await assert_runtime_security(connection, target)


async def test_release_143_refuses_a_drifted_lane_describe_without_partial_upgrade(tmp_path):
    successor = release_at(SUCCESSOR, tmp_path / "successor-lock")
    previous = release_at(PREVIOUS, tmp_path / "previous-lock")
    async with disposable(tmp_path) as (target, connection):
        await install(target, previous)
        before_receipts = await connection.fetch(
            "SELECT * FROM mission_control.component_release ORDER BY migration_key"
        )
        # Drift the Deep Agents describe the way an unreviewed edit would, under the migrator.
        await connection.execute(
            "ALTER TABLE mission_control.lane_profile NO FORCE ROW LEVEL SECURITY; "
            "ALTER TABLE mission_control.lane_profile DISABLE TRIGGER lane_profile_immutable; "
            "UPDATE mission_control.lane_profile SET describe = describe || "
            '\'{"versions":{"deepagents":"0.0.0"}}\'::jsonb '
            "WHERE lane_profile = 'deep_agents'; "
            "ALTER TABLE mission_control.lane_profile ENABLE TRIGGER lane_profile_immutable; "
            "ALTER TABLE mission_control.lane_profile FORCE ROW LEVEL SECURITY"
        )
        plan = await plan_release(target, successor, **VERSIONS)
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
            == "1.4.2"
        )
        assert (
            await connection.fetch(
                "SELECT * FROM mission_control.component_release ORDER BY migration_key"
            )
            == before_receipts
        )
        assert not await connection.fetchval(
            "SELECT to_regclass('mission_control.cognition_point') IS NOT NULL"
        )
