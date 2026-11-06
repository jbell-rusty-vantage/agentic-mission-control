"""W1 D26 on the Temporal test server (time skipping): the root's bounded retries end terminal.

The `mc.mission_run.v1` root's family fails while one unit's reservation never settles. The
production activity body (`terminalize_failed_family` over `FamilyFailureTerminalization`, here
on the real in-memory reducer) waits through the first attempts (`budget_not_settled`, a
retryable failure under the root's retry policy) and, at `LIABILITY_TERMINALIZATION_ATTEMPT`,
closes the run `failed` with the reservation named as a terminal liability. No workflow
command changed: the root history replays.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

import pytest
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from mission_control.adapters.temporal.family_failure_activity import terminalize_failed_family
from mission_control.adapters.temporal.workflow_sandbox import coordinator_workflow_runner
from mission_control.adapters.temporal.workflows.mission_run import MissionRunWorkflow
from mission_control.application.execution.family_failure import FamilyFailureTerminalization
from mission_control.domain.policies.contracts import RunOutcome, terminal_liability_condition_id
from mission_control.domain.programs.family_failure import (
    BUDGET_UNSETTLED_AT_FAILURE,
    LIABILITY_TERMINALIZATION_ATTEMPT,
    FamilyFailureTerminalizationRequest,
    FamilyFailureTerminalizationResult,
)
from tests.fixtures.goal_directed_journaled import SCOPE
from tests.integration.temporal.test_w1_family_failure_root import QUEUE, FailingFamily, _root
from tests.unit.coordinator.test_w1_d26_liability_terminalization import _stuck_unit


@pytest.mark.asyncio
async def test_bounded_retries_close_a_run_whose_unit_never_settles() -> None:
    composition, run_id, service = await _stuck_unit()
    assert isinstance(service, FamilyFailureTerminalization)
    opened = await composition.run_control.get_budget(SCOPE, run_id)
    (unit,) = (key for key in opened.reservations if key != "baseline")
    unit_amounts = dict(opened.reservations[unit])
    attempts: list[int] = []

    @activity.defn(name="coordinator.terminalize_failed_family")
    async def terminalize(
        request: FamilyFailureTerminalizationRequest,
    ) -> FamilyFailureTerminalizationResult:
        attempts.append(activity.info().attempt)
        # The in-memory run control is admitted under the fixture tenant scope.
        return await terminalize_failed_family(service, replace(request, request_scope=SCOPE))

    try:
        env = await WorkflowEnvironment.start_time_skipping()
    except RuntimeError as error:
        pytest.skip(f"Temporal test server is unavailable: {error}")
    admitted = _root(run_id)
    async with env:
        async with Worker(
            env.client,
            task_queue=QUEUE,
            workflows=[MissionRunWorkflow, FailingFamily],
            workflow_runner=coordinator_workflow_runner(),
            activities=[terminalize],
        ):
            root = await env.client.start_workflow(
                MissionRunWorkflow.run, admitted, id=admitted.workflow_id, task_queue=QUEUE
            )
            with pytest.raises(WorkflowFailureError):
                await asyncio.wait_for(root.result(), timeout=120)
            history = await root.fetch_history()

    assert attempts == list(range(1, LIABILITY_TERMINALIZATION_ATTEMPT + 1))
    run = await composition.run_control.get_run(SCOPE, run_id)
    assert run.terminal_outcome == RunOutcome.FAILED
    # N2: the unit's reservation is preserved as the liability, held open for the operator.
    closed_budget = await composition.run_control.get_budget(SCOPE, run_id)
    assert closed_budget.reservations[unit] == unit_amounts
    assert terminal_liability_condition_id(f"reservation:{unit}") in {
        wait.condition_id for wait in run.active_waits
    }
    terminal = (await composition.run_control.list_transitions(SCOPE, run_id))[-1]
    assert any(ref.startswith(f"{BUDGET_UNSETTLED_AT_FAILURE}:") for ref in terminal.evidence_refs)
    replayer: Any = Replayer(
        workflows=[MissionRunWorkflow, FailingFamily], workflow_runner=coordinator_workflow_runner()
    )
    await replayer.replay_workflow(history)
