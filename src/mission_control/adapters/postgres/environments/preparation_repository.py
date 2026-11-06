"""PostgreSQL `EnvironmentPreparationRepository` over `mission_control.environment_preparation`
(migration 0037; MO-16).

One row per harness execution generation, keyed by the deterministic preparation id. A first
record inserts; a later one is merged into the stored record under its row lock
(`EnvironmentPreparation.merged`: only levels beyond the stored one are added) and written with
the next version. The table's guard refuses what the merge already never does (a regressed
level, a changed receipt or identity, a delete), so a writer that bypasses the merge fails too.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import asyncpg

from mission_control.adapters.postgres.run_control.canonical import SCOPE, begin, load
from mission_control.domain.execution.environment_preparation import EnvironmentPreparation


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _record(value: Any) -> EnvironmentPreparation:
    return EnvironmentPreparation.model_validate(load(value))


class PostgresEnvironmentPreparationRepository:
    def __init__(self, pool: asyncpg.Pool, *, clock: Callable[[], datetime] = _utc_now) -> None:
        self._pool = pool
        self._clock = clock

    async def record(
        self, request_scope: str, preparation: EnvironmentPreparation
    ) -> EnvironmentPreparation:
        now = self._clock()
        async with self._pool.acquire() as connection, connection.transaction():
            args = await begin(connection, request_scope)
            inserted = await connection.fetchval(
                """
                INSERT INTO mission_control.environment_preparation (
                    installation_id, application_id, tenant_id, preparation_id, run_key,
                    harness_execution_id, generation, lane_profile, binding_digest,
                    declaration_digest, readiness, receipt_digest, record, version,
                    created_at, updated_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13::jsonb, 1,
                        $14, $14)
                ON CONFLICT DO NOTHING
                RETURNING preparation_id
                """,
                *args,
                preparation.preparation_id,
                preparation.run_key,
                preparation.harness_execution_id,
                preparation.generation,
                preparation.lane_profile,
                preparation.binding_digest,
                preparation.declaration_digest,
                preparation.readiness.value,
                preparation.receipt_digest,
                preparation.model_dump_json(),
                now,
            )
            if inserted is not None:
                return preparation
            stored = await connection.fetchval(
                f"""
                SELECT record FROM mission_control.environment_preparation
                WHERE {SCOPE} AND preparation_id = $4
                FOR UPDATE
                """,
                *args,
                preparation.preparation_id,
            )
            if stored is None:
                raise LookupError(
                    f"environment preparation {preparation.preparation_id} is held by another scope"
                )
            current = _record(stored)
            merged = current.merged(preparation)
            if merged == current:
                return current
            await connection.execute(
                f"""
                UPDATE mission_control.environment_preparation
                SET readiness = $5, receipt_digest = $6, record = $7::jsonb,
                    version = version + 1, updated_at = greatest($8, updated_at)
                WHERE {SCOPE} AND preparation_id = $4
                """,
                *args,
                merged.preparation_id,
                merged.readiness.value,
                merged.receipt_digest,
                merged.model_dump_json(),
                now,
            )
        return merged

    async def get(self, request_scope: str, preparation_id: UUID) -> EnvironmentPreparation | None:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await begin(connection, request_scope)
            stored = await connection.fetchval(
                f"""
                SELECT record FROM mission_control.environment_preparation
                WHERE {SCOPE} AND preparation_id = $4
                """,
                *args,
                preparation_id,
            )
        return None if stored is None else _record(stored)

    async def for_run(self, request_scope: str, run_key: str) -> tuple[EnvironmentPreparation, ...]:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await begin(connection, request_scope)
            rows = await connection.fetch(
                f"""
                SELECT record FROM mission_control.environment_preparation
                WHERE {SCOPE} AND run_key = $4
                ORDER BY created_at, harness_execution_id, generation
                """,
                *args,
                run_key,
            )
        return tuple(_record(row["record"]) for row in rows)


__all__ = ["PostgresEnvironmentPreparationRepository"]
