from __future__ import annotations

from types import SimpleNamespace

import pytest

from mission_control.application.coordinator.coordinator_launch import (
    CoordinatorWorkflowLaunchService,
    RuntimePlanPreparation,
)
from mission_control.application.coordinator.coordinator_results import (
    CoordinatorResultService,
    InMemoryWorkflowResultRepository,
)
from mission_control.bootstrap.coordinator_composition import CoordinatorLaunchProductionInputs
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import (
    DefinitionKind,
    ExactDefinitionRef,
)
from mission_control.domain.coordinator.launch import (
    BlueprintFamily,
    LaunchTicketUnavailable,
    PreparedLaunchTicket,
    StageGraphResultDetails,
    WorkflowResultRecord,
)
from mission_control.domain.graph_runtime.definitions import (
    ContentAddressedRef,
    GraphAssemblySpecV2,
    RunPlanV3,
    RuntimeDefinitionKind,
    UnavailableStageSurface,
)
from mission_control.domain.policies.contracts import (
    RunOutcome,
    RunPhase,
)
from tests.support.unit.coordinator.coordinator_launch_preparation import (
    NOW,
    SCOPE,
    TENANT,
    FixtureSemanticBindingProvider,
    launch_fixture,
)


class UnexpectedAdmission:
    async def admit(self, _request):
        raise AssertionError("the tested launch guard must reject before admission")


class FixtureRuntimePlans:
    def __init__(self, *, unavailable: bool = False) -> None:
        self.unavailable = unavailable

    async def prepare_runtime_plan(self, _proposal, configuration, semantic_plan):
        implementation = ExactDefinitionRef(
            kind=DefinitionKind.WORKFLOW_IMPLEMENTATION,
            logical_id="workflow.fixture.v3",
            revision=1,
            digest=sha256_digest("workflow.fixture.v3"),
        )
        graph = GraphAssemblySpecV2(
            graph_assembly_ref=ContentAddressedRef(
                kind=RuntimeDefinitionKind.GRAPH_ASSEMBLY,
                logical_id="graph.fixture.v3",
                schema_version="1",
                digest=sha256_digest("graph.fixture.v3"),
            ),
            state_schema_digest=sha256_digest("state.fixture.v3"),
            reducer_registry_digest=sha256_digest("reducers.fixture.v3"),
            operation_registry_digest=sha256_digest("operations.fixture.v3"),
            stage_requirements=(),
            stage_execution_bindings=(),
            compatibility_manifest_digest=sha256_digest("compatibility.fixture.v3"),
        )
        plan = RunPlanV3.create(
            plan_id=f"plan:{semantic_plan.plan_ref}",
            effective_run_configuration_digest=configuration.digest,
            semantic_binding_ref=semantic_plan.plan_ref,
            workflow_implementation_ref=implementation,
            graph_assembly=graph,
            alias_evidence_digest=sha256_digest(
                [item.model_dump(mode="json") for item in configuration.alias_evidence]
            ),
        )
        unavailable = (
            (
                UnavailableStageSurface(
                    stage_id="fixture",
                    capability_id="literature_search",
                    reason_code="authority_denied",
                    maturity="stable",
                    fallback="reject",
                    detail="outside effective authority",
                ),
            )
            if self.unavailable
            else ()
        )
        return RuntimePlanPreparation(run_plan=plan, unavailable_surfaces=unavailable)


@pytest.mark.asyncio
async def test_stagegraph_rejects_initial_goal_and_public_ticket_redacts_private_input() -> None:
    service, _tickets, proposal, context = await launch_fixture(
        "StageGraph",
        initial_goal="not allowed",
    )
    with pytest.raises(LaunchTicketUnavailable, match="does not accept"):
        await service.prepare(proposal, context)

    service, tickets, proposal, context = await launch_fixture("StageGraph")
    public = await service.prepare(proposal, context)
    payload = public.model_dump(mode="json")
    assert "initial_goal" not in payload
    assert "frozen_run_request" not in payload
    assert "semantic_binding_plan" not in payload
    assert public.semantic_binding_plan_ref
    assert public.semantic_binding_plan_digest
    assert public.initial_goal_digest is None
    private = await tickets.get(public.ticket_id, request_scope=SCOPE)
    assert private is not None
    assert private.frozen_run_request.effective_configuration_digest == (
        public.effective_configuration_digest
    )
    assert private.semantic_binding_plan is not None
    assert private.semantic_binding_plan.plan_digest == (public.semantic_binding_plan_digest)
    assert PreparedLaunchTicket.model_validate(private.model_dump(mode="json")) == private


@pytest.mark.asyncio
async def test_preparation_persists_frozen_v3_runtime_plan() -> None:
    service, tickets, proposal, context = await launch_fixture(
        "StageGraph",
        runtime_plans=FixtureRuntimePlans(),
    )

    public = await service.prepare(proposal, context)
    private = await tickets.get(public.ticket_id, request_scope=SCOPE)

    assert private is not None
    assert private.runtime_run_plan is not None
    assert private.runtime_run_plan.schema_version == "belllabs.run-plan.v3"
    assert private.runtime_run_plan.effective_run_configuration_digest == (
        private.effective_configuration_digest
    )
    assert private.runtime_unavailable_surfaces == ()
    assert private.launchable
    assert "runtime_run_plan" not in public.model_dump(mode="json")


@pytest.mark.asyncio
async def test_preparation_fails_closed_for_unavailable_required_runtime_surface() -> None:
    service, tickets, proposal, context = await launch_fixture(
        "StageGraph",
        runtime_plans=FixtureRuntimePlans(unavailable=True),
    )

    public = await service.prepare(proposal, context)
    private = await tickets.get(public.ticket_id, request_scope=SCOPE)

    assert private is not None
    assert not public.launchable
    assert private.runtime_unavailable_surfaces[0].reason_code == "authority_denied"
    assert any("required_runtime_surfaces_unavailable" in item for item in public.warnings)


@pytest.mark.asyncio
async def test_launch_rejects_ticket_with_unavailable_runtime_surface() -> None:
    preparation, tickets, proposal, context = await launch_fixture(
        "StageGraph",
        runtime_plans=FixtureRuntimePlans(unavailable=True),
    )
    public = await preparation.prepare(proposal, context)

    class UnexpectedAdmission:
        async def admit(self, _request):
            raise AssertionError("unavailable runtime surfaces must reject before admission")

    service = CoordinatorWorkflowLaunchService(
        tickets=tickets,
        admission=UnexpectedAdmission(),
        dispatcher=None,  # type: ignore[arg-type]
        submissions=None,  # type: ignore[arg-type]
    )
    with pytest.raises(LaunchTicketUnavailable, match="unavailable required runtime surfaces"):
        await service.launch(public.ticket_id, context)


@pytest.mark.asyncio
async def test_production_composition_requires_and_freezes_v3_plan() -> None:
    legacy_preparation, tickets, proposal, context = await launch_fixture("StageGraph")
    inputs = CoordinatorLaunchProductionInputs(
        compiler=legacy_preparation._compiler,
        admission_preview=legacy_preparation._admission,
        admission=UnexpectedAdmission(),
        tickets=tickets,
        dispatcher=None,  # type: ignore[arg-type]
        submissions=None,  # type: ignore[arg-type]
        semantic_bindings=FixtureSemanticBindingProvider(),
        runtime_plans=FixtureRuntimePlans(),
        binding_service=None,  # type: ignore[arg-type]
    )
    production_preparation, _launcher = inputs.build()

    public = await production_preparation.prepare(proposal, context)
    frozen = await tickets.get(public.ticket_id, request_scope=SCOPE)

    assert frozen is not None and frozen.runtime_run_plan is not None
    assert frozen.runtime_run_plan.schema_version == "belllabs.run-plan.v3"


@pytest.mark.asyncio
async def test_production_composed_launcher_rejects_legacy_ticket_without_v3_plan() -> None:
    legacy_preparation, tickets, proposal, context = await launch_fixture("StageGraph")
    legacy_ticket = await legacy_preparation.prepare(proposal, context)
    inputs = CoordinatorLaunchProductionInputs(
        compiler=legacy_preparation._compiler,
        admission_preview=legacy_preparation._admission,
        admission=UnexpectedAdmission(),
        tickets=tickets,
        dispatcher=None,  # type: ignore[arg-type]
        submissions=None,  # type: ignore[arg-type]
        semantic_bindings=FixtureSemanticBindingProvider(),
        runtime_plans=FixtureRuntimePlans(),
        binding_service=None,  # type: ignore[arg-type]
    )
    _preparation, launcher = inputs.build()

    with pytest.raises(LaunchTicketUnavailable, match="no frozen RunPlanV3"):
        await launcher.launch(legacy_ticket.ticket_id, context)


@pytest.mark.asyncio
async def test_goaldirected_requires_goal_and_freezes_only_its_digest_publicly() -> None:
    service, _tickets, proposal, context = await launch_fixture("GoalDirected")
    with pytest.raises(LaunchTicketUnavailable, match="non-empty"):
        await service.prepare(proposal, context)

    goal = "Reconcile supporting graph evidence within the admitted protected scope."
    service, tickets, proposal, context = await launch_fixture(
        "GoalDirected",
        initial_goal=goal,
    )
    public = await service.prepare(proposal, context)
    assert public.initial_goal_digest == sha256_digest(goal)
    assert goal not in public.model_dump_json()
    private = await tickets.get(public.ticket_id, request_scope=SCOPE)
    assert private is not None and private.initial_goal == goal


@pytest.mark.asyncio
async def test_preparation_rejects_changed_policy_environment_caller_or_tenant() -> None:
    service, _tickets, proposal, context = await launch_fixture("StageGraph")
    for update in (
        {"caller_id": "another-caller"},
        {"tenant_scope": "another-tenant"},
        {"policy_snapshot_digest": sha256_digest("changed-policy")},
        {"environment_snapshot_digest": sha256_digest("changed-environment")},
    ):
        with pytest.raises(RuntimeError):
            await service.prepare(proposal, context.model_copy(update=update))


@pytest.mark.asyncio
async def test_result_polling_returns_phase_then_exact_typed_terminal_result() -> None:
    class Runs:
        phase = RunPhase.ACTIVE

        async def get_run(self, request_scope, run_id):
            return SimpleNamespace(
                request_scope=request_scope,
                run_id=run_id,
                phase=self.phase,
            )

    runs = Runs()
    records = InMemoryWorkflowResultRepository()
    service = CoordinatorResultService(runs=runs, results=records)
    _preparation, _tickets, _proposal, context = await launch_fixture("StageGraph")
    pending = await service.get_workflow_result("run-result-1", context)
    assert pending.phase == "active" and pending.result is None

    result = WorkflowResultRecord(
        run_id="run-result-1",
        tenant_scope=TENANT,
        request_scope=SCOPE,
        blueprint_family=BlueprintFamily.STAGE_GRAPH,
        terminal_outcome=RunOutcome.COMPLETED,
        output_contract_results={"output:fixture": {"accepted": True}},
        artifact_refs=("artifact:fixture",),
        evidence_refs=("evidence:fixture",),
        operation_binding_refs=("binding:fixture",),
        usage_summary={"tokens.total": 10},
        family_result=StageGraphResultDetails(
            execution_epoch=1,
            workflow_cycles=0,
            stage_cycles={"research": 1},
            operation_attempts={"research": 1},
            output_refs={"report": ("artifact:fixture",)},
        ),
        completed_at=NOW,
    )
    await records.save(result)
    runs.phase = RunPhase.TERMINAL
    completed = await service.get_workflow_result("run-result-1", context)
    assert completed.result == result
