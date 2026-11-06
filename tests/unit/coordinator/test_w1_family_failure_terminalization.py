"""W1 D15: a run whose family workflow ended without terminalizing it is terminalized typed.

The real W1 runs left every run `running/active` after the GoalDirected family failed (and the
decode-looping ones `cancelling` forever). The Mission Control root now schedules
`coordinator.terminalize_failed_family` on its family queue before failing, and run control
(the real in-memory reducer here) ends the run `failed` with the typed cause, or `cancelled`
when a cancel was accepted, after releasing the unused baseline. A unit still settling keeps
the run open (retryable); history recorded before the patch fails at once, as it did.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from temporalio import activity
from temporalio.exceptions import (
    ActivityError,
    ApplicationError,
    CancelledError,
    ChildWorkflowError,
    RetryState,
    TerminatedError,
    TimeoutType,
)
from temporalio.exceptions import TimeoutError as TemporalTimeoutError

from mission_control.adapters.temporal.activities.goal_directed import GoalDirectedActivities
from mission_control.adapters.temporal.family_failure_activity import FAMILY_FAILURE_ACTIVITY
from mission_control.adapters.temporal.orchestration_activities import StageGraphActivities
from mission_control.adapters.temporal.registration.activities import coordinator_activities
from mission_control.adapters.temporal.workflows import mission_run
from mission_control.adapters.temporal.workflows.belllabs_run import BellLabsRunWorkflow
from mission_control.application.execution.family_failure import (
    FamilyFailureLiabilityPending,
    FamilyFailureTerminalization,
)
from mission_control.application.programs.service import orchestration_lifecycle_actor
from mission_control.domain.policies.contracts import (
    CancelAction,
    CommandStatus,
    RecordUsageAction,
    RunOutcome,
    RunPhase,
)
from mission_control.domain.programs.family_failure import (
    FamilyFailureTerminalizationRequest,
    FamilyFailureTerminalizationResult,
)
from tests.fixtures.goal_directed_journaled import SCOPE, goal_start_action
from tests.unit.coordinator.test_root_result_materialization import root
from tests.unit.orchestration.test_rrm_016_goal_directed_settlement import (
    _claim,
    _composition,
    _preparation,
)
from tests.unit.run_control.test_run_control import command

NOW = datetime(2026, 10, 28, tzinfo=UTC)


def _request(run_id: str, *, epoch: int = 1, cause: str = "application_error:x") -> Any:
    return FamilyFailureTerminalizationRequest(
        request_scope=SCOPE,
        run_id=run_id,
        execution_epoch=epoch,
        family="GoalDirected",
        family_workflow_id=f"family/{run_id}/1",
        cause=cause,
        cause_digest="sha256:" + "1" * 64,
        occurred_at=NOW,
    )


async def _started_run() -> tuple[Any, str]:
    composition, run_id = await _composition()
    return composition, run_id


def _service(composition: Any) -> FamilyFailureTerminalization:
    return FamilyFailureTerminalization(composition.run_control, orchestration_lifecycle_actor())


@pytest.mark.asyncio
async def test_an_active_run_whose_family_failed_ends_failed_with_the_typed_cause() -> None:
    composition, run_id = await _started_run()
    run_control = composition.run_control
    before = await run_control.get_run(SCOPE, run_id)
    assert before.phase == RunPhase.ACTIVE

    cause = "application_error:goal_operation_unreported"
    result = await _service(composition).terminalize(_request(run_id, cause=cause))

    assert result == FamilyFailureTerminalizationResult(
        accepted=True,
        resulting_run_version=result.resulting_run_version,
        terminal_outcome=RunOutcome.FAILED.value,
    )
    run = await run_control.get_run(SCOPE, run_id)
    assert run.phase == RunPhase.TERMINAL and run.terminal_outcome == RunOutcome.FAILED
    budget = await run_control.get_budget(SCOPE, run_id)
    assert not any(budget.reserved.values())  # the unused baseline was released
    terminal = (await run_control.list_transitions(SCOPE, run_id))[-1]
    assert f"family-failure-cause:{cause}" in terminal.evidence_refs
    assert terminal.command_id.startswith(f"family-failure:{run_id}:epoch:1:terminalize:")

    # Retried (an activity retry, a replayed root): already terminal, nothing written.
    written = len(await run_control.list_transitions(SCOPE, run_id))
    again = await _service(composition).terminalize(_request(run_id), attempt=2)
    assert (again.accepted, again.reason_code) == (True, "already_terminal")
    assert again.terminal_outcome == RunOutcome.FAILED.value
    assert len(await run_control.list_transitions(SCOPE, run_id)) == written


@pytest.mark.asyncio
async def test_a_cancelling_run_whose_family_never_finished_the_saga_ends_cancelled() -> None:
    composition, run_id = await _started_run()
    run_control = composition.run_control
    run = await run_control.get_run(SCOPE, run_id)
    cancelled = await run_control.execute(
        command(run_id, run.version, "w1-d15-cancel", CancelAction(urgency="normal"))
    )
    assert cancelled.status == CommandStatus.ACCEPTED
    assert (await run_control.get_run(SCOPE, run_id)).phase == RunPhase.CANCELLING

    result = await _service(composition).terminalize(_request(run_id, cause="terminated"))

    assert result.accepted and result.terminal_outcome == RunOutcome.CANCELLED.value
    run = await run_control.get_run(SCOPE, run_id)
    assert run.terminal_outcome == RunOutcome.CANCELLED


@pytest.mark.asyncio
async def test_a_late_operation_settlement_against_the_terminal_run_changes_nothing() -> None:
    composition, run_id = await _started_run()
    run_control = composition.run_control
    await _service(composition).terminalize(_request(run_id))
    terminal = await run_control.get_run(SCOPE, run_id)
    assert terminal.phase == RunPhase.TERMINAL
    before = await run_control.list_transitions(SCOPE, run_id)
    budget_before = await run_control.get_budget(SCOPE, run_id)
    late = await run_control.execute(
        command(
            run_id,
            terminal.version,
            "w1-d15-late-settlement",
            RecordUsageAction(
                usage_id="goal-usage:late-unit",
                actual_amounts={"tokens.total": 5},
                reservation_id="late-unit",
            ),
        )
    )
    assert late.status != CommandStatus.ACCEPTED
    assert (await run_control.get_run(SCOPE, run_id)) == terminal
    assert await run_control.list_transitions(SCOPE, run_id) == before
    assert await run_control.get_budget(SCOPE, run_id) == budget_before
    # The family's late reconciliation reads the closed run and records nothing either.
    again = await _service(composition).terminalize(_request(run_id), attempt=3)
    assert again.reason_code == "already_terminal"


@pytest.mark.asyncio
async def test_a_unit_still_settling_keeps_the_run_open_and_retries() -> None:
    composition, run_id = await _started_run()
    claim = await _claim(run_id)
    run = await composition.run_control.get_run(SCOPE, run_id)
    # The executor is admitted (its reservation is held) but never settles.
    await composition.family.execute_iteration(
        _preparation(run_id, claim, "executor", run.version, 0)
    )
    with pytest.raises(FamilyFailureLiabilityPending) as pending:
        await _service(composition).terminalize(_request(run_id))
    assert pending.value.reason_code == "budget_not_settled"
    assert (await composition.run_control.get_run(SCOPE, run_id)).phase == RunPhase.ACTIVE


@pytest.mark.asyncio
async def test_another_execution_epoch_is_refused_without_a_write() -> None:
    composition, run_id = await _started_run()
    before = await composition.run_control.list_transitions(SCOPE, run_id)
    run = await composition.run_control.get_run(SCOPE, run_id)
    assert run.execution_target == goal_start_action(run_id).execution_target
    result = await _service(composition).terminalize(_request(run_id, epoch=2))
    assert (result.accepted, result.reason_code) == (False, "stale_execution_epoch")
    assert await composition.run_control.list_transitions(SCOPE, run_id) == before


def _child_error(cause: BaseException) -> ChildWorkflowError:
    error = ChildWorkflowError(
        "Child Workflow execution failed",
        namespace="default",
        workflow_id="family",
        run_id="r",
        workflow_type="belllabs.goal-directed",
        initiated_event_id=1,
        started_event_id=2,
        retry_state=RetryState.NON_RETRYABLE_FAILURE,
    )
    error.__cause__ = cause
    return error


def _activity_error(cause: BaseException) -> ActivityError:
    error = ActivityError(
        "Activity task failed",
        scheduled_event_id=1,
        started_event_id=2,
        identity="w",
        activity_type="goaldirected.prepare_executor",
        activity_id="1",
        retry_state=RetryState.NON_RETRYABLE_FAILURE,
    )
    error.__cause__ = cause
    return error


@pytest.mark.parametrize(
    ("cause", "code"),
    [
        (
            ApplicationError("x", type="goal_operation_unreported"),
            "application_error:goal_operation_unreported",
        ),
        (
            ApplicationError("pydantic said", type="ValidationError"),
            "application_error:ValidationError",
        ),
        (
            _activity_error(ApplicationError("x", type="goal_dispatch_invalid")),
            "activity_error:goal_dispatch_invalid",
        ),
        (TerminatedError("operator"), "terminated"),
        (
            TemporalTimeoutError("t", type=TimeoutType.START_TO_CLOSE, last_heartbeat_details=[]),
            "timed_out",
        ),
        (CancelledError("c"), "cancelled"),
    ],
)
def test_the_family_end_is_named_by_a_typed_cause(cause: BaseException, code: str) -> None:
    named, _message = mission_run.family_failure_cause(_child_error(cause))
    assert named == code


def test_w1_d39_a_failed_operation_child_is_named_by_its_innermost_typed_cause() -> None:
    """W1 D39: the family failed because its operation child failed on an exhausted
    `operation.execute` refused behind a claim lease. One level of unwrapping named it
    `unknown`; the root now names the innermost typed failure (on patched histories)."""

    operation = _child_error(
        _activity_error(ApplicationError("held", type="operation_execution_in_progress"))
    )
    family = _child_error(operation)
    assert mission_run.family_failure_cause(family, nested=False)[0] == "unknown"
    named, message = mission_run.family_failure_cause(family)
    assert named == "activity_error:operation_execution_in_progress"
    assert message == "held"


def _patch_root(monkeypatch: pytest.MonkeyPatch, admitted: Any, *, patched: bool) -> None:
    monkeypatch.setattr(
        mission_run.workflow, "info", lambda: SimpleNamespace(workflow_id=admitted.workflow_id)
    )
    monkeypatch.setattr(mission_run.workflow, "patched", lambda _: patched)
    monkeypatch.setattr(mission_run.workflow, "now", lambda: NOW)
    monkeypatch.setattr(mission_run.workflow, "logger", SimpleNamespace(warning=lambda *a: None))


@pytest.mark.parametrize("family", ["StageGraph", "GoalDirected"])
@pytest.mark.asyncio
async def test_the_root_terminalizes_the_run_then_fails_with_the_family_error(
    monkeypatch: pytest.MonkeyPatch, family: str
) -> None:
    admitted = root(family)
    failure = _child_error(ApplicationError("boom", type="goal_operation_unreported"))
    calls: list[tuple[str, Any, dict[str, Any]]] = []

    async def run_activity(name: str, request: Any, **options: Any) -> Any:
        calls.append((name, request, options))
        return FamilyFailureTerminalizationResult(accepted=True, resulting_run_version=9)

    monkeypatch.setattr(BellLabsRunWorkflow, "run", AsyncMock(side_effect=failure))
    _patch_root(monkeypatch, admitted, patched=True)
    monkeypatch.setattr(mission_run.workflow, "start_activity", run_activity)
    with pytest.raises(ChildWorkflowError) as raised:
        await mission_run.MissionRunWorkflow().run(admitted)
    assert raised.value is failure
    ((name, request, options),) = calls
    assert name == FAMILY_FAILURE_ACTIVITY
    assert options["task_queue"] == admitted.family_task_queue
    assert "NotFoundError" in options["retry_policy"].non_retryable_error_types
    assert request == replace(
        request,
        request_scope=admitted.request_scope,
        run_id=admitted.run_id,
        execution_epoch=1,
        family=family,
        family_workflow_id=admitted.family_workflow_id,
        cause="application_error:goal_operation_unreported",
        occurred_at=NOW,
    )
    assert "boom" not in repr(request)  # the message is digested, never carried


@pytest.mark.asyncio
async def test_an_exhausted_terminalization_never_masks_the_family_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admitted = root("GoalDirected")
    failure = _child_error(TerminatedError("operator"))
    exhausted = _activity_error(RuntimeError("budget_not_settled"))
    monkeypatch.setattr(BellLabsRunWorkflow, "run", AsyncMock(side_effect=failure))
    _patch_root(monkeypatch, admitted, patched=True)
    exhausted_activity = AsyncMock(side_effect=exhausted)
    monkeypatch.setattr(mission_run.workflow, "start_activity", exhausted_activity)
    with pytest.raises(ChildWorkflowError) as raised:
        await mission_run.MissionRunWorkflow().run(admitted)
    assert raised.value is failure


@pytest.mark.asyncio
async def test_pre_patch_root_history_fails_without_the_new_activity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admitted = root("GoalDirected")
    failure = _child_error(ApplicationError("boom"))
    start_activity = AsyncMock()
    monkeypatch.setattr(BellLabsRunWorkflow, "run", AsyncMock(side_effect=failure))
    _patch_root(monkeypatch, admitted, patched=False)
    monkeypatch.setattr(mission_run.workflow, "start_activity", start_activity)
    with pytest.raises(ChildWorkflowError):
        await mission_run.MissionRunWorkflow().run(admitted)
    start_activity.assert_not_called()


@pytest.mark.parametrize(
    ("family", "cls"),
    [("StageGraph", StageGraphActivities), ("GoalDirected", GoalDirectedActivities)],
)
def test_both_family_queues_register_the_terminalization(family: str, cls: type) -> None:
    names = {
        activity._Definition.must_from_callable(item).name
        for item in coordinator_activities(family, cls)
    }
    assert FAMILY_FAILURE_ACTIVITY in names
