"""Loop iter-1 L1-03: a refused parallel admission persists nothing a correct retry conflicts with.

E2 (runs f10a2e30, d91ebbb2): with two parallel stages, the sibling's run-control fact moved the
run version, so the second stage's admission was refused `stale_run_version`. Its Operation
Execution Binding had already been persisted (it embeds the run-control revision), so every
re-admission on the fresh version failed `IdempotencyConflict` and the family failed.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from mission_control.adapters.temporal.orchestration_activities import StageGraphActivities
from mission_control.application.execution.operations.operation_execution import (
    InMemoryOperationBindingRepository,
    bind_operation_execution_request,
)
from mission_control.application.execution.run_control_repository import (
    InMemoryRunControlRepository,
)
from mission_control.application.execution.service import FamilyAdmissionRegistry, RunControlService
from mission_control.application.programs.service import (
    StageGraphDecisionService,
    StageGraphOperationPreparationService,
    StaticStageGraphOperationTemplateProvider,
    register_stagegraph_family_mutations,
)
from mission_control.domain.authoring.contracts import StageGraphBlueprint
from mission_control.domain.authoring.stagegraph_builder import (
    StageGraphStageSpec,
    build_stagegraph_v2,
)
from mission_control.domain.policies.contracts import (
    BudgetApplicability,
    CommandStatus,
    ReserveBudgetAction,
    StartAction,
)
from mission_control.domain.policies.errors import IdempotencyConflict
from mission_control.domain.programs.contracts import (
    ExecutionIdentity,
    StageGraphAcceptedProjection,
    StageGraphAdmissionActivityRequest,
)
from mission_control.domain.programs.interpreter import StageGraphInterpreter
from tests.fixtures.lane_bindings import LANE_REBINDERS
from tests.unit.operations.test_operation_execution import operation_request
from tests.unit.run_control.test_atomic_family_admission import admission_policies
from tests.unit.run_control.test_run_control import ConfigurationVerifier, command, request

NOW = datetime(2026, 11, 3, 4, 4, 49, tzinfo=UTC)
SCOPE = "tenant-1"


def graph() -> StageGraphBlueprint:
    return build_stagegraph_v2(
        logical_id="test.parallel-admission",
        title="Parallel admission",
        description="Two independent collectors",
        stages=(
            StageGraphStageSpec("collect_a", reservation={"tokens.total": 1}),
            StageGraphStageSpec("collect_b", reservation={"tokens.total": 1}),
        ),
        max_concurrency=2,
    )


async def harness() -> tuple[
    RunControlService,
    StageGraphInterpreter,
    StageGraphAcceptedProjection,
    InMemoryOperationBindingRepository,
    StageGraphActivities,
    str,
]:
    run_request = request()
    run_request = run_request.model_copy(
        update={
            "budget_envelope": run_request.budget_envelope.model_copy(
                update={
                    "dimensions": tuple(
                        item.model_copy(update={"applicability": BudgetApplicability.UNBOUNDED})
                        if item.dimension == "operation.attempts"
                        else item
                        for item in run_request.budget_envelope.dimensions
                    )
                }
            )
        }
    )
    repository = InMemoryRunControlRepository()
    registry = FamilyAdmissionRegistry()
    register_stagegraph_family_mutations(registry)
    control = RunControlService(repository, ConfigurationVerifier(), admission_policies(), registry)
    admitted = await control.admit(run_request)
    assert admitted.run_id
    run_id = admitted.run_id
    started = await control.execute(command(run_id, 1, "start", StartAction()))
    assert started.status == CommandStatus.ACCEPTED
    interpreter = StageGraphInterpreter(graph(), effective_max_concurrency=2)
    projection = interpreter.initial_projection(ExecutionIdentity(run_id), run_version=2)
    template = operation_request().model_copy(update={"request_scope": SCOPE})
    templates = {
        proposal.operation_request_key: template
        for proposal in interpreter.frontier(projection, available_concurrency=2)
    }
    bindings = InMemoryOperationBindingRepository()
    activities = StageGraphActivities(
        decision_service=StageGraphDecisionService(control, repository),
        operation_materializer=StageGraphOperationPreparationService(
            lane_bindings=LANE_REBINDERS,
            templates=StaticStageGraphOperationTemplateProvider(templates),
            operation_bindings=bindings,
        ),
        lifecycle_gateway=object(),  # type: ignore[arg-type]
    )
    return control, interpreter, projection, bindings, activities, run_id


def admission(
    run_id: str,
    interpreter: StageGraphInterpreter,
    projection: StageGraphAcceptedProjection,
    at: datetime,
) -> StageGraphAdmissionActivityRequest:
    available = 2 - interpreter.running_concurrency(projection)
    return StageGraphAdmissionActivityRequest(
        run_id=run_id,
        request_scope=SCOPE,
        projection=projection,
        proposal=interpreter.frontier(projection, available_concurrency=available)[0],
        operation=None,
        blueprint=graph().model_dump(mode="json"),
        effective_max_concurrency=2,
        occurred_at=at,
        idempotency_issuer="operator",
        correlation_id="stagegraph:parallel-admission",
        semantic_input_binding_ref="semantic-input:test",
        effective_configuration_digest=request().effective_configuration_digest,
    )


@pytest.mark.asyncio
async def test_stale_parallel_admission_persists_nothing_and_the_retry_admits() -> None:
    control, interpreter, projection, bindings, activities, run_id = await harness()

    first = await activities.admit_operation(admission(run_id, interpreter, projection, NOW))
    assert first.accepted and first.operation is not None
    assert first.operation.operation.run_control_revision == 3
    projection = first.projection

    # The sibling's run-control fact (its operation reserving/starting) moves the run version
    # while the family still holds its admission-time projection.
    moved = await control.execute(
        command(
            run_id,
            projection.run_version,
            "sibling-fact",
            ReserveBudgetAction(reservation_id="sibling", amounts={"tokens.total": 1}),
        )
    )
    assert moved.status == CommandStatus.ACCEPTED

    stale_request = admission(run_id, interpreter, projection, NOW + timedelta(seconds=10))
    assert stale_request.proposal.identity.stage_id == "collect_b"
    refused = await activities.admit_operation(stale_request)
    assert not refused.accepted and refused.reason_code == "stale_run_version"
    semantic = refused.projection.stages  # unchanged projection
    assert semantic == projection.stages
    assert len(bindings._bindings) == 1  # only collect_a's admitted binding

    fresh = replace(projection, run_version=moved.resulting_run_version)
    retried = await activities.admit_operation(
        admission(run_id, interpreter, fresh, NOW + timedelta(seconds=70))
    )
    assert retried.accepted and retried.operation is not None
    assert retried.operation.operation.run_control_revision == moved.resulting_run_version + 1
    persisted = await bindings.get_binding(
        retried.operation.operation.identity.semantic_key, request_scope=SCOPE
    )
    assert persisted == bind_operation_execution_request(retried.operation.operation)


@pytest.mark.asyncio
async def test_a_true_duplicate_with_other_intent_still_conflicts_and_names_its_stage() -> None:
    _control, interpreter, projection, bindings, activities, run_id = await harness()
    candidate = admission(run_id, interpreter, projection, NOW)
    first = await activities.admit_operation(candidate)
    assert first.accepted and first.operation is not None
    materializer = StageGraphOperationPreparationService(
        lane_bindings=LANE_REBINDERS,
        templates=StaticStageGraphOperationTemplateProvider(
            {
                candidate.proposal.operation_request_key: operation_request().model_copy(
                    update={"request_scope": SCOPE, "session_id": "another-intent"}
                )
            }
        ),
        operation_bindings=bindings,
    )
    with pytest.raises(IdempotencyConflict) as raised:
        await materializer.materialize(candidate)
    message = str(raised.value)
    assert "collect_a" in message
    assert first.operation.operation.runtime_unit is not None
    assert first.operation.operation.runtime_unit.unit_key in message


@pytest.mark.asyncio
async def test_l2_01_refused_admission_returns_the_live_run_version_for_the_retry() -> None:
    """Loop iter-2 L2-01 (E2 d0a16126): the refusal returned the caller's projection unchanged,
    so the workflow (which retried only when `family_version` grew) never retried and the
    parallel collectors ran one after the other. The refusal now carries the run's live
    version (the family head is unchanged, so the semantic projection and digest are too) and
    re-admitting with exactly that projection succeeds."""

    control, interpreter, projection, bindings, activities, run_id = await harness()
    first = await activities.admit_operation(admission(run_id, interpreter, projection, NOW))
    assert first.accepted
    projection = first.projection
    moved = await control.execute(
        command(
            run_id,
            projection.run_version,
            "sibling-fact",
            ReserveBudgetAction(reservation_id="sibling", amounts={"tokens.total": 1}),
        )
    )
    assert moved.status == CommandStatus.ACCEPTED

    refused = await activities.admit_operation(
        admission(run_id, interpreter, projection, NOW + timedelta(seconds=10))
    )
    assert not refused.accepted and refused.reason_code == "stale_run_version"
    assert refused.projection.run_version == moved.resulting_run_version
    assert refused.projection.family_version == projection.family_version
    assert refused.projection.digest == projection.digest

    retried = await activities.admit_operation(
        admission(run_id, interpreter, refused.projection, NOW + timedelta(seconds=11))
    )
    assert retried.accepted and retried.operation is not None
    assert len(bindings._bindings) == 2
