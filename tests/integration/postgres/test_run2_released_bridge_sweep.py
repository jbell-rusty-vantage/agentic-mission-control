"""Real runtime-role advisory-lock and forced-scope cleanup proof; explicitly unrun offline."""

import asyncio
from pathlib import Path

import pytest

from mission_control.adapters.cursor.bridge_recovery import (
    sweep_released_cursor_bridges,
)
from mission_control.adapters.postgres.lanes.workspace_leases import PostgresWorkspaceLeaseStore
from mission_control.application.workspaces.policy import slot_path
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.integration.postgres.runtime_common import common_db  # noqa: F401
from tests.unit.workspaces.lease_scenarios import NOW, claim

pytestmark = pytest.mark.common_db


async def test_released_sweep_is_scoped_and_acquisition_waits_for_endpoint_shutdown(
    common_db: CommonDatabase,  # noqa: F811
    tmp_path: Path,
):
    pool = await common_db.pool("mission_control_runtime", min_size=3, max_size=3)
    tasks = []
    entered, finish = asyncio.Event(), asyncio.Event()
    try:
        store = PostgresWorkspaceLeaseStore(pool)
        scope = common_db.scope("tenant-1")
        slot = "run:released-cursor"
        candidate = claim(scope, slot).model_copy(
            update={
                "lane_profile": "cursor_local",
                "allocator_ref": "local-root",
                "path": str(slot_path(tmp_path, scope, slot)),
            }
        )
        active = await store.acquire(candidate, now=NOW)
        released = await store.release_fenced(
            scope,
            active.lease_id,
            fence=active.fence,
            patch_artifact_ref=None,
            snapshot_ref=None,
            released_at=NOW,
            cleanup_status="pending",
        )
        assert (
            await store.released_bridge_candidates(
                common_db.scope("tenant-2"),
                allocator_ref="local-root",
                limit=1,
            )
            == ()
        )
        assert (
            await store.released_bridge_candidates(
                scope,
                allocator_ref="foreign-root",
                limit=1,
            )
            == ()
        )

        async def shutdown(*, workspace, timeout_s):
            assert workspace == Path(released.path)
            entered.set()
            await finish.wait()
            return "stopped"

        sweep = asyncio.create_task(
            sweep_released_cursor_bridges(
                store,
                request_scope=scope,
                root=tmp_path,
                allocator_ref="local-root",
                shutdown=shutdown,
                limit=1,
            )
        )
        tasks.append(sweep)
        await asyncio.wait_for(entered.wait(), timeout=3)
        successor = claim(scope, slot, generation=2).model_copy(
            update={
                "lane_profile": "cursor_local",
                "allocator_ref": "local-root",
                "path": released.path,
            }
        )
        acquisition = asyncio.create_task(store.acquire(successor, now=NOW))
        tasks.append(acquisition)
        done, _pending = await asyncio.wait({acquisition}, timeout=0.05)
        assert not done, "acquisition crossed a released-holder shutdown lock"
        finish.set()
        outcomes = await asyncio.wait_for(sweep, timeout=3)
        newer = await asyncio.wait_for(acquisition, timeout=3)
        assert outcomes[0].disposition == "stopped" and newer.fence > released.fence

        async def forbidden(locked):
            pytest.fail("newer active holder was shut down")

        assert not await store.guard_released_bridge(
            released,
            allocator_ref="local-root",
            shutdown=forbidden,
        )
    finally:
        finish.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await pool.close()


async def test_confirmed_receipts_advance_limit_one_to_older_released_holders(
    common_db: CommonDatabase,  # noqa: F811
    tmp_path: Path,
):
    pool = await common_db.pool("mission_control_runtime")
    try:
        store = PostgresWorkspaceLeaseStore(pool)
        scope = common_db.scope("tenant-1")
        holders = []
        for index in range(2):
            slot = f"run:released-advance-{index}"
            candidate = claim(scope, slot).model_copy(
                update={
                    "lane_profile": "cursor_local",
                    "allocator_ref": "advance-root",
                    "path": str(slot_path(tmp_path, scope, slot)),
                }
            )
            active = await store.acquire(candidate, now=NOW)
            holders.append(
                await store.release_fenced(
                    scope,
                    active.lease_id,
                    fence=active.fence,
                    patch_artifact_ref=None,
                    snapshot_ref=None,
                    released_at=NOW,
                    cleanup_status="pending",
                )
            )
        pending = await store.released_bridge_candidates(
            scope,
            allocator_ref="advance-root",
            limit=1,
        )

        async def ambiguous(**kwargs):
            raise ConnectionError("ambiguous-private-endpoint")

        failed = await sweep_released_cursor_bridges(
            store,
            request_scope=scope,
            root=tmp_path,
            allocator_ref="advance-root",
            shutdown=ambiguous,
            limit=1,
        )
        assert failed[0].disposition == "unavailable"
        assert "private-endpoint" not in repr(failed)
        retryable = await store.released_bridge_candidates(
            scope,
            allocator_ref="advance-root",
            limit=1,
        )
        assert retryable[0].lease_id == pending[0].lease_id

        visited = []

        async def shutdown(*, workspace, timeout_s):
            visited.append(workspace)
            return "already_absent" if len(visited) == 1 else "stopped"

        dispositions = []
        ids = []
        for _ in range(2):
            batch = await sweep_released_cursor_bridges(
                store,
                request_scope=scope,
                root=tmp_path,
                allocator_ref="advance-root",
                shutdown=shutdown,
                limit=1,
            )
            assert len(batch) == 1
            dispositions.append(batch[0].disposition)
            ids.append(batch[0].lease_id)
        assert set(ids) == {holder.lease_id for holder in holders}
        assert dispositions == ["already_absent", "stopped"]
        assert len(set(visited)) == 2
        assert (
            await store.released_bridge_candidates(
                scope,
                allocator_ref="advance-root",
                limit=1,
            )
            == ()
        )
    finally:
        await pool.close()
