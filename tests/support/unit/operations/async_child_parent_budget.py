"""Builders, constants and fakes that other test files import.

Moved from tests/unit/operations/test_async_child_parent_budget.py.
"""

from __future__ import annotations

from mission_control.domain.policies.contracts import (
    BudgetApplicability,
    BudgetDimensionLimit,
    CommandStatus,
    ReserveBudgetAction,
    StartAction,
)
from tests.support.deep_agents import request
from tests.support.run_control import command
from tests.support.run_control import request as run_request
from tests.support.run_control import service as run_control_service


async def admitted_parent(*, bounded: dict[str, int] | None = None) -> tuple[object, str]:
    """An admitted, started parent run; `bounded` turns the named dimensions into bounded ones."""

    run_control, _ = run_control_service()
    parent = run_request(request_id="rrm-013-parent")
    if bounded:
        envelope = parent.budget_envelope
        dimensions = tuple(
            BudgetDimensionLimit(
                dimension=limit.dimension,
                applicability=BudgetApplicability.BOUNDED,
                hard_cap=bounded[limit.dimension],
            )
            if limit.dimension in bounded
            else limit
            for limit in envelope.dimensions
        )
        parent = parent.model_copy(
            update={"budget_envelope": envelope.model_copy(update={"dimensions": dimensions})}
        )
    decision = await run_control.admit(parent)
    assert decision.run_id is not None
    started = await run_control.execute(command(decision.run_id, 1, "start", StartAction()))
    assert started.status == CommandStatus.ACCEPTED
    reserved = await run_control.execute(
        command(
            decision.run_id,
            started.resulting_run_version,
            "reserve-parent",
            ReserveBudgetAction(
                reservation_id="reservation:parent-operation", amounts={"tokens.total": 20}
            ),
        )
    )
    assert reserved.status == CommandStatus.ACCEPTED
    return run_control, decision.run_id


def spawn(run_id: str, *, limits: dict[str, int] | None = None):  # type: ignore[no-untyped-def]
    base = request()
    contract = base.contract.model_copy(update={"budget_limits": limits or {"tokens.total": 10}})
    contract = type(contract).create(
        **contract.model_dump(mode="python", exclude={"contract_digest"})
    )
    return base.model_copy(
        update={
            "request_scope": "tenant-1",
            "parent_run_id": run_id,
            "contract": contract,
            "parent_reservation_id": "reservation:parent-operation",
        }
    )
