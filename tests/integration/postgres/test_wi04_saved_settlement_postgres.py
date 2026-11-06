"""WI-04 / OVE-166 on a disposable PostgreSQL 17 with release 1.7.0 (restricted runtime role).

``PostgresInvocationSettlementStore`` over ``invocation_settlement`` (migration 0058) under
forced row security: a saved result is written once (same bytes return it, other bytes
refuse), advances by compare-and-set (a lost CAS is a conflict), and the table's guard refuses
what the domain refuses (immutable saved bytes, a terminal settled row, a fenced-out writer, a
lifted stop fence, deletion); another tenant sees nothing.

The restart proof runs the whole operation boundary (a real ``create_deep_agent`` graph, the
RRM-004 harness) on the canonical scope with the PostgreSQL store as the only durable record of
the saved result: the worker is lost in the settlement pass while the native receipt is
pending, a fresh boundary (new store instance, new pool) resumes the saved row, and the run
settles with two model calls, one native write and one lane dispatch.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio

from mission_control.adapters.postgres.operations.invocation_settlement import (
    PostgresInvocationSettlementStore,
)
from mission_control.adapters.postgres.scope import apply_scope
from mission_control.application.execution.operations.invocation_settlement import (
    SavedSettlementConflict,
    SettlementEvent,
    StaleSettlementHolder,
)
from mission_control.domain.execution.contracts import RuntimeResult
from mission_control.domain.execution.invocation_settlement import (
    InvocationSettlement,
    SettlementOutcome,
    SettlementState,
    WaitReason,
)
from mission_control.domain.policies.errors import IdempotencyConflict
from tests.fixtures.checkpoint_recovery import recovery_harness, stage_recovery_unit
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.fixtures.saved_settlement import DurableEffectDouble
from tests.integration.postgres.runtime_common import common_db  # noqa: F401

pytestmark = [pytest.mark.asyncio, pytest.mark.common_db]


@pytest_asyncio.fixture
async def pool(common_db: CommonDatabase) -> AsyncIterator[asyncpg.Pool]:  # noqa: F811
    await common_db.add_tenants(["tenant-1", "tenant-2"])
    created = await common_db.pool()
    try:
        yield created
    finally:
        await created.close()


def _saved(scope: str, *, output: str = "done", binding: str = "binding-1") -> InvocationSettlement:
    return InvocationSettlement.save(
        request_scope=scope,
        run_id=str(uuid4()),
        binding_id=binding,
        operation_ref="operation-1",
        operation_attempt=1,
        unit_key="unit-1",
        execution_generation=1,
        result=RuntimeResult(output_text=output),
        recovery_owner="operation/workflow-1",
        claim_fence=2,
        at=datetime.now(UTC),
    )


async def _sqlstate(pool: asyncpg.Pool, scope: str, statement: str, *args: object) -> str:
    async with pool.acquire() as connection:
        try:
            async with connection.transaction():
                await apply_scope(connection, scope)
                await connection.execute(statement, *args)
        except asyncpg.PostgresError as error:
            return str(error.sqlstate)
    return "accepted"


async def test_saved_results_are_written_once_and_advance_by_cas(
    common_db: CommonDatabase,  # noqa: F811
    pool: asyncpg.Pool,
) -> None:
    scope = common_db.scope("tenant-1")
    # The lineage of this proof is not in PostgreSQL: no attempt row carries the fence.
    store = PostgresInvocationSettlementStore(pool, require_unit_generation=False)
    record = _saved(scope)
    saved = await store.save(record)
    assert saved == record
    assert await store.save(record) == record, "the same saved bytes return the stored row"
    with pytest.raises(IdempotencyConflict):
        await store.save(_saved(scope, output="other").model_copy(update={"run_id": record.run_id}))
    waiting = saved.advanced(
        SettlementOutcome(
            state="waiting", reason=WaitReason.EFFECT_PENDING, pending_effects=("effect-1",)
        ),
        claim_fence=2,
        at=datetime.now(UTC),
        stop_fence="cancelled",
    )
    stored = await store.advance(waiting, expected_version=1)
    assert stored.settlement is SettlementState.WAITING and stored.pending_effects == ("effect-1",)
    with pytest.raises(SavedSettlementConflict):
        await store.advance(waiting, expected_version=1)
    settled = stored.advanced(
        SettlementOutcome.done(finalization_ref="finalization:1"),
        claim_fence=3,
        at=datetime.now(UTC) + timedelta(seconds=1),
    )
    assert (await store.advance(settled, expected_version=2)).settled
    assert await store.get(common_db.scope("tenant-2"), record.binding_id) is None
    loaded = await store.get(scope, record.binding_id)
    assert loaded == settled and loaded.saved_result == record.saved_result

    # The guard refuses what the domain refuses, even for a direct runtime-role write.
    table = "mission_control.invocation_settlement"
    binding = record.binding_id
    assert (
        await _sqlstate(
            pool,
            scope,
            f"UPDATE {table} SET version = version + 1, updated_at = now() WHERE binding_id = $1",
            binding,
        )
        == "23000"
    ), "a settled row is terminal"
    other = await store.save(_saved(scope, binding="binding-2"))
    for statement in (
        f'UPDATE {table} SET saved_result = \'{{"output_text": "x"}}\' WHERE binding_id = $1',
        f"UPDATE {table} SET version = version + 1, claim_fence = 1 WHERE binding_id = $1",
        f"UPDATE {table} SET version = version + 5 WHERE binding_id = $1",
    ):
        assert await _sqlstate(pool, scope, statement, other.binding_id) == "23000", statement
    fenced = other.advanced(
        SettlementOutcome(
            state="waiting", reason=WaitReason.REVIEW_PENDING, pending_reviews=("r",)
        ),
        claim_fence=2,
        at=datetime.now(UTC),
        stop_fence="cancelled",
    )
    await store.advance(fenced, expected_version=1)
    assert (
        await _sqlstate(
            pool,
            scope,
            f"UPDATE {table} SET version = version + 1, stop_fence = 'none', "
            "record = jsonb_set(jsonb_set(record, '{stop_fence}', '\"none\"'), '{version}', "
            "to_jsonb(version + 1)) WHERE binding_id = $1",
            other.binding_id,
        )
        == "23000"
    ), "a stop fence is never lifted"
    assert (
        await _sqlstate(pool, scope, f"DELETE FROM {table} WHERE binding_id = $1", binding)
        == "42501"
    ), "the runtime role cannot delete a saved result"


async def test_a_fresh_worker_resumes_the_postgres_saved_result_without_cognition(
    common_db: CommonDatabase,  # noqa: F811
    pool: asyncpg.Pool,
) -> None:
    scope = common_db.scope("tenant-1")
    double = DurableEffectDouble()
    harness = await recovery_harness(
        request_scope=scope,
        saved_results=PostgresInvocationSettlementStore(pool, require_unit_generation=False),
        settlers=(double,),
    )
    double.attach(harness.model, answer_turns=(2, 4, 6))
    request = await harness.request(stage_recovery_unit(harness.run_id, request_scope=scope))
    first = await harness.run(request)
    assert first.status == "waiting" and first.failure_code == "effect_pending"
    double.crash_on_pass(2)
    await harness.crash(request)
    double.acknowledge()  # the receipt arrives after the worker that waited for it is gone
    # A fresh worker: the boundary reads the saved row through a new pool and store.
    fresh = await common_db.pool()
    try:
        harness.service._saved_results = PostgresInvocationSettlementStore(
            fresh, require_unit_generation=False
        )
        result = await harness.run(request)
        row = await PostgresInvocationSettlementStore(fresh).get(scope, result.binding_id)
    finally:
        await fresh.close()
    assert result.status == "completed"
    assert len(harness.model.calls) == 2 and double.writes == ["native-write:1"]
    assert harness.runtime.invocations == 1 and len(harness.journal.settlements) == 1
    assert row is not None and row.settled and row.waits == 1
    assert row.saved_result.output_text == result.output_text
    print(
        "WI-04 EVIDENCE postgres restart:",
        {
            "model_calls": len(harness.model.calls),
            "native_writes": len(double.writes),
            "lane_dispatches": harness.runtime.invocations,
            "settlement_passes": len(double.passes),
            "row": {"settlement": row.settlement.value, "waits": row.waits, "version": row.version},
        },
    )


async def test_the_live_fence_and_durable_events_hold_in_the_same_transaction(
    common_db: CommonDatabase,  # noqa: F811
    pool: asyncpg.Pool,
) -> None:
    """Review 5: the production store refuses a writer whose unit generation has no current
    attempt fence (a stale or unknown holder) and changes nothing; review 4: durable events
    are appended once per kind and sequence and are immutable."""

    scope = common_db.scope("tenant-1")
    lenient = PostgresInvocationSettlementStore(pool, require_unit_generation=False)
    strict = PostgresInvocationSettlementStore(pool)
    record = await strict.save(_saved(scope, binding="binding-live"))
    successor = record.advanced(SettlementOutcome.done(), claim_fence=2, at=datetime.now(UTC))
    with pytest.raises(StaleSettlementHolder):
        await strict.advance(successor, expected_version=1)
    unchanged = await strict.get(scope, record.binding_id)
    assert unchanged is not None and unchanged.version == 1 and not unchanged.settled
    event = SettlementEvent(
        settlement_id=record.settlement_id,
        kind="review_alarm",
        sequence=1,
        occurred_at=datetime.now(UTC),
        detail={"pending_reviews": ["r"]},
    )
    assert await lenient.record_event(record, event) is True
    assert await lenient.record_event(record, event) is False
    table = "mission_control.invocation_settlement_event"
    assert (
        await _sqlstate(pool, scope, f"UPDATE {table} SET sequence = 2 WHERE sequence = 1")
        == "42501"
    ), "the runtime role cannot rewrite an event (and the owner is refused by reject_mutation)"
    assert (await lenient.advance(successor, expected_version=1)).settled


async def test_native_receipt_reference_snapshot_survives_new_pool_and_store(
    common_db: CommonDatabase,  # noqa: F811
) -> None:
    import json

    from tests.unit.operations.test_native_receipt_evidence import EFFECT, RECEIPT, REFERENCES

    await common_db.add_tenants(["tenant-1", "tenant-2"])
    scope = common_db.scope("tenant-1")
    first_pool = await common_db.pool()
    original = _saved(scope, binding="native-evidence-restart")
    try:
        first_store = PostgresInvocationSettlementStore(first_pool, require_unit_generation=False)
        saved = await first_store.save(original)
        waiting = saved.advanced(
            SettlementOutcome(
                state="waiting",
                reason=WaitReason.EFFECT_PENDING,
                pending_effects=(EFFECT,),
                detail={
                    "native_effects": [
                        REFERENCES
                        | {
                            "state": "pending_effect",
                            "receipt_ref": None,
                            "receipt_digest": None,
                            "journal_state": "uncertain",
                        }
                    ],
                    "raw_provider_body": "PRIVATE_DETAIL",
                },
            ),
            claim_fence=2,
            at=datetime.now(UTC),
        )
        await first_store.advance(waiting, expected_version=1)
    finally:
        await first_pool.close()

    second_pool = await common_db.pool()
    try:
        restarted = PostgresInvocationSettlementStore(second_pool, require_unit_generation=False)
        loaded = await restarted.get(scope, original.binding_id)
        assert loaded is not None
        assert (
            loaded.evidence()["invocation_settlement"]["native_effects"][0]["state"]
            == "pending_effect"
        )
        assert await restarted.get(common_db.scope("tenant-2"), original.binding_id) is None
        complete = loaded.advanced(
            SettlementOutcome.done(
                detail={"native_effects": [REFERENCES | {"raw_receipt": "PRIVATE_RECEIPT"}]}
            ),
            claim_fence=3,
            at=datetime.now(UTC),
        )
        await restarted.advance(complete, expected_version=loaded.version)
        with pytest.raises(SavedSettlementConflict):
            await restarted.advance(complete, expected_version=loaded.version)
    finally:
        await second_pool.close()

    third_pool = await common_db.pool()
    try:
        final = await PostgresInvocationSettlementStore(
            third_pool, require_unit_generation=False
        ).get(scope, original.binding_id)
        assert final is not None and final.settled
        assert (
            final.evidence()["invocation_settlement"]["native_effects"][0]["receipt_ref"] == RECEIPT
        )
        assert final.saved_result == original.saved_result
        assert final.saved_result_digest == original.saved_result_digest
        assert "PRIVATE_" not in json.dumps(final.evidence())
        assert "PRIVATE_" not in final.model_dump_json()
    finally:
        await third_pool.close()
