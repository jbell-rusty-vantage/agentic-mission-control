"""PostgreSQL `LaneExecutionStateStore` over `mission_control.harness_execution` (FT-G2).

The row is opened by the frame store (migration 0027) before any lane write; this store
updates the lane columns of migration 0030 (G2 section) under forced RLS. The native
session and turn are written once: a later write naming another value is refused inside
the same row lock, so a resumed segment can never re-point an attempt at another agent.

MP-06: the session owner and the dispatch journal live in the existing `native_identity`
jsonb (runtime UPDATE grant of 0027) under `mc_session_owner` and `mc_dispatch`; they are
merged with `||` under the same `FOR UPDATE` row lock the frame append takes, so a frame
writer's read-modify-write of its own keys and these writes serialize and keep each other.
No new column: the dedicated columns/table are a proposed 0032+ delta (MP-06 handoff).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import asyncpg

from mission_control.adapters.postgres.run_control.canonical import SCOPE, begin
from mission_control.application.execution.harness.dispatch import (
    DispatchClaim,
    DispatchKind,
    DispatchOutcome,
    DispatchRecord,
    SessionOwner,
    assert_holder,
    claim_ownership,
    dispatch_key,
    intend,
    renew_ownership,
    resolve,
)
from mission_control.application.execution.harness.state import (
    LaneExecutionState,
    LaneExecutionUpdate,
    acknowledge_history_state,
    close_history_window_state,
    enqueue_budget_control,
    merge_state,
    reject_history_state,
    request_history_state,
    validate_budget_update,
)
from mission_control.domain.execution.budget_controls import BudgetControlRecord
from mission_control.domain.execution.history_reconciliation import HistoryJournal, HistoryRequest

_COLUMNS = (
    "native_session_ref",
    "native_turn_ref",
    "provider_cursor",
    "usage_disposition",
    "last_segment_at",
    "cursor_sdk_version",
    "bridge_state_root",
    "cloud_branch",
    "cloud_agent_url",
)
OWNER_KEY = "mc_session_owner"
DISPATCH_KEY = "mc_dispatch"
BUDGET_CONTROL_KEY = "mc_budget_controls"
HISTORY_KEY = "mc_history_reconciliation"
HISTORY_CLOSED_KEY = "mc_history_closed_turn"


class HarnessExecutionNotOpened(LookupError):
    """The harness execution row does not exist yet (the frame store opens it)."""


def _identity(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    return dict(value) if isinstance(value, Mapping) else {}


def _owner(identity: Mapping[str, Any]) -> SessionOwner | None:
    raw = identity.get(OWNER_KEY)
    return SessionOwner.model_validate(raw) if isinstance(raw, Mapping) else None


def _dispatches(identity: Mapping[str, Any]) -> dict[str, DispatchRecord]:
    raw = identity.get(DISPATCH_KEY)
    if not isinstance(raw, Mapping):
        return {}
    return {key: DispatchRecord.model_validate(value) for key, value in raw.items()}


def _state(harness_execution_id: UUID, row: asyncpg.Record) -> LaneExecutionState:
    identity = _identity(row["native_identity"])
    return LaneExecutionState(
        harness_execution_id=harness_execution_id,
        owner=_owner(identity),
        history_closed_turn=identity.get(HISTORY_CLOSED_KEY),
        history_reconciliation=HistoryJournal.model_validate(identity[HISTORY_KEY])
        if identity.get(HISTORY_KEY) is not None
        else None,
        dispatches=_dispatches(identity),
        budget_controls={
            key: BudgetControlRecord.model_validate(value)
            for key, value in identity.get(BUDGET_CONTROL_KEY, {}).items()
        },
        **{name: row[name] for name in _COLUMNS},
    )


class PostgresLaneExecutionStateStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def refresh_history_authority(
        self, request: HistoryRequest, *, owner: SessionOwner, at: datetime
    ) -> HistoryJournal:
        async with self._pool.acquire() as connection, connection.transaction():
            args, row = await self._locked(
                connection, request.request_scope, request.harness_execution_id
            )
            state = _state(request.harness_execution_id, row)
            if row["generation"] != owner.generation or row["lifecycle"] != "live":
                raise ValueError("history authority execution is no longer live")
            rejected = reject_history_state(state, request, owner=owner, at=at)
            journal = state.history_reconciliation
            assert journal is not None
            if journal.covers(request) or journal.rejects(request):
                return journal
            if await self._lock_live_history_binding(connection, args, request):
                return journal
            await self._merge_identity(
                connection,
                args,
                request.harness_execution_id,
                {HISTORY_KEY: rejected.model_dump(mode="json")},
            )
            return rejected

    async def close_history_window(
        self,
        request_scope: str,
        harness_execution_id: UUID,
        *,
        owner: SessionOwner,
        native_turn_ref: str,
    ) -> None:
        async with self._pool.acquire() as connection, connection.transaction():
            args, row = await self._locked(connection, request_scope, harness_execution_id)
            # Loop iter-3 F2: the turn's own `run_result` frame, persisted while the turn was
            # pumped, already set this generation's execution `ended` (frames/identity.py), so
            # a hosted (history-reconciliation) lane's close always met `ended`. Closing the
            # holder's own turn window of the same generation stays valid after that; another
            # generation or any other lifecycle is still refused.
            if row["generation"] != owner.generation or row["lifecycle"] not in {"live", "ended"}:
                raise ValueError(
                    "history close execution is no longer live "
                    f"(row generation {row['generation']}, lifecycle {row['lifecycle']}; "
                    f"owner generation {owner.generation})"
                )
            state = close_history_window_state(
                _state(harness_execution_id, row),
                owner=owner,
                native_turn_ref=native_turn_ref,
            )
            await self._merge_identity(
                connection,
                args,
                harness_execution_id,
                {HISTORY_CLOSED_KEY: state.history_closed_turn},
            )

    async def request_history(self, request: HistoryRequest) -> HistoryJournal:
        async with self._pool.acquire() as connection, connection.transaction():
            args, row = await self._locked(
                connection, request.request_scope, request.harness_execution_id
            )
            state = _state(request.harness_execution_id, row)
            if state.history_reconciliation is not None and state.history_reconciliation.covers(
                request
            ):
                return state.history_reconciliation
            if not await self._lock_live_history_binding(connection, args, request):
                raise ValueError("history request binding is no longer live")
            journal = request_history_state(state, request)
            await self._merge_identity(
                connection,
                args,
                request.harness_execution_id,
                {HISTORY_KEY: journal.model_dump(mode="json")},
            )
            return journal

    async def acknowledge_history(
        self, request: HistoryRequest, *, owner: SessionOwner, cursor: str | None, at: datetime
    ) -> HistoryJournal:
        async with self._pool.acquire() as connection, connection.transaction():
            args, row = await self._locked(
                connection, request.request_scope, request.harness_execution_id
            )
            state = _state(request.harness_execution_id, row)
            if row["generation"] != request.generation or row["lifecycle"] != "live":
                raise ValueError("history acknowledgment execution is no longer live")
            journal = acknowledge_history_state(state, request, owner=owner, cursor=cursor, at=at)
            if state.history_reconciliation is not None and state.history_reconciliation.covers(
                request
            ):
                return journal  # existing proof is immutable across later binding revocation
            if state.history_reconciliation is not None and state.history_reconciliation.rejects(
                request
            ):
                return state.history_reconciliation
            if not await self._lock_live_history_binding(connection, args, request):
                journal = reject_history_state(state, request, owner=owner, at=at)
            await self._merge_identity(
                connection,
                args,
                request.harness_execution_id,
                {HISTORY_KEY: journal.model_dump(mode="json")},
            )
            return journal

    @staticmethod
    async def _lock_live_history_binding(
        connection: asyncpg.Connection, args: tuple[Any, ...], request: HistoryRequest
    ) -> bool:
        # The caller holds the execution row first. SHARE serializes both request and
        # new acknowledgment with binding revocation; no provider I/O holds these locks.
        bound = await connection.fetchval(
            """SELECT b.revoked_at IS NULL AND b.expires_at>clock_timestamp()
            FROM mission_control.ingress_session_binding b
            JOIN mission_control.harness_execution h
              ON h.installation_id=b.installation_id AND h.application_id=b.application_id
             AND h.tenant_id=b.tenant_id
            WHERE b.installation_id=$1 AND b.application_id=$2 AND b.tenant_id=$3
              AND b.session_binding_id=$4 AND b.run_key=$5 AND b.generation=$6
              AND b.session_id=$7
              AND h.harness_execution_id=$8 AND h.generation=$6 AND h.lifecycle='live'
              AND b.context->>'harness_execution_id'=$8::text
              AND b.context->>'operation_workflow_id'=$9
              AND b.context->>'product'=$10
            FOR SHARE OF b""",
            *args,
            request.session_binding_id,
            request.run_id,
            request.generation,
            request.native_session_ref,
            request.harness_execution_id,
            request.workflow_id,
            request.lane_profile,
        )
        return bound is True

    async def enqueue_budget_control(self, record: BudgetControlRecord) -> BudgetControlRecord:
        async with self._pool.acquire() as connection, connection.transaction():
            args, row = await self._locked(
                connection, record.request_scope, record.harness_execution_id
            )
            state = _state(record.harness_execution_id, row)
            result = enqueue_budget_control(state, record)
            controls = {**state.budget_controls, result.key: result}
            await self._merge_identity(
                connection,
                args,
                record.harness_execution_id,
                {
                    BUDGET_CONTROL_KEY: {
                        key: value.model_dump(mode="json") for key, value in controls.items()
                    }
                },
            )
            return result

    async def update_budget_control(
        self, record: BudgetControlRecord, *, expected_revision: int, owner: SessionOwner
    ) -> BudgetControlRecord:
        async with self._pool.acquire() as connection, connection.transaction():
            args, row = await self._locked(
                connection, record.request_scope, record.harness_execution_id
            )
            state = _state(record.harness_execution_id, row)
            validate_budget_update(state, record, expected_revision, owner)
            controls = {**state.budget_controls, record.key: record}
            await self._merge_identity(
                connection,
                args,
                record.harness_execution_id,
                {
                    BUDGET_CONTROL_KEY: {
                        key: value.model_dump(mode="json") for key, value in controls.items()
                    }
                },
            )
            return record

    async def _row(
        self,
        connection: asyncpg.Connection,
        args: tuple[Any, ...],
        harness_execution_id: UUID,
        *,
        lock: bool,
    ) -> asyncpg.Record | None:
        return await connection.fetchrow(
            f"""
            SELECT {", ".join(_COLUMNS)}, native_identity, generation, lifecycle
            FROM mission_control.harness_execution
            WHERE {SCOPE} AND harness_execution_id = $4
            {"FOR UPDATE" if lock else ""}
            """,
            *args,
            harness_execution_id,
        )

    async def _locked(
        self, connection: asyncpg.Connection, request_scope: str, harness_execution_id: UUID
    ) -> tuple[tuple[Any, ...], asyncpg.Record]:
        args = await begin(connection, request_scope)
        row = await self._row(connection, args, harness_execution_id, lock=True)
        if row is None:
            raise HarnessExecutionNotOpened(str(harness_execution_id))
        return args, row

    async def _merge_identity(
        self,
        connection: asyncpg.Connection,
        args: tuple[Any, ...],
        harness_execution_id: UUID,
        patch: Mapping[str, Any],
    ) -> None:
        await connection.execute(
            f"""
            UPDATE mission_control.harness_execution
            SET native_identity = COALESCE(native_identity, '{{}}'::jsonb) || $5::jsonb,
                version = version + 1, updated_at = clock_timestamp()
            WHERE {SCOPE} AND harness_execution_id = $4
            """,
            *args,
            harness_execution_id,
            json.dumps(patch, sort_keys=True),
        )

    async def load(
        self, request_scope: str, harness_execution_id: UUID
    ) -> LaneExecutionState | None:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await begin(connection, request_scope)
            row = await self._row(connection, args, harness_execution_id, lock=False)
        return None if row is None else _state(harness_execution_id, row)

    async def record(
        self,
        request_scope: str,
        harness_execution_id: UUID,
        update: LaneExecutionUpdate,
        *,
        owner: SessionOwner | None = None,
    ) -> LaneExecutionState:
        async with self._pool.acquire() as connection, connection.transaction():
            args, row = await self._locked(connection, request_scope, harness_execution_id)
            current = _state(harness_execution_id, row)
            if owner is not None:
                assert_holder(current.owner, owner)
            merged = merge_state(current, update)
            if current.history_closed_turn != merged.history_closed_turn:
                await self._merge_identity(
                    connection,
                    args,
                    harness_execution_id,
                    {HISTORY_CLOSED_KEY: merged.history_closed_turn},
                )
            fields = update.fields()
            if fields:
                assignments = ", ".join(
                    f"{name} = ${index}" for index, name in enumerate(fields, start=5)
                )
                await connection.execute(
                    f"""
                    UPDATE mission_control.harness_execution
                    SET {assignments}, version = version + 1, updated_at = clock_timestamp()
                    WHERE {SCOPE} AND harness_execution_id = $4
                    """,
                    *args,
                    harness_execution_id,
                    *fields.values(),
                )
        return merged

    # --- MP-06 session ownership and dispatch journal ---------------------------------------

    async def claim_owner(
        self,
        request_scope: str,
        harness_execution_id: UUID,
        *,
        owner_ref: str,
        generation: int,
        now: datetime,
        lease: timedelta,
    ) -> SessionOwner:
        async with self._pool.acquire() as connection, connection.transaction():
            args, row = await self._locked(connection, request_scope, harness_execution_id)
            current = _owner(_identity(row["native_identity"]))
            owner = claim_ownership(
                current, owner_ref=owner_ref, generation=generation, now=now, lease=lease
            )
            if owner != current:
                await self._merge_identity(
                    connection,
                    args,
                    harness_execution_id,
                    {OWNER_KEY: owner.model_dump(mode="json")},
                )
            return owner

    async def renew_owner(
        self,
        request_scope: str,
        harness_execution_id: UUID,
        owner: SessionOwner,
        *,
        expires_at: datetime,
    ) -> SessionOwner:
        async with self._pool.acquire() as connection, connection.transaction():
            args, row = await self._locked(connection, request_scope, harness_execution_id)
            renewed = renew_ownership(
                _owner(_identity(row["native_identity"])), owner, expires_at=expires_at
            )
            await self._merge_identity(
                connection, args, harness_execution_id, {OWNER_KEY: renewed.model_dump(mode="json")}
            )
            return renewed

    async def assert_owner(
        self, request_scope: str, harness_execution_id: UUID, owner: SessionOwner
    ) -> None:
        # Read under the row lock so a takeover that committed first is always seen.
        async with self._pool.acquire() as connection, connection.transaction():
            _args, row = await self._locked(connection, request_scope, harness_execution_id)
            assert_holder(_owner(_identity(row["native_identity"])), owner)

    async def intend_dispatch(
        self,
        request_scope: str,
        harness_execution_id: UUID,
        record: DispatchRecord,
        *,
        owner: SessionOwner,
    ) -> DispatchClaim:
        async with self._pool.acquire() as connection, connection.transaction():
            args, row = await self._locked(connection, request_scope, harness_execution_id)
            identity = _identity(row["native_identity"])
            assert_holder(_owner(identity), owner)
            journal = _dispatches(identity)
            claim = intend(journal.get(record.key), record, owner)
            if claim.fresh:
                journal[record.key] = claim.record
                await self._write_journal(connection, args, harness_execution_id, journal)
            return claim

    async def resolve_dispatch(
        self,
        request_scope: str,
        harness_execution_id: UUID,
        kind: DispatchKind,
        idempotency_key: str,
        *,
        outcome: DispatchOutcome,
        owner: SessionOwner,
        at: datetime,
        native_ref: str | None = None,
        reason: str | None = None,
    ) -> DispatchRecord:
        async with self._pool.acquire() as connection, connection.transaction():
            args, row = await self._locked(connection, request_scope, harness_execution_id)
            identity = _identity(row["native_identity"])
            assert_holder(_owner(identity), owner)
            journal = _dispatches(identity)
            key = dispatch_key(kind, idempotency_key)
            record = resolve(
                journal.get(key),
                outcome=outcome,
                owner=owner,
                at=at,
                native_ref=native_ref,
                reason=reason,
            )
            if record != journal.get(key):
                journal[key] = record
                await self._write_journal(connection, args, harness_execution_id, journal)
            return record

    async def _write_journal(
        self,
        connection: asyncpg.Connection,
        args: tuple[Any, ...],
        harness_execution_id: UUID,
        journal: Mapping[str, DispatchRecord],
    ) -> None:
        await self._merge_identity(
            connection,
            args,
            harness_execution_id,
            {DISPATCH_KEY: {key: value.model_dump(mode="json") for key, value in journal.items()}},
        )


__all__ = ["HarnessExecutionNotOpened", "PostgresLaneExecutionStateStore"]
