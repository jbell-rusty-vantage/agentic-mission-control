"""``KnowledgeHandleStore`` over ``mission_control.knowledge_operation_handle`` (release 1.6.0).

One row per remote handle (scope, binding, remote operation id), idempotent per request id.
``observe`` locks the row and applies a remote status only when its revision is newer and the
K01 state is forward-reachable (``knowledge_operation_handle_guard`` enforces the same rules,
so a stale poll never regresses a handle). ``request_cancel`` stores only the first cancel
request id. Every statement runs in an explicit transaction under transaction-local tenant
scope; only coordinates, references and digests are written, never credentials.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import uuid4

import asyncpg

from mission_control.adapters.postgres.run_control import canonical as mc
from mission_control.adapters.postgres.run_control.canonical import SCOPE
from mission_control.adapters.postgres.scope import apply_actor
from mission_control.application.ports.knowledge import HandleCandidate, HandleRecord
from mission_control.contracts.knowledge_protocol import (
    TERMINAL_STATES,
    OperationHandle,
    Origin,
    Ref,
    can_reach,
)
from mission_control.contracts.knowledge_protocol_results import OperationStatus

_TABLE = "mission_control.knowledge_operation_handle"
_OPEN = "('queued', 'running', 'waiting_review', 'cancelling')"


def _record(row: asyncpg.Record) -> HandleRecord:
    result = mc.load(row["result_ref"]) if row["result_ref"] is not None else None
    effects = mc.load(row["unresolved_effects"])
    return HandleRecord(
        handle_id=str(row["handle_id"]),
        binding_id=row["binding_id"],
        operation=row["operation"],
        request_id=row["request_id"],
        handle=OperationHandle.model_validate(mc.load(row["handle"])),
        invocation_ref=row["invocation_ref"],
        caller_origin=Origin.model_validate(mc.load(row["caller_origin"])),
        state=row["state"],
        remote_revision=int(row["remote_revision"]),
        version=int(row["version"]),
        effect_key=row["effect_key"],
        subject_ref=row["subject_ref"],
        cancel_request_id=row["cancel_request_id"],
        pending_review_ref=row["pending_review_ref"],
        result_ref=None if result is None else Ref.model_validate(result),
        error_code=row["error_code"],
        unresolved_effects=tuple(effects),
    )


class PostgresKnowledgeHandleStore:
    """RLS-scoped durable knowledge handles for one runtime-role pool."""

    def __init__(
        self, pool: asyncpg.Pool, *, actor_ref: str = "mission-control:knowledge-gateway"
    ) -> None:
        self._pool = pool
        self._actor_ref = actor_ref

    async def record(self, candidate: HandleCandidate) -> HandleRecord:
        coordinates = candidate.coordinates
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, candidate.scope)
            await apply_actor(connection, candidate.actor_ref)
            row = await connection.fetchrow(
                f"INSERT INTO {_TABLE} (installation_id, application_id, tenant_id, handle_id, "
                "binding_id, operation, request_id, remote_operation_id, protocol_version, "
                "handle, effect_key, subject_ref, mission_id, run_id, activation_id, "
                "operation_ref, operation_attempt, execution_generation, unit_key, "
                "lane_profile, invocation_ref, caller_origin, state, remote_revision, "
                "unresolved_effects, version, recorded_at, updated_at, created_at, "
                "created_by_actor_ref) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, "
                "$10::jsonb, $11, $12, $13::uuid, $14::uuid, $15::uuid, $16, $17, $18, $19, "
                "$20, $21, $22::jsonb, 'queued', 0, '[]'::jsonb, 1, $23, $23, $23, $24) "
                "ON CONFLICT DO NOTHING RETURNING *",
                *args,
                uuid4(),
                candidate.binding_id,
                candidate.operation,
                candidate.request_id,
                candidate.handle.operationId,
                candidate.handle.protocolVersion,
                json.dumps(candidate.handle.model_dump(mode="json")),
                candidate.effect_key,
                candidate.subject_ref,
                coordinates.mission_id,
                coordinates.run_id,
                coordinates.activation_id,
                coordinates.operation_ref,
                coordinates.operation_attempt,
                coordinates.execution_generation,
                coordinates.unit_key,
                coordinates.lane_profile,
                candidate.invocation_ref,
                json.dumps(candidate.caller_origin.model_dump(mode="json")),
                candidate.at,
                candidate.actor_ref,
            )
            if row is None:
                row = await connection.fetchrow(
                    f"SELECT * FROM {_TABLE} WHERE {SCOPE} AND binding_id = $4 "
                    "AND (remote_operation_id = $5 OR (operation = $6 AND request_id = $7))",
                    *args,
                    candidate.binding_id,
                    candidate.handle.operationId,
                    candidate.operation,
                    candidate.request_id,
                )
        if row is None:  # pragma: no cover - the conflicting row is visible in this scope
            raise RuntimeError(f"knowledge handle {candidate.handle.operationId} is not visible")
        return _record(row)

    async def get(self, scope: str, binding_id: str, operation_id: str) -> HandleRecord | None:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            row = await connection.fetchrow(
                f"SELECT * FROM {_TABLE} WHERE {SCOPE} AND binding_id = $4 "
                "AND remote_operation_id = $5",
                *args,
                binding_id,
                operation_id,
            )
        return None if row is None else _record(row)

    async def observe(
        self, scope: str, binding_id: str, status: OperationStatus, *, at: datetime
    ) -> HandleRecord:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            await apply_actor(connection, self._actor_ref)
            current = await connection.fetchrow(
                f"SELECT * FROM {_TABLE} WHERE {SCOPE} AND binding_id = $4 "
                "AND remote_operation_id = $5 FOR UPDATE",
                *args,
                binding_id,
                status.handle.operationId,
            )
            if current is None:
                raise LookupError(f"no knowledge handle {status.handle.operationId}")
            stale = (
                current["state"] in TERMINAL_STATES
                or status.revision <= int(current["remote_revision"])
                or (
                    status.state != current["state"]
                    and not can_reach(current["state"], status.state)
                )
            )
            if stale:
                return _record(current)
            values: dict[str, Any] = {
                "state": status.state,
                "revision": status.revision,
                "cancel": status.cancelRequestId,
                "review": None if status.pendingReviewRef is None else status.pendingReviewRef.id,
                "result": None
                if status.resultRef is None
                else json.dumps(status.resultRef.model_dump(mode="json")),
                "error": None if status.error is None else status.error.code,
                "effects": json.dumps(
                    [effect.model_dump(mode="json") for effect in status.unresolvedEffects]
                ),
            }
            row = await connection.fetchrow(
                f"UPDATE {_TABLE} SET state = $6, remote_revision = $7, "
                "cancel_request_id = COALESCE(cancel_request_id, $8), pending_review_ref = $9, "
                "result_ref = $10::jsonb, error_code = $11, unresolved_effects = $12::jsonb, "
                "version = version + 1, updated_at = GREATEST($13::timestamptz, updated_at) "
                f"WHERE {SCOPE} AND binding_id = $4 AND remote_operation_id = $5 RETURNING *",
                *args,
                binding_id,
                status.handle.operationId,
                values["state"],
                values["revision"],
                values["cancel"],
                values["review"],
                values["result"],
                values["error"],
                values["effects"],
                at,
            )
        assert row is not None
        return _record(row)

    async def request_cancel(
        self,
        scope: str,
        binding_id: str,
        operation_id: str,
        cancel_request_id: str,
        *,
        at: datetime,
    ) -> HandleRecord:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            await apply_actor(connection, self._actor_ref)
            row = await connection.fetchrow(
                f"UPDATE {_TABLE} SET cancel_request_id = $6, version = version + 1, "
                "updated_at = GREATEST($7::timestamptz, updated_at) "
                f"WHERE {SCOPE} AND binding_id = $4 AND remote_operation_id = $5 "
                f"AND cancel_request_id IS NULL AND state IN {_OPEN} RETURNING *",
                *args,
                binding_id,
                operation_id,
                cancel_request_id,
                at,
            )
            if row is None:
                row = await connection.fetchrow(
                    f"SELECT * FROM {_TABLE} WHERE {SCOPE} AND binding_id = $4 "
                    "AND remote_operation_id = $5",
                    *args,
                    binding_id,
                    operation_id,
                )
        if row is None:
            raise LookupError(f"no knowledge handle {operation_id}")
        return _record(row)

    async def open_for_run(self, scope: str, run_id: str) -> list[HandleRecord]:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            rows = await connection.fetch(
                f"SELECT * FROM {_TABLE} WHERE {SCOPE} AND run_id = $4::uuid "
                f"AND state IN {_OPEN} ORDER BY recorded_at, remote_operation_id",
                *args,
                run_id,
            )
        return [_record(row) for row in rows]

    async def open_for_invocation(self, scope: str, invocation_ref: str) -> list[HandleRecord]:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            rows = await connection.fetch(
                f"SELECT * FROM {_TABLE} WHERE {SCOPE} AND invocation_ref = $4 "
                f"AND state IN {_OPEN} ORDER BY recorded_at, remote_operation_id",
                *args,
                invocation_ref,
            )
        return [_record(row) for row in rows]


__all__ = ["PostgresKnowledgeHandleStore"]
