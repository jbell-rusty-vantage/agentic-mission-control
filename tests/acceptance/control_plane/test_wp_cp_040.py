from __future__ import annotations

import inspect
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import ValidationError
from tests.fixtures.checkpoint_lineage import (
    activity_attempt,
)
from tests.fixtures.lane_bindings import lane_fields
from tests.support.deep_agents import (
    cognitive_schemas,
    exact,
    exact_fixture,
    observed_human_counts,
    planned_invocation,
    registry,
    runtime_invocation,
    session_probe_model,
    skill_reading_model,
    unit_bound,
)
from tests.support.operations import operation_request

from mission_control.adapters.deep_agents import (
    DeepAgentRuntimeAdapter,
    ExactComponentRegistry,
    ExactDeepAgentMaterializer,
)
from mission_control.adapters.deep_agents.harness import DeepAgentsHarness
from mission_control.application.execution.operations.checkpoint_lineage import (
    CheckpointLineageService,
    InMemoryCheckpointLineageRepository,
)
from mission_control.application.resolution.registries import LaneRegistry
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import DefinitionKind
from mission_control.domain.execution.checkpoint_lineage import (
    STAMP_BINDING_DIGEST,
    STAMP_EXECUTION_GENERATION,
    STAMP_INVOCATION_ID,
    STAMP_STATE_SCHEMA_DIGEST,
    STAMP_UNIT_KEY,
    CheckpointLineageInDoubt,
    IncompatibleCheckpointSchema,
)
from mission_control.domain.execution.contracts import (
    CapabilityGrant,
    CognitiveChannelDefinition,
    CognitiveChannelPack,
    CognitiveRuntimeContextPack,
    CognitiveRuntimeField,
    DeepAgentExecutionBinding,
    DeepAgentExecutionPlacementProfile,
    DeepAgentModelComponent,
    DeepAgentProfile,
    OperationAttemptIdentity,
    OperationExecutionRequest,
    OperationWorkflowRequest,
    SyncSubagentProfile,
)
from mission_control.domain.execution.errors import (
    DeepAgentMaterializationError,
    DeepAgentRuntimeDrift,
)
from mission_control.domain.execution.materialization import (
    compile_deep_agent_execution_binding,
    compose_cognitive_context_schema,
    compose_cognitive_state_schema,
)

DIGEST_A = "sha256:" + "a" * 64


def unit_request(binding: DeepAgentExecutionBinding) -> OperationExecutionRequest:
    payload = operation_request().model_dump(mode="python")
    payload.update(
        identity=OperationAttemptIdentity(
            run_id=binding.run_id,
            operation_id=binding.operation_id,
            operation_attempt=binding.operation_attempt,
        ),
        execution_runtime="deep_agent",
        native_placement=None,
        **lane_fields(binding),
        runtime_unit=binding.runtime_unit,
        idempotency_key=f"side-effect:{binding.operation_id}",
    )
    return OperationExecutionRequest.model_validate(payload)


async def execute_and_observe(
    adapter: DeepAgentRuntimeAdapter,
    lineage: CheckpointLineageService,
    binding: DeepAgentExecutionBinding,
):  # type: ignore[no-untyped-def]
    invocation = await planned_invocation(binding, lineage)
    result = await adapter.execute(invocation, {})
    assert invocation.checkpoint_plan is not None and result.checkpoint is not None
    transition = await lineage.record_transition(
        invocation.checkpoint_plan,
        result.checkpoint,
        result_manifest_ref=f"manifest:{binding.binding_id}",
        result_manifest_digest=sha256_digest(result.output_text),
    )
    return invocation, result, transition


def test_operation_workflow_derives_queue_and_rejects_binding_generation_drift() -> None:
    binding, _profile, _bundle = exact_fixture()
    payload = operation_request().model_dump(mode="python")
    payload.update(
        execution_runtime="deep_agent",
        native_placement=None,
        **lane_fields(binding),
    )
    operation = OperationExecutionRequest.model_validate(payload)
    request = OperationWorkflowRequest(
        semantic_attempt_id=operation.identity.semantic_key,
        execution_generation=binding.execution_generation,
        operation_kind="bound_operation",
        operation=operation,
    )

    assert request.activity_task_queue == binding.task_queue
    with pytest.raises(ValueError, match="generation"):
        OperationWorkflowRequest(
            semantic_attempt_id=operation.identity.semantic_key,
            execution_generation=binding.execution_generation + 1,
            operation_kind="bound_operation",
            operation=operation,
        )


def test_profile_placement_and_cognitive_schema_digests_are_strict_and_stable() -> None:
    first, profile, _bundle = exact_fixture()
    second, second_profile, _second_bundle = exact_fixture()
    assert first == second
    assert profile.profile_digest == second_profile.profile_digest
    assert first.binding_digest.startswith("sha256:")
    with pytest.raises(ValidationError, match="profile digest mismatch"):
        DeepAgentProfile.model_validate(
            {**profile.model_dump(mode="python"), "profile_digest": DIGEST_A}
        )
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DeepAgentProfile.model_validate(
            {**profile.model_dump(mode="python"), "runtime_alias": "latest"}
        )


def test_nested_frozenset_projections_have_one_canonical_digest() -> None:
    observed = {
        (
            binding.binding_digest,
            binding.cognitive_state_schema.schema_digest,
            binding.cognitive_context_schema.schema_digest,
        )
        for binding, _profile, _bundle in (exact_fixture(with_child_slices=True) for _ in range(25))
    }
    assert len(observed) == 1


def test_channel_collision_and_context_secret_material_fail_closed() -> None:
    state_packs, context_pack, _state, _context = cognitive_schemas()
    collision = CognitiveChannelPack.create(
        logical_id="pack.collision",
        revision=1,
        contributor="middleware",
        channels=(
            CognitiveChannelDefinition(
                name="artifact_index",
                value_kind="object",
                value_schema_ref="schema:different@1",
                reducer="replace",
            ),
        ),
    )
    with pytest.raises(ValueError, match="channel collision"):
        compose_cognitive_state_schema(
            schema_id="state.collision",
            packs=(state_packs[0], collision),
        )
    unsafe = CognitiveRuntimeContextPack.create(
        logical_id="pack.unsafe",
        revision=1,
        contributor="operation_role",
        fields=(CognitiveRuntimeField(name="api_key", value_kind="string"),),
    )
    with pytest.raises(ValidationError, match="references only"):
        compose_cognitive_context_schema(
            schema_id="context.unsafe",
            packs=(context_pack, unsafe),
        )


@pytest.mark.asyncio
async def test_actual_deep_agent_progressively_loads_skill_md_into_messages() -> None:
    binding, _profile, bundle = exact_fixture()
    model = skill_reading_model()
    adapter = DeepAgentRuntimeAdapter(ExactDeepAgentMaterializer(registry(binding, bundle, model)))
    lineage = CheckpointLineageService(InMemoryCheckpointLineageRepository())
    result = await adapter.execute(await planned_invocation(unit_bound(binding), lineage), {})

    assert result.output_text == "SKILL-MD-IN-MESSAGES-040 observed and followed."
    inspection = result.event_payloads[0]
    assert "artifact_index" in inspection["state_keys"]
    assert inspection["skills_metadata"][0]["name"] == "exact-binding-proof"
    assert "SKILL-MD-IN-MESSAGES-040" in (inspection["skill_instruction_messages"][0]["content"])
    assert inspection["skill_instruction_messages"][0]["path"].endswith("SKILL.md")
    assert len(model.calls) == 2


@pytest.mark.asyncio
async def test_shared_session_reuse_is_ordered_and_same_unit_never_reappends_prompt() -> None:
    """REQ-CP-DA-018 / REQ-BP-GD-012 / RRM-001 section 7 #3.

    The WP-CP-040 test asserted `[1, 2, 1]` by executing the *same* invocation twice, which
    re-appended its prompt on the same thread. Under the accepted checkpoint protocol a
    checkpoint written by the current submission never authorizes appending that input
    again: the same-unit re-execution now fails closed before the model is called. The
    intentional cross-iteration session reuse (next unit, pinned to the namespace head) and
    the empty rollover session keep their accepted human-message counts.

    RRM-004 (REQ-CP-DA-018): RRM-003 failed the same-unit re-execution closed because only
    `not_submitted` was implemented. The full classifier now recognizes the unit's own
    stamped terminal lineage as `terminal_unobserved` and reconstructs the identical result
    from it, still with no model call and no re-appended prompt.
    """

    binding, _profile, bundle = exact_fixture()
    model = session_probe_model()
    adapter = DeepAgentRuntimeAdapter(ExactDeepAgentMaterializer(registry(binding, bundle, model)))
    lineage = CheckpointLineageService(InMemoryCheckpointLineageRepository())
    first_unit = unit_bound(binding, iteration=1)
    first_invocation, first_result, first_transition = await execute_and_observe(
        adapter, lineage, first_unit
    )

    reconstructed = await adapter.execute(first_invocation, {})
    assert reconstructed.checkpoint is not None and first_result.checkpoint is not None
    assert reconstructed.checkpoint.classification == "terminal_unobserved"
    assert reconstructed.checkpoint.result_key == first_result.checkpoint.result_key
    assert reconstructed.output_text == first_result.output_text
    assert reconstructed.usage == first_result.usage
    assert observed_human_counts(model) == [1]
    with pytest.raises(CheckpointLineageInDoubt, match="unsettled transition"):
        await planned_invocation(first_unit, lineage, attempt=2)

    _second_invocation, second_result, second_transition = await execute_and_observe(
        adapter, lineage, unit_bound(binding, iteration=2)
    )
    _fresh_invocation, fresh_result, fresh_transition = await execute_and_observe(
        adapter, lineage, unit_bound(binding, iteration=3, session_generation=2)
    )

    assert observed_human_counts(model) == [1, 2, 1]
    assert second_transition.namespace == first_transition.namespace
    assert second_transition.source_key == first_transition.result_key
    assert fresh_transition.namespace != first_transition.namespace
    assert fresh_transition.source_key is None
    assert first_result.usage.amounts["tokens.total"] == 5
    assert second_result.usage.amounts["tokens.total"] == 5
    assert fresh_result.usage.amounts["tokens.total"] == 5


@pytest.mark.asyncio
async def test_invocation_is_root_namespaced_pinned_sync_durable_and_fully_stamped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """REQ-CP-DA-016/017: exact thread, root `checkpoint_ns`, source pin, stamps, sync."""

    import mission_control.adapters.deep_agents.adapter as adapter_module

    invoke_kwargs: list[dict[str, Any]] = []
    real_create = adapter_module.create_deep_agent

    def recording_create(*args: Any, **kwargs: Any) -> Any:
        agent = real_create(*args, **kwargs)
        real_ainvoke = agent.ainvoke

        async def ainvoke(state: Any, **invoke: Any) -> Any:
            invoke_kwargs.append(invoke)
            return await real_ainvoke(state, **invoke)

        object.__setattr__(agent, "ainvoke", ainvoke)
        return agent

    monkeypatch.setattr(adapter_module, "create_deep_agent", recording_create)
    binding, _profile, bundle = exact_fixture()
    saver = InMemorySaver()
    exact_registry = registry(binding, bundle, session_probe_model())
    exact_registry = ExactComponentRegistry(
        model_factories=exact_registry.model_factories,
        skill_bundles=exact_registry.skill_bundles,
        sandbox_factories=exact_registry.sandbox_factories,
        checkpointers={binding.checkpointer_ref.digest: saver},
        stores=exact_registry.stores,
    )
    adapter = DeepAgentRuntimeAdapter(ExactDeepAgentMaterializer(exact_registry))
    lineage = CheckpointLineageService(InMemoryCheckpointLineageRepository())
    first_binding = unit_bound(binding, iteration=1)
    second_binding = unit_bound(binding, iteration=2)
    first, first_result, first_transition = await execute_and_observe(
        adapter, lineage, first_binding
    )
    second, second_result, second_transition = await execute_and_observe(
        adapter, lineage, second_binding
    )
    assert first.checkpoint_plan is not None and second.checkpoint_plan is not None
    assert first_result.checkpoint is not None and second_result.checkpoint is not None

    namespace = first_transition.namespace
    assert namespace == "belllabs/goal/run-operation/epoch/1/session/1/role/executor"
    assert [call["config"]["configurable"] for call in invoke_kwargs] == [
        {"thread_id": namespace, "checkpoint_ns": ""},
        {
            "thread_id": namespace,
            "checkpoint_ns": "",
            "checkpoint_id": first_transition.result_key.checkpoint_id,
        },
    ]
    assert [call["durability"] for call in invoke_kwargs] == ["sync", "sync"]
    thread = {"configurable": {"thread_id": namespace, "checkpoint_ns": ""}}
    root = [item async for item in saver.alist(thread)]
    plans = {plan.invocation_id: plan for plan in (first.checkpoint_plan, second.checkpoint_plan)}
    stamped_per_invocation: dict[str, int] = {}
    for item in root:
        plan = plans[item.metadata[STAMP_INVOCATION_ID]]
        assert item.metadata[STAMP_UNIT_KEY] == plan.unit_key
        assert item.metadata[STAMP_EXECUTION_GENERATION] == 1
        assert item.metadata[STAMP_BINDING_DIGEST] == plan.binding_digest
        assert item.metadata[STAMP_STATE_SCHEMA_DIGEST] == (
            binding.cognitive_state_schema.schema_digest
        )
        assert "Return BINDING-OK" not in str(item.metadata)
        stamped_per_invocation[plan.invocation_id] = (
            stamped_per_invocation.get(plan.invocation_id, 0) + 1
        )
    assert stamped_per_invocation == {
        first_transition.invocation_id: first_result.checkpoint.stamped_checkpoint_count,
        second_transition.invocation_id: second_result.checkpoint.stamped_checkpoint_count,
    }
    assert second_transition.result_key.parent_checkpoint_id is not None
    assert await lineage.repository.get_namespace_head("tenant-1", namespace) == (
        second_transition.result_key
    )


@pytest.mark.asyncio
async def test_source_state_schema_mismatch_fails_closed_before_model_invocation() -> None:
    """REQ-CP-CS-007 (amended): the stamped source schema digest gates every resume."""

    binding, _profile, bundle = exact_fixture()
    drifted, _drifted_profile, _drifted_bundle = exact_fixture(with_child_slices=True)
    assert drifted.cognitive_state_schema.schema_digest != (
        binding.cognitive_state_schema.schema_digest
    )
    model = session_probe_model()
    adapter = DeepAgentRuntimeAdapter(ExactDeepAgentMaterializer(registry(binding, bundle, model)))
    lineage = CheckpointLineageService(InMemoryCheckpointLineageRepository())
    await execute_and_observe(adapter, lineage, unit_bound(binding, iteration=1))
    second = await planned_invocation(unit_bound(drifted, iteration=2), lineage)

    with pytest.raises(IncompatibleCheckpointSchema, match="REQ-CP-CS-007"):
        await adapter.execute(second, {})
    assert observed_human_counts(model) == [1]


@pytest.mark.asyncio
async def test_unplanned_or_drifted_invocation_is_refused_before_materialization() -> None:
    binding, _profile, bundle = exact_fixture()
    model = session_probe_model()
    adapter = DeepAgentRuntimeAdapter(ExactDeepAgentMaterializer(registry(binding, bundle, model)))
    lineage = CheckpointLineageService(InMemoryCheckpointLineageRepository())
    planned = await planned_invocation(unit_bound(binding), lineage)
    assert planned.checkpoint_plan is not None

    with pytest.raises(DeepAgentMaterializationError, match="lineage plan"):
        await adapter.execute(planned.model_copy(update={"checkpoint_plan": None}), {})
    with pytest.raises(DeepAgentMaterializationError, match="lineage plan"):
        await adapter.execute(runtime_invocation(binding), {})
    drifted_plan = planned.checkpoint_plan.model_copy(update={"checkpointer_ref_digest": DIGEST_A})
    with pytest.raises(DeepAgentMaterializationError, match="does not match"):
        await adapter.execute(planned.model_copy(update={"checkpoint_plan": drifted_plan}), {})
    assert observed_human_counts(model) == []


@pytest.mark.asyncio
async def test_exact_mcp_server_and_tool_surface_materialize() -> None:
    binding, _profile, bundle = exact_fixture(include_mcp=True)
    materializer = ExactDeepAgentMaterializer(registry(binding, bundle))
    async with materializer.prepare(binding, {}) as resolved:
        assert [tool.name for tool in resolved.tools] == ["lookup_binding_marker"]
        assert await resolved.tools[0].ainvoke({"code": "UNIT"})


@pytest.mark.asyncio
async def test_runtime_package_drift_fails_before_model_or_sandbox_effects() -> None:
    binding, _profile, bundle = exact_fixture(package_versions={"deepagents": "999.0.0"})
    calls = 0

    def model_factory(_binding, _secrets):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        return skill_reading_model()

    exact_registry = registry(binding, bundle)
    exact_registry = ExactComponentRegistry(
        model_factories={binding.model.ref.digest: model_factory},
        skill_bundles=exact_registry.skill_bundles,
        sandbox_factories=exact_registry.sandbox_factories,
        checkpointers=exact_registry.checkpointers,
        stores=exact_registry.stores,
    )
    with pytest.raises(DeepAgentRuntimeDrift, match="package drift"):
        async with ExactDeepAgentMaterializer(exact_registry).prepare(binding, {}):
            pass
    assert calls == 0


def test_sync_subagent_cannot_exceed_parent_tool_or_workspace_ceiling() -> None:
    _state_packs, _context_pack, state_schema, context_schema = cognitive_schemas(
        with_child_slices=True
    )
    model = DeepAgentModelComponent(
        ref=exact(DefinitionKind.MODEL, "model.child", "child-model"),
        provider="openai",
        model_name="fixture-model",
    )
    child = SyncSubagentProfile(
        name="bounded-child",
        description="A bounded child fixture.",
        system_prompt_ref=exact(DefinitionKind.PROMPT, "prompt.child", "child-prompt"),
        model=model,
        tool_refs=(exact(DefinitionKind.TOOL, "tool.not-parent", "not-parent"),),
        state_slice_id="child-state",
        context_slice_id="child-context",
        workspace_id="workspace-child",
        writable_paths=("/workspace/child",),
    )
    _binding, base_profile, _bundle = exact_fixture(with_child_slices=True)
    profile_payload = base_profile.model_dump(mode="python", exclude={"profile_digest"})
    profile_payload["sync_subagents"] = (child,)
    profile = DeepAgentProfile.create(**profile_payload)
    del state_schema, context_schema
    request = operation_request()
    _, _, effective_state, effective_context = cognitive_schemas(with_child_slices=True)
    placement = DeepAgentExecutionPlacementProfile.create(
        logical_id="placement.wp-cp-040",
        revision=1,
        placement="local_in_worker",
        python_runtime="3.12",
        package_versions={"deepagents": "0.7.5"},
        task_queue="agent-cognitive",
        checkpoint_behavior="local_checkpointer",
        cancellation_behavior="cooperative",
        streaming_behavior="state_updates",
        message_injection_behavior="invoke_only",
        reconnect_behavior="checkpoint_resume",
        sandbox_backends=frozenset({"state"}),
        qualification_refs=("QUAL-CP-DEEP-AGENT-MATERIALIZATION",),
    )
    with pytest.raises(ValueError, match="tools exceed"):
        compile_deep_agent_execution_binding(
            profile=profile,
            placement=placement,
            state_schema=effective_state,
            context_schema=effective_context,
            context_values={
                "run_id": request.identity.run_id,
                "operation_id": request.identity.operation_id,
                "operation_attempt": 1,
                "execution_generation": 1,
                "capability_grant_ref": "ref:grant",
                "workspace_handle": "handle:workspace",
            },
            run_id=request.identity.run_id,
            operation_id=request.identity.operation_id,
            operation_attempt=1,
            execution_generation=1,
            erc_digest=request.effective_configuration_digest,
            control_revision=request.run_control_revision,
            workspace=request.workspace,
            capability_grant=CapabilityGrant(capabilities=frozenset()),
            reservation_id=request.budget_reservation_id,
            authority_refs=("authority:test",),
            redaction_policy_ref="redaction:test",
            initial_context_manifest={"digest": sha256_digest("context")},
        )


def test_create_deep_agent_has_one_non_experiment_production_call_site() -> None:
    import mission_control.adapters.deep_agents.adapter as adapter_module

    source = inspect.getsource(adapter_module)
    assert source.count("create_deep_agent(") == 1


@pytest.mark.asyncio
async def test_operation_service_pins_records_and_links_the_result_checkpoint() -> None:
    """Production seam: `OperationExecutionService` → adapter → transition → settlement."""

    from tests.support.deep_agents_runtime import (
        ConformanceAssetVerifier,
        ConformanceBudgetAuthority,
        ConformanceEventSink,
        ConformanceSandbox,
        ConformanceSecretResolver,
    )
    from tests.support.operations import MCP_DIGEST, SKILL_DIGEST

    from mission_control.application.execution.operations.operation_execution import (
        InMemoryOperationBindingRepository,
        OperationExecutionService,
    )

    class AcceptingAuthority:
        async def verify(self, request: OperationExecutionRequest) -> None:
            del request

        async def verify_continuation(
            self, request: OperationExecutionRequest, binding: Any
        ) -> None:
            del request, binding

        async def verify_cancellation(
            self, request: OperationExecutionRequest, binding: Any
        ) -> None:
            del request, binding

    binding, _profile, bundle = exact_fixture()
    model = session_probe_model()
    repository = InMemoryCheckpointLineageRepository()
    assets = ConformanceAssetVerifier(
        mcp_schema_digests={"fixture-mcp": MCP_DIGEST},
        asset_manifest_digests={"skill:fixture.skill:1": SKILL_DIGEST},
    )

    def compose(lineage: CheckpointLineageService | None) -> OperationExecutionService:
        return OperationExecutionService(
            authority=AcceptingAuthority(),
            bindings=InMemoryOperationBindingRepository(),
            lanes=LaneRegistry(
                [
                    DeepAgentsHarness(
                        DeepAgentRuntimeAdapter(
                            ExactDeepAgentMaterializer(registry(binding, bundle, model))
                        )
                    )
                ]
            ),
            sandbox=ConformanceSandbox(),
            assets=assets,
            mcp=assets,
            secrets=ConformanceSecretResolver({"environment:OPENAI_API_KEY": "unused"}),
            events=ConformanceEventSink(),
            budget=ConformanceBudgetAuthority(),
            lineage=lineage,
        )

    request = unit_request(unit_bound(binding))
    with pytest.raises(ValueError, match="checkpoint lineage composition"):
        await compose(None).execute(request, activity_attempt())
    service = compose(CheckpointLineageService(repository))

    result = await service.execute(request, activity_attempt(attempt=1))
    replay = await service.execute(request, activity_attempt(attempt=2))

    assert request.runtime_unit is not None
    transition = await repository.get_transition("tenant-1", request.runtime_unit.unit_key, 1)
    assert transition is not None
    assert result.status == "completed"
    assert result.result_checkpoint == transition.result_key
    assert result.checkpoint_transition_id == transition.transition_id
    assert transition.result_manifest_ref.startswith("operation-settlement:")
    assert replay == result
    assert observed_human_counts(model) == [1]
    attempts = await repository.list_attempts("tenant-1", request.runtime_unit.unit_key)
    assert [(item.attempt.attempt, item.dispatching) for item in attempts] == [(1, True)]
