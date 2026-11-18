from __future__ import annotations

from dataclasses import dataclass

import pytest

from biotech_mission_adapters.application.web_research.web_research_semantic_binding import (
    SemanticServiceWebResearchOperationBindingAuthor,
    WebResearchOperationBindingRequest,
)
from mission_control.application.coordinator.coordinator_launch import (
    CoordinatorWorkflowLaunchService,
)
from mission_control.application.coordinator.coordinator_semantic_bindings import (
    WorkflowSemanticBindingProviderRouter,
)
from mission_control.application.execution.operations.operation_execution import (
    InMemoryOperationBindingRepository,
)
from mission_control.application.execution.operations.semantic_operation_bindings import (
    SemanticOperationBindingTemplates,
    SemanticOperationExecutionBindingService,
)
from mission_control.application.programs.orchestration_binding_repository import (
    InMemoryRunSemanticInputBindingRepository,
    RunSemanticInputBindingService,
)
from mission_control.application.programs.orchestration_routing import (
    BoundStageOperationExecutor,
    SemanticHandlerRegistry,
    SemanticRoutingError,
)
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import DefinitionKind, ExactDefinitionRef
from mission_control.domain.policies.contracts import AdmissionDecision, DecisionStatus
from mission_control.domain.programs.contracts import (
    StageCandidateIdentity,
    StageExecutionIdentity,
    StageOperationRequest,
    StageOperationResult,
)
from tests.support.unit.coordinator.coordinator_launch_preparation import NOW, SCOPE, launch_fixture
from tests.support.unit.coordinator.coordinator_semantic_binding_integration import (
    _operation_template,
    _schema_context_provider,
    _supporting_graph_provider,
)


class AcceptingAdmission:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id

    async def admit(self, request):
        return AdmissionDecision(
            request_scope=request.request_scope,
            idempotency_issuer=request.idempotency_issuer,
            request_id=request.request_id,
            request_fingerprint=sha256_digest(request.model_dump(mode="json")),
            status=DecisionStatus.ACCEPTED,
            run_id=self.run_id,
            reason_code="accepted",
            reason="integration admission accepted",
            recorded_at=NOW,
        )


class CapturingDispatcher:
    def __init__(self) -> None:
        self.binding = None

    async def prepare_bound(
        self,
        request_scope,
        run_id,
        *,
        semantic_binding,
        binding_service,
        **_kwargs,
    ):
        self.binding = semantic_binding
        binding_ref = await binding_service.freeze(semantic_binding)
        return {
            "request_scope": request_scope,
            "run_id": run_id,
            "semantic_input_binding_ref": binding_ref,
        }


class CompletingStageHandler:
    async def execute(self, request, binding):
        return StageOperationResult(
            identity=request.identity,
            disposition="completed",
            output_refs=("evidence:oeb-authority-consumed",),
            output_contract_ref=binding.output_contract_ref,
        )


@dataclass
class CapturingSubmissions:
    payload: object | None = None

    async def submit(self, workflow_input, *, workflow_id, blueprint_family):
        self.payload = workflow_input
        return type(
            "Submission",
            (),
            {
                "workflow_id": workflow_id,
                "temporal_run_id": f"temporal:{blueprint_family.value}",
            },
        )()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("family", "run_id", "expected_operations"),
    [
        (
            "StageGraph",
            "run-full-chain-a",
            {"semantic_selector", "independent_reviewer"},
        ),
        ("GoalDirected", "run-full-chain-c", {"goal_executor", "goal_verifier"}),
    ],
)
async def test_full_coordinator_chain_freezes_real_oebs_before_dispatch(
    family: str,
    run_id: str,
    expected_operations: set[str],
) -> None:
    operation_repository = InMemoryOperationBindingRepository()
    provider = (
        _schema_context_provider(operation_repository)
        if family == "StageGraph"
        else await _supporting_graph_provider(operation_repository)
    )
    router = WorkflowSemanticBindingProviderRouter(
        {
            "schema-context-selection": provider,
            "supporting-graph-reconciliation": provider,
        }
    )
    preparation, tickets, proposal, context = await launch_fixture(
        family,
        initial_goal=(
            "Reconcile the bounded supporting graph." if family == "GoalDirected" else None
        ),
        semantic_bindings=router,
    )
    public = await preparation.prepare(proposal, context)
    semantic_repository = InMemoryRunSemanticInputBindingRepository()
    dispatcher = CapturingDispatcher()
    submissions = CapturingSubmissions()
    launcher = CoordinatorWorkflowLaunchService(
        tickets=tickets,
        admission=AcceptingAdmission(run_id),
        dispatcher=dispatcher,
        submissions=submissions,
        semantic_bindings=router,
        binding_service=RunSemanticInputBindingService(semantic_repository),
    )

    handle = await launcher.launch(public.ticket_id, context)

    assert handle.run_id == run_id
    assert dispatcher.binding is not None
    assert submissions.payload is not None
    if family == "StageGraph":
        refs = {
            route.handler.operation_execution_binding_ref
            for route in dispatcher.binding.stage_handlers
            if route.handler.operation_execution_binding_ref is not None
        }
    else:
        # CON-BP-GOAL-DIRECTED-V1 routes the independent verifier through its own slot.
        executor_refs = {
            route.handler.operation_execution_binding_ref
            for route in dispatcher.binding.goal_operation_handlers
            if route.handler.operation_execution_binding_ref is not None
        }
        assert dispatcher.binding.goal_verifier is not None
        verifier_ref = dispatcher.binding.goal_verifier.operation_execution_binding_ref
        assert verifier_ref is not None
        assert verifier_ref not in executor_refs
        refs = executor_refs | {verifier_ref}
    assert len(refs) == len(expected_operations)
    persisted = {
        operation_id: await operation_repository.get_binding(
            f"{run_id}:operation:{operation_id}:attempt:1"
        )
        for operation_id in expected_operations
    }
    assert all(binding is not None for binding in persisted.values())
    assert {binding.binding_id for binding in persisted.values() if binding is not None} == refs
    assert all(
        binding.effective_configuration_digest == handle.effective_configuration_digest
        for binding in persisted.values()
        if binding is not None
    )
    assert dispatcher.binding.operation_execution_binding_refs == tuple(sorted(refs))

    if family == "StageGraph":
        request = StageOperationRequest(
            identity=StageExecutionIdentity(
                run_id=run_id,
                execution_epoch=1,
                candidate=StageCandidateIdentity(
                    stage_id="semantic_selector",
                    mapped_instance_presence=0,
                    mapped_instance_id="NO_MAPPED_INSTANCE",
                    workflow_cycle_ordinal=0,
                    stage_cycle_ordinal=0,
                    operation_slot_id="execute",
                ),
                semantic_attempt=1,
            ),
            idempotency_key="operation:semantic-selector:1",
            objective="Consume the frozen selector authority.",
            input_refs=(),
            reservation_id="reservation:selector",
            reservation={"operation.attempts": 1},
            workspace_namespace=f"run/{run_id}/semantic-selector",
            request_scope=SCOPE,
            semantic_input_binding_ref=dispatcher.binding.binding_id,
            effective_configuration_digest=handle.effective_configuration_digest,
            blueprint_digest=handle.blueprint_ref.digest,
        )
        registry = SemanticHandlerRegistry()
        registry.register_stage(
            "schema-context.select",
            1,
            CompletingStageHandler(),
        )
        with pytest.raises(
            SemanticRoutingError,
            match="Operation Execution Binding repository",
        ):
            await BoundStageOperationExecutor(
                semantic_repository,
                registry,
            ).execute(request)
        result = await BoundStageOperationExecutor(
            semantic_repository,
            registry,
            operation_repository,
        ).execute(request)
        assert result.output_refs == ("evidence:oeb-authority-consumed",)


@pytest.mark.asyncio
async def test_scenario_d_operation_author_uses_shared_three_stage_freezer() -> None:
    operation_repository = InMemoryOperationBindingRepository()
    templates = SemanticOperationBindingTemplates(
        operations={
            stage_id: _operation_template(stage_id)
            for stage_id in (
                "search_firecrawl",
                "search_tavily",
                "browser_verify",
            )
        }
    )
    author = SemanticServiceWebResearchOperationBindingAuthor(
        templates,
        SemanticOperationExecutionBindingService(operation_repository),
        operation_repository,
    )
    preparation, tickets, proposal, context = await launch_fixture("StageGraph")
    public = await preparation.prepare(proposal, context)
    ticket = await tickets.get(public.ticket_id, request_scope=SCOPE)
    assert ticket is not None
    bindings = await author.author(
        WebResearchOperationBindingRequest(
            request_scope=SCOPE,
            run_id="run-scenario-d-oeb",
            effective_configuration_digest=ticket.effective_configuration_digest,
            runtime_profile_ref=ExactDefinitionRef(
                kind=DefinitionKind.RUNTIME_PROFILE,
                logical_id="web-research-browser-verification-runtime-v1",
                revision=1,
                digest=sha256_digest("runtime"),
            ),
            workspace_template_ref=ExactDefinitionRef(
                kind=DefinitionKind.WORKSPACE_TEMPLATE,
                logical_id="web-research-browser-verification-workspace-v1",
                revision=1,
                digest=sha256_digest("workspace"),
            ),
            selected_capability_refs=(),
            created_at=NOW,
        ),
        ticket=ticket,
    )
    assert set(bindings) == {
        "search_firecrawl",
        "search_tavily",
        "browser_verify",
    }
    assert all(
        binding.operation_id == stage_id
        and binding.run_id == "run-scenario-d-oeb"
        and binding.effective_configuration_digest == ticket.effective_configuration_digest
        for stage_id, binding in bindings.items()
    )
