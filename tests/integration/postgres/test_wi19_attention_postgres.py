"""WI-19 / OVE-182 on a disposable PostgreSQL 17: the built 1.7.0 release plus the candidate
``scripts/release_180/0063_coordinator_delivery_observations.sql`` (restricted runtime role,
forced RLS).

- a real started run's terminal notice is materialized into the inbox; an HTTP-style wait
  records one transport observation per return (a re-delivery after a disconnect is a second
  one), never acknowledgment; the host's wake and visible reports, the explicit ack and the
  bounded retrieval each land as their own fact and only all six qualify the notice;
- the retrieved excerpt is the exact accepted revision of the real WI-01 output store (its
  revision id, digest and producer), bounded by the request budget;
- the observation table refuses an update, a delete, an observation of an unsealed or foreign
  notification, a stage/channel mismatch and a credential in evidence; another tenant sees
  nothing;
- the output inspection reads (promises, accepted heads, fulfillment, assessments, history
  pages, transition events, sealed plans and receipts) answer the immutable rows exactly, and
  the actionable list names the unmet required promise and the held assessment.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import pytest
import pytest_asyncio

from mission_control.adapters.postgres.knowledge.output_contracts import (
    PostgresOutputContractStore,
)
from mission_control.adapters.postgres.knowledge.output_inspection import (
    PostgresOutputInspectionReader,
)
from mission_control.adapters.postgres.subscriptions.attention import PostgresAttentionStore
from mission_control.adapters.postgres.subscriptions.coordinator_inbox import (
    PostgresCoordinatorInboxStore,
)
from mission_control.adapters.postgres.subscriptions.store import PostgresSubscriptionStore
from mission_control.application.knowledge.access import InvocationAccess
from mission_control.application.outputs.inspection import (
    InspectionRejected,
    OutputInspectionService,
)
from mission_control.application.subscriptions.coordinator_service import (
    ContentRequest,
    CoordinatorInboxService,
    CoordinatorRejected,
    CoordinatorSubscribeRequest,
)
from mission_control.domain.coordinator.attention import HostObservation, nonce_digest
from mission_control.domain.outputs.contracts import Enforcement, OutputForm, Requirement
from mission_control.domain.policies.contracts import ActorContext
from tests.fixtures.mission_control_common_db import (
    CommonDatabase,
    common_database,
    migration_paths_with,
)
from tests.integration.postgres.test_mp15_coordinator_inbox_postgres import (
    owner_fetch,
    started_run,
)
from tests.unit.knowledge.test_gateway import origin
from tests.unit.outputs.scenario import Stack, build_stack, obligation, text

pytestmark = [pytest.mark.asyncio, pytest.mark.common_db]
MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "scripts/release_180/0063_coordinator_delivery_observations.sql"
)
AT = datetime(2026, 10, 28, 12, tzinfo=UTC)
COORDINATOR = ActorContext(
    actor_id="coordinator-1",
    permissions=frozenset({"workflow_run.read", "workflow.result.read"}),
)
BODY = "Generation Lab summary: 3 of 4 tests reproduce; the exact revision is retained."


@pytest_asyncio.fixture
async def db() -> AsyncIterator[CommonDatabase]:
    async with common_database(paths=migration_paths_with(MIGRATION)) as database:
        yield database


@pytest_asyncio.fixture
async def pool(db: CommonDatabase) -> AsyncIterator[asyncpg.Pool]:
    created = await db.pool(max_size=6)
    try:
        yield created
    finally:
        await created.close()


def access_for(db: CommonDatabase, run_id: UUID) -> InvocationAccess:
    _mc, installation, application, tenant_id = db.scope().split("/")
    return InvocationAccess(
        origin=origin(
            1,
            installation_id=installation,
            application_id=application,
            tenant_id=tenant_id,
            run_id=str(run_id),
        ),
        subject="mission-control-runtime",
        invocation_id="inv-0001",
        authenticated_at=AT,
    )


async def output_stack(db: CommonDatabase, pool: asyncpg.Pool, run_id: UUID) -> Stack:
    store = PostgresOutputContractStore(pool)
    return await build_stack(
        store,
        store,
        access_for(db, run_id),
        obligation("report.summary", OutputForm.TEXT),
        obligation(
            "report.review",
            OutputForm.TEXT,
            requirements=(Requirement(key="grounded", validator="mc.check.command@1"),),
        ),
        obligation("report.notes", OutputForm.TEXT, enforcement=Enforcement.OPTIONAL),
    )


def inbox_service(pool: asyncpg.Pool, scope: str) -> CoordinatorInboxService:
    return CoordinatorInboxService(
        PostgresSubscriptionStore(pool, scope),
        PostgresCoordinatorInboxStore(pool, scope),
        attention=PostgresAttentionStore(pool, scope),
        outputs=PostgresOutputContractStore(pool),
    )


def host(stage: str, nonce: str, key: str) -> HostObservation:
    at = datetime.now(UTC)
    if stage == "wake":
        return HostObservation(
            stage="wake",
            channel="background_task_exit",
            observation_key=key,
            delivery_nonce=nonce,
            observed_at=at,
            idle_since=at - timedelta(minutes=3),
            host_ref="claude-code:wi19-fixture",
        )
    return HostObservation(
        stage="visible",
        channel="task_output",
        observation_key=key,
        delivery_nonce=nonce,
        observed_at=at,
        host_ref="claude-code:wi19-fixture",
    )


async def subscribe(inboxes: CoordinatorInboxService, run_uuid: UUID, **profile: object) -> UUID:
    created = await inboxes.subscribe(
        CoordinatorSubscribeRequest.model_validate(
            {
                "target": "run",
                "target_id": str(run_uuid),
                "after_seq": 0,
                "profile": {"batch_window_seconds": 0, **profile},
            }
        ),
        COORDINATOR,
    )
    return created.subscription_id


async def test_six_stages_land_separately_on_postgres(
    db: CommonDatabase, pool: asyncpg.Pool
) -> None:
    scope = db.scope()
    _run_key, _mission, run_uuid = await started_run(pool, db)
    inboxes = inbox_service(pool, scope)
    sid = await subscribe(
        inboxes,
        run_uuid,
        kinds=["accepted_output"],
        content={"purpose": "coordinator_review"},
    )
    stack = await output_stack(db, pool, run_uuid)
    ack = await stack.submit("s-1", "report.summary", text("summary", BODY), position="draft")
    revision_id = await stack.accept(ack, "report.summary")
    # The final evaluation journals `output.fulfilled` in its own transaction (the gap fix).
    await stack.evaluate()
    first = await inboxes.wait(sid, COORDINATOR, timeout_seconds=1, channel="http")
    (notice,) = first.notifications
    assert notice.facts["obligation_key"] == "report.summary"
    nid = notice.notification_id
    nonce = first.delivery_nonces[str(nid)]
    # The host disconnects before acknowledging: the same notice is delivered again.
    again = await inboxes.wait(sid, COORDINATOR, timeout_seconds=0, channel="http")
    assert [item.notification_id for item in again.notifications] == [nid]
    assert again.delivery_nonces[str(nid)] != nonce  # one nonce per delivery
    await inboxes.observe(sid, nid, host("wake", nonce, "wake-1"), COORDINATOR)
    seen = host("visible", nonce, "visible-1")
    await inboxes.observe(sid, nid, seen, COORDINATOR)
    replay = await inboxes.observe(sid, nid, seen, COORDINATOR)
    assert replay.replay is True
    with pytest.raises(CoordinatorRejected) as refused:
        await inboxes.observe(sid, nid, host("visible", "f" * 32, "forged"), COORDINATOR)
    assert refused.value.code == "delivery_nonce_unknown"
    await inboxes.ack(sid, COORDINATOR, notification_ids=(nid,))
    result = await inboxes.retrieve(
        sid, nid, ContentRequest(obligations=("report.summary",), max_total_chars=40), COORDINATOR
    )
    (excerpt,) = result.content.excerpts
    assert excerpt.revision_id == revision_id and excerpt.excerpt == BODY[:40]
    assert excerpt.truncated and excerpt.source_chars == len(BODY)
    assert excerpt.purpose == "coordinator_review"
    accepted = await PostgresOutputContractStore(pool).accepted_outputs(scope, str(run_uuid))
    assert excerpt.content_digest == accepted[0].content_digest
    (claim,) = (await inboxes.attention(sid, COORDINATOR)).claims
    assert claim.verdict == "qualified", claim.codes
    rows = await owner_fetch(
        db,
        "SELECT stage, observation_key, notice_digest, delivery_nonce_digest, transport_key, "
        "received_at FROM mission_control.coordinator_delivery_observation "
        "WHERE notification_id = $1 ORDER BY stage, observation_key",
        nid,
    )
    assert [(row["stage"], row["observation_key"]) for row in rows] == [
        ("retrieval", result.observation_key),
        ("transport", "http:1"),
        ("transport", "http:2"),
        ("visible", "visible-1"),
        ("wake", "wake-1"),
    ]
    assert len({row["notice_digest"] for row in rows}) == 1
    assert rows[1]["delivery_nonce_digest"] == nonce_digest(nonce)  # only the digest is kept
    assert nonce not in {str(row["delivery_nonce_digest"]) for row in rows}
    assert (rows[3]["transport_key"], rows[4]["transport_key"]) == ("http:1", "http:1")
    acked = await owner_fetch(
        db,
        "SELECT state, acknowledged_by_actor_ref FROM mission_control.coordinator_notification "
        "WHERE notification_id = $1",
        nid,
    )
    assert (acked[0]["state"], acked[0]["acknowledged_by_actor_ref"]) == (
        "acknowledged",
        "coordinator-1",
    )
    digest = rows[0]["notice_digest"]
    # Immutable, scoped and guarded.
    for statement in (
        "UPDATE mission_control.coordinator_delivery_observation SET channel = 'mcp'",
        "DELETE FROM mission_control.coordinator_delivery_observation",
    ):
        with pytest.raises(asyncpg.PostgresError):
            await owner_fetch(db, statement)
    async with pool.acquire() as connection, connection.transaction():
        from mission_control.adapters.postgres.run_control import canonical as mc

        args = await mc.begin(connection, scope)
        for stage, channel, observer, result_name, evidence, transport_key in (
            ("wake", "http", "host", "observed", "{}", "http:1"),  # wrong channel family
            ("transport", "webhook", "server", "delivered", "{}", None),  # needs an attempt
            ("visible", "task_output", "server", "observed", "{}", "http:1"),  # host stage
            ("wake", "monitor_event", "host", "observed", '{"token": "x"}', "http:1"),
            ("wake", "monitor_event", "host", "observed", "{}", None),  # unbound host stage
            ("wake", "monitor_event", "host", "observed", "{}", "http:9"),  # unknown transport
        ):
            with pytest.raises(asyncpg.CheckViolationError):
                async with connection.transaction():
                    await connection.execute(
                        "INSERT INTO mission_control.coordinator_delivery_observation ("
                        "installation_id, application_id, tenant_id, subscription_id, "
                        "notification_id, stage, observation_key, channel, observer, result, "
                        "notice_digest, evidence, observed_at, created_at, created_by_actor_ref, "
                        "received_at, transport_key"
                        ") VALUES ($1, $2, $3, $4, $5, $6, 'k-x', $7, $8, $9, $10, $11::jsonb, "
                        "now(), now(), 'test', now(), $12)",
                        *args,
                        sid,
                        nid,
                        stage,
                        channel,
                        observer,
                        result_name,
                        digest,
                        evidence,
                        transport_key,
                    )
    other = inbox_service(pool, db.scope("tenant-2"))
    with pytest.raises(CoordinatorRejected) as hidden:
        await other.attention(sid, COORDINATOR)
    assert hidden.value.code == "not_found"
    assert await PostgresAttentionStore(pool, db.scope("tenant-2")).observations(sid, (nid,)) == {}


async def test_output_inspection_reads_the_exact_rows(
    db: CommonDatabase, pool: asyncpg.Pool
) -> None:
    scope = db.scope()
    _run_key, _mission, run_uuid = await started_run(pool, db)
    run_id = str(run_uuid)
    stack = await output_stack(db, pool, run_uuid)
    first = await stack.submit("s-1", "report.summary", text("summary", "v1"), position="draft")
    await stack.accept(first, "report.summary")
    second = await stack.submit("s-2", "report.summary", text("summary", "v2"), position="draft")
    latest = await stack.accept(second, "report.summary")
    review = await stack.submit("s-3", "report.review", text("review", "draft review"))
    review_id = await stack.accept(review, "report.review")
    review_digest = review.revisions[0].content_digest
    receipt = await stack.judge(review_id, review_digest, grounded="review")
    assert receipt.status == "recorded", receipt.error
    await stack.evaluate()
    service = OutputInspectionService(PostgresOutputInspectionReader(pool), request_scope=scope)
    view = await service.outputs(run_id, COORDINATOR)
    assert [item.obligation_key for item in view.obligations] == [
        "report.summary",
        "report.review",
        "report.notes",
    ]
    heads = {item.obligation_key: item.revision for item in view.accepted}
    assert heads["report.summary"].revision_id == latest and heads["report.summary"].revision == 2
    assert heads["report.summary"].accepted is True
    assert view.fulfillment is not None
    dispositions = {item.obligation_key: item.disposition for item in view.fulfillment.decisions}
    assert dispositions["report.summary"] == "fulfilled"
    assert dispositions["report.review"] in {"unfulfilled", "blocked"}
    codes = {(item.code, item.obligation_key) for item in view.actionable}
    assert any(key == "report.review" and code.startswith("OBLIGATION_") for code, key in codes)
    assert ("ASSESSMENT_HELD", None) in codes
    assert not any(key == "report.notes" for _code, key in codes)  # optional absence is silent
    # History: oldest first behind a stable cursor; only the head is accepted.
    page = await service.revisions(run_id, "report.summary", COORDINATOR, limit=1)
    assert [item.revision for item in page.revisions] == [1] and page.next_cursor
    rest = await service.revisions(run_id, "report.summary", COORDINATOR, cursor=page.next_cursor)
    assert [(item.revision, item.accepted) for item in rest.revisions] == [(2, True)]
    assert rest.next_cursor is None and page.revisions[0].accepted is False
    # Events: every transition once, joinable by position and operation, in a stable order.
    events = await service.events(run_id, COORDINATOR, limit=200)
    kinds = [item.kind for item in events.events]
    assert kinds.count("output.submitted") == 3 and kinds.count("assessment.recorded") == 1
    assert kinds.count("fulfillment.decided") == 3
    submitted = [item for item in events.events if item.kind == "output.submitted"]
    assert {item.position for item in submitted} == {"draft"}
    assert all(item.operation_ref and item.operation_attempt == 1 for item in submitted)
    paged = await service.events(run_id, COORDINATOR, limit=2)
    tail = await service.events(run_id, COORDINATOR, cursor=paged.next_cursor, limit=200)
    assert [item.ref for item in (*paged.events, *tail.events)] == [
        item.ref for item in events.events
    ]
    # Absent, foreign and malformed reads refuse typed.
    with pytest.raises(InspectionRejected) as refused:
        await service.outputs("00000000-0000-4000-8000-000000000000", COORDINATOR)
    assert refused.value.code == "not_found"
    other = OutputInspectionService(
        PostgresOutputInspectionReader(pool), request_scope=db.scope("tenant-2")
    )
    with pytest.raises(InspectionRejected):
        await other.outputs(run_id, COORDINATOR)
    with pytest.raises(InspectionRejected) as refused:
        await service.revisions(run_id, "report.summary", COORDINATOR, cursor="not-a-cursor")
    assert refused.value.code == "invalid"
    with pytest.raises(InspectionRejected) as refused:
        await service.outputs(run_id, ActorContext(actor_id="nobody"))
    assert refused.value.code == "unauthorized"


async def test_transfer_inspection_reads_plans_receipts_and_refusals(
    db: CommonDatabase, pool: asyncpg.Pool
) -> None:
    from mission_control.adapters.postgres.context.transfer_plans import (
        PostgresTransferPlanStore,
    )
    from mission_control.domain.context.transfer import (
        DeliveryReceipt,
        ReceiverAttempt,
        ReceiverRef,
        ResourceUsage,
        SealedTransferPlan,
        seal_plan,
    )
    from tests.unit.context.test_transfer_plan import (
        OVERHEAD,
        _deliveries,
        report_input,
        report_members,
        selection,
    )

    scope = db.scope()
    _run_key, _mission, run_uuid = await started_run(pool, db)
    run_id = str(run_uuid)
    plan = seal_plan(
        plan_id=str(uuid4()),
        receiver=ReceiverRef(scope=scope, run_id=run_id, operation_id="op-consumer"),
        selection=selection(report_input()),
        configuration_ref="erc:sha256:" + "0" * 64,
        host_state_ref=None,
        members=report_members(),
        overhead=OVERHEAD,
        inline_texts={
            m.member_key: '{"report":"r7"}' for m in report_members() if m.part == "manifest"
        },
    )
    assert isinstance(plan, SealedTransferPlan), plan
    store = PostgresTransferPlanStore(pool)
    sealed = await store.seal(plan)
    for sequence, result in ((1, "ready"), (2, "refused")):
        await store.append_receipt(
            scope,
            DeliveryReceipt(
                receipt_id=str(uuid4()),
                plan_id=sealed.plan_id,
                plan_digest=sealed.digest,
                receiver_attempt=ReceiverAttempt(
                    operation_attempt=sequence, execution_generation=1, invocation_ref="inv-1"
                ),
                realized_backend="sandbox",
                sequence=sequence,
                delivered=tuple(_deliveries(sealed)) if result == "ready" else (),
                current_access_refs=(),
                resource_usage=ResourceUsage(overhead=OVERHEAD, total_tokens=10, headroom_tokens=1),
                result=result,  # type: ignore[arg-type]
                correlation_id=f"corr-{sequence}",
            ),
        )
    service = OutputInspectionService(PostgresOutputInspectionReader(pool), request_scope=scope)
    (summary,) = await service.transfer_plans(run_id, COORDINATOR)
    assert summary.plan_id == sealed.plan_id and summary.plan_digest == sealed.digest
    assert summary.receipts == 2 and summary.latest_receipt is not None
    assert (summary.latest_receipt.sequence, summary.latest_receipt.result) == (2, "refused")
    assert summary.total_tokens == sealed.resource_plan.total_tokens
    detail = await service.transfer_plan(sealed.plan_id, COORDINATOR)
    assert detail.plan["digest"] == sealed.digest
    assert [item["result"] for item in detail.receipts] == ["ready", "refused"]
    view = await service.outputs(run_id, COORDINATOR)
    assert [(item.code, item.position) for item in view.actionable] == [
        ("INPUT_DELIVERY_REFUSED", summary.receiver_position)
    ]
    events = await service.events(run_id, COORDINATOR)
    delivered = [item for item in events.events if item.kind == "delivery.recorded"]
    assert [(item.result, item.operation_attempt) for item in delivered] == [
        ("ready", 1),
        ("refused", 2),
    ]
    assert {item.operation_ref for item in delivered} == {"op-consumer"}
    journaled = await owner_fetch(
        db,
        "SELECT event_type, payload->'payload'->>'transfer_plan_id' AS plan "
        "FROM mission_control.mission_event WHERE event_type LIKE 'transfer.%'",
    )
    assert [(row["event_type"], row["plan"]) for row in journaled] == [
        ("transfer.delivery_refused", sealed.plan_id)
    ]
    with pytest.raises(InspectionRejected) as refused:
        await OutputInspectionService(
            PostgresOutputInspectionReader(pool), request_scope=db.scope("tenant-2")
        ).transfer_plan(sealed.plan_id, COORDINATOR)
    assert refused.value.code == "not_found"


async def test_output_and_transfer_attention_events_wake_the_inbox(
    db: CommonDatabase, pool: asyncpg.Pool
) -> None:
    """The output stores journal the default actionable transitions in the transaction of the
    state change, and the OVE-78 inbox turns them into notices (no relay, no second engine)."""

    scope = db.scope()
    _run_key, _mission, run_uuid = await started_run(pool, db)
    inboxes = inbox_service(pool, scope)
    sid = await subscribe(inboxes, run_uuid)
    stack = await output_stack(db, pool, run_uuid)
    review = await stack.submit("s-3", "report.review", text("review", "draft review"))
    review_id = await stack.accept(review, "report.review")
    held = await stack.judge(review_id, review.revisions[0].content_digest, grounded="review")
    again = await stack.judge(review_id, review.revisions[0].content_digest, grounded="review")
    assert held.status == again.status == "recorded"  # the same judgment, journaled once
    await stack.evaluate()
    await stack.evaluate()  # an unchanged disposition is not journaled again
    page = await inboxes.poll(sid, COORDINATOR, channel="http")
    seen = sorted(
        (item.kind.value, str(item.facts.get("obligation_key")), str(item.facts.get("result")))
        for item in page.notifications
    )
    assert ("blocked", "None", "review") in seen  # the held assessment
    assert ("blocked", "report.review", "None") in seen  # required promise unmet
    assert ("blocked", "report.summary", "None") in seen  # required, never submitted
    assert not any(key == "report.notes" for _kind, key, _result in seen)  # optional: silent
    events = await owner_fetch(
        db,
        "SELECT event_type, count(*) AS n FROM mission_control.mission_event "
        "WHERE event_type LIKE 'output.%' GROUP BY event_type ORDER BY event_type",
    )
    assert {row["event_type"]: row["n"] for row in events} == {
        "output.assessment_held": 1,
        "output.fulfillment_unmet": 2,
    }
