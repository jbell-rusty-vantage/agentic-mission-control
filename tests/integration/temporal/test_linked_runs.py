from __future__ import annotations

import pytest
from temporalio.worker import Worker

from mission_control.adapters.temporal.linked_run_activities import (
    LinkedRunActivities,
    LinkedRunDecisionGateway,
)
from mission_control.adapters.temporal.linked_run_workflow import (
    LinkedRunObserverWorkflow,
    LinkedRunWorkflow,
)
from mission_control.adapters.temporal.workflow_sandbox import coordinator_workflow_runner
from mission_control.domain.composition.contracts import (
    DependencyAssessment,
    LinkedChildResultObservation,
    LinkedResultAdmissionProposal,
    LinkedRunContinuationState,
    ResultEvidenceAssessment,
    RunDependencyClass,
)
from mission_control.domain.policies.contracts import (
    RunPhase,
)
from mission_control.domain.policies.errors import AdmissionRejected, IdempotencyConflict
from mission_control.domain.programs.contracts import (
    StageGraphRunInput,
)
from tests.support.integration.temporal.linked_runs import (
    CHILD_WORKFLOW,
    DECISION_AUTHORITY,
    DIGEST,
    NOW,
    PARENT_ACCOUNT,
    actor,
    authority,
    linked_request,
    service_fixture,
)
from tests.support.temporal import FixtureChildWorkflow, start_workflow_env


class FixtureResultAssessor:
    def __init__(self) -> None:
        self.assessed_refs: list[str] = []

    async def assess(
        self,
        _observation: LinkedChildResultObservation,
        exact_output_ref: str,
    ) -> LinkedResultAdmissionProposal:
        self.assessed_refs.append(exact_output_ref)
        return LinkedResultAdmissionProposal(
            outcome="admit",
            assessment=ResultEvidenceAssessment(
                intended_purpose_satisfied=True,
                exact_version_compatible=True,
                ready=True,
                provenance_valid=True,
                permissions_valid=True,
                evaluation_evidence_valid=True,
                evidence_refs=(f"evaluation:{exact_output_ref}",),
            ),
            reason="fixture assessor accepted exact output evidence",
        )


@pytest.mark.asyncio
async def test_linked_request_retry_returns_one_child_reservation_and_link() -> None:
    service, control, run_control, _repository = service_fixture()
    request = linked_request()

    first = await service.request_child(request)
    replayed = await service.request_child(request)

    assert first == replayed
    assert first.child_run_id == "child-run"
    assert first.linked_budget_account_id == "budget-account:child"
    assert len(control.compilations) == 1
    assert control.compilations[0].parent_authority == authority()
    assert len(run_control.admissions) == 1
    admitted = run_control.admissions[0]
    assert admitted.budget_envelope.parent_account_id == PARENT_ACCOUNT

    with pytest.raises(IdempotencyConflict):
        await service.request_child(linked_request(purpose="conflicting payload"))


@pytest.mark.asyncio
async def test_linked_request_rejects_mismatched_exact_child_revision() -> None:
    service, control, _run_control, _repository = service_fixture()
    control.compiled_workflow_ref = CHILD_WORKFLOW.model_copy(
        update={"revision": 2, "digest": "sha256:" + "d" * 64}
    )

    with pytest.raises(AdmissionRejected, match="exact Workflow Type revision"):
        await service.request_child(linked_request())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("dependency", "terminal", "admitted", "blocks", "waits", "degrades", "may_complete"),
    [
        (RunDependencyClass.REQUIRED_BLOCKING, False, False, True, True, False, False),
        (RunDependencyClass.DEGRADABLE_BLOCKING, True, False, True, False, True, True),
        (RunDependencyClass.DEGRADABLE_NONBLOCKING, False, False, False, False, False, True),
        (RunDependencyClass.DETACHED_ADVISORY, False, False, False, False, False, True),
    ],
)
async def test_dependency_classes_have_declared_completion_behavior(
    dependency: RunDependencyClass,
    terminal: bool,
    admitted: bool,
    blocks: bool,
    waits: bool,
    degrades: bool,
    may_complete: bool,
) -> None:
    service, _control, _run_control, _repository = service_fixture(dependency)
    link = await service.request_child(linked_request(dependency))

    disposition = await service.dependency_disposition(
        "tenant-1",
        link.link_id,
        child_terminal=terminal,
        acceptable_result_admitted=admitted,
    )

    assert disposition.blocks_parent_completion is blocks
    assert disposition.wait_required is waits
    assert disposition.degradation_required_on_failure is degrades
    assert disposition.parent_may_complete is may_complete


@pytest.mark.asyncio
async def test_dependency_revision_result_admission_late_delivery_and_cancellation() -> None:
    service, _control, run_control, repository = service_fixture()
    link = await service.request_child(linked_request())
    revision = await service.revise_dependency(
        "tenant-1",
        link.link_id,
        RunDependencyClass.DEGRADABLE_NONBLOCKING,
        DependencyAssessment(
            affected_obligation_refs=("obligation:child",),
            affected_artifact_refs=("artifact:parent-draft",),
            affected_evaluation_refs=("evaluation:parent",),
            readiness_reassessment_required=True,
            reason="authorized parent policy revision",
        ),
        authority_ref=DECISION_AUTHORITY,
        actor=actor(),
        decided_at=NOW,
    )
    assert revision.revision == 2
    assert revision.prior_dependency_class == RunDependencyClass.REQUIRED_BLOCKING

    assessment = ResultEvidenceAssessment(
        intended_purpose_satisfied=True,
        exact_version_compatible=True,
        ready=True,
        provenance_valid=True,
        permissions_valid=True,
        evaluation_evidence_valid=True,
        evidence_refs=("evaluation:child-output",),
    )
    admitted = await service.decide_result(
        "tenant-1",
        link.link_id,
        "artifact:child:exact-v1",
        "admit",
        assessment,
        authority_ref=DECISION_AUTHORITY,
        actor=actor(),
        decided_at=NOW,
        reason="exact child result satisfies the parent purpose",
    )
    assert admitted.outcome == "admit"
    assert not admitted.late_result

    run_control.parent_phase = RunPhase.TERMINAL
    late = await service.decide_result(
        "tenant-1",
        link.link_id,
        "artifact:child:late-v2",
        "admit",
        assessment,
        authority_ref=DECISION_AUTHORITY,
        actor=actor(),
        decided_at=NOW,
        reason="preserve late result without parent mutation",
    )
    assert late.outcome == "defer"
    assert late.late_result
    assert len(await repository.list_result_decisions("tenant-1", link.link_id)) == 2

    cancellations = await service.cancellation_requests("tenant-1", "parent-run")
    assert len(cancellations) == 1
    assert cancellations[0].requested


@pytest.mark.asyncio
async def test_revised_dependency_controls_cancellation_and_decisions_are_link_bound() -> None:
    service, _control, _run_control, repository = service_fixture(
        RunDependencyClass.DEGRADABLE_BLOCKING
    )
    link = await service.request_child(linked_request(RunDependencyClass.DEGRADABLE_BLOCKING))
    await service.revise_dependency(
        "tenant-1",
        link.link_id,
        RunDependencyClass.DEGRADABLE_NONBLOCKING,
        DependencyAssessment(
            affected_output_refs=("output:advisory-child",),
            readiness_reassessment_required=True,
            reason="retain advisory work without blocking parent cancellation",
        ),
        authority_ref=DECISION_AUTHORITY,
        actor=actor(),
        decided_at=NOW,
    )
    cancellations = await service.cancellation_requests("tenant-1", "parent-run")
    assert not cancellations[0].requested

    assessment = ResultEvidenceAssessment(
        intended_purpose_satisfied=True,
        exact_version_compatible=True,
        ready=True,
        provenance_valid=True,
        permissions_valid=True,
        evaluation_evidence_valid=True,
    )
    valid = await service.decide_result(
        "tenant-1",
        link.link_id,
        "artifact:child:bound",
        "admit",
        assessment,
        authority_ref=DECISION_AUTHORITY,
        actor=actor(),
        decided_at=NOW,
        reason="create a valid decision fixture",
    )
    with pytest.raises(IdempotencyConflict, match="do not match"):
        await repository.commit_result_decision(
            "tenant-1",
            valid.model_copy(
                update={
                    "decision_id": "wrong-link-runs",
                    "exact_output_ref": "artifact:child:wrong-link",
                    "child_run_id": "different-child",
                }
            ),
        )


def test_continue_as_new_contract_preserves_semantic_state() -> None:
    state = LinkedRunContinuationState(
        run_id="parent-run",
        next_execution_epoch=2,
        workflow_cycle=3,
        semantic_counters={"operation_attempt": 7, "stage_cycle": 2},
        pending_wait_ids=("wait:child",),
        link_ids=("link:child",),
        accepted_dependency_revision_ids=("dependency-revision:2",),
        accepted_result_decision_ids=("result-decision:1",),
        reservation_ids=("reservation:child",),
        authority_ref=DECISION_AUTHORITY,
    )

    replayed = LinkedRunContinuationState.model_validate_json(state.model_dump_json())
    assert replayed == state


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("initial_dependency", "effective_dependency", "expected_child_status"),
    [
        (
            RunDependencyClass.REQUIRED_BLOCKING,
            RunDependencyClass.REQUIRED_BLOCKING,
            "completed",
        ),
        (
            RunDependencyClass.DEGRADABLE_NONBLOCKING,
            RunDependencyClass.DEGRADABLE_NONBLOCKING,
            "completed",
        ),
        (
            RunDependencyClass.REQUIRED_BLOCKING,
            RunDependencyClass.DEGRADABLE_NONBLOCKING,
            "cancelled",
        ),
    ],
)
async def test_temporal_mapping_executes_admitted_child_as_distinct_workflow(
    initial_dependency: RunDependencyClass,
    effective_dependency: RunDependencyClass,
    expected_child_status: str,
) -> None:
    service, _control, _run_control, repository = service_fixture(initial_dependency)
    link = await service.request_child(linked_request(initial_dependency))
    if initial_dependency != effective_dependency:
        await service.revise_dependency(
            "tenant-1",
            link.link_id,
            effective_dependency,
            DependencyAssessment(
                affected_output_refs=("output:child",),
                readiness_reassessment_required=True,
                reason="exercise accepted Temporal dependency revision",
            ),
            authority_ref=DECISION_AUTHORITY,
            actor=actor(),
            decided_at=NOW,
        )
    execution_binding = await service.execution_binding("tenant-1", link.link_id)
    assert execution_binding.effective_dependency_class == effective_dependency
    child_input = StageGraphRunInput(
        run_id=link.child_run_id,
        request_scope=link.request_scope,
        effective_configuration_digest=link.child_effective_configuration_digest,
        workflow_type_digest=DIGEST,
        blueprint_digest=DIGEST,
        blueprint={
            "logical_id": (
                "child.cancel" if expected_child_status == "cancelled" else "child.graph"
            ),
            "title": "Child graph",
            "description": "Minimal child workflow fixture",
            "family": "StageGraph",
            "stages": [{"stage_id": "child"}],
        },
    )
    environment = await start_workflow_env()

    async with environment:
        assessor = FixtureResultAssessor()
        decisions = LinkedRunDecisionGateway(
            service,
            assessor,
            actor=actor(),
            authority_ref=DECISION_AUTHORITY,
        )
        activities = LinkedRunActivities(decisions)
        continuation = LinkedRunContinuationState(
            run_id="parent-run",
            next_execution_epoch=2,
            workflow_cycle=0,
            semantic_counters={"operation_attempt": 1},
            pending_wait_ids=("wait:unrelated",),
            link_ids=(link.link_id,),
            accepted_dependency_revision_ids=(),
            accepted_result_decision_ids=(),
            reservation_ids=(link.linked_budget_account_id,),
            authority_ref=DECISION_AUTHORITY,
        )
        async with Worker(
            environment.client,
            task_queue="linked-run-composition",
            workflows=[
                LinkedRunWorkflow,
                LinkedRunObserverWorkflow,
                FixtureChildWorkflow,
            ],
            workflow_runner=coordinator_workflow_runner(),
            activities=[
                activities.resolve_execution_binding,
                activities.resolve_child_observation,
            ],
        ):
            result = await environment.client.execute_workflow(
                LinkedRunWorkflow.run,
                {
                    "request_scope": link.request_scope,
                    "link_id": link.link_id,
                    "dependency_revision_id": execution_binding.dependency_revision_id,
                    "child_task_queue": "linked-run-composition",
                    "child_input": {
                        "run_id": child_input.run_id,
                        "request_scope": child_input.request_scope,
                        "effective_configuration_digest": (
                            child_input.effective_configuration_digest
                        ),
                        "workflow_type_digest": child_input.workflow_type_digest,
                        "blueprint_digest": child_input.blueprint_digest,
                        "blueprint": child_input.blueprint,
                    },
                    "continuation_state": continuation.model_dump(mode="json"),
                    "force_continue_as_new": True,
                },
                id="linked-run-parent-fixture",
                task_queue="linked-run-composition",
            )
            if effective_dependency == RunDependencyClass.DEGRADABLE_NONBLOCKING:
                assert result["disposition"] == "launched_nonblocking"
                observer = environment.client.get_workflow_handle(result["observer_workflow_id"])
                result = await observer.result()

    assert result["child_status"] == expected_child_status
    assert result["disposition"] == (
        "admitted" if expected_child_status == "completed" else "failed"
    )
    assert result["execution_epoch"] == 2
    assert LinkedRunContinuationState.model_validate(result["continuation_state"]) == continuation
    assert result["child_run_id"] == link.child_run_id
    expected_outputs = ["artifact:child:exact-v1"] if expected_child_status == "completed" else []
    assert result["admitted_output_refs"] == expected_outputs
    assert assessor.assessed_refs == expected_outputs
    assert len(await repository.list_result_decisions("tenant-1", link.link_id)) == (
        1 if expected_child_status == "completed" else 0
    )
    assert "child_result" not in result


@pytest.mark.asyncio
async def test_degradable_child_failure_requires_governed_resolution() -> None:
    dependency = RunDependencyClass.DEGRADABLE_BLOCKING
    service, _control, _run_control, repository = service_fixture(dependency)
    link = await service.request_child(linked_request(dependency))
    decisions = LinkedRunDecisionGateway(
        service,
        FixtureResultAssessor(),
        actor=actor(),
        authority_ref=DECISION_AUTHORITY,
    )
    activities = LinkedRunActivities(decisions)
    environment = await start_workflow_env()

    async with environment:
        async with Worker(
            environment.client,
            task_queue="linked-run-degradation",
            workflows=[
                LinkedRunWorkflow,
                LinkedRunObserverWorkflow,
                FixtureChildWorkflow,
            ],
            workflow_runner=coordinator_workflow_runner(),
            activities=[
                activities.resolve_execution_binding,
                activities.resolve_child_observation,
            ],
        ):
            result = await environment.client.execute_workflow(
                LinkedRunWorkflow.run,
                {
                    "request_scope": link.request_scope,
                    "link_id": link.link_id,
                    "dependency_revision_id": None,
                    "child_task_queue": "linked-run-degradation",
                    "child_input": {
                        "run_id": link.child_run_id,
                        "request_scope": link.request_scope,
                        "effective_configuration_digest": (
                            link.child_effective_configuration_digest
                        ),
                        "workflow_type_digest": DIGEST,
                        "blueprint_digest": DIGEST,
                        "blueprint": {
                            "logical_id": "child.fail",
                            "title": "Failing child",
                            "description": "Exercise governed degradation",
                            "family": "StageGraph",
                            "stages": [{"stage_id": "child"}],
                        },
                    },
                },
                id="linked-run-degradation-parent",
                task_queue="linked-run-degradation",
            )

    assert result["disposition"] == "degraded"
    assert result["admitted_output_refs"] == []
    assert await repository.list_result_decisions("tenant-1", link.link_id) == ()
