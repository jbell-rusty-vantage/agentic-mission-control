from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from temporalio import activity

from mission_control.adapters.temporal.activities.goal_directed import GoalDirectedActivities
from mission_control.adapters.temporal.orchestration_activities import StageGraphActivities
from mission_control.adapters.temporal.registration.activities import coordinator_activities
from mission_control.adapters.temporal.workflows import mission_run
from mission_control.adapters.temporal.workflows.belllabs_run import BellLabsRunWorkflow
from mission_control.application.coordinator.coordinator_results import (
    TerminalWorkflowCompletionService,
)
from mission_control.domain.coordinator.workflow_completion import terminal_family_completion
from mission_control.domain.policies.contracts import RunOutcome, RunPhase
from mission_control.domain.programs.contracts import (
    BellLabsRunInput,
    GoalDirectedRunResult,
    StageGraphCompletionProposal,
    StageGraphRunResult,
)
from tests.unit.coordinator.test_coordinator_result_completion import AmbiguousFirstSave

NOW = datetime(2026, 10, 11, tzinfo=UTC)
SCOPE = "mc/00000000-0000-0000-0000-000000000001/biotech/00000000-0000-0000-0000-000000000002"
DIGEST = "sha256:" + "a" * 64


def root(family="StageGraph"):
    return BellLabsRunInput(
        schema_version="mc.mission_run.v1",
        run_id="run-1",
        request_scope=SCOPE,
        effective_configuration_digest=DIGEST,
        workflow_type_digest=DIGEST,
        family=family,
        family_task_queue="family-queue",
        family_input={
            "run_id": "run-1",
            "request_scope": SCOPE,
            "effective_configuration_digest": DIGEST,
            "workflow_type_digest": DIGEST,
        },
    )


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
@pytest.mark.parametrize("outcome", list(RunOutcome))
@pytest.mark.asyncio
async def test_root_waits_for_persisted_result_with_retryable_same_payload(
    monkeypatch, family, outcome
):
    admitted = root(family)
    result = family_result(family, outcome)
    repository = AmbiguousFirstSave()
    run = SimpleNamespace(
        run_id=admitted.run_id,
        request_scope=SCOPE,
        phase=RunPhase.TERMINAL,
        terminal_outcome=outcome,
        accepted_output_evidence=(SimpleNamespace(output_ref="artifact:accepted"),),
        accepted_obligation_evidence=(SimpleNamespace(obligation_ref="goal:accepted"),),
    )
    runs = SimpleNamespace(get_run=AsyncMock(return_value=run))
    calls = []

    async def materialize(name, request, **options):
        assert name == "coordinator.materialize_workflow_result"
        assert options["task_queue"] == admitted.family_task_queue
        assert options["retry_policy"].maximum_attempts == 0
        assert request.terminal_outcome is None
        calls.append(request)
        first = TerminalWorkflowCompletionService(runs=runs, results=repository)
        with pytest.raises(TimeoutError, match="ambiguous"):
            await first.complete(request)
        # Restarted activity/service recovers the committed record with identical inputs.
        restarted = TerminalWorkflowCompletionService(runs=runs, results=repository)
        return await restarted.complete(request)

    monkeypatch.setattr(BellLabsRunWorkflow, "run", AsyncMock(return_value=result))
    monkeypatch.setattr(
        mission_run.workflow, "info", lambda: SimpleNamespace(workflow_id=admitted.workflow_id)
    )
    monkeypatch.setattr(mission_run.workflow, "patched", lambda _: True)
    monkeypatch.setattr(mission_run.workflow, "now", lambda: NOW)
    monkeypatch.setattr(mission_run.workflow, "execute_activity", materialize)
    assert await mission_run.MissionRunWorkflow().run(admitted) == result
    saved = await repository.get(SCOPE, SCOPE, admitted.run_id)
    assert saved.terminal_outcome == outcome
    assert saved.artifact_refs == ("artifact:accepted",)
    assert saved.evidence_refs == ("goal:accepted",)
    assert saved.output_contract_results == {}
    assert saved.completed_at == NOW
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_pre_patch_root_replay_has_no_new_activity(monkeypatch):
    admitted = root()
    historical_result = {"old": "family-result"}
    materialize = AsyncMock()
    monkeypatch.setattr(BellLabsRunWorkflow, "run", AsyncMock(return_value=historical_result))
    monkeypatch.setattr(
        mission_run.workflow, "info", lambda: SimpleNamespace(workflow_id=admitted.workflow_id)
    )
    monkeypatch.setattr(mission_run.workflow, "patched", lambda _: False)
    monkeypatch.setattr(mission_run.workflow, "execute_activity", materialize)
    assert await mission_run.MissionRunWorkflow().run(admitted) == historical_result
    materialize.assert_not_awaited()


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
