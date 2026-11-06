"""``InvocationSettlementStore`` over the 1.7.0 ``invocation_settlement`` table (0058; WI-04).

One row per bound operation attempt whose cognition completed: the saved ``RuntimeResult``
(immutable, digest-bound) and its settlement state, advanced by compare-and-set on
``version``. A second save of the same bytes returns the stored row; other bytes for the same
binding are an ``IdempotencyConflict``. The table's guard enforces the same successor rules as
the domain (identity and bytes immutable, ``settled`` terminal, monotonic claim fence, stop
fence never lifted); a lost CAS is :class:`SavedSettlementConflict`.

Live fence (WI-04 review): every advance takes the unit's advisory lock (the lineage
repository's) and, in the same transaction, compares the writer's claim fence with the unit
generation's current ``attempt.fencing_token``: a holder fenced out by a takeover is
:class:`StaleSettlementHolder` even before the new holder writes. A unit generation with no
attempt row is refused too (``require_unit_generation``; only a proof whose lineage is not
in PostgreSQL turns it off). ``record_event`` appends one durable settlement event once.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import asyncpg

from mission_control.adapters.postgres.operations.checkpoint_lineage import attempt_key
from mission_control.adapters.postgres.run_control import canonical as mc
from mission_control.adapters.postgres.run_control.canonical import SCOPE
from mission_control.adapters.postgres.scope import apply_actor
from mission_control.application.execution.operations.invocation_settlement import (
    MAX_SAVED_RESULT_BYTES,
    SavedResultTooLarge,
    SavedSettlementConflict,
    SettlementEvent,
    StaleSettlementHolder,
)
from mission_control.domain.execution.invocation_settlement import InvocationSettlement
from mission_control.domain.policies.errors import IdempotencyConflict

_TABLE = "mission_control.invocation_settlement"
_EVENT = "mission_control.invocation_settlement_event"


def _document(record: InvocationSettlement) -> dict[str, Any]:
    """The record document without the saved bytes (they live once, in ``saved_result``)."""

    return record.model_dump(mode="json", exclude={"saved_result"})


def _load(value: object) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _record(row: asyncpg.Record) -> InvocationSettlement:
    return InvocationSettlement.model_validate(
        {**_load(row["record"]), "saved_result": _load(row["saved_result"])}
    )


class PostgresInvocationSettlementStore:
    """RLS-scoped saved results and their settlement state for one runtime-role pool."""

    def __init__(
        self,
        pool: asyncpg.Pool,
        *,
        actor_ref: str = "mission-control:saved-settlement",
        require_unit_generation: bool = True,
    ) -> None:
        self._pool = pool
        self._actor_ref = actor_ref
        self._require_unit_generation = require_unit_generation

    async def save(self, record: InvocationSettlement) -> InvocationSettlement:
        document = _document(record)
        saved = json.dumps(
            record.saved_result.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        )
        size = len(saved.encode("utf-8"))
        if size > MAX_SAVED_RESULT_BYTES:
            raise SavedResultTooLarge(f"saved result is {size} bytes, over the bound")
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, record.request_scope)
            await apply_actor(connection, self._actor_ref)
            row = await connection.fetchrow(
                f"INSERT INTO {_TABLE} (installation_id, application_id, tenant_id, "
                "settlement_id, run_id, binding_id, operation_ref, operation_attempt, unit_key, "
                "execution_generation, saved_result, saved_result_digest, "
                "saved_result_size_bytes, execution_outcome, settlement, reason, "
                "pending_reviews, pending_effects, fulfillment_refs, finalization_ref, "
                "recovery_owner, next_action, claim_fence, stop_fence, waits, version, record, "
                "saved_at, updated_at, settled_at, created_by_actor_ref) VALUES "
                "($1, $2, $3, $4, $5::uuid, $6, $7, $8, $9, $10, $11::jsonb, $12, $13, $14, $15, "
                "$16, $17, $18, $19, $20, $21, $22, $23, $24, $25, $26, $27::jsonb, $28, $29, "
                "$30, $31) ON CONFLICT DO NOTHING RETURNING record, saved_result",
                *args,
                UUID(record.settlement_id),
                record.run_id,
                record.binding_id,
                record.operation_ref,
                record.operation_attempt,
                record.unit_key,
                record.execution_generation,
                saved,
                record.saved_result_digest,
                size,
                record.execution_outcome,
                record.settlement.value,
                None if record.reason is None else record.reason.value,
                list(record.pending_reviews),
                list(record.pending_effects),
                list(record.fulfillment_refs),
                record.finalization_ref,
                record.recovery_owner,
                record.next_action,
                record.claim_fence,
                record.stop_fence,
                record.waits,
                record.version,
                json.dumps(document, sort_keys=True),
                record.saved_at,
                record.updated_at,
                record.settled_at,
                self._actor_ref,
            )
            if row is None:
                row = await connection.fetchrow(
                    f"SELECT record, saved_result FROM {_TABLE} WHERE {SCOPE} AND binding_id = $4",
                    *args,
                    record.binding_id,
                )
        if row is None:  # pragma: no cover - the unique row is visible in this scope
            raise RuntimeError(f"saved result of {record.binding_id} is not visible")
        stored = _record(row)
        if stored.saved_result_digest != record.saved_result_digest:
            raise IdempotencyConflict("the binding already saved another provider result")
        return stored

    async def get(self, request_scope: str, binding_id: str) -> InvocationSettlement | None:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, request_scope)
            row = await connection.fetchrow(
                f"SELECT record, saved_result FROM {_TABLE} WHERE {SCOPE} AND binding_id = $4",
                *args,
                binding_id,
            )
        return None if row is None else _record(row)

    async def advance(
        self, record: InvocationSettlement, *, expected_version: int
    ) -> InvocationSettlement:
        document = _document(record)
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, record.request_scope)
            await apply_actor(connection, self._actor_ref)
            # The lineage repository's unit lock: a takeover cannot interleave with this write.
            await mc.advisory_lock(
                connection,
                f"mission-control-runtime-unit:{record.request_scope}:{record.unit_key}",
            )
            current = await connection.fetchval(
                f"SELECT fencing_token FROM mission_control.attempt WHERE {SCOPE} "
                "AND attempt_key = $4",
                *args,
                attempt_key(record.unit_key, record.execution_generation),
            )
            if (current is None and self._require_unit_generation) or (
                current is not None and int(current) != record.claim_fence
            ):
                raise StaleSettlementHolder(
                    "the writer's claim fence is not the unit generation's current fence"
                )
            row = await connection.fetchrow(
                f"UPDATE {_TABLE} SET settlement = $6, reason = $7, pending_reviews = $8, "
                "pending_effects = $9, fulfillment_refs = $10, finalization_ref = $11, "
                "recovery_owner = $12, next_action = $13, claim_fence = $14, stop_fence = $15, "
                "waits = $16, version = $17, record = $18::jsonb, updated_at = $19, "
                f"settled_at = $20 WHERE {SCOPE} AND binding_id = $4 AND version = $5 "
                "RETURNING record, saved_result",
                *args,
                record.binding_id,
                expected_version,
                record.settlement.value,
                None if record.reason is None else record.reason.value,
                list(record.pending_reviews),
                list(record.pending_effects),
                list(record.fulfillment_refs),
                record.finalization_ref,
                record.recovery_owner,
                record.next_action,
                record.claim_fence,
                record.stop_fence,
                record.waits,
                record.version,
                json.dumps(document, sort_keys=True),
                record.updated_at,
                record.settled_at,
            )
        if row is None:
            raise SavedSettlementConflict("the saved result moved since it was read")
        return _record(row)

    async def record_event(self, record: InvocationSettlement, event: SettlementEvent) -> bool:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, record.request_scope)
            await apply_actor(connection, self._actor_ref)
            inserted = await connection.fetchval(
                f"INSERT INTO {_EVENT} (installation_id, application_id, tenant_id, "
                "settlement_id, kind, sequence, occurred_at, detail, created_by_actor_ref) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9) ON CONFLICT DO NOTHING "
                "RETURNING true",
                *args,
                UUID(event.settlement_id),
                event.kind,
                event.sequence,
                event.occurred_at,
                json.dumps(dict(event.detail), sort_keys=True),
                self._actor_ref,
            )
        return bool(inserted)


__all__ = ["PostgresInvocationSettlementStore"]
