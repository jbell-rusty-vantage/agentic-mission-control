"""Installation-wide capacity through scoped, non-enumerating definer functions (0041)."""

from datetime import datetime
from uuid import UUID

import asyncpg

from mission_control.adapters.postgres.run_control.canonical import begin
from mission_control.domain.execution.placement import PlacementLimit


class PostgresPlacementStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def reserve(
        self, scope: str, execution: UUID, profile: str, limit: PlacementLimit, now: datetime
    ) -> bool:
        del now  # PostgreSQL owns launch-rate time, never an individual worker clock.
        async with self._pool.acquire() as connection, connection.transaction():
            await begin(connection, scope)
            return bool(
                await connection.fetchval(
                    "SELECT mission_control.placement_reserve($1, $2, $3, $4)",
                    execution,
                    profile,
                    limit.max_active,
                    limit.launches_per_minute,
                )
            )

    async def release(self, scope: str, execution: UUID) -> None:
        async with self._pool.acquire() as connection, connection.transaction():
            await begin(connection, scope)
            await connection.execute("SELECT mission_control.placement_release($1)", execution)
