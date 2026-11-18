"""Builders, constants and fakes that other test files import.

Moved from tests/integration/temporal/test_linked_runs.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from mission_control.application.programs.linked_runs import (
    InMemoryLinkedRunRepository,
    LinkedRunService,
)
from mission_control.domain.authoring.contracts import (
    AuthorityCeiling,
    BudgetCeiling,
    CompilationContext,
    CompileInvocation,
    DefinitionKind,
    DefinitionSelector,
    EnvironmentAvailability,
    ExactDefinitionRef,
    LinkedRunSlotConstraint,
    RunInputManifestRef,
)
from mission_control.domain.composition.contracts import LinkedRunRequest, RunDependencyClass
from mission_control.domain.policies.contracts import (
    ActorContext,
    AdmissionDecision,
    BudgetApplicability,
    BudgetDimensionLimit,
    BudgetEnvelope,
    BudgetState,
    DecisionStatus,
    RunPhase,
    RunRequest,
)

NOW = datetime(2026, 7, 19, 21, 0, tzinfo=UTC)
DIGEST = "sha256:" + "a" * 64
CHILD_DIGEST = "sha256:" + "b" * 64
PARENT_ACCOUNT = "budget-account:parent"
PARENT_AUTHORITY = "workflow_run.parent:parent-run:sponsor"
DECISION_AUTHORITY = "authority:composition"


def ref(kind: DefinitionKind, name: str, digest: str = DIGEST) -> ExactDefinitionRef:
    return ExactDefinitionRef(kind=kind, logical_id=name, revision=1, digest=digest)


CHILD_WORKFLOW = ref(DefinitionKind.WORKFLOW_TYPE, "child.workflow")
INPUT_MANIFEST = RunInputManifestRef(manifest_id="child-input", revision=1, digest=DIGEST)


def actor() -> ActorContext:
    return ActorContext(
        actor_id="composition-worker",
        authority_refs=frozenset({PARENT_AUTHORITY, DECISION_AUTHORITY}),
        permissions=frozenset(
            {
                "workflow_run.admit",
                "workflow_run.revise_dependency",
                "workflow_run.admit_linked_result",
            }
        ),
    )


def authority() -> AuthorityCeiling:
    return AuthorityCeiling(
        capabilities=frozenset({"sandbox.execute"}),
        budgets=BudgetCeiling(dimensions={"units": 10}),
        max_concurrency=1,
    )


def compile_invocation() -> CompileInvocation:
    return CompileInvocation(
        workflow_type=DefinitionSelector(exact=CHILD_WORKFLOW),
        blueprint=DefinitionSelector(exact=ref(DefinitionKind.BLUEPRINT, "child.graph")),
        control_profile=DefinitionSelector(
            exact=ref(DefinitionKind.CONTROL_PROFILE, "child.control")
        ),
        runtime_profile=DefinitionSelector(
            exact=ref(DefinitionKind.RUNTIME_PROFILE, "child.runtime")
        ),
        workspace_template=DefinitionSelector(
            exact=ref(DefinitionKind.WORKSPACE_TEMPLATE, "child.workspace")
        ),
        evaluation_profile=DefinitionSelector(
            exact=ref(DefinitionKind.EVALUATION_PROFILE, "child.evaluation")
        ),
        input_manifest=INPUT_MANIFEST,
        caller_authority=authority(),
        environment=EnvironmentAvailability(
            capabilities=frozenset({"sandbox.execute"}),
            runtime_bindings=frozenset({"python-3.12"}),
        ),
        context=CompilationContext(
            compilation_id="compile-child-request-1",
            compiled_at=NOW,
            actor_id=actor().actor_id,
            authority_subject_id=actor().actor_id,
            authority_scope="tenant-1",
        ),
    )


def linked_request(
    dependency: RunDependencyClass = RunDependencyClass.REQUIRED_BLOCKING,
    *,
    purpose: str = "produce exact child evidence",
) -> LinkedRunRequest:
    return LinkedRunRequest(
        request_scope="tenant-1",
        parent_run_id="parent-run",
        slot_id="child_work",
        request_revision=1,
        target_workflow_type_ref=CHILD_WORKFLOW,
        compilation=compile_invocation(),
        child_budget=BudgetEnvelope(
            dimensions=(
                BudgetDimensionLimit(
                    dimension="units",
                    applicability=BudgetApplicability.BOUNDED,
                    hard_cap=5,
                ),
            ),
            baseline_reservations={"units": 5},
        ),
        dependency_class=dependency,
        purpose=purpose,
        actor=actor(),
        requested_at=NOW,
        authority_request_refs=frozenset({PARENT_AUTHORITY}),
        permission_assessment_refs=("permission-assessment:child",),
        causation_id="stage:request-child",
        correlation_id="parent-run:composition",
    )


class FakeControlPlane:
    def __init__(self, dependency: RunDependencyClass) -> None:
        self.compilations: list[CompileInvocation] = []
        self.compiled_workflow_ref = CHILD_WORKFLOW
        self.slot = LinkedRunSlotConstraint(
            slot_id="child_work",
            allowed_child_workflow_types=frozenset({CHILD_WORKFLOW}),
            dependency_class=dependency.value,
            wait_policy=(
                "wait"
                if dependency
                in {
                    RunDependencyClass.REQUIRED_BLOCKING,
                    RunDependencyClass.DEGRADABLE_BLOCKING,
                }
                else "continue"
            ),
            cancellation_policy=(
                "request_cancel"
                if dependency == RunDependencyClass.REQUIRED_BLOCKING
                else "allow_continue"
            ),
            result_admission_policy="linked-result:exact-evidence@1",
            delegation_ceiling=authority(),
            budget_reservation_ceiling=BudgetCeiling(dimensions={"units": 5}),
        )

    async def retrieve_for_admission(self, _digest: str) -> SimpleNamespace:
        return SimpleNamespace(linked_run_slots=(self.slot,))

    async def compile(self, invocation: CompileInvocation) -> SimpleNamespace:
        self.compilations.append(invocation)
        return SimpleNamespace(
            digest=CHILD_DIGEST,
            workflow_type=SimpleNamespace(logical_id=CHILD_WORKFLOW.logical_id),
            source_refs=(self.compiled_workflow_ref,),
            input_manifest=INPUT_MANIFEST,
        )


class FakeRunControl:
    def __init__(self) -> None:
        self.parent_phase = RunPhase.ACTIVE
        self.admissions: list[RunRequest] = []
        self.parent_budget = BudgetState(
            account_id=PARENT_ACCOUNT,
            run_id="parent-run",
            limits=(
                BudgetDimensionLimit(
                    dimension="units",
                    applicability=BudgetApplicability.BOUNDED,
                    hard_cap=10,
                ),
            ),
        )
        self.child_budget = BudgetState(
            account_id="budget-account:child",
            run_id="child-run",
            parent_account_id=PARENT_ACCOUNT,
            limits=(
                BudgetDimensionLimit(
                    dimension="units",
                    applicability=BudgetApplicability.BOUNDED,
                    hard_cap=5,
                ),
            ),
        )

    async def get_run(self, _scope: str, run_id: str) -> SimpleNamespace:
        if run_id == "parent-run":
            return SimpleNamespace(
                phase=self.parent_phase,
                effective_configuration_digest=DIGEST,
            )
        return SimpleNamespace(phase=RunPhase.TERMINAL)

    async def get_budget(self, _scope: str, run_id: str) -> BudgetState:
        return self.parent_budget if run_id == "parent-run" else self.child_budget

    async def admit(self, request: RunRequest) -> AdmissionDecision:
        self.admissions.append(request)
        return AdmissionDecision(
            request_scope="tenant-1",
            idempotency_issuer="linked-run:parent-run",
            request_id=request.request_id,
            request_fingerprint=DIGEST,
            status=DecisionStatus.ACCEPTED,
            run_id="child-run",
            reason_code="accepted",
            reason="independently compiled and admitted",
            recorded_at=NOW,
        )


def service_fixture(
    dependency: RunDependencyClass = RunDependencyClass.REQUIRED_BLOCKING,
) -> tuple[
    LinkedRunService,
    FakeControlPlane,
    FakeRunControl,
    InMemoryLinkedRunRepository,
]:
    control = FakeControlPlane(dependency)
    run_control = FakeRunControl()
    repository = InMemoryLinkedRunRepository()
    service = LinkedRunService(control, run_control, repository)  # type: ignore[arg-type]
    return service, control, run_control, repository
