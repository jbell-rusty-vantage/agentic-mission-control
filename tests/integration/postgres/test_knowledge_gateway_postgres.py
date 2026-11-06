"""M05/K05 seam on a disposable PostgreSQL 17 (restricted runtime login, forced RLS, 1.7.0).

The gateway and submission service run against the real journal, handle, submission and
transfer tables, with real Ed25519 credentials verified by the fake binding: concurrent
same-key invocations admit one row and transmit one effect; another tenant sees nothing; a
crash after native commit leaves ``uncertain`` until a fresh recovery settles it from the
receipt lookup; submission keys are idempotent and a changed selection is MCE02; a stop during
review reaches the binding after a restart through the durable handle; the independent
assessment handoff holds; a sealed transfer plan is immutable, one per receiver, and each
attempt appends its receipt (1.7.0 / 0057).
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from collections.abc import AsyncIterator
from datetime import timedelta

import asyncpg
import pytest
import pytest_asyncio

from mission_control.adapters.postgres.context.transfer_plans import PostgresTransferPlanStore
from mission_control.adapters.postgres.knowledge.handles import PostgresKnowledgeHandleStore
from mission_control.adapters.postgres.knowledge.operations import PostgresKnowledgeJournal
from mission_control.adapters.postgres.knowledge.submissions import PostgresOutputSubmissionStore
from mission_control.application.context.materialization import (
    ContextDeliveryBlocked,
    KnowledgeReadAccess,
    MaterializeRequest,
    ProducedOutputResolver,
    TransferMaterializer,
    TransferPlanConflict,
)
from mission_control.application.context.resolution import ContentResolutionService
from mission_control.application.knowledge.access import InvocationAccess, RecoveryAccess
from mission_control.application.knowledge.gateway import KnowledgeGateway
from mission_control.application.knowledge.operations import KnowledgeRefused
from mission_control.application.outputs.submission_service import (
    OutputSelection,
    SubmissionService,
)
from mission_control.application.ports.knowledge import (
    PrepareRequest,
    SubmissionClosed,
    SubmissionConflict,
)
from mission_control.domain.context.transfer import ReceiverAttempt, ReceiverRef
from mission_control.domain.knowledge.effects import EffectConflict, JournalState
from mission_control.domain.outputs.contracts import ExactOutput, OutputForm
from tests.fixtures.knowledge_binding import (
    FakeKnowledgeBinding,
    InMemoryStaging,
    Issuer,
    RecordingMinter,
    SteppingClock,
    knowledge_port,
    model_report,
    report_package,
)
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.integration.postgres.runtime_common import common_db, owner_rows  # noqa: F401
from tests.unit.knowledge.test_gateway import AUDIENCE, BINDING, call, origin

pytestmark = [pytest.mark.asyncio, pytest.mark.common_db]


@pytest_asyncio.fixture
async def pool(common_db: CommonDatabase) -> AsyncIterator[asyncpg.Pool]:  # noqa: F811
    created = await common_db.pool()
    try:
        yield created
    finally:
        await created.close()


def access_for(db: CommonDatabase, tenant: str = "tenant-1", **updates: object) -> InvocationAccess:
    _mc, installation, application, tenant_id = db.scope(tenant).split("/")
    attempt = int(updates.pop("attempt", 1))  # type: ignore[call-overload]
    return InvocationAccess(
        origin=origin(
            attempt,
            installation_id=installation,
            application_id=application,
            tenant_id=tenant_id,
            **updates,
        ),
        subject="mission-control-runtime",
        invocation_id="inv-0001",
        authenticated_at=SteppingClock().now,
    )


def recovery_for(access: InvocationAccess) -> RecoveryAccess:
    source = access.origin
    return RecoveryAccess(
        installation_id=source.installation_id,
        application_id=source.application_id,
        tenant_id=source.tenant_id,
        issuer=source.issuer,
        subject="mission-control-reconciler",
        authority_ref="recovery-grant-7",
        invocation_id="inv-0009",
        authenticated_at=SteppingClock().now,
    )


def stack(pool: asyncpg.Pool, clock: SteppingClock | None = None):
    clock = clock or SteppingClock()
    issuer = Issuer(clock=clock)
    minter = RecordingMinter(issuer.minter())
    client = FakeKnowledgeBinding(verifier=issuer.verifier(), clock=clock)
    journal = PostgresKnowledgeJournal(pool)
    handles = PostgresKnowledgeHandleStore(pool)

    async def sleep(_seconds: float) -> None:
        return None

    def gateway(max_polls: int = 10) -> KnowledgeGateway:
        return KnowledgeGateway(
            client=client,
            journal=journal,
            handles=handles,
            minter=minter,
            content=client,
            knowledge=knowledge_port(BINDING),
            audience=AUDIENCE,
            max_polls=max_polls,
            clock=clock,
            sleep=sleep,
        )

    return clock, minter, client, journal, gateway


def report_item(tenant_id: str, report_id: str = "r-1"):
    package = report_package(report_id, "1", tenant=tenant_id)
    report = package.report
    return package, {
        "kind": "handle",
        "ref": f"kh:{report.binding}/report/{report.id}@{report.version}",
        "digest": report.digest,
    }


async def test_concurrent_same_key_invocations_admit_one_row_and_one_effect(
    common_db: CommonDatabase,  # noqa: F811
    pool: asyncpg.Pool,
) -> None:
    _clock, _minter, client, journal, gateway = stack(pool)
    access = access_for(common_db)
    first, second = await asyncio.gather(
        gateway().invoke(call(), access), gateway().invoke(call(), access)
    )
    assert first.effect_key == second.effect_key
    key = first.effect_key or ""
    assert len(client.calls_of("invoke")) == 1 and len(client.committed) == 1
    rows = await owner_rows(
        common_db,
        "SELECT state, version FROM mission_control.knowledge_operation_journal "
        "WHERE effect_key = $1",
        key,
    )
    assert [(row["state"], row["version"]) for row in rows] == [("applied", 3)]
    assert await journal.transitions(access.scope, key) == [
        (None, JournalState.PREPARED),
        (JournalState.PREPARED, JournalState.DISPATCHED),
        (JournalState.DISPATCHED, JournalState.APPLIED),
    ]

    # Same scoped key, other bound effect: the database itself refuses (MCE01).
    record = await journal.lookup(access.scope, key)
    assert record is not None
    with pytest.raises(EffectConflict):
        await journal.prepare(
            PrepareRequest(
                scope=access.scope,
                effect_key=key,
                semantic_payload_digest=record.semantic_payload_digest,
                bound_effect_digest="sha256:" + "f" * 64,
                originating_origin=record.originating_origin,
                current_caller_origin=record.originating_origin,
                coordinates=access.coordinates(),
                capability_pin=record.capability_pin,
                binding_id=record.binding_id,
                actor_ref="test:conflict",
            )
        )
    with pytest.raises(KnowledgeRefused) as refused:
        await gateway().invoke(call({"intent": "changed"}, effect_key=key), access)
    assert refused.value.code == "EFFECT_CONFLICT"


async def test_journal_and_submissions_are_tenant_isolated(
    common_db: CommonDatabase,  # noqa: F811
    pool: asyncpg.Pool,
) -> None:
    _clock, _minter, _client, journal, gateway = stack(pool)
    mine = access_for(common_db, "tenant-1")
    other = access_for(common_db, "tenant-2")
    result = await gateway().invoke(call(), mine)
    key = result.effect_key or ""
    assert await journal.lookup(mine.scope, key) is not None
    assert await journal.lookup(other.scope, key) is None
    with pytest.raises(KnowledgeRefused) as refused:
        await gateway().reconcile(key, recovery_for(other))
    assert refused.value.code == "NOT_FOUND"

    service = SubmissionService(PostgresOutputSubmissionStore(pool))
    _package, item = report_item(mine.origin.tenant_id)
    selection = OutputSelection.model_validate({"items": [item]})
    await service.submit(mine, "report", selection, "tc-1")
    store = PostgresOutputSubmissionStore(pool)
    assert len(await store.list_for_invocation(mine.scope, mine.invocation_ref)) == 1
    assert await store.list_for_invocation(other.scope, mine.invocation_ref) == []


async def test_crash_after_dispatch_is_uncertain_until_recovery_settles_from_receipt(
    common_db: CommonDatabase,  # noqa: F811
    pool: asyncpg.Pool,
) -> None:
    clock, minter, client, _journal, gateway = stack(pool)
    access = access_for(common_db)
    client.invoke_script.append("lost")  # native commit happened, the answer was lost
    client.lookups.append("not_found")  # and the immediate lookup raced it
    first = await gateway().invoke(call(), access)
    assert first.state is JournalState.UNCERTAIN
    key = first.effect_key or ""

    clock.advance(timedelta(hours=2))  # process restart long after the invocation ended
    recovered = await gateway().reconcile(key, recovery_for(access))
    assert recovered.state is JournalState.APPLIED
    assert recovered.lookup is not None and recovered.lookup.disposition == "found"
    assert len(client.calls_of("invoke")) == 1

    rows = await owner_rows(
        common_db,
        "SELECT transition.from_state, transition.to_state, transition.reconciled, "
        "transition.recorded_by_actor_ref FROM mission_control.knowledge_operation_transition "
        "transition JOIN mission_control.knowledge_operation_journal journal USING "
        "(installation_id, application_id, tenant_id, knowledge_operation_id) "
        "WHERE journal.effect_key = $1 ORDER BY transition.transition_version",
        key,
    )
    assert [(row["from_state"], row["to_state"]) for row in rows] == [
        (None, "prepared"),
        ("prepared", "dispatched"),
        ("dispatched", "uncertain"),
        ("uncertain", "applied"),
    ]
    assert rows[-1]["reconciled"] is True
    assert all(row["recorded_by_actor_ref"] for row in rows)
    (journal_row,) = await owner_rows(
        common_db,
        "SELECT to_jsonb(journal) AS body FROM mission_control.knowledge_operation_journal "
        "journal WHERE effect_key = $1",
        key,
    )
    body = journal_row["body"]
    assert body is not None
    for claims in minter.minted:  # no credential bytes are ever journalled
        assert minter.inner.sign_claims(claims) not in body
        assert claims.jti not in body
    assert json.loads(body)["terminal_receipt_ref"] == client.committed[key].receipt_ref()


@pytest.mark.parametrize("code", ["INTERNAL", "UNRESOLVED_EFFECT"])
async def test_a_refusal_after_the_native_commit_stays_uncertain_across_a_restart(
    common_db: CommonDatabase,  # noqa: F811
    pool: asyncpg.Pool,
    code: str,
) -> None:
    """WI-05: the binding committed natively, lost its protocol receipt and refused. The durable
    journal never records it rejected (the guard allows no rejected -> applied edge); a fresh
    gateway after a restart settles it from the reconstructed original receipt, no redispatch."""

    clock, _minter, client, _journal, gateway = stack(pool)
    access = access_for(common_db)
    client.invoke_script.append(f"commit_refuse:{code}")
    client.lookups.append("unresolved")
    first = await gateway().invoke(call(), access)
    assert first.state is JournalState.UNCERTAIN and first.refusal_code == "UNRESOLVED_EFFECT"
    key = first.effect_key or ""

    clock.advance(timedelta(hours=2))
    recovered = await gateway().reconcile(key, recovery_for(access))
    assert recovered.state is JournalState.APPLIED
    assert len(client.calls_of("invoke")) == 1
    rows = await owner_rows(
        common_db,
        "SELECT transition.to_state FROM mission_control.knowledge_operation_transition "
        "transition JOIN mission_control.knowledge_operation_journal journal USING "
        "(installation_id, application_id, tenant_id, knowledge_operation_id) "
        "WHERE journal.effect_key = $1 ORDER BY transition.transition_version",
        key,
    )
    assert [row["to_state"] for row in rows] == ["prepared", "dispatched", "uncertain", "applied"]


async def test_submission_key_is_idempotent_and_a_changed_selection_is_mce02(
    common_db: CommonDatabase,  # noqa: F811
    pool: asyncpg.Pool,
) -> None:
    service = SubmissionService(PostgresOutputSubmissionStore(pool))
    access = access_for(common_db)

    def selection(letter: str) -> OutputSelection:
        return OutputSelection.model_validate(
            {
                "items": [
                    {
                        "kind": "handle",
                        "ref": f"kh:aiengineer-postgres/report/r-{letter}@research-report.v2",
                        "digest": "sha256:" + letter * 64,
                    }
                ]
            }
        )

    first = await service.submit(access, "report", selection("a"), "tc-1")
    retry = await service.submit(access, "report", selection("a"), "tc-1")
    assert retry == first and first.revision == 1 and first.assessment_state == "pending"
    with pytest.raises(SubmissionConflict):
        await service.submit(access, "report", selection("b"), "tc-1")
    revision = await service.submit(access, "report", selection("b"), "tc-2")
    assert revision.revision == 2 and revision.submission_id != first.submission_id

    identity = access.identity(("report", "summary"))
    report = await service.finalize(identity)
    # Coverage is not fulfillment (1.7.0): without a verdict nothing declared is fulfilled.
    assert report.outcome == "unfulfilled" and report.assessment_state == "pending"
    assert report.outcome_basis == "declared_obligations"
    by_obligation = {item.obligation_id: item for item in report.obligations}
    assert by_obligation["report"].submission_ids == (first.submission_id, revision.submission_id)
    assert by_obligation["summary"].submission_ids == ()
    assert (await service.finalize(identity)).finalization_id == report.finalization_id
    with pytest.raises(SubmissionClosed):
        await service.submit(access, "summary", selection("c"), "tc-3")

    rows = await owner_rows(
        common_db,
        "SELECT assessment_state FROM mission_control.output_submission WHERE invocation_ref = $1",
        access.invocation_ref,
    )
    assert sorted(row["assessment_state"] for row in rows) == ["pending", "pending"]


async def test_stop_during_review_reaches_the_binding_after_a_restart(
    common_db: CommonDatabase,  # noqa: F811
    pool: asyncpg.Pool,
) -> None:
    _clock, _minter, client, _journal, gateway = stack(pool)
    client.operation_statuses["report.assess"] = deque(["running", "waiting_review"])
    access = access_for(common_db)
    started = await gateway(max_polls=2).invoke(
        call({"report": "r-1"}, operation="report.assess", request_key="assess:sub-1"), access
    )
    assert started.handle_record is not None
    assert started.handle_record.state == "waiting_review"

    restarted = gateway()  # a new process: no in-memory handles or outstanding sets
    await restarted.cancel(access, "cancel-review-1")
    await restarted.cancel(access, "cancel-review-2")
    rows = await owner_rows(
        common_db,
        "SELECT state, cancel_request_id, pending_review_ref, remote_revision, version "
        "FROM mission_control.knowledge_operation_handle WHERE request_id = $1",
        "assess:sub-1",
    )
    assert [(r["state"], r["cancel_request_id"]) for r in rows] == [
        ("cancelled", "cancel-review-1")
    ]
    assert rows[0]["pending_review_ref"] is not None and rows[0]["remote_revision"] >= 4
    assert len(client.calls_of("operation.cancel")) == 1


async def test_final_submission_assessment_handoff_is_durable(
    common_db: CommonDatabase,  # noqa: F811
    pool: asyncpg.Pool,
) -> None:
    _clock, _minter, client, _journal, gateway = stack(pool)
    client.operation_statuses["report.assess"] = deque(["running", "running", "succeeded"])
    access = access_for(common_db)
    _package, item = report_item(access.origin.tenant_id)
    store = PostgresOutputSubmissionStore(pool)
    first = SubmissionService(store, assessor=gateway(max_polls=1))
    submitted = await first.submit(
        access, "report", OutputSelection.model_validate({"items": [item]}), "tc-1"
    )
    identity = access.identity(("report",))
    report = await first.finalize(identity, access)
    assert report.outcome_basis == "declared_obligations" and report.open_assessments

    later = SubmissionService(store, assessor=gateway(max_polls=5))
    (settled,) = await later.refresh_assessments(identity, access)
    assert settled.assessed and settled.assessment is not None
    rows = await owner_rows(
        common_db,
        "SELECT submission.assessment_state, submission.assessment_operation_id, "
        "submission.assessment_binding, handle.state AS handle_state, "
        "finalization.outcome_basis FROM mission_control.output_submission submission "
        "JOIN mission_control.knowledge_operation_handle handle ON "
        "handle.remote_operation_id = submission.assessment_operation_id "
        "AND handle.binding_id = submission.assessment_binding "
        "JOIN mission_control.invocation_finalization finalization ON "
        "finalization.invocation_ref = submission.invocation_ref "
        "WHERE submission.submission_id = $1::uuid",
        submitted.submission_id,
    )
    assert [tuple(row) for row in rows] == [
        ("assessed", report.open_assessments[0], BINDING, "succeeded", "declared_obligations")
    ]


async def test_one_sealed_plan_per_receiver_and_appended_attempt_receipts(
    common_db: CommonDatabase,  # noqa: F811
    pool: asyncpg.Pool,
) -> None:
    from tests.unit.context.test_transfer_materializer import (
        OVERHEAD,
        REPORT_INPUT,
        FakeBackend,
        FakeOutputs,
        dependent,
    )

    _clock, _minter, client, _journal, gateway = stack(pool)
    client.operation_statuses["knowledge.read"] = deque(["succeeded"] * 16)
    access = access_for(common_db)
    package, item = report_item(access.origin.tenant_id, "r-9")
    client.register_package(package)
    outputs = FakeOutputs()
    from mission_control.domain.outputs.contracts import OutputContract, OutputObligation

    outputs.obligations.append(
        OutputObligation(
            key="draft.report",
            owner_position="draft",
            contract=OutputContract(form=OutputForm.REFERENCE),
        )
    )
    outputs.accepted.append(
        ExactOutput(
            revision_id="rev-r9",
            run_id=access.origin.run_id,
            obligation_key="draft.report",
            obligation_revision=1,
            deliverable_id="report",
            revision=1,
            form=OutputForm.REFERENCE,
            content_digest=item["digest"],
            candidate={"kind": "handle", "ref": item["ref"]},
            producer_origin_ref="mc-inv:draft",
        )
    )
    reports = ContentResolutionService(gateway())
    staging = InMemoryStaging()
    store = PostgresTransferPlanStore(pool)
    materializer = TransferMaterializer(
        store=store,
        staging=staging,
        custody=staging,
        resolvers={"produced_output": ProducedOutputResolver(outputs, reports=reports)},  # type: ignore[arg-type]
        access={"produced_output": KnowledgeReadAccess(reports)},
    )

    def request(attempt: int) -> MaterializeRequest:
        return MaterializeRequest(
            receiver=ReceiverRef(
                scope=access.scope, run_id=access.origin.run_id, operation_id="op-review-1"
            ),
            attempt=ReceiverAttempt(
                operation_attempt=attempt, execution_generation=1, invocation_ref=f"inv-{attempt}"
            ),
            selection=dependent(REPORT_INPUT),
            configuration_ref="erc:sha256:" + "0" * 64,
            host_state_ref=None,
            overhead=OVERHEAD,
            access=access_for(common_db, attempt=attempt),
        )

    first = await materializer.materialize(request(1), FakeBackend("fake:a"))
    again = await materializer.materialize(request(2), FakeBackend("fake:b"))
    assert again.plan.digest == first.plan.digest
    with pytest.raises(ContextDeliveryBlocked, match="BACKEND_UNREADABLE"):
        await materializer.materialize(request(3), FakeBackend("fake:c", unreadable=("body.md",)))
    # One sealed plan per receiver: another selection for the same receiver conflicts.
    other = first.plan.model_dump(mode="json") | {
        "plan_id": "0" * 8 + "-0000-4000-8000-" + "0" * 12
    }
    from mission_control.domain.context.transfer import SealedTransferPlan, plan_digest

    other["digest"] = plan_digest(other)
    with pytest.raises(TransferPlanConflict):
        await store.seal(SealedTransferPlan.model_validate(other))
    rows = await owner_rows(
        common_db,
        "SELECT receipt.sequence, receipt.operation_attempt, receipt.realized_backend, "
        "receipt.result, count(member.*) AS members, bool_and(member.access_ok) AS access "
        "FROM mission_control.transfer_delivery_receipt receipt "
        "JOIN mission_control.transfer_member_delivery member USING "
        "(installation_id, application_id, tenant_id, delivery_receipt_id) "
        "GROUP BY 1, 2, 3, 4 ORDER BY 1",
    )
    assert [tuple(row) for row in rows] == [
        (1, 1, "fake:a", "ready", 3, True),
        (2, 2, "fake:b", "ready", 3, True),
        (3, 3, "fake:c", "refused", 3, True),
    ]
    plans = await owner_rows(
        common_db,
        "SELECT boundary, member_count, plan_digest FROM mission_control.transfer_plan",
    )
    assert [tuple(row) for row in plans] == [("dependent_stage", 3, first.plan.digest)]
    # Immutable: the runtime role cannot rewrite a sealed plan or a receipt.
    async with pool.acquire() as connection:
        with pytest.raises(asyncpg.PostgresError):
            await connection.execute("UPDATE mission_control.transfer_plan SET member_count = 0")
    # Another tenant sees no plan for the same receiver.
    foreign = access_for(common_db, tenant="tenant-2")
    assert await store.plan_for(foreign.scope, first.plan.receiver_key) is None
    assert await store.get(access.scope, first.plan.plan_id) == first.plan


async def test_content_lineage_persists_production_adoption_and_consumption(
    common_db: CommonDatabase,  # noqa: F811
    pool: asyncpg.Pool,
) -> None:
    from mission_control.adapters.postgres.knowledge.lineage import PostgresContentLineageStore
    from mission_control.application.knowledge.toolset import KnowledgeToolset, LiveInvocation
    from mission_control.application.ports.knowledge import LineageEntry
    from mission_control.domain.knowledge.lineage import (
        ActorKind,
        LineageFact,
        ProvenanceRole,
    )

    clock, _minter, client, _journal, gateway = stack(pool)
    lineage = PostgresContentLineageStore(pool)
    access = access_for(common_db)
    toolset = KnowledgeToolset(
        gateway=gateway(),
        submissions=SubmissionService(PostgresOutputSubmissionStore(pool)),
        issuer="mission-control",
        clock=clock,
        lineage=lineage,
    )
    origin = access.origin

    def live(operation: str) -> LiveInvocation:
        return LiveInvocation(
            request_scope=access.scope,
            run_id=origin.run_id,
            operation_id=operation,
            operation_attempt=1,
            execution_generation=1,
            lane="deep_agents",
            mission_id=origin.mission_id,
            activation_id=origin.activation_id,
        )

    registered = await toolset.dispatch(
        "report_register",
        {"report": model_report("r-lineage")},
        live("op-draft"),
        tool_call_id="c-1",
    )
    assert registered["ok"]
    (report,) = next(iter(client.committed.values())).affectedRefs
    handle = f"kh:{report.binding}/report/{report.id}@{report.version}"
    item = {"kind": "handle", "ref": handle, "digest": report.digest}
    await toolset.dispatch(
        "submit_output",
        {"obligation": "report", "items": [item]},
        live("op-draft"),
        tool_call_id="c-2",
    )
    await toolset.dispatch(
        "submit_output",
        {"obligation": "report", "items": [item]},
        live("op-review"),
        tool_call_id="c-3",
    )
    consumer = LineageEntry(
        fact=LineageFact(
            subject_handle=handle,
            role=ProvenanceRole.CONSUMER,
            actor_kind=ActorKind.ORIGIN,
            actor_ref="mc-inv:review",
            actor_origin=origin,
        ),
        subject_kind="report",
        subject_digest=report.digest,
        run_id=origin.run_id,
    )
    assert await lineage.record(access.scope, [consumer], actor_ref="test", at=clock.now) == 1
    assert await lineage.record(access.scope, [consumer], actor_ref="test", at=clock.now) == 0
    rows = await owner_rows(
        common_db,
        "SELECT role, actor_kind, subject_kind, fact->>'act' AS act, "
        "knowledge_operation_id IS NOT NULL AS journaled FROM mission_control.content_lineage "
        "WHERE subject_handle = $1 ORDER BY role",
        handle,
    )
    assert [tuple(row) for row in rows] == [
        ("adopter", "obligation", "report", "adoption", False),
        ("caller", "origin", "report", "registration", True),
        ("consumer", "origin", "report", None, False),
        ("producer", "origin", "report", "production", True),
        ("receipt", "receipt", "report", None, True),
    ]
    second_producer = LineageEntry(
        fact=LineageFact(
            subject_handle=handle,
            role=ProvenanceRole.PRODUCER,
            actor_kind=ActorKind.EXTERNAL,
            actor_ref="external:someone",
            fact={"act": "production"},
        ),
        subject_kind="report",
    )
    with pytest.raises(asyncpg.UniqueViolationError):
        await lineage.record(access.scope, [second_producer], actor_ref="test", at=clock.now)


async def test_a_host_grant_is_recorded_with_the_retry_dispatch_it_authorized(
    common_db: CommonDatabase,  # noqa: F811
    pool: asyncpg.Pool,
) -> None:
    """R2-MC D2 on the 1.6.0 journal: attempt 1 leaves the effect uncertain; the host's grant
    for attempt 2 is found through `open_for_operation` and recorded on the dispatch row and
    its transition."""

    from dataclasses import replace

    from mission_control.application.knowledge.access import RecoveryGrant

    _clock, _minter, client, journal, gateway = stack(pool)
    first = access_for(common_db)
    client.invoke_script.append("lost")
    client.lookups.extend(["not_found", "not_found"])
    lost = await gateway().invoke(call(), first)
    assert lost.state is JournalState.UNCERTAIN
    key = lost.effect_key or ""
    second = access_for(common_db, attempt=2)
    (row,) = await journal.open_for_operation(
        second.scope, run_id=second.origin.run_id, operation_ref=second.origin.operation_id
    )
    assert row.effect_key == key and row.operation_attempt == 1
    grant = RecoveryGrant(
        authority_ref="host-retry:pg-1",
        effect_key=row.effect_key,
        bound_effect_digest=row.bound_effect_digest,
    )
    resent = await gateway().invoke(call(), replace(second, recovery_grants=(grant,)))
    assert resent.state is JournalState.APPLIED
    assert (await journal.lookup(second.scope, key)).recovery_authority_ref == grant.authority_ref
    rows = await owner_rows(
        common_db,
        "SELECT transition.to_state, transition.recovery_authority_ref "
        "FROM mission_control.knowledge_operation_transition transition "
        "JOIN mission_control.knowledge_operation_journal journal USING "
        "(installation_id, application_id, tenant_id, knowledge_operation_id) "
        "WHERE journal.effect_key = $1 ORDER BY transition.transition_version",
        key,
    )
    assert [(r["to_state"], r["recovery_authority_ref"]) for r in rows][-2:] == [
        ("dispatched", "host-retry:pg-1"),
        ("applied", "host-retry:pg-1"),
    ]
    assert rows[1]["recovery_authority_ref"] is None  # attempt 1 dispatched as the originator


async def test_registration_reuse_is_atomic_under_concurrent_writers(
    common_db: CommonDatabase,  # noqa: F811
    pool: asyncpg.Pool,
) -> None:
    from mission_control.adapters.postgres.knowledge.lineage import PostgresContentLineageStore
    from mission_control.domain.knowledge.lineage import ProvenanceRole
    from tests.unit.knowledge.test_registration_lineage import registration_entries

    store = PostgresContentLineageStore(pool)
    first = access_for(common_db, operation_id="register-first")
    second = access_for(common_db, operation_id="register-second")
    clock = SteppingClock()
    handles = [
        "kh:fixture/artifact/shared-a@artifact.v1",
        "kh:fixture/artifact/shared-b@artifact.v1",
    ]
    digest = "sha256:" + "a" * 64
    batches = [
        [
            entry
            for handle in order
            for entry in registration_entries(access.origin, handle, digest, receipt)
        ]
        for access, order, receipt in (
            (first, handles, "receipt-1"),
            (second, handles[::-1], "receipt-2"),
        )
    ]
    counts = await asyncio.wait_for(
        asyncio.gather(
            *(
                store.record_registration(first.scope, batch, actor_ref="test", at=clock.now)
                for batch in batches
            )
        ),
        timeout=15,
    )
    assert sum(counts) == 10
    for batch in batches:
        assert (
            await store.record_registration(first.scope, batch, actor_ref="test", at=clock.now) == 0
        )
    for handle in handles:
        facts = await store.facts(first.scope, handle)
        producers = [fact for fact in facts if fact.role is ProvenanceRole.PRODUCER]
        assert len(producers) == 1
        assert producers[0].actor_ref in {first.invocation_ref, second.invocation_ref}
        assert {fact.actor_ref for fact in facts if fact.role is ProvenanceRole.CALLER} == {
            first.invocation_ref,
            second.invocation_ref,
        }
        assert len([fact for fact in facts if fact.role is ProvenanceRole.RECEIPT]) == 2
        assert not any(fact.role is ProvenanceRole.ADOPTER for fact in facts)


async def test_registration_subject_mismatch_rolls_back_without_weakening_strict_record(
    common_db: CommonDatabase,  # noqa: F811
    pool: asyncpg.Pool,
) -> None:
    from dataclasses import replace

    from mission_control.adapters.postgres.knowledge.lineage import PostgresContentLineageStore
    from tests.unit.knowledge.test_registration_lineage import registration_entries

    store = PostgresContentLineageStore(pool)
    first = access_for(common_db, operation_id="register-first")
    second = access_for(common_db, operation_id="register-second")
    clock = SteppingClock()
    handle = "kh:fixture/artifact/immutable@artifact.v1"
    entries = registration_entries(first.origin, handle, "sha256:" + "a" * 64, "receipt-1")
    await store.record_registration(first.scope, entries, actor_ref="test", at=clock.now)
    other = registration_entries(second.origin, handle, "sha256:" + "a" * 64, "receipt-2")
    for field, value in (("subject_digest", "sha256:" + "b" * 64), ("subject_kind", "report")):
        new = registration_entries(
            second.origin,
            "kh:fixture/artifact/a-new@artifact.v1",
            "sha256:" + "c" * 64,
            "receipt-3",
        )
        bad = [replace(entry, **{field: value}) for entry in other]
        with pytest.raises(ValueError, match="immutable subject identity"):
            await store.record_registration(
                first.scope, [*new, *bad], actor_ref="test", at=clock.now
            )
        assert not await store.facts(first.scope, new[0].fact.subject_handle)
        assert len(await store.facts(first.scope, handle)) == 3
    with pytest.raises(asyncpg.UniqueViolationError):
        await store.record(first.scope, other, actor_ref="test", at=clock.now)
