"""``RetainedReadStore`` over ``mission_control.retained_read_observation`` (release 1.5.0, 0052).

Append-only: each observation has a deterministic id (UUIDv5 of its invocation ref and read
observation ref, computed by the caller), and the insert targets the table's unique key
``(scope, invocation_ref, read_observation_ref)`` with ``DO NOTHING``, so a replayed read is the
same row. ``digest_verified`` is a generated column and is never written.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime

import asyncpg

from mission_control.adapters.postgres.run_control import canonical as mc
from mission_control.adapters.postgres.run_control.canonical import SCOPE
from mission_control.adapters.postgres.scope import apply_actor
from mission_control.domain.knowledge.reads import RetainedReadObservation

_TABLE = "mission_control.retained_read_observation"


class PostgresRetainedReadStore:
    """RLS-scoped retained read observations for one runtime-role pool."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def record(
        self,
        scope: str,
        rows: Sequence[RetainedReadObservation],
        *,
        actor_ref: str,
        at: datetime,
    ) -> int:
        if not rows:
            return 0
        written = 0
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            await apply_actor(connection, actor_ref)
            for row in rows:
                status = await connection.execute(
                    f"INSERT INTO {_TABLE} (installation_id, application_id, tenant_id, "
                    "observation_id, source_binding_id, run_id, invocation_ref, handle, "
                    "read_observation_ref, retained_ref, expected_digest, observed_digest, "
                    "readable, byte_count, consistency, observed_at, created_at, "
                    "created_by_actor_ref) VALUES ($1, $2, $3, $4::uuid, $5::uuid, $6::uuid, $7, "
                    "$8, $9, $10, $11, $12, $13, $14, $15::jsonb, $16, $17, $18) "
                    "ON CONFLICT (installation_id, application_id, tenant_id, invocation_ref, "
                    "read_observation_ref) DO NOTHING",
                    *args,
                    row.observation_id,
                    row.source_binding_id,
                    row.run_id,
                    row.invocation_ref,
                    row.handle,
                    row.read_observation_ref,
                    row.retained_ref,
                    row.expected_digest,
                    row.observed_digest,
                    row.readable,
                    row.byte_count,
                    json.dumps(dict(row.consistency), sort_keys=True, separators=(",", ":")),
                    row.observed_at,
                    at,
                    actor_ref,
                )
                written += int(status.rsplit(" ", 1)[-1])
        return written

    async def observations(self, scope: str, invocation_ref: str) -> list[RetainedReadObservation]:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            rows = await connection.fetch(
                "SELECT observation_id, source_binding_id, run_id, invocation_ref, handle, "
                "read_observation_ref, retained_ref, expected_digest, observed_digest, readable, "
                f"byte_count, consistency, observed_at FROM {_TABLE} "
                f"WHERE {SCOPE} AND invocation_ref = $4 "
                "ORDER BY observed_at, read_observation_ref",
                *args,
                invocation_ref,
            )
        return [
            RetainedReadObservation(
                observation_id=str(row["observation_id"]),
                source_binding_id=None
                if row["source_binding_id"] is None
                else str(row["source_binding_id"]),
                run_id=str(row["run_id"]),
                invocation_ref=row["invocation_ref"],
                handle=row["handle"],
                read_observation_ref=row["read_observation_ref"],
                retained_ref=row["retained_ref"],
                expected_digest=row["expected_digest"],
                observed_digest=row["observed_digest"],
                readable=row["readable"],
                byte_count=row["byte_count"],
                consistency=mc.load(row["consistency"]),
                observed_at=row["observed_at"],
            )
            for row in rows
        ]


__all__ = ["PostgresRetainedReadStore"]
