"""Knowledge store contracts: `adapters/knowledge/memory.py` versus the PostgreSQL stores.

One subject holds the six stores behind `application.ports.knowledge` (and the transfer-plan
store of `application.context`): the operation journal, remote handles, output submissions,
sealed transfer plans, content lineage and retained reads. Each scenario calls one store's
public methods and asserts what a caller observes: compare-and-set versions, idempotent replays,
refusals with their error types, ordering and scoping by tenant.

Staging (`tests.support.knowledge.stores.InMemoryStaging`) has no PostgreSQL adapter: the
durable side is an object store, so it has no contract here.

Runners: `tests/unit/knowledge/test_knowledge_store_contract.py` (in memory) and
`tests/integration/postgres/test_knowledge_store_contract_postgres.py` (PostgreSQL).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest

from mission_control.application.context.materialization import TransferPlanConflict
from mission_control.application.knowledge.access import InvocationAccess
from mission_control.application.ports.knowledge import (
    FinalizationCandidate,
    HandleCandidate,
    JournalVersionConflict,
    PrepareRequest,
    Settlement,
    SubmissionCandidate,
    SubmissionClosed,
    SubmissionConflict,
)
from mission_control.contracts.knowledge_protocol import OperationHandle
from mission_control.contracts.knowledge_protocol_results import OperationStatus
from mission_control.domain.context.transfer import (
    DeliveryReceipt,
    ReceiverAttempt,
    ReceiverRef,
    ResourceUsage,
    SealedTransferPlan,
    plan_digest,
    seal_plan,
)
from mission_control.domain.knowledge.effects import EffectConflict, JournalState
from mission_control.domain.knowledge.lineage import ProvenanceRole
from mission_control.domain.knowledge.reads import RetainedReadObservation
from tests.support.knowledge.credentials import BINDING, KNOWLEDGE_NOW
from tests.support.knowledge.gateway import origin
from tests.support.unit.context.transfer_plan import (
    OVERHEAD,
    _deliveries,
    report_input,
    report_members,
    selection,
)
from tests.support.unit.knowledge.registration_lineage import registration_entries

ACTOR = "mission-control:contract"
D1, D2 = "sha256:" + "1" * 64, "sha256:" + "2" * 64
CAPABILITY = "ai-engineer.research@1:knowledge.apply"


@dataclass
class KnowledgeSubject:
    """The knowledge stores under test and two tenant scopes of one installation."""

    journal: Any
    handles: Any
    submissions: Any
    transfer_plans: Any
    lineage: Any
    retained_reads: Any
    scope: str
    other_scope: str

    def access(
        self, *, scope: str | None = None, attempt: int = 1, **updates: object
    ) -> InvocationAccess:
        _mc, installation, application, tenant = (scope or self.scope).split("/")
        return InvocationAccess(
            origin=origin(
                attempt,
                installation_id=installation,
                application_id=application,
                tenant_id=tenant,
                **updates,
            ),
            subject="mission-control-runtime",
            invocation_id=f"inv-{attempt:04d}",
            authenticated_at=KNOWLEDGE_NOW,
        )


Scenario = Callable[[KnowledgeSubject], Awaitable[None]]


# ---------------------------------------------------------------- builders


def prepare(access: InvocationAccess, effect_key: str, *, bound: str = D1) -> PrepareRequest:
    wire = access.wire_origin()
    return PrepareRequest(
        scope=access.scope,
        effect_key=effect_key,
        semantic_payload_digest=D1,
        bound_effect_digest=bound,
        originating_origin=wire,
        current_caller_origin=wire,
        coordinates=access.coordinates(),
        capability_pin=CAPABILITY,
        binding_id=BINDING,
        actor_ref=ACTOR,
    )


def handle(access: InvocationAccess, operation_id: str) -> OperationHandle:
    return OperationHandle(
        protocolVersion="ks.knowledge_operation.v2",
        tenant=access.origin.tenant_id,
        application=access.origin.application_id,
        binding=BINDING,
        operationId=operation_id,
    )


def handle_candidate(
    access: InvocationAccess, operation_id: str, *, request_id: str | None = None
) -> HandleCandidate:
    return HandleCandidate(
        scope=access.scope,
        binding_id=BINDING,
        operation="knowledge.apply",
        request_id=request_id or f"request:{operation_id}",
        handle=handle(access, operation_id),
        coordinates=access.coordinates(),
        invocation_ref=access.invocation_ref,
        caller_origin=access.wire_origin(),
        actor_ref=ACTOR,
        at=KNOWLEDGE_NOW,
        effect_key=f"effect:{operation_id}",
    )


def status(
    access: InvocationAccess, operation_id: str, state: str, revision: int, **updates: object
) -> OperationStatus:
    terminal = state in {"succeeded", "partial", "held", "rejected", "failed", "cancelled"}
    values: dict[str, object] = {
        "handle": handle(access, operation_id).model_dump(mode="json"),
        "state": state,
        "revision": revision,
        "createdAt": "2026-10-24T20:00:00Z",
        "updatedAt": "2026-10-24T20:00:01Z",
        "progressRef": None,
        "pendingReviewRef": None,
        "resultRef": None,
        "error": None,
        "unresolvedEffects": [],
        "retryAfterMs": None if terminal else 1_000,
        "cancelRequestId": None,
        **updates,
    }
    return OperationStatus.model_validate(values)


def submission(
    access: InvocationAccess, key: str, *, digest: str = D1, obligation: str = "draft.report"
) -> SubmissionCandidate:
    return SubmissionCandidate(
        scope=access.scope,
        run_id=access.origin.run_id,
        operation_ref=access.origin.operation_id,
        operation_attempt=access.origin.attempt,
        execution_generation=access.origin.generation,
        invocation_ref=access.invocation_ref,
        obligation_id=obligation,
        submission_key=key,
        selection={"items": [key]},
        selection_digest=digest,
        actor_ref=ACTOR,
        at=KNOWLEDGE_NOW,
    )


def finalization(
    access: InvocationAccess, submission_ids: tuple[str, ...]
) -> FinalizationCandidate:
    return FinalizationCandidate(
        scope=access.scope,
        run_id=access.origin.run_id,
        operation_ref=access.origin.operation_id,
        operation_attempt=access.origin.attempt,
        execution_generation=access.origin.generation,
        invocation_ref=access.invocation_ref,
        outcome="fulfilled",
        submission_ids=submission_ids,
        report={"outcome": "fulfilled"},
        report_digest=D1,
        actor_ref=ACTOR,
        at=KNOWLEDGE_NOW,
    )


def sealed_plan(
    access: InvocationAccess, *, operation_id: str = "op-consumer"
) -> SealedTransferPlan:
    members = report_members()
    plan = seal_plan(
        plan_id=str(uuid4()),
        receiver=ReceiverRef(
            scope=access.scope, run_id=access.origin.run_id, operation_id=operation_id
        ),
        selection=selection(report_input()),
        configuration_ref="erc:sha256:" + "0" * 64,
        host_state_ref=None,
        members=members,
        overhead=OVERHEAD,
        inline_texts={m.member_key: '{"report":"r7"}' for m in members if m.part == "manifest"},
    )
    assert isinstance(plan, SealedTransferPlan), plan
    return plan


def receipt(plan: SealedTransferPlan, attempt: int) -> DeliveryReceipt:
    return DeliveryReceipt(
        receipt_id=str(uuid4()),
        plan_id=plan.plan_id,
        plan_digest=plan.digest,
        receiver_attempt=ReceiverAttempt(
            operation_attempt=attempt, execution_generation=1, invocation_ref=f"inv-{attempt}"
        ),
        realized_backend="sandbox",
        sequence=99,
        delivered=tuple(_deliveries(plan)),
        current_access_refs=(),
        resource_usage=ResourceUsage(overhead=OVERHEAD, total_tokens=10, headroom_tokens=1),
        result="ready",
        correlation_id=f"correlation-{attempt}",
    )


def observation(
    access: InvocationAccess, ref: str, *, seconds: int = 0, readable: bool = True
) -> RetainedReadObservation:
    return RetainedReadObservation(
        observation_id=str(uuid4()),
        run_id=access.origin.run_id,
        invocation_ref=access.invocation_ref,
        handle="kh:fixture/report/r-1@research_report.v1",
        read_observation_ref=ref,
        readable=readable,
        observed_at=KNOWLEDGE_NOW + timedelta(seconds=seconds),
        expected_digest=D1,
        observed_digest=D1 if readable else None,
        byte_count=4 if readable else None,
    )


# ---------------------------------------------------------------- journal


async def journal_prepare_is_idempotent_and_conflicts(subject: KnowledgeSubject) -> None:
    journal, access = subject.journal, subject.access()
    record = await journal.prepare(prepare(access, "effect-1"))
    assert (record.effect_key, record.state, record.version) == (
        "effect-1",
        JournalState.PREPARED,
        1,
    )
    assert (record.operation_ref, record.operation_attempt) == (access.origin.operation_id, 1)
    again = await journal.prepare(prepare(access, "effect-1"))
    assert again.knowledge_operation_id == record.knowledge_operation_id and again.version == 1
    with pytest.raises(EffectConflict):
        await journal.prepare(prepare(access, "effect-1", bound=D2))
    assert await journal.lookup(access.scope, "effect-1") == record
    assert await journal.lookup(access.scope, "effect-never-prepared") is None
    assert await journal.lookup(subject.other_scope, "effect-1") is None
    assert await journal.transitions(access.scope, "effect-1") == [(None, JournalState.PREPARED)]
    # The same effect key in another tenant is its own row.
    theirs = await journal.prepare(
        prepare(subject.access(scope=subject.other_scope), "effect-1", bound=D2)
    )
    assert theirs.knowledge_operation_id != record.knowledge_operation_id
    assert (await journal.lookup(access.scope, "effect-1")) == record


async def journal_advances_by_compare_and_set(subject: KnowledgeSubject) -> None:
    journal, access = subject.journal, subject.access()
    scope = access.scope
    await journal.prepare(prepare(access, "effect-1"))
    coordinates = {
        "run_id": access.origin.run_id,
        "operation_ref": access.origin.operation_id,
    }
    assert [
        item.effect_key
        for item in await journal.open_for_attempt(scope, operation_attempt=1, **coordinates)
    ] == ["effect-1"]
    dispatch: dict[str, Any] = {
        "dispatch_id": str(uuid4()),
        "envelope_digest": D1,
        "protocol_version": "ks.knowledge_operation.v2",
        "caller": access.wire_origin(),
        "at": KNOWLEDGE_NOW,
    }
    dispatched = await journal.dispatch(scope, "effect-1", expected_version=1, **dispatch)
    assert (dispatched.state, dispatched.version) == (JournalState.DISPATCHED, 2)
    with pytest.raises(JournalVersionConflict):
        await journal.dispatch(scope, "effect-1", expected_version=1, **dispatch)
    handled = await journal.record_handle(
        scope, "effect-1", expected_version=2, operation_id="remote-1", at=KNOWLEDGE_NOW
    )
    assert (handled.state, handled.version, handled.operation_id) == (
        JournalState.DISPATCHED,
        3,
        "remote-1",
    )
    settled = await journal.settle(
        scope,
        "effect-1",
        expected_version=3,
        settlement=Settlement(
            state=JournalState.APPLIED, terminal_receipt_ref="receipt-1", receipt_digest=D1
        ),
        at=KNOWLEDGE_NOW,
    )
    assert (settled.state, settled.version, settled.terminal_receipt_ref) == (
        JournalState.APPLIED,
        4,
        "receipt-1",
    )
    assert await journal.open_for_attempt(scope, operation_attempt=1, **coordinates) == []
    assert await journal.open_for_operation(scope, **coordinates) == []
    assert await journal.transitions(scope, "effect-1") == [
        (None, JournalState.PREPARED),
        (JournalState.PREPARED, JournalState.DISPATCHED),
        # Every version is a transition row, a handle recorded in place included.
        (JournalState.DISPATCHED, JournalState.DISPATCHED),
        (JournalState.DISPATCHED, JournalState.APPLIED),
    ]


async def journal_refuses_moves_a_row_cannot_make(subject: KnowledgeSubject) -> None:
    journal, access = subject.journal, subject.access()
    scope = access.scope
    await journal.prepare(prepare(access, "effect-1"))
    # Only a dispatched row can become uncertain; a refused move is a lost compare-and-set.
    with pytest.raises(JournalVersionConflict):
        await journal.mark_uncertain(scope, "effect-1", expected_version=1, at=KNOWLEDGE_NOW)
    with pytest.raises(JournalVersionConflict):
        await journal.mark_uncertain(
            scope, "effect-never-prepared", expected_version=1, at=KNOWLEDGE_NOW
        )
    # Another tenant cannot move this tenant's row.
    with pytest.raises(JournalVersionConflict):
        await journal.record_handle(
            subject.other_scope, "effect-1", expected_version=1, operation_id="x", at=KNOWLEDGE_NOW
        )
    rejected = await journal.settle(
        scope,
        "effect-1",
        expected_version=1,
        settlement=Settlement(state=JournalState.REJECTED, refusal_code="REFUSED"),
        at=KNOWLEDGE_NOW,
    )
    assert (rejected.state, rejected.version) == (JournalState.REJECTED, 2)
    # A terminal row accepts no further move.
    with pytest.raises(JournalVersionConflict):
        await journal.record_handle(
            scope, "effect-1", expected_version=2, operation_id="late", at=KNOWLEDGE_NOW
        )
    with pytest.raises(JournalVersionConflict):
        await journal.settle(
            scope,
            "effect-1",
            expected_version=2,
            settlement=Settlement(state=JournalState.APPLIED),
            at=KNOWLEDGE_NOW,
        )
    final = await journal.lookup(scope, "effect-1")
    assert final is not None and (final.state, final.version, final.operation_id) == (
        JournalState.REJECTED,
        2,
        None,
    )


# ---------------------------------------------------------------- handles


async def handles_record_once_and_observe_forward(subject: KnowledgeSubject) -> None:
    handles, access = subject.handles, subject.access()
    scope = access.scope
    record = await handles.record(handle_candidate(access, "remote-1"))
    assert (record.state, record.remote_revision, record.version) == ("queued", 0, 1)
    assert (
        await handles.record(handle_candidate(access, "remote-1"))
    ).handle_id == record.handle_id
    # The same request answered with a second remote id is still the one recorded handle.
    same_request = await handles.record(
        handle_candidate(access, "remote-2", request_id="request:remote-1")
    )
    assert same_request.handle_id == record.handle_id
    assert await handles.get(scope, BINDING, "remote-2") is None
    running = await handles.observe(
        scope, BINDING, status(access, "remote-1", "running", 1), at=KNOWLEDGE_NOW
    )
    assert (running.state, running.remote_revision, running.version) == ("running", 1, 2)
    # A stale or regressing poll never moves the handle.
    assert (
        await handles.observe(
            scope, BINDING, status(access, "remote-1", "queued", 2), at=KNOWLEDGE_NOW
        )
        == running
    )
    assert (
        await handles.observe(
            scope, BINDING, status(access, "remote-1", "running", 1), at=KNOWLEDGE_NOW
        )
        == running
    )
    assert [item.handle_id for item in await handles.open_for_run(scope, access.origin.run_id)] == [
        record.handle_id
    ]
    assert [
        item.handle_id for item in await handles.open_for_invocation(scope, access.invocation_ref)
    ] == [record.handle_id]
    done = await handles.observe(
        scope, BINDING, status(access, "remote-1", "succeeded", 3), at=KNOWLEDGE_NOW
    )
    assert (done.state, done.version, done.terminal) == ("succeeded", 3, True)
    assert (
        await handles.observe(
            scope, BINDING, status(access, "remote-1", "running", 4), at=KNOWLEDGE_NOW
        )
        == done
    )
    assert await handles.open_for_run(scope, access.origin.run_id) == []
    assert await handles.open_for_invocation(scope, access.invocation_ref) == []
    assert await handles.get(scope, BINDING, "remote-1") == done
    with pytest.raises(LookupError):
        await handles.observe(
            scope, BINDING, status(access, "remote-never", "running", 1), at=KNOWLEDGE_NOW
        )


async def handles_keep_the_first_cancel_request(subject: KnowledgeSubject) -> None:
    handles, access = subject.handles, subject.access()
    scope = access.scope
    await handles.record(handle_candidate(access, "remote-1"))
    first = await handles.request_cancel(scope, BINDING, "remote-1", "cancel-1", at=KNOWLEDGE_NOW)
    assert (first.cancel_request_id, first.version) == ("cancel-1", 2)
    second = await handles.request_cancel(scope, BINDING, "remote-1", "cancel-2", at=KNOWLEDGE_NOW)
    assert second == first
    with pytest.raises(LookupError):
        await handles.request_cancel(scope, BINDING, "remote-never", "cancel-1", at=KNOWLEDGE_NOW)


async def handles_are_scoped_by_tenant(subject: KnowledgeSubject) -> None:
    handles, access = subject.handles, subject.access()
    other = subject.other_scope
    mine = await handles.record(handle_candidate(access, "remote-1"))
    assert await handles.get(other, BINDING, "remote-1") is None
    assert await handles.open_for_run(other, access.origin.run_id) == []
    with pytest.raises(LookupError):
        await handles.observe(
            other, BINDING, status(access, "remote-1", "running", 1), at=KNOWLEDGE_NOW
        )
    with pytest.raises(LookupError):
        await handles.request_cancel(other, BINDING, "remote-1", "cancel-1", at=KNOWLEDGE_NOW)
    theirs = await handles.record(handle_candidate(subject.access(scope=other), "remote-1"))
    assert theirs.handle_id != mine.handle_id
    assert await handles.get(access.scope, BINDING, "remote-1") == mine


# ---------------------------------------------------------------- submissions


async def submissions_replay_conflict_and_close(subject: KnowledgeSubject) -> None:
    store, access = subject.submissions, subject.access()
    scope = access.scope
    first = await store.record_selection(submission(access, "call-1"))
    assert (first.revision, first.assessment_state, first.version) == (1, "pending", 1)
    assert (
        await store.record_selection(submission(access, "call-1"))
    ).submission_id == first.submission_id
    with pytest.raises(SubmissionConflict):
        await store.record_selection(submission(access, "call-1", digest=D2))
    second = await store.record_selection(submission(access, "call-2", digest=D2))
    other_obligation = await store.record_selection(
        submission(access, "call-1", obligation="draft.alpha")
    )
    assert (second.revision, other_obligation.revision) == (2, 1)
    listed = await store.list_for_invocation(scope, access.invocation_ref)
    assert [(item.obligation_id, item.revision) for item in listed] == [
        ("draft.alpha", 1),
        ("draft.report", 1),
        ("draft.report", 2),
    ]
    final = await store.finalize(finalization(access, (first.submission_id, second.submission_id)))
    again = await store.finalize(finalization(access, (first.submission_id,)))
    assert again.finalization_id == final.finalization_id
    assert again.submission_ids == (first.submission_id, second.submission_id)
    with pytest.raises(SubmissionClosed):
        await store.record_selection(submission(access, "call-3"))
    with pytest.raises(SubmissionClosed):
        await store.record_selection(submission(access, "call-1"))


async def submission_assessment_moves_by_compare_and_set(subject: KnowledgeSubject) -> None:
    store, access = subject.submissions, subject.access()
    scope = access.scope
    row = await store.record_selection(submission(access, "call-1"))
    pending = await store.record_selection(submission(access, "call-2", digest=D2))
    assessing = await store.start_assessment(
        scope,
        row.submission_id,
        expected_version=1,
        operation_id="assess-1",
        binding_id=BINDING,
        actor_ref=ACTOR,
        at=KNOWLEDGE_NOW,
    )
    assert (assessing.assessment_state, assessing.version, assessing.assessment_operation_id) == (
        "assessing",
        2,
        "assess-1",
    )
    with pytest.raises(JournalVersionConflict):
        await store.start_assessment(
            scope,
            row.submission_id,
            expected_version=1,
            operation_id="assess-2",
            binding_id=BINDING,
            actor_ref=ACTOR,
            at=KNOWLEDGE_NOW,
        )
    # Only an assessing submission records its assessment.
    with pytest.raises(JournalVersionConflict):
        await store.record_assessment(
            scope,
            pending.submission_id,
            expected_version=1,
            state="assessed",
            assessment_ref="assessment-1",
            assessment_digest=D1,
            actor_ref=ACTOR,
            at=KNOWLEDGE_NOW,
        )
    # Another tenant cannot move this tenant's submission.
    with pytest.raises(JournalVersionConflict):
        await store.record_assessment(
            subject.other_scope,
            row.submission_id,
            expected_version=2,
            state="assessed",
            assessment_ref="assessment-1",
            assessment_digest=D1,
            actor_ref=ACTOR,
            at=KNOWLEDGE_NOW,
        )
    assessed = await store.record_assessment(
        scope,
        row.submission_id,
        expected_version=2,
        state="assessed",
        assessment_ref="assessment-1",
        assessment_digest=D1,
        actor_ref=ACTOR,
        at=KNOWLEDGE_NOW,
    )
    assert (assessed.assessment_state, assessed.version, assessed.assessment_ref) == (
        "assessed",
        3,
        "assessment-1",
    )
    assert await store.list_for_invocation(subject.other_scope, access.invocation_ref) == []


# ---------------------------------------------------------------- transfer plans


async def a_receiver_has_one_sealed_plan(subject: KnowledgeSubject) -> None:
    store, access = subject.transfer_plans, subject.access()
    plan = sealed_plan(access)
    assert await store.seal(plan) == plan
    assert await store.seal(plan) == plan
    rival_values = plan.model_dump(mode="json") | {"plan_id": str(uuid4())}
    rival_values["digest"] = plan_digest(rival_values)
    with pytest.raises(TransferPlanConflict):
        await store.seal(SealedTransferPlan.model_validate(rival_values))
    assert await store.plan_for(access.scope, plan.receiver_key) == plan
    assert await store.get(access.scope, plan.plan_id) == plan
    assert await store.plan_for(subject.other_scope, plan.receiver_key) is None
    assert await store.get(subject.other_scope, plan.plan_id) is None


async def delivery_receipts_are_appended_in_sequence(subject: KnowledgeSubject) -> None:
    store, access = subject.transfer_plans, subject.access()
    plan = await store.seal(sealed_plan(access))
    first = await store.append_receipt(access.scope, receipt(plan, 1))
    second = await store.append_receipt(access.scope, receipt(plan, 2))
    assert (first.sequence, second.sequence) == (1, 2)
    assert await store.receipts(access.scope, plan.plan_id) == (first, second)
    assert await store.receipts(subject.other_scope, plan.plan_id) == ()
    with pytest.raises(ValueError):
        await store.append_receipt(subject.other_scope, receipt(plan, 3))
    unsealed = sealed_plan(access, operation_id="op-never-sealed")
    with pytest.raises(ValueError):
        await store.append_receipt(access.scope, receipt(unsealed, 1))
    files = [
        plan.member(item.member_key).source_ref
        for item in plan.placements
        if item.placement == "file"
    ]
    found = await store.file_realizations(access.scope, files)
    assert set(found) == set(files)
    assert all(
        value.startswith(f"transfer-receipt:{first.receipt_id}#") for value in found.values()
    )
    assert await store.file_realizations(subject.other_scope, files) == {}
    assert await store.file_realizations(access.scope, []) == {}


# ---------------------------------------------------------------- lineage


async def registration_lineage_keeps_one_producer(subject: KnowledgeSubject) -> None:
    store, first, second = subject.lineage, subject.access(), subject.access(operation_id="op-2")
    handle_ref = "kh:fixture/artifact/shared@artifact.v1"
    entries = registration_entries(first.origin, handle_ref, D1, "receipt-1")
    assert (
        await store.record_registration(first.scope, entries, actor_ref=ACTOR, at=KNOWLEDGE_NOW)
        == 3
    )
    assert (
        await store.record_registration(first.scope, entries, actor_ref=ACTOR, at=KNOWLEDGE_NOW)
        == 0
    )
    reuse = registration_entries(second.origin, handle_ref, D1, "receipt-2")
    # A second registration of identical bytes adds its caller and receipt, never a producer.
    assert (
        await store.record_registration(first.scope, reuse, actor_ref=ACTOR, at=KNOWLEDGE_NOW) == 2
    )
    facts = await store.facts(first.scope, handle_ref)
    assert [fact.actor_ref for fact in facts if fact.role is ProvenanceRole.PRODUCER] == [
        first.invocation_ref
    ]
    assert len(facts) == 5
    changed = [
        replace(entry, subject_digest=D2)
        for entry in registration_entries(second.origin, handle_ref, D1, "receipt-3")
    ]
    with pytest.raises(ValueError, match="immutable subject identity"):
        await store.record_registration(first.scope, changed, actor_ref=ACTOR, at=KNOWLEDGE_NOW)
    assert len(await store.facts(first.scope, handle_ref)) == 5
    assert await store.facts(subject.other_scope, handle_ref) == []


async def lineage_facts_read_in_recorded_order(subject: KnowledgeSubject) -> None:
    store, access = subject.lineage, subject.access()
    handle_ref = "kh:fixture/artifact/ordered@artifact.v1"
    early = registration_entries(access.origin, handle_ref, D1, "receipt-1")
    late = registration_entries(
        subject.access(operation_id="op-2").origin, handle_ref, D1, "receipt-2"
    )
    await store.record_registration(
        access.scope, late, actor_ref=ACTOR, at=KNOWLEDGE_NOW + timedelta(seconds=5)
    )
    await store.record_registration(access.scope, early, actor_ref=ACTOR, at=KNOWLEDGE_NOW)
    facts = await store.facts(access.scope, handle_ref)
    # Ordered by recorded time (then by fact identity): the earlier write reads first.
    assert [fact.fact["receipt"] for fact in facts][:2] == ["receipt-1", "receipt-1"]
    assert [fact.fact["receipt"] for fact in facts][2:] == ["receipt-2"] * 3


async def strict_lineage_refuses_a_second_producer(subject: KnowledgeSubject) -> None:
    store, first, second = subject.lineage, subject.access(), subject.access(operation_id="op-2")
    handle_ref = "kh:fixture/artifact/strict@artifact.v1"
    await store.record(
        first.scope,
        registration_entries(first.origin, handle_ref, D1, "r1"),
        actor_ref=ACTOR,
        at=KNOWLEDGE_NOW,
    )
    with pytest.raises(ValueError):
        await store.record(
            first.scope,
            registration_entries(second.origin, handle_ref, D1, "r2"),
            actor_ref=ACTOR,
            at=KNOWLEDGE_NOW,
        )
    assert len(await store.facts(first.scope, handle_ref)) == 3


# ---------------------------------------------------------------- retained reads


async def retained_reads_are_written_once_in_observed_order(subject: KnowledgeSubject) -> None:
    store, access = subject.retained_reads, subject.access()
    late, early = observation(access, "read-b", seconds=5), observation(access, "read-a", seconds=1)
    assert await store.record(access.scope, [late, early], actor_ref=ACTOR, at=KNOWLEDGE_NOW) == 2
    replay = [observation(access, "read-b", seconds=5)]
    assert await store.record(access.scope, replay, actor_ref=ACTOR, at=KNOWLEDGE_NOW) == 0
    assert await store.record(access.scope, [], actor_ref=ACTOR, at=KNOWLEDGE_NOW) == 0
    stored = await store.observations(access.scope, access.invocation_ref)
    assert [item.read_observation_ref for item in stored] == ["read-a", "read-b"]
    assert [item.observation_id for item in stored] == [early.observation_id, late.observation_id]
    assert await store.observations(subject.other_scope, access.invocation_ref) == []
    unreadable = observation(access, "read-c", seconds=9, readable=False)
    assert await store.record(access.scope, [unreadable], actor_ref=ACTOR, at=KNOWLEDGE_NOW) == 1
    assert len(await store.observations(access.scope, access.invocation_ref)) == 3


SCENARIOS: tuple[Scenario, ...] = (
    journal_prepare_is_idempotent_and_conflicts,
    journal_advances_by_compare_and_set,
    journal_refuses_moves_a_row_cannot_make,
    handles_record_once_and_observe_forward,
    handles_keep_the_first_cancel_request,
    handles_are_scoped_by_tenant,
    submissions_replay_conflict_and_close,
    submission_assessment_moves_by_compare_and_set,
    a_receiver_has_one_sealed_plan,
    delivery_receipts_are_appended_in_sequence,
    registration_lineage_keeps_one_producer,
    lineage_facts_read_in_recorded_order,
    strict_lineage_refuses_a_second_producer,
    retained_reads_are_written_once_in_observed_order,
)

__all__ = ["SCENARIOS", "KnowledgeSubject", "Scenario"]
