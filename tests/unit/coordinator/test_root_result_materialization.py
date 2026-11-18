"""Terminal family completion identity and the materializer's registration on both family
queues. The root's wait for the persisted result runs on Temporal in
tests/integration/temporal/test_root_result_materialization.py."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from temporalio import activity

from mission_control.adapters.temporal.activities.goal_directed import GoalDirectedActivities
from mission_control.adapters.temporal.orchestration_activities import StageGraphActivities
from mission_control.adapters.temporal.registration.activities import coordinator_activities
from mission_control.domain.coordinator.workflow_completion import terminal_family_completion
from mission_control.domain.policies.contracts import RunOutcome
from mission_control.domain.programs.contracts import (
    GoalDirectedRunResult,
    StageGraphCompletionProposal,
    StageGraphRunResult,
)
from tests.support.unit.coordinator.root_result_materialization import root

NOW = datetime(2026, 10, 11, tzinfo=UTC)


def family_result(family="StageGraph", outcome=RunOutcome.COMPLETED):
    if family == "StageGraph":
        return StageGraphRunResult(
            run_id="run-1",
            workflow_cycles=0,
            execution_epoch=1,
            family_version=3,
            output_refs={"stage": ("artifact:lineage",)},
            reused_output_refs={},
            schedule_trace=("stage",),
            completion_proposal=StageGraphCompletionProposal(
                required_obligations_accepted=outcome == RunOutcome.COMPLETED,
                pending_dependency_ids=(),
                open_producer_liability_ids=(),
                valid_output_refs=("artifact:accepted",),
                cancelled=outcome == RunOutcome.CANCELLED,
                failed=outcome == RunOutcome.FAILED,
            ),
        )
    return GoalDirectedRunResult(
        run_id="run-1",
        execution_epoch=1,
        status="cancelled" if outcome == RunOutcome.CANCELLED else "stopping",
        convergence_proposal=None,
        terminalization_proposal=None,
        goal_iterations=2,
        agent_runs=3,
        rollover_count=1,
        active_revision_id="revision:2",
        accepted_revision_ids=("revision:1", "revision:2"),
        output_refs=("artifact:unaccepted-executor-output",),
        handoffs=(),
        execution_results=(),
        verification_results=(),
    )


@pytest.mark.parametrize("family", ["StageGraph", "GoalDirected"])
def test_completion_rejects_other_run_or_generation(family):
    result = family_result(family)
    for changed in (replace(result, run_id="other"), replace(result, execution_epoch=2)):
        with pytest.raises(ValueError, match="identity"):
            terminal_family_completion(root(family), changed, completed_at=NOW)


def test_completion_rejects_other_family():
    with pytest.raises(ValueError, match="family"):
        terminal_family_completion(root(), family_result("GoalDirected"), completed_at=NOW)


@pytest.mark.parametrize(
    ("family", "cls"),
    [("StageGraph", StageGraphActivities), ("GoalDirected", GoalDirectedActivities)],
)
def test_both_production_queues_register_terminal_materializer(family, cls):
    names = {
        activity._Definition.must_from_callable(item).name
        for item in coordinator_activities(family, cls)
    }
    assert "coordinator.materialize_workflow_result" in names
