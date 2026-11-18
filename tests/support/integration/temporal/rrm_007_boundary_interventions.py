"""Builders, constants and fakes that other test files import.

Moved from tests/integration/temporal/test_rrm_007_boundary_interventions.py.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, replace
from typing import Any

from temporalio import activity
from temporalio.client import WorkflowHandle
from temporalio.worker import Replayer

from mission_control.adapters.temporal.boundary_activities import apply_boundary_fact
from mission_control.adapters.temporal.boundary_commands import TemporalBoundaryCommandTransport
from mission_control.adapters.temporal.submission import TemporalWorkflowSubmitter
from mission_control.adapters.temporal.workflow_sandbox import coordinator_workflow_runner
from mission_control.adapters.temporal.workflows.belllabs_run import BellLabsRunWorkflow
from mission_control.adapters.temporal.workflows.goal_directed import GoalDirectedWorkflow
from mission_control.adapters.temporal.workflows.operation import OperationWorkflow
from mission_control.adapters.temporal.workflows.stagegraph import StageGraphWorkflow
from mission_control.application.execution.boundary_interventions import (
    BoundaryCommandApplicationService,
    BoundaryCommandDeliveryService,
    BoundaryInterventionService,
)
from mission_control.application.execution.service import RunControlService
from mission_control.application.programs.service import orchestration_lifecycle_actor
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import GoalDirectedBlueprint
from mission_control.domain.authoring.fixtures import GENERIC_GOAL_DIRECTED
from mission_control.domain.policies.contracts import (
    BudgetApplicability,
    CommandStatus,
    LifecycleCommand,
    PauseAction,
    PauseDecision,
    ResumeAction,
    ResumeDecision,
    RunPhase,
    RunRequest,
    StartAction,
)
from mission_control.domain.programs.contracts import (
    BoundaryLifecycleOutcome,
    BoundaryLifecycleRequest,
    GoalDirectedRunInput,
    LifecycleCommandOutcome,
    LifecycleCommandRequest,
    StageGraphInitializeRequest,
    StageGraphInitializeResult,
)
from mission_control.domain.programs.goal_directed_runtime import (
    GoalOperationReconciliationRequest,
    GoalOperationReconciliationResult,
)
from tests.support.integration.temporal.wp_bp_010_temporal import QUEUE, FakeStageGraphActivities
from tests.support.integration.temporal.wp_bp_020_temporal import FakeGoalDirectedActivities
from tests.support.integration.temporal.wp_bp_020_temporal import _run_input as goal_input
from tests.support.run_control import command, request, service
from tests.support.temporal import wait_heartbeating

GOAL_QUEUE = "wp-bp-020-temporal"
SCOPE = "tenant-1"


class Authority:
    """In-memory run control, the boundary application service and the operator facade.

    ``scope``, ``run_request`` and ``lifecycle_command`` default to the in-memory fixture
    scope and builders; the PostgreSQL acceptance proof passes its disposable database's
    canonical scope and scoped builders instead.
    """

    def __init__(
        self,
        client: Any,
        run_control: RunControlService | None = None,
        *,
        scope: str = SCOPE,
        run_request: Callable[..., RunRequest] = request,
        lifecycle_command: Callable[..., LifecycleCommand] = command,
    ) -> None:
        self.scope = scope
        self.run_request = run_request
        self.lifecycle_command = lifecycle_command
        if run_control is None:
            self.run_control, self.repository = service()
        else:
            self.run_control = run_control
        self.boundary = BoundaryCommandApplicationService(
            self.run_control, orchestration_lifecycle_actor()
        )
        self.facade = BoundaryInterventionService(
            self.run_control,
            BoundaryCommandDeliveryService(
                self.run_control, TemporalBoundaryCommandTransport(client)
            ),
        )

    async def admit(self, request_id: str, *, bounded: dict[str, int] | None = None) -> str:
        """Admit a run; `bounded` turns not-applicable fixture dimensions into bounded ones
        so that a family's iteration reservation (and the resume probe) can be made."""

        run_request = self.run_request(request_id=request_id)
        if bounded:
            envelope = run_request.budget_envelope
            dimensions = tuple(
                item.model_copy(
                    update={
                        "applicability": BudgetApplicability.BOUNDED,
                        "hard_cap": bounded[item.dimension],
                    }
                )
                if item.dimension in bounded
                else item
                for item in envelope.dimensions
            )
            run_request = run_request.model_copy(
                update={"budget_envelope": envelope.model_copy(update={"dimensions": dimensions})}
            )
        admitted = await self.run_control.admit(run_request)
        assert admitted.run_id is not None
        return admitted.run_id

    async def start(self, lifecycle: LifecycleCommandRequest | StageGraphInitializeRequest) -> Any:
        if isinstance(lifecycle, StageGraphInitializeRequest):
            action: Any = StartAction(execution_target=lifecycle.execution_target)
            command_id = f"stagegraph:{lifecycle.run_id}:start"
            correlation_id = lifecycle.correlation_id
        else:
            action = StartAction.model_validate(lifecycle.action)
            command_id = lifecycle.command_id
            correlation_id = lifecycle.correlation_id
        expected_run_version = lifecycle.expected_run_version
        for attempt in range(2):
            result = await self.run_control.execute(
                LifecycleCommand(
                    # RRM-008: like the production start, retried once at the reported
                    # version when an outside command (a cancel) moved the run first.
                    command_id=(
                        command_id
                        if attempt == 0
                        else f"{command_id}:at-version:{expected_run_version}"
                    ),
                    idempotency_issuer=lifecycle.idempotency_issuer,
                    request_scope=lifecycle.request_scope,
                    run_id=lifecycle.run_id,
                    expected_run_version=expected_run_version,
                    actor=orchestration_lifecycle_actor(),
                    action=action,
                    reason="family started",
                    occurred_at=lifecycle.occurred_at,  # type: ignore[arg-type]
                    correlation_id=correlation_id,
                )
            )
            if result.status != CommandStatus.STALE:
                return result
            expected_run_version = result.resulting_run_version
        return result

    async def intervene(self, run_id: str, command_id: str, action: object) -> Any:
        run = await self.run_control.get_run(self.scope, run_id)
        result = await self.facade.execute(
            self.lifecycle_command(run_id, run.version, command_id, action)
        )
        assert result.status == CommandStatus.ACCEPTED, (result.reason_code, result.reason)
        return result

    async def states(self, run_id: str, command_id: str) -> list[str]:
        status = await self.run_control.get_boundary_command(
            self.scope, run_id, "operator", command_id
        )
        return [item.state.value for item in status.receipts] if status is not None else []

    async def run(self, run_id: str) -> Any:
        return await self.run_control.get_run(self.scope, run_id)


# Wall-clock ceilings for the real-time waits below. They only bound a genuine hang: every
# wait returns as soon as its condition holds (about 10 s alone), and the ceilings are sized
# for a heavily loaded host, so an assertion never races the machine's speed.
WAIT_SECONDS = 180.0


async def until(predicate: Callable[[], Awaitable[bool]], *, seconds: float = WAIT_SECONDS) -> None:
    """Poll authority until `predicate` holds (receipts are recorded by activities).

    The deadline is monotonic wall time, not an iteration count, so a slow poll cannot
    shorten the wait.
    """

    deadline = time.monotonic() + seconds
    while True:
        if await predicate():
            return
        if time.monotonic() >= deadline:
            raise AssertionError(f"condition did not hold within {seconds:.0f}s")
        await asyncio.sleep(0.1)


def pause(decision_id: str, scope: set[str] | None = None) -> PauseAction:
    return PauseAction(
        decision=PauseDecision(
            decision_id=decision_id,
            scope=frozenset(scope or {"run"}),
            reason="operator hold",
            authority_ref="authority:lifecycle",
        ),
        runnable_work_remains=False,
    )


def resume(pause_decision_id: str, decision_id: str) -> ResumeAction:
    return ResumeAction(
        decision=ResumeDecision(
            decision_id=decision_id,
            pause_decision_id=pause_decision_id,
            reason="operator release",
            authority_ref="authority:lifecycle",
        )
    )


async def replay(handle: WorkflowHandle[Any, Any], workflows: list[type]) -> int:
    """Replay every run of the execution chain (walking Continue-As-New backwards from the
    latest run); returns the number of runs replayed, always at least one."""

    histories = []
    run_id: str | None = None
    while True:
        run_handle = handle._client.get_workflow_handle(handle.id, run_id=run_id)
        history = await run_handle.fetch_history()
        histories.append(history)
        started = next(
            event.workflow_execution_started_event_attributes
            for event in history.events
            if event.HasField("workflow_execution_started_event_attributes")
        )
        if not started.continued_execution_run_id:
            break
        run_id = started.continued_execution_run_id
    replayer = Replayer(workflows=workflows, workflow_runner=coordinator_workflow_runner())
    for history in reversed(histories):
        await replayer.replay_workflow(history)
    return len(histories)


class GovernedStageGraphActivities(FakeStageGraphActivities):
    """The WP-BP-010 fixture with a real `start` and the boundary application activity."""

    def __init__(self, authority: Authority, *, gate_fast_on_slow: bool = True) -> None:
        super().__init__()
        self.authority = authority
        self.gate_fast_on_slow = gate_fast_on_slow

    @activity.defn(name="stagegraph.initialize")
    async def initialize(self, request: StageGraphInitializeRequest) -> StageGraphInitializeResult:
        result = await self.authority.start(request)
        self.initialized.set()
        return StageGraphInitializeResult(
            accepted=result.status == CommandStatus.ACCEPTED,
            projection=replace(
                request.initial_projection, run_version=result.resulting_run_version
            ),
            reason_code=result.reason_code,
            phase=result.phase.value,
        )

    @activity.defn(name="stagegraph.apply_boundary_command")
    async def apply_boundary_command(
        self, request: BoundaryLifecycleRequest
    ) -> BoundaryLifecycleOutcome:
        return await apply_boundary_fact(self.authority.boundary, request)

    @activity.defn(name="operation.execute")
    async def execute_operation(self, request: dict[str, Any]) -> dict[str, Any]:
        operation_id = str(request["identity"]["operation_id"])
        if ":stage:slow:" in operation_id:
            self.slow_started.set()
            await wait_heartbeating(self.slow_release)
            self.slow_completed.set()
            stage_id = "slow"
        elif ":stage:downstream:" in operation_id:
            self.downstream_started.set()
            stage_id = "downstream"
        else:
            if self.gate_fast_on_slow:
                await wait_heartbeating(self.slow_started)
            stage_id = "fast"
        return {"output_refs": [f"artifact:{stage_id}"]}

    @property
    def functions(self) -> list[object]:
        return [*super().functions, self.apply_boundary_command]


class GovernedGoalActivities(FakeGoalDirectedActivities):
    """The WP-BP-020 fixture with a real `start`, a gated executor and the boundary activity."""

    def __init__(
        self,
        authority: Authority,
        *,
        complete_at_iteration: int = 2,
        no_progress_until_iteration: int = 0,
    ) -> None:
        super().__init__(complete_at_iteration=complete_at_iteration)
        self.authority = authority
        self.release_executor = asyncio.Event()
        self.release_executor.set()
        self.executor_started = asyncio.Event()
        self.final_executor_started = asyncio.Event()
        self._no_progress_until = no_progress_until_iteration

    @activity.defn(name="goaldirected.apply_lifecycle_command")
    async def lifecycle(self, request: LifecycleCommandRequest) -> LifecycleCommandOutcome:
        if request.action["kind"] == "start":
            result = await self.authority.start(request)
            self.lifecycle_kinds.append("start")
            return LifecycleCommandOutcome(
                accepted=result.status == CommandStatus.ACCEPTED,
                resulting_run_version=result.resulting_run_version,
                phase=result.phase.value,
                reason_code=result.reason_code,
            )
        return await super().lifecycle(request)

    @activity.defn(name="goaldirected.apply_boundary_command")
    async def apply_boundary_command(
        self, request: BoundaryLifecycleRequest
    ) -> BoundaryLifecycleOutcome:
        return await apply_boundary_fact(self.authority.boundary, request)

    @activity.defn(name="operation.execute")
    async def execute_operation(self, request: dict[str, Any]) -> dict[str, Any]:
        operation_id = str(request["identity"]["operation_id"])
        if operation_id.endswith("/1/executor"):
            self.executor_started.set()
            await wait_heartbeating(self.release_executor)
        elif operation_id.endswith(f"/{self._complete_at_iteration}/executor"):
            self.final_executor_started.set()
            await wait_heartbeating(self.release_executor)
        self.operation_started.set()
        return {"operation_id": str(request["identity"])}

    @activity.defn(name="goaldirected.reconcile_operation")
    async def reconcile(
        self, request: GoalOperationReconciliationRequest
    ) -> GoalOperationReconciliationResult:
        result = await super().reconcile(request)
        verification = result.verification_result
        if (
            verification is None
            or request.claim.identity.iteration.goal_iteration > self._no_progress_until
        ):
            return result
        draft = replace(verification, progress_made=False, verification_digest="pending")
        payload = asdict(draft)
        payload.pop("verification_digest")
        return result.model_copy(
            update={
                "verification_result": replace(draft, verification_digest=sha256_digest(payload))
            }
        )

    @property
    def functions(self) -> list[object]:
        return [*super().functions, self.apply_boundary_command]


def _goal_blueprint(**overrides: Any) -> GoalDirectedBlueprint:
    values = GENERIC_GOAL_DIRECTED.model_dump(mode="python")
    convergence = values.pop("convergence_policy")
    convergence.update(overrides.pop("convergence_policy", {}))
    return GoalDirectedBlueprint.model_validate(
        {**values, "convergence_policy": convergence, **overrides}
    )


async def _goal_run(
    authority: Authority, request_id: str, blueprint: GoalDirectedBlueprint, **extra: Any
) -> tuple[str, str, GoalDirectedRunInput]:
    run_id = await authority.admit(request_id, bounded={"goal.iterations": 10})
    run_input = replace(goal_input(blueprint=blueprint, run_id=run_id), **extra)
    return run_id, f"family/{run_id}/1", run_input


async def _has_wait(authority: Authority, run_id: str, condition_id: str) -> bool:
    projection = await authority.run(run_id)
    return any(item.condition_id == condition_id for item in projection.active_waits)


async def _state_is(authority: Authority, run_id: str, command_id: str, state: str) -> bool:
    states = await authority.states(run_id, command_id)
    return bool(states) and states[-1] == state


async def _phase_is(authority: Authority, run_id: str, phase: RunPhase) -> bool:
    return (await authority.run(run_id)).phase == phase


ROOT_WORKFLOWS = [BellLabsRunWorkflow, StageGraphWorkflow, GoalDirectedWorkflow, OperationWorkflow]


def _submitter(client: Any) -> TemporalWorkflowSubmitter:
    return TemporalWorkflowSubmitter(
        client, stagegraph_task_queue=QUEUE, goal_directed_task_queue=GOAL_QUEUE
    )
