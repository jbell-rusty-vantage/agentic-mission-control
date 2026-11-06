"""OVE-176 / WI-13 on real Temporal (test server): a Stage Graph stage hosting a nested Stage Graph
body runs it as a real child run (its own `mc.mission_run.v1` root and family workflow), exports
exactly the declared accepted output to the parent stage (the body's internal output never
crosses), the consumer runs after the composite, a parent cancel reaches the hosted child through
the governed path (with Temporal cancellation only as the fallback), a refused activation starts
nothing and releases the unit, and every recorded history replays deterministically.

Family and nested-program activities are fixtures (no PostgreSQL); the workflows, child workflow
starts, ids and command sequences are the production ones.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from temporalio import activity, workflow
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from mission_control.adapters.temporal.workflow_sandbox import coordinator_workflow_runner
from mission_control.adapters.temporal.workflows.mission_run import MissionRunWorkflow
from mission_control.adapters.temporal.workflows.nested_body import (
    NESTED_BODY_PATCH,
    start_nested_body,
)
from mission_control.adapters.temporal.workflows.operation import (
    MissionOperationWorkflow,
    OperationWorkflow,
)
from mission_control.adapters.temporal.workflows.stagegraph import StageGraphWorkflow
from mission_control.application.coordinator.coordinator_results import (
    InMemoryWorkflowResultRepository,
    TerminalWorkflowCompletionService,
)
from mission_control.contracts.identities import mission_root_id
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import StageGraphBlueprint
from mission_control.domain.authoring.nested_bodies import NestedBody, NestedExport
from mission_control.domain.authoring.stagegraph_builder import (
    StageGraphStageSpec,
    StageInputBindingSpec,
    build_stagegraph_v2,
)
from mission_control.domain.coordinator.launch import (
    TerminalWorkflowCompletion,
    WorkflowResultRecord,
)
from mission_control.domain.execution.contracts import OperationWorkflowRequest
from mission_control.domain.policies.contracts import RunOutcome, RunPhase
from mission_control.domain.programs.contracts import (
    BellLabsRunInput,
    ExecutionIdentity,
    StageGraphAdmissionActivityRequest,
    StageGraphRunInput,
)
from mission_control.domain.programs.goal_directed_runtime import (
    GoalOperationReconciliationRequest,
    GoalOperationReconciliationResult,
)
from mission_control.domain.programs.interpreter import StageGraphInterpreter
from mission_control.domain.programs.nested import (
    NestedActivation,
    NestedActivationRequest,
    NestedControlReceipt,
    NestedControlRequest,
    NestedSettlement,
    NestedSettlementRequest,
    child_terminal,
    project_exports,
    stage_result,
)
from tests.fixtures.temporal_history import patch_ids
from tests.integration.temporal.test_wp_bp_010_temporal import (
    DIGEST,
    QUEUE,
    FakeStageGraphActivities,
    _operation,
)

INSTALLATION = "5e8f2a52-7c0e-4f55-9a4e-2f2a3b1c0d11"
SCOPE = f"mc/{INSTALLATION}/ai-engineer/7a7d7b1e-1c2d-4e3f-8a9b-0c1d2e3f4a5b"
PARENT_RUN = "run-wi13-parent"
CHILD_RUN = "run-wi13-child"
STAGE = re.compile(r":stage:([^:]+):")


def child_graph() -> StageGraphBlueprint:
    """The body: `inner` produces the exported report, `notes` an internal draft."""

    return build_stagegraph_v2(
        logical_id="wi13.body",
        title="WI-13 nested body",
        description="a two-stage nested Stage Graph body",
        stages=(
            StageGraphStageSpec("inner", output_slots=("report",)),
            StageGraphStageSpec("notes", output_slots=("draft",)),
        ),
        max_concurrency=2,
    )


def nested_body() -> NestedBody:
    return NestedBody(
        host_id="research",
        node_key="research",
        position="research",
        behavior="stage_graph",
        family="StageGraph",
        depth=1,
        max_depth=2,
        definition_digest=DIGEST,
        blueprint_digest=sha256_digest(child_graph()),
        exports=(NestedExport(output="report", source="inner.report"),),
    )


def parent_graph() -> StageGraphBlueprint:
    graph = build_stagegraph_v2(
        logical_id="wi13.parent",
        title="WI-13 parent",
        description="a stage hosting a nested body, then a consumer of its export",
        stages=(
            StageGraphStageSpec("research", output_slots=("report",)),
            StageGraphStageSpec(
                "compare",
                depends_on=("research",),
                output_slots=("comparison",),
                bindings=(StageInputBindingSpec("research", "report"),),
            ),
        ),
        max_concurrency=2,
    )
    return StageGraphBlueprint.model_validate(
        {**graph.model_dump(mode="python"), "nested_bodies": (nested_body(),)}
    )


def stage_input(graph: StageGraphBlueprint, run_id: str, scope: str) -> StageGraphRunInput:
    return StageGraphRunInput(
        run_id=run_id,
        request_scope=scope,
        effective_configuration_digest=DIGEST,
        workflow_type_digest=DIGEST,
        blueprint_digest=sha256_digest(graph),
        blueprint=graph.model_dump(mode="json"),
        initial_run_version=1,
        max_concurrency=2,
        task_timeout_seconds=10,
        correlation_id="wi13:temporal",
        semantic_input_binding_ref="semantic-input:test",
    )


class TerminalStandIn:
    async def get_run(self, request_scope: str, run_id: str) -> Any:
        return SimpleNamespace(
            request_scope=request_scope,
            run_id=run_id,
            phase=RunPhase.TERMINAL,
            terminal_outcome=RunOutcome.COMPLETED,
            accepted_output_evidence=(),
            accepted_obligation_evidence=(),
        )


class NestedActivities(FakeStageGraphActivities):
    """The fixture family seam for parent and child, plus the nested-program activities."""

    def __init__(self, *, refuse: str = "", hold_inner: bool = False) -> None:
        super().__init__()
        self.refuse = refuse
        self.hold_inner = hold_inner
        self.inner_started = asyncio.Event()
        self.inner_release = asyncio.Event()
        self.inner_cancelled = asyncio.Event()
        self.activations: list[NestedActivationRequest] = []
        self.settlements: list[NestedSettlementRequest] = []
        self.controls: list[NestedControlRequest] = []
        self.executed: list[tuple[str, str]] = []
        self.results = InMemoryWorkflowResultRepository()

    @activity.defn(name="operation.execute")
    async def execute_operation(self, request: dict[str, Any]) -> dict[str, Any]:
        run_id = str(request["identity"]["run_id"])
        match = STAGE.search(str(request["identity"]["operation_id"]))
        stage = match.group(1) if match else "unknown"
        self.executed.append((run_id, stage))
        if stage == "inner" and self.hold_inner:
            self.inner_started.set()
            try:
                while not self.inner_release.is_set():
                    activity.heartbeat()
                    await asyncio.sleep(0.2)
            except asyncio.CancelledError:
                self.inner_cancelled.set()
                raise
        return {"output_refs": [f"artifact:{run_id}:{stage}"]}

    @activity.defn(name="nested_program.activate")
    async def activate(self, request: NestedActivationRequest) -> NestedActivation:
        self.activations.append(request)
        if self.refuse:
            return NestedActivation(activated=False, reason_code=self.refuse)
        graph = child_graph()
        # Parent and child share one canonical scope (the GD fixture parent has a test scope).
        family = stage_input(graph, CHILD_RUN, SCOPE)
        root = BellLabsRunInput(
            schema_version="mc.mission_run.v1",
            run_id=CHILD_RUN,
            request_scope=SCOPE,
            effective_configuration_digest=DIGEST,
            workflow_type_digest=DIGEST,
            family="StageGraph",
            family_input=asdict(family),
            family_task_queue=request.child_task_queue,
            parent_run_id=request.parent_run_id,
        )
        return NestedActivation(
            activated=True,
            child_run_id=CHILD_RUN,
            child_root=root,
            budget_ceiling=dict(request.parent_reservation),
        )

    @activity.defn(name="nested_program.settle")
    async def settle(self, request: NestedSettlementRequest) -> NestedSettlement:
        self.settlements.append(request)
        terminal = child_terminal(
            request.body.family, request.end, request.family_result, cause=request.cause
        )
        projection = project_exports(request.body, request.child_run_id, terminal, None)
        return NestedSettlement(projection=projection, settled_run_version=9)

    @activity.defn(name="nested_program.propagate")
    async def propagate(self, request: NestedControlRequest) -> NestedControlReceipt:
        self.controls.append(request)
        # The fixture has no child run control: report "not delivered" so the handle falls
        # back to Temporal cancellation of the child root.
        return NestedControlReceipt(False, reason_code="fixture_without_run_control")

    @activity.defn(name="coordinator.materialize_workflow_result")
    async def materialize_workflow_result(
        self, completion: TerminalWorkflowCompletion
    ) -> WorkflowResultRecord:
        service = TerminalWorkflowCompletionService(runs=TerminalStandIn(), results=self.results)
        return await service.complete(completion)

    @property
    def functions(self) -> list[object]:
        return [
            *super().functions,  # `operation.execute` is this class's override
            self.activate,
            self.settle,
            self.propagate,
            self.materialize_workflow_result,
        ]


async def _environment() -> WorkflowEnvironment:
    try:
        return await WorkflowEnvironment.start_time_skipping()
    except RuntimeError as error:
        pytest.skip(f"Temporal test server is unavailable: {error}")


@pytest.mark.asyncio
async def test_a_nested_stage_graph_body_runs_as_a_child_run_and_exports_exactly() -> None:
    activities = NestedActivities()
    environment = await _environment()
    workflows = [
        StageGraphWorkflow,
        OperationWorkflow,
        MissionOperationWorkflow,
        MissionRunWorkflow,
    ]
    async with environment:
        async with Worker(
            environment.client,
            task_queue=QUEUE,
            workflows=workflows,
            workflow_runner=coordinator_workflow_runner(),
            activities=activities.functions,
        ):
            parent = await environment.client.start_workflow(
                StageGraphWorkflow.run,
                stage_input(parent_graph(), PARENT_RUN, SCOPE),
                id="family/run-wi13-parent/1",
                task_queue=QUEUE,
            )
            result = await asyncio.wait_for(parent.result(), timeout=60)
            child_root = environment.client.get_workflow_handle(mission_root_id(SCOPE, CHILD_RUN))
            child_family = environment.client.get_workflow_handle(
                f"{mission_root_id(SCOPE, CHILD_RUN)}/family/1"
            )
            histories = [
                await parent.fetch_history(),
                await child_root.fetch_history(),
                await child_family.fetch_history(),
            ]
    # The composite's stage output is exactly the body's declared export.
    assert result.output_refs["research"] == (f"artifact:{CHILD_RUN}:inner",)
    assert f"artifact:{CHILD_RUN}:notes" not in result.output_refs["research"]
    assert result.output_refs["compare"] == (f"artifact:{PARENT_RUN}:compare",)
    assert result.completion_proposal.can_terminalize
    # The body ran as its own run (both inner stages), never as a parent operation.
    assert (PARENT_RUN, "research") not in activities.executed
    assert {(CHILD_RUN, "inner"), (CHILD_RUN, "notes"), (PARENT_RUN, "compare")} <= set(
        activities.executed
    )
    (activation,) = activities.activations
    assert (activation.host_id, activation.parent_run_id) == ("research", PARENT_RUN)
    assert activation.body == nested_body()
    (settlement,) = activities.settlements
    assert (settlement.end, settlement.child_run_id) == ("returned", CHILD_RUN)
    assert settlement.parent_reservation_id == activation.parent_reservation_id
    assert NESTED_BODY_PATCH in patch_ids(histories[0])
    replayer = Replayer(workflows=workflows, workflow_runner=coordinator_workflow_runner())
    for history in histories:
        await replayer.replay_workflow(history)


@pytest.mark.asyncio
async def test_a_refused_activation_starts_nothing_and_fails_the_host_stage() -> None:
    activities = NestedActivities(refuse="nested_execution_unavailable")
    environment = await _environment()
    workflows = [
        StageGraphWorkflow,
        OperationWorkflow,
        MissionOperationWorkflow,
        MissionRunWorkflow,
    ]
    async with environment:
        async with Worker(
            environment.client,
            task_queue=QUEUE,
            workflows=workflows,
            workflow_runner=coordinator_workflow_runner(),
            activities=activities.functions,
        ):
            parent = await environment.client.start_workflow(
                StageGraphWorkflow.run,
                stage_input(parent_graph(), PARENT_RUN, SCOPE),
                id="family/run-wi13-refused/1",
                task_queue=QUEUE,
            )
            result = await asyncio.wait_for(parent.result(), timeout=60)
            history = await parent.fetch_history()
    assert activities.executed == []  # no child stage, no parent operation, no consumer
    (settlement,) = activities.settlements
    assert (settlement.child_run_id, settlement.end, settlement.cause) == (
        "",
        "failed",
        "nested_execution_unavailable",
    )
    # The host stage was rejected (failed) and its consumer was never released.
    assert activities.admission_order == ["research"]
    assert [decision for _, decision in activities.result_decisions] == ["reject"]
    assert result.output_refs == {}
    await Replayer(
        workflows=workflows, workflow_runner=coordinator_workflow_runner()
    ).replay_workflow(history)


@dataclass(frozen=True)
class ProbeInput:
    request_scope: str
    parent_run_id: str
    operation: dict[str, Any]


@workflow.defn(name="test.wi13.nested-probe")
class NestedProbeWorkflow:
    """Hosts one nested body through the shared seam and cancels it on a signal, as a family's
    cancellation saga does (`handle.cancel()` on every active unit)."""

    def __init__(self) -> None:
        self._cancel = False
        self._pause = False

    @workflow.signal
    def cancel_body(self) -> None:
        self._cancel = True

    @workflow.signal
    def pause_body(self) -> None:
        self._pause = True

    @workflow.run
    async def run(self, probe: ProbeInput) -> dict[str, Any]:
        operation = OperationWorkflowRequest.model_validate(probe.operation)

        async def start_child(root: Any, workflow_id: str) -> Any:
            return await workflow.start_child_workflow(
                "mc.mission_run.v1",
                root,
                id=workflow_id,
                task_queue=workflow.info().task_queue,
                parent_close_policy=workflow.ParentClosePolicy.REQUEST_CANCEL,
            )

        handle, unit = await start_nested_body(
            request_scope=probe.request_scope,
            parent_run_id=probe.parent_run_id,
            parent_family="StageGraph",
            host_id="research",
            body=nested_body(),
            operation=operation,
            reservation_id="unit-1",
            reservation={"operation.attempts": 1},
            execution_epoch=1,
            correlation_id="wi13:probe",
            activity_timeout=timedelta(seconds=10),
            start_child=start_child,
            unit_result=stage_result,
        )
        while True:
            await workflow.wait_condition(lambda: self._cancel or self._pause or unit.done())
            if not self._pause:
                break
            # A parent pause covering the hosted body (as the family applies it).
            self._pause = False
            await handle.propagate("pause", "parent-pause-1", "the parent paused")
        if self._cancel:
            handle.cancel()
        result = await unit
        return {"disposition": result.disposition, "result": dict(result.result)}


def _probe_operation() -> dict[str, Any]:
    """The exact operation request the parent admitted for its `research` unit."""

    graph = parent_graph()
    interpreter = StageGraphInterpreter(graph, effective_max_concurrency=2)
    projection = interpreter.initial_projection(ExecutionIdentity(PARENT_RUN), run_version=2)
    proposal = interpreter.frontier(projection, available_concurrency=2)[0]
    request = StageGraphAdmissionActivityRequest(
        run_id=PARENT_RUN,
        request_scope=SCOPE,
        projection=projection,
        proposal=proposal,
        operation=None,
        blueprint=graph.model_dump(mode="json"),
        effective_max_concurrency=2,
        effective_configuration_digest=DIGEST,
        occurred_at=datetime(2026, 10, 29, tzinfo=UTC),
        idempotency_issuer="probe",
        correlation_id="probe",
    )
    return _operation(request).model_dump(mode="json")


@pytest.mark.asyncio
async def test_a_parent_cancel_is_governed_first_and_settles_the_hosted_body_cancelled() -> None:
    activities = NestedActivities(hold_inner=True)
    activities.operation_heartbeat_timeout_seconds = 5
    environment = await _environment()
    workflows = [
        NestedProbeWorkflow,
        StageGraphWorkflow,
        OperationWorkflow,
        MissionOperationWorkflow,
        MissionRunWorkflow,
    ]
    async with environment:
        async with Worker(
            environment.client,
            task_queue=QUEUE,
            workflows=workflows,
            workflow_runner=coordinator_workflow_runner(),
            activities=activities.functions,
        ):
            probe = await environment.client.start_workflow(
                NestedProbeWorkflow.run,
                ProbeInput(SCOPE, PARENT_RUN, _probe_operation()),
                id="test/wi13/probe",
                task_queue=QUEUE,
            )
            await asyncio.wait_for(activities.inner_started.wait(), timeout=30)
            await probe.signal(NestedProbeWorkflow.cancel_body)
            outcome = await asyncio.wait_for(probe.result(), timeout=60)
            history = await probe.fetch_history()
    # The governed path was tried first (the child's own run control), then the fallback.
    (control,) = activities.controls
    assert (control.kind, control.child_run_id, control.host_id) == (
        "cancel",
        CHILD_RUN,
        "research",
    )
    (settlement,) = activities.settlements
    assert settlement.end == "cancelled"
    assert outcome["disposition"] == "cancelled"
    assert outcome["result"]["nested"]["outcome"] == "cancelled"
    assert outcome["result"]["nested_settlement"]["reservation_id"] == "unit-1"
    await Replayer(
        workflows=workflows, workflow_runner=coordinator_workflow_runner()
    ).replay_workflow(history)


# --------------------------------------------------------------------------- Graph-in-Goal

GOAL_RUN = "run-wi13-goal"


def goal_blueprint_with_body() -> Any:
    from mission_control.domain.authoring.contracts import GoalDirectedBlueprint
    from mission_control.domain.authoring.fixtures import GENERIC_GOAL_DIRECTED

    body = nested_body().model_copy(
        update={"host_id": "executor", "position": "goal/pass", "node_key": "pass"}
    )
    return GoalDirectedBlueprint.model_validate(
        {**GENERIC_GOAL_DIRECTED.model_dump(mode="python"), "nested_bodies": (body,)}
    )


class GoalDocuments:
    def __init__(self) -> None:
        self.iterations: list[Any] = []

    async def persist_iteration(self, scope: str, result: Any, revision: str, at: Any) -> str:
        self.iterations.append(result)
        return f"goal-iteration:{len(self.iterations)}"


def goal_activities(nested: NestedActivities) -> list[object]:
    """The fixture Goal Loop family (executor reconciled through the nested path, verifier
    through its fixture operation) plus the child Stage Graph and nested activities."""

    from dataclasses import replace as dc_replace

    from mission_control.application.programs.goal_directed import (
        GoalDirectedOperationResultService,
    )
    from mission_control.domain.programs.contracts import GoalVerificationResult
    from tests.integration.temporal.test_wp_bp_020_temporal import FakeGoalDirectedActivities

    documents = GoalDocuments()
    results = GoalDirectedOperationResultService(documents=documents)  # type: ignore[arg-type]
    nested.goal_documents = documents  # type: ignore[attr-defined]

    class GoalFamily(FakeGoalDirectedActivities):
        @activity.defn(name="goaldirected.reconcile_operation")
        async def reconcile(
            self, request: GoalOperationReconciliationRequest
        ) -> GoalOperationReconciliationResult:
            result = await super().reconcile(request)
            if result.verification_result is None or request.executor_result is None:
                return result
            draft = dc_replace(
                result.verification_result,
                admitted_executor_output_refs=request.executor_result.output_refs,
                admitted_executor_evidence_refs=request.executor_result.evidence_refs,
                verification_digest="pending",
            )
            payload = asdict(draft)
            payload.pop("verification_digest")
            verified: GoalVerificationResult = dc_replace(
                draft, verification_digest=sha256_digest(payload)
            )
            return result.model_copy(update={"verification_result": verified})

        @activity.defn(name="goaldirected.reconcile_nested_executor")
        async def reconcile_nested(
            self, request: GoalOperationReconciliationRequest
        ) -> GoalOperationReconciliationResult:
            return await results.reconcile_nested_executor(request)

    family = GoalFamily(complete_at_iteration=1)
    nested.goal_family = family  # type: ignore[attr-defined]
    return [
        family.prepare_executor,
        family.prepare_verifier,
        family.reconcile,
        family.reconcile_nested,
        family.lifecycle,
        *nested.functions,
    ]


@pytest.mark.asyncio
async def test_a_goal_loop_executor_body_runs_as_a_child_graph_each_iteration() -> None:
    from mission_control.adapters.temporal.workflows.goal_directed import GoalDirectedWorkflow
    from tests.integration.temporal.test_wp_bp_020_temporal import _run_input as goal_input

    nested = NestedActivities()
    activities = goal_activities(nested)
    environment = await _environment()
    workflows = [
        GoalDirectedWorkflow,
        StageGraphWorkflow,
        OperationWorkflow,
        MissionOperationWorkflow,
        MissionRunWorkflow,
    ]
    blueprint = goal_blueprint_with_body()
    async with environment:
        first = Worker(
            environment.client,
            task_queue="wp-bp-020-temporal",
            workflows=workflows,
            workflow_runner=coordinator_workflow_runner(),
            activities=activities,
        )
        second = Worker(
            environment.client,
            task_queue=QUEUE,
            workflows=workflows,
            workflow_runner=coordinator_workflow_runner(),
            activities=activities,
        )
        async with first, second:
            goal = await environment.client.start_workflow(
                GoalDirectedWorkflow.run,
                goal_input(blueprint=blueprint, run_id=GOAL_RUN),
                id="family/run-wi13-goal/1",
                task_queue="wp-bp-020-temporal",
            )
            result = await asyncio.wait_for(goal.result(), timeout=90)
            histories = [
                await goal.fetch_history(),
                await environment.client.get_workflow_handle(
                    mission_root_id(SCOPE, CHILD_RUN)
                ).fetch_history(),
            ]
    # The executor phase never ran as an operation; the child graph's two stages did.
    family = nested.goal_family  # type: ignore[attr-defined]
    assert family.prepared_roles == ["executor", "verifier"]
    assert {(CHILD_RUN, "inner"), (CHILD_RUN, "notes")} <= set(nested.executed)
    (activation,) = nested.activations
    assert (activation.parent_family, activation.host_id) == ("GoalDirected", "executor")
    (settlement,) = nested.settlements
    assert settlement.end == "returned" and settlement.operation_id.endswith("/executor")
    # The iteration's execution result is exactly the body's export; the loop completed.
    (iteration,) = nested.goal_documents.iterations  # type: ignore[attr-defined]
    assert iteration.output_refs == (f"artifact:{CHILD_RUN}:inner",)
    assert iteration.completion_claim
    assert result.terminalization_proposal is not None
    assert result.terminalization_proposal.proposed_outcome == "complete"
    assert NESTED_BODY_PATCH in patch_ids(histories[0])
    replayer = Replayer(workflows=workflows, workflow_runner=coordinator_workflow_runner())
    for history in histories:
        await replayer.replay_workflow(history)


class SlowActivation(NestedActivities):
    """The activation completes only after the test cancelled the hosting unit."""

    def __init__(self, *, hold_inner: bool = False) -> None:
        super().__init__(hold_inner=hold_inner)
        self.activating = asyncio.Event()
        self.release = asyncio.Event()

    @activity.defn(name="nested_program.activate")
    async def activate(self, request: NestedActivationRequest) -> NestedActivation:
        self.activating.set()
        while not self.release.is_set():
            activity.heartbeat()
            await asyncio.sleep(0.1)
        return await super().activate(request)


@pytest.mark.asyncio
async def test_a_cancel_during_activation_never_starts_the_child_and_closes_it() -> None:
    activities = SlowActivation()
    environment = await _environment()
    workflows = [
        NestedProbeWorkflow,
        StageGraphWorkflow,
        OperationWorkflow,
        MissionOperationWorkflow,
        MissionRunWorkflow,
    ]
    async with environment:
        async with Worker(
            environment.client,
            task_queue=QUEUE,
            workflows=workflows,
            workflow_runner=coordinator_workflow_runner(),
            activities=activities.functions,
        ):
            probe = await environment.client.start_workflow(
                NestedProbeWorkflow.run,
                ProbeInput(SCOPE, PARENT_RUN, _probe_operation()),
                id="test/wi13/probe-early-cancel",
                task_queue=QUEUE,
            )
            await asyncio.wait_for(activities.activating.wait(), timeout=30)
            await probe.signal(NestedProbeWorkflow.cancel_body)
            activities.release.set()
            outcome = await asyncio.wait_for(probe.result(), timeout=60)
            history = await probe.fetch_history()
    assert outcome["disposition"] == "cancelled"
    assert activities.executed == []  # the child never started
    assert activities.controls == []  # nothing to propagate to: no child root
    (settlement,) = activities.settlements
    assert (settlement.child_run_id, settlement.child_started) == (CHILD_RUN, False)
    await Replayer(
        workflows=workflows, workflow_runner=coordinator_workflow_runner()
    ).replay_workflow(history)


class PauseDuringActivation(SlowActivation):
    """The child's inner stage holds until the pause reached the child (delivered on attach)."""

    def __init__(self) -> None:
        super().__init__(hold_inner=True)

    @activity.defn(name="nested_program.propagate")
    async def propagate(self, request: NestedControlRequest) -> NestedControlReceipt:
        receipt = await super().propagate(request)
        if request.kind == "pause":
            self.inner_release.set()
        return receipt


@pytest.mark.asyncio
async def test_a_pause_during_activation_is_delivered_once_the_child_started() -> None:
    """S1/S-A: a parent pause that lands before the child started is held by the handle and
    delivered to the child run on attach (never dropped); the body then completes."""

    activities = PauseDuringActivation()
    environment = await _environment()
    workflows = [
        NestedProbeWorkflow,
        StageGraphWorkflow,
        OperationWorkflow,
        MissionOperationWorkflow,
        MissionRunWorkflow,
    ]
    async with environment:
        async with Worker(
            environment.client,
            task_queue=QUEUE,
            workflows=workflows,
            workflow_runner=coordinator_workflow_runner(),
            activities=activities.functions,
        ):
            probe = await environment.client.start_workflow(
                NestedProbeWorkflow.run,
                ProbeInput(SCOPE, PARENT_RUN, _probe_operation()),
                id="test/wi13/probe-early-pause",
                task_queue=QUEUE,
            )
            await asyncio.wait_for(activities.activating.wait(), timeout=30)
            await probe.signal(NestedProbeWorkflow.pause_body)
            activities.release.set()
            outcome = await asyncio.wait_for(probe.result(), timeout=60)
            history = await probe.fetch_history()
    (control,) = activities.controls
    assert (control.kind, control.child_run_id, control.command_ref) == (
        "pause",
        CHILD_RUN,
        "parent-pause-1",
    )
    assert len(activities.activations) == 1  # one activation, one child start
    assert outcome["disposition"] == "completed"
    await Replayer(
        workflows=workflows, workflow_runner=coordinator_workflow_runner()
    ).replay_workflow(history)
