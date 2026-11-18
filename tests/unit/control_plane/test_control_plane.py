from __future__ import annotations

from datetime import datetime

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

from mission_control.adapters.storage.control_plane_payloads import InMemoryPayloadStore
from mission_control.application.authoring.control_plane_repository import (
    InMemoryDefinitionRepository,
)
from mission_control.application.authoring.service import ControlPlaneService
from mission_control.domain.authoring.canonical import canonical_json
from mission_control.domain.authoring.contracts import (
    AliasRef,
    CompilationContext,
    DefinitionKind,
    DefinitionSelector,
    GoalDirectedBlueprint,
    MoveAliasRequest,
    NamespacedExtension,
    PublishDraftRequest,
    RetireRequest,
    RunOverlay,
    SaveDraftRequest,
    SecretRef,
    StageNode,
    WorkflowConfigurationDefinition,
    WorkspaceSlot,
    WorkspaceTemplateDefinition,
)
from mission_control.domain.authoring.errors import (
    CompilationRejected,
    DefinitionConflict,
    PayloadIntegrityError,
    RetiredDefinition,
)
from mission_control.domain.authoring.extensions import ExtensionRegistry
from mission_control.domain.authoring.fixtures import GENERIC_GOAL_DIRECTED
from mission_control.domain.authoring.stagegraph_builder import (
    StageGraphStageSpec,
    build_stagegraph_v2,
)
from tests.support.unit.control_plane.control_plane import (
    NOW,
    authority,
    configured_service,
    invocation,
    publish,
)


def test_contracts_forbid_unknown_fields_and_invalid_stage_graphs() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        StageNode(stage_id="stage", unknown=True)  # type: ignore[call-arg]

    with pytest.raises(ValidationError, match="dependency cycle"):
        build_stagegraph_v2(
            logical_id="cycle",
            title="Cycle",
            description="Invalid",
            stages=(
                StageGraphStageSpec(stage_id="a", depends_on=("b",), output_slots=("result",)),
                StageGraphStageSpec(stage_id="b", depends_on=("a",), output_slots=("result",)),
            ),
        )

    with pytest.raises(ValueError, match="must declare an output slot"):
        build_stagegraph_v2(
            logical_id="output",
            title="Output",
            description="Invalid",
            stages=(
                StageGraphStageSpec(stage_id="a"),
                StageGraphStageSpec(stage_id="b", depends_on=("a",)),
            ),
        )


def test_canonicalization_sorts_sets_but_preserves_lists() -> None:
    assert canonical_json({"items": frozenset({"b", "a"})}) == canonical_json(
        {"items": frozenset({"a", "b"})}
    )
    assert canonical_json({"items": ["a", "b"]}) != canonical_json({"items": ["b", "a"]})


def test_goal_directed_requires_bounded_independent_verification() -> None:
    goal = GoalDirectedBlueprint.model_validate(
        {
            **GENERIC_GOAL_DIRECTED.model_dump(mode="python"),
            "logical_id": "generic.goal",
            "title": "Generic goal",
            "description": "Contract fixture",
            "objective_contract": "contract:objective@1",
            "acceptance_contract": "contract:acceptance@1",
            "max_iterations": 2,
        }
    )
    assert goal.independent_verification_required is True
    with pytest.raises(ValidationError):
        GoalDirectedBlueprint.model_validate(
            {
                **goal.model_dump(mode="python"),
                "max_iterations": 0,
            }
        )


def test_compilation_context_rejects_naive_time() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        CompilationContext(
            compilation_id="naive-time",
            compiled_at=datetime(2026, 1, 2, 3, 4),  # noqa: DTZ001 - naive input is under test
            actor_id="caller",
            authority_subject_id="caller",
            authority_scope="tenant-1",
        )


def test_extension_payload_cannot_embed_secret_values() -> None:
    with pytest.raises(ValidationError, match="typed SecretRef"):
        NamespacedExtension(
            namespace="belllabs.workflow",
            schema_version="1",
            discriminator="fixture",
            payload={"api_key": "must-not-persist"},
        )
    extension = NamespacedExtension(
        namespace="belllabs.workflow",
        schema_version="1",
        discriminator="secret-reference",
        payload={
            "client_secret": SecretRef(provider="aws-secrets-manager", key="belllabs/runtime")
        },
    )
    assert isinstance(extension.payload["client_secret"], SecretRef)


def test_workspace_template_rejects_duplicate_slot_names() -> None:
    slot = WorkspaceSlot(
        name="output",
        path="/workspace/output",
        access="exclusive_write",
        purpose="generic output",
    )
    with pytest.raises(ValidationError, match="slot names must be unique"):
        WorkspaceTemplateDefinition(
            logical_id="duplicate.workspace",
            title="Duplicate workspace",
            description="Invalid duplicate slot fixture",
            slots=(slot, slot),
        )


def test_generated_schema_rejects_the_same_unknown_definition_field() -> None:
    payload = {
        "logical_id": "schema.generic-goal",
        "title": "Schema goal",
        "description": "Schema parity fixture",
        "family": "GoalDirected",
        "objective_contract": "contract:objective@1",
        "acceptance_contract": "contract:acceptance@1",
        "max_iterations": 1,
        "unexpected": True,
    }
    with pytest.raises(ValidationError):
        GoalDirectedBlueprint.model_validate(payload)
    with pytest.raises(JsonSchemaValidationError):
        Draft202012Validator(GoalDirectedBlueprint.model_json_schema()).validate(payload)


async def test_publish_compile_retrieve_is_deterministic_and_intersects_ceilings() -> None:
    service, _, records = await configured_service()
    request = invocation(
        records,
        overlay=RunOverlay(
            requested_capabilities=frozenset({"sandbox", "evaluate"}),
            budget_ceilings={"units": 50},
            max_concurrency=1,
            selected_variants=frozenset({"default"}),
        ),
    )
    first = await service.compile(request)
    second = await service.compile(request)

    assert first == second
    assert first.digest == second.digest
    assert first.effective_authority.capabilities == frozenset({"sandbox", "evaluate"})
    assert first.effective_authority.budgets.dimensions == {"units": 50}
    assert first.effective_authority.max_concurrency == 1
    assert any(
        decision.status == "degraded"
        and decision.field == "environment.capability.optional-observability"
        for decision in first.overlay_decisions
    )
    assert await service.retrieve(first.digest) == first


async def test_authoring_head_uses_optimistic_revisions_and_publishes_exact_draft() -> None:
    repository = InMemoryDefinitionRepository()
    service = ControlPlaneService(
        repository,
        ExtensionRegistry(),
        InMemoryPayloadStore(),
    )
    draft = GoalDirectedBlueprint.model_validate(
        {
            **GENERIC_GOAL_DIRECTED.model_dump(mode="python"),
            "logical_id": "draft.generic-goal",
            "title": "Draft goal",
            "description": "Mutable authoring content",
            "objective_contract": "contract:objective@1",
            "acceptance_contract": "contract:acceptance@1",
            "max_iterations": 1,
        }
    )
    first = await service.save_draft(
        SaveDraftRequest(
            definition=draft,
            actor_id="author",
            updated_at=NOW,
            expected_draft_revision=0,
        )
    )
    second = await service.save_draft(
        SaveDraftRequest(
            definition=draft.model_copy(update={"description": "Reviewed draft"}),
            actor_id="reviewer",
            updated_at=NOW,
            expected_draft_revision=1,
        )
    )
    assert first.draft_revision == 1
    assert second.draft_revision == 2
    with pytest.raises(DefinitionConflict, match="expected draft revision"):
        await repository.publish(
            draft,
            "stale-publisher",
            NOW,
            expected_head_revision=0,
            expected_draft_revision=1,
        )
    published = await service.publish_draft(
        PublishDraftRequest(
            kind=DefinitionKind.BLUEPRINT,
            logical_id=draft.logical_id,
            actor_id="publisher",
            published_at=NOW,
            expected_draft_revision=2,
            expected_published_revision=0,
        )
    )
    assert published.definition.description == "Reviewed draft"
    assert published.ref.revision == 1


async def test_workflow_specific_configuration_is_exact_and_resolved() -> None:
    service, _, records = await configured_service()
    configuration = await publish(
        service,
        WorkflowConfigurationDefinition(
            logical_id="generic.workflow-config",
            title="Generic workflow configuration",
            description="Typed extension point without product semantics",
            workflow_type_logical_id="generic.workflow",
        ),
    )
    original_workflow = records["workflow"]
    revised_workflow = await publish(
        service,
        original_workflow.definition.model_copy(  # type: ignore[attr-defined]
            update={"allowed_workflow_configurations": frozenset({configuration.ref})}
        ),
        expected=1,
    )
    records["workflow"] = revised_workflow
    request = invocation(records).model_copy(
        update={"workflow_configuration": DefinitionSelector(exact=configuration.ref)}
    )
    compiled = await service.compile(request)
    assert compiled.workflow_specific_configuration == configuration.definition
    assert configuration.ref in compiled.source_refs


async def test_workflow_type_rejects_configuration_for_another_workflow() -> None:
    service, _, records = await configured_service()
    configuration = await publish(
        service,
        WorkflowConfigurationDefinition(
            logical_id="foreign.workflow-config",
            title="Foreign workflow configuration",
            description="Targets a different Workflow Type",
            workflow_type_logical_id="another.workflow",
        ),
    )
    workflow = records["workflow"]
    with pytest.raises(CompilationRejected, match="different Workflow Type"):
        await publish(
            service,
            workflow.definition.model_copy(  # type: ignore[attr-defined]
                update={"allowed_workflow_configurations": frozenset({configuration.ref})}
            ),
            expected=1,
        )


async def test_alias_movement_preserves_snapshot_and_retirement_is_readable() -> None:
    service, repository, records = await configured_service()
    workflow = records["workflow"]
    alias = AliasRef(
        kind=DefinitionKind.WORKFLOW_TYPE,
        logical_id="generic.workflow",
        alias="stable",
    )
    await service.move_alias(
        MoveAliasRequest(alias=alias, target=workflow.ref, actor_id="operator", moved_at=NOW)  # type: ignore[attr-defined]
    )
    aliased = invocation(records).model_copy(
        update={"workflow_type": DefinitionSelector(alias=alias)}
    )
    compiled = await service.compile(aliased)
    assert compiled.alias_evidence[0].alias_ref == alias
    assert compiled.alias_evidence[0].target == workflow.ref  # type: ignore[attr-defined]

    definition = workflow.definition.model_copy(  # type: ignore[attr-defined]
        update={"description": "A second immutable contract fixture"}
    )
    second = await publish(service, definition, expected=1)
    await service.move_alias(
        MoveAliasRequest(alias=alias, target=second.ref, actor_id="operator", moved_at=NOW)
    )
    assert (await service.retrieve(compiled.digest)).source_refs[0] == workflow.ref  # type: ignore[attr-defined]

    await service.retire(RetireRequest(ref=second.ref, actor_id="operator", retired_at=NOW))
    assert (await repository.get(second.ref)).retired_at == NOW
    with pytest.raises(RetiredDefinition):
        await service.resolve_alias(alias)


async def test_overlay_cannot_escalate_or_select_undeclared_variant() -> None:
    service, _, records = await configured_service()
    with pytest.raises(CompilationRejected, match="exceed"):
        await service.compile(
            invocation(
                records,
                overlay=RunOverlay(requested_capabilities=frozenset({"available-not-authorized"})),
            )
        )
    with pytest.raises(CompilationRejected, match="undeclared"):
        await service.compile(
            invocation(
                records,
                overlay=RunOverlay(selected_variants=frozenset({"invented"})),
            )
        )


async def test_required_capabilities_must_also_be_authorized() -> None:
    service, _, records = await configured_service()
    request = invocation(records).model_copy(
        update={"caller_authority": authority("sandbox", budget=70, concurrency=2)}
    )
    with pytest.raises(CompilationRejected, match="required capabilities exceed"):
        await service.compile(request)


async def test_capability_overlay_cannot_remove_a_required_capability() -> None:
    service, _, records = await configured_service()
    with pytest.raises(CompilationRejected, match="removes a required"):
        await service.compile(
            invocation(
                records,
                overlay=RunOverlay(requested_capabilities=frozenset({"sandbox"})),
            )
        )


async def test_caller_cannot_inject_an_unallowed_registered_extension() -> None:
    service, _, records = await configured_service()
    extension = NamespacedExtension(
        namespace="belllabs.workflow",
        schema_version="1",
        discriminator="caller-injected",
        payload={},
    )
    with pytest.raises(CompilationRejected, match="not allowed"):
        await service.compile(invocation(records, overlay=RunOverlay(extensions=(extension,))))


async def test_compilation_identity_cannot_point_to_different_digests() -> None:
    service, _, records = await configured_service()
    first = invocation(records)
    await service.compile(first)
    changed_manifest = first.input_manifest.model_copy(update={"digest": "sha256:" + "2" * 64})
    with pytest.raises(DefinitionConflict, match="compilation identity"):
        await service.compile(first.model_copy(update={"input_manifest": changed_manifest}))


async def test_externalized_payload_has_same_contract_and_detects_tampering() -> None:
    service, repository, records = await configured_service(externalize_above_bytes=0)
    compiled = await service.compile(invocation(records))
    record = await repository.get_erc_record(compiled.digest)
    assert record["payload"] is None
    assert await service.retrieve(compiled.digest) == compiled

    record["payload_ref"]["digest"] = "sha256:" + "0" * 64
    repository._erc[compiled.digest] = record
    with pytest.raises(PayloadIntegrityError, match="content-address mismatch"):
        await service.retrieve(compiled.digest)
