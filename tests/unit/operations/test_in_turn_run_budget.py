"""W1 D38 / D41 (session 12) through the governed operation boundary.

A unit that, like a Goal Loop iteration, reserves none of the dimensions its turn spends
(here `concurrency.slots`) runs the real Deep Agents adapter against real run control
(`RunControlOperationAuthority`, the journaled settlement):

- D38: its tokens are recorded as consumed on the run's declared `tokens.total`, not 0.
- D41: the turn is stopped once it exceeds what the run's hard cap leaves, and the attempt
  settles `failed/budget_exceeded` with its spend recorded.
"""

from __future__ import annotations

import pytest

from mission_control.application.execution.operations.operation_execution import (
    RunBudgetStatePort,
    bind_operation_execution_request,
    in_turn_run_budget,
)
from mission_control.domain.policies.contracts import (
    BudgetApplicability,
    BudgetDimensionLimit,
    BudgetState,
    CommandStatus,
    ReserveBudgetAction,
)
from tests.fixtures.checkpoint_recovery import (
    TOKENS_PER_CALL,
    recovery_harness,
    stage_recovery_unit,
)
from tests.unit.run_control.test_run_control import command

SLOT = {"concurrency.slots": 1}


async def _leave(harness: object, tokens: int) -> None:
    """Another unit holds the run's token cap (reserved, not yet consumed) but `tokens`."""

    run_control = harness.run_control  # type: ignore[attr-defined]
    run = await run_control.get_run("tenant-1", harness.run_id)  # type: ignore[attr-defined]
    budget = await run_control.get_budget("tenant-1", harness.run_id)  # type: ignore[attr-defined]
    cap = next(item.hard_cap for item in budget.limits if item.dimension == "tokens.total")
    held = budget.reserved.get("tokens.total", 0) + budget.consumed.get("tokens.total", 0)
    amounts = {"tokens.total": cap - held - tokens}
    held = await run_control.execute(
        command(
            harness.run_id,  # type: ignore[attr-defined]
            run.version,
            "reserve:other-unit",
            ReserveBudgetAction(reservation_id="reservation:other-unit", amounts=amounts),
        )
    )
    assert held.status == CommandStatus.ACCEPTED, (held.reason_code, held.reason)


@pytest.mark.asyncio
async def test_a_unit_without_a_token_reservation_records_its_tokens_on_the_run() -> None:
    harness = await recovery_harness(real_authority=True)
    assert isinstance(harness.service._authority, RunBudgetStatePort)
    request = await harness.request(stage_recovery_unit(harness.run_id), reservation=SLOT)

    result = await harness.run(request)

    assert result.status == "completed"
    assert result.usage.amounts.get("tokens.total") == 2 * TOKENS_PER_CALL
    budget = await harness.run_control.get_budget("tenant-1", harness.run_id)
    assert budget.consumed.get("tokens.total") == 2 * TOKENS_PER_CALL


@pytest.mark.asyncio
async def test_the_turn_stops_at_what_the_runs_hard_cap_leaves() -> None:
    harness = await recovery_harness(real_authority=True)
    await _leave(harness, TOKENS_PER_CALL - 1)
    request = await harness.request(stage_recovery_unit(harness.run_id), reservation=SLOT)

    result = await harness.run(request)

    # Call 1 spent 5 tokens > the 4 the run's cap leaves: call 2 is answered by the stop.
    assert len(harness.model.calls) == 1
    assert result.status == "failed" and result.failure_code == "budget_exceeded"
    assert result.usage.amounts.get("tokens.total") == TOKENS_PER_CALL
    budget = await harness.run_control.get_budget("tenant-1", harness.run_id)
    assert budget.consumed.get("tokens.total") == TOKENS_PER_CALL


@pytest.mark.asyncio
async def test_a_saved_result_of_a_stopped_turn_settles_budget_exceeded() -> None:
    """The default boundary saves the result first (WI-04): the typed stop travels with the
    saved record, so its settlement (and any re-settlement) refuses it the same way."""

    from mission_control.application.execution.operations.invocation_settlement import (
        InMemoryInvocationSettlementStore,
    )

    store = InMemoryInvocationSettlementStore()
    harness = await recovery_harness(real_authority=True, saved_results=store)
    await _leave(harness, TOKENS_PER_CALL - 1)
    request = await harness.request(stage_recovery_unit(harness.run_id), reservation=SLOT)

    result = await harness.run(request)

    assert result.status == "failed" and result.failure_code == "budget_exceeded"
    (record,) = store.records.values()
    assert record.saved_result.budget_stop == {
        "tokens.total": {"limit": TOKENS_PER_CALL - 1, "spent": TOKENS_PER_CALL}
    }
    budget = await harness.run_control.get_budget("tenant-1", harness.run_id)
    assert budget.consumed.get("tokens.total") == TOKENS_PER_CALL


def _budget(**update: object) -> BudgetState:
    state = BudgetState(
        account_id="account-1",
        run_id="run-1",
        limits=(
            BudgetDimensionLimit(
                dimension="tokens.total", applicability=BudgetApplicability.BOUNDED, hard_cap=100
            ),
            BudgetDimensionLimit(
                dimension="tool.calls.total",
                applicability=BudgetApplicability.BOUNDED,
                hard_cap=20,
            ),
            BudgetDimensionLimit(
                dimension="model.turns", applicability=BudgetApplicability.UNBOUNDED
            ),
            BudgetDimensionLimit(
                dimension="goal.iterations", applicability=BudgetApplicability.BOUNDED, hard_cap=3
            ),
        ),
    )
    return state.model_copy(update=update)


def test_the_in_turn_run_budget_is_the_hard_cap_less_what_others_hold_and_spent() -> None:
    from tests.unit.harness.test_lane_settlement_usage import _stage_operation

    binding = bind_operation_execution_request(_stage_operation())
    own = binding.budget_reservation_id
    budget = _budget(
        consumed={"tokens.total": 30, "tool.calls.total": 4},
        pending_settlement={"tokens.total": 5},
        reserved={"tokens.total": 50, "tool.calls.total": 2},
        reservations={own: {"tokens.total": 10}, "other": {"tokens.total": 40}},
    )
    dimensions, remaining = in_turn_run_budget(budget, binding)
    assert dimensions == ("model.turns", "tokens.total", "tool.calls.total")
    # 100 - 30 consumed - 5 pending - 50 reserved + this unit's own 10 = 25.
    assert remaining == {"tokens.total": 25, "tool.calls.total": 14}


def test_the_in_turn_run_budget_does_not_count_the_units_own_recorded_usage() -> None:
    """A settlement re-checked after its usage was recorded reads the same remainder."""

    from mission_control.application.execution.operations.operation_execution import (
        operation_settlement_id,
    )
    from mission_control.domain.policies.contracts import UsageRecord
    from tests.unit.harness.test_lane_settlement_usage import _stage_operation

    binding = bind_operation_execution_request(_stage_operation())
    settlement_id = operation_settlement_id(binding.binding_id)
    before = _budget(consumed={"tokens.total": 30})
    after = _budget(
        consumed={"tokens.total": 37},
        usage_records={
            settlement_id: UsageRecord(
                usage_id=settlement_id,
                reservation_id=binding.budget_reservation_id,
                authority_ref=binding.binding_id,
                actual_amounts={"tokens.total": 7},
            )
        },
    )
    assert in_turn_run_budget(before, binding) == in_turn_run_budget(after, binding)
