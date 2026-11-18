from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from mission_control.adapters.temporal.workflow_sandbox import coordinator_workflow_runner
from mission_control.adapters.temporal.workflows.operation import OperationWorkflow
from mission_control.adapters.temporal.workflows.stagegraph import StageGraphWorkflow
from mission_control.application.programs.service import (
    StageGraphOperationPreparationService,
    StaticStageGraphOperationTemplateProvider,
)
from mission_control.domain.execution.contracts import (
    DeepAgentExecutionBinding,
    OperationExecutionRequest,
)
from mission_control.domain.programs.contracts import (
    ExecutionIdentity,
    StageGraphAdmissionActivityRequest,
)
from mission_control.domain.programs.interpreter import StageGraphInterpreter
from tests.fixtures.lane_bindings import LANE_REBINDERS, lane_fields
from tests.support.integration.temporal.wp_bp_010_temporal import (
    DIGEST,
    NOW,
    QUEUE,
    FakeStageGraphActivities,
    RecordingOperationBindings,
    _blueprint,
    _operation,
    _run_input,
)

# A cancelled sibling's heartbeat timeout: the cancel is delivered on the next heartbeat.
SIBLING_CANCEL_HEARTBEAT_SECONDS = 5


@pytest.mark.asyncio
async def test_real_materializer_persists_exact_operation_child_intent() -> None:
    graph = _blueprint()
    interpreter = StageGraphInterpreter(graph, effective_max_concurrency=3)
    projection = interpreter.initial_projection(
        identity=ExecutionIdentity("run-wp-bp-010-temporal"),
        run_version=2,
    )
    proposal = replace(
        interpreter.frontier(projection, available_concurrency=3)[0],
        objective_override="Repair only the accepted stage evidence.",
    )
    request = StageGraphAdmissionActivityRequest(
        run_id="run-wp-bp-010-temporal",
        request_scope="tenant-1",
        projection=projection,
        proposal=proposal,
        operation=None,
        blueprint=graph.model_dump(mode="json"),
        effective_max_concurrency=3,
        occurred_at=NOW,
        idempotency_issuer="stagegraph-worker",
        correlation_id="stagegraph:materializer-test",
        semantic_input_binding_ref="semantic-input:test",
        effective_configuration_digest=DIGEST,
    )
    template = _operation(request).operation
    repository = RecordingOperationBindings()
    service = StageGraphOperationPreparationService(
        lane_bindings=LANE_REBINDERS,
        templates=StaticStageGraphOperationTemplateProvider(
            {proposal.operation_request_key: template}
        ),
        operation_bindings=repository,  # type: ignore[arg-type]
    )

    prepared = await service.materialize(request)

    assert prepared.semantic_attempt_id == proposal.identity.semantic_key
    assert prepared.operation.run_control_revision == projection.run_version + 1
    assert prepared.operation.budget_reservation_id == proposal.reservation_id
    assert prepared.operation.prompt_segments[-1].content == proposal.objective_override
    assert len(repository.bindings) == 1
    # REQ-CP-EXEC-013: mapped instance, cycles, and slot become the structured unit.
    unit = prepared.operation.runtime_unit
    candidate = proposal.identity.candidate
    assert unit is not None
    assert (unit.family, unit.unit_kind, unit.semantic_operation_id) == (
        "stage_graph",
        "stage_operation",
        proposal.identity.operation_id,
    )
    assert unit.location.model_dump() == {
        "stage_id": candidate.stage_id,
        "mapped_instance_id": candidate.mapped_instance_id,
        "workflow_cycle_ordinal": candidate.workflow_cycle_ordinal,
        "stage_cycle_ordinal": candidate.stage_cycle_ordinal,
        "operation_slot_id": candidate.operation_slot_id,
    }
    assert repository.bindings[0].runtime_unit == unit


@pytest.mark.asyncio
async def test_real_materializer_freezes_the_stage_unit_cognitive_namespace() -> None:
    """REQ-CP-DA-016: a StageGraph Deep Agent unit owns one namespace per unit generation."""

    from tests.support.deep_agents import exact_fixture
    from tests.support.operations import operation_request

    graph = _blueprint()
    interpreter = StageGraphInterpreter(graph, effective_max_concurrency=3)
    projection = interpreter.initial_projection(
        identity=ExecutionIdentity("run-wp-bp-010-temporal"),
        run_version=2,
    )
    proposal = interpreter.frontier(projection, available_concurrency=3)[0]
    request = StageGraphAdmissionActivityRequest(
        run_id="run-wp-bp-010-temporal",
        request_scope="tenant-1",
        projection=projection,
        proposal=proposal,
        operation=None,
        blueprint=graph.model_dump(mode="json"),
        effective_max_concurrency=3,
        occurred_at=NOW,
        idempotency_issuer="stagegraph-worker",
        correlation_id="stagegraph:namespace-test",
        semantic_input_binding_ref="semantic-input:test",
        effective_configuration_digest=DIGEST,
    )
    deep_binding, _profile, _bundle = exact_fixture()
    template = OperationExecutionRequest.model_validate(
        {
            **operation_request().model_dump(mode="python"),
            "execution_runtime": "deep_agent",
            "native_placement": None,
            **lane_fields(deep_binding),
        }
    )
    service = StageGraphOperationPreparationService(
        lane_bindings=LANE_REBINDERS,
        templates=StaticStageGraphOperationTemplateProvider(
            {proposal.operation_request_key: template}
        ),
        operation_bindings=RecordingOperationBindings(),  # type: ignore[arg-type]
    )

    prepared = await service.materialize(request)

    bound = DeepAgentExecutionBinding.carried_by(prepared.operation)
    unit = prepared.operation.runtime_unit
    assert bound is not None and unit is not None
    assert bound.runtime_unit == unit
    assert bound.cognitive_session_namespace == f"belllabs/stage/{unit.unit_key}/gen/1"
    assert bound.binding_digest == bound.content_digest()


@pytest.mark.asyncio
async def test_incremental_any_join_runs_downstream_before_slow_sibling_and_replays() -> None:
    activities = FakeStageGraphActivities()
    try:
        environment = await WorkflowEnvironment.start_time_skipping()
    except RuntimeError as error:
        pytest.skip(f"Temporal test server is unavailable: {error}")

    workflow_id = "family/run-wp-bp-010-temporal/1"
    async with environment:
        async with Worker(
            environment.client,
            task_queue=QUEUE,
            workflows=[StageGraphWorkflow, OperationWorkflow],
            workflow_runner=coordinator_workflow_runner(),
            activities=activities.functions,
        ):
            handle = await environment.client.start_workflow(
                StageGraphWorkflow.run,
                _run_input(_blueprint()),
                id=workflow_id,
                task_queue=QUEUE,
            )
            await asyncio.wait_for(activities.downstream_started.wait(), timeout=20)
            assert not activities.slow_completed.is_set()
            activities.slow_release.set()
            result = await handle.result()
            history = await handle.fetch_history()

        await Replayer(
            workflows=[StageGraphWorkflow, OperationWorkflow],
            workflow_runner=coordinator_workflow_runner(),
        ).replay_workflow(history)

    assert activities.admission_order.index("downstream") < len(activities.admission_order)
    assert result.output_refs["downstream"] == ("artifact:downstream",)
    assert result.completion_proposal.can_terminalize


@pytest.mark.asyncio
async def test_slow_sibling_cancellation_is_reconciled_before_completion() -> None:
    activities = FakeStageGraphActivities()
    activities.operation_heartbeat_timeout_seconds = SIBLING_CANCEL_HEARTBEAT_SECONDS
    try:
        environment = await WorkflowEnvironment.start_time_skipping()
    except RuntimeError as error:
        pytest.skip(f"Temporal test server is unavailable: {error}")

    async with environment:
        async with Worker(
            environment.client,
            task_queue=QUEUE,
            workflows=[StageGraphWorkflow, OperationWorkflow],
            workflow_runner=coordinator_workflow_runner(),
            activities=activities.functions,
        ):
            result = await environment.client.execute_workflow(
                StageGraphWorkflow.run,
                _run_input(_blueprint(cancel_slow_sibling=True)),
                id="family/run-wp-bp-010-slow-cancel/1",
                task_queue=QUEUE,
            )
            # The cancel reached the running Activity through its heartbeat while the worker
            # is still up (not through the worker's shutdown).
            await asyncio.wait_for(activities.slow_cancelled.wait(), timeout=60)

    assert activities.slow_cancelled.is_set()
    assert not activities.slow_completed.is_set()
    [reconciled] = activities.cancel_settlements
    assert ":stage:slow:" in reconciled, "only the cancelled sibling runs operation.cancel"
    assert result.output_refs["downstream"] == ("artifact:downstream",)
    assert result.completion_proposal.can_terminalize


@pytest.mark.asyncio
async def test_continue_as_new_preserves_accepted_projection_and_semantic_identity() -> None:
    activities = FakeStageGraphActivities()
    try:
        environment = await WorkflowEnvironment.start_time_skipping()
    except RuntimeError as error:
        pytest.skip(f"Temporal test server is unavailable: {error}")

    run_input = _run_input(_blueprint())
    run_input = run_input.__class__(**{**run_input.__dict__, "force_continue_as_new": True})
    async with environment:
        async with Worker(
            environment.client,
            task_queue=QUEUE,
            workflows=[StageGraphWorkflow, OperationWorkflow],
            workflow_runner=coordinator_workflow_runner(),
            activities=activities.functions,
        ):
            handle = await environment.client.start_workflow(
                StageGraphWorkflow.run,
                run_input,
                id="family/run-wp-bp-010-continuation/1",
                task_queue=QUEUE,
            )
            await asyncio.wait_for(activities.downstream_started.wait(), timeout=20)
            activities.slow_release.set()
            result = await handle.result()

    assert activities.admission_order.count("fast") == 1
    assert activities.admission_order.count("slow") == 1
    assert activities.admission_order.count("downstream") == 1
    assert result.execution_epoch == 1
    assert result.output_refs["downstream"] == ("artifact:downstream",)


@pytest.mark.asyncio
async def test_bounded_workflow_cycle_reuses_producers_and_advances_cycle_identity() -> None:
    activities = FakeStageGraphActivities(cycle_once=True)
    try:
        environment = await WorkflowEnvironment.start_time_skipping()
    except RuntimeError as error:
        pytest.skip(f"Temporal test server is unavailable: {error}")

    async with environment:
        async with Worker(
            environment.client,
            task_queue=QUEUE,
            workflows=[StageGraphWorkflow, OperationWorkflow],
            workflow_runner=coordinator_workflow_runner(),
            activities=activities.functions,
        ):
            handle = await environment.client.start_workflow(
                StageGraphWorkflow.run,
                _run_input(_blueprint(workflow_cycles=1)),
                id="family/run-wp-bp-010-cycle/1",
                task_queue=QUEUE,
            )
            await asyncio.wait_for(activities.downstream_started.wait(), timeout=20)
            activities.slow_release.set()
            result = await handle.result()

    assert activities.admission_order.count("fast") == 1
    assert activities.admission_order.count("slow") == 1
    assert activities.admission_order.count("downstream") == 2
    assert result.workflow_cycles == 1
    assert any("workflow-cycle:1" in item for item in result.schedule_trace)
    assert any(
        "workflow-cycle:1" in identity and decision == "admit"
        for identity, decision in activities.result_decisions
    )
    assert result.reused_output_refs


@pytest.mark.asyncio
async def test_bounded_stage_cycle_has_distinct_identity_and_preserves_workflow_ordinal() -> None:
    activities = FakeStageGraphActivities(cycle_once=True, cycle_scope="stage")
    try:
        environment = await WorkflowEnvironment.start_time_skipping()
    except RuntimeError as error:
        pytest.skip(f"Temporal test server is unavailable: {error}")
    async with environment:
        async with Worker(
            environment.client,
            task_queue=QUEUE,
            workflows=[StageGraphWorkflow, OperationWorkflow],
            workflow_runner=coordinator_workflow_runner(),
            activities=activities.functions,
        ):
            handle = await environment.client.start_workflow(
                StageGraphWorkflow.run,
                _run_input(_blueprint(stage_cycles=1)),
                id="family/run-wp-bp-010-stage-cycle/1",
                task_queue=QUEUE,
            )
            await asyncio.wait_for(activities.downstream_started.wait(), timeout=20)
            activities.slow_release.set()
            result = await handle.result()

    assert activities.admission_order.count("downstream") == 2
    assert result.workflow_cycles == 0
    assert any("stage-cycle:1" in item for item in result.schedule_trace)
    assert any(
        "stage-cycle:1" in identity and decision == "admit"
        for identity, decision in activities.result_decisions
    )
    assert result.reused_output_refs
