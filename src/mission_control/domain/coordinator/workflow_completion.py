"""Convert terminal family diagnostics without inferring the mission's outcome."""

from dataclasses import asdict
from datetime import datetime

from mission_control.domain.coordinator.launch import (
    BlueprintFamily,
    GoalDirectedResultDetails,
    StageGraphResultDetails,
    TerminalWorkflowCompletion,
)
from mission_control.domain.programs.contracts import (
    BellLabsRunInput,
    GoalDirectedRunResult,
    StageGraphRunResult,
)


def terminal_family_completion(
    run_input: BellLabsRunInput,
    result: StageGraphRunResult | GoalDirectedRunResult,
    *,
    completed_at: datetime,
) -> TerminalWorkflowCompletion:
    if result.run_id != run_input.run_id or (
        result.execution_epoch != run_input.continuity.execution_epoch
    ):
        raise ValueError("terminal family result differs from the admitted root identity")
    details: StageGraphResultDetails | GoalDirectedResultDetails
    if isinstance(result, StageGraphRunResult) and run_input.family == "StageGraph":
        details = StageGraphResultDetails(
            execution_epoch=result.execution_epoch,
            workflow_cycles=result.workflow_cycles,
            output_refs=result.output_refs,
            reused_output_refs=result.reused_output_refs,
            schedule_trace=result.schedule_trace,
        )
    elif isinstance(result, GoalDirectedRunResult) and run_input.family == "GoalDirected":
        details = GoalDirectedResultDetails(
            execution_epoch=result.execution_epoch,
            stop_reason=(
                "cancelled"
                if result.status == "cancelled"
                else result.convergence_proposal.reason
                if result.convergence_proposal is not None
                else "not_observed"
            ),
            final_verifier_action=(
                result.verification_results[-1].decision
                if result.verification_results
                else "not_observed"
            ),
            goal_iterations=result.goal_iterations,
            agent_runs=result.agent_runs,
            rollover_count=result.rollover_count,
            active_revision_id=result.active_revision_id,
            accepted_revision_ids=result.accepted_revision_ids,
            handoff_checkpoints=tuple(asdict(item) for item in result.handoffs),
            execution_results=tuple(item.to_payload() for item in result.execution_results),
            verification_results=tuple(asdict(item) for item in result.verification_results),
        )
    else:
        raise ValueError("terminal family result differs from the admitted blueprint family")
    return TerminalWorkflowCompletion(
        run_id=run_input.run_id,
        tenant_scope=run_input.family_input.get("tenant_scope") or run_input.request_scope,
        request_scope=run_input.request_scope,
        blueprint_family=BlueprintFamily(run_input.family),
        family_result=details,
        completed_at=completed_at,
    )
