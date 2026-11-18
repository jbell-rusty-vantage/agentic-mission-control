from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest
from temporalio.worker import Replayer, Worker

from mission_control.adapters.temporal.workflow_sandbox import coordinator_workflow_runner
from mission_control.adapters.temporal.workflows.goal_directed import GoalDirectedWorkflow
from mission_control.adapters.temporal.workflows.operation import OperationWorkflow
from mission_control.application.programs.goal_directed import (
    GoalDirectedOperationPreparationService,
    GoalDirectedOperationResultService,
)
from mission_control.domain.authoring.contracts import (
    GoalDirectedBlueprint,
)
from mission_control.domain.authoring.fixtures import GENERIC_GOAL_DIRECTED
from mission_control.domain.execution.contracts import (
    OperationExecutionRequest,
    OperationExecutionResult,
    OperationWorkflowRequest,
    OperationWorkflowResult,
    RuntimeUsage,
)
from mission_control.domain.policies.contracts import ActorContext
from mission_control.domain.programs.contracts import (
    GoalExecutionResult,
    GoalRevision,
    GoalVerificationResult,
)
from mission_control.domain.programs.goal_directed import GoalDirectedInterpreter
from mission_control.domain.programs.goal_directed_runtime import (
    GoalOperationPreparationRequest,
    GoalOperationReconciliationRequest,
)
from tests.support.integration.temporal.goal_loop_workflow_temporal import (
    NOW,
    FakeGoalDirectedActivities,
    _operation,
    _run_input,
)
from tests.support.journaled_goal_loop import goal_template_workspace
from tests.support.lane_bindings import LANE_REBINDERS
from tests.support.temporal import start_workflow_env


class RecordingGoalDocuments:
    def __init__(self) -> None:
        self.revisions: list[GoalRevision] = []
        self.verifications: list[GoalVerificationResult] = []

    async def persist_revision(
        self,
        request_scope: str,
        run_id: str,
        revision: GoalRevision,
        recorded_at: datetime,
    ) -> str:
        self.revisions.append(revision)
        return "goal-revision:recorded"

    async def persist_verification(
        self,
        request_scope: str,
        run_id: str,
        goal_revision_id: str,
        verification: GoalVerificationResult,
        recorded_at: datetime,
    ) -> str:
        self.verifications.append(verification)
        return "goal-verification:recorded"


class FixedGoalTemplateProvider:
    def __init__(self, template: OperationExecutionRequest) -> None:
        self._template = template

    async def get_template(self, **_: object) -> OperationExecutionRequest:
        return self._template


class RecordingOperationBindings:
    def __init__(self) -> None:
        self.bindings: list[object] = []

    async def create_binding(self, binding, *, request_scope: str):
        self.bindings.append(binding)
        return binding


class AcceptingFamilyRunControl:
    def __init__(self) -> None:
        self.mutations: list[object] = []

    async def execute_family_admission(self, command, mutation):
        self.mutations.append(mutation)
        return SimpleNamespace(
            command_result=SimpleNamespace(resulting_run_version=3),
            family_receipt=SimpleNamespace(family_version=2),
        )


@pytest.mark.asyncio
async def test_real_preparer_persists_revision_before_atomic_operation_admission() -> None:
    run_input = _run_input()
    interpreter = GoalDirectedInterpreter(GENERIC_GOAL_DIRECTED)
    _, claim = interpreter.claim_execution(interpreter.initial_state(run_input))
    request = GoalOperationPreparationRequest(
        request_scope=run_input.request_scope,
        run_id=run_input.run_id,
        effective_configuration_digest=run_input.effective_configuration_digest,
        semantic_input_binding_ref=run_input.semantic_input_binding_ref,
        goal_revision_id=run_input.initial_revision.revision_id,
        goal_revision_digest=run_input.initial_revision.canonical_digest,
        goal_revision=run_input.initial_revision,
        goal_iteration=1,
        operation_role="executor",
        operation_attempt=1,
        execution_generation=1,
        expected_run_version=2,
        expected_family_version=1,
        reservation_id=claim.reservation_id,
        reservation=claim.reservation,
        session_id=claim.session_id,
        workspace_id=claim.workspace_namespace,
        decided_at=NOW,
        execution_epoch=claim.identity.iteration.execution_epoch,
        agent_run=claim.identity.agent_run,
        session_generation=claim.identity.session_generation,
    )
    documents = RecordingGoalDocuments()
    bindings = RecordingOperationBindings()
    run_control = AcceptingFamilyRunControl()
    service = GoalDirectedOperationPreparationService(
        lane_bindings=LANE_REBINDERS,
        # RRM-016: a GoalDirected template carries the compiled workspace slots.
        templates=FixedGoalTemplateProvider(
            _operation(request).model_copy(
                update={"workspace": goal_template_workspace(_operation(request).workspace)}
            )
        ),
        operation_bindings=bindings,  # type: ignore[arg-type]
        run_control=run_control,  # type: ignore[arg-type]
        documents=documents,  # type: ignore[arg-type]
        actor=ActorContext(
            actor_id="goal-directed-worker",
            permissions=frozenset({"workflow_run.goal_directed"}),
        ),
    )
    dispatch = await service.prepare(request)

    assert documents.revisions == [run_input.initial_revision]
    assert len(bindings.bindings) == 1
    assert len(run_control.mutations) == 1
    assert dispatch.resulting_run_version == 3
    assert dispatch.resulting_family_version == 2
    assert dispatch.workflow_request.operation.identity.run_id == run_input.run_id
    # REQ-CP-EXEC-013: the dispatched request carries the iteration/revision/session/role unit.
    unit = dispatch.workflow_request.operation.runtime_unit
    assert unit is not None
    assert (unit.family, unit.unit_kind, unit.execution_epoch) == (
        "goal_directed",
        "goal_executor",
        1,
    )
    assert unit.location.model_dump() == {
        "goal_iteration": 1,
        "goal_revision_id": run_input.initial_revision.revision_id,
        "operation_role": "executor",
        "agent_run": claim.identity.agent_run,
        "session_generation": claim.identity.session_generation,
    }
    assert bindings.bindings[0].runtime_unit == unit
    with pytest.raises(ValueError, match="agent run and session generation"):
        await service.prepare(request.model_copy(update={"session_generation": None}))


@pytest.mark.asyncio
async def test_real_reconciler_binds_verifier_authority_and_recomputes_digest() -> None:
    run_input = _run_input()
    interpreter = GoalDirectedInterpreter(GENERIC_GOAL_DIRECTED)
    state, claim = interpreter.claim_execution(interpreter.initial_state(run_input))
    execution = GoalExecutionResult(
        identity=claim.identity,
        disposition="completed",
        operation_identity=f"{claim.identity.iteration.semantic_key}:executor",
        operation_binding_ref="binding:executor",
        session_id=claim.session_id,
        workspace_id=claim.workspace_namespace,
        writable_paths=("/goal/executor/work",),
        output_refs=("artifact:verified-result",),
    )
    state = interpreter.apply_execution_result(state, execution)
    preparation = GoalOperationPreparationRequest(
        request_scope=run_input.request_scope,
        run_id=run_input.run_id,
        effective_configuration_digest=run_input.effective_configuration_digest,
        semantic_input_binding_ref=run_input.semantic_input_binding_ref,
        goal_revision_id=run_input.initial_revision.revision_id,
        goal_revision_digest=run_input.initial_revision.canonical_digest,
        goal_revision=run_input.initial_revision,
        goal_iteration=1,
        operation_role="verifier",
        operation_attempt=1,
        execution_generation=1,
        expected_run_version=2,
        expected_family_version=1,
        reservation_id="reservation:verifier",
        reservation={"goal.iterations": 1},
        session_id=f"{claim.session_id}:verifier",
        workspace_id=f"{claim.workspace_namespace}:verifier",
        read_workspace_id=execution.workspace_id,
        verifier_input_refs=execution.output_refs,
        decided_at=NOW,
    )
    operation = _operation(preparation)
    workflow_request = OperationWorkflowRequest(
        semantic_attempt_id=operation.identity.semantic_key,
        operation_kind="bound_operation",
        operation=operation,
    )
    provider_values = {
        "schema_version": "belllabs.goal-verifier-observation.v1",
        "decision": "accepted",
        "progress_made": True,
        "accepted_obligation_refs": ("fixture-obligation",),
        "findings": (),
        "evidence_refs": ("evidence:verifier",),
        "unmet_obligations": (),
        "obligation_applicability": (("fixture-obligation", True),),
        "blocker_class": "",
        "authority_breach_ref": "",
        "hard_budget_exhausted_dimensions": (),
        "soft_budget_dimensions": (),
        "irrecoverable_failure_ref": "",
        "proposed_revision": None,
        "scope_expansion_route": None,
        "route_ref": "",
        "effect_refs": (),
        "output_contract_ref": "fixture-output",
    }
    documents = RecordingGoalDocuments()
    service = GoalDirectedOperationResultService(documents)  # type: ignore[arg-type]
    reconciled = await service.reconcile(
        GoalOperationReconciliationRequest(
            request_scope=run_input.request_scope,
            goal_revision_id=run_input.initial_revision.revision_id,
            operation_role="verifier",
            operation_binding_ref="binding:persisted-verifier",
            required_output_contract_refs=("fixture-output",),
            operation_request=workflow_request,
            claim=claim,
            executor_result=execution,
            operation_result=OperationWorkflowResult(
                semantic_attempt_id=workflow_request.semantic_attempt_id,
                execution_generation=1,
                disposition="completed",
                result=OperationExecutionResult(
                    binding_id="binding:persisted-verifier",
                    semantic_attempt_key=workflow_request.semantic_attempt_id,
                    status="completed",
                    structured_output=provider_values,
                    usage=RuntimeUsage(amounts={"goal.iterations": 1}),
                ).model_dump(mode="json"),
                message_cursor=0,
                effect_frontier=("effect:operation-frontier",),
                active_async_child_ids=("child:still-active",),
            ),
            remaining_iterations=0,
            verifier_policy_binding_ref=GENERIC_GOAL_DIRECTED.verifier_policy.binding_ref,
            verifier_rubric_ref=GENERIC_GOAL_DIRECTED.verifier_policy.rubric_ref,
            verifier_rubric_version=GENERIC_GOAL_DIRECTED.verifier_policy.rubric_version,
            acceptance_contract_ref=GENERIC_GOAL_DIRECTED.acceptance_contract,
            acceptance_version=GENERIC_GOAL_DIRECTED.verifier_policy.acceptance_version,
            recorded_at=NOW,
        )
    )
    verification = reconciled.verification_result
    assert verification is not None
    assert verification.verification_id.startswith("goal-verification:")
    assert verification.verification_id != "verification:provider-observation"
    assert verification.verification_ref.startswith(f"{verification.verification_id}@sha256:")
    assert verification.verifier_binding_ref == "binding:persisted-verifier"
    assert (
        verification.verifier_policy_binding_ref
        == GENERIC_GOAL_DIRECTED.verifier_policy.binding_ref
    )
    assert verification.effect_refs == (
        "effect:operation-frontier",
        "async-child:child:still-active",
    )
    accepted = interpreter.apply_verification(state, verification)
    assert accepted.convergence_proposal is not None
    assert accepted.convergence_proposal.action == "complete"


@pytest.mark.asyncio
async def test_goal_workflow_runs_separate_operation_children_and_replays() -> None:
    activities = FakeGoalDirectedActivities()
    environment = await start_workflow_env()

    async with environment:
        async with Worker(
            environment.client,
            task_queue="wp-bp-020-temporal",
            workflows=[GoalDirectedWorkflow, OperationWorkflow],
            workflow_runner=coordinator_workflow_runner(),
            activities=activities.functions,
        ):
            result = await environment.client.execute_workflow(
                GoalDirectedWorkflow.run,
                _run_input(),
                id="family/run-wp-bp-020-temporal/1",
                task_queue="wp-bp-020-temporal",
            )
            history = await environment.client.get_workflow_handle(
                "family/run-wp-bp-020-temporal/1"
            ).fetch_history()

        await Replayer(
            workflows=[GoalDirectedWorkflow, OperationWorkflow],
            workflow_runner=coordinator_workflow_runner(),
        ).replay_workflow(history)

    assert activities.prepared_roles == ["executor", "verifier"]
    execution = result.execution_results[0]
    verification = result.verification_results[0]
    assert execution.operation_identity != verification.verifier_operation_identity
    assert execution.operation_binding_ref != verification.verifier_binding_ref
    assert execution.session_id != verification.verifier_session_id
    assert execution.workspace_id != verification.verifier_workspace_id
    assert result.convergence_proposal.action == "complete"
    assert activities.lifecycle_kinds[-1] == "terminalize"


@pytest.mark.asyncio
async def test_goal_workflow_continue_as_new_preserves_semantic_iteration() -> None:
    blueprint = GoalDirectedBlueprint.model_validate(
        {
            **GENERIC_GOAL_DIRECTED.model_dump(mode="python"),
            "max_iterations": 25,
        }
    )
    activities = FakeGoalDirectedActivities(complete_at_iteration=25)
    environment = await start_workflow_env()

    async with environment:
        async with Worker(
            environment.client,
            task_queue="wp-bp-020-temporal",
            workflows=[GoalDirectedWorkflow, OperationWorkflow],
            workflow_runner=coordinator_workflow_runner(),
            activities=activities.functions,
        ):
            result = await environment.client.execute_workflow(
                GoalDirectedWorkflow.run,
                _run_input(
                    blueprint=blueprint,
                    run_id="run-wp-bp-020-continuation",
                ),
                id="family/run-wp-bp-020-continuation/1",
                task_queue="wp-bp-020-temporal",
            )
            history = await environment.client.get_workflow_handle(
                "family/run-wp-bp-020-continuation/1"
            ).fetch_history()

        await Replayer(
            workflows=[GoalDirectedWorkflow, OperationWorkflow],
            workflow_runner=coordinator_workflow_runner(),
        ).replay_workflow(history)

    assert activities.prepared_roles.count("executor") == 25
    assert activities.prepared_roles.count("verifier") == 25
    assert activities.lifecycle_kinds.count("start") == 1
    assert result.goal_iterations == 25
    assert result.agent_runs == 25
    assert result.lineage_digest
    assert result.verification_results[-1].executor_identity.iteration.goal_iteration == 25
    assert result.convergence_proposal.action == "complete"


@pytest.mark.asyncio
async def test_goal_workflow_returns_governed_scope_expansion_proposal() -> None:
    activities = FakeGoalDirectedActivities(scope_expansion_route="linked_run")
    blueprint = GoalDirectedBlueprint.model_validate(
        {
            **GENERIC_GOAL_DIRECTED.model_dump(mode="python"),
            "max_iterations": 2,
        }
    )
    environment = await start_workflow_env()

    async with environment:
        async with Worker(
            environment.client,
            task_queue="wp-bp-020-temporal",
            workflows=[GoalDirectedWorkflow, OperationWorkflow],
            workflow_runner=coordinator_workflow_runner(),
            activities=activities.functions,
        ):
            result = await environment.client.execute_workflow(
                GoalDirectedWorkflow.run,
                _run_input(
                    blueprint=blueprint,
                    run_id="run-wp-bp-020-route",
                ),
                id="family/run-wp-bp-020-route/1",
                task_queue="wp-bp-020-temporal",
            )

    assert result.convergence_proposal.action == "linked_run"
    assert result.convergence_proposal.route_ref == "route:governed-expansion"
    assert result.terminalization_proposal is None
    assert "terminalize" not in activities.lifecycle_kinds


@pytest.mark.asyncio
async def test_goal_workflow_cancels_active_operation_and_replays_reconciliation() -> None:
    activities = FakeGoalDirectedActivities(slow_operation=True)
    environment = await start_workflow_env()

    async with environment:
        async with Worker(
            environment.client,
            task_queue="wp-bp-020-temporal",
            workflows=[GoalDirectedWorkflow, OperationWorkflow],
            workflow_runner=coordinator_workflow_runner(),
            activities=activities.functions,
        ):
            handle = await environment.client.start_workflow(
                GoalDirectedWorkflow.run,
                _run_input(),
                id="family/run-wp-bp-020-cancel/1",
                task_queue="wp-bp-020-temporal",
            )
            await asyncio.wait_for(activities.operation_started.wait(), timeout=10)
            await handle.signal(GoalDirectedWorkflow.request_cancel)
            result = await handle.result()
            history = await handle.fetch_history()

        await Replayer(
            workflows=[GoalDirectedWorkflow, OperationWorkflow],
            workflow_runner=coordinator_workflow_runner(),
        ).replay_workflow(history)

    # RRM-008 (REQ-CP-EXEC-008): the family completes the cancellation saga as workflow
    # logic. The active unit settles `cancelled` (`operation.cancel`), the family consumes
    # that settlement and proposes terminal `cancelled`; it issues no cancel of its own and
    # never fails in place of reconciliation.
    assert result.status == "cancelled" and result.convergence_proposal is None
    assert activities.cancelled_operations == ["goal-iteration/1/executor"]
    assert "cancel" not in activities.lifecycle_kinds
    assert activities.lifecycle_kinds.count("terminalize") == 1
