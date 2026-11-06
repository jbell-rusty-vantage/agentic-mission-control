"""PostgreSQL `OwnerPrerequisiteRepository` over `mission_control.owner_prerequisite`
(migration 0038; MO-20).

One row per prerequisite id in an installation scope. A first registration inserts an unmet
record; a later one, and every attestation or verification, is merged into the stored record
under its row lock (`OwnerPrerequisiteRecord.registered` and `.evidenced`) and written with the
next version. An unchanged definition writes nothing. The table's guard refuses a changed
identity, a skipped version, an update back in time and a delete, and its checks refuse a
state the evidence method cannot set.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import asyncpg

from mission_control.adapters.postgres.run_control.canonical import SCOPE, begin, load
from mission_control.application.prerequisites.service import UnknownPrerequisite
from mission_control.domain.prerequisites import (
    OwnerPrerequisite,
    OwnerPrerequisiteRecord,
    PrerequisiteEvidence,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _record(value: Any) -> OwnerPrerequisiteRecord:
    return OwnerPrerequisiteRecord.model_validate(load(value))


class PostgresOwnerPrerequisiteRepository:
    def __init__(self, pool: asyncpg.Pool, *, clock: Callable[[], datetime] = _utc_now) -> None:
        self._pool = pool
        self._clock = clock

    async def register(
        self, request_scope: str, prerequisite: OwnerPrerequisite
    ) -> OwnerPrerequisiteRecord:
        record = OwnerPrerequisiteRecord.of(prerequisite)
        now = self._clock()
        async with self._pool.acquire() as connection, connection.transaction():
            args = await begin(connection, request_scope)
            inserted = await connection.fetchval(
                """
                INSERT INTO mission_control.owner_prerequisite (
                    installation_id, application_id, tenant_id, prerequisite_id, provider,
                    prerequisite_scope, definition_digest, state, verification_method,
                    expires_at, record, version, created_at, updated_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NULL, NULL, $9::jsonb, 1, $10, $10)
                ON CONFLICT DO NOTHING
                RETURNING prerequisite_id
                """,
                *args,
                prerequisite.id,
                prerequisite.provider,
                prerequisite.scope.value,
                record.definition_digest,
                record.state.value,
                record.model_dump_json(),
                now,
            )
            if inserted is not None:
                return record
            current = await self._locked(connection, args, prerequisite.id)
            return await self._write(connection, args, current, current.registered(prerequisite))

    async def record_evidence(
        self, request_scope: str, prerequisite_id: str, evidence: PrerequisiteEvidence
    ) -> OwnerPrerequisiteRecord:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await begin(connection, request_scope)
            current = await self._locked(connection, args, prerequisite_id)
            return await self._write(connection, args, current, current.evidenced(evidence))

    async def get(self, request_scope: str, prerequisite_id: str) -> OwnerPrerequisiteRecord | None:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await begin(connection, request_scope)
            stored = await connection.fetchval(
                f"""
                SELECT record FROM mission_control.owner_prerequisite
                WHERE {SCOPE} AND prerequisite_id = $4
                """,
                *args,
                prerequisite_id,
            )
        return None if stored is None else _record(stored)

    async def list(self, request_scope: str) -> tuple[OwnerPrerequisiteRecord, ...]:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await begin(connection, request_scope)
            rows = await connection.fetch(
                f"""
                SELECT record FROM mission_control.owner_prerequisite
                WHERE {SCOPE}
                ORDER BY prerequisite_id
                """,
                *args,
            )
        return tuple(_record(row["record"]) for row in rows)

    async def _locked(
        self, connection: asyncpg.Connection, args: tuple[Any, ...], prerequisite_id: str
    ) -> OwnerPrerequisiteRecord:
        stored = await connection.fetchval(
            f"""
            SELECT record FROM mission_control.owner_prerequisite
            WHERE {SCOPE} AND prerequisite_id = $4
            FOR UPDATE
            """,
            *args,
            prerequisite_id,
        )
        if stored is None:
            raise UnknownPrerequisite(prerequisite_id)
        return _record(stored)

    async def _write(
        self,
        connection: asyncpg.Connection,
        args: tuple[Any, ...],
        current: OwnerPrerequisiteRecord,
        merged: OwnerPrerequisiteRecord,
    ) -> OwnerPrerequisiteRecord:
        if merged == current:
            return current
        evidence = merged.evidence
        await connection.execute(
            f"""
            UPDATE mission_control.owner_prerequisite
            SET definition_digest = $5, state = $6, verification_method = $7,
                expires_at = $8, record = $9::jsonb, version = version + 1,
                updated_at = greatest($10, updated_at)
            WHERE {SCOPE} AND prerequisite_id = $4
            """,
            *args,
            merged.id,
            merged.definition_digest,
            merged.state.value,
            None if evidence is None else evidence.method.value,
            None if evidence is None else evidence.expires_at,
            merged.model_dump_json(),
            self._clock(),
        )
        return merged


__all__ = ["PostgresOwnerPrerequisiteRepository"]
