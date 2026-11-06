"""Use real run-control reductions for cancellation before any root starts."""

import pytest

from mission_control.application.execution.unstarted_cancellation import UnstartedRunCancellation
from mission_control.domain.policies.contracts import (
    ActorContext,
    CancelAction,
    ClaimEffectAction,
    CommandStatus,
    ExecutionTarget,
    RecordUsageAction,
    ReserveBudgetAction,
    RunPhase,
    StartAction,
)
from mission_control.domain.policies.errors import CommandRejected
from tests.unit.run_control.test_run_control import actor, command, request, service


async def admitted():
    control, repository = service()
    result = await control.admit(request())
    assert result.run_id
    return control, repository, result.run_id


async def execute(control, run_id, name, action):
    run = await control.get_run("tenant-1", run_id)
    result = await control.execute(command(run_id, run.version, name, action))
    assert result.status == CommandStatus.ACCEPTED, result
    return result


async def test_unused_baseline_releases_and_cancelled_closes_once_without_family():
    control, _, run_id = await admitted()
    await execute(control, run_id, "cancel", CancelAction())
    closure = UnstartedRunCancellation(control, actor())
    assert await closure.close("tenant-1", run_id) == "closed"
    run = await control.get_run("tenant-1", run_id)
    assert run.phase == RunPhase.TERMINAL and run.terminal_outcome == "cancelled"
    assert run.execution_target is None
    budget = await control.get_budget("tenant-1", run_id)
    assert not any(budget.reserved.values()) and not any(budget.consumed.values())
    transitions = await control.list_transitions("tenant-1", run_id)
    assert any("release-baseline" in row.command_id for row in transitions)
    assert transitions[-1].evidence_refs == (f"unstarted-run:{run_id}",)
    assert await closure.close("tenant-1", run_id) == "closed"
    assert await control.list_transitions("tenant-1", run_id) == transitions


@pytest.mark.parametrize("unsafe", ["reservation", "consumption"])
async def test_unstarted_cancellation_never_releases_execution_budget(unsafe):
    control, _, run_id = await admitted()
    action = (
        ReserveBudgetAction(reservation_id="operation", amounts={"tokens.total": 1})
        if unsafe == "reservation"
        else RecordUsageAction(
            usage_id="actual",
            actual_amounts={"tokens.total": 1},
            reservation_id="baseline",
            release_amounts={"tokens.total": 1},
        )
    )
    await execute(control, run_id, "liability", action)
    await execute(control, run_id, "cancel", CancelAction())
    budget = await control.get_budget("tenant-1", run_id)
    with pytest.raises(ValueError, match="liabilities"):
        await UnstartedRunCancellation(control, actor()).close("tenant-1", run_id)
    assert await control.get_budget("tenant-1", run_id) == budget
    assert (await control.get_run("tenant-1", run_id)).phase == RunPhase.CANCELLING


async def test_historical_targetless_started_run_retains_its_cancellation_owner():
    control, _, run_id = await admitted()
    await execute(control, run_id, "start", StartAction())
    await execute(control, run_id, "cancel", CancelAction())
    budget = await control.get_budget("tenant-1", run_id)
    assert (
        await UnstartedRunCancellation(control, actor()).close("tenant-1", run_id)
        == "execution_owned"
    )
    assert await control.get_budget("tenant-1", run_id) == budget


async def test_chain_cancel_permission_cannot_release_or_terminalize():
    control, _, run_id = await admitted()
    await execute(control, run_id, "cancel", CancelAction())
    limited = ActorContext(actor_id="chain", permissions=frozenset({"workflow_run.cancel"}))
    with pytest.raises(CommandRejected, match="permission"):
        await UnstartedRunCancellation(control, limited).close("tenant-1", run_id)
    assert (await control.get_budget("tenant-1", run_id)).reserved["tokens.total"] == 20


async def test_concurrent_governed_baseline_release_retries_from_actual_facts(monkeypatch):
    control, _, run_id = await admitted()
    await execute(control, run_id, "cancel", CancelAction())
    ordinary = control.execute
    raced = False

    async def race(cmd, **kwargs):
        nonlocal raced
        if not raced and "release-baseline" in cmd.command_id:
            raced = True
            await ordinary(
                command(
                    run_id,
                    cmd.expected_run_version,
                    "concurrent-release",
                    RecordUsageAction(
                        usage_id="concurrent",
                        actual_amounts={},
                        reservation_id="baseline",
                        release_amounts={"tokens.total": 20},
                    ),
                )
            )
        return await ordinary(cmd, **kwargs)

    monkeypatch.setattr(control, "execute", race)
    assert await UnstartedRunCancellation(control, actor()).close("tenant-1", run_id) == "closed"
    assert raced and not any((await control.get_budget("tenant-1", run_id)).consumed.values())


async def test_effect_liability_cannot_be_closed_or_release_its_baseline():
    control, _, run_id = await admitted()
    await execute(
        control,
        run_id,
        "effect",
        ClaimEffectAction(
            effect_id="effect-one",
            effect_kind="external",
            operation_ref="operation",
            provider_idempotency_key="effect-one",
            reservation_id="baseline",
        ),
    )
    await execute(control, run_id, "cancel", CancelAction())
    with pytest.raises(ValueError, match="liabilities"):
        await UnstartedRunCancellation(control, actor()).close("tenant-1", run_id)
    assert (await control.get_budget("tenant-1", run_id)).reserved["tokens.total"] == 20


async def test_concurrent_root_binding_defers_to_existing_cancellation_saga(monkeypatch):
    control, _, run_id = await admitted()
    await execute(control, run_id, "cancel", CancelAction())
    ordinary = control.execute
    attempts = []

    async def race(cmd, **kwargs):
        if "terminalize" in cmd.command_id and not attempts:
            attempts.append(
                await ordinary(
                    command(
                        run_id,
                        cmd.expected_run_version,
                        "late-root-start",
                        StartAction(
                            execution_target=ExecutionTarget(
                                family="GoalDirected",
                                family_workflow_id="actual-family",
                                root_workflow_id="actual-root",
                            )
                        ),
                    )
                )
            )
        return await ordinary(cmd, **kwargs)

    monkeypatch.setattr(control, "execute", race)
    assert (
        await UnstartedRunCancellation(control, actor()).close("tenant-1", run_id)
        == "execution_owned"
    )
    assert attempts and all(item.status == CommandStatus.ACCEPTED for item in attempts)
    run = await control.get_run("tenant-1", run_id)
    assert run.execution_target is not None and run.phase == RunPhase.CANCELLING


async def test_root_submitted_before_closure_cannot_start_after_terminal_cancel():
    control, _, run_id = await admitted()
    await execute(control, run_id, "cancel", CancelAction())
    await UnstartedRunCancellation(control, actor()).close("tenant-1", run_id)
    run = await control.get_run("tenant-1", run_id)
    result = await control.execute(command(run_id, run.version, "late-start", StartAction()))
    assert result.status == CommandStatus.REJECTED
    assert (await control.get_run("tenant-1", run_id)).terminal_outcome == "cancelled"
