"""Builders, constants and fakes that other test files import.

Moved from tests/unit/control_plane/test_control_plane.py.
"""

from __future__ import annotations

from datetime import UTC, datetime

from mission_control.adapters.storage.control_plane_payloads import InMemoryPayloadStore
from mission_control.application.authoring.control_plane_repository import (
    DefinitionRepository,
    InMemoryDefinitionRepository,
)
from mission_control.application.authoring.service import ControlPlaneService
from mission_control.application.ports.payloads import ContentAddressedPayloadStore
from mission_control.domain.authoring.contracts import (
    AuthorityCeiling,
    AvailabilityRequirement,
    BudgetCeiling,
    CompilationContext,
    CompileInvocation,
    ControlProfileDefinition,
    DefinitionSelector,
    EnvironmentAvailability,
    EvaluationProfileDefinition,
    PublishRequest,
    RunInputManifestRef,
    RunOverlay,
    RuntimeProfileDefinition,
    WorkflowTypeDefinition,
    WorkflowWorkspaceContract,
    WorkspaceSlot,
    WorkspaceTemplateDefinition,
)
from mission_control.domain.authoring.extensions import ExtensionRegistry
from mission_control.domain.authoring.stagegraph_builder import (
    StageGraphStageSpec,
    build_stagegraph_v2,
)

NOW = datetime(2026, 1, 2, 3, 4, tzinfo=UTC)
DIGEST = "sha256:" + "1" * 64


def authority(*capabilities: str, budget: int = 100, concurrency: int = 4) -> AuthorityCeiling:
    return AuthorityCeiling(
        capabilities=frozenset(capabilities),
        budgets=BudgetCeiling(dimensions={"units": budget}),
        max_concurrency=concurrency,
    )


async def publish(service: ControlPlaneService, definition: object, expected: int = 0):
    return await service.publish(
        PublishRequest(
            definition=definition,  # type: ignore[arg-type]
            actor_id="publisher",
            published_at=NOW,
            expected_head_revision=expected,
        )
    )


async def configured_service(
    *,
    externalize_above_bytes: int = 256_000,
    repository: DefinitionRepository | None = None,
    payload_store: ContentAddressedPayloadStore | None = None,
) -> tuple[ControlPlaneService, DefinitionRepository, dict[str, object]]:
    repository = repository or InMemoryDefinitionRepository()
    service = ControlPlaneService(
        repository,
        ExtensionRegistry(),
        payload_store or InMemoryPayloadStore(),
        externalize_above_bytes=externalize_above_bytes,
    )
    blueprint = await publish(
        service,
        build_stagegraph_v2(
            logical_id="generic.graph",
            title="Generic graph",
            description="Contract-only test graph",
            stages=(
                StageGraphStageSpec(
                    stage_id="first",
                    output_slots=("result",),
                ),
            ),
        ),
    )
    control = await publish(
        service,
        ControlProfileDefinition(
            logical_id="generic.control",
            title="Generic control",
            description="No workflow-specific defaults",
            blueprint_ref=blueprint.ref,
            selected_variants=frozenset({"default"}),
            authority_ceiling=authority("sandbox", "evaluate", budget=80, concurrency=3),
            overlayable_fields=frozenset(
                {"capabilities", "budgets", "max_concurrency", "variants"}
            ),
            strengthen_only_fields=frozenset({"budgets", "max_concurrency"}),
        ),
    )
    runtime = await publish(
        service,
        RuntimeProfileDefinition(
            logical_id="generic.runtime",
            title="Generic runtime",
            description="Pinned compatibility requirement",
            binding="python-3.12",
            required_capabilities=frozenset({"sandbox"}),
            capability_requirements=(
                AvailabilityRequirement(
                    capability="optional-observability",
                    when_unavailable="degrade",
                    decision_reason="run without optional observability",
                ),
            ),
        ),
    )
    workspace = await publish(
        service,
        WorkspaceTemplateDefinition(
            logical_id="generic.workspace",
            title="Generic workspace",
            description="One governed output location",
            slots=(
                WorkspaceSlot(
                    name="output",
                    path="/workspace/output",
                    access="exclusive_write",
                    purpose="generic output",
                ),
            ),
            required_capabilities=frozenset({"sandbox"}),
        ),
    )
    evaluation = await publish(
        service,
        EvaluationProfileDefinition(
            logical_id="generic.evaluation",
            title="Generic evaluation",
            description="Pinned gate contract placeholder",
            gate_contract_refs=frozenset({"contract:generic-evaluation@1"}),
            required_capabilities=frozenset({"evaluate"}),
        ),
    )
    workflow = await publish(
        service,
        WorkflowTypeDefinition(
            logical_id="generic.workflow",
            title="Generic workflow",
            description="A contract fixture, not a product workflow",
            purpose="Exercise control-plane binding",
            non_goals=frozenset({"Define product semantics"}),
            input_admission_contract="contract:generic-input@1",
            invariants=frozenset({"contract:generic-invariant@1"}),
            allowed_blueprints=frozenset({blueprint.ref}),
            allowed_control_profiles=frozenset({control.ref}),
            allowed_runtime_profiles=frozenset({runtime.ref}),
            allowed_workspace_templates=frozenset({workspace.ref}),
            allowed_evaluation_profiles=frozenset({evaluation.ref}),
            authority_ceiling=authority("sandbox", "evaluate", budget=90, concurrency=4),
            workspace_contract=WorkflowWorkspaceContract(
                slots=(
                    WorkspaceSlot(
                        name="output",
                        path="/workspace/output",
                        access="exclusive_write",
                        purpose="generic output",
                    ),
                )
            ),
        ),
    )
    return (
        service,
        repository,
        {
            "workflow": workflow,
            "blueprint": blueprint,
            "control": control,
            "runtime": runtime,
            "workspace": workspace,
            "evaluation": evaluation,
        },
    )


def invocation(
    records: dict[str, object], *, overlay: RunOverlay | None = None
) -> CompileInvocation:
    def selector(name: str) -> DefinitionSelector:
        return DefinitionSelector(exact=records[name].ref)  # type: ignore[attr-defined]

    return CompileInvocation(
        workflow_type=selector("workflow"),
        blueprint=selector("blueprint"),
        control_profile=selector("control"),
        runtime_profile=selector("runtime"),
        workspace_template=selector("workspace"),
        evaluation_profile=selector("evaluation"),
        input_manifest=RunInputManifestRef(manifest_id="manifest-1", revision=1, digest=DIGEST),
        overlay=overlay or RunOverlay(),
        caller_authority=authority("sandbox", "evaluate", "unused", budget=70, concurrency=2),
        parent_authority=authority("sandbox", "evaluate", budget=60, concurrency=2),
        environment=EnvironmentAvailability(
            capabilities=frozenset({"sandbox", "evaluate", "available-not-authorized"}),
            runtime_bindings=frozenset({"python-3.12"}),
        ),
        context=CompilationContext(
            compilation_id="compilation-1",
            compiled_at=NOW,
            actor_id="caller",
            authority_subject_id="caller",
            authority_scope="tenant-1",
        ),
    )
