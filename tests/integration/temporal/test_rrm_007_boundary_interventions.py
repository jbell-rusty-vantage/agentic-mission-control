"""RRM-007: governed boundary interventions at both family boundaries (time-skipping Temporal).

Run control (in memory here; PostgreSQL in the acceptance proof) accepts every command and
keeps the receipt ledger; the Temporal transport delivers through the family's
`deliver_boundary_command` Update; the family applies at its boundary through its
`apply_boundary_command` activity, which records `applied` atomically with the phase effect.

Covered: REQ-BP-SG-009 (a declared wait is inspectable while held, released only through
the facade, and stays satisfied across Continue-As-New; a raw signal releases nothing),
REQ-CP-RUN-004 (scoped pause leaves unrelated work admissible; the aggregate phase stays
accurate), REQ-BP-GD-011 (command and policy pauses are durable, never a failure; resume
continues the recorded frontier; forced Continue-As-New carries the paused state),
REQ-CP-EXEC-006/007 (delivered is not applied; duplicates and stale targets are
acknowledged without a second application), and replay of every captured history.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

import pytest
from temporalio import activity
from temporalio.client import WorkflowHandle
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from mission_control.adapters.temporal.workflow_sandbox import coordinator_workflow_runner
from mission_control.adapters.temporal.workflows.belllabs_run import BellLabsRunWorkflow
from mission_control.adapters.temporal.workflows.goal_directed import GoalDirectedWorkflow
from mission_control.adapters.temporal.workflows.operation import OperationWorkflow
from mission_control.adapters.temporal.workflows.stagegraph import (
    StageGraphWorkflow,
    wait_condition_id,
)
from mission_control.domain.coordinator.launch import BlueprintFamily
from mission_control.domain.policies.contracts import (
    CancelAction,
    RunPhase,
    SatisfyWaitAction,
)
from mission_control.domain.programs.contracts import (
    BoundaryCommandDelivery,
    StageGraphCompletionActivityRequest,
    StageGraphCompletionActivityResult,
)
from tests.support.integration.temporal.rrm_007_boundary_interventions import (
    GOAL_QUEUE,
    ROOT_WORKFLOWS,
    SCOPE,
    WAIT_SECONDS,
    Authority,
    GovernedGoalActivities,
    GovernedStageGraphActivities,
    _goal_blueprint,
    _goal_run,
    _has_wait,
    _phase_is,
    _state_is,
    _submitter,
    pause,
    replay,
    resume,
    until,
)
from tests.support.integration.temporal.wp_bp_010_temporal import (
    QUEUE,
    _blueprint,
)
from tests.support.integration.temporal.wp_bp_010_temporal import _run_input as stage_input

# --- Authority and transport ---------------------------------------------------------------


RESULT_SECONDS = 300.0


# --- StageGraph ------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stagegraph_declared_wait_is_governed_and_survives_continue_as_new(
    workflow_env: WorkflowEnvironment,
) -> None:
    authority = Authority(workflow_env.client)
    activities = GovernedStageGraphActivities(authority)
    run_id = await authority.admit("rrm-007-stagegraph-wait")
    workflow_id = f"family/{run_id}/1"
    run_input = replace(
        stage_input(_blueprint(workflow_wait=True)), run_id=run_id, force_continue_as_new=True
    )
    condition_id = wait_condition_id("release-workflow")
    async with Worker(
        workflow_env.client,
        task_queue=QUEUE,
        workflows=[StageGraphWorkflow, OperationWorkflow],
        workflow_runner=coordinator_workflow_runner(),
        activities=activities.functions,
    ):
        handle = await workflow_env.client.start_workflow(
            StageGraphWorkflow.run, run_input, id=workflow_id, task_queue=QUEUE
        )
        # REQ-BP-SG-009: the held wait is declared to authority and inspectable.
        await until(lambda: _has_wait(authority, run_id, condition_id), seconds=WAIT_SECONDS)
        projection = await authority.run(run_id)
        assert projection.phase == RunPhase.WAITING
        assert projection.execution_target is not None
        assert projection.execution_target.family_workflow_id == workflow_id
        assert projection.execution_target.root_workflow_id is None

        # REQ-CP-EXEC-007: a raw signal is not a governed release path.
        await handle.signal(StageGraphWorkflow.satisfy_wait, "release-workflow")
        assert await handle.query(StageGraphWorkflow.satisfied_waits) == ()
        assert activities.admission_order == []

        released = await authority.intervene(
            run_id,
            "release",
            SatisfyWaitAction(
                condition_id=condition_id, verification_evidence_ref="evidence:operator"
            ),
        )
        assert released.reason_code == "accepted_pending_application"
        assert released.phase == RunPhase.WAITING, "accepted is not applied"
        await until(lambda: _state_is(authority, run_id, "release", "applied"))
        assert await authority.states(run_id, "release") == [
            "accepted",
            "delivered",
            "applied",
        ]
        projection = await authority.run(run_id)
        assert projection.active_waits == () and projection.phase == RunPhase.ACTIVE

        await asyncio.wait_for(activities.downstream_started.wait(), timeout=WAIT_SECONDS)
        activities.slow_release.set()
        result = await handle.result()
        final_state = await handle.query(StageGraphWorkflow.boundary_state)
        history = await handle.fetch_history()

    # REQ-CP-EXEC-011: the wait satisfied before Continue-As-New stayed satisfied after
    # it (the continued run admitted every stage), and the applied cache travelled.
    assert sorted(activities.admission_order) == ["downstream", "fast", "slow"]
    assert result.output_refs["downstream"] == ("artifact:downstream",)
    assert final_state["technical_segment"] == 2
    assert final_state["satisfied_wait_ids"] == ["release-workflow"]
    assert final_state["applied_command_ids"] == ["release"]
    assert any(
        event.HasField("workflow_execution_continued_as_new_event_attributes")
        for event in (
            await workflow_env.client.get_workflow_handle(
                workflow_id, run_id=handle.first_execution_run_id
            ).fetch_history()
        ).events
    )
    assert await replay(handle, [StageGraphWorkflow, OperationWorkflow]) == 2
    del history


@pytest.mark.asyncio
async def test_stagegraph_scoped_pause_leaves_unrelated_work_admissible(
    workflow_env: WorkflowEnvironment,
) -> None:
    """REQ-CP-RUN-004 / REQ-BP-SG-009: a pause on one stage never blocks its siblings; the
    aggregate phase is `paused` only while no admissible work remains."""

    authority = Authority(workflow_env.client)
    activities = GovernedStageGraphActivities(authority, gate_fast_on_slow=False)
    activities.slow_release.set()
    run_id = await authority.admit("rrm-007-stagegraph-pause")
    workflow_id = f"family/{run_id}/1"
    run_input = replace(stage_input(_blueprint(workflow_wait=True)), run_id=run_id)
    condition_id = wait_condition_id("release-workflow")
    async with Worker(
        workflow_env.client,
        task_queue=QUEUE,
        workflows=[StageGraphWorkflow, OperationWorkflow],
        workflow_runner=coordinator_workflow_runner(),
        activities=activities.functions,
    ):
        handle = await workflow_env.client.start_workflow(
            StageGraphWorkflow.run, run_input, id=workflow_id, task_queue=QUEUE
        )
        await until(lambda: _has_wait(authority, run_id, condition_id))
        # Pause the slow stage while everything is held: nothing is admissible.
        await authority.intervene(run_id, "pause-slow", pause("hold-slow", {"stage:slow"}))
        await until(lambda: _state_is(authority, run_id, "pause-slow", "applied"))
        projection = await authority.run(run_id)
        assert [item.decision_id for item in projection.active_pauses] == ["hold-slow"]
        assert projection.phase == RunPhase.PAUSED

        await authority.intervene(
            run_id,
            "release",
            SatisfyWaitAction(
                condition_id=condition_id, verification_evidence_ref="evidence:operator"
            ),
        )
        await until(lambda: _state_is(authority, run_id, "release", "applied"))
        # The release's own transition moved the run back to `active` (the unrelated
        # stages were admissible); the phase may already have moved on since.
        release_status = await authority.run_control.get_boundary_command(
            SCOPE, run_id, "operator", "release"
        )
        assert release_status is not None
        release_version = release_status.receipts[-1].applied_run_version
        transitions = await authority.run_control.list_transitions(SCOPE, run_id)
        assert [
            item.resulting_phase
            for item in transitions
            if item.resulting_version == release_version
        ] == [RunPhase.ACTIVE]
        # The unrelated stages run to completion while the paused stage is held.
        await asyncio.wait_for(activities.downstream_started.wait(), timeout=WAIT_SECONDS)
        await until(lambda: _phase_is(authority, run_id, RunPhase.PAUSED))
        assert activities.admission_order == ["fast", "downstream"]
        assert not activities.slow_started.is_set()
        runtime = await handle.query(StageGraphWorkflow.runtime_state)
        assert (runtime["active_count"], runtime["frontier_count"]) == (0, 0)

        await authority.intervene(run_id, "resume-slow", resume("hold-slow", "release-slow"))
        await until(lambda: _state_is(authority, run_id, "resume-slow", "applied"))
        result = await handle.result()
        history = await handle.fetch_history()

    assert activities.admission_order == ["fast", "downstream", "slow"]
    assert activities.slow_completed.is_set()
    assert result.completion_proposal.can_terminalize
    projection = await authority.run(run_id)
    assert projection.active_pauses == ()
    assert [item.decision_id for item in projection.resume_decisions] == ["release-slow"]
    for command_id in ("pause-slow", "release", "resume-slow"):
        assert await authority.states(run_id, command_id) == [
            "accepted",
            "delivered",
            "applied",
        ]
    await Replayer(
        workflows=[StageGraphWorkflow, OperationWorkflow],
        workflow_runner=coordinator_workflow_runner(),
    ).replay_workflow(history)


# --- GoalDirected ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_goal_directed_command_pause_is_durable_and_resume_continues_the_frontier(
    workflow_env: WorkflowEnvironment,
) -> None:
    authority = Authority(workflow_env.client)
    activities = GovernedGoalActivities(authority, complete_at_iteration=2)
    activities.release_executor.clear()
    blueprint = _goal_blueprint(max_iterations=3)
    run_id, workflow_id, run_input = await _goal_run(authority, "rrm-007-goal-pause", blueprint)
    async with Worker(
        workflow_env.client,
        task_queue=GOAL_QUEUE,
        workflows=[GoalDirectedWorkflow, OperationWorkflow],
        workflow_runner=coordinator_workflow_runner(),
        activities=activities.functions,
    ):
        handle = await workflow_env.client.start_workflow(
            GoalDirectedWorkflow.run, run_input, id=workflow_id, task_queue=GOAL_QUEUE
        )
        await asyncio.wait_for(activities.executor_started.wait(), timeout=WAIT_SECONDS)
        # REQ-BP-GD-011: a pause requested while a unit is active is delivered now and
        # applied only at the next iteration boundary.
        await authority.intervene(run_id, "pause", pause("hold-run"))
        await until(lambda: _state_is(authority, run_id, "pause", "delivered"))
        assert await authority.states(run_id, "pause") == ["accepted", "delivered"]
        assert (await authority.run(run_id)).phase == RunPhase.ACTIVE
        activities.release_executor.set()
        await until(lambda: _state_is(authority, run_id, "pause", "applied"))
        projection = await authority.run(run_id)
        assert projection.phase == RunPhase.PAUSED
        assert [item.decision_id for item in projection.active_pauses] == ["hold-run"]
        assert activities.prepared_roles == ["executor", "verifier"], "quiesced at the boundary"
        description = await handle.describe()
        assert description.status is not None and description.status.name == "RUNNING"
        state = await handle.query(GoalDirectedWorkflow.boundary_state)
        paused = state["paused"]
        assert (
            paused["next_goal_iteration"],
            paused["active_revision_id"],
            paused["session_generation"],
            paused["held_reservation_ids"],
            paused["released_reservation_ids"],
        ) == (2, "goal-revision:1", 1, [], [])
        assert paused["next_iteration_reservation"] == dict(blueprint.iteration_reservation)
        status = await authority.run_control.get_boundary_command(
            SCOPE, run_id, "operator", "pause"
        )
        assert status is not None
        assert status.receipts[-1].boundary_state["next_goal_iteration"] == 2
        assert status.receipts[-1].boundary_state["held_reservation_ids"] == ["baseline"]

        # REQ-CP-EXEC-006: redelivery and stale deliveries never apply twice.
        delivery = BoundaryCommandDelivery(
            command_id="pause",
            kind="pause",
            target_sequence=1,
            execution_epoch=1,
            execution_generation=1,
            accepted_run_version=2,
            payload=pause("hold-run").model_dump(mode="json"),
            payload_digest=status.command.payload_digest,
            idempotency_issuer="operator",
        )
        duplicate = await handle.execute_update(
            GoalDirectedWorkflow.deliver_boundary_command, delivery
        )
        assert duplicate.status == "duplicate"
        stale = await handle.execute_update(
            GoalDirectedWorkflow.deliver_boundary_command,
            replace(delivery, command_id="pause-gen-2", execution_generation=2),
        )
        assert stale.status == "stale_generation"
        foreign = await handle.execute_update(
            GoalDirectedWorkflow.deliver_boundary_command,
            replace(delivery, command_id="pause-epoch-2", execution_epoch=2),
        )
        assert foreign.status == "stale_target"
        assert await authority.facade.redeliver(SCOPE, run_id) == ()

        # F7: an out-of-order sequence is a transient gap at the family.
        gap = await handle.execute_update(
            GoalDirectedWorkflow.deliver_boundary_command,
            replace(delivery, command_id="too-early", target_sequence=5),
        )
        assert gap.status == "gap"

        # Gate the final executor before resuming, so the late pause below is delivered
        # while the final unit runs.
        activities.release_executor.clear()
        await authority.intervene(run_id, "resume", resume("hold-run", "release-run"))
        await until(lambda: _state_is(authority, run_id, "resume", "applied"))
        # F1: a pause delivered during the final iteration is closed `not_applicable` by
        # the boundary before it terminalizes, never left `delivered`.
        await asyncio.wait_for(activities.final_executor_started.wait(), timeout=WAIT_SECONDS)
        await authority.intervene(run_id, "late-pause", pause("hold-late"))
        await until(lambda: _state_is(authority, run_id, "late-pause", "delivered"))
        assert (await authority.run(run_id)).phase == RunPhase.ACTIVE
        activities.release_executor.set()
        result = await asyncio.wait_for(handle.result(), timeout=RESULT_SECONDS)
        final_state = await handle.query(GoalDirectedWorkflow.boundary_state)
        history = await handle.fetch_history()
        late = await authority.run_control.get_boundary_command(
            SCOPE, run_id, "operator", "late-pause"
        )
        assert late is not None
        assert [item.state.value for item in late.receipts] == [
            "accepted",
            "delivered",
            "rejected",
        ]
        assert late.receipts[-1].rejection_reason == "not_applicable"
        # F1: a command accepted after the family closed is a terminal `stale_target`.
        await authority.intervene(run_id, "after-close", pause("hold-after"))
        after = await authority.run_control.get_boundary_command(
            SCOPE, run_id, "operator", "after-close"
        )
        assert after is not None
        assert [item.state.value for item in after.receipts] == ["accepted", "rejected"]
        assert after.receipts[-1].rejection_reason == "stale_target"

    assert result.convergence_proposal.action == "complete"
    assert result.goal_iterations == 2
    assert activities.prepared_roles == ["executor", "verifier", "executor", "verifier"]
    assert result.verification_results[-1].executor_identity.iteration.goal_iteration == 2
    assert result.active_revision_id == "goal-revision:1"
    assert await authority.states(run_id, "resume") == ["accepted", "delivered", "applied"]
    projection = await authority.run(run_id)
    assert projection.active_pauses == () and projection.phase == RunPhase.ACTIVE
    assert final_state["paused"] is None
    assert final_state["applied_command_ids"] == ["late-pause", "pause", "resume"]
    await Replayer(
        workflows=[GoalDirectedWorkflow, OperationWorkflow],
        workflow_runner=coordinator_workflow_runner(),
    ).replay_workflow(history)


@pytest.mark.asyncio
async def test_goal_directed_policy_pause_is_durable_across_forced_continue_as_new(
    workflow_env: WorkflowEnvironment,
) -> None:
    """REQ-BP-GD-011: a policy-selected pause enters run control as a pause bound to the
    convergence decision, waits without failing, survives forced Continue-As-New and
    resumes at the recorded next iteration with the same revision."""

    authority = Authority(workflow_env.client)
    activities = GovernedGoalActivities(
        authority, complete_at_iteration=2, no_progress_until_iteration=1
    )
    blueprint = _goal_blueprint(
        max_iterations=3,
        convergence_policy={"no_progress_action": "pause", "max_no_progress_iterations": 1},
    )
    run_id, workflow_id, run_input = await _goal_run(
        authority, "rrm-007-goal-policy-pause", blueprint, force_continue_as_new=True
    )
    async with Worker(
        workflow_env.client,
        task_queue=GOAL_QUEUE,
        workflows=[GoalDirectedWorkflow, OperationWorkflow],
        workflow_runner=coordinator_workflow_runner(),
        activities=activities.functions,
    ):
        handle = await workflow_env.client.start_workflow(
            GoalDirectedWorkflow.run, run_input, id=workflow_id, task_queue=GOAL_QUEUE
        )
        await until(lambda: _phase_is(authority, run_id, RunPhase.PAUSED))
        projection = await authority.run(run_id)
        policy_pause = projection.active_pauses[0]
        assert policy_pause.decision_id.startswith("goal-policy-pause:")
        assert "convergence policy selected pause: no_progress" in policy_pause.reason
        commands = await authority.run_control.list_boundary_commands(SCOPE, run_id)
        assert [(item.command.kind, item.state.value) for item in commands] == [
            ("pause", "applied")
        ]
        # Forced Continue-As-New while paused: the paused state continues.
        await until(lambda: _segment_is(handle, 2))
        state = await handle.query(GoalDirectedWorkflow.boundary_state)
        assert state["paused"]["pause_decision_id"] == policy_pause.decision_id
        assert state["paused"]["next_goal_iteration"] == 2
        description = await handle.describe()
        assert description.status is not None and description.status.name == "RUNNING"

        await authority.intervene(
            run_id, "resume-policy", resume(policy_pause.decision_id, "operator-release")
        )
        await until(lambda: _state_is(authority, run_id, "resume-policy", "applied"))
        result = await asyncio.wait_for(handle.result(), timeout=RESULT_SECONDS)

    assert result.convergence_proposal.action == "complete"
    assert result.goal_iterations == 2
    assert result.active_revision_id == "goal-revision:1"
    assert activities.prepared_roles == ["executor", "verifier", "executor", "verifier"]
    assert "terminalize" in activities.lifecycle_kinds
    assert await replay(handle, [GoalDirectedWorkflow, OperationWorkflow]) == 2


# --- Polling predicates ------------------------------------------------------------------------


async def _segment_is(handle: WorkflowHandle[Any, Any], segment: int) -> bool:
    try:
        state = await handle.query(GoalDirectedWorkflow.boundary_state)
    except Exception:
        return False
    return bool(state["technical_segment"] == segment and state["paused"] is not None)


# --- Routed through a real root (review N1) ---------------------------------------------------


@pytest.mark.asyncio
async def test_policy_pause_then_operator_resume_through_the_root_is_applied(
    workflow_env: WorkflowEnvironment,
) -> None:
    """N1: a self-issued policy pause takes no place in the root's sequence space, so the
    operator's resume (root sequence 1) is routed root-first and applied."""

    authority = Authority(workflow_env.client)
    activities = GovernedGoalActivities(
        authority, complete_at_iteration=2, no_progress_until_iteration=1
    )
    blueprint = _goal_blueprint(
        max_iterations=3,
        convergence_policy={"no_progress_action": "pause", "max_no_progress_iterations": 1},
    )
    run_id, family_id, run_input = await _goal_run(
        authority, "rrm-007-root-policy-pause", blueprint
    )
    async with Worker(
        workflow_env.client,
        task_queue=GOAL_QUEUE,
        workflows=ROOT_WORKFLOWS,
        workflow_runner=coordinator_workflow_runner(),
        activities=activities.functions,
    ):
        submitted = await _submitter(workflow_env.client).submit(
            run_input, workflow_id="ignored", blueprint_family=BlueprintFamily.GOAL_DIRECTED
        )
        root = workflow_env.client.get_workflow_handle(submitted.workflow_id)
        await until(lambda: _phase_is(authority, run_id, RunPhase.PAUSED))
        projection = await authority.run(run_id)
        assert projection.execution_target is not None
        assert projection.execution_target.root_workflow_id == submitted.workflow_id
        [policy] = await authority.run_control.list_boundary_commands(SCOPE, run_id)
        assert policy.command.kind == "pause" and policy.state.value == "applied"
        assert policy.command.target.sequence_space == f"boundary:{family_id}"
        assert policy.command.target_sequence == 1, "sequenced in its own space"

        await authority.intervene(
            run_id, "resume", resume(projection.active_pauses[0].decision_id, "release")
        )
        await until(lambda: _state_is(authority, run_id, "resume", "applied"))
        resumed = await authority.run_control.get_boundary_command(
            SCOPE, run_id, "operator", "resume"
        )
        assert resumed is not None
        assert resumed.command.target.sequence_space == "execution"
        assert resumed.command.target_sequence == 1, "first command in the root's space"
        continuity = await root.query(BellLabsRunWorkflow.continuity)
        assert [
            (item.message_id, item.sequence, item.status) for item in continuity.message_receipts
        ] == [("resume", 1, "accepted")]
        result = await asyncio.wait_for(root.result(), timeout=RESULT_SECONDS)
    assert result["convergence_proposal"]["action"] == "complete"
    assert result["goal_iterations"] == 2
    assert await authority.facade.redeliver(SCOPE, run_id) == ()


@pytest.mark.asyncio
async def test_cancel_never_blocks_a_later_command_at_the_root(
    workflow_env: WorkflowEnvironment,
) -> None:
    """N1: a cancel is sequenced in its own space, so a later operator command is still the
    root's sequence 1 and is delivered. RRM-008: the cancel itself is delivered root-first
    (`accepted`, `delivered`) and the family runs its cancellation saga; the later release is
    delivered but never applied (nothing is admitted after the cancel)."""

    authority = Authority(workflow_env.client)
    activities = _HoldingCompletionActivities(authority)
    run_id = await authority.admit("rrm-007-root-cancel")
    run_input = replace(stage_input(_blueprint(workflow_wait=True)), run_id=run_id)
    condition_id = wait_condition_id("release-workflow")
    async with Worker(
        workflow_env.client,
        task_queue=QUEUE,
        workflows=ROOT_WORKFLOWS,
        workflow_runner=coordinator_workflow_runner(),
        activities=activities.functions,
    ):
        submitted = await _submitter(workflow_env.client).submit(
            run_input, workflow_id="ignored", blueprint_family=BlueprintFamily.STAGE_GRAPH
        )
        root = workflow_env.client.get_workflow_handle(submitted.workflow_id)
        await until(lambda: _has_wait(authority, run_id, condition_id))
        cancelled = await authority.intervene(run_id, "cancel", CancelAction())
        assert cancelled.phase == RunPhase.CANCELLING
        cancel = await authority.run_control.get_boundary_command(
            SCOPE, run_id, "operator", "cancel"
        )
        assert cancel is not None
        assert (cancel.command.target.sequence_space, cancel.command.target_sequence) == (
            "cancel",
            1,
        )
        await until(lambda: _state_is(authority, run_id, "cancel", "delivered"))

        await authority.intervene(
            run_id,
            "release",
            SatisfyWaitAction(
                condition_id=condition_id, verification_evidence_ref="evidence:operator"
            ),
        )
        await until(lambda: _state_is(authority, run_id, "release", "delivered"))
        release = await authority.run_control.get_boundary_command(
            SCOPE, run_id, "operator", "release"
        )
        assert release is not None and release.command.target_sequence == 1
        # Delivered to the cancelling family (its Update handler acknowledges while the
        # completion activity runs); a family at its boundary rejects it `superseded`
        # and run control's terminal closure rejects it `terminal_run` (RRM-008 suites).
        assert [item.state.value for item in release.receipts] == ["accepted", "delivered"]
        continuity = await root.query(BellLabsRunWorkflow.continuity)
        assert [
            (item.message_id, item.sequence, item.status) for item in continuity.message_receipts
        ] == [("release", 1, "accepted")]
        assert [
            (item.command_id, item.status)
            for item in await root.query(BellLabsRunWorkflow.cancel_receipts)
        ] == [("cancel", "delivered")]
        activities.complete_release.set()
        result = await asyncio.wait_for(root.result(), timeout=RESULT_SECONDS)
    assert result["completion_proposal"]["cancelled"] is True
    assert activities.admission_order == [], "nothing is admitted after the cancel"


class _HoldingCompletionActivities(GovernedStageGraphActivities):
    """The governed StageGraph fixture whose completion waits for the test's release, so
    the family is still running when a later command is delivered to it."""

    def __init__(self, authority: Authority) -> None:
        super().__init__(authority)
        self.complete_release = asyncio.Event()

    @activity.defn(name="stagegraph.complete")
    async def complete(
        self, request: StageGraphCompletionActivityRequest
    ) -> StageGraphCompletionActivityResult:
        await asyncio.wait_for(self.complete_release.wait(), timeout=WAIT_SECONDS)
        return await super().complete(request)
