"""W1 D15: a root whose family failed terminalizes the run, on the time-skipping server.

The root is the production `MissionRunWorkflow`; the families are fixtures under the production
family workflow names that fail at once with a typed application error. The root schedules
`coordinator.terminalize_failed_family` on the family queue with the typed cause (the failure
message only digested), then fails with the family's own error even when the terminalization
is refused for good; a root history recorded before `w1-d15-root-terminalizes-failed-family`
replays on the production root without the new activity.

Replaces the `temporalio.workflow`-patching root tests of
tests/unit/coordinator/test_w1_family_failure_terminalization.py (OVE-238 G4). The real-server
cases (a terminated family, an undecodable result, a cancel during terminalization) are in
test_w1_family_failure_root.py.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from temporalio import activity, workflow
from temporalio.client import WorkflowFailureError, WorkflowHistory
from temporalio.exceptions import ApplicationError, ChildWorkflowError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from mission_control.adapters.temporal.family_failure_activity import FAMILY_FAILURE_ACTIVITY
from mission_control.adapters.temporal.workflow_sandbox import coordinator_workflow_runner
from mission_control.adapters.temporal.workflows.mission_run import (
    FAMILY_FAILURE_PATCH,
    MissionRunWorkflow,
)
from mission_control.domain.programs.family_failure import (
    FamilyFailureTerminalizationRequest,
    FamilyFailureTerminalizationResult,
)
from tests.support.integration.temporal.w1_family_failure_root import (
    QUEUE,
    PrePatchMissionRun,
    admitted_root,
)
from tests.support.temporal import patch_ids, scheduled_activity_inputs


def _fail() -> None:
    raise ApplicationError(
        "boom: a secret-bearing message", type="goal_operation_unreported", non_retryable=True
    )


@workflow.defn(name="belllabs.stagegraph", sandboxed=False)
class FailingStageGraph:
    @workflow.run
    async def run(self, family_input: dict[str, Any]) -> None:
        _fail()


@workflow.defn(name="belllabs.goal-directed", sandboxed=False)
class FailingGoalDirected:
    @workflow.run
    async def run(self, family_input: dict[str, Any]) -> None:
        _fail()


class _Terminalizer:
    def __init__(self, *, refuse: bool = False) -> None:
        self.refuse = refuse
        self.requests: list[FamilyFailureTerminalizationRequest] = []

    @activity.defn(name=FAMILY_FAILURE_ACTIVITY)
    async def terminalize(
        self, request: FamilyFailureTerminalizationRequest
    ) -> FamilyFailureTerminalizationResult:
        self.requests.append(request)
        if self.refuse:
            # Exhausted for good (the run is unknown to run control): never retried.
            raise ApplicationError("run not found", type="NotFoundError", non_retryable=True)
        return FamilyFailureTerminalizationResult(accepted=True, resulting_run_version=9)


async def _run(
    env: WorkflowEnvironment, root: type, family: str, run_id: str, terminalizer: _Terminalizer
) -> tuple[WorkflowFailureError, WorkflowHistory]:
    admitted = admitted_root(family, run_id)
    async with Worker(
        env.client,
        task_queue=QUEUE,
        workflows=[root, FailingStageGraph, FailingGoalDirected],
        workflow_runner=coordinator_workflow_runner(),
        activities=[terminalizer.terminalize],
    ):
        handle = await env.client.start_workflow(
            root.run, admitted, id=admitted.workflow_id, task_queue=QUEUE
        )
        with pytest.raises(WorkflowFailureError) as failed:
            await asyncio.wait_for(handle.result(), timeout=60)
        history = await handle.fetch_history()
    return failed.value, history


async def _replay(history: WorkflowHistory) -> None:
    await Replayer(
        workflows=[MissionRunWorkflow, FailingStageGraph, FailingGoalDirected],
        workflow_runner=coordinator_workflow_runner(),
    ).replay_workflow(history)


@pytest.mark.asyncio
@pytest.mark.parametrize("family", ["StageGraph", "GoalDirected"])
async def test_the_root_terminalizes_the_run_then_fails_with_the_family_error(
    workflow_env: WorkflowEnvironment, family: str
) -> None:
    terminalizer = _Terminalizer()
    run_id = f"run-w1-terminalize-{family}"
    failed, history = await _run(workflow_env, MissionRunWorkflow, family, run_id, terminalizer)

    assert isinstance(failed.cause, ChildWorkflowError)
    assert isinstance(failed.cause.cause, ApplicationError)
    assert failed.cause.cause.type == "goal_operation_unreported"
    admitted = admitted_root(family, run_id)
    (request,) = terminalizer.requests
    assert request.request_scope == admitted.request_scope
    assert request.run_id == run_id and request.execution_epoch == 1
    assert request.family == family
    assert request.family_workflow_id == admitted.family_workflow_id
    assert request.cause == "application_error:goal_operation_unreported"
    assert "boom" not in repr(request)  # the message is digested, never carried
    (scheduled,) = scheduled_activity_inputs(history, FAMILY_FAILURE_ACTIVITY)
    assert scheduled["cause"] == request.cause
    event = next(
        item.activity_task_scheduled_event_attributes
        for item in history.events
        if item.HasField("activity_task_scheduled_event_attributes")
    )
    assert event.task_queue.name == admitted.family_task_queue
    assert "NotFoundError" in event.retry_policy.non_retryable_error_types
    assert FAMILY_FAILURE_PATCH in patch_ids(history)
    await _replay(history)


@pytest.mark.asyncio
async def test_an_exhausted_terminalization_never_masks_the_family_failure(
    workflow_env: WorkflowEnvironment,
) -> None:
    terminalizer = _Terminalizer(refuse=True)
    failed, history = await _run(
        workflow_env, MissionRunWorkflow, "GoalDirected", "run-w1-exhausted", terminalizer
    )

    assert len(terminalizer.requests) == 1
    assert isinstance(failed.cause, ChildWorkflowError), "the family's error, not the activity's"
    assert isinstance(failed.cause.cause, ApplicationError)
    assert failed.cause.cause.type == "goal_operation_unreported"
    await _replay(history)


@pytest.mark.asyncio
async def test_pre_patch_root_history_fails_without_the_new_activity(
    workflow_env: WorkflowEnvironment,
) -> None:
    terminalizer = _Terminalizer()
    failed, history = await _run(
        workflow_env, PrePatchMissionRun, "GoalDirected", "run-w1-pre-patch", terminalizer
    )

    assert isinstance(failed.cause, ChildWorkflowError)
    assert FAMILY_FAILURE_PATCH not in patch_ids(history), "recorded before the patch"
    assert terminalizer.requests == []
    # The production root replays it: no terminalization is scheduled on replay.
    await _replay(history)
