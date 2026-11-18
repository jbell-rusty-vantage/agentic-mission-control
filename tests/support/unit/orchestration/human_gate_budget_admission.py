"""Builders, constants and fakes that other test files import.

Moved from tests/unit/orchestration/test_human_gate_budget_admission.py.
"""

from datetime import UTC, datetime

from mission_control.application.execution.run_control_repository import (
    InMemoryRunControlRepository,
)
from mission_control.application.execution.service import FamilyAdmissionRegistry, RunControlService
from mission_control.application.programs.service import (
    StageGraphDecisionService,
    register_stagegraph_family_mutations,
)
from mission_control.domain.authoring.stagegraph_builder import (
    StageGraphStageSpec,
    build_stagegraph_v2,
)
from mission_control.domain.execution.contracts import (
    OperationAttemptIdentity,
    OperationWorkflowRequest,
)
from mission_control.domain.policies.contracts import CommandStatus, RecordUsageAction, StartAction
from mission_control.domain.programs.contracts import (
    ExecutionIdentity,
    StageGraphAdmissionActivityRequest,
)
from mission_control.domain.programs.human_gate import HumanGateSpec
from mission_control.domain.programs.interpreter import StageGraphInterpreter
from tests.support.operations import operation_request
from tests.support.run_control import ConfigurationVerifier, command, request
from tests.support.unit.run_control.atomic_family_admission import admission_policies

GATE = HumanGateSpec(
    gate_key="review",
    prompt="Review exact report",
    reviewers=("actual-owner",),
    packet_sources=("probe.report",),
)


def graph():
    return build_stagegraph_v2(
        logical_id="test.control-budget",
        title="Control budget",
        description="Review is not cognition",
        stages=(
            StageGraphStageSpec("review", reservation={"tokens.total": 1}),
            StageGraphStageSpec("work", reservation={"tokens.total": 1}),
        ),
        max_concurrency=1,
    )


class TrustedGates:
    async def verify(self, candidate):
        if candidate.human_gate != GATE or candidate.control_gate_keys != ("review",):
            raise ValueError("gate policy mismatch")
        return (GATE,)


async def fixture(repository=None, *, run_request=None, make_command=command):
    repository = repository if repository is not None else InMemoryRunControlRepository()
    registry = FamilyAdmissionRegistry()
    register_stagegraph_family_mutations(registry)
    control = RunControlService(repository, ConfigurationVerifier(), admission_policies(), registry)
    admitted = await control.admit(run_request or request())
    scope = (run_request or request()).request_scope
    run_id = admitted.run_id
    assert run_id
    await control.execute(make_command(run_id, 1, "start", StartAction()))
    # Provider facts must remain recorded even above the declared ledger hard cap.
    usage = await control.execute(
        make_command(
            run_id,
            2,
            "actual-provider-usage",
            RecordUsageAction(
                usage_id="actual",
                actual_amounts={"tokens.total": 112976},
                reservation_id="baseline",
            ),
        )
    )
    assert usage.status == CommandStatus.ACCEPTED, usage.reason_code
    interpreter = StageGraphInterpreter(
        graph(), effective_max_concurrency=1, control_gate_keys=frozenset({"review"})
    )
    projection = interpreter.initial_projection(ExecutionIdentity(run_id), run_version=3)
    proposal = interpreter.frontier(projection, available_concurrency=0)[0]
    operation = operation_request().model_copy(
        update={
            "request_scope": scope,
            "identity": OperationAttemptIdentity(
                run_id=run_id, operation_id=proposal.identity.operation_id, operation_attempt=1
            ),
            "budget_reservation_id": proposal.reservation_id,
            "run_control_revision": 4,
            "budget_limits": {},
        }
    )
    candidate = StageGraphAdmissionActivityRequest(
        run_id=run_id,
        request_scope=scope,
        projection=projection,
        proposal=proposal,
        operation=OperationWorkflowRequest(
            semantic_attempt_id=proposal.identity.semantic_key,
            operation_kind="bound_operation",
            operation=operation,
        ),
        blueprint=graph().model_dump(mode="json"),
        effective_max_concurrency=1,
        occurred_at=datetime.now(UTC),
        idempotency_issuer="operator",
        correlation_id="control-test",
        human_gate=GATE,
        control_gate_keys=("review",),
    )
    return control, repository, candidate


async def accept_gate_result(control, repository, candidate):
    from mission_control.domain.programs.contracts import (
        LateResultFacts,
        StageGraphResultActivityRequest,
        StageResultObservation,
    )
    from mission_control.domain.programs.human_gate import (
        decide_resolution,
        outcome_for,
        stagegraph_gate_result,
    )
    from tests.unit.human_tasks.fixtures import activation, later, open_task
    from tests.unit.human_tasks.fixtures import request as resolution_request

    service = StageGraphDecisionService(control, repository, human_gates=TrustedGates())
    admitted = await service.admit_operation(candidate)
    assert admitted.accepted
    task = open_task(activation(gate=GATE, scope=candidate.request_scope, run_id=candidate.run_id))
    assert outcome_for(task) is None
    denied = decide_resolution(
        task,
        resolution_request(task.activation),
        actor_id="impostor",
        permissions=frozenset(),
        now=later(1),
    )
    assert denied.status == "reject"
    resolved = decide_resolution(
        task,
        resolution_request(task.activation),
        actor_id="actual-owner",
        permissions=frozenset(),
        now=later(1),
    )
    assert resolved.resolution is not None
    task = task.model_copy(
        update={"lifecycle": "resolved", "resolution": resolved.resolution, "version": 2}
    )
    outcome = outcome_for(task)
    assert outcome is not None
    disposition, payload = stagegraph_gate_result(
        outcome, evaluation_contract_ref=None, objective_contract_ref=None
    )
    result = await service.decide_result(
        StageGraphResultActivityRequest(
            run_id=candidate.run_id,
            request_scope=candidate.request_scope,
            projection=admitted.projection,
            observation=StageResultObservation(
                identity=candidate.proposal.identity,
                operation_result=payload,
                child_closed_or_quiesced=True,
                reservations_and_usage_settled=True,
                effects_settled=True,
                cancellation_reconciled=True,
                accepted_order=1,
                operation_disposition=disposition,
            ),
            late_facts=LateResultFacts(),
            blueprint=candidate.blueprint,
            effective_max_concurrency=1,
            occurred_at=candidate.occurred_at,
            idempotency_issuer=candidate.idempotency_issuer,
            correlation_id=candidate.correlation_id,
        )
    )
    assert result.accepted
    assert result.proposal.decision.value == "admit"
    stage = result.projection.stages[candidate.proposal.identity.candidate.semantic_prefix]
    assert stage.status == "completed"
    assert stage.output_refs == (outcome.resolution_ref,)
    assert (await control.get_budget(candidate.request_scope, candidate.run_id)).consumed[
        "tokens.total"
    ] == 112976
    return result
