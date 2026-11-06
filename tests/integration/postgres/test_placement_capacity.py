"""Real PostgreSQL role/RLS capacity admission and restart-safe reservations (0041)."""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import asyncpg
import pytest

from mission_control.adapters.postgres.frames.repository import PostgresFrameRepository
from mission_control.adapters.postgres.lanes.placement import PostgresPlacementStore
from mission_control.adapters.postgres.run_control.canonical import begin
from mission_control.domain.execution.placement import PlacementLimit
from mission_control.domain.frames.contracts import LaneProfile
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.integration.postgres.frames_common import admit_unit_attempt
from tests.integration.postgres.runtime_common import common_db  # noqa: F401

pytestmark = pytest.mark.common_db


async def test_durable_capacity_restarts_and_cannot_enumerate_or_forge_other_tenants(
    common_db: CommonDatabase,  # noqa: F811
) -> None:
    pool = await common_db.pool("mission_control_runtime")
    try:
        admitted = await admit_unit_attempt(pool, common_db)
        store = PostgresPlacementStore(pool)
        frames = PostgresFrameRepository(pool)
        ids = [uuid4() for _ in range(5)]
        for execution in ids:
            start = admitted.start(lane=LaneProfile.CURSOR_CLOUD).model_copy(
                update={"harness_execution_id": execution, "launch_key": str(execution)}
            )
            await frames.open_execution(start)
        scope = start.request_scope
        limit = PlacementLimit(max_active=3)
        now = datetime.now(UTC)
        results = await asyncio.gather(
            *(store.reserve(scope, execution, "cursor_cloud", limit, now) for execution in ids)
        )
        assert sum(results) == 3
        other = await admit_unit_attempt(pool, common_db, tenant="tenant-2")
        other_start = other.start(lane=LaneProfile.CURSOR_CLOUD)
        await frames.open_execution(other_start)
        assert not await store.reserve(
            other_start.request_scope,
            other_start.harness_execution_id,
            "cursor_cloud",
            limit,
            now,
        )
        # Another tenant cannot free our reservation to make room for itself.
        await store.release(other_start.request_scope, ids[results.index(True)])
        assert not await store.reserve(
            other_start.request_scope,
            other_start.harness_execution_id,
            "cursor_cloud",
            limit,
            now,
        )
        await store.release(scope, ids[results.index(True)])
        waiting = ids[results.index(False)]
        assert await PostgresPlacementStore(pool).reserve(
            scope, waiting, "cursor_cloud", limit, now
        )
        assert await store.reserve(scope, waiting, "cursor_cloud", limit, now)
        async with pool.acquire() as connection, connection.transaction():
            await begin(connection, scope)
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await connection.fetch("SELECT * FROM mission_control.placement_reservation")
        with pytest.raises(asyncpg.RaiseError, match="not admitted"):
            await store.reserve(scope, uuid4(), "cursor_cloud", limit, now)
    finally:
        await pool.close()
