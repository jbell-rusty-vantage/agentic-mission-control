"""1.12.0 Workspace Closures: append-only, tenant-isolated, expired only by the definer.

OVE-204 slice 5 (`0070_workspace_closure.sql`): fresh install and upgrade from 1.11.0; the
runtime role inserts and reads closures and entries, cannot update or delete them, another
tenant sees none; `expire_workspace_closures` deletes only completed runs' closures past
`retain_until` (entries cascade); the readonly role reads only.
"""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from mission_control_db_contract.deployment import plan_release, verify_release
from tests.integration.postgres.test_run2_release_141 import (
    PACKAGE,
    VERSIONS,
    disposable,
    install,
    release_at,
)
from tests.integration.postgres.test_sprint_v_release_150 import (
    as_role,
    create_tenant,
    raises_sqlstate,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.common_db]
ACTOR = "fixture:release-1120"
UNIT = "bl-unit-v1:" + "c" * 64


def _digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


async def _run(connection, target, tenant, *, completed: bool) -> UUID:
    """Owner-inserted mission/revision/run chain (fixture data only)."""

    key = (UUID(target["installation_id"]), target["application_id"], tenant)
    now = datetime.now(UTC)
    mission_id, snapshot_id, revision_id, run_id = uuid4(), uuid4(), uuid4(), uuid4()
    run_key = f"run-{run_id}"
    definition = {"fixture": run_key}
    await connection.execute(
        """INSERT INTO mission_control.mission
           (installation_id, application_id, tenant_id, mission_id, mission_key, title,
            owner_actor_ref, lifecycle, next_event_seq, version, updated_at, last_event_seq,
            created_at, created_by_actor_ref)
           VALUES ($1,$2,$3,$4,$5,'fixture mission',$6,'active',1,1,$7,0,$7,$6)""",
        *key,
        mission_id,
        "mission:" + run_key,
        ACTOR,
        now,
    )
    await connection.execute(
        """INSERT INTO mission_control.definition_snapshot
           (installation_id, application_id, tenant_id, definition_snapshot_id, mission_id,
            definition_contract_version, definition, definition_digest, created_at,
            created_by_actor_ref)
           VALUES ($1,$2,$3,$4,$5,'fixture/1',$6::jsonb,$7,$8,$9)""",
        *key,
        snapshot_id,
        mission_id,
        json.dumps(definition),
        _digest(definition),
        now,
        ACTOR,
    )
    await connection.execute(
        """INSERT INTO mission_control.mission_revision
           (installation_id, application_id, tenant_id, revision_id, mission_id, revision_no,
            definition_snapshot_id, policy_digest, binding_digest, committed_at, created_at,
            created_by_actor_ref)
           VALUES ($1,$2,$3,$4,$5,1,$6,$7,$7,$8,$8,$9)""",
        *key,
        revision_id,
        mission_id,
        snapshot_id,
        _digest("fixture-policy"),
        now,
        ACTOR,
    )
    await connection.execute(
        """INSERT INTO mission_control.mission_run
           (installation_id, application_id, tenant_id, run_id, run_key, mission_id,
            revision_id, scheduling_revision_id, request_key, input_manifest_ref,
            input_digest, admission_binding_ref, admission_binding_digest, workflow_family,
            phase, lifecycle, terminal_outcome, execution_epoch, execution_generation,
            technical_segment, admitted_policy_ref, admitted_build_ref, projection_contract,
            projection, version, admitted_at, updated_at, created_at, created_by_actor_ref)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$7,$8,'fixture://input',$9,'fixture://binding',$9,
                   'stagegraph',$10,$11,$12,1,1,1,'fixture-policy','fixture-build',
                   'fixture.run/1','{}'::jsonb,1,$13,$13,$13,$14)""",
        *key,
        run_id,
        run_key,
        mission_id,
        revision_id,
        "request:" + run_key,
        _digest(definition),
        "terminal" if completed else "active",
        "completed" if completed else "active",
        "succeeded" if completed else None,
        now,
        ACTOR,
    )
    return run_id


async def _closure(connection, target, tenant, run_id: UUID, *, retain_until) -> UUID:
    closure_id = uuid4()
    digest = "sha256:" + "d" * 64
    await connection.execute(
        """INSERT INTO mission_control.workspace_closure
           (installation_id, application_id, tenant_id, closure_id, run_id, unit_key,
            execution_generation, harness_execution_id, point_id, boundary, backend, manifest,
            manifest_digest, file_count, total_bytes, promoted_bytes, complete, retain_until,
            recorded_at, created_at, created_by_actor_ref)
           VALUES ($1::uuid,$2,$3,$4,$5,$6,1,NULL,$7,'attempt_settled','state',$8::jsonb,$9,
                   2,10,4,true,$10,now(),now(),$11)""",
        target["installation_id"],
        target["application_id"],
        tenant,
        closure_id,
        run_id,
        UNIT,
        uuid4(),
        json.dumps({"schema_version": "mc.workspace_closure.v1"}),
        digest,
        retain_until,
        ACTOR,
    )
    await connection.executemany(
        """INSERT INTO mission_control.workspace_closure_entry
           (installation_id, application_id, tenant_id, closure_id, run_id, path, size_bytes,
            digest, slot, destination, body_state, object_ref, media_type, candidate_id)
           VALUES ($1::uuid,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,'text/plain',NULL)""",
        [
            (
                target["installation_id"],
                target["application_id"],
                tenant,
                closure_id,
                run_id,
                "/out/a.txt",
                4,
                digest,
                "out",
                "state_channel",
                "promoted",
                "memory://artifacts/" + "d" * 64,
            ),
            (
                target["installation_id"],
                target["application_id"],
                tenant,
                closure_id,
                run_id,
                "/private/b.txt",
                6,
                digest,
                "private",
                "state_channel",
                "withheld_sensitive",
                None,
            ),
        ],
    )
    return closure_id


@pytest.mark.parametrize("upgrade", [False, True], ids=["fresh", "upgrade-from-1110"])
async def test_workspace_closures_are_append_only_scoped_and_expired_by_definer(
    tmp_path: Path, upgrade: bool
) -> None:
    successor = release_at(PACKAGE / "releases/1.12.0/component", tmp_path / "new", "biotech")
    async with disposable(tmp_path, "biotech") as (target, connection):
        receipts = []
        if upgrade:
            await install(
                target,
                release_at(PACKAGE / "releases/1.11.0/component", tmp_path / "old", "biotech"),
            )
            receipts = await connection.fetch("SELECT * FROM mission_control.component_release")
            plan = await plan_release(target, successor, **VERSIONS)
            assert plan["plan"]["pending_migrations"] == ["0070_workspace_closure"]
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
        completed = await _run(connection, target, tenant, completed=True)
        active = await _run(connection, target, tenant, completed=False)
        past = datetime.now(UTC) - timedelta(days=1)
        async with as_role(connection, target, tenant):
            expiring = await _closure(connection, target, tenant, completed, retain_until=past)
            kept_mission = await _closure(connection, target, tenant, completed, retain_until=None)
            kept_active = await _closure(connection, target, tenant, active, retain_until=past)
            assert (
                await connection.fetchval("SELECT count(*) FROM mission_control.workspace_closure")
                == 3
            )
            assert (
                await connection.fetchval(
                    "SELECT count(*) FROM mission_control.workspace_closure_entry"
                )
                == 6
            )
            for table in ("workspace_closure", "workspace_closure_entry"):
                for privilege in ("UPDATE", "DELETE"):
                    assert not await connection.fetchval(
                        "SELECT has_table_privilege(current_user,$1,$2)",
                        f"mission_control.{table}",
                        privilege,
                    )
        async with as_role(connection, target, tenant):
            await raises_sqlstate(
                connection, "42501", "UPDATE mission_control.workspace_closure SET complete=false"
            )
            await raises_sqlstate(
                connection, "42501", "DELETE FROM mission_control.workspace_closure"
            )
            # A promoted body always names its object; a withheld one never does.
            await raises_sqlstate(
                connection,
                "23514",
                """INSERT INTO mission_control.workspace_closure_entry
                   (installation_id, application_id, tenant_id, closure_id, run_id, path,
                    size_bytes, digest, destination, body_state, object_ref)
                   SELECT installation_id, application_id, tenant_id, closure_id, run_id,
                          '/out/c.txt', 1, 'sha256:' || repeat('e', 64), 'state_channel',
                          'promoted', NULL
                   FROM mission_control.workspace_closure LIMIT 1""",
            )
        other = await create_tenant(connection, target)
        async with as_role(connection, target, other):
            assert (
                await connection.fetchval("SELECT count(*) FROM mission_control.workspace_closure")
                == 0
            )
            assert (
                await connection.fetchval(
                    "SELECT count(*) FROM mission_control.expire_workspace_closures(now())"
                )
                == 0
            )
        async with as_role(connection, target, tenant, role="mission_control_readonly"):
            assert (
                await connection.fetchval(
                    "SELECT count(*) FROM mission_control.workspace_closure_entry"
                )
                == 6
            )
            assert not await connection.fetchval(
                "SELECT has_table_privilege(current_user,'mission_control.workspace_closure',"
                "'INSERT')"
            )
        async with as_role(connection, target, tenant):
            expired = await connection.fetch(
                "SELECT expired_closure_id FROM mission_control.expire_workspace_closures(now())"
            )
            assert [row["expired_closure_id"] for row in expired] == [expiring]
            remaining = {
                row["closure_id"]
                for row in await connection.fetch(
                    "SELECT closure_id FROM mission_control.workspace_closure"
                )
            }
            assert remaining == {kept_mission, kept_active}
            assert (
                await connection.fetchval(
                    "SELECT count(*) FROM mission_control.workspace_closure_entry"
                )
                == 4
            )
        assert (await verify_release(target, successor, **VERSIONS))["status"] == "verified"
        assert (await install(target, successor))["applied_migrations"] == []
