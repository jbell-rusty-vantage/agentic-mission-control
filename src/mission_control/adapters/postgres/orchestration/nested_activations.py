"""``mission_control.nested_activation``: durable lineage of recursive composition (OVE-176).

One row per parent unit attempt, written once at activation and settled once with the export
receipt (the table's trigger refuses every other change). ``record`` is idempotent: the same
activation returns the stored row; another child for the same unit attempt (or another
activation of the same child) refuses with ``NestedActivationConflict``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import asyncpg

from mission_control.adapters.postgres.run_control import canonical as mc
from mission_control.application.programs.nested_bodies import (
    NestedActivationConflict,
    NestedActivationRecord,
)

_TABLE = "mission_control.nested_activation"
_SCOPE = "installation_id = $1 AND application_id = $2 AND tenant_id = $3"
WRITER_REF = "mission-control-runtime/nested-activations"


def _record(request_scope: str, row: asyncpg.Record) -> NestedActivationRecord:
    receipt = mc.load(row["receipt"]) if row["receipt"] is not None else None
    return NestedActivationRecord(
        request_scope=request_scope,
        parent_run_id=row["parent_run_key"],
        host_id=row["host_id"],
        semantic_attempt_id=row["semantic_attempt_id"],
        position=row["position"],
        family=row["family"],
        depth=row["depth"],
        child_run_id=row["child_run_key"],
        budget_ceiling={str(k): int(v) for k, v in dict(mc.load(row["budget_ceiling"])).items()},
        body_digest=row["body_digest"],
        activated_at=row["activated_at"],
        receipt=receipt if isinstance(receipt, dict) else None,
        settled_at=row["settled_at"],
    )


class PostgresNestedActivationStore:
    def __init__(self, pool: asyncpg.Pool, *, actor_ref: str = WRITER_REF) -> None:
        self._pool = pool
        self._actor = actor_ref

    async def get(
        self, scope: str, parent_run_id: str, host_id: str, semantic_attempt_id: str
    ) -> NestedActivationRecord | None:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            row = await connection.fetchrow(
                f"SELECT * FROM {_TABLE} WHERE {_SCOPE} AND parent_run_key = $4 "
                "AND host_id = $5 AND semantic_attempt_id = $6",
                *args,
                parent_run_id,
                host_id,
                semantic_attempt_id,
            )
        return None if row is None else _record(scope, row)

    async def record(self, record: NestedActivationRecord) -> NestedActivationRecord:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, record.request_scope)
            row = await connection.fetchrow(
                f"""
                INSERT INTO {_TABLE} (
                    installation_id, application_id, tenant_id, parent_run_key, host_id,
                    semantic_attempt_id, position, family, depth, child_run_key, budget_ceiling,
                    body_digest, activated_at, created_at, created_by_actor_ref
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb, $12, $13, $13, $14)
                ON CONFLICT DO NOTHING
                RETURNING *
                """,
                *args,
                record.parent_run_id,
                record.host_id,
                record.semantic_attempt_id,
                record.position,
                record.family,
                record.depth,
                record.child_run_id,
                mc.dump(dict(sorted(record.budget_ceiling.items()))),
                record.body_digest,
                record.activated_at,
                self._actor,
            )
            if row is not None:
                return _record(record.request_scope, row)
            prior = await connection.fetchrow(
                f"SELECT * FROM {_TABLE} WHERE {_SCOPE} AND ((parent_run_key = $4 "
                "AND host_id = $5 AND semantic_attempt_id = $6) OR child_run_key = $7)",
                *args,
                record.parent_run_id,
                record.host_id,
                record.semantic_attempt_id,
                record.child_run_id,
            )
        if prior is None:
            raise NestedActivationConflict("the nested activation could not be recorded")
        stored = _record(record.request_scope, prior)
        if (
            stored.parent_run_id,
            stored.host_id,
            stored.semantic_attempt_id,
            stored.child_run_id,
            stored.body_digest,
        ) != (
            record.parent_run_id,
            record.host_id,
            record.semantic_attempt_id,
            record.child_run_id,
            record.body_digest,
        ):
            raise NestedActivationConflict("the unit attempt or child run activated differently")
        return stored

    async def settle(
        self,
        scope: str,
        child_run_id: str,
        receipt: dict[str, object],
        settled_at: datetime,
    ) -> NestedActivationRecord:
        digest = str(receipt.get("receipt_digest", ""))
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            row = await connection.fetchrow(
                f"SELECT * FROM {_TABLE} WHERE {_SCOPE} AND child_run_key = $4 FOR UPDATE",
                *args,
                child_run_id,
            )
            if row is None:
                raise LookupError(f"no nested activation for child run {child_run_id}")
            if row["receipt"] is not None:
                if row["receipt_digest"] != digest:
                    raise NestedActivationConflict("the activation settled differently")
                return _record(scope, row)
            updated = await connection.fetchrow(
                f"UPDATE {_TABLE} SET receipt = $5::jsonb, receipt_digest = $6, settled_at = $7 "
                f"WHERE {_SCOPE} AND child_run_key = $4 RETURNING *",
                *args,
                child_run_id,
                mc.dump(receipt),
                digest,
                settled_at,
            )
        assert updated is not None
        return _record(scope, updated)

    async def by_child(self, scope: str, child_run_id: str) -> NestedActivationRecord | None:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            row = await connection.fetchrow(
                f"SELECT * FROM {_TABLE} WHERE {_SCOPE} AND child_run_key = $4",
                *args,
                child_run_id,
            )
        return None if row is None else _record(scope, row)

    async def for_parent(
        self, scope: str, parent_run_id: str
    ) -> tuple[NestedActivationRecord, ...]:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            rows: list[Any] = await connection.fetch(
                f"SELECT * FROM {_TABLE} WHERE {_SCOPE} AND parent_run_key = $4 "
                "ORDER BY activated_at, host_id, semantic_attempt_id",
                *args,
                parent_run_id,
            )
        return tuple(_record(scope, row) for row in rows)


__all__ = ["PostgresNestedActivationStore"]
