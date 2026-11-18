"""Builders, constants and fakes that other test files import.

Moved from tests/unit/orchestration/test_goal_loop_operation_settlement.py.
"""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from mission_control.adapters.storage.artifact_payloads import InMemoryArtifactPayloadStore
from mission_control.application.execution.operations.checkpoint_lineage import (
    CheckpointLineageService,
    InMemoryCheckpointLineageRepository,
)
from mission_control.application.execution.operations.operation_execution import (
    InMemoryOperationBindingRepository,
    OperationExecutionService,
)
from mission_control.application.programs.goal_directed import GoalDirectedOperationResultService
from mission_control.domain.execution.contracts import (
    OperationExecutionResult,
    OperationWorkflowResult,
)
from mission_control.domain.policies.contracts import CommandStatus
from mission_control.domain.programs.contracts import GoalExecutionResult
from mission_control.domain.programs.goal_directed import GoalDirectedInterpreter
from mission_control.domain.programs.goal_directed_runtime import (
    GoalOperationDispatch,
    GoalOperationPreparationRequest,
    GoalOperationReconciliationRequest,
)
from tests.support.checkpoint_lineage import activity_attempt
from tests.support.checkpoint_recovery import AcceptingAuthority
from tests.support.journal import MemoryOperationJournal
from tests.support.journaled_goal_loop import (
    SCOPE,
    GoalComposition,
    admit_goal_run,
    compose_goal_directed,
    goal_blueprint,
    goal_model,
    goal_run_control,
    goal_run_input,
    goal_start_action,
)
from tests.support.run_control import command


async def _composition(*, journaled: bool = True) -> tuple[GoalComposition, str]:
    run_control = goal_run_control()
    composition = await compose_goal_directed(
        run_control=run_control,
        journal=MemoryOperationJournal(),
        lineage=CheckpointLineageService(InMemoryCheckpointLineageRepository()),
        results=InMemoryArtifactPayloadStore(),
        bindings=InMemoryOperationBindingRepository(),
        saver=InMemorySaver(),
        model=goal_model(),
        blueprint=goal_blueprint(),
    )
    if not journaled:
        # The pre-change composition RRM-006 had to use: no journal, an accepting authority.
        prior = composition.service
        composition.service = OperationExecutionService(
            authority=AcceptingAuthority(),
            bindings=prior._bindings,
            lanes=prior._lanes,
            sandbox=prior._sandbox,
            assets=prior._assets,
            mcp=prior._mcp,
            secrets=prior._secrets,
            events=prior._events,
            budget=prior._budget,
            journal=None,
            lineage=prior._lineage,
        )
        # ... and a family that records each operation's usage itself (no settlement port).
        composition.family._results = GoalDirectedOperationResultService(composition.documents)
    run_id = await admit_goal_run(run_control, f"rrm-016-unit-{'journal' if journaled else 'none'}")
    started = await run_control.execute(
        command(run_id, 1, "rrm-016-start", goal_start_action(run_id))
    )
    assert started.status == CommandStatus.ACCEPTED
    return composition, run_id


def _preparation(
    run_id: str,
    claim: Any,
    role: str,
    run_version: int,
    family_version: int,
    executor: GoalExecutionResult | None = None,
) -> GoalOperationPreparationRequest:
    blueprint = goal_blueprint()
    run_input = goal_run_input(run_id, blueprint, baseline={})
    revision = run_input.initial_revision
    verifier = role == "verifier"
    return GoalOperationPreparationRequest(
        request_scope=SCOPE,
        run_id=run_id,
        effective_configuration_digest=run_input.effective_configuration_digest,
        semantic_input_binding_ref=run_input.semantic_input_binding_ref,
        goal_revision_id=revision.revision_id,
        goal_revision_digest=revision.canonical_digest,
        goal_revision=revision,
        goal_iteration=claim.identity.iteration.goal_iteration,
        operation_role=role,  # type: ignore[arg-type]
        operation_attempt=1,
        execution_generation=1,
        expected_run_version=run_version,
        expected_family_version=family_version,
        reservation_id=(f"{claim.reservation_id}:verifier" if verifier else claim.reservation_id),
        reservation=claim.reservation,
        session_id=(f"{claim.session_id}:verifier" if verifier else claim.session_id),
        workspace_id=(
            f"{claim.workspace_namespace}:verifier" if verifier else claim.workspace_namespace
        ),
        read_workspace_id=executor.workspace_id if executor is not None else None,
        verifier_input_refs=executor.output_refs if executor is not None else (),
        decided_at=_now(),
        execution_epoch=claim.identity.iteration.execution_epoch,
        agent_run=claim.identity.agent_run,
        session_generation=claim.identity.session_generation,
    )


def _now() -> Any:
    from tests.support.run_control import NOW

    return NOW


def _reconciliation(
    claim: Any,
    role: str,
    dispatch: GoalOperationDispatch,
    result: OperationExecutionResult,
    executor: GoalExecutionResult | None = None,
) -> GoalOperationReconciliationRequest:
    blueprint = goal_blueprint()
    verifier = role == "verifier"
    return GoalOperationReconciliationRequest(
        request_scope=SCOPE,
        goal_revision_id=claim.identity.iteration.goal_revision_id,
        operation_role=role,  # type: ignore[arg-type]
        operation_binding_ref=dispatch.operation_binding_ref,
        required_output_contract_refs=tuple(sorted(blueprint.required_output_contracts)),
        operation_request=dispatch.workflow_request,
        claim=claim,
        executor_result=executor,
        operation_result=OperationWorkflowResult(
            semantic_attempt_id=dispatch.workflow_request.semantic_attempt_id,
            execution_generation=1,
            disposition="completed",
            result=result.model_dump(mode="json"),
            message_cursor=0,
        ),
        remaining_iterations=1,
        protected_fact_classes=(
            () if verifier else tuple(sorted(blueprint.session_policy.protected_fact_classes))
        ),
        context_selection_policy_ref=(
            None if verifier else blueprint.session_policy.context_selection_policy_ref
        ),
        context_compaction_policy_ref=(
            None if verifier else blueprint.session_policy.context_compaction_policy_ref
        ),
        workspace_ref_class=(
            None if verifier else sorted(blueprint.handoff_policy.allowed_workspace_ref_classes)[0]
        ),
        compaction_failure_action=(
            None if verifier else blueprint.session_policy.compaction_failure_action
        ),
        verifier_policy_binding_ref=(blueprint.verifier_policy.binding_ref if verifier else None),
        verifier_rubric_ref=blueprint.verifier_policy.rubric_ref if verifier else None,
        verifier_rubric_version=(blueprint.verifier_policy.rubric_version if verifier else None),
        acceptance_contract_ref=blueprint.acceptance_contract if verifier else None,
        acceptance_version=(blueprint.verifier_policy.acceptance_version if verifier else None),
        recorded_at=_now(),
    )


async def _claim(run_id: str) -> Any:
    blueprint = goal_blueprint()
    interpreter = GoalDirectedInterpreter(blueprint)
    state = interpreter.initial_state(goal_run_input(run_id, blueprint, baseline={}))
    _claimed, claim = interpreter.claim_execution(state)
    return claim


async def _run_iteration_one(composition: GoalComposition, run_id: str) -> dict[str, Any]:
    """Executor then verifier of iteration 1, each reconciled by the family service."""

    claim = await _claim(run_id)
    run = await composition.run_control.get_run(SCOPE, run_id)
    observed: dict[str, Any] = {"claim": claim, "versions": [run.version]}
    executor_dispatch = await composition.family.execute_iteration(
        _preparation(run_id, claim, "executor", run.version, 0)
    )
    executor_result = await composition.service.execute(
        executor_dispatch.workflow_request.operation,
        activity_attempt(workflow_id=executor_dispatch.workflow_request.workflow_id),
    )
    assert executor_result.status == "completed", executor_result
    executor = await composition.family.prepare_handoff(
        _reconciliation(claim, "executor", executor_dispatch, executor_result)
    )
    assert executor.execution_result is not None
    observed.update(
        executor_dispatch=executor_dispatch,
        executor_result=executor_result,
        executor=executor,
    )
    run = await composition.run_control.get_run(SCOPE, run_id)
    next_version = (
        executor.settlement.settled_run_version if executor.settlement is not None else run.version
    )
    verifier_dispatch = await composition.family.verify_iteration(
        _preparation(
            run_id,
            claim,
            "verifier",
            next_version,
            executor_dispatch.resulting_family_version,
            executor.execution_result,
        )
    )
    verifier_result = await composition.service.execute(
        verifier_dispatch.workflow_request.operation,
        activity_attempt(workflow_id=verifier_dispatch.workflow_request.workflow_id),
    )
    assert verifier_result.status == "completed", verifier_result
    verifier = await composition.family.prepare_handoff(
        _reconciliation(
            claim, "verifier", verifier_dispatch, verifier_result, executor.execution_result
        )
    )
    observed.update(
        verifier_dispatch=verifier_dispatch,
        verifier_result=verifier_result,
        verifier=verifier,
    )
    return observed
