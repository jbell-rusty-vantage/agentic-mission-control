"""A denied cognitive reservation is a governed failure, never a native execution."""

from dataclasses import asdict, replace

import pytest

from mission_control.application.programs.service import (
    StageGraphDecisionService,
)
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.stagegraph_builder import (
    StageGraphStageSpec,
    build_stagegraph_v2,
)
from mission_control.domain.execution.contracts import OperationAttemptIdentity
from mission_control.domain.programs.contracts import (
    ExecutionIdentity,
    StageGraphCompletionActivityRequest,
    StageGraphDecisionMutation,
)
from mission_control.domain.programs.interpreter import StageGraphInterpreter
from tests.unit.orchestration.test_human_gate_budget_admission import fixture


def graph():
    return build_stagegraph_v2(
        logical_id="test.admission-failure",
        title="Admission failure",
        description="No cognition ran",
        stages=(StageGraphStageSpec("work", reservation={"tokens.total": 1}),),
        max_concurrency=1,
    )


async def prepared(*, conclude=True, repository=None, run_request=None, make_command=None):
    from mission_control.domain.policies.contracts import BudgetApplicability
    from tests.unit.run_control.test_run_control import request

    run_request = run_request or request()
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
    kwargs = {"repository": repository, "run_request": run_request}
    if make_command is not None:
        kwargs["make_command"] = make_command
    control, repository, gate = await fixture(**kwargs)
    interpreter = StageGraphInterpreter(graph(), effective_max_concurrency=1)
    projection = interpreter.initial_projection(ExecutionIdentity(gate.run_id), run_version=3)
    proposal = interpreter.frontier(projection, available_concurrency=1)[0]
    operation = gate.operation.model_copy(
        update={
            "semantic_attempt_id": proposal.identity.semantic_key,
            "operation": gate.operation.operation.model_copy(
                update={
                    "identity": OperationAttemptIdentity(
                        run_id=gate.run_id,
                        operation_id=proposal.identity.operation_id,
                        operation_attempt=1,
                    ),
                    "budget_reservation_id": proposal.reservation_id,
                    "run_control_revision": 4,
                    "budget_limits": proposal.reservation,
                }
            ),
        }
    )
    candidate = replace(
        gate,
        projection=projection,
        proposal=proposal,
        operation=operation,
        blueprint=graph().model_dump(mode="json"),
        human_gate=None,
        control_gate_keys=(),
        conclude_budget_rejection=conclude,
    )
    return control, repository, candidate, interpreter


@pytest.mark.asyncio
async def test_budget_rejection_persists_truth_and_terminalizes_first_stage_failed():
    control, repository, candidate, interpreter = await prepared()
    service = StageGraphDecisionService(control, repository)
    before_budget = await control.get_budget(candidate.request_scope, candidate.run_id)
    before_effects = await control.get_effects(candidate.request_scope, candidate.run_id)
    refused = await service.admit_operation(candidate)
    assert not refused.accepted and refused.reason_code == "budget_hard_cap_exceeded"
    assert refused.operation is None
    stage = refused.projection.stages[candidate.proposal.identity.candidate.semantic_prefix]
    assert stage.status == "failed"
    assert stage.semantic_attempt == 0
    assert stage.admitted_operation_request_ref is None
    assert not stage.output_refs and not refused.projection.accepted_results
    assert not refused.projection.producer_liabilities
    assert await control.get_budget(candidate.request_scope, candidate.run_id) == before_budget
    assert await control.get_effects(candidate.request_scope, candidate.run_id) == before_effects
    assert await service.admit_operation(candidate) == refused
    head = await repository.get_family_head(
        candidate.request_scope, candidate.run_id, "stagegraph", StageGraphDecisionMutation
    )
    assert head and head.decision_kind == "admission_rejected"
    denied = head.decision_payload["rejected_command"]
    actual = await repository.get_family_admission_receipt(
        candidate.request_scope,
        candidate.run_id,
        denied["idempotency_issuer"],
        denied["command_id"],
    )
    assert actual and actual.command_result.reason_code == "budget_hard_cap_exceeded"
    run = await control.get_run(candidate.request_scope, candidate.run_id)
    completion = interpreter.failure_completion(refused.projection)
    assert completion and completion.failed and completion.can_terminalize
    terminal = await service.complete(
        StageGraphCompletionActivityRequest(
            run_id=candidate.run_id,
            request_scope=candidate.request_scope,
            projection=refused.projection,
            proposal=completion,
            workflow_type_digest=run.workflow_type_ref.digest,
            occurred_at=candidate.occurred_at,
            idempotency_issuer=candidate.idempotency_issuer,
            correlation_id=candidate.correlation_id,
        )
    )
    assert terminal.accepted
    assert terminal.terminal_outcome.value == "failed"
    assert (
        await control.get_run(candidate.request_scope, candidate.run_id)
    ).phase.value == "terminal"
    assert await control.get_budget(candidate.request_scope, candidate.run_id) == before_budget
    assert await service.admit_operation(candidate) == refused
    assert (
        await control.get_run(candidate.request_scope, candidate.run_id)
    ).phase.value == "terminal"


@pytest.mark.asyncio
async def test_old_admission_path_retains_original_rejection_without_new_family_fact():
    control, repository, candidate, _ = await prepared(conclude=False)
    refused = await StageGraphDecisionService(control, repository).admit_operation(candidate)
    assert not refused.accepted
    assert refused.projection == candidate.projection
    assert (
        await repository.get_family_head(
            candidate.request_scope, candidate.run_id, "stagegraph", StageGraphDecisionMutation
        )
        is None
    )
    assert (await control.get_run(candidate.request_scope, candidate.run_id)).version == 3


def test_absent_admission_rejection_keeps_legacy_projection_digest_and_payload():
    interpreter = StageGraphInterpreter(graph(), effective_max_concurrency=1)
    projection = interpreter.initial_projection(ExecutionIdentity("run"), run_version=1)
    legacy = asdict(projection)
    legacy.pop("run_version")
    for stage in legacy["stages"].values():
        if not stage["frozen_input_bindings"]:
            stage.pop("frozen_input_bindings")
    assert projection.digest == sha256_digest(legacy)
    assert all(
        "admission_rejection_ref" not in item for item in asdict(projection)["stages"].values()
    )


@pytest.mark.asyncio
async def test_stale_admission_is_not_converted_to_candidate_failure():
    from mission_control.domain.policies.contracts import CancelAction
    from tests.unit.run_control.test_run_control import command

    control, repository, candidate, _ = await prepared()
    advanced = await control.execute(command(candidate.run_id, 3, "advance", CancelAction()))
    assert advanced.status.value == "accepted"
    refused = await StageGraphDecisionService(control, repository).admit_operation(candidate)
    assert refused.reason_code == "stale_run_version"
    # L2-01: the refusal carries the live run version; nothing semantic changed.
    assert refused.projection == replace(
        candidate.projection, run_version=advanced.resulting_run_version
    )
    assert (
        await repository.get_family_head(
            candidate.request_scope, candidate.run_id, "stagegraph", StageGraphDecisionMutation
        )
        is None
    )


@pytest.mark.asyncio
async def test_nondeclared_budget_dimension_is_not_converted_to_candidate_failure():
    control, repository, candidate, _ = await prepared()
    different = build_stagegraph_v2(
        logical_id="test.other-denial",
        title="Other denial",
        description="Not a cap",
        stages=(StageGraphStageSpec("work", reservation={"tool.calls.total": 1}),),
        max_concurrency=1,
    )
    interpreter = StageGraphInterpreter(different, effective_max_concurrency=1)
    proposal = interpreter.frontier(candidate.projection, available_concurrency=1)[0]
    candidate = replace(candidate, blueprint=different.model_dump(mode="json"), proposal=proposal)
    refused = await StageGraphDecisionService(control, repository).admit_operation(candidate)
    assert refused.reason_code == "budget_not_applicable"
    assert refused.projection == candidate.projection
    assert (
        await repository.get_family_head(
            candidate.request_scope, candidate.run_id, "stagegraph", StageGraphDecisionMutation
        )
        is None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("corruption", ["missing", "status", "reason", "fingerprint", "family"])
async def test_recording_rechecks_actual_persisted_reserve_rejection(monkeypatch, corruption):
    from mission_control.domain.policies.contracts import CommandStatus
    from mission_control.domain.policies.errors import CommandRejected

    control, repository, candidate, _ = await prepared()
    read = repository.get_family_admission_receipt

    async def corrupted(scope, run_id, issuer, command_id):
        receipt = await read(scope, run_id, issuer, command_id)
        if receipt is not None and command_id.startswith("stagegraph:admit-"):
            if corruption == "missing":
                return None
            result = receipt.command_result
            updates = (
                {"status": CommandStatus.STALE}
                if corruption == "status"
                else {"reason_code": "unauthorized_command"}
                if corruption == "reason"
                else {"command_fingerprint": "sha256:" + "f" * 64}
                if corruption == "fingerprint"
                else {}
            )
            return receipt.model_copy(
                update={
                    "command_result": result.model_copy(update=updates),
                    "family_mutation_fingerprint": "sha256:" + "e" * 64
                    if corruption == "family"
                    else receipt.family_mutation_fingerprint,
                }
            )
        return receipt

    monkeypatch.setattr(repository, "get_family_admission_receipt", corrupted)
    with pytest.raises(CommandRejected, match="persisted|reserve command"):
        await StageGraphDecisionService(control, repository).admit_operation(candidate)
    assert (
        await repository.get_family_head(
            candidate.request_scope, candidate.run_id, "stagegraph", StageGraphDecisionMutation
        )
        is None
    )
    assert (await control.get_run(candidate.request_scope, candidate.run_id)).version == 3


@pytest.mark.asyncio
async def test_different_proposal_cannot_borrow_authentic_rejection_receipt():
    import copy

    from mission_control.application.programs.service import orchestration_lifecycle_actor
    from mission_control.domain.policies.contracts import (
        LifecycleCommand,
        RecordAdmissionRejectionAction,
    )
    from mission_control.domain.policies.errors import CommandRejected
    from mission_control.domain.programs.contracts import StageGraphAdmissionRejectionMutation

    control, repository, candidate, _ = await prepared()
    assert not (
        await StageGraphDecisionService(control, repository).admit_operation(candidate)
    ).accepted
    head = await repository.get_family_head(
        candidate.request_scope,
        candidate.run_id,
        "stagegraph",
        StageGraphAdmissionRejectionMutation,
    )
    denied = LifecycleCommand.model_validate(head.decision_payload["rejected_command"])
    receipt = await repository.get_family_admission_receipt(
        candidate.request_scope, candidate.run_id, denied.idempotency_issuer, denied.command_id
    )
    payload = copy.deepcopy(head.decision_payload)
    payload["proposal"]["identity"]["candidate"]["stage_id"] = "other-stage"
    forged = head.model_copy(update={"mutation_id": "forged", "decision_payload": payload})
    command = LifecycleCommand(
        command_id="forged",
        idempotency_issuer=denied.idempotency_issuer,
        request_scope=candidate.request_scope,
        run_id=candidate.run_id,
        expected_run_version=3,
        actor=orchestration_lifecycle_actor(),
        action=RecordAdmissionRejectionAction(
            stage_id="other-stage",
            rejected_command_id=denied.command_id,
            rejected_command_issuer=denied.idempotency_issuer,
            rejected_command_fingerprint=receipt.command_result.command_fingerprint,
            rejected_family_fingerprint=receipt.family_mutation_fingerprint,
            exact_operation_request_ref=head.exact_operation_request_ref,
        ),
        reason="forged",
        occurred_at=candidate.occurred_at,
        correlation_id=candidate.correlation_id,
    )
    with pytest.raises(CommandRejected, match="differs"):
        await control.execute_family_admission(command, forged)


@pytest.mark.asyncio
async def test_cancel_between_denial_and_rejection_commit_preserves_cancellation(monkeypatch):
    from mission_control.domain.policies.contracts import (
        CancelAction,
        RecordAdmissionRejectionAction,
    )
    from tests.unit.run_control.test_run_control import command

    control, repository, candidate, _ = await prepared()
    execute = control.execute_family_admission

    async def cancel_before_record(cmd, mutation, **options):
        if isinstance(cmd.action, RecordAdmissionRejectionAction):
            await control.execute(command(candidate.run_id, 3, "cancel", CancelAction()))
        return await execute(cmd, mutation, **options)

    monkeypatch.setattr(control, "execute_family_admission", cancel_before_record)
    refused = await StageGraphDecisionService(control, repository).admit_operation(candidate)
    assert refused.reason_code == "stale_run_version"
    assert refused.projection == candidate.projection
    assert (
        await control.get_run(candidate.request_scope, candidate.run_id)
    ).phase.value == "cancelling"
    assert (
        await repository.get_family_head(
            candidate.request_scope, candidate.run_id, "stagegraph", StageGraphDecisionMutation
        )
        is None
    )


@pytest.mark.parametrize("kind", ["all", "any", "optional"])
def test_rejected_candidate_resolves_dependencies_without_creating_execution(kind):
    from mission_control.domain.authoring.contracts import DependencyClass, JoinKind

    graph = build_stagegraph_v2(
        logical_id="test.rejection-dependencies",
        title="Dependencies",
        description="Conclusive rejection",
        stages=(
            StageGraphStageSpec("a", output_slots=("out",)),
            StageGraphStageSpec("b", output_slots=("out",)),
            StageGraphStageSpec("consumer", depends_on=("a", "b")),
        ),
        max_concurrency=2,
    )
    if kind == "any":
        graph = graph.model_copy(
            update={
                "joins": tuple(
                    join.model_copy(update={"kind": JoinKind.ANY}) for join in graph.joins
                )
            }
        )
    if kind == "optional":
        graph = graph.model_copy(
            update={
                "dependencies": tuple(
                    edge.model_copy(update={"dependency_class": DependencyClass.OPTIONAL})
                    if edge.producer_stage_id == "a"
                    else edge
                    for edge in graph.dependencies
                )
            }
        )
    interpreter = StageGraphInterpreter(graph, effective_max_concurrency=2)
    projection = interpreter.initial_projection(ExecutionIdentity("run"), run_version=1)
    proposal = next(
        item
        for item in interpreter.frontier(projection, available_concurrency=2)
        if item.identity.stage_id == "a"
    )
    rejected = interpreter.apply_admission_rejection(
        projection, proposal, next_run_version=2, next_family_version=1
    )
    assert not rejected.producer_liabilities
    assert rejected.stages[proposal.identity.candidate.semantic_prefix].semantic_attempt == 0
    edge = next(edge for edge in graph.dependencies if edge.producer_stage_id == "a")
    assert rejected.dependencies[edge.dependency_id].disposition.value == (
        "omitted" if kind == "optional" else "failed"
    )
    assert interpreter.failure_completion(rejected) is None  # independent b remains admissible
    from tests.unit.orchestration.test_mp20_stagegraph_concluded_failure import _run

    completed = _run(interpreter, rejected, "b", "completed")
    ready = [
        item.identity.stage_id for item in interpreter.frontier(completed, available_concurrency=2)
    ]
    if kind == "all":
        assert ready == []
        assert interpreter.failure_completion(completed).can_terminalize
    else:
        assert ready == ["consumer"]
        assert interpreter.failure_completion(completed) is None


def test_admission_failure_does_not_close_existing_producer_liability():
    graph = build_stagegraph_v2(
        logical_id="test.open-liability",
        title="Liability",
        description="Other producer still running",
        stages=(StageGraphStageSpec("a"), StageGraphStageSpec("b")),
        max_concurrency=2,
    )
    interpreter = StageGraphInterpreter(graph, effective_max_concurrency=2)
    initial = interpreter.initial_projection(ExecutionIdentity("run"), run_version=1)
    b = next(
        item
        for item in interpreter.frontier(initial, available_concurrency=2)
        if item.identity.stage_id == "b"
    )
    running = interpreter.apply_admission(initial, b, next_run_version=2, next_family_version=1)
    a = interpreter.frontier(running, available_concurrency=1)[0]
    failed = interpreter.apply_admission_rejection(
        running, a, next_run_version=3, next_family_version=2
    )
    assert failed.producer_liabilities == running.producer_liabilities
    assert not interpreter.completion(failed).can_terminalize
    assert interpreter.failure_completion(failed) is None


@pytest.mark.asyncio
async def test_completion_refuses_mismatched_cycle_provenance(monkeypatch):
    import copy

    control, repository, candidate, interpreter = await prepared()
    service = StageGraphDecisionService(control, repository)
    refused = await service.admit_operation(candidate)
    read = repository.get_family_mutation

    async def mismatched(*args, **kwargs):
        fact = await read(*args, **kwargs)
        if fact is not None and fact.decision_kind == "admission_rejected":
            payload = copy.deepcopy(fact.decision_payload)
            payload["proposal"]["identity"]["candidate"]["stage_cycle_ordinal"] += 1
            return fact.model_copy(update={"decision_payload": payload})
        return fact

    monkeypatch.setattr(repository, "get_family_mutation", mismatched)
    run = await control.get_run(candidate.request_scope, candidate.run_id)
    with pytest.raises(ValueError, match="provenance"):
        await service.complete(
            StageGraphCompletionActivityRequest(
                run_id=candidate.run_id,
                request_scope=candidate.request_scope,
                projection=refused.projection,
                proposal=interpreter.failure_completion(refused.projection),
                workflow_type_digest=run.workflow_type_ref.digest,
                occurred_at=candidate.occurred_at,
                idempotency_issuer=candidate.idempotency_issuer,
                correlation_id=candidate.correlation_id,
            )
        )
    assert (
        await control.get_run(candidate.request_scope, candidate.run_id)
    ).phase.value == "active"


@pytest.mark.asyncio
@pytest.mark.parametrize("liability", ["reserved", "pending"])
async def test_other_producer_budget_liabilities_do_not_conclude_candidate(liability):
    from mission_control.application.execution.run_control_repository import (
        InMemoryRunControlRepository,
    )
    from mission_control.application.execution.service import (
        FamilyAdmissionRegistry,
        RunControlService,
    )
    from mission_control.application.programs.service import register_stagegraph_family_mutations
    from mission_control.domain.policies.contracts import (
        BudgetApplicability,
        RecordUsageAction,
        ReserveBudgetAction,
        StartAction,
    )
    from tests.unit.run_control.test_atomic_family_admission import admission_policies
    from tests.unit.run_control.test_run_control import ConfigurationVerifier, command, request

    _, _, candidate, _ = await prepared()
    repository = InMemoryRunControlRepository()
    registry = FamilyAdmissionRegistry()
    register_stagegraph_family_mutations(registry)
    control = RunControlService(repository, ConfigurationVerifier(), admission_policies(), registry)
    requested = request()
    requested = requested.model_copy(
        update={
            "budget_envelope": requested.budget_envelope.model_copy(
                update={
                    "dimensions": tuple(
                        item.model_copy(update={"applicability": BudgetApplicability.UNBOUNDED})
                        if item.dimension == "operation.attempts"
                        else item
                        for item in requested.budget_envelope.dimensions
                    )
                }
            )
        }
    )
    admitted = await control.admit(requested)
    assert admitted.run_id == candidate.run_id
    await control.execute(command(candidate.run_id, 1, "start", StartAction()))
    reserved = await control.execute(
        command(
            candidate.run_id,
            2,
            "other-producer",
            ReserveBudgetAction(reservation_id="other", amounts={"tokens.total": 80}),
        )
    )
    assert reserved.status.value == "accepted"
    if liability == "pending":
        pending = await control.execute(
            command(
                candidate.run_id,
                3,
                "other-pending",
                RecordUsageAction(
                    usage_id="other",
                    actual_amounts={},
                    pending_external_amounts={"tokens.total": 80},
                    reservation_id="other",
                ),
            )
        )
        assert pending.status.value == "accepted", pending.reason_code
        candidate = replace(
            candidate,
            projection=replace(candidate.projection, run_version=4),
            operation=candidate.operation.model_copy(
                update={
                    "operation": candidate.operation.operation.model_copy(
                        update={"run_control_revision": 5}
                    )
                }
            ),
        )
    before = await control.get_budget(candidate.request_scope, candidate.run_id)
    assert before.consumed.get("tokens.total", 0) == 0
    refused = await StageGraphDecisionService(control, repository).admit_operation(candidate)
    assert refused.reason_code == "budget_hard_cap_exceeded"
    assert refused.projection == candidate.projection
    assert await control.get_budget(candidate.request_scope, candidate.run_id) == before
    assert (
        await repository.get_family_head(
            candidate.request_scope, candidate.run_id, "stagegraph", StageGraphDecisionMutation
        )
        is None
    )
