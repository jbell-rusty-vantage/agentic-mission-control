"""Noncognitive review admission remains available after factual producer overage."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from mission_control.application.execution.run_control_repository import (
    InMemoryRunControlRepository,
)
from mission_control.application.execution.service import FamilyAdmissionRegistry, RunControlService
from mission_control.application.programs.service import (
    StageGraphDecisionService,
    orchestration_lifecycle_actor,
    register_stagegraph_family_mutations,
)
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.stagegraph_builder import (
    StageGraphStageSpec,
    build_stagegraph_v2,
)
from mission_control.domain.execution.contracts import (
    OperationAttemptIdentity,
    OperationWorkflowRequest,
)
from mission_control.domain.policies.contracts import (
    AdmitHumanGateAction,
    CommandStatus,
    RecordUsageAction,
    ReserveBudgetAction,
    StartAction,
)
from mission_control.domain.programs.contracts import (
    ExecutionIdentity,
    StageGraphAdmissionActivityRequest,
    StageGraphDecisionMutation,
)
from mission_control.domain.programs.human_gate import HumanGateSpec
from mission_control.domain.programs.interpreter import StageGraphInterpreter
from tests.unit.operations.test_operation_execution import operation_request
from tests.unit.run_control.test_atomic_family_admission import admission_policies
from tests.unit.run_control.test_run_control import ConfigurationVerifier, command, request

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


def test_gate_frontier_and_running_gate_do_not_consume_cognitive_slots():
    interpreter = StageGraphInterpreter(
        graph(), effective_max_concurrency=1, control_gate_keys=frozenset({"review"})
    )
    projection = interpreter.initial_projection(ExecutionIdentity("run"), run_version=2)
    frontier = interpreter.frontier(projection, available_concurrency=0)
    assert [item.identity.stage_id for item in frontier] == ["review"]
    assert frontier[0].reservation == {}
    admitted = interpreter.apply_admission(
        projection, frontier[0], next_run_version=3, next_family_version=1
    )
    assert interpreter.running_concurrency(admitted) == 0
    assert [
        item.identity.stage_id for item in interpreter.frontier(admitted, available_concurrency=1)
    ] == ["work"]


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


@pytest.mark.asyncio
async def test_gate_atomic_admission_over_cap_is_idempotent_and_cognition_still_denied():
    control, repository, candidate = await fixture()
    before = await control.get_budget("tenant-1", candidate.run_id)
    service = StageGraphDecisionService(control, repository, human_gates=TrustedGates())
    result = await service.admit_operation(candidate)
    assert result.accepted
    assert await service.admit_operation(candidate) == result
    assert await control.get_budget("tenant-1", candidate.run_id) == before
    assert before.consumed["tokens.total"] == 112976
    head = await repository.get_family_head(
        "tenant-1", candidate.run_id, "stagegraph", StageGraphDecisionMutation
    )
    assert head and head.decision_kind == "control_admitted"
    assert not (await control.get_budget("tenant-1", candidate.run_id)).reservations
    denied = await control.execute(
        command(
            candidate.run_id,
            result.projection.run_version,
            "more-cognition",
            ReserveBudgetAction(reservation_id="next", amounts={"tokens.total": 1}),
        )
    )
    assert denied.reason_code == "budget_hard_cap_exceeded"
    # Exact atomic receipt can be replayed without inventing a second activation.
    receipts = await repository.get_family_admission_receipt(
        "tenant-1",
        candidate.run_id,
        "operator",
        "stagegraph:admit-" + sha256_digest(candidate.proposal.identity.semantic_key)[7:],
    )
    assert receipts is not None


@pytest.mark.asyncio
async def test_new_gate_admission_fails_closed_without_trusted_provider():
    control, repository, candidate = await fixture()
    with pytest.raises(ValueError, match="not configured"):
        await StageGraphDecisionService(control, repository).admit_operation(candidate)
    assert (await control.get_run("tenant-1", candidate.run_id)).version == 3


@pytest.mark.asyncio
async def test_changed_reviewer_cannot_borrow_control_admission():
    control, repository, candidate = await fixture()
    changed = replace(candidate, human_gate=GATE.model_copy(update={"reviewers": ("impostor",)}))
    with pytest.raises(ValueError, match="mismatch"):
        await StageGraphDecisionService(
            control, repository, human_gates=TrustedGates()
        ).admit_operation(changed)


@pytest.mark.asyncio
async def test_plain_control_action_cannot_bypass_atomic_family_orchestration():
    control, _, candidate = await fixture()
    action = AdmitHumanGateAction(
        gate_key="review",
        gate_spec_digest="sha256:" + "a" * 64,
        exact_operation_request_ref="operation-request:fake",
    )
    cmd = command(candidate.run_id, 3, "plain-control", action).model_copy(
        update={"actor": orchestration_lifecycle_actor()}
    )
    result = await control.execute(cmd)
    assert result.status == CommandStatus.REJECTED
    assert result.reason_code == "invalid_control_admission"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "drift",
    [
        None,
        "configuration",
        "blueprint",
        "semantic_ref",
        "reviewer",
        "gate_set",
        "missing_definition",
        "missing_template",
        "template_config",
        "template_scope",
    ],
)
async def test_actual_manifest_gate_provider_checks_frozen_scope(drift):
    from types import SimpleNamespace

    from mission_control.application.programs.control_admission import (
        ManifestStageGraphHumanGateProvider,
    )
    from mission_control.domain.authoring.manifest import Behavior
    from tests.unit.authoring.test_completion_support import definition

    control, _, candidate = await fixture()
    run = await control.get_run(candidate.request_scope, candidate.run_id)
    authored = definition()
    node = authored.program.model_copy(
        update={
            "key": "review",
            "behavior": Behavior.HUMAN_GATE,
            "nodes": (),
            "body": {
                "task": {
                    "kind": "REVIEW",
                    "prompt": GATE.prompt,
                    "reviewers": list(GATE.reviewers),
                    "packet": list(GATE.packet_sources),
                }
            },
        }
    )
    authored = authored.model_copy(update={"program": node})

    class Definitions:
        async def run_subscriptions(self, scope, run_id):
            assert (scope, run_id) == (candidate.request_scope, candidate.run_id)
            return (
                None
                if drift == "missing_definition"
                else {"definition": authored.model_dump(mode="json")}
            )

    class Configurations:
        async def retrieve_for_admission(self, digest):
            assert digest == run.effective_configuration_digest
            return SimpleNamespace(digest=digest, selected_blueprint=graph())

    candidate = replace(
        candidate,
        semantic_input_binding_ref=f"semantic-input:manifest:{candidate.run_id}",
        effective_configuration_digest=run.effective_configuration_digest,
    )
    if drift == "configuration":
        candidate = replace(candidate, effective_configuration_digest="sha256:" + "0" * 64)
    elif drift == "blueprint":
        candidate = replace(candidate, blueprint={**candidate.blueprint, "title": "drift"})
    elif drift == "semantic_ref":
        candidate = replace(candidate, semantic_input_binding_ref="semantic-input:fork:unverified")
    elif drift == "reviewer":
        candidate = replace(candidate, human_gate=GATE.model_copy(update={"reviewers": ("wrong",)}))
    elif drift == "gate_set":
        candidate = replace(candidate, control_gate_keys=("work",))

    class Templates:
        async def get_template(self, **kwargs):
            if drift == "missing_template":
                raise ValueError("immutable template absent")
            assert kwargs == {
                "semantic_input_binding_ref": f"semantic-input:manifest:{candidate.run_id}",
                "operation_request_key": candidate.proposal.operation_request_key,
                "request_scope": candidate.request_scope,
                "run_id": candidate.run_id,
            }
            return SimpleNamespace(
                request_scope=(
                    "other-scope" if drift == "template_scope" else candidate.request_scope
                ),
                effective_configuration_digest=(
                    "sha256:" + "0" * 64
                    if drift == "template_config"
                    else run.effective_configuration_digest
                ),
            )

    provider = ManifestStageGraphHumanGateProvider(
        Definitions(), Configurations(), control, Templates()
    )
    if drift is None:
        assert await provider.verify(candidate) == (GATE,)
    else:
        with pytest.raises(ValueError):
            await provider.verify(candidate)


def test_legacy_and_fork_interpretation_still_reserve_and_hold_cognitive_capacity():
    interpreter = StageGraphInterpreter(graph(), effective_max_concurrency=1)
    projection = interpreter.initial_projection(ExecutionIdentity("fork-run"), run_version=1)
    assert interpreter.frontier(projection, available_concurrency=0) == ()
    proposal = interpreter.frontier(projection, available_concurrency=1)[0]
    assert proposal.reservation["operation.attempts"] == 1
    assert proposal.reservation["concurrency.slots"] == 1
    assert proposal.reservation["tokens.total"] == 1


@pytest.mark.asyncio
async def test_control_atomic_retry_does_not_accept_tampered_prior_projection():
    control, repository, candidate = await fixture()
    service = StageGraphDecisionService(control, repository, human_gates=TrustedGates())
    assert (await service.admit_operation(candidate)).accepted
    from mission_control.domain.policies.errors import IdempotencyConflict

    changed = replace(candidate, correlation_id="different-command-body")
    with pytest.raises(IdempotencyConflict):
        await service.admit_operation(changed)


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


@pytest.mark.asyncio
async def test_attributed_review_result_is_accepted_after_overage_without_budget_reset():
    await accept_gate_result(*(await fixture()))


@pytest.mark.asyncio
@pytest.mark.parametrize("hold", ["pause", "wait", "cancel"])
async def test_control_admission_honors_authoritative_hold_or_stop(hold):
    from mission_control.domain.policies.contracts import (
        CancelAction,
        PauseAction,
        PauseDecision,
        SetWaitAction,
        WaitCondition,
    )

    control, repository, candidate = await fixture()
    if hold == "pause":
        action = PauseAction(
            decision=PauseDecision(
                decision_id="hold",
                scope=frozenset({"stage:review"}),
                reason="Hold review",
                authority_ref="authority:lifecycle",
            ),
            runnable_work_remains=False,
        )
    elif hold == "wait":
        action = SetWaitAction(
            condition=WaitCondition(
                condition_id="hold",
                kind="dependency",
                scope=frozenset({"stage:review"}),
                verification_ref="proof:hold",
                timeout_policy_ref="policy:wait",
            ),
            runnable_work_remains=False,
        )
    else:
        action = CancelAction()
    held = await control.execute(command(candidate.run_id, 3, "hold", action))
    assert held.status == CommandStatus.ACCEPTED
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
    result = await StageGraphDecisionService(
        control, repository, human_gates=TrustedGates()
    ).admit_operation(candidate)
    assert not result.accepted
    assert (
        result.reason_code
        == {
            "pause": "control_admission_paused",
            "wait": "control_admission_waiting",
            "cancel": "run_is_cancelling",
        }[hold]
    )
    assert (
        await repository.get_family_head(
            candidate.request_scope, candidate.run_id, "stagegraph", StageGraphDecisionMutation
        )
        is None
    )


@pytest.mark.parametrize(
    ("reference", "enabled", "expected"),
    [
        ("semantic-input:manifest:run", True, {"review"}),
        ("semantic-input:manifest:run", False, set()),
        ("semantic-input:fork:trusted-fork-request", True, set()),
        ("semantic-input:manifest:other-run", True, set()),
    ],
)
def test_temporal_patch_compatibility_keeps_fork_and_old_histories_on_legacy_path(
    reference, enabled, expected
):
    from types import SimpleNamespace

    from mission_control.adapters.temporal.workflows.stagegraph import _noncognitive_gate_keys

    assert _noncognitive_gate_keys(
        SimpleNamespace(run_id="run", semantic_input_binding_ref=reference),
        {"review": GATE},
        enabled=enabled,
    ) == frozenset(expected)
