"""Actual family scheduling and history replay over isolated, existing local Temporal.

The child is inert and the provider receipt is a fixture: provider/journal behavior
is proved separately. These tests prove that accepted controls reach active children
through both real family workflows instead of waiting for operation completion.
"""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest
from temporalio import activity, workflow
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from mission_control.adapters.temporal.workflow_sandbox import coordinator_workflow_runner
from mission_control.adapters.temporal.workflows.goal_directed import GoalDirectedWorkflow
from mission_control.adapters.temporal.workflows.stagegraph import StageGraphWorkflow
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.execution.budget_controls import (
    BudgetControlRecord,
    LaneBudgetControlRequest,
    budget_control_key,
)
from mission_control.domain.execution.contracts import OperationWorkflowRequest
from mission_control.domain.policies.contracts import (
    ManagedBudgetGate,
    PauseAction,
    PauseDecision,
    ResumeAction,
    ResumeDecision,
)
from mission_control.domain.programs.contracts import (
    BoundaryLifecycleOutcome,
    BoundaryLifecycleRequest,
    StageGraphAdmissionActivityRequest,
    StageGraphAdmissionActivityResult,
)
from tests.fixtures.managed_lane import managed_binding, managed_operation
from tests.integration.temporal.test_rrm_007_boundary_interventions import (
    SCOPE,
    Authority,
    GovernedGoalActivities,
    GovernedStageGraphActivities,
    _goal_blueprint,
    _goal_run,
    _state_is,
    until,
)
from tests.integration.temporal.test_wp_bp_010_temporal import _blueprint, _run_input

DIGEST = "sha256:" + "a" * 64
QUEUE = "run2-budget-family-isolated"


def existing_test_server() -> str:
    selected = os.environ.get("MISSION_CONTROL_TEST_TEMPORAL_SERVER", "")
    assert selected and Path(selected).is_file(), (
        "set MISSION_CONTROL_TEST_TEMPORAL_SERVER to the authorized existing test server; "
        "this test never downloads a binary or uses a shared namespace"
    )
    return selected


@workflow.defn(name="belllabs.operation.v2", sandboxed=False)
class InertManagedChild:
    @workflow.run
    async def run(self, request: OperationWorkflowRequest) -> None:
        await workflow.wait_condition(lambda: False)


def managed_request(original):
    operation = managed_operation(managed_binding(DIGEST, task_queue=QUEUE))
    operation = operation.model_copy(
        update={
            "identity": original.operation.identity,
            "request_scope": original.operation.request_scope,
            "runtime_unit": original.operation.runtime_unit,
            "budget_reservation_id": original.operation.budget_reservation_id,
            "budget_limits": original.operation.budget_limits,
        }
    )
    return original.model_copy(update={"operation": operation})


class BudgetReceipts:
    def init_budget(self):
        self.managed_requests = []
        self.controls = []

    @activity.defn(name="lane.budget_control")
    async def budget_control(self, payload: dict) -> dict:
        request = LaneBudgetControlRequest.model_validate(payload)
        self.controls.append(request)
        status = await self.authority.run_control.get_boundary_command(
            SCOPE, request.operation.identity.run_id, request.command_issuer, request.command_id
        )
        assert status is not None
        command = status.command
        return BudgetControlRecord(
            key=budget_control_key(request.command_issuer, request.command_id),
            command_id=request.command_id,
            command_issuer=request.command_issuer,
            command_digest=command.payload_digest,
            command_sequence=command.target_sequence,
            operation_digest=sha256_digest(request.operation),
            request_scope=SCOPE,
            run_id=request.operation.identity.run_id,
            harness_execution_id=uuid5(NAMESPACE_URL, request.operation.identity.semantic_key),
            native_session_ref="fixture:" + request.operation.identity.semantic_key,
            generation=request.generation,
            binding_digest=DIGEST,
            configuration_digest=DIGEST,
            action="hold" if command.kind == "pause" else "resume",
            ceiling_minor_units=90,
            phase="boundary_observed" if command.kind == "pause" else "cap_confirmed",
            evidence="fixture-native-budget-boundary",
            recorded_at=datetime.now(UTC),
        ).model_dump(mode="json")


class ManagedStageActivities(BudgetReceipts, GovernedStageGraphActivities):
    def __init__(self, authority):
        super().__init__(authority)
        self.init_budget()
        self.reject_commands = set()
        self.boundary_requests = []

    @activity.defn(name="stagegraph.apply_boundary_command")
    async def apply_boundary_command(
        self, request: BoundaryLifecycleRequest
    ) -> BoundaryLifecycleOutcome:
        self.boundary_requests.append(request)
        if request.boundary_command_id in self.reject_commands:
            request = replace(request, action={}, rejection_reason="not_applicable")
        return await super().apply_boundary_command(request)

    @activity.defn(name="stagegraph.admit_operation")
    async def admit(
        self, request: StageGraphAdmissionActivityRequest
    ) -> StageGraphAdmissionActivityResult:
        result = await super().admit(request)
        operation = managed_request(result.operation)
        self.managed_requests.append(operation)
        return replace(result, operation=operation)

    @property
    def functions(self):
        return [*super().functions, self.budget_control]


class ManagedGoalActivities(BudgetReceipts, GovernedGoalActivities):
    def __init__(self, authority):
        super().__init__(authority)
        self.init_budget()

    async def _prepare(self, request):
        result = await super()._prepare(request)
        operation = managed_request(result.workflow_request)
        self.managed_requests.append(operation)
        return result.model_copy(update={"workflow_request": operation})

    @property
    def functions(self):
        return [*super().functions, self.budget_control]


@pytest.mark.parametrize("family", ["StageGraph", "GoalDirected"])
async def test_accepted_budget_hold_and_resume_reach_active_family_children_and_replay(family):
    environment = await WorkflowEnvironment.start_time_skipping(
        test_server_existing_path=existing_test_server()
    )
    async with environment:
        authority = Authority(environment.client)
        if family == "StageGraph":
            activities = ManagedStageActivities(authority)
            run_id = await authority.admit("run2-budget-stage")
            run_input = replace(_run_input(_blueprint()), run_id=run_id)
            cls = StageGraphWorkflow
        else:
            activities = ManagedGoalActivities(authority)
            run_id, _, run_input = await _goal_run(authority, "run2-budget-goal", _goal_blueprint())
            cls = GoalDirectedWorkflow
        async with Worker(
            environment.client,
            task_queue=QUEUE,
            workflows=[cls, InertManagedChild],
            activities=activities.functions,
            workflow_runner=coordinator_workflow_runner(),
        ):
            handle = await environment.client.start_workflow(
                cls.run, run_input, id=f"family/{run_id}/1", task_queue=QUEUE
            )

            async def started():
                return bool(activities.managed_requests)

            await until(started)
            pause = PauseAction(
                decision=PauseDecision(
                    decision_id="budget-pause",
                    scope=frozenset({"run"}),
                    reason="fixture hold",
                    authority_ref="authority:lifecycle",
                    budget_gate=ManagedBudgetGate(),
                ),
                runnable_work_remains=False,
            )
            await authority.intervene(run_id, "hold", pause)
            await until(lambda: _state_is(authority, run_id, "hold", "applied"))
            assert activities.controls and all(
                ProviderExecutionBinding.carried_by(r.operation).lane_profile == "claude_managed"
                for r in activities.controls
            )
            hold_count = len(activities.controls)
            assert await authority.facade.redeliver(SCOPE, run_id) == ()
            assert len(activities.controls) == hold_count
            resume = ResumeAction(
                decision=ResumeDecision(
                    decision_id="budget-resume",
                    pause_decision_id="budget-pause",
                    reason="fixture resume",
                    authority_ref="authority:lifecycle",
                    budget_gate=ManagedBudgetGate(
                        hold_command_id="hold", hold_command_issuer="operator"
                    ),
                )
            )
            await authority.intervene(run_id, "resume", resume)
            await until(lambda: _state_is(authority, run_id, "resume", "applied"))
            assert len(activities.controls) == 2 * hold_count
            assert (await authority.run(run_id)).active_pauses == ()
            history = await handle.fetch_history()
            await Replayer(
                workflows=[cls], workflow_runner=coordinator_workflow_runner()
            ).replay_workflow(history)
            # Only fixture executions exist on this ephemeral server; termination ensures
            # the test never leaves an inert child waiting after its assertion scope.
            await handle.terminate("isolated budget family proof complete")


@pytest.mark.parametrize("rejected_kind", ["pause", "resume"])
async def test_stagegraph_rejected_authority_keeps_previous_held_child_projection(rejected_kind):
    environment = await WorkflowEnvironment.start_time_skipping(
        test_server_existing_path=existing_test_server()
    )
    async with environment:
        authority = Authority(environment.client)
        activities = ManagedStageActivities(authority)
        run_id = await authority.admit(f"run2-budget-rejected-{rejected_kind}")
        run_input = replace(_run_input(_blueprint()), run_id=run_id)
        async with Worker(
            environment.client,
            task_queue=QUEUE,
            workflows=[StageGraphWorkflow, InertManagedChild],
            activities=activities.functions,
            workflow_runner=coordinator_workflow_runner(),
        ):
            handle = await environment.client.start_workflow(
                StageGraphWorkflow.run, run_input, id=f"family/{run_id}/1", task_queue=QUEUE
            )

            async def started():
                return bool(activities.managed_requests)

            await until(started)
            activities.reject_commands.add("hold" if rejected_kind == "pause" else "resume")
            await authority.intervene(
                run_id,
                "hold",
                PauseAction(
                    decision=PauseDecision(
                        decision_id="budget-pause",
                        scope=frozenset({"run"}),
                        reason="fixture hold",
                        authority_ref="authority:lifecycle",
                        budget_gate=ManagedBudgetGate(),
                    ),
                    runnable_work_remains=False,
                ),
            )
            await until(
                lambda: _state_is(
                    authority, run_id, "hold", "rejected" if rejected_kind == "pause" else "applied"
                )
            )
            if rejected_kind == "resume":
                await authority.intervene(
                    run_id,
                    "resume",
                    ResumeAction(
                        decision=ResumeDecision(
                            decision_id="budget-resume",
                            pause_decision_id="budget-pause",
                            reason="fixture resume",
                            authority_ref="authority:lifecycle",
                            budget_gate=ManagedBudgetGate(
                                hold_command_id="hold", hold_command_issuer="operator"
                            ),
                        )
                    ),
                )
                await until(lambda: _state_is(authority, run_id, "resume", "rejected"))
            # A later boundary-only pause reads the committed projection. A refused
            # native hold must not suppress it; a refused resume must not restore it.
            await authority.intervene(
                run_id,
                "probe",
                PauseAction(
                    decision=PauseDecision(
                        decision_id="projection-probe",
                        scope=frozenset({"run"}),
                        reason="inspect committed runnable projection",
                        authority_ref="authority:lifecycle",
                    ),
                    runnable_work_remains=True,
                ),
            )
            await until(lambda: _state_is(authority, run_id, "probe", "applied"))
            probe = next(
                r for r in activities.boundary_requests if r.boundary_command_id == "probe"
            )
            assert probe.action["runnable_work_remains"] is (rejected_kind == "pause")
            refused = next(
                r
                for r in activities.boundary_requests
                if r.boundary_command_id == ("hold" if rejected_kind == "pause" else "resume")
            )
            assert refused.action["boundary_state"]["budget_controls"]
            await Replayer(
                workflows=[StageGraphWorkflow], workflow_runner=coordinator_workflow_runner()
            ).replay_workflow(await handle.fetch_history())
            await handle.terminate("isolated rejected budget authority proof complete")
