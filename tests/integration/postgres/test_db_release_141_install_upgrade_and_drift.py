"""Real installer proof for the canonical 1.4.1 successor on fresh mct_* databases."""

from __future__ import annotations

import json

import pytest

from mission_control.application.execution.harness.describe import declared_matrix
from mission_control_db_contract.deployment import apply_release, plan_release, verify_release
from mission_control_db_contract.errors import ContractError
from mission_control_db_contract.seeds import load_bundles, seed_apply, seed_plan
from tests.support.integration.postgres.run2_release_141 import (
    PACKAGE,
    VERSIONS,
    assert_runtime_security,
    disposable,
    install,
    release_at,
    retained_release_130,
)

SUCCESSOR = PACKAGE / "releases/1.4.1/component"
pytestmark = [pytest.mark.asyncio, pytest.mark.common_db]


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
