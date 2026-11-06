"""WI-22 / OVE-183 on a disposable PostgreSQL 17: the built 1.7.0 release plus
``scripts/release_170/0061_durable_transition_reactions.sql`` (restricted runtime role, forced RLS).

- the 0061 capture triggers record the five durable transitions (an output submitted, an
  assessment recorded, a fulfillment decided, a transfer delivery recorded, a saved result
  settled) as five distinct kinds, each reaching only the reactions bound to it, and a run with
  no armed reaction captures nothing;
- a duplicate event is one transition and one logical reaction, also under two racing admitters;
- a crash after admission and before dispatch, and one after the start before the
  acknowledgement, recover through the outbox into one dispatch;
- a re-attached (stale) generation and a stop-fenced run cancel instead of dispatching;
- a self-trigger chain through every kind (each reaction operation produces the next
  transition through the ordinary WI-01/02/04 stores) keeps its depth, because each capture
  takes its cause from an authenticated operation identity, and stops at the admitted
  recursion limit; through outputs it also stops at the activation, rate, spend and time
  limits; an assessor origin naming a reaction is never the cause, and a ``reaction-`` cause
  with no activation fails closed;
- capture never fails the source write: edge facts are bounded, an invalid source is skipped
  with a recorded anomaly, and only the runtime role writes the source tables;
- the tables refuse a backward activation, a rewritten transition and deletion; another tenant
  sees nothing.
"""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio

from mission_control.adapters.postgres.context.transfer_plans import PostgresTransferPlanStore
from mission_control.adapters.postgres.knowledge.output_contracts import (
    PostgresOutputContractStore,
)
from mission_control.adapters.postgres.operations.invocation_settlement import (
    PostgresInvocationSettlementStore,
)
from mission_control.adapters.postgres.reactions import (
    PostgresReactionAuthority,
    PostgresReactionStore,
)
from mission_control.adapters.postgres.run_control.run_control_repository import (
    PostgresRunControlRepository,
)
from mission_control.adapters.postgres.run_control.stop_fence import PostgresStopFenceRepository
from mission_control.adapters.postgres.scope import apply_scope
from mission_control.application.knowledge.access import InvocationAccess
from mission_control.application.reactions.service import (
    ReactionBindingService,
    ReactionDispatchReceipt,
    ReactionRelay,
)
from mission_control.domain.context.transfer import (
    DeliveryReceipt,
    ReceiverAttempt,
    ReceiverRef,
    ResourceUsage,
    SealedTransferPlan,
    seal_plan,
)
from mission_control.domain.execution.contracts import RuntimeResult
from mission_control.domain.execution.invocation_settlement import (
    InvocationSettlement,
    SettlementOutcome,
)
from mission_control.domain.outputs.contracts import Cardinality, OutputForm, Requirement
from mission_control.domain.policies.stop_fence import StopFence
from mission_control.domain.reactions.contracts import (
    DurableTransition,
    ReactionActivation,
    ReactionBinding,
    ReactionDeclaration,
    TransitionKind,
)
from tests.fixtures.mission_control_common_db import (
    CommonDatabase,
    common_database,
    migration_paths_with,
)
from tests.integration.postgres.runtime_common import scoped_request
from tests.unit.context.test_transfer_plan import (
    OVERHEAD,
    _deliveries,
    report_input,
    report_members,
    selection,
)
from tests.unit.knowledge.test_gateway import origin
from tests.unit.outputs.scenario import (
    REPO,
    Stack,
    build_stack,
    code_change,
    obligation,
)
from tests.unit.run_control.test_run_control import service

pytestmark = [pytest.mark.asyncio, pytest.mark.common_db]
MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "scripts/release_170/0061_durable_transition_reactions.sql"
)
RUN = "22222222-2222-4222-8222-222222222222"  # the WI-01 scenario's origin run
AT = datetime(2026, 10, 27, 12, tzinfo=UTC)
PATCH = obligation(
    "draft.patch",
    OutputForm.CODE_CHANGE,
    repository=REPO,
    cardinality=Cardinality(max=16),  # every chained operation adds one change
    requirements=(
        Requirement(key="tests", validator="mc.check.command@1"),
        Requirement(key="lint", validator="mc.check.command@1"),
    ),
)


@pytest_asyncio.fixture
async def db() -> AsyncIterator[CommonDatabase]:
    async with common_database(paths=migration_paths_with(MIGRATION)) as database:
        yield database


@pytest_asyncio.fixture
async def pool(db: CommonDatabase) -> AsyncIterator[asyncpg.Pool]:
    created = await db.pool()
    try:
        yield created
    finally:
        await created.close()


def reaction(
    reaction_id: str, event: str, *, where: str | None = None, **limits: Any
) -> ReactionDeclaration:
    spend = limits.pop("spend", {"tokens_per_activation": 10, "max_tokens": 1_000})
    return ReactionDeclaration.model_validate(
        {
            "id": reaction_id,
            "on": {"event": event},
            "where": where,
            "operation": {"template": "reviewer", "purpose": "React to the transition."},
            "limits": {
                "max_activations": 32,
                "max_depth": 8,
                "rate": {"count": 32, "window_seconds": 3600},
                **limits,
                "spend": spend,
            },
        }
    )


class RecordingOperations:
    """The dispatch port as a recorder (the Temporal start is proven separately); ``then`` runs
    the activation's work, ``crash`` kills the relay before or after the start."""

    def __init__(self, then: Any = None, crash: str | None = None) -> None:
        self.calls: list[str] = []
        self._then = then
        self._crash = crash

    async def dispatch(
        self,
        scope: str,
        activation: ReactionActivation,
        binding: ReactionBinding,
        transition: DurableTransition,
    ) -> ReactionDispatchReceipt:
        if self._crash == "before":
            self._crash = None
            raise Crash("killed before the start")
        self.calls.append(activation.activation_id)
        if self._then is not None:
            await self._then(activation)
        if self._crash == "after":
            self._crash = None
            raise Crash("killed after the start, before the acknowledgement")
        return ReactionDispatchReceipt(workflow_id=f"wf/{activation.operation_id}")


class Crash(BaseException):
    """The relay process dying (not an ordinary delivery failure it would retry)."""


def relay(pool: asyncpg.Pool, operations: Any, owner: str = "relay-1") -> ReactionRelay:
    return ReactionRelay(
        store=PostgresReactionStore(pool),
        authority=PostgresReactionAuthority(pool),
        operations=operations,
        lease_owner=owner,
    )


def access(db: CommonDatabase, operation_id: str) -> InvocationAccess:
    _mc, installation, application, tenant_id = db.scope().split("/")
    return InvocationAccess(
        origin=origin(
            1,
            installation_id=installation,
            application_id=application,
            tenant_id=tenant_id,
            operation_id=operation_id,
        ),
        subject="mission-control-runtime",
        invocation_id=f"inv-{operation_id}"[:60],
        authenticated_at=AT,
    )


async def patch_stack(db: CommonDatabase, pool: asyncpg.Pool) -> Stack:
    store = PostgresOutputContractStore(pool)
    return await build_stack(store, store, access(db, "op-research-1"), PATCH)


async def owner_rows(db: CommonDatabase, query: str, *args: object) -> list[asyncpg.Record]:
    connection = await asyncpg.connect(db.owner_dsn)
    try:
        return await connection.fetch(query, *args)
    finally:
        await connection.close()


async def settle_one(
    db: CommonDatabase,
    pool: asyncpg.Pool,
    run_id: str,
    binding: str,
    *,
    operation: str = "operation-1",
) -> None:
    # No PostgreSQL attempt row carries a unit fence here (as in the WI-04 store tests).
    store = PostgresInvocationSettlementStore(pool, require_unit_generation=False)
    saved = await store.save(
        InvocationSettlement.save(
            request_scope=db.scope(),
            run_id=run_id,
            binding_id=binding,
            operation_ref=operation,
            operation_attempt=1,
            unit_key="unit-1",
            execution_generation=1,
            result=RuntimeResult(output_text="done"),
            recovery_owner="operation/workflow-1",
            claim_fence=2,
            at=datetime.now(UTC),
        )
    )
    settled = saved.advanced(
        SettlementOutcome.done(finalization_ref="finalization:1"),
        claim_fence=3,
        at=datetime.now(UTC),
    )
    await store.advance(settled, expected_version=1)


async def deliver_one(
    db: CommonDatabase, pool: asyncpg.Pool, run_id: str, *, operation: str = "op-consumer"
) -> None:
    plan = seal_plan(
        plan_id=str(uuid4()),
        receiver=ReceiverRef(scope=db.scope(), run_id=run_id, operation_id=operation),
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
    await store.append_receipt(
        db.scope(),
        DeliveryReceipt(
            receipt_id=str(uuid4()),
            plan_id=sealed.plan_id,
            plan_digest=sealed.digest,
            receiver_attempt=ReceiverAttempt(
                operation_attempt=1, execution_generation=1, invocation_ref="inv-1"
            ),
            realized_backend="sandbox",
            sequence=1,
            delivered=tuple(_deliveries(sealed)),
            current_access_refs=(),
            resource_usage=ResourceUsage(overhead=OVERHEAD, total_tokens=10, headroom_tokens=1),
            result="ready",
            correlation_id="corr-1",
        ),
    )


# ---------------------------------------------------------------- capture and distinct events


async def test_the_five_durable_transitions_are_captured_as_distinct_kinds(
    db: CommonDatabase, pool: asyncpg.Pool
) -> None:
    scope = db.scope()
    bindings = ReactionBindingService(PostgresReactionStore(pool))
    await bindings.attach(
        scope,
        RUN,
        [reaction(f"on-{kind.value.replace('.', '-')}", kind.value) for kind in TransitionKind],
    )
    stack = await patch_stack(db, pool)
    patch = await stack.submit("p1", "draft.patch", code_change())
    revision = patch.revisions[0]
    await stack.accept(patch, "draft.patch")
    judged = await stack.judge(
        revision.revision_id, revision.content_digest, tests="pass", lint="pass"
    )
    assert judged.status == "recorded", judged.error
    evaluated = await stack.evaluate()
    assert evaluated.fulfillments
    await settle_one(db, pool, RUN, "binding-1")
    await deliver_one(db, pool, RUN)
    # A run with no armed reaction captures nothing.
    other = str(uuid4())
    await settle_one(db, pool, other, "binding-2")

    store = PostgresReactionStore(pool)
    captured = await store.transitions(scope, RUN)
    kinds = [item.kind for item in captured]
    assert set(kinds) == set(TransitionKind)
    assert kinds.count(TransitionKind.OUTPUT_SUBMITTED) == 1
    assert kinds.count(TransitionKind.ASSESSMENT_RECORDED) == 1
    assert kinds.count(TransitionKind.SETTLEMENT_SETTLED) == 1, "settled once, not per update"
    assert kinds.count(TransitionKind.DELIVERY_RECORDED) == 1
    submitted = next(i for i in captured if i.kind is TransitionKind.OUTPUT_SUBMITTED)
    assert submitted.source_ref == revision.revision_id
    assert submitted.cause_ref == "op-research-1" and submitted.execution_generation == 1
    assert submitted.facts["obligation_key"] == "draft.patch"
    assessed = next(i for i in captured if i.kind is TransitionKind.ASSESSMENT_RECORDED)
    assert assessed.facts["result"] == "pass"
    assert await store.transitions(scope, other) == ()

    report = await relay(pool, RecordingOperations()).admit_once(scope, now=datetime.now(UTC))
    assert report.transitions == len(captured)
    by_reaction: dict[str, set[TransitionKind]] = {}
    for item in report.activations:
        by_reaction.setdefault(item.reaction_id, set()).add(item.event)
    assert by_reaction == {
        f"on-{kind.value.replace('.', '-')}": {kind} for kind in TransitionKind
    }, "each kind reaches only the reaction bound to it"
    assert all(item.state == "admitted" for item in report.activations)
    assert await PostgresReactionStore(pool).transitions(db.scope("tenant-2"), RUN) == ()


# ---------------------------------------------------------------- duplicate, crash, stale


def fulfillment_event(source: str, at: datetime | None = None) -> DurableTransition:
    return DurableTransition.of(
        TransitionKind.FULFILLMENT_DECIDED,
        source,
        run_id=RUN,
        captured_at=at or datetime.now(UTC),
        facts={"obligation_key": "draft.patch", "disposition": "unfulfilled"},
    )


async def test_a_duplicate_event_yields_one_logical_reaction(
    db: CommonDatabase, pool: asyncpg.Pool
) -> None:
    scope = db.scope()
    store = PostgresReactionStore(pool)
    await ReactionBindingService(store).attach(
        scope, RUN, [reaction("repair", "fulfillment.decided")]
    )
    event = fulfillment_event("fulfillment-1")
    assert await store.record_transition(scope, event) is True
    assert await store.record_transition(scope, event) is False, "the same event is one row"
    racing = await asyncio.gather(
        relay(pool, RecordingOperations(), "a").admit_once(scope, now=datetime.now(UTC)),
        relay(pool, RecordingOperations(), "b").admit_once(scope, now=datetime.now(UTC)),
    )
    assert sum(len(item.activations) for item in racing) == 1
    [activation] = await store.activations(scope, RUN)
    # The same event recorded again after admission is still one reaction.
    assert await store.record_transition(scope, event) is False
    assert (
        await relay(pool, RecordingOperations()).admit_once(scope, now=datetime.now(UTC))
    ).transitions == 0
    operations = RecordingOperations()
    dispatched = await relay(pool, operations).dispatch_once(scope, now=datetime.now(UTC))
    assert dispatched.dispatched == (activation.activation_id,)
    assert operations.calls == [activation.activation_id]
    assert (
        await relay(pool, operations).dispatch_once(scope, now=datetime.now(UTC))
    ).dispatched == ()
    rows = await owner_rows(
        db,
        "SELECT delivery_state FROM mission_control.outbox WHERE destination_kind = $1",
        "mc.reaction.dispatch",
    )
    assert [row["delivery_state"] for row in rows] == ["delivered"]


@pytest.mark.parametrize("window", ["before", "after"])
async def test_a_crash_between_admission_and_acknowledgement_recovers(
    db: CommonDatabase, pool: asyncpg.Pool, window: str
) -> None:
    scope = db.scope()
    store = PostgresReactionStore(pool)
    await ReactionBindingService(store).attach(
        scope, RUN, [reaction("repair", "fulfillment.decided")]
    )
    await store.record_transition(scope, fulfillment_event("fulfillment-1"))
    await relay(pool, RecordingOperations()).admit_once(scope, now=datetime.now(UTC))
    [admitted] = await store.activations(scope, RUN)
    assert admitted.state == "admitted"
    dying = RecordingOperations(crash=window)
    with pytest.raises(Crash):
        await relay(pool, dying, "worker-1").dispatch_once(scope, now=datetime.now(UTC))
    assert (await store.activation(scope, admitted.activation_id)).state == "admitted"  # type: ignore[union-attr]
    # A fresh relay (a new process: new pool, new store) waits out the dead lease.
    fresh_pool = await db.pool()
    try:
        recovered = RecordingOperations()
        early = await relay(fresh_pool, recovered, "worker-2").dispatch_once(
            scope, now=datetime.now(UTC)
        )
        assert early.dispatched == (), "the dead relay's lease is still held"
        later = datetime.now(UTC) + timedelta(seconds=61)
        report = await relay(fresh_pool, recovered, "worker-2").dispatch_once(scope, now=later)
    finally:
        await fresh_pool.close()
    assert report.dispatched == (admitted.activation_id,)
    assert recovered.calls == [admitted.activation_id]
    # Before the start the dead relay started nothing; after it, the recovery re-delivers the
    # same activation (the Temporal start attaches to the existing workflow).
    assert dying.calls == ([] if window == "before" else [admitted.activation_id])
    final = await store.activation(scope, admitted.activation_id)
    assert final is not None and final.state == "dispatched"
    assert final.workflow_id == f"wf/{admitted.operation_id}"


async def test_a_stale_generation_and_a_fenced_run_cancel(
    db: CommonDatabase, pool: asyncpg.Pool
) -> None:
    scope = db.scope()
    store = PostgresReactionStore(pool)
    bindings = ReactionBindingService(store)
    await bindings.attach(scope, RUN, [reaction("repair", "fulfillment.decided")])
    await store.record_transition(scope, fulfillment_event("fulfillment-1"))
    await relay(pool, RecordingOperations()).admit_once(scope, now=datetime.now(UTC))
    [stale] = await store.activations(scope, RUN)
    [rebound] = await bindings.attach(
        scope, RUN, [reaction("repair", "fulfillment.decided", max_activations=5)]
    )
    assert rebound.generation == 2
    [same] = await bindings.attach(
        scope, RUN, [reaction("repair", "fulfillment.decided", max_activations=5)]
    )
    assert same.generation == 2, "the same armed descriptor is no new generation"
    operations = RecordingOperations()
    report = await relay(pool, operations).dispatch_once(scope, now=datetime.now(UTC))
    assert report.cancelled == {stale.activation_id: "stale_generation"}
    assert operations.calls == []
    detached = await bindings.detach(scope, RUN, "repair")
    assert detached is not None and detached.state == "detached" and detached.generation == 3
    assert await store.record_transition(scope, fulfillment_event("fulfillment-2")) is False

    # A real admitted run: its stop fence cancels the pending reaction.
    run_service, _ = service(PostgresRunControlRepository(pool))  # type: ignore[arg-type]
    admitted = await run_service.admit(scoped_request(db, request_id="wi22-fenced"))
    assert admitted.run_id is not None
    run_uuid = admitted.run_id  # the public run identity (mission_run.run_key)
    await bindings.attach(scope, run_uuid, [reaction("repair", "fulfillment.decided")])
    await store.record_transition(
        scope,
        DurableTransition.of(
            TransitionKind.FULFILLMENT_DECIDED,
            "fulfillment-3",
            run_id=run_uuid,
            captured_at=datetime.now(UTC),
            facts={"disposition": "unfulfilled"},
        ),
    )
    [pending] = (await relay(pool, operations).admit_once(scope, now=datetime.now(UTC))).activations
    assert pending.run_generation == 1, "admission records the run's execution generation"
    await PostgresStopFenceRepository(pool).persist(
        StopFence(
            request_scope=scope,
            run_id=admitted.run_id,
            generation=1,
            command_id="cancel-now",
            reason="operator stop",
            requested_at=datetime.now(UTC),
        )
    )
    report = await relay(pool, operations).dispatch_once(scope, now=datetime.now(UTC))
    assert report.cancelled == {pending.activation_id: "run_fenced"}
    assert operations.calls == []


# ---------------------------------------------------------------- the self-trigger chain


async def produce(
    kind: TransitionKind,
    db: CommonDatabase,
    pool: asyncpg.Pool,
    stack: Stack,
    operation: str,
    n: int,
) -> None:
    """One transition of ``kind`` made by ``operation`` through the ordinary stores."""

    if kind in {TransitionKind.DELIVERY_RECORDED, TransitionKind.SETTLEMENT_SETTLED}:
        if kind is TransitionKind.DELIVERY_RECORDED:
            await deliver_one(db, pool, RUN, operation=operation)
        else:
            await settle_one(db, pool, RUN, f"binding-{n}", operation=operation)
        return
    invocation = stack if operation == "op-research-1" else await stack.start(access(db, operation))
    ack = await invocation.submit(f"chain-{n}", "draft.patch", code_change(f"change-{n}"))
    assert ack.status == "accepted", ack.error
    if kind is TransitionKind.OUTPUT_SUBMITTED:
        return
    revision = ack.revisions[0]
    await stack.accept(ack, "draft.patch")
    if kind is TransitionKind.ASSESSMENT_RECORDED:
        judged = await stack.judge(
            revision.revision_id, revision.content_digest, tests="pass", lint="pass"
        )
        assert judged.status == "recorded", judged.error
    else:
        assert (await stack.evaluate()).fulfillments


class ChainedOperation:
    """Each reaction operation makes the next transition of the bound kind as its own
    invocation (operation ``reaction-<activation>``); the capture attributes it to that
    authenticated operation, which is the self-trigger."""

    def __init__(
        self,
        db: CommonDatabase,
        pool: asyncpg.Pool,
        stack: Stack,
        kind: TransitionKind,
        *,
        pause: float = 0,
    ) -> None:
        self._db = db
        self._pool = pool
        self._stack = stack
        self._kind = kind
        self._pause = pause
        self.count = 0

    async def __call__(self, activation: ReactionActivation) -> None:
        self.count += 1
        if self._pause and self.count == 1:  # the first operation outlives the lifetime
            await asyncio.sleep(self._pause)
        await produce(
            self._kind, self._db, self._pool, self._stack, activation.operation_id, self.count
        )


async def run_chain(
    db: CommonDatabase,
    pool: asyncpg.Pool,
    declaration: ReactionDeclaration,
    *,
    pause: float = 0,
) -> list[ReactionActivation]:
    scope = db.scope()
    kind = declaration.on.event
    store = PostgresReactionStore(pool)
    await ReactionBindingService(store).attach(scope, RUN, [declaration])
    stack = await patch_stack(db, pool)
    chained = ChainedOperation(db, pool, stack, kind, pause=pause)
    operations = RecordingOperations(then=chained)
    await produce(kind, db, pool, stack, "op-research-1", 0)
    for _step in range(10):
        admitted, dispatched = await relay(pool, operations).run_once(scope, now=datetime.now(UTC))
        if not admitted.transitions and not dispatched.dispatched:
            break
    return list(await store.activations(scope, RUN))


def assert_chain(activations: list[ReactionActivation], code: str) -> None:
    admitted = [item for item in activations if item.state == "dispatched"]
    refused = [item for item in activations if item.state == "refused"]
    assert len(admitted) == 3 and [item.refusal_code for item in refused] == [code]
    root = admitted[0]
    assert [item.depth for item in admitted] == [1, 2, 3]
    assert all(item.root_activation_id == root.activation_id for item in activations)
    assert refused[0].cause_activation_id == admitted[-1].activation_id
    assert refused[0].depth == 4 and refused[0].reserved_tokens == 0


@pytest.mark.parametrize("kind", list(TransitionKind))
async def test_a_self_trigger_chain_through_every_kind_stops_at_its_depth(
    db: CommonDatabase, pool: asyncpg.Pool, kind: TransitionKind
) -> None:
    activations = await run_chain(db, pool, reaction("echo", kind.value, max_depth=3))
    assert {item.event for item in activations} == {kind}
    assert_chain(activations, "RECURSION_LIMIT")


@pytest.mark.parametrize(
    ("limits", "code"),
    [
        ({"max_depth": 3}, "RECURSION_LIMIT"),
        ({"max_activations": 3}, "ACTIVATION_LIMIT"),
        ({"rate": {"count": 3, "window_seconds": 3600}}, "RATE_LIMIT"),
        ({"spend": {"tokens_per_activation": 100, "max_tokens": 300}}, "SPEND_LIMIT"),
    ],
)
async def test_a_self_trigger_chain_stops_at_its_admitted_limit(
    db: CommonDatabase, pool: asyncpg.Pool, limits: dict[str, Any], code: str
) -> None:
    activations = await run_chain(db, pool, reaction("echo", "output.submitted", **limits))
    assert_chain(activations, code)


async def test_a_self_trigger_chain_stops_at_its_lifetime(
    db: CommonDatabase, pool: asyncpg.Pool
) -> None:
    lifetime = 3
    declaration = reaction(
        "echo", "output.submitted", time={"lifetime_seconds": lifetime, "operation_seconds": 60}
    )
    activations = await run_chain(db, pool, declaration, pause=lifetime + 0.5)
    states = [(item.depth, item.state, item.refusal_code) for item in activations]
    assert states == [(1, "dispatched", None), (2, "refused", "TIME_LIMIT")]


# ---------------------------------------------------------------- table guards


async def _sqlstate(db: CommonDatabase, statement: str, *args: object) -> str:
    connection = await asyncpg.connect(db.dsn())
    try:
        async with connection.transaction():
            await apply_scope(connection, db.scope())
            await connection.execute(statement, *args)
    except asyncpg.PostgresError as error:
        return str(error.sqlstate)
    finally:
        await connection.close()
    return "00000"


async def test_the_tables_refuse_backward_moves_rewrites_and_deletion(
    db: CommonDatabase, pool: asyncpg.Pool
) -> None:
    scope = db.scope()
    store = PostgresReactionStore(pool)
    await ReactionBindingService(store).attach(
        scope, RUN, [reaction("repair", "fulfillment.decided")]
    )
    await store.record_transition(scope, fulfillment_event("fulfillment-1"))
    await relay(pool, RecordingOperations()).run_once(scope, now=datetime.now(UTC))
    [activation] = await store.activations(scope, RUN)
    assert activation.state == "dispatched"
    table = "mission_control.reaction_activation"
    assert await _sqlstate(db, f"UPDATE {table} SET state = 'admitted', version = version + 1") in {
        "23001",
        "42501",
    }
    assert await _sqlstate(
        db, "UPDATE mission_control.reaction_transition SET facts = '{}'::jsonb"
    ) in {"23001", "42501"}
    assert await _sqlstate(db, f"DELETE FROM {table}") in {"23001", "42501"}
    assert await _sqlstate(db, f"TRUNCATE {table}") in {"23001", "42501"}
    assert await _sqlstate(
        db, "UPDATE mission_control.reaction_binding SET generation = 1, version = version + 1"
    ) in {"23001", "42501"}
    assert await store.activations(db.scope("tenant-2"), RUN) == ()


# ---------------------------------------------------------------- causes cannot be forged


async def test_an_assessor_origin_is_never_a_cause_and_an_unknown_cause_fails_closed(
    db: CommonDatabase, pool: asyncpg.Pool
) -> None:
    scope = db.scope()
    store = PostgresReactionStore(pool)
    await ReactionBindingService(store).attach(
        scope,
        RUN,
        [
            reaction("on-assessment", "assessment.recorded"),
            reaction("repair", "fulfillment.decided"),
        ],
    )
    forged = "reaction-00000000-0000-4000-8000-000000000000"
    stack = await patch_stack(db, pool)
    # An assessor whose origin names a reaction operation: the cause stays the subject's producer.
    stack.assessor = dataclasses.replace(stack.assessor, origin_ref=f"mc-assessor:{forged}")
    ack = await stack.submit("p1", "draft.patch", code_change())
    revision = ack.revisions[0]
    judged = await stack.judge(
        revision.revision_id, revision.content_digest, tests="pass", lint="pass"
    )
    assert judged.status == "recorded", judged.error
    [assessed] = [
        item
        for item in await store.transitions(scope, RUN)
        if item.kind is TransitionKind.ASSESSMENT_RECORDED
    ]
    assert assessed.cause_ref == "op-research-1", "the subject's authenticated producer"
    # A host capture whose cause names a reaction operation with no activation fails closed.
    assert await store.record_transition(
        scope,
        DurableTransition.of(
            TransitionKind.FULFILLMENT_DECIDED,
            "fulfillment-forged",
            run_id=RUN,
            captured_at=datetime.now(UTC),
            cause_ref=forged,
            facts={"disposition": "unfulfilled"},
        ),
    )
    report = await relay(pool, RecordingOperations()).admit_once(scope, now=datetime.now(UTC))
    states = {
        (item.reaction_id, item.state, item.refusal_code, item.depth) for item in report.activations
    }
    assert ("on-assessment", "admitted", None, 1) in states
    assert ("repair", "refused", "CAUSE_UNKNOWN", 1) in states


# ---------------------------------------------------------------- capture never fails the write


async def test_capture_never_fails_the_source_write(db: CommonDatabase, pool: asyncpg.Pool) -> None:
    scope = db.scope()
    store = PostgresReactionStore(pool)
    await ReactionBindingService(store).attach(
        scope, RUN, [reaction("on-settled", "settlement.settled")]
    )
    # Edge facts: an oversized binding id is bounded in the facts and the write commits.
    await settle_one(db, pool, RUN, "b" * 2000)
    [settled] = await store.transitions(scope, RUN)
    assert settled.kind is TransitionKind.SETTLEMENT_SETTLED
    assert len(str(settled.facts["binding_id"])) == 512
    # A source the capture cannot record is skipped with a visible anomaly, not an error.
    _mc, installation, application, tenant = scope.split("/")
    connection = await asyncpg.connect(db.dsn())
    try:
        async with connection.transaction():
            await apply_scope(connection, scope)
            await connection.execute(
                "SELECT mission_control.capture_reaction_transition($1::uuid, $2, $3::uuid, "
                "$4::uuid, 'settlement.settled', $5, NULL, 1, '{}'::jsonb)",
                installation,
                application,
                tenant,
                RUN,
                "x" * 600,
            )
            await connection.execute(
                "SELECT mission_control.capture_reaction_transition($1::uuid, $2, $3::uuid, "
                "$4::uuid, 'settlement.settled', 'source-1', NULL, 1, '{\"token\": 1}'::jsonb)",
                installation,
                application,
                tenant,
                RUN,
            )
            anomalies = await connection.fetch(
                "SELECT reason FROM mission_control.reaction_capture_anomaly ORDER BY reason"
            )
    finally:
        await connection.close()
    assert [row["reason"] for row in anomalies] == ["facts_invalid", "source_invalid"]
    assert len(await store.transitions(scope, RUN)) == 1
    # Only the runtime role writes the five source tables, and only it executes the capture.
    rows = await owner_rows(
        db,
        """
        SELECT role.rolname, source.name,
               has_table_privilege(role.oid, 'mission_control.' || source.name,
                   'INSERT,UPDATE') AS writes,
               has_function_privilege(role.oid,
                   'mission_control.capture_reaction_transition(uuid, text, uuid, uuid, text, '
                   'text, text, integer, jsonb)', 'EXECUTE') AS captures
        FROM pg_roles AS role
        CROSS JOIN unnest(ARRAY['output_revision', 'output_assessment', 'obligation_fulfillment',
            'transfer_delivery_receipt', 'invocation_settlement']) AS source(name)
        WHERE role.rolname LIKE 'mission_control_%' AND NOT role.rolcanlogin
        """,
    )
    writers = {row["rolname"] for row in rows if row["writes"]}
    executors = {row["rolname"] for row in rows if row["captures"]}
    assert writers == {"mission_control_runtime"}
    assert executors == {"mission_control_runtime"}
