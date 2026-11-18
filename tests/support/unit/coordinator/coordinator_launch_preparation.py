"""Builders, constants and fakes that other test files import.

Moved from tests/unit/coordinator/test_coordinator_launch_preparation.py.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from biotech_mission_adapters.domain.schema_grounding.definitions import (
    register_schema_grounding_extensions,
    schema_grounding_definitions,
)
from mission_control.adapters.storage.control_plane_payloads import InMemoryPayloadStore
from mission_control.application.authoring.control_plane_repository import (
    InMemoryDefinitionRepository,
)
from mission_control.application.authoring.service import ControlPlaneService
from mission_control.application.coordinator.coordinator_launch import (
    CoordinatorLaunchPreparationService,
    InMemoryLaunchTicketRepository,
)
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import (
    CompilationContext,
    CompileInvocation,
    DefinitionSelector,
    EnvironmentAvailability,
    GoalDirectedBlueprint,
    PublishRequest,
    RunInputManifestRef,
    StageGraphBlueprint,
    WorkflowImplementationBindingDefinition,
)
from mission_control.domain.authoring.extensions import ExtensionRegistry
from mission_control.domain.coordinator.launch import (
    AdmissionPreviewDecision,
    BlueprintFamily,
    LaunchRequestContext,
    RunAdmissionSpec,
    SemanticBindingPlan,
    WorkflowLaunchProposal,
)
from mission_control.domain.policies.contracts import (
    ActorContext,
    BudgetApplicability,
    BudgetDimensionLimit,
    BudgetEnvelope,
)
from mission_control.domain.programs.bindings import (
    GoalOperationHandlerBinding,
    RunSemanticInputBinding,
    SemanticHandlerBinding,
    SemanticInputPayload,
    StageHandlerBinding,
)

NOW = datetime(2026, 7, 25, 16, 0, tzinfo=UTC)
POLICY = sha256_digest("policy-v1")
ENVIRONMENT = sha256_digest("environment-v1")
SCOPE = "tenant-1/research"
TENANT = "tenant-1"
ACTOR = ActorContext(
    actor_id="coordinator-1",
    authority_refs=frozenset({"authority:coordinator"}),
    permissions=frozenset({"workflow_run.admit"}),
)


class AcceptingPreview:
    async def preview(self, _request):
        return AdmissionPreviewDecision(
            accepted=True,
            reason_code="accepted",
            reason="admission preview accepted",
        )


class FixtureSemanticBindingProvider:
    async def prepare(self, proposal, configuration):
        family = (
            BlueprintFamily.STAGE_GRAPH
            if isinstance(configuration.selected_blueprint, StageGraphBlueprint)
            else BlueprintFamily.GOAL_DIRECTED
        )
        return SemanticBindingPlan.create(
            plan_ref=f"semantic-plan:{proposal.idempotency_key}",
            blueprint_family=family,
            exact_input_refs=(configuration.input_manifest.manifest_id,),
            payload={"fixture": proposal.idempotency_key},
        )

    async def author(self, plan, ticket, *, run_id):
        handler = SemanticHandlerBinding(
            handler_id="fixture.handler",
            handler_revision=1,
            input=SemanticInputPayload.from_value(
                schema_ref="schema:fixture:v1",
                value=plan.payload,
            ),
            output_contract_ref="schema:fixture-output:v1",
        )
        values = {
            "request_scope": ticket.request_scope,
            "run_id": run_id,
            "blueprint_family": ticket.blueprint_family.value,
            "effective_configuration_digest": ticket.effective_configuration_digest,
            "blueprint_digest": ticket.blueprint_ref.digest,
            "created_at": ticket.prepared_at,
        }
        if ticket.blueprint_family == BlueprintFamily.STAGE_GRAPH:
            return RunSemanticInputBinding.create(
                **values,
                stage_handlers=(StageHandlerBinding(stage_id="fixture", handler=handler),),
            )
        return RunSemanticInputBinding.create(
            **values,
            goal_operation_handlers=(
                GoalOperationHandlerBinding(
                    operation_class="fixture",
                    handler=handler,
                ),
            ),
            goal_verifier=handler,
            goal_handoff=handler,
        )


async def launch_fixture(
    family: str,
    *,
    idempotency_key: str = "launch-1",
    initial_goal: str | None = None,
    semantic_bindings=None,
    runtime_plans=None,
):
    repository = InMemoryDefinitionRepository()
    extensions = ExtensionRegistry()
    register_schema_grounding_extensions(extensions)
    control_plane = ControlPlaneService(
        repository,
        extensions,
        InMemoryPayloadStore(),
    )
    published = {}
    revisions = {}
    implementations: list[object] = []
    for definition in schema_grounding_definitions():
        key = (definition.kind, definition.logical_id)
        record = await control_plane.publish(
            PublishRequest(
                definition=definition,
                actor_id="fixture-publisher",
                published_at=NOW,
                expected_head_revision=revisions.get(key, 0),
            )
        )
        revisions[key] = record.ref.revision
        published[definition.logical_id] = record
        if isinstance(definition, WorkflowImplementationBindingDefinition):
            implementations.append(record)

    if family == "StageGraph":
        workflow = published["schema-context-selection"]
        blueprint = published["schema-context-selection-v1"]
        control = published["schema-context-selection-control-v1"]
        runtime = published["schema-context-selection-runtime-v1"]
        workspace = published["schema-context-selection-workspace-v1"]
        evaluation = published["schema-context-selection-evaluation-v1"]
        configuration = published["schema-context-selection-official-v1"]
    else:
        workflow = published["supporting-graph-reconciliation"]
        blueprint = published["supporting-graph-reconciliation-goal-directed-v1"]
        control = published["supporting-graph-reconciliation-goal-directed-control-v1"]
        runtime = published["supporting-graph-reconciliation-runtime-v1"]
        workspace = published["supporting-graph-reconciliation-workspace-v1"]
        evaluation = published["supporting-graph-reconciliation-evaluation-v1"]
        configuration = published["supporting-graph-reconciliation-official-v1"]

    selected_blueprint = blueprint.definition
    assert isinstance(selected_blueprint, StageGraphBlueprint | GoalDirectedBlueprint)
    authority = control.definition.authority_ceiling
    invocation = CompileInvocation(
        workflow_type=DefinitionSelector(exact=workflow.ref),
        blueprint=DefinitionSelector(exact=blueprint.ref),
        control_profile=DefinitionSelector(exact=control.ref),
        runtime_profile=DefinitionSelector(exact=runtime.ref),
        workspace_template=DefinitionSelector(exact=workspace.ref),
        evaluation_profile=DefinitionSelector(exact=evaluation.ref),
        workflow_configuration=DefinitionSelector(exact=configuration.ref),
        input_manifest=RunInputManifestRef(
            manifest_id=f"{family.lower()}-input",
            revision=1,
            digest=sha256_digest({"family": family, "input": "fixture"}),
        ),
        caller_authority=authority,
        parent_authority=authority,
        environment=EnvironmentAvailability(
            capabilities=authority.capabilities,
            runtime_bindings=frozenset({runtime.definition.binding}),
            secret_refs=runtime.definition.required_secrets,
        ),
        context=CompilationContext(
            compilation_id=f"compile-{idempotency_key}",
            compiled_at=NOW,
            actor_id=ACTOR.actor_id,
            authority_subject_id=ACTOR.actor_id,
            authority_scope=SCOPE,
        ),
    )
    proposal = WorkflowLaunchProposal(
        request_scope=SCOPE,
        tenant_scope=TENANT,
        compilation=invocation,
        admission=RunAdmissionSpec(
            actor=ACTOR,
            budget_envelope=BudgetEnvelope(
                dimensions=(
                    BudgetDimensionLimit(
                        dimension="workflow.cycles",
                        applicability=BudgetApplicability.BOUNDED,
                        hard_cap=4,
                    ),
                )
            ),
            requested_at=NOW,
            correlation_id=f"correlation-{idempotency_key}",
            sponsorship_ref="sponsorship:fixture",
            approval_refs=("approval:fixture",),
            delegation_authority_refs=ACTOR.authority_refs,
            admission_evidence_refs=("fixture:admission",),
        ),
        initial_goal=initial_goal,
        policy_snapshot_digest=POLICY,
        environment_snapshot_digest=ENVIRONMENT,
        idempotency_issuer=ACTOR.actor_id,
        idempotency_key=idempotency_key,
    )
    context = LaunchRequestContext(
        caller_id=ACTOR.actor_id,
        tenant_scope=TENANT,
        request_scope=SCOPE,
        approval_refs=("approval:fixture",),
        policy_snapshot_digest=POLICY,
        environment_snapshot_digest=ENVIRONMENT,
        observed_at=NOW,
    )
    tickets = InMemoryLaunchTicketRepository()
    service = CoordinatorLaunchPreparationService(
        compiler=control_plane,
        admission=AcceptingPreview(),
        tickets=tickets,
        semantic_bindings=semantic_bindings or FixtureSemanticBindingProvider(),
        runtime_plans=runtime_plans,
        ttl=timedelta(minutes=15),
    )
    return service, tickets, proposal, context
