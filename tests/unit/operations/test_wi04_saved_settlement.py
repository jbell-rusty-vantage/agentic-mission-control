"""WI-04 / OVE-166 (RV-01): saved provider results settle without repeated cognition.

A real `create_deep_agent` graph (deterministic scripted model, two calls per cognition) runs
through the whole operation boundary (RRM-004 harness: journaled coordinator, checkpoint
lineage, in-memory run control) with the saved-result store and a generic durable-wait double
(`tests/fixtures/saved_settlement.py`): cognition performs one native write per answer turn,
the write needs a receipt and an independent review may hold the result. Worker loss is a
`SimulatedWorkerCrash` (no lease release, nothing settled); a fresh worker takes the lease over
after it expires. Every window converges to one logical result with the model called twice,
one native write, one lane dispatch and one operation settlement.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from mission_control.application.execution.operations.invocation_settlement import (
    InMemoryInvocationSettlementStore,
    SavedSettlementConflict,
    StaleSettlementHolder,
)
from mission_control.domain.execution.contracts import RuntimeResult
from mission_control.domain.execution.invocation_settlement import (
    FIRST_WAIT_SECONDS,
    InvocationSettlement,
    SettlementOutcome,
    SettlementState,
    WaitReason,
    invocation_settlement_id,
    wait_seconds,
)
from mission_control.domain.policies.contracts import CommandStatus, ReconcileUnitAction
from mission_control.domain.policies.errors import IdempotencyConflict
from tests.fixtures.checkpoint_recovery import (
    RESULT_MARKER,
    TOKENS_PER_CALL,
    MutableClock,
    RecoveryHarness,
    recovery_harness,
    stage_recovery_unit,
)
from tests.fixtures.saved_settlement import REVIEW, DurableEffectDouble

ANSWER_TURNS = (2, 4, 6)


async def _stack(
    *,
    review: bool = False,
    acknowledged: bool = False,
    store: InMemoryInvocationSettlementStore | None = None,
    **options: Any,
) -> tuple[RecoveryHarness, DurableEffectDouble, InMemoryInvocationSettlementStore, Any]:
    double = DurableEffectDouble(review_required=review, acknowledge_on_write=acknowledged)
    store = store or InMemoryInvocationSettlementStore()
    harness = await recovery_harness(
        saved_results=store, settlers=(double,), service_options=options
    )
    double.attach(harness.model, answer_turns=ANSWER_TURNS)
    request = await harness.request(stage_recovery_unit(harness.run_id))
    return harness, double, store, request


def _record(store: InMemoryInvocationSettlementStore) -> InvocationSettlement:
    (record,) = store.records.values()
    return record


def _one_logical_result(harness: RecoveryHarness, double: DurableEffectDouble, result: Any) -> None:
    """The invariant of every window: one cognition, one native write, one settlement."""

    assert len(harness.model.calls) == 2, "the model was never called again"
    assert double.writes == ["native-write:1"], "no second native write"
    assert len(harness.journal.settlements) == 1
    assert json.loads(result.output_text)["answer"] == RESULT_MARKER
    assert result.usage.amounts["tokens.total"] == 2 * TOKENS_PER_CALL


@pytest.mark.asyncio
async def test_completed_result_is_saved_before_settlement_and_settles_once() -> None:
    harness, double, store, request = await _stack(acknowledged=True)
    result = await harness.run(request)
    assert result.status == "completed"
    _one_logical_result(harness, double, result)
    record = _record(store)
    assert record.settled and record.stop_fence == "none"
    assert record.execution_outcome == "completed"
    assert record.finalization_ref == "finalization:double"
    assert [item.settlement for item in store.history] == [
        SettlementState.PENDING,
        SettlementState.SETTLED,
    ]
    assert record.saved_result.checkpoint is not None
    assert result.result_checkpoint == record.saved_result.checkpoint.result_key
    assert record.recovery_owner == f"operation/{request.identity.semantic_key}"
    [settlement] = harness.journal.settlements.values()
    assert settlement.status == "completed"
    # A settled unit returns unchanged: no pass, no dispatch.
    again = await harness.run(request)
    assert (again.status, again.output_text) == (result.status, result.output_text)
    assert double.passes == [False]
    assert harness.runtime.invocations == 1


@pytest.mark.asyncio
async def test_crash_after_provider_completion_resumes_the_saved_result() -> None:
    """Window 1: the worker is lost in the first settlement pass, after the save."""

    harness, double, store, request = await _stack(acknowledged=True)
    double.crash_on_pass(1)
    await harness.crash(request)
    assert _record(store).settlement is SettlementState.PENDING
    assert not harness.journal.settlements
    result = await harness.run(request)
    assert result.status == "completed"
    _one_logical_result(harness, double, result)
    assert harness.runtime.invocations == 1, "the saved result is consumed, never redispatched"
    assert double.passes == [False, False]


@pytest.mark.asyncio
async def test_crash_between_cognition_and_the_save_reconstructs_without_a_model_call() -> None:
    """Window 1': lost after the lane returned, before the save. The redispatch is classified
    `terminal_unobserved` from the checkpointer: no model call, no write; then it is saved."""

    harness, double, store, request = await _stack(acknowledged=True)
    harness.runtime.crash_after_invocation = True
    await harness.crash(request)
    assert not store.records
    result = await harness.run(request)
    assert result.status == "completed"
    _one_logical_result(harness, double, result)
    assert harness.runtime.invocations == 2
    assert _record(store).settled


@pytest.mark.asyncio
async def test_review_wait_survives_a_crash_and_settles_after_the_verdict() -> None:
    """Window 2: the review holds the saved result; the worker is lost while polling it."""

    harness, double, store, request = await _stack(review=True, acknowledged=True)
    first = await harness.run(request)
    assert first.status == "waiting" and first.failure_code == "review_pending"
    assert first.settlement_wait is not None
    assert first.settlement_wait["pending_reviews"] == [REVIEW]
    assert first.settlement_wait["next_action"] == "await_review"
    assert first.settlement_wait["wait_seconds"] == FIRST_WAIT_SECONDS
    assert not harness.journal.settlements, "waiting is not a settlement"
    double.crash_on_pass(2)
    await harness.crash(request)
    double.verdict()
    result = await harness.run(request)
    assert result.status == "completed"
    _one_logical_result(harness, double, result)
    assert harness.runtime.invocations == 1
    assert double.passes == [False, False, False]
    assert [item.settlement for item in store.history] == [
        SettlementState.PENDING,
        SettlementState.WAITING,
        SettlementState.SETTLED,
    ]


@pytest.mark.asyncio
async def test_effect_wait_survives_a_crash_without_a_second_native_write() -> None:
    """Window 3: the native write's receipt is pending; the worker is lost; the receipt lands."""

    harness, double, store, request = await _stack()
    first = await harness.run(request)
    assert first.status == "waiting" and first.failure_code == "effect_pending"
    assert first.settlement_wait is not None
    assert first.settlement_wait["pending_effects"] == ["native-write:1"]
    assert _record(store).pending_effects == ("native-write:1",)
    double.crash_on_pass(2)
    await harness.crash(request)
    double.acknowledge()
    result = await harness.run(request)
    assert result.status == "completed"
    _one_logical_result(harness, double, result)
    assert harness.runtime.invocations == 1


@pytest.mark.asyncio
async def test_late_acknowledgment_settles_the_saved_result_exactly_once() -> None:
    """Window 4: passes keep waiting (growing durable delay) until the receipt arrives late;
    the next pass settles; later attempts and a duplicate receipt change nothing."""

    harness, double, store, request = await _stack()
    first = await harness.run(request)
    second = await harness.run(request)
    assert (first.status, second.status) == ("waiting", "waiting")
    assert first.settlement_wait is not None and second.settlement_wait is not None
    assert second.settlement_wait["wait_seconds"] > first.settlement_wait["wait_seconds"]
    double.acknowledge()
    result = await harness.run(request)
    assert result.status == "completed"
    double.acknowledge()
    again = await harness.run(request)
    assert again.status == "completed" and again.output_text == result.output_text
    _one_logical_result(harness, double, result)
    assert double.passes == [False, False, False]
    assert harness.runtime.invocations == 1
    assert _record(store).waits == 2


@pytest.mark.asyncio
async def test_unavailable_settlement_is_a_wait_not_a_cognition_failure() -> None:
    harness, double, store, request = await _stack(acknowledged=True)
    double.unavailable_passes = 1
    first = await harness.run(request)
    assert first.status == "waiting" and first.failure_code == "settlement_unavailable"
    assert _record(store).next_action == "retry_settlement"
    result = await harness.run(request)
    assert result.status == "completed"
    _one_logical_result(harness, double, result)


@pytest.mark.asyncio
async def test_cancellation_after_completion_settles_the_saved_result_honestly() -> None:
    """Window 5: a cancel while the review holds the result. The saga's fenced pass starts no
    evaluation; the unit settles `cancelled` with its completed outcome, output and usage."""

    harness, double, store, request = await _stack(review=True, acknowledged=True)
    assert (await harness.run(request)).status == "waiting"
    result = await harness.service.cancel(request, harness.attempt(request))
    assert result.status == "cancelled" and result.failure_code == "cancelled"
    _one_logical_result(harness, double, result)
    assert double.passes == [False, True], "the saga's pass is fenced"
    record = _record(store)
    assert record.settled and record.stop_fence == "cancelled"
    assert record.execution_outcome == "completed"
    [settlement] = harness.journal.settlements.values()
    assert settlement.status == "cancelled"
    assert harness.runtime.invocations == 1
    # The verdict arriving after the cancel reopens nothing.
    double.verdict()
    again = await harness.service.cancel(request, harness.attempt(request))
    assert again.status == "cancelled" and double.passes == [False, True]


@pytest.mark.asyncio
async def test_cancellation_still_reconciles_a_committed_effect_before_settling() -> None:
    harness, double, store, request = await _stack()
    assert (await harness.run(request)).status == "waiting"
    held = await harness.service.cancel(request, harness.attempt(request))
    assert held.status == "waiting" and held.failure_code == "effect_pending"
    assert _record(store).stop_fence == "cancelled"
    assert not harness.journal.settlements
    double.acknowledge()
    result = await harness.service.cancel(request, harness.attempt(request))
    assert result.status == "cancelled"
    _one_logical_result(harness, double, result)
    assert double.passes == [False, True, True]


# --- the record's own rules -------------------------------------------------------------------


def _saved(fence: int = 1, output: str = "done") -> InvocationSettlement:
    return InvocationSettlement.save(
        request_scope="tenant-1",
        run_id="run-1",
        binding_id="binding-1",
        operation_ref="operation-1",
        operation_attempt=1,
        unit_key="unit-1",
        execution_generation=1,
        result=RuntimeResult(output_text=output),
        recovery_owner="operation/workflow-1",
        claim_fence=fence,
        at=datetime.now(UTC),
    )


def test_settlement_record_rules() -> None:
    record = _saved(fence=2)
    assert record.settlement_id == invocation_settlement_id("binding-1")
    assert record.saved_result_ref.startswith("saved-result:")
    waiting = record.advanced(
        SettlementOutcome(
            state="waiting", reason=WaitReason.REVIEW_PENDING, pending_reviews=("r",)
        ),
        claim_fence=2,
        at=datetime.now(UTC),
    )
    assert (waiting.version, waiting.waits, waiting.next_action) == (2, 1, "await_review")
    with pytest.raises(ValueError, match="fenced-out"):
        waiting.advanced(SettlementOutcome.done(), claim_fence=1, at=datetime.now(UTC))
    fenced = waiting.advanced(
        SettlementOutcome(
            state="waiting", reason=WaitReason.EFFECT_PENDING, pending_effects=("e",)
        ),
        claim_fence=3,
        at=datetime.now(UTC),
        stop_fence="cancelled",
    )
    with pytest.raises(ValueError, match="never lifted"):
        fenced.advanced(
            SettlementOutcome.done(), claim_fence=3, at=datetime.now(UTC), stop_fence="none"
        )
    settled = fenced.advanced(SettlementOutcome.done(), claim_fence=3, at=datetime.now(UTC))
    assert settled.settled and settled.next_action is None and settled.stop_fence == "cancelled"
    with pytest.raises(ValueError, match="never changes"):
        settled.advanced(SettlementOutcome.done(), claim_fence=3, at=datetime.now(UTC))
    with pytest.raises(ValueError, match="names its reason"):
        SettlementOutcome(state="waiting")
    with pytest.raises(ValueError, match="pending effects"):
        SettlementOutcome(state="waiting", reason=WaitReason.EFFECT_PENDING)
    assert [wait_seconds(n) for n in (0, 1, 2, 3, 20)] == [5, 5, 10, 20, 3_600]
    assert wait_seconds(20, cap=300) == 300 and wait_seconds(30, cap=10**9) == 7 * 86_400


@pytest.mark.asyncio
async def test_in_memory_store_guards() -> None:
    store = InMemoryInvocationSettlementStore()
    record = await store.save(_saved())
    assert await store.save(_saved()) == record
    other = _saved(output="other")
    with pytest.raises(IdempotencyConflict):
        await store.save(other)
    waiting = record.advanced(
        SettlementOutcome(
            state="waiting", reason=WaitReason.REVIEW_PENDING, pending_reviews=("r",)
        ),
        claim_fence=1,
        at=datetime.now(UTC),
    )
    assert (await store.advance(waiting, expected_version=1)).version == 2
    with pytest.raises(SavedSettlementConflict):
        await store.advance(waiting, expected_version=1)


# --- review fixes ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_fenced_pass_that_cannot_run_still_waits_for_the_committed_effect() -> None:
    """Review 1: under cancellation only a review stops holding the result; an unavailable
    pass and an unresolved effect keep it waiting until the effect is reconciled."""

    harness, double, _store, request = await _stack()
    assert (await harness.run(request)).status == "waiting"
    double.unavailable_passes = 1
    first = await harness.service.cancel(request, harness.attempt(request))
    assert first.status == "waiting" and first.failure_code == "settlement_unavailable"
    second = await harness.service.cancel(request, harness.attempt(request))
    assert second.status == "waiting" and second.failure_code == "effect_pending"
    assert not harness.journal.settlements
    double.acknowledge()
    result = await harness.service.cancel(request, harness.attempt(request))
    assert result.status == "cancelled"
    _one_logical_result(harness, double, result)
    assert double.passes == [False, True, True, True]


@pytest.mark.asyncio
async def test_the_result_is_saved_before_the_fence_check_and_survives_its_error() -> None:
    """Review 2: a transient error in the post-turn fence check after completion neither
    loses the result nor redispatches cognition."""

    harness, double, store, request = await _stack(acknowledged=True)
    original = harness.service._turn_fence
    calls = {"n": 0}

    async def flaky(*args: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("stop fence store unavailable")
        return await original(*args)

    harness.service._turn_fence = flaky  # type: ignore[method-assign]
    with pytest.raises(ConnectionError):
        await harness.run(request)
    assert _record(store).settlement is SettlementState.PENDING
    result = await harness.run(request)
    assert result.status == "completed"
    _one_logical_result(harness, double, result)
    assert harness.runtime.invocations == 1


@pytest.mark.asyncio
async def test_a_result_over_the_saved_bound_settles_failed_with_usage_retained() -> None:
    """Review 3: typed, non-retryable; the completed cognition's usage is charged."""

    harness, double, store, request = await _stack(
        acknowledged=True, store=InMemoryInvocationSettlementStore(max_bytes=64)
    )
    result = await harness.run(request)
    assert result.status == "failed" and result.failure_code == "saved_result_too_large"
    assert result.usage.amounts["tokens.total"] == 2 * TOKENS_PER_CALL
    assert result.result_checkpoint is not None
    assert not store.records and double.passes == []
    assert len(harness.model.calls) == 2 and len(harness.journal.settlements) == 1


@pytest.mark.asyncio
async def test_another_saved_result_for_the_binding_parks_the_unit_in_doubt() -> None:
    """Review 3: a different saved result for the same binding is an operator incident."""

    harness, _double, store, request = await _stack(acknowledged=True)

    async def conflict(record: InvocationSettlement) -> InvocationSettlement:
        raise IdempotencyConflict("the binding already saved another provider result")

    store.save = conflict  # type: ignore[method-assign]
    result = await harness.run(request)
    assert result.status == "in_doubt"
    assert result.failure_code == "unrecoverable_result_manifest"
    assert result.reconciliation_incident_id is not None
    assert not harness.journal.settlements and harness.runtime.invocations == 1


@pytest.mark.asyncio
async def test_an_effect_wait_past_its_deadline_becomes_an_operator_incident() -> None:
    """Review 4: no silent settle; the incident names the pending effect and a durable
    `effect_deadline` event is recorded (abandonment: the two abandon tests below)."""

    harness, double, store, request = await _stack(effect_wait_deadline=timedelta(0))
    parked = await harness.run(request)
    assert parked.status == "in_doubt" and parked.failure_code == "unsettled_effect_claims"
    [event] = store.events
    assert event.kind == "effect_deadline"
    assert event.detail == {"pending_effects": ["native-write:1"]}
    assert _record(store).settlement is SettlementState.WAITING
    assert not harness.journal.settlements
    # Still parked on the next attempt until the operator decides.
    assert (await harness.run(request)).status == "in_doubt"
    assert harness.runtime.invocations == 1 and double.writes == ["native-write:1"]


@pytest.mark.asyncio
async def test_a_review_wait_has_no_deadline_and_records_durable_alarms() -> None:
    clock = MutableClock()
    harness, double, store, request = await _stack(
        review=True,
        acknowledged=True,
        effect_wait_deadline=timedelta(0),
        review_alarm_interval=timedelta(hours=1),
        settlement_clock=clock,
    )
    assert (await harness.run(request)).status == "waiting"
    assert not store.events, "no alarm before one interval"
    clock.advance(timedelta(minutes=61))
    first = await harness.run(request)
    clock.advance(timedelta(hours=1))
    second = await harness.run(request)
    assert (first.status, second.status) == ("waiting", "waiting"), "no deadline for a review"
    alarms = [event for event in store.events if event.kind == "review_alarm"]
    assert [alarm.sequence for alarm in alarms] == [1, 2]
    assert alarms[0].detail["pending_reviews"] == [REVIEW]
    double.verdict()
    assert (await harness.run(request)).status == "completed"


@pytest.mark.asyncio
async def test_a_configured_cap_bounds_the_durable_wait() -> None:
    harness, _double, _store, request = await _stack(settlement_wait_cap=timedelta(seconds=7))
    waits = [(await harness.run(request)).settlement_wait for _ in range(4)]
    assert [item["wait_seconds"] for item in waits if item is not None] == [5, 7, 7, 7]


@pytest.mark.asyncio
async def test_a_stale_holder_cannot_advance_the_saved_result() -> None:
    """Review 5: the writer's fence must be the unit's current fence in the same write,
    even when the holder that fenced it out has not written yet."""

    harness, double, store, request = await _stack(acknowledged=True)
    double.crash_on_pass(1)
    await harness.crash(request)
    record = _record(store)
    assert store.fences is not None
    current = store.fences(record.request_scope, record.unit_key, record.execution_generation)
    assert current == record.claim_fence
    # A takeover advances the unit's fence; the old holder's successor is refused.
    key = (record.request_scope, record.unit_key, record.execution_generation)
    generation = harness.lineage.generations[key]
    harness.lineage.generations[key] = type(generation)(
        **{**generation.__dict__, "claim_fence": generation.claim_fence + 1}
    )
    stale = record.advanced(SettlementOutcome.done(), claim_fence=current, at=datetime.now(UTC))
    with pytest.raises(StaleSettlementHolder):
        await store.advance(stale, expected_version=record.version)
    assert _record(store).settlement is SettlementState.PENDING


# --- re-review fixes --------------------------------------------------------------------------


async def _decide(
    harness: RecoveryHarness, request: Any, parked: Any, decision: str, **extra: Any
) -> None:
    assert parked.reconciliation_incident_id is not None and request.runtime_unit is not None
    decided = await harness.reconcile(
        request,
        f"reconcile-{decision}-{parked.reconciliation_incident_id}",
        ReconcileUnitAction(
            unit_key=request.runtime_unit.unit_key,
            execution_generation=1,
            incident_id=parked.reconciliation_incident_id,
            decision=decision,  # type: ignore[arg-type]
            **extra,
        ),
    )
    assert decided.status == CommandStatus.ACCEPTED, decided


@pytest.mark.asyncio
async def test_an_abandoned_saved_result_keeps_its_known_spend() -> None:
    """Re-review 1 (execute path): `abandon_unit` settles `failed` (`in_doubt_abandoned`) with
    the saved result's usage; the accepted abandonment closed the lineage, so no checkpoint
    transition is written (the key is evidence); the saved record ends settled."""

    harness, double, store, request = await _stack(effect_wait_deadline=timedelta(0))
    parked = await harness.run(request)
    assert parked.status == "in_doubt"
    await _decide(harness, request, parked, "abandon_unit")
    result = await harness.run(request)
    assert result.status == "failed" and result.failure_code == "in_doubt_abandoned"
    assert result.usage.amounts["tokens.total"] == 2 * TOKENS_PER_CALL
    assert result.result_checkpoint is None
    assert _record(store).settled
    assert harness.runtime.invocations == 1 and double.writes == ["native-write:1"]
    assert len(harness.journal.settlements) == 1


@pytest.mark.asyncio
async def test_an_abandoned_saved_result_keeps_its_known_spend_on_the_cancel_path() -> None:
    harness, double, store, request = await _stack(effect_wait_deadline=timedelta(0))
    parked = await harness.run(request)
    await _decide(harness, request, parked, "abandon_unit")
    result = await harness.service.cancel(request, harness.attempt(request))
    assert result.status == "cancelled" and result.failure_code == "in_doubt_abandoned"
    assert result.usage.amounts["tokens.total"] == 2 * TOKENS_PER_CALL
    assert result.result_checkpoint is None
    assert _record(store).settled
    assert harness.runtime.invocations == 1 and double.writes == ["native-write:1"]


@pytest.mark.asyncio
async def test_an_operator_resume_restarts_the_effect_deadline_once() -> None:
    """Re-review 2: after the operator accepts the saved result's checkpoint, the effect wait
    keeps waiting (no resume/incident loop) and escalates only after a fresh full deadline."""

    clock = MutableClock()
    harness, double, store, request = await _stack(
        effect_wait_deadline=timedelta(hours=1), settlement_clock=clock
    )
    assert (await harness.run(request)).status == "waiting"
    clock.advance(timedelta(hours=2))
    parked = await harness.run(request)
    assert parked.status == "in_doubt" and parked.failure_code == "unsettled_effect_claims"
    checkpoint = _record(store).saved_result.checkpoint
    assert checkpoint is not None
    await _decide(
        harness, request, parked, "accept_descendant", accepted_checkpoint=checkpoint.result_key
    )
    resumed = await harness.run(request)
    assert resumed.status == "waiting" and resumed.failure_code == "effect_pending"
    record = _record(store)
    assert record.effect_wait_since == clock() and record.effect_wait_decision is not None
    clock.advance(timedelta(minutes=30))
    assert (await harness.run(request)).status == "waiting", "the same decision restarts once"
    assert _record(store).effect_wait_since == record.effect_wait_since
    clock.advance(timedelta(minutes=31))
    again = await harness.run(request)
    assert again.status == "in_doubt" and again.failure_code == "unsettled_effect_claims"
    assert [event.kind for event in store.events] == ["effect_deadline", "effect_deadline"]
    assert harness.runtime.invocations == 1 and double.writes == ["native-write:1"]


@pytest.mark.asyncio
async def test_a_long_review_then_an_effect_wait_does_not_escalate_at_once() -> None:
    """Re-review 2: the deadline is anchored at the start of the effect wait, not the save."""

    clock = MutableClock()
    harness, double, store, request = await _stack(
        review=True,
        acknowledged=True,
        effect_wait_deadline=timedelta(hours=1),
        review_alarm_interval=timedelta(hours=10),
        settlement_clock=clock,
    )
    assert (await harness.run(request)).status == "waiting"
    assert _record(store).effect_wait_since is None
    clock.advance(timedelta(hours=5))
    double.verdict()
    double.receipts.clear()  # the native receipt is now in doubt: an effect wait begins
    first = await harness.run(request)
    assert first.status == "waiting" and first.failure_code == "effect_pending"
    assert _record(store).effect_wait_since == clock()
    clock.advance(timedelta(minutes=59))
    assert (await harness.run(request)).status == "waiting"
    clock.advance(timedelta(minutes=2))
    assert (await harness.run(request)).status == "in_doubt"
