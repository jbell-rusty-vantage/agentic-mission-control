"""Harness execution lane state: native identity, provider cursor, usage disposition (FT-G2).

`lane.turn` writes the native identity of a session and turn *before* it observes (native
identity first, then observation), the provider cursor at every segment boundary, and the
usage disposition at settlement. A resumed segment reads them back: a recorded native turn
means the turn was sent, so a resume never sends it again. The production store updates
`mission_control.harness_execution` (migration 0030, G2 section); the row itself is opened
by the frame store (SPEC-03) before any of these writes.

MP-06: the same row carries the session owner and the dispatch journal (`dispatch.py`), so
identity, ownership and every journaled create/send change under one row lock.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

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
from mission_control.domain.execution.budget_controls import BudgetControlRecord
from mission_control.domain.execution.history_reconciliation import (
    HistoryAcknowledgment,
    HistoryDeferred,
    HistoryJournal,
    HistoryRejection,
    HistoryRequest,
    enqueue_history,
)
from mission_control.domain.execution.lanes import UsageDisposition


class LaneExecutionState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    harness_execution_id: UUID
    native_session_ref: str | None = Field(default=None, min_length=1)
    native_turn_ref: str | None = Field(default=None, min_length=1)
    provider_cursor: str | None = Field(default=None, min_length=1)
    usage_disposition: UsageDisposition | None = None
    last_segment_at: AwareDatetime | None = None
    cursor_sdk_version: str | None = None
    bridge_state_root: str | None = None
    cloud_branch: str | None = None
    cloud_agent_url: str | None = None
    # MP-06: the worker-owned session manager holding the session, and the journal of
    # every native create/send keyed by `dispatch_key(kind, idempotency_key)`.
    owner: SessionOwner | None = None
    dispatches: Mapping[str, DispatchRecord] = Field(default_factory=dict)
    budget_controls: dict[str, BudgetControlRecord] = Field(default_factory=dict)
    history_reconciliation: HistoryJournal | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        json_schema_extra={"digest_omit_default": True},
    )

    history_closed_turn: str | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        json_schema_extra={"digest_omit_default": True},
    )

    def dispatch(self, kind: DispatchKind, idempotency_key: str) -> DispatchRecord | None:
        return self.dispatches.get(dispatch_key(kind, idempotency_key))


class LaneExecutionUpdate(BaseModel):
    """Fields one write sets; `None` leaves a field unchanged (identity is never cleared).

    FT-G4: a recorded native identity moves only by an explicit supersession naming the
    identity it replaces (compare-and-set): `supersedes_turn_ref` for a `cancel_and_replace`
    replacement turn on the same agent, `supersedes_session_ref` for a continuation handed to
    a fresh agent. The two guards are never stored.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    native_session_ref: str | None = Field(default=None, min_length=1)
    native_turn_ref: str | None = Field(default=None, min_length=1)
    provider_cursor: str | None = Field(default=None, min_length=1)
    usage_disposition: UsageDisposition | None = None
    last_segment_at: AwareDatetime | None = None
    cursor_sdk_version: str | None = None
    bridge_state_root: str | None = None
    cloud_branch: str | None = None
    cloud_agent_url: str | None = None
    supersedes_session_ref: str | None = Field(default=None, min_length=1)
    supersedes_turn_ref: str | None = Field(default=None, min_length=1)

    def fields(self) -> dict[str, object]:
        return {
            name: value
            for name, value in self.model_dump(
                exclude={"supersedes_session_ref", "supersedes_turn_ref"}
            ).items()
            if value is not None
        }


class LaneExecutionStateStore(Protocol):
    async def refresh_history_authority(
        self, request: HistoryRequest, *, owner: SessionOwner, at: datetime
    ) -> HistoryJournal: ...

    async def close_history_window(
        self,
        request_scope: str,
        harness_execution_id: UUID,
        *,
        owner: SessionOwner,
        native_turn_ref: str,
    ) -> None: ...

    async def request_history(self, request: HistoryRequest) -> HistoryJournal: ...

    async def acknowledge_history(
        self, request: HistoryRequest, *, owner: SessionOwner, cursor: str | None, at: datetime
    ) -> HistoryJournal: ...

    async def enqueue_budget_control(self, record: BudgetControlRecord) -> BudgetControlRecord: ...

    async def update_budget_control(
        self, record: BudgetControlRecord, *, expected_revision: int, owner: SessionOwner
    ) -> BudgetControlRecord: ...

    async def load(
        self, request_scope: str, harness_execution_id: UUID
    ) -> LaneExecutionState | None: ...

    async def record(
        self,
        request_scope: str,
        harness_execution_id: UUID,
        update: LaneExecutionUpdate,
        *,
        owner: SessionOwner | None = None,
    ) -> LaneExecutionState: ...

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
        """Claim or renew the session (`claim_ownership`); a live foreign lease refuses."""
        ...

    async def renew_owner(
        self,
        request_scope: str,
        harness_execution_id: UUID,
        owner: SessionOwner,
        *,
        expires_at: datetime,
    ) -> SessionOwner: ...

    async def assert_owner(
        self, request_scope: str, harness_execution_id: UUID, owner: SessionOwner
    ) -> None:
        """Raise `StaleSessionOwner` unless `owner` still holds the session."""
        ...

    async def intend_dispatch(
        self,
        request_scope: str,
        harness_execution_id: UUID,
        record: DispatchRecord,
        *,
        owner: SessionOwner,
    ) -> DispatchClaim: ...

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
    ) -> DispatchRecord: ...


def enqueue_budget_control(
    state: LaneExecutionState, record: BudgetControlRecord
) -> BudgetControlRecord:
    if (
        state.native_session_ref != record.native_session_ref
        or state.owner is None
        or state.owner.generation != record.generation
    ):
        raise ValueError("budget control native identity/generation changed")
    prior = state.budget_controls.get(record.key)
    if prior is not None:
        mutable = {
            "phase",
            "revision",
            "owner_epoch",
            "evidence",
            "reason",
            "recorded_at",
            "target_cap_minor_units",
            "prior_cap_minor_units",
            "observed_cost_minor_units",
            "prior_boundary_evidence",
        }
        if prior.model_dump(exclude=mutable) != record.model_dump(exclude=mutable):
            raise ValueError("budget control idempotency conflict")
        return prior
    if record.phase != "queued" or record.revision != 1:
        raise ValueError("new budget control must be queued")
    return record


def validate_budget_update(
    state: LaneExecutionState,
    record: BudgetControlRecord,
    expected_revision: int,
    owner: SessionOwner,
) -> None:
    assert_holder(state.owner, owner)
    prior = state.budget_controls.get(record.key)
    if (
        prior is None
        or prior.revision != expected_revision
        or record.revision != expected_revision + 1
    ):
        raise RuntimeError("budget control revision changed")
    # Reuse immutable input equality independently of phase transitions.
    enqueue_budget_control(state, record.model_copy(update={"phase": "queued", "revision": 1}))
    if prior.phase in {"rejected", "boundary_observed"} or (
        prior.action == "resume" and prior.applied
    ):
        raise ValueError("terminal budget control cannot change")
    allowed = (
        {"intended", "rejected"}
        if prior.phase == "queued"
        else {"in_doubt", "cap_confirmed", "boundary_observed"}
    )
    if record.phase not in allowed or (
        record.action == "resume" and record.phase == "boundary_observed"
    ):
        raise ValueError("invalid budget control phase transition")
    if prior.phase != "queued" and (
        record.target_cap_minor_units != prior.target_cap_minor_units
        or record.prior_cap_minor_units != prior.prior_cap_minor_units
        or record.prior_boundary_evidence != prior.prior_boundary_evidence
    ):
        raise ValueError("intended budget control cap/evidence cannot change")


def request_history_state(state: LaneExecutionState, request: HistoryRequest) -> HistoryJournal:
    prior = state.history_reconciliation
    if prior is not None and prior.covers(request):
        return prior
    if state.history_closed_turn == request.native_turn_ref:
        raise ValueError("native turn history admission is closed")
    if (
        state.native_session_ref != request.native_session_ref
        or state.native_turn_ref != request.native_turn_ref
        or state.owner is None
        or state.owner.generation != request.generation
    ):
        raise ValueError("history request native identity/generation differs")
    return enqueue_history(prior, request)


def acknowledge_history_state(
    state: LaneExecutionState,
    request: HistoryRequest,
    *,
    owner: SessionOwner,
    cursor: str | None,
    at: datetime,
) -> HistoryJournal:
    assert_holder(state.owner, owner)
    prior = state.history_reconciliation
    if (
        prior is None
        or prior.requested.binding != request.binding
        or request.watermark > prior.requested.watermark
    ):
        raise ValueError("history acknowledgment has no exact requested authority")
    if prior.covers(request) or prior.rejects(request):
        return prior
    if (
        state.native_session_ref != request.native_session_ref
        or state.native_turn_ref != request.native_turn_ref
        or owner.generation != request.generation
    ):
        raise ValueError("history acknowledgment native identity/generation differs")
    receipts = tuple(
        r
        for r in prior.acknowledgments
        if r.request.binding != request.binding
        or r.request.native_turn_ref != request.native_turn_ref
    )
    return HistoryJournal(
        requested=prior.requested,
        rejection=prior.rejection,
        acknowledgments=(
            *receipts,
            HistoryAcknowledgment(
                request=request,
                acknowledged_at=at,
                persisted_cursor=cursor,
            ),
        ),
    )


def reject_history_state(
    state: LaneExecutionState, request: HistoryRequest, *, owner: SessionOwner, at: datetime
) -> HistoryJournal:
    assert_holder(state.owner, owner)
    prior = state.history_reconciliation
    if prior is None:
        raise ValueError("history rejection has no requested authority")
    if prior.covers(request) or prior.rejects(request):
        return prior
    if (
        prior.requested.binding != request.binding
        or prior.requested.native_turn_ref != request.native_turn_ref
        or request.watermark > prior.requested.watermark
        or request.generation > owner.generation
        or (
            request.generation == owner.generation
            and (
                state.native_session_ref != request.native_session_ref
                or state.native_turn_ref != request.native_turn_ref
            )
        )
    ):
        raise ValueError("history rejection native identity or requested authority differs")
    # Revocation invalidates the exact binding, including newer coalesced hints. The
    # original inbox keeps its receipt when rejected, so advancing this bounded journal
    # never erases ingress audit. A rejection is not a successful native observation.
    return HistoryJournal(
        requested=prior.requested,
        acknowledgments=prior.acknowledgments,
        rejection=HistoryRejection(request=prior.requested, rejected_at=at),
    )


def close_history_window_state(
    state: LaneExecutionState, *, owner: SessionOwner, native_turn_ref: str
) -> LaneExecutionState:
    assert_holder(state.owner, owner)
    if state.native_turn_ref != native_turn_ref:
        raise ValueError("native history close names a different turn")
    if state.history_reconciliation is not None and state.history_reconciliation.pending:
        raise HistoryDeferred("native_history_pending")
    return state.model_copy(update={"history_closed_turn": native_turn_ref})


class NativeIdentityConflict(RuntimeError):
    """A write named a different native session or turn than the one already recorded."""


def merge_state(current: LaneExecutionState, update: LaneExecutionUpdate) -> LaneExecutionState:
    """Apply an update; a recorded native identity never changes to another value."""

    for name, guard in (
        ("native_session_ref", update.supersedes_session_ref),
        ("native_turn_ref", update.supersedes_turn_ref),
    ):
        recorded = getattr(current, name)
        incoming = getattr(update, name)
        if recorded is not None and incoming is not None and recorded != incoming:
            if guard is None or guard != recorded:
                raise NativeIdentityConflict(f"{name} is already {recorded}, not {incoming}")
    changed_native = any(
        getattr(update, name) is not None and getattr(update, name) != getattr(current, name)
        for name in ("native_session_ref", "native_turn_ref")
    )
    if (
        changed_native
        and current.history_reconciliation is not None
        and current.history_reconciliation.pending
    ):
        raise HistoryDeferred("native_history_pending")
    changes = update.fields()
    if changed_native and current.history_closed_turn is not None:
        changes["history_closed_turn"] = None
    return current.model_copy(update=changes)


class InMemoryLaneExecutionStateStore:
    """Process-local store with the production merge rule (tests and local proof)."""

    def __init__(self) -> None:
        self._states: dict[tuple[str, UUID], LaneExecutionState] = {}
        self._lock = asyncio.Lock()

    async def refresh_history_authority(
        self, request: HistoryRequest, *, owner: SessionOwner, at: datetime
    ) -> HistoryJournal:
        # Fixtures have no credential registry, but a generation takeover invalidates
        # old bindings just as the execution row does in the PostgreSQL implementation.
        async with self._lock:
            state = self._current(request.request_scope, request.harness_execution_id)
            rejected = reject_history_state(state, request, owner=owner, at=at)
            if request.generation < owner.generation:
                self._put(
                    request.request_scope,
                    state.model_copy(update={"history_reconciliation": rejected}),
                )
                return rejected
            assert state.history_reconciliation is not None
            return state.history_reconciliation

    async def close_history_window(
        self,
        request_scope: str,
        harness_execution_id: UUID,
        *,
        owner: SessionOwner,
        native_turn_ref: str,
    ) -> None:
        async with self._lock:
            state = close_history_window_state(
                self._current(request_scope, harness_execution_id),
                owner=owner,
                native_turn_ref=native_turn_ref,
            )
            self._put(request_scope, state)

    async def request_history(self, request: HistoryRequest) -> HistoryJournal:
        async with self._lock:
            state = self._current(request.request_scope, request.harness_execution_id)
            journal = request_history_state(state, request)
            self._states[(request.request_scope, request.harness_execution_id)] = state.model_copy(
                update={"history_reconciliation": journal}
            )
            return journal

    async def acknowledge_history(
        self, request: HistoryRequest, *, owner: SessionOwner, cursor: str | None, at: datetime
    ) -> HistoryJournal:
        async with self._lock:
            state = self._current(request.request_scope, request.harness_execution_id)
            journal = acknowledge_history_state(state, request, owner=owner, cursor=cursor, at=at)
            self._states[(request.request_scope, request.harness_execution_id)] = state.model_copy(
                update={"history_reconciliation": journal}
            )
            return journal

    async def load(
        self, request_scope: str, harness_execution_id: UUID
    ) -> LaneExecutionState | None:
        return self._states.get((request_scope, harness_execution_id))

    async def record(
        self,
        request_scope: str,
        harness_execution_id: UUID,
        update: LaneExecutionUpdate,
        *,
        owner: SessionOwner | None = None,
    ) -> LaneExecutionState:
        async with self._lock:
            current = self._current(request_scope, harness_execution_id)
            if owner is not None:
                assert_holder(current.owner, owner)
            merged = merge_state(current, update)
            self._states[(request_scope, harness_execution_id)] = merged
            return merged

    def _current(self, request_scope: str, harness_execution_id: UUID) -> LaneExecutionState:
        return self._states.get((request_scope, harness_execution_id)) or LaneExecutionState(
            harness_execution_id=harness_execution_id
        )

    def _put(self, request_scope: str, state: LaneExecutionState) -> None:
        self._states[(request_scope, state.harness_execution_id)] = state

    async def enqueue_budget_control(self, record: BudgetControlRecord) -> BudgetControlRecord:
        async with self._lock:
            state = self._current(record.request_scope, record.harness_execution_id)
            result = enqueue_budget_control(state, record)
            self._put(
                record.request_scope,
                state.model_copy(
                    update={"budget_controls": {**state.budget_controls, result.key: result}}
                ),
            )
            return result

    async def update_budget_control(
        self, record: BudgetControlRecord, *, expected_revision: int, owner: SessionOwner
    ) -> BudgetControlRecord:
        async with self._lock:
            state = self._current(record.request_scope, record.harness_execution_id)
            validate_budget_update(state, record, expected_revision, owner)
            self._put(
                record.request_scope,
                state.model_copy(
                    update={"budget_controls": {**state.budget_controls, record.key: record}}
                ),
            )
            return record

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
        async with self._lock:
            current = self._current(request_scope, harness_execution_id)
            owner = claim_ownership(
                current.owner, owner_ref=owner_ref, generation=generation, now=now, lease=lease
            )
            self._put(request_scope, current.model_copy(update={"owner": owner}))
            return owner

    async def renew_owner(
        self,
        request_scope: str,
        harness_execution_id: UUID,
        owner: SessionOwner,
        *,
        expires_at: datetime,
    ) -> SessionOwner:
        async with self._lock:
            current = self._current(request_scope, harness_execution_id)
            renewed = renew_ownership(current.owner, owner, expires_at=expires_at)
            self._put(request_scope, current.model_copy(update={"owner": renewed}))
            return renewed

    async def assert_owner(
        self, request_scope: str, harness_execution_id: UUID, owner: SessionOwner
    ) -> None:
        assert_holder(self._current(request_scope, harness_execution_id).owner, owner)

    async def intend_dispatch(
        self,
        request_scope: str,
        harness_execution_id: UUID,
        record: DispatchRecord,
        *,
        owner: SessionOwner,
    ) -> DispatchClaim:
        async with self._lock:
            current = self._current(request_scope, harness_execution_id)
            assert_holder(current.owner, owner)
            claim = intend(current.dispatches.get(record.key), record, owner)
            if claim.fresh:
                self._put(request_scope, _with_dispatch(current, claim.record))
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
        async with self._lock:
            current = self._current(request_scope, harness_execution_id)
            assert_holder(current.owner, owner)
            record = resolve(
                current.dispatches.get(dispatch_key(kind, idempotency_key)),
                outcome=outcome,
                owner=owner,
                at=at,
                native_ref=native_ref,
                reason=reason,
            )
            self._put(request_scope, _with_dispatch(current, record))
            return record


def _with_dispatch(state: LaneExecutionState, record: DispatchRecord) -> LaneExecutionState:
    return state.model_copy(update={"dispatches": {**state.dispatches, record.key: record}})


def segment_update(cursor: str | None, at: datetime) -> LaneExecutionUpdate:
    return LaneExecutionUpdate(provider_cursor=cursor, last_segment_at=at)


__all__ = [
    "InMemoryLaneExecutionStateStore",
    "LaneExecutionState",
    "LaneExecutionStateStore",
    "LaneExecutionUpdate",
    "NativeIdentityConflict",
    "merge_state",
    "segment_update",
]
