"""W1 D26: a failed family whose unit budget never settles still reaches a terminal run.

Run 29a1eae9 retried `coordinator.terminalize_failed_family` on `budget_not_settled` (its
unit's saved settlement waited on evaluators). From activity attempt
`LIABILITY_TERMINALIZATION_ATTEMPT`, and only when the previous attempt was refused at the same
run version (nothing progressed), the run closes `failed` with every unsettled reservation and
effect named as a terminal liability (`budget_unsettled_at_failure`). Nothing is released on the
unit's behalf: each liability holds an `operator_reconciliation` wait on the closed run (an
actionable blocked notice) until the privileged `reconcile_terminal_liability` decision closes
it through the ordinary usage ledger. The reducer accepts such a close only when the named
liabilities are exactly the outstanding ones, and a late settlement changes nothing.
"""

from __future__ import annotations

from typing import Any

import pytest

from mission_control.application.execution.family_failure import (
    FamilyFailureLiabilityPending,
    FamilyFailureTerminalization,
    _proposal,
)
from mission_control.application.programs.service import orchestration_lifecycle_actor
from mission_control.application.subscriptions.coordinator import NotificationKind
from mission_control.domain.policies.contracts import (
    ClaimEffectAction,
    CommandStatus,
    LifecycleCommand,
    ReconcileTerminalLiabilityAction,
    RecordUsageAction,
    RunOutcome,
    RunPhase,
    TerminalizeAction,
    outstanding_liabilities,
    terminal_liability_condition_id,
)
from mission_control.domain.policies.errors import CommandRejected
from mission_control.domain.programs.family_failure import (
    BUDGET_UNSETTLED_AT_FAILURE,
    LIABILITY_TERMINALIZATION_ATTEMPT,
)
from tests.fixtures.goal_directed_journaled import SCOPE
from tests.unit.coordinator.test_w1_family_failure_terminalization import _request
from tests.unit.orchestration.test_rrm_016_goal_directed_settlement import (
    _claim,
    _composition,
    _preparation,
)
from tests.unit.run_control.test_run_control import command
from tests.unit.subscriptions.test_mp15_coordinator import classify_type


async def _stuck_unit() -> tuple[Any, str, FamilyFailureTerminalization]:
    """A started run whose executor unit is admitted (reservation held) and never settles."""

    composition, run_id = await _composition()
    claim = await _claim(run_id)
    run = await composition.run_control.get_run(SCOPE, run_id)
    await composition.family.execute_iteration(
        _preparation(run_id, claim, "executor", run.version, 0)
    )
    service = FamilyFailureTerminalization(composition.run_control, orchestration_lifecycle_actor())
    return composition, run_id, service


async def _closed(composition: Any, run_id: str, service: FamilyFailureTerminalization) -> Any:
    for attempt in range(1, LIABILITY_TERMINALIZATION_ATTEMPT):
        with pytest.raises(FamilyFailureLiabilityPending, match="budget_not_settled"):
            await service.terminalize(_request(run_id), attempt=attempt)
    return await service.terminalize(_request(run_id), attempt=LIABILITY_TERMINALIZATION_ATTEMPT)


def _operator(run_id: str, version: int, command_id: str, action: object) -> LifecycleCommand:
    base = command(run_id, version, command_id, action)
    return base.model_copy(
        update={
            "actor": base.actor.model_copy(
                update={"permissions": base.actor.permissions | {"workflow_run.reconcile_unit"}}
            )
        }
    )


@pytest.mark.asyncio
async def test_an_unsettled_unit_closes_failed_with_named_reconcilable_liabilities() -> None:
    composition, run_id, service = await _stuck_unit()
    run_control = composition.run_control
    opened = await run_control.get_budget(SCOPE, run_id)
    (reservation_id,) = (key for key in opened.reservations if key != "baseline")
    unit_amounts = dict(opened.reservations[reservation_id])

    closed = await _closed(composition, run_id, service)
    budget = await run_control.get_budget(SCOPE, run_id)
    effects = await run_control.get_effects(SCOPE, run_id)
    liabilities = outstanding_liabilities(budget, effects)
    assert f"reservation:{reservation_id}" in liabilities
    assert budget.reservations[reservation_id] == unit_amounts  # never released for the unit

    assert closed.accepted and closed.reason_code == BUDGET_UNSETTLED_AT_FAILURE
    assert closed.terminal_outcome == RunOutcome.FAILED.value
    run = await run_control.get_run(SCOPE, run_id)
    assert run.phase == RunPhase.TERMINAL and run.terminal_outcome == RunOutcome.FAILED
    # Nothing was released on the unit's behalf: the reservation is the liability.
    # Each liability holds one inspectable operator_reconciliation wait on the closed run.
    assert {wait.condition_id for wait in run.active_waits} == {
        terminal_liability_condition_id(name) for name in liabilities
    }
    assert {wait.kind for wait in run.active_waits} == {"operator_reconciliation"}
    terminal = (await run_control.list_transitions(SCOPE, run_id))[-1]
    assert terminal.command_id.startswith(f"family-failure:{run_id}:epoch:1:terminalize-liability:")
    assert any(
        ref.startswith(f"{BUDGET_UNSETTLED_AT_FAILURE}:reservation:{reservation_id}:")
        for ref in terminal.evidence_refs
    )

    # B1: a late usage record of the stuck unit is refused and changes nothing.
    late = await run_control.execute(
        command(
            run_id,
            run.version,
            "w1-d26-late",
            RecordUsageAction(
                usage_id="late-unit-usage",
                actual_amounts={"tokens.total": 5},
                reservation_id=reservation_id,
            ),
        )
    )
    assert (late.status, late.reason_code) == (CommandStatus.REJECTED, "run_is_terminal")
    assert await run_control.get_run(SCOPE, run_id) == run
    assert (await run_control.get_budget(SCOPE, run_id)).reserved == budget.reserved

    # B2: the operator's audited decision closes the liability through the usage ledger.
    with pytest.raises(CommandRejected, match="reconcile_unit"):
        await run_control.execute(
            command(
                run_id,
                run.version,
                "w1-d26-reconcile-unauthorized",
                ReconcileTerminalLiabilityAction(
                    attestation="operator: provider console checked",
                    liability=f"reservation:{reservation_id}",
                    resolution="released",
                ),
            )
        )
    settled = await run_control.execute(
        _operator(
            run_id,
            run.version,
            "w1-d26-reconcile",
            ReconcileTerminalLiabilityAction(
                attestation="operator: provider console checked",
                liability=f"reservation:{reservation_id}",
                resolution="settled",
                actual_amounts={"tokens.total": 5},
            ),
        )
    )
    assert settled.status == CommandStatus.ACCEPTED, settled.reason
    after = await run_control.get_run(SCOPE, run_id)
    assert after.terminal_outcome == RunOutcome.FAILED  # the outcome never changes
    assert terminal_liability_condition_id(f"reservation:{reservation_id}") not in {
        wait.condition_id for wait in after.active_waits
    }
    reconciled = await run_control.get_budget(SCOPE, run_id)
    assert reservation_id not in reconciled.reservations
    assert reconciled.consumed.get("tokens.total", 0) >= 5
    repeat = await run_control.execute(
        _operator(
            run_id,
            after.version,
            "w1-d26-reconcile-again",
            ReconcileTerminalLiabilityAction(
                attestation="operator: provider console checked",
                liability=f"reservation:{reservation_id}",
                resolution="released",
            ),
        )
    )
    assert repeat.reason_code == "liability_not_pending"
    # Replayed (an activity retry after the close): already terminal, nothing written.
    again = await service.terminalize(
        _request(run_id), attempt=LIABILITY_TERMINALIZATION_ATTEMPT + 1
    )
    assert (again.accepted, again.reason_code) == (True, "already_terminal")


@pytest.mark.asyncio
async def test_a_progressing_settlement_is_not_closed_early() -> None:
    """S2: at the bound, without a refusal of the previous attempt at the same run version
    (the state moved, or nothing was tried), the run keeps waiting."""

    composition, run_id, service = await _stuck_unit()
    with pytest.raises(FamilyFailureLiabilityPending):
        await service.terminalize(_request(run_id), attempt=LIABILITY_TERMINALIZATION_ATTEMPT)
    run = await composition.run_control.get_run(SCOPE, run_id)
    assert run.phase == RunPhase.ACTIVE
    # The previous attempt now exists at this version: the next attempt escalates.
    closed = await service.terminalize(
        _request(run_id), attempt=LIABILITY_TERMINALIZATION_ATTEMPT + 1
    )
    assert closed.accepted and closed.reason_code == BUDGET_UNSETTLED_AT_FAILURE


@pytest.mark.asyncio
async def test_the_reducer_accepts_only_exactly_the_outstanding_liabilities() -> None:
    composition, run_id, _service = await _stuck_unit()
    run_control = composition.run_control
    run = await run_control.get_run(SCOPE, run_id)
    budget = await run_control.get_budget(SCOPE, run_id)
    effects = await run_control.get_effects(SCOPE, run_id)
    liabilities = outstanding_liabilities(budget, effects)
    base = _proposal(run, _request(run_id), 1)

    async def propose(command_id: str, **update: Any) -> Any:
        proposal = base.model_copy(update={"budget_settled": False, **update})
        return await run_control.execute(
            command(run_id, run.version, command_id, TerminalizeAction(proposal=proposal))
        )

    partial = await propose("w1-d26-partial", unsettled_liabilities=liabilities[:-1] or ("x",))
    assert (partial.status, partial.reason_code) == (CommandStatus.REJECTED, "liability_mismatch")
    unfailed = await propose(
        "w1-d26-unfailed", unsettled_liabilities=liabilities, execution_failure_refs=()
    )
    assert unfailed.reason_code == "liability_without_failure"
    assert (await run_control.get_run(SCOPE, run_id)).phase == RunPhase.ACTIVE
    exact = await propose("w1-d26-exact", unsettled_liabilities=liabilities)
    assert exact.status == CommandStatus.ACCEPTED
    assert exact.terminal_outcome == RunOutcome.FAILED  # never completed


def test_a_liability_close_is_an_actionable_blocked_notice() -> None:
    kind, actionable, _public = classify_type(
        "workflow_run.terminalize",
        terminal_outcome="failed",
        condition_kind="operator_reconciliation",
        condition_id=terminal_liability_condition_id("reservation:r1"),
    )
    assert (kind, actionable) == (NotificationKind.BLOCKED, True)
    # An ordinary close stays a terminal result.
    assert classify_type("workflow_run.terminalize", terminal_outcome="failed")[0] is (  # type: ignore[index]
        NotificationKind.TERMINAL_RESULT
    )


def test_resolutions_fit_their_liability_kind() -> None:
    with pytest.raises(ValueError, match="released or settled"):
        ReconcileTerminalLiabilityAction(
            attestation="checked", liability="reservation:r1", resolution="acknowledged"
        )
    with pytest.raises(ValueError, match="released or settled"):
        ReconcileTerminalLiabilityAction(
            attestation="checked", liability="effect:e1", resolution="released"
        )
    with pytest.raises(ValueError, match="only a settled"):
        ReconcileTerminalLiabilityAction(
            attestation="operator: provider console checked",
            liability="reservation:r1",
            resolution="released",
            actual_amounts={"tokens.total": 1},
        )
    assert ReconcileTerminalLiabilityAction(
        attestation="checked", liability="effect:e1", resolution="acknowledged"
    )


async def _closed_with(extra: list[object]) -> tuple[Any, str, str]:
    """A stuck unit with extra pre-close facts (usage, effects), then the liability close."""

    composition, run_id, service = await _stuck_unit()
    run_control = composition.run_control
    opened = await run_control.get_budget(SCOPE, run_id)
    (unit,) = (key for key in opened.reservations if key != "baseline")
    for index, make in enumerate(extra):
        run = await run_control.get_run(SCOPE, run_id)
        action = make(unit)  # type: ignore[operator]
        result = await run_control.execute(command(run_id, run.version, f"pre-{index}", action))
        assert result.status == CommandStatus.ACCEPTED, result.reason
    closed = await _closed(composition, run_id, service)
    assert closed.accepted
    return composition, run_id, unit


def _reconcile(liability: str, resolution: str, **extra: Any) -> ReconcileTerminalLiabilityAction:
    return ReconcileTerminalLiabilityAction(
        liability=liability,
        resolution=resolution,  # type: ignore[arg-type]
        attestation="operator: reconciled against the provider usage export",
        **extra,
    )


@pytest.mark.asyncio
async def test_a_clean_reservation_is_released_with_an_attestation() -> None:
    composition, run_id, unit = await _closed_with([])
    run_control = composition.run_control
    run = await run_control.get_run(SCOPE, run_id)
    released = await run_control.execute(
        _operator(run_id, run.version, "release", _reconcile(f"reservation:{unit}", "released"))
    )
    assert released.status == CommandStatus.ACCEPTED, released.reason
    assert unit not in (await run_control.get_budget(SCOPE, run_id)).reservations
    event_reason = (await run_control.list_transitions(SCOPE, run_id))[-1].command_id
    assert event_reason == "release"
    with pytest.raises(ValueError, match="attestation"):
        ReconcileTerminalLiabilityAction.model_validate(
            {"liability": f"reservation:{unit}", "resolution": "released", "attestation": ""}
        )


@pytest.mark.asyncio
async def test_recorded_unsettled_usage_is_never_released_silently() -> None:
    composition, run_id, unit = await _closed_with(
        [
            lambda unit: RecordUsageAction(
                usage_id="unit-usage-pending",
                actual_amounts={},
                reservation_id=unit,
                pending_external_amounts={"tokens.total": 2},
            )
        ]
    )
    run_control = composition.run_control
    run = await run_control.get_run(SCOPE, run_id)
    remaining = (await run_control.get_budget(SCOPE, run_id)).reservations.get(unit, {})
    refused = await run_control.execute(
        _operator(run_id, run.version, "release", _reconcile(f"reservation:{unit}", "released"))
    )
    assert refused.reason_code == "unsettled_usage_on_reservation"
    assert remaining  # the pending draw left the rest of the reservation
    over = {key: value + 1 for key, value in remaining.items()}
    overrun = await run_control.execute(
        _operator(
            run_id,
            run.version,
            "overrun",
            _reconcile(f"reservation:{unit}", "settled", actual_amounts=over),
        )
    )
    assert overrun.reason_code == "settlement_exceeds_reservation"
    settled = await run_control.execute(
        _operator(
            run_id,
            run.version,
            "settle",
            _reconcile(f"reservation:{unit}", "settled", actual_amounts=dict(remaining)),
        )
    )
    assert settled.status == CommandStatus.ACCEPTED, settled.reason
    # The pending settlement is acknowledged durably and no longer unexplained.
    run = await run_control.get_run(SCOPE, run_id)
    acknowledged = await run_control.execute(
        _operator(run_id, run.version, "ack", _reconcile("pending_settlement", "acknowledged"))
    )
    assert acknowledged.status == CommandStatus.ACCEPTED, acknowledged.reason
    run = await run_control.get_run(SCOPE, run_id)
    assert "pending_settlement" in run.acknowledged_liabilities
    budget = await run_control.get_budget(SCOPE, run_id)
    effects = await run_control.get_effects(SCOPE, run_id)
    assert "pending_settlement" in outstanding_liabilities(budget, effects)
    assert "pending_settlement" not in outstanding_liabilities(
        budget, effects, run.acknowledged_liabilities
    )
    transition = (await run_control.list_transitions(SCOPE, run_id))[-1]
    assert transition.reason and transition.command_id == "ack"


@pytest.mark.asyncio
async def test_an_unsettled_effect_is_acknowledged_durably() -> None:
    composition, run_id, _unit = await _closed_with(
        [
            lambda unit: ClaimEffectAction(
                effect_id="effect-native-write",
                effect_kind="native.write",
                operation_ref="goal-iteration/1/executor",
                provider_idempotency_key="native-1",
                reservation_id=unit,
            )
        ]
    )
    run_control = composition.run_control
    run = await run_control.get_run(SCOPE, run_id)
    assert terminal_liability_condition_id("effect:effect-native-write") in {
        wait.condition_id for wait in run.active_waits
    }
    acknowledged = await run_control.execute(
        _operator(
            run_id,
            run.version,
            "ack-effect",
            _reconcile("effect:effect-native-write", "acknowledged"),
        )
    )
    assert acknowledged.status == CommandStatus.ACCEPTED, acknowledged.reason
    run = await run_control.get_run(SCOPE, run_id)
    assert run.acknowledged_liabilities == ("effect:effect-native-write",)
    assert run.terminal_outcome == RunOutcome.FAILED
    budget = await run_control.get_budget(SCOPE, run_id)
    effects = await run_control.get_effects(SCOPE, run_id)
    assert "effect:effect-native-write" not in outstanding_liabilities(
        budget, effects, run.acknowledged_liabilities
    )
