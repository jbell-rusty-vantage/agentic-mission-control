"""The `mc.mission_run.v1` root saves its typed result before it closes (time-skipping Temporal).

The root is the production `MissionRunWorkflow`; the family is a fixture registered under the
production family workflow name that returns a typed family result at once. The root's
`coordinator.materialize_workflow_result` activity runs the real
`TerminalWorkflowCompletionService` over an in-memory result repository whose first save
commits but answers ambiguously (a lost database acknowledgement). Temporal retries the
activity with the same payload, the restarted service recovers the committed record, and the
root completes only after it.

A root history recorded before the `mc-root-materialize-terminal-result-v1` patch (a root
that returned straight after its family) replays on the production root without scheduling
the new activity.

Replaces the `temporalio.workflow`-patching tests of
tests/unit/coordinator/test_root_result_materialization.py (OVE-238 G4).
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, replace
from typing import Any

import pytest
from temporalio import activity, workflow
from temporalio.client import WorkflowHistory
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from mission_control.adapters.temporal.workflow_sandbox import coordinator_workflow_runner
from mission_control.adapters.temporal.workflows.belllabs_run import BellLabsRunWorkflow
from mission_control.adapters.temporal.workflows.mission_run import MissionRunWorkflow
from mission_control.application.coordinator.coordinator_results import (
    TerminalWorkflowCompletionService,
)
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.fixtures import GENERIC_GOAL_DIRECTED
from mission_control.domain.coordinator.launch import (
    TerminalWorkflowCompletion,
    WorkflowResultRecord,
)
from mission_control.domain.policies.contracts import RunOutcome, RunPhase
from mission_control.domain.programs.contracts import (
    BellLabsRunInput,
    GoalDirectedRunInput,
    GoalDirectedRunResult,
    StageGraphCompletionProposal,
    StageGraphRunResult,
)
from tests.support.integration.temporal.chain_start_idempotent import revision
from tests.support.integration.temporal.w1_family_failure_root import _root as stage_root
from tests.support.temporal import (
    completed_activity_results,
    patch_ids,
    scheduled_activity_inputs,
)
from tests.support.unit.coordinator.coordinator_result_completion import AmbiguousFirstSave
from tests.support.unit.coordinator.root_result_materialization import SCOPE

QUEUE = "w1-family-failure-root"  # the stage root builder's family queue
MATERIALIZE = "coordinator.materialize_workflow_result"
ROOT_RESULT_PATCH = "mc-root-materialize-terminal-result-v1"


def goal_root(run_id: str) -> BellLabsRunInput:
    staged = stage_root(run_id)
    goal = revision(run_id)
    family_input = asdict(
        GoalDirectedRunInput(
            run_id=run_id,
            request_scope=SCOPE,
            effective_configuration_digest=staged.effective_configuration_digest,
            blueprint_digest=sha256_digest(GENERIC_GOAL_DIRECTED),
            blueprint=GENERIC_GOAL_DIRECTED.model_dump(mode="json"),
            envelope_digest=goal.envelope_digest,
            initial_revision=goal,
            workflow_type_digest=staged.workflow_type_digest,
        )
    )
    return replace(staged, family="GoalDirected", family_input=family_input)


def admitted(family: str, run_id: str) -> BellLabsRunInput:
    return stage_root(run_id) if family == "StageGraph" else goal_root(run_id)


@workflow.defn(name="belllabs.stagegraph", sandboxed=False)
class CompletedStageGraph:
    """A StageGraph family that returns its typed result at once."""

    @workflow.run
    async def run(self, family_input: dict[str, Any]) -> StageGraphRunResult:
        return StageGraphRunResult(
            run_id=family_input["run_id"],
            workflow_cycles=0,
            execution_epoch=1,
            family_version=3,
            output_refs={"stage": ("artifact:lineage",)},
            reused_output_refs={},
            schedule_trace=("stage",),
            completion_proposal=StageGraphCompletionProposal(
                required_obligations_accepted=True,
                pending_dependency_ids=(),
                open_producer_liability_ids=(),
                valid_output_refs=("artifact:candidate",),
            ),
        )


@workflow.defn(name="belllabs.goal-directed", sandboxed=False)
class StoppedGoalDirected:
    """A GoalDirected family that returns its typed result at once."""

    @workflow.run
    async def run(self, family_input: dict[str, Any]) -> GoalDirectedRunResult:
        return GoalDirectedRunResult(
            run_id=family_input["run_id"],
            execution_epoch=1,
            status="stopping",
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


@workflow.defn(name="mc.mission_run.v1", sandboxed=False)
class PrePatchMissionRun(BellLabsRunWorkflow):
    """The root as recorded before the materialization patch: it returned its family's
    result straight away (the identity check is unchanged)."""

    @workflow.run
    async def run(self, run_input: BellLabsRunInput) -> Any:
        return await super().run(run_input)


@dataclass(frozen=True)
class _Evidence:
    output_ref: str


@dataclass(frozen=True)
class _Obligation:
    obligation_ref: str


@dataclass(frozen=True)
class _TerminalRun:
    request_scope: str
    run_id: str
    terminal_outcome: RunOutcome
    phase: RunPhase = RunPhase.TERMINAL
    accepted_output_evidence: tuple[_Evidence, ...] = (_Evidence("artifact:accepted"),)
    accepted_obligation_evidence: tuple[_Obligation, ...] = (_Obligation("goal:accepted"),)


class _TerminalRuns:
    """The run projection port: the reducer already recorded each run's terminal outcome."""

    def __init__(self) -> None:
        self.outcomes: dict[str, RunOutcome] = {}

    async def get_run(self, request_scope: str, run_id: str) -> _TerminalRun:
        return _TerminalRun(request_scope, run_id, self.outcomes[run_id])


class _Materializer:
    """`coordinator.materialize_workflow_result` over the real completion service; every
    attempt builds the service again, as a restarted worker would."""

    def __init__(self) -> None:
        self.runs = _TerminalRuns()
        self.results = AmbiguousFirstSave()
        self.attempts: list[tuple[int, TerminalWorkflowCompletion]] = []

    @activity.defn(name=MATERIALIZE)
    async def materialize(self, completion: TerminalWorkflowCompletion) -> WorkflowResultRecord:
        self.attempts.append((activity.info().attempt, completion))
        service = TerminalWorkflowCompletionService(runs=self.runs, results=self.results)
        return await service.complete(completion)


def _workers(env: WorkflowEnvironment, root: type, materializer: _Materializer) -> Worker:
    return Worker(
        env.client,
        task_queue=QUEUE,
        workflows=[root, CompletedStageGraph, StoppedGoalDirected],
        workflow_runner=coordinator_workflow_runner(),
        activities=[materializer.materialize],
    )


async def _replay(history: WorkflowHistory) -> None:
    await Replayer(
        workflows=[MissionRunWorkflow, CompletedStageGraph, StoppedGoalDirected],
        workflow_runner=coordinator_workflow_runner(),
    ).replay_workflow(history)


@pytest.mark.asyncio
@pytest.mark.parametrize("family", ["StageGraph", "GoalDirected"])
async def test_root_waits_for_persisted_result_with_retryable_same_payload(
    workflow_env: WorkflowEnvironment, family: str
) -> None:
    materializer = _Materializer()
    async with _workers(workflow_env, MissionRunWorkflow, materializer):
        for outcome in RunOutcome:
            # A fresh ambiguous first save per run.
            materializer.results = AmbiguousFirstSave()
            materializer.attempts.clear()
            run_input = admitted(family, f"run-root-result-{family}-{outcome.value}")
            materializer.runs.outcomes[run_input.run_id] = outcome
            handle = await workflow_env.client.start_workflow(
                MissionRunWorkflow.run, run_input, id=run_input.workflow_id, task_queue=QUEUE
            )
            result = await asyncio.wait_for(handle.result(), timeout=60)
            history = await handle.fetch_history()

            # The root returned its family's result, after the durable record was saved.
            assert result["run_id"] == run_input.run_id
            saved = await materializer.results.get(SCOPE, SCOPE, run_input.run_id)
            assert saved is not None
            assert saved.terminal_outcome == outcome
            assert saved.artifact_refs == ("artifact:accepted",)
            assert saved.evidence_refs == ("goal:accepted",)
            assert saved.output_contract_results == {}

            # One scheduled activity on the family queue with unlimited retries: the
            # ambiguous first attempt was retried with the identical payload.
            (scheduled,) = scheduled_activity_inputs(history, MATERIALIZE)
            assert scheduled["terminal_outcome"] is None
            assert [attempt for attempt, _ in materializer.attempts] == [1, 2]
            first, second = (completion for _, completion in materializer.attempts)
            assert first == second
            assert saved.completed_at == first.completed_at
            (record,) = completed_activity_results(history, MATERIALIZE)
            assert record["run_id"] == run_input.run_id
            event = next(
                item.activity_task_scheduled_event_attributes
                for item in history.events
                if item.HasField("activity_task_scheduled_event_attributes")
            )
            assert event.task_queue.name == run_input.family_task_queue
            assert event.retry_policy.maximum_attempts == 0
            assert ROOT_RESULT_PATCH in patch_ids(history)
            await _replay(history)


@pytest.mark.asyncio
async def test_pre_patch_root_replay_has_no_new_activity(
    workflow_env: WorkflowEnvironment,
) -> None:
    materializer = _Materializer()
    run_input = admitted("StageGraph", "run-root-result-pre-patch")
    async with _workers(workflow_env, PrePatchMissionRun, materializer):
        handle = await workflow_env.client.start_workflow(
            PrePatchMissionRun.run, run_input, id=run_input.workflow_id, task_queue=QUEUE
        )
        result = await asyncio.wait_for(handle.result(), timeout=60)
        history = await handle.fetch_history()

    assert result["run_id"] == run_input.run_id
    assert ROOT_RESULT_PATCH not in patch_ids(history), "recorded before the patch"
    assert scheduled_activity_inputs(history, MATERIALIZE) == []
    assert materializer.attempts == []
    # The production root replays the old history: it schedules no new activity (a new
    # command would fail the replay as nondeterministic).
    await _replay(history)
