"""``KnowledgeJournal`` over ``mission_control.knowledge_operation_journal`` (release 1.5.0).

Admission uses ``mission_control.admit_knowledge_operation(jsonb)``: race-safe per scoped
effect key, ``EFFECT_CONFLICT`` (SQLSTATE MCE01) for the same key with another bound effect.
Every later write is a compare-and-set on ``version``; the ``knowledge_operation_guard``
trigger enforces the legal edges and frozen identity, and
``knowledge_operation_append_transition`` appends one immutable transition per version
(attributed to ``mc.actor_ref``). Every statement runs in an explicit transaction under
transaction-local tenant scope, so forced row security applies. Only coordinates and digests
are written: never credentials or payloads.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import asyncpg

from mission_control.adapters.postgres.run_control import canonical as mc
from mission_control.adapters.postgres.run_control.canonical import SCOPE
from mission_control.adapters.postgres.scope import apply_actor
from mission_control.application.ports.knowledge import (
    JournalRecord,
    JournalVersionConflict,
    PrepareRequest,
    Settlement,
)
from mission_control.contracts.knowledge_protocol import Origin
from mission_control.domain.knowledge.effects import EffectConflict, JournalState

EFFECT_CONFLICT_SQLSTATE = "MCE01"
_TABLE = "mission_control.knowledge_operation_journal"
_OPEN = "('prepared', 'dispatched', 'uncertain')"


def _record(row: asyncpg.Record) -> JournalRecord:
    return JournalRecord(
        knowledge_operation_id=str(row["knowledge_operation_id"]),
        effect_key=row["effect_key"],
        semantic_payload_digest=row["semantic_payload_digest"],
        bound_effect_digest=row["bound_effect_digest"],
        originating_origin=Origin.model_validate(mc.load(row["originating_origin"])),
        current_caller_origin=Origin.model_validate(mc.load(row["current_caller_origin"])),
        capability_pin=row["capability_pin"],
        binding_id=row["binding_id"],
        state=JournalState(row["state"]),
        version=int(row["version"]),
        reconciled=bool(row["reconciled"]),
        dispatch_id=None if row["dispatch_id"] is None else str(row["dispatch_id"]),
        envelope_digest=row["envelope_digest"],
        protocol_version=row["protocol_version"],
        operation_id=row["operation_id"],
        terminal_receipt_ref=row["terminal_receipt_ref"],
        receipt_digest=row["receipt_digest"],
        refusal_code=row["refusal_code"],
        recovery_authority_ref=row["recovery_authority_ref"],
        operation_ref=row["operation_ref"],
        operation_attempt=int(row["operation_attempt"]),
    )


def _origin_json(origin: Origin) -> dict[str, Any]:
    return origin.model_dump(mode="json")


class PostgresKnowledgeJournal:
    """RLS-scoped knowledge operation journal for one runtime-role pool."""

    def __init__(
        self, pool: asyncpg.Pool, *, actor_ref: str = "mission-control:knowledge-gateway"
    ) -> None:
        self._pool = pool
        self._actor_ref = actor_ref

    async def prepare(self, request: PrepareRequest) -> JournalRecord:
        now = datetime.now(UTC).isoformat()
        coordinates = request.coordinates
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, request.scope)
            await apply_actor(connection, request.actor_ref)
            candidate = {
                "installation_id": str(args[0]),
                "application_id": args[1],
                "tenant_id": str(args[2]),
                "knowledge_operation_id": str(uuid4()),
                "effect_key": request.effect_key,
                "semantic_payload_digest": request.semantic_payload_digest,
                "bound_effect_digest": request.bound_effect_digest,
                "originating_origin": _origin_json(request.originating_origin),
                "current_caller_origin": _origin_json(request.current_caller_origin),
                "mission_id": coordinates.mission_id,
                "run_id": coordinates.run_id,
                "activation_id": coordinates.activation_id,
                "operation_ref": coordinates.operation_ref,
                "operation_attempt": coordinates.operation_attempt,
                "execution_generation": coordinates.execution_generation,
                "unit_key": coordinates.unit_key,
                "lane_profile": coordinates.lane_profile,
                "capability_pin": request.capability_pin,
                "binding_id": request.binding_id,
                "state": JournalState.PREPARED.value,
                "reconciled": False,
                "version": 1,
                "prepared_at": now,
                "updated_at": now,
                "created_at": now,
                "created_by_actor_ref": request.actor_ref,
            }
            try:
                row = await connection.fetchrow(
                    "SELECT * FROM mission_control.admit_knowledge_operation($1::jsonb)",
                    json.dumps(candidate),
                )
            except asyncpg.PostgresError as error:
                if getattr(error, "sqlstate", None) == EFFECT_CONFLICT_SQLSTATE:
                    raise EffectConflict(f"EFFECT_CONFLICT {request.effect_key}") from None
                raise
        return _record(row)

    async def lookup(self, scope: str, effect_key: str) -> JournalRecord | None:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            row = await connection.fetchrow(
                f"SELECT * FROM {_TABLE} WHERE {SCOPE} AND effect_key = $4", *args, effect_key
            )
        return None if row is None else _record(row)

    async def open_for_attempt(
        self, scope: str, *, run_id: str, operation_ref: str, operation_attempt: int
    ) -> list[JournalRecord]:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            rows = await connection.fetch(
                f"SELECT * FROM {_TABLE} WHERE {SCOPE} AND run_id = $4::uuid "
                f"AND operation_ref = $5 AND operation_attempt = $6 AND state IN {_OPEN} "
                "ORDER BY effect_key",
                *args,
                run_id,
                operation_ref,
                operation_attempt,
            )
        return [_record(row) for row in rows]

    async def open_for_operation(
        self, scope: str, *, run_id: str, operation_ref: str
    ) -> list[JournalRecord]:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            rows = await connection.fetch(
                f"SELECT * FROM {_TABLE} WHERE {SCOPE} AND run_id = $4::uuid "
                f"AND operation_ref = $5 AND state IN {_OPEN} "
                "ORDER BY operation_attempt, effect_key",
                *args,
                run_id,
                operation_ref,
            )
        return [_record(row) for row in rows]

    async def dispatch(
        self,
        scope: str,
        effect_key: str,
        *,
        expected_version: int,
        dispatch_id: str,
        envelope_digest: str,
        protocol_version: str,
        caller: Origin,
        at: datetime,
        recovery_authority_ref: str | None = None,
    ) -> JournalRecord:
        return await self._update(
            scope,
            effect_key,
            expected_version,
            "state = 'dispatched', dispatch_id = $6::uuid, envelope_digest = $7, "
            "protocol_version = $8, current_caller_origin = $9::jsonb, dispatched_at = $10, "
            "recovery_authority_ref = $11",
            "state IN ('prepared', 'uncertain')",
            (
                dispatch_id,
                envelope_digest,
                protocol_version,
                json.dumps(_origin_json(caller)),
                at,
                recovery_authority_ref,
            ),
            at,
        )

    async def record_handle(
        self, scope: str, effect_key: str, *, expected_version: int, operation_id: str, at: datetime
    ) -> JournalRecord:
        return await self._update(
            scope,
            effect_key,
            expected_version,
            "operation_id = $6",
            f"state IN {_OPEN}",
            (operation_id,),
            at,
        )

    async def settle(
        self,
        scope: str,
        effect_key: str,
        *,
        expected_version: int,
        settlement: Settlement,
        at: datetime,
    ) -> JournalRecord:
        return await self._update(
            scope,
            effect_key,
            expected_version,
            "state = $6, terminal_receipt_ref = $7, receipt_digest = $8, refusal_code = $9, "
            "reconciled = $10, settled_at = GREATEST($11::timestamptz, updated_at)",
            f"state IN {_OPEN}",
            (
                settlement.state.value,
                settlement.terminal_receipt_ref,
                settlement.receipt_digest,
                settlement.refusal_code,
                settlement.reconciled,
                at,
            ),
            at,
        )

    async def mark_uncertain(
        self, scope: str, effect_key: str, *, expected_version: int, at: datetime
    ) -> JournalRecord:
        return await self._update(
            scope,
            effect_key,
            expected_version,
            "state = 'uncertain'",
            "state = 'dispatched'",
            (),
            at,
        )

    async def transitions(
        self, scope: str, effect_key: str
    ) -> list[tuple[JournalState | None, JournalState]]:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            rows = await connection.fetch(
                "SELECT transition.from_state, transition.to_state "
                "FROM mission_control.knowledge_operation_transition transition "
                f"JOIN {_TABLE} journal USING "
                "(installation_id, application_id, tenant_id, knowledge_operation_id) "
                "WHERE journal.installation_id = $1 AND journal.application_id = $2 "
                "AND journal.tenant_id = $3 AND journal.effect_key = $4 "
                "ORDER BY transition.transition_version",
                *args,
                effect_key,
            )
        return [
            (
                None if row["from_state"] is None else JournalState(row["from_state"]),
                JournalState(row["to_state"]),
            )
            for row in rows
        ]

    async def _update(
        self,
        scope: str,
        effect_key: str,
        expected_version: int,
        assignments: str,
        state_guard: str,
        values: tuple[Any, ...],
        at: datetime,
    ) -> JournalRecord:
        # $1..$3 scope, $4 effect key, $5 expected version, $6.. assignment values, last: at.
        at_param = 6 + len(values)
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            await apply_actor(connection, self._actor_ref)
            row = await connection.fetchrow(
                f"UPDATE {_TABLE} SET {assignments}, version = version + 1, "
                f"updated_at = GREATEST(${at_param}::timestamptz, updated_at) "
                f"WHERE {SCOPE} AND effect_key = $4 AND version = $5 AND {state_guard} "
                "RETURNING *",
                *args,
                effect_key,
                expected_version,
                *values,
                at,
            )
        if row is None:
            raise JournalVersionConflict(f"knowledge operation {effect_key} moved on")
        return _record(row)


__all__ = ["EFFECT_CONFLICT_SQLSTATE", "PostgresKnowledgeJournal"]
