"""Registered Managed budget activity over real application services and memory ports.

This proves the registered activity/service/provider join, without Temporal server,
PostgreSQL, deployment factory execution, or native provider qualification. Factory
construction of these services is a separately inspected static link.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from typing import Any

from temporalio.testing import ActivityEnvironment
from tests.fixtures.lane_turns import DIGEST, ScriptedSessionLane, lane_stack
from tests.fixtures.managed_lane import managed_binding, managed_operation
from tests.unit.harness.test_managed_budget_controls import NOW, Approvals, Authority, Provider

from mission_control.adapters.anthropic_managed.describe import CLAUDE_MANAGED_DESCRIBE
from mission_control.adapters.temporal.operation_activities import OperationExecutionActivities
from mission_control.application.execution.harness.budget_controls import BudgetControlService
from mission_control.application.execution.harness.lane_turns import (
    LaneExecutionIdentity,
    LaneTurnService,
)
from mission_control.application.execution.harness.sessions import WorkerSessionManager
from mission_control.application.execution.harness.state import (
    InMemoryLaneExecutionStateStore,
    LaneExecutionUpdate,
)
from mission_control.application.execution.stop_fence import InMemoryStopFenceRepository
from mission_control.application.resolution.registries import LaneRegistry
from mission_control.domain.execution.budget_controls import (
    BudgetControlRecord,
    LaneBudgetControlRequest,
)
from mission_control.domain.policies.contracts import (
    ManagedBudgetGate,
    PauseAction,
    PauseDecision,
    ResumeAction,
    ResumeDecision,
)


class ControlledManagedLane(ScriptedSessionLane, Provider):
    """Native session boundary fake; the activity and application services stay real."""

    def __init__(self) -> None:
        ScriptedSessionLane.__init__(self, describe_matrix=CLAUDE_MANAGED_DESCRIBE)
        Provider.__init__(self)


def accept(authority: Authority, command_id: str, *, resume: str | None = None) -> None:
    gate = ManagedBudgetGate(
        hold_command_id=resume,
        hold_command_issuer="operator" if resume else None,
    )
    action = (
        ResumeAction(
            decision=ResumeDecision(
                decision_id=command_id,
                pause_decision_id=resume,
                reason="fixture resume",
                authority_ref="fixture authority",
                budget_gate=gate,
            )
        )
        if resume
        else PauseAction(
            decision=PauseDecision(
                decision_id=command_id,
                scope=frozenset({"run"}),
                reason="fixture hold",
                authority_ref="fixture authority",
                budget_gate=gate,
            ),
            runnable_work_remains=False,
        )
    )
    authority.commands[command_id] = SimpleNamespace(
        kind="resume" if resume else "pause",
        action=action,
        payload_digest=DIGEST,
        target_sequence=len(authority.commands) + 1,
    )


async def composed_stack(*, current_owner: str = "worker-a") -> SimpleNamespace:
    operation = managed_operation(managed_binding(DIGEST))
    identity = LaneExecutionIdentity.of(operation, "claude_managed", 1)
    states = InMemoryLaneExecutionStateStore()
    await states.record(
        operation.request_scope,
        identity.harness_execution_id,
        LaneExecutionUpdate(native_session_ref="session-1", native_turn_ref="turn-1"),
    )
    await states.claim_owner(
        operation.request_scope,
        identity.harness_execution_id,
        owner_ref=current_owner,
        generation=1,
        now=NOW,
        lease=timedelta(seconds=30),
    )
    authority = Authority()
    provider = ControlledManagedLane()
    fences = InMemoryStopFenceRepository()
    budget_controls = BudgetControlService(
        states=states, authority=authority, approvals=Approvals(), fences=fences
    )
    ports = lane_stack(provider, operation=operation)
    boundary = ports.boundary

    def compose_activity() -> Any:
        turns = LaneTurnService(
            lanes=LaneRegistry([provider], allow_unqualified=True),
            boundary=boundary,
            frames=ports.frames,
            states=states,
            sessions=WorkerSessionManager(owner_ref="worker-a"),
            clock=lambda: NOW,
            fences=fences,
            budget_controls=budget_controls,
        )
        activities = OperationExecutionActivities(
            boundary, lane_turns=turns, worker_identity="fixture-worker"
        )
        registered = {
            getattr(fn, "__temporal_activity_definition").name: fn
            for fn in activities.lane_activities()
        }
        return registered["lane.budget_control"]

    return SimpleNamespace(
        operation=operation,
        provider=provider,
        authority=authority,
        activity=compose_activity,
        states=states,
        identity=identity,
    )


async def invoke(stack: SimpleNamespace, command_id: str) -> BudgetControlRecord:
    payload = LaneBudgetControlRequest(
        operation=stack.operation, generation=1, command_id=command_id, command_issuer="operator"
    )
    result = await ActivityEnvironment().run(stack.activity(), payload.model_dump(mode="json"))
    return BudgetControlRecord.model_validate(result)


async def test_registered_budget_activity_hold_replay_boundary_and_resume() -> None:
    stack = await composed_stack()
    accept(stack.authority, "hold-1")
    hold = await invoke(stack, "hold-1")
    assert hold.phase == "cap_confirmed" and not hold.applied
    assert (stack.provider.cap, stack.provider.posts) == (4, [4])

    # Rebuild the registered activity with a fresh worker session manager, preserving
    # the in-memory journal. A replay must not repeat the native cap write.
    replay = await invoke(stack, "hold-1")
    assert replay.phase == "cap_confirmed" and stack.provider.posts == [4]
    stack.provider.boundary, stack.provider.evidence = True, "fresh-budget-boundary"
    observed = await invoke(stack, "hold-1")
    assert observed.applied and observed.evidence == "fresh-budget-boundary"

    accept(stack.authority, "resume-1", resume="hold-1")
    resumed = await invoke(stack, "resume-1")
    assert resumed.applied and resumed.hold_key == hold.key
    assert (stack.provider.cap, stack.provider.posts) == (90, [4, 90])
    await invoke(stack, "resume-1")
    assert stack.provider.posts == [4, 90]
    assert not stack.provider.sends and not stack.provider.cancels


async def test_registered_budget_activity_other_live_owner_only_enqueues() -> None:
    stack = await composed_stack(current_owner="other-worker")
    accept(stack.authority, "hold-1")
    receipt = await invoke(stack, "hold-1")
    assert receipt.phase == "queued" and not receipt.applied
    assert stack.provider.cap == 90 and not stack.provider.posts
