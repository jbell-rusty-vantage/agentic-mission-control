"""W1 D10/D15 and stuck cancels on a real Temporal server (`WorkflowEnvironment.start_local`).

* An operator who terminates a stuck family workflow (the bounded recovery for a family that
  can make no progress) gets the run terminalized: the `mc.mission_run.v1` root observes the
  termination and schedules `coordinator.terminalize_failed_family` with cause `terminated`.
* A family whose activity result fails its contract when decoded (the D10 shape) fails at once
  with a typed `ValidationError` instead of failing workflow tasks forever, and the root
  terminalizes the run with that cause.

The families are stand-ins registered under the production family workflow names; the root,
its patch and the payload decode are real. Both new histories replay.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, replace
from datetime import timedelta
from typing import Any

import pytest
from pydantic import ValidationError
from temporalio import activity, workflow
from temporalio.client import WorkflowFailureError
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError, CancelledError, ChildWorkflowError
from temporalio.worker import Replayer, Worker

from mission_control.adapters.temporal.workflow_sandbox import coordinator_workflow_runner
from mission_control.adapters.temporal.workflows.mission_run import (
    FAMILY_FAILURE_PATCH,
    MissionRunWorkflow,
)
from mission_control.adapters.temporal.workflows.payload_contracts import decode_contract
from mission_control.domain.programs.contracts import BellLabsRunInput, StageGraphRunInput
from mission_control.domain.programs.family_failure import (
    FamilyFailureTerminalizationRequest,
    FamilyFailureTerminalizationResult,
)
from mission_control.domain.programs.goal_directed_runtime import GoalOperationDispatch
from tests.fixtures.temporal_history import patch_ids
from tests.integration.temporal.test_rrm_005_search_attributes import _start_local
from tests.integration.temporal.test_wp_bp_010_temporal import _blueprint
from tests.integration.temporal.test_wp_bp_010_temporal import _run_input as stage_run_input
from tests.unit.coordinator.test_root_result_materialization import SCOPE

QUEUE = "w1-family-failure-root"


@workflow.defn(name="belllabs.stagegraph", sandboxed=False)
class StuckFamily:
    """A family that can make no progress (as a decode-looping one cannot)."""

    @workflow.run
    async def run(self, run_input: StageGraphRunInput) -> None:
        await workflow.wait_condition(lambda: False)


@workflow.defn(name="belllabs.stagegraph", sandboxed=False)
class UndecodableResultFamily:
    """Decodes an activity result that fails its contract through the production decode site
    (`payload_contracts.decode_contract`, as the GoalDirected family's prepare does)."""

    @workflow.run
    async def run(self, run_input: StageGraphRunInput) -> None:
        raw = await workflow.execute_activity(
            "w1.undecodable_dispatch",
            result_type=dict,
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
        decode_contract(GoalOperationDispatch, raw, site="w1.undecodable_dispatch")


@workflow.defn(name="belllabs.stagegraph", sandboxed=False)
class FailingFamily:
    """Fails at once with a typed application error."""

    @workflow.run
    async def run(self, run_input: StageGraphRunInput) -> None:
        raise ApplicationError("unit failed", type="goal_operation_unreported", non_retryable=True)


class Recorder:
    def __init__(self, *, hold: bool = False) -> None:
        self.requests: list[FamilyFailureTerminalizationRequest] = []
        self.completed: list[str] = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        if not hold:
            self.release.set()

    @activity.defn(name="coordinator.terminalize_failed_family")
    async def terminalize(
        self, request: FamilyFailureTerminalizationRequest
    ) -> FamilyFailureTerminalizationResult:
        self.requests.append(request)
        self.started.set()
        await self.release.wait()
        self.completed.append(request.run_id)
        return FamilyFailureTerminalizationResult(
            accepted=True, resulting_run_version=7, terminal_outcome="failed"
        )

    @activity.defn(name="w1.undecodable_dispatch")
    async def undecodable(self) -> dict[str, Any]:
        # A run-control field over its 8192-character bound: refused only when decoded.
        return {
            "schema_version": "belllabs.goal-operation-dispatch.v1",
            "operation_binding_ref": "b" * 8_193,
        }


def _root(run_id: str) -> BellLabsRunInput:
    family_input = asdict(
        replace(stage_run_input(_blueprint()), run_id=run_id, request_scope=SCOPE)
    )
    return BellLabsRunInput(
        schema_version="mc.mission_run.v1",
        run_id=run_id,
        request_scope=SCOPE,
        effective_configuration_digest=family_input["effective_configuration_digest"],
        workflow_type_digest=family_input["workflow_type_digest"],
        family="StageGraph",
        family_task_queue=QUEUE,
        family_input=family_input,
    )


async def _run(
    family: type, run_id: str, *, terminate: bool, cancel_root: bool = False
) -> tuple[Recorder, list[Any]]:
    recorder = Recorder(hold=cancel_root)
    admitted = _root(run_id)
    env = await _start_local()
    async with env:
        client = env.client
        async with Worker(
            client,
            task_queue=QUEUE,
            workflows=[MissionRunWorkflow, family],
            workflow_runner=coordinator_workflow_runner(),
            activities=[recorder.terminalize, recorder.undecodable],
        ):
            root = await client.start_workflow(
                MissionRunWorkflow.run, admitted, id=admitted.workflow_id, task_queue=QUEUE
            )
            family_handle = client.get_workflow_handle(admitted.family_workflow_id)
            if terminate:
                async with asyncio.timeout(30):
                    while True:
                        try:
                            await family_handle.describe()
                            break
                        except Exception:
                            await asyncio.sleep(0.2)
                await family_handle.terminate(reason="w1 operator: family cannot progress")
            if cancel_root:
                # The root is cancelled while its terminalization activity runs.
                await asyncio.wait_for(recorder.started.wait(), timeout=30)
                await root.cancel()
                await asyncio.sleep(1)
                assert recorder.completed == []
                recorder.release.set()
            with pytest.raises(WorkflowFailureError) as failed:
                await asyncio.wait_for(root.result(), timeout=60)
            expected = CancelledError if cancel_root else ChildWorkflowError
            assert isinstance(failed.value.cause, expected)
            histories = [await root.fetch_history(), await family_handle.fetch_history()]
    return recorder, histories


async def _replay(family: type, histories: list[Any]) -> None:
    replayer = Replayer(
        workflows=[MissionRunWorkflow, family], workflow_runner=coordinator_workflow_runner()
    )
    for history in histories:
        await replayer.replay_workflow(history)


@pytest.mark.asyncio
async def test_terminating_a_stuck_family_terminalizes_the_run_with_the_typed_cause() -> None:
    recorder, histories = await _run(StuckFamily, "run-w1-terminated", terminate=True)
    (request,) = recorder.requests
    assert (request.run_id, request.request_scope) == ("run-w1-terminated", SCOPE)
    assert request.cause == "terminated"
    assert request.family == "StageGraph" and request.execution_epoch == 1
    assert request.family_workflow_id.endswith("/family/1")
    assert FAMILY_FAILURE_PATCH in patch_ids(histories[0])
    await _replay(StuckFamily, histories)


@pytest.mark.asyncio
async def test_an_undecodable_activity_result_fails_the_family_once_not_forever() -> None:
    recorder, histories = await _run(UndecodableResultFamily, "run-w1-undecodable", terminate=False)
    (request,) = recorder.requests
    assert request.cause == "application_error:payload_bound_violation"
    family_events = [event.WhichOneof("attributes") for event in histories[1].events]
    assert "workflow_execution_failed_event_attributes" in family_events
    # The decode failed the workflow, not its tasks: no workflow task failure was recorded.
    assert "workflow_task_failed_event_attributes" not in family_events
    await _replay(UndecodableResultFamily, histories)


@pytest.mark.asyncio
async def test_a_root_cancelled_while_terminalizing_still_finishes_the_terminalization() -> None:
    recorder, histories = await _run(
        FailingFamily, "run-w1-cancel-during", terminate=False, cancel_root=True
    )
    (request,) = recorder.requests
    assert request.cause == "application_error:goal_operation_unreported"
    # The shielded activity completed after the cancel; the root then ended cancelled.
    assert recorder.completed == ["run-w1-cancel-during"]
    root_events = [event.WhichOneof("attributes") for event in histories[0].events]
    assert "activity_task_completed_event_attributes" in root_events
    assert "workflow_execution_canceled_event_attributes" in root_events
    await _replay(FailingFamily, histories)


def test_the_stand_in_failure_matches_the_production_decode() -> None:
    with pytest.raises(ValidationError, match="8192"):
        GoalOperationDispatch.model_validate(
            {
                "schema_version": "belllabs.goal-operation-dispatch.v1",
                "operation_binding_ref": "b" * 8_193,
            }
        )
