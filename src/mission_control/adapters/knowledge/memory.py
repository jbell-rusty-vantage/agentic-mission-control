"""In-process Mission Control knowledge stores with the PostgreSQL adapters' legality rules.

The journal, handle, submission, transfer-plan, lineage and retained-read stores behind the
`application.ports.knowledge` ports. They hold rows in process memory with the legality rules the
PostgreSQL adapters enforce, for unit proofs and the in-memory compositions; ordinary launch never
composes them (the precedent is `decisions.InMemoryUseDecisionStore`). The PostgreSQL proofs
reuse the same scenarios against the durable stores
(`tests/integration/postgres/test_knowledge_gateway_postgres.py`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from typing import Any
from uuid import uuid4

from mission_control.application.context.materialization import TransferPlanConflict
from mission_control.application.ports.knowledge import (
    FinalizationCandidate,
    FinalizationRecord,
    HandleCandidate,
    HandleRecord,
    JournalRecord,
    JournalVersionConflict,
    LineageEntry,
    PrepareRequest,
    RetainedReadObservation,
    Settlement,
    SubmissionCandidate,
    SubmissionClosed,
    SubmissionConflict,
    SubmissionRecord,
)
from mission_control.contracts.knowledge_protocol import (
    can_reach,
)
from mission_control.contracts.knowledge_protocol_results import (
    OperationStatus,
)
from mission_control.domain.context.transfer import DeliveryReceipt, SealedTransferPlan
from mission_control.domain.knowledge.effects import (
    EffectConflict,
    JournalState,
    require_transition,
)


class InMemoryKnowledgeJournal:
    """The journal port with the 1.5.0 legality rules, for unit tests."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], JournalRecord] = {}
        self.coordinates: dict[tuple[str, str], tuple[str, str, int]] = {}
        self.history: dict[tuple[str, str], list[tuple[JournalState | None, JournalState]]] = {}

    async def prepare(self, request: PrepareRequest) -> JournalRecord:
        key = (request.scope, request.effect_key)
        existing = self.rows.get(key)
        if existing is not None:
            if existing.bound_effect_digest != request.bound_effect_digest:
                raise EffectConflict(f"EFFECT_CONFLICT {request.effect_key}")
            return existing
        record = JournalRecord(
            knowledge_operation_id=str(uuid4()),
            effect_key=request.effect_key,
            semantic_payload_digest=request.semantic_payload_digest,
            bound_effect_digest=request.bound_effect_digest,
            originating_origin=request.originating_origin,
            current_caller_origin=request.current_caller_origin,
            capability_pin=request.capability_pin,
            binding_id=request.binding_id,
            state=JournalState.PREPARED,
            version=1,
            operation_ref=request.coordinates.operation_ref,
            operation_attempt=request.coordinates.operation_attempt,
        )
        self.rows[key] = record
        coordinates = request.coordinates
        self.coordinates[key] = (
            coordinates.run_id,
            coordinates.operation_ref,
            coordinates.operation_attempt,
        )
        self.history[key] = [(None, JournalState.PREPARED)]
        return record

    async def lookup(self, scope: str, effect_key: str) -> JournalRecord | None:
        return self.rows.get((scope, effect_key))

    async def open_for_attempt(
        self, scope: str, *, run_id: str, operation_ref: str, operation_attempt: int
    ) -> list[JournalRecord]:
        wanted = (run_id, operation_ref, operation_attempt)
        return [
            record
            for key, record in self.rows.items()
            if key[0] == scope
            and self.coordinates[key] == wanted
            and record.state
            in {JournalState.PREPARED, JournalState.DISPATCHED, JournalState.UNCERTAIN}
        ]

    async def open_for_operation(
        self, scope: str, *, run_id: str, operation_ref: str
    ) -> list[JournalRecord]:
        return [
            record
            for key, record in self.rows.items()
            if key[0] == scope
            and self.coordinates[key][:2] == (run_id, operation_ref)
            and record.state
            in {JournalState.PREPARED, JournalState.DISPATCHED, JournalState.UNCERTAIN}
        ]

    def _advance(self, scope: str, effect_key: str, expected: int, **changes: Any) -> JournalRecord:
        key = (scope, effect_key)
        current = self.rows[key]
        if current.version != expected:
            raise JournalVersionConflict(effect_key)
        state = changes.get("state", current.state)
        if state != current.state:
            require_transition(current.state, state)
        record = replace(current, version=current.version + 1, **changes)
        self.rows[key] = record
        self.history[key].append((current.state, record.state))
        return record

    async def dispatch(
        self,
        scope: str,
        effect_key: str,
        *,
        expected_version: int,
        dispatch_id: str,
        envelope_digest: str,
        protocol_version: str,
        caller: Any,
        at: datetime,
        recovery_authority_ref: str | None = None,
    ) -> JournalRecord:
        return self._advance(
            scope,
            effect_key,
            expected_version,
            state=JournalState.DISPATCHED,
            dispatch_id=dispatch_id,
            envelope_digest=envelope_digest,
            protocol_version=protocol_version,
            current_caller_origin=caller,
            recovery_authority_ref=recovery_authority_ref,
        )

    async def record_handle(
        self, scope: str, effect_key: str, *, expected_version: int, operation_id: str, at: datetime
    ) -> JournalRecord:
        return self._advance(scope, effect_key, expected_version, operation_id=operation_id)

    async def settle(
        self,
        scope: str,
        effect_key: str,
        *,
        expected_version: int,
        settlement: Settlement,
        at: datetime,
    ) -> JournalRecord:
        return self._advance(
            scope,
            effect_key,
            expected_version,
            state=settlement.state,
            terminal_receipt_ref=settlement.terminal_receipt_ref,
            receipt_digest=settlement.receipt_digest,
            refusal_code=settlement.refusal_code,
            reconciled=settlement.reconciled,
        )

    async def mark_uncertain(
        self, scope: str, effect_key: str, *, expected_version: int, at: datetime
    ) -> JournalRecord:
        return self._advance(scope, effect_key, expected_version, state=JournalState.UNCERTAIN)

    async def transitions(
        self, scope: str, effect_key: str
    ) -> list[tuple[JournalState | None, JournalState]]:
        return list(self.history.get((scope, effect_key), []))


class InMemoryKnowledgeHandleStore:
    """``KnowledgeHandleStore`` with the 1.6.0 rules (monotonic revision, first cancel id)."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str, str], HandleRecord] = {}
        self.runs: dict[tuple[str, str, str], str] = {}

    async def record(self, candidate: HandleCandidate) -> HandleRecord:
        key = (candidate.scope, candidate.binding_id, candidate.handle.operationId)
        if key in self.rows:
            return self.rows[key]
        self.runs[key] = candidate.coordinates.run_id
        record = HandleRecord(
            handle_id=str(uuid4()),
            binding_id=candidate.binding_id,
            operation=candidate.operation,
            request_id=candidate.request_id,
            handle=candidate.handle,
            invocation_ref=candidate.invocation_ref,
            caller_origin=candidate.caller_origin,
            state="queued",
            remote_revision=0,
            version=1,
            effect_key=candidate.effect_key,
            subject_ref=candidate.subject_ref,
        )
        self.rows[key] = record
        return record

    async def get(self, scope: str, binding_id: str, operation_id: str) -> HandleRecord | None:
        return self.rows.get((scope, binding_id, operation_id))

    async def observe(
        self, scope: str, binding_id: str, status: OperationStatus, *, at: datetime
    ) -> HandleRecord:
        key = (scope, binding_id, status.handle.operationId)
        current = self.rows[key]
        if status.revision <= current.remote_revision or current.terminal:
            return current
        if status.state != current.state and not can_reach(current.state, status.state):
            return current  # stale or illegal: a poll never regresses a handle
        record = replace(
            current,
            state=status.state,
            remote_revision=status.revision,
            version=current.version + 1,
            cancel_request_id=current.cancel_request_id or status.cancelRequestId,
            pending_review_ref=None
            if status.pendingReviewRef is None
            else status.pendingReviewRef.id,
            result_ref=status.resultRef,
            error_code=None if status.error is None else status.error.code,
            unresolved_effects=tuple(
                effect.model_dump(mode="json") for effect in status.unresolvedEffects
            ),
        )
        self.rows[key] = record
        return record

    async def request_cancel(
        self,
        scope: str,
        binding_id: str,
        operation_id: str,
        cancel_request_id: str,
        *,
        at: datetime,
    ) -> HandleRecord:
        key = (scope, binding_id, operation_id)
        current = self.rows[key]
        if current.cancel_request_id is not None or current.terminal:
            return current
        record = replace(current, cancel_request_id=cancel_request_id, version=current.version + 1)
        self.rows[key] = record
        return record

    async def open_for_run(self, scope: str, run_id: str) -> list[HandleRecord]:
        return [
            record
            for key, record in self.rows.items()
            if key[0] == scope and self.runs.get(key) == run_id and not record.terminal
        ]

    async def open_for_invocation(self, scope: str, invocation_ref: str) -> list[HandleRecord]:
        return [
            record
            for key, record in self.rows.items()
            if key[0] == scope and record.invocation_ref == invocation_ref and not record.terminal
        ]


class InMemorySubmissionStore:
    """``OutputSubmissionStore`` with the 1.5.0 + 1.6.0 rules."""

    def __init__(self) -> None:
        self.rows: dict[str, SubmissionRecord] = {}
        self.scopes: dict[str, str] = {}
        self.finalizations: dict[tuple[str, str], FinalizationRecord] = {}
        self.meta: dict[str, tuple[str, str, int]] = {}  # submission -> run, operation, attempt
        self.finalized: list[tuple[str, FinalizationCandidate]] = []

    async def record_selection(self, candidate: SubmissionCandidate) -> SubmissionRecord:
        if (candidate.scope, candidate.invocation_ref) in self.finalizations:
            raise SubmissionClosed(candidate.invocation_ref)
        mine = [
            row
            for sid, row in self.rows.items()
            if self.scopes[sid] == candidate.scope
            and row.invocation_ref == candidate.invocation_ref
            and row.obligation_id == candidate.obligation_id
        ]
        for row in mine:
            if row.submission_key == candidate.submission_key:
                if row.selection_digest != candidate.selection_digest:
                    raise SubmissionConflict(candidate.submission_key)
                return row
        record = SubmissionRecord(
            submission_id=str(uuid4()),
            invocation_ref=candidate.invocation_ref,
            obligation_id=candidate.obligation_id,
            submission_key=candidate.submission_key,
            revision=len(mine) + 1,
            selection_digest=candidate.selection_digest,
            assessment_state="pending",
            selection=candidate.selection,
        )
        self.rows[record.submission_id] = record
        self.scopes[record.submission_id] = candidate.scope
        self.meta[record.submission_id] = (
            candidate.run_id,
            candidate.operation_ref,
            candidate.operation_attempt,
        )
        return record

    async def list_for_invocation(self, scope: str, invocation_ref: str) -> list[SubmissionRecord]:
        return sorted(
            (
                row
                for sid, row in self.rows.items()
                if self.scopes[sid] == scope and row.invocation_ref == invocation_ref
            ),
            key=lambda row: (row.obligation_id, row.revision),
        )

    def _cas(self, submission_id: str, expected: int, **changes: Any) -> SubmissionRecord:
        current = self.rows[submission_id]
        if current.version != expected:
            raise JournalVersionConflict(submission_id)
        record = replace(current, version=current.version + 1, **changes)
        self.rows[submission_id] = record
        return record

    async def start_assessment(
        self,
        scope: str,
        submission_id: str,
        *,
        expected_version: int,
        operation_id: str,
        binding_id: str,
        actor_ref: str,
        at: datetime,
    ) -> SubmissionRecord:
        if self.rows[submission_id].assessment_state != "pending":
            raise ValueError("only a pending submission starts its assessment")
        return self._cas(
            submission_id,
            expected_version,
            assessment_state="assessing",
            assessment_operation_id=operation_id,
            assessment_binding=binding_id,
        )

    async def record_assessment(
        self,
        scope: str,
        submission_id: str,
        *,
        expected_version: int,
        state: str,
        assessment_ref: str,
        assessment_digest: str | None,
        actor_ref: str,
        at: datetime,
    ) -> SubmissionRecord:
        if self.rows[submission_id].assessment_state != "assessing":
            raise ValueError("only an assessing submission records its assessment")
        return self._cas(
            submission_id,
            expected_version,
            assessment_state=state,
            assessment_ref=assessment_ref,
            assessment_digest=assessment_digest,
        )

    async def finalize(self, candidate: FinalizationCandidate) -> FinalizationRecord:
        key = (candidate.scope, candidate.invocation_ref)
        if key not in self.finalizations:
            self.finalized.append((candidate.scope, candidate))
            self.finalizations[key] = FinalizationRecord(
                finalization_id=str(uuid4()),
                invocation_ref=candidate.invocation_ref,
                outcome=candidate.outcome,
                submission_ids=candidate.submission_ids,
                report=candidate.report,
                report_digest=candidate.report_digest,
                outcome_basis=candidate.outcome_basis,
            )
        return self.finalizations[key]


class InMemoryTransferPlanStore:
    """``TransferPlanStore``: one immutable plan per receiver key, appended receipts (0057)."""

    def __init__(self) -> None:
        self.plans: dict[tuple[str, str], SealedTransferPlan] = {}
        self.receipt_rows: list[tuple[str, DeliveryReceipt]] = []

    async def seal(self, plan: SealedTransferPlan) -> SealedTransferPlan:
        key = (plan.receiver.scope, plan.receiver_key)
        stored = self.plans.setdefault(key, plan)
        if stored.digest != plan.digest:
            raise TransferPlanConflict(f"receiver {plan.receiver_key} has another sealed plan")
        return stored

    async def plan_for(self, scope: str, receiver_key: str) -> SealedTransferPlan | None:
        return self.plans.get((scope, receiver_key))

    async def get(self, scope: str, plan_id: str) -> SealedTransferPlan | None:
        return next(
            (p for (s, _k), p in self.plans.items() if s == scope and p.plan_id == plan_id),
            None,
        )

    async def append_receipt(self, scope: str, receipt: DeliveryReceipt) -> DeliveryReceipt:
        sequence = 1 + sum(1 for s, r in self.receipt_rows if r.plan_id == receipt.plan_id)
        stored = receipt.model_copy(update={"sequence": sequence})
        self.receipt_rows.append((scope, stored))
        return stored

    async def receipts(self, scope: str, plan_id: str) -> tuple[DeliveryReceipt, ...]:
        return tuple(r for s, r in self.receipt_rows if s == scope and r.plan_id == plan_id)

    async def file_realizations(self, scope: str, source_refs: Sequence[str]) -> dict[str, str]:
        found: dict[str, str] = {}
        for s, receipt in self.receipt_rows:
            plan = await self.get(s, receipt.plan_id)
            if s != scope or plan is None:
                continue
            for item in receipt.delivered:
                source = plan.member(item.member_key).source_ref
                if (
                    source in source_refs
                    and item.placement == "file"
                    and item.ok
                    and source not in found
                ):
                    found[source] = f"transfer-receipt:{receipt.receipt_id}#{item.path_or_handle}"
        return found


class InMemoryLineageStore:
    """``ContentLineageStore`` with the 0051 rules (one producer per subject, replay-safe)."""

    def __init__(self) -> None:
        self.entries: list[tuple[str, LineageEntry]] = []
        self._ids: set[str] = set()

    async def record(self, scope: str, entries: Any, *, actor_ref: str, at: datetime) -> int:
        from mission_control.adapters.postgres.knowledge.lineage import lineage_id

        written = 0
        for entry in entries:
            key = lineage_id(entry)
            if key in self._ids:
                continue
            if entry.fact.role.value == "producer" and any(
                stored.fact.role.value == "producer"
                and stored.fact.subject_handle == entry.fact.subject_handle
                and stored_scope == scope
                for stored_scope, stored in self.entries
            ):
                raise ValueError("a subject has at most one producer")
            self._ids.add(key)
            self.entries.append((scope, entry))
            written += 1
        return written

    async def record_registration(
        self, scope: str, entries: Any, *, actor_ref: str, at: datetime
    ) -> int:
        # No await between validation and commit: matches the atomic registration transaction.
        from mission_control.adapters.postgres.knowledge.lineage import lineage_id

        pending = list(entries)
        handles = {entry.fact.subject_handle for entry in pending}
        producers = {
            entry.fact.subject_handle
            for saved_scope, entry in self.entries
            if saved_scope == scope and entry.fact.role.value == "producer"
        }
        for handle in handles:
            incoming = [entry for entry in pending if entry.fact.subject_handle == handle]
            identities = {(entry.subject_kind, entry.subject_digest) for entry in incoming}
            if len(identities) != 1 or any(entry.subject_digest is None for entry in incoming):
                raise ValueError("registration lineage requires one exact kind and digest")
            if any(
                entry.fact.role.value not in {"producer", "caller", "receipt"} for entry in incoming
            ):
                raise ValueError("registration lineage cannot assert other provenance roles")
            if any(
                (entry.subject_kind, entry.subject_digest) not in identities
                for saved_scope, entry in self.entries
                if saved_scope == scope and entry.fact.subject_handle == handle
            ):
                raise ValueError("registration lineage differs from immutable subject identity")
        written = 0
        for entry in pending:
            if entry.fact.role.value == "producer":
                if entry.fact.subject_handle in producers:
                    continue
                producers.add(entry.fact.subject_handle)
            key = lineage_id(entry)
            if key not in self._ids:
                self._ids.add(key)
                self.entries.append((scope, entry))
                written += 1
        return written

    async def facts(self, scope: str, subject_handle: str) -> list[Any]:
        return [
            entry.fact
            for stored_scope, entry in self.entries
            if stored_scope == scope and entry.fact.subject_handle == subject_handle
        ]


class InMemoryRetainedReadStore:
    """``RetainedReadStore`` with the 0052 rules: unique (scope, invocation, read ref), the
    readable-needs-digest CHECK (the dataclass), append-only."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str, str], RetainedReadObservation] = {}
        self.actors: list[str] = []
        self.fail: Exception | None = None

    async def record(self, scope: str, rows: Any, *, actor_ref: str, at: datetime) -> int:
        if self.fail is not None:
            raise self.fail
        written = 0
        for row in rows:
            key = (scope, row.invocation_ref, row.read_observation_ref)
            if key in self.rows:
                continue
            self.rows[key] = row
            self.actors.append(actor_ref)
            written += 1
        return written

    async def observations(self, scope: str, invocation_ref: str) -> list[RetainedReadObservation]:
        return [
            row
            for (stored, invocation, _), row in self.rows.items()
            if stored == scope and invocation == invocation_ref
        ]


__all__ = [
    "InMemoryKnowledgeHandleStore",
    "InMemoryKnowledgeJournal",
    "InMemoryLineageStore",
    "InMemoryRetainedReadStore",
    "InMemorySubmissionStore",
    "InMemoryTransferPlanStore",
]
