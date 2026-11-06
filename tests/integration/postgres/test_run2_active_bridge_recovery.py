# ruff: noqa: F811
"""Runtime-role active orphan inspection retains custody and serializes with owner/acquisition."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import asyncpg
import pytest

from mission_control.adapters.postgres.frames.repository import PostgresFrameRepository
from mission_control.adapters.postgres.lanes.execution_state import PostgresLaneExecutionStateStore
from mission_control.adapters.postgres.lanes.workspace_leases import PostgresWorkspaceLeaseStore
from mission_control.adapters.postgres.run_control.cluster_bindings import (
    PostgresRunClusterBindings,
)
from mission_control.application.execution.harness.leases import lease_identity
from mission_control.application.execution.run_launch import TemporalClusterIdentity
from mission_control.application.workspaces.errors import WorkspaceLeaseHeld
from mission_control.application.workspaces.policy import slot_path
from mission_control.domain.frames.contracts import LaneProfile
from tests.integration.postgres.frames_common import admit_unit_attempt
from tests.integration.postgres.runtime_common import common_db  # noqa: F401
from tests.unit.workspaces.lease_scenarios import claim

pytestmark = pytest.mark.common_db


async def setup(common_db, pool, root):
    unit = await admit_unit_attempt(pool, common_db)
    start = unit.start(lane=LaneProfile.CURSOR_LOCAL).model_copy(
        update={"native_identity": {"semantic_attempt_key": "fixture:semantic"}}
    )
    await PostgresFrameRepository(pool).open_execution(start)
    scope, execution = start.request_scope, start.harness_execution_id
    await PostgresRunClusterBindings(pool).bind(
        scope,
        unit.run_key,
        workflow_id="fixture:root",
        cluster=TemporalClusterIdentity("fixture", "local", "127.0.0.1:7233", "default", "fixture"),
        now=datetime.now(UTC),
    )
    owner = await asyncpg.connect(common_db.owner_dsn)
    try:
        intent = uuid4()
        await owner.execute(
            """INSERT INTO mission_control.operation_intent
            (installation_id,application_id,tenant_id,operation_intent_id,run_id,
             action_ref,effect_key,input_digest,side_effect_class,state,detail,version,
             updated_at,created_at,created_by_actor_ref)
            SELECT installation_id,application_id,tenant_id,$2,run_id,'fixture','fixture',
              $3,'fixture','claimed','{}',1,now(),now(),'fixture'
            FROM mission_control.harness_execution WHERE harness_execution_id=$1""",
            execution,
            intent,
            "sha256:" + "a" * 64,
        )
        await owner.execute(
            """INSERT INTO mission_control.operation_claim
            (installation_id,application_id,tenant_id,operation_claim_id,claim_key,
             operation_intent_id,run_key,operation_contract_digest,idempotency_key,request_digest,
             semantic_binding_key,semantic_binding_digest,semantic_attempt_key,unit_key,
             claim_mode,status,claimed_by,claimed_at,version,updated_at,created_at,created_by_actor_ref)
            SELECT installation_id,application_id,tenant_id,$2,'fixture',$3,$4,$5,'fixture',$5,
              'fixture',$5,'fixture:semantic',$6,'active','executing','fixture',now(),1,now(),now(),'fixture'
            FROM mission_control.harness_execution WHERE harness_execution_id=$1""",
            execution,
            uuid4(),
            intent,
            unit.run_key,
            "sha256:" + "a" * 64,
            unit.unit.unit_key,
        )
    finally:
        await owner.close()
    store = PostgresWorkspaceLeaseStore(pool)
    lease_id, key = lease_identity("cursor_local", execution, 1)
    slot = "active-fixture"
    candidate = claim(scope, slot).model_copy(
        update={
            "lease_id": lease_id,
            "lease_key": key,
            "lane_profile": "cursor_local",
            "harness_execution_id": execution,
            "run_id": unit.run_key,
            "allocator_ref": "fixture:host",
            "path": str(slot_path(root, scope, slot)),
        }
    )
    candidate = await store.acquire(candidate, now=datetime.now(UTC))
    return store, candidate, PostgresLaneExecutionStateStore(pool)


async def test_active_guard_serializes_owner_and_acquisition_without_releasing(common_db, tmp_path):
    pool = await common_db.pool("mission_control_runtime", min_size=4, max_size=4)
    tasks = []
    entered, finish = asyncio.Event(), asyncio.Event()
    try:
        store, candidate, states = await setup(common_db, pool, tmp_path)
        assert (
            await store.active_bridge_candidates(
                common_db.scope("tenant-2"), allocator_ref="fixture:host", limit=1
            )
            == ()
        )

        async def inspect(context):
            assert context.lease == candidate and context.root_workflow_id == "fixture:root"
            assert context.workflow_id.endswith("/operation/fixture:semantic")
            entered.set()
            await finish.wait()
            return "recovery_notified"

        sweep = asyncio.create_task(
            store.guard_active_bridge(candidate, allocator_ref="fixture:host", inspect=inspect)
        )
        tasks.append(sweep)
        await asyncio.wait_for(entered.wait(), 3)
        owner = asyncio.create_task(
            states.claim_owner(
                candidate.request_scope,
                candidate.harness_execution_id,
                owner_ref="new-worker",
                generation=1,
                now=datetime.now(UTC),
                lease=timedelta(seconds=30),
            )
        )
        successor = candidate.model_copy(
            update={"lease_id": uuid4(), "lease_key": "competing", "generation": 2}
        )
        acquisition = asyncio.create_task(store.acquire(successor, now=datetime.now(UTC)))
        tasks.extend((owner, acquisition))
        done, _ = await asyncio.wait({owner, acquisition}, timeout=0.05)
        assert not done
        finish.set()
        assert await sweep == "recovery_notified"
        await owner
        with pytest.raises(WorkspaceLeaseHeld):
            await acquisition
        retained = await store.get(candidate.request_scope, candidate.lease_id)
        assert retained == candidate and not retained.released

        async def forbidden(context):
            pytest.fail("live new owner must not be inspected")

        assert (
            await store.guard_active_bridge(
                candidate, allocator_ref="fixture:host", inspect=forbidden
            )
            == "protected"
        )
    finally:
        finish.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await pool.close()


async def test_stale_generation_and_missing_route_remain_retained(common_db, tmp_path):
    pool = await common_db.pool("mission_control_runtime")
    owner = await asyncpg.connect(common_db.owner_dsn)
    try:
        store, candidate, _ = await setup(common_db, pool, tmp_path)

        async def forbidden(context):
            pytest.fail("unbound or stale execution must not be inspected")

        await owner.execute(
            "UPDATE mission_control.harness_execution SET generation=2 "
            "WHERE harness_execution_id=$1",
            candidate.harness_execution_id,
        )
        assert (
            await store.guard_active_bridge(
                candidate, allocator_ref="fixture:host", inspect=forbidden
            )
            == "protected"
        )
        await owner.execute(
            "UPDATE mission_control.harness_execution SET generation=1 "
            "WHERE harness_execution_id=$1",
            candidate.harness_execution_id,
        )
        await owner.execute(
            "UPDATE mission_control.operation_claim SET status='settled' "
            "WHERE semantic_attempt_key='fixture:semantic'"
        )
        assert (
            await store.guard_active_bridge(
                candidate, allocator_ref="fixture:host", inspect=forbidden
            )
            == "custody_required"
        )
        assert await store.get(candidate.request_scope, candidate.lease_id) == candidate
    finally:
        await owner.close()
        await pool.close()
