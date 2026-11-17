"""Deep Agents binding builders and async-subagent doubles, from test_wp_cp_040 and test_wp_cp_045.

exact_fixture, registry, unit_bound and planned_invocation build an exact Deep Agents
binding; SkillReadingModel and SessionProbeModel are scripted chat models; the
DeterministicProvider/OrderedDetails/OrderedAuthority group drives async subagents.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from mission_control.adapters.deep_agents import (
    ExactComponentRegistry,
    ResolvedSkillBundle,
    StateSandboxFactory,
)
from mission_control.application.execution.operations.checkpoint_lineage import (
    CheckpointLineageService,
)
from mission_control.application.execution.operations.operation_execution import (
    bind_operation_execution_request,
)
from mission_control.application.subordinates.service import (
    AsyncSubagentSpawnRequest,
    ProviderAsyncObservation,
)
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import DefinitionKind, ExactDefinitionRef, SecretRef
from mission_control.domain.execution.async_subagent_reconciliation import (
    AsyncProviderRunObservation,
    AsyncProviderRunRecord,
    AsyncServedGraphIdentity,
    AsyncSpawnKeyObservation,
)
from mission_control.domain.execution.contracts import (
    AsyncProviderCheckpointKey,
    AsyncSubagentContract,
    AsyncSubagentDependencyClass,
    AsyncSubagentExecution,
    AsyncSubagentMessage,
    AsyncSubagentUsage,
    CapabilityGrant,
    CognitiveChannelDefinition,
    CognitiveChannelPack,
    CognitiveChannelPackRef,
    CognitiveRuntimeContextPack,
    CognitiveRuntimeField,
    DeepAgentExecutionBinding,
    DeepAgentExecutionPlacementProfile,
    DeepAgentMCPServerComponent,
    DeepAgentMCPToolComponent,
    DeepAgentModelComponent,
    DeepAgentProfile,
    DeepAgentSandboxComponent,
    DeepAgentSkillComponent,
    MaterializedWorkspace,
    OperationAttemptIdentity,
    OperationExecutionRequest,
    RuntimeInvocation,
    SubagentContextSlice,
    SubagentStateSlice,
    SyncSubagentProfile,
)
from mission_control.domain.execution.materialization import (
    compile_deep_agent_execution_binding,
    compose_cognitive_context_schema,
    compose_cognitive_state_schema,
)
from tests.fixtures.checkpoint_lineage import activity_attempt, bind_unit, goal_unit, stage_unit
from tests.fixtures.lane_bindings import lane_fields
from tests.support.operations import operation_request

MCP_TOOL_SCHEMA_DIGEST = "sha256:bb30ffeeaa9cc8d145c2160ac76df146df61820df24db1078c4db98573714a99"
SKILL_TEXT = """---
name: exact-binding-proof
description: Use for the WP-CP-040 exact binding proof.
---

Read this full instruction before acting. The proof marker is SKILL-MD-IN-MESSAGES-040.
"""


def exact(kind: DefinitionKind, logical_id: str, seed: str) -> ExactDefinitionRef:
    return ExactDefinitionRef(
        kind=kind,
        logical_id=logical_id,
        revision=1,
        digest=sha256_digest(seed),
    )


def skill_bundle() -> ResolvedSkillBundle:
    content = SKILL_TEXT.encode()
    manifest = [
        {
            "path": "SKILL.md",
            "digest": sha256_digest(SKILL_TEXT),
            "size_bytes": len(content),
        }
    ]
    return ResolvedSkillBundle(
        bundle_digest=sha256_digest(manifest),
        files=(("SKILL.md", content),),
    )


def cognitive_schemas(*, with_child_slices: bool = False):
    state_pack = CognitiveChannelPack.create(
        logical_id="pack.belllabs.base-state",
        revision=1,
        contributor="base",
        channels=(
            CognitiveChannelDefinition(
                name="artifact_index",
                value_kind="map",
                value_schema_ref="schema:artifact-index@1",
                reducer="merge_by_key",
            ),
            CognitiveChannelDefinition(
                name="context_manifest",
                value_kind="object",
                value_schema_ref="schema:context-manifest@1",
                reducer="replace",
            ),
            CognitiveChannelDefinition(
                name="child_result_index",
                value_kind="append_list",
                value_schema_ref="schema:child-result-index@1",
                reducer="append_unique_by_id",
            ),
        ),
    )
    skills_pack = CognitiveChannelPack.create(
        logical_id="pack.deepagents.skills-middleware",
        revision=1,
        contributor="middleware",
        channels=(
            CognitiveChannelDefinition(
                name="skills_metadata",
                value_kind="append_list",
                value_schema_ref="schema:deepagents-skill-metadata@0.7.5",
                reducer="replace",
            ),
            CognitiveChannelDefinition(
                name="skills_load_errors",
                value_kind="string_list",
                value_schema_ref="schema:deepagents-skill-load-errors@0.7.5",
                reducer="replace",
            ),
        ),
    )
    context_pack = CognitiveRuntimeContextPack.create(
        logical_id="pack.belllabs.base-context",
        revision=1,
        contributor="base",
        fields=(
            CognitiveRuntimeField(name="run_id", value_kind="string"),
            CognitiveRuntimeField(name="operation_id", value_kind="string"),
            CognitiveRuntimeField(name="operation_attempt", value_kind="integer"),
            CognitiveRuntimeField(name="execution_generation", value_kind="integer"),
            CognitiveRuntimeField(
                name="capability_grant_ref",
                value_kind="string",
                reference_only=True,
            ),
            CognitiveRuntimeField(
                name="workspace_handle",
                value_kind="string",
                reference_only=True,
            ),
        ),
    )
    state_slices = (
        (
            SubagentStateSlice(
                slice_id="child-state",
                channel_names=frozenset({"artifact_index", "context_manifest"}),
            ),
        )
        if with_child_slices
        else ()
    )
    context_slices = (
        (
            SubagentContextSlice(
                slice_id="child-context",
                field_names=frozenset({"run_id", "operation_id", "workspace_handle"}),
            ),
        )
        if with_child_slices
        else ()
    )
    return (
        (state_pack, skills_pack),
        context_pack,
        compose_cognitive_state_schema(
            schema_id="state.wp-cp-040",
            packs=(state_pack, skills_pack),
            subagent_slices=state_slices,
        ),
        compose_cognitive_context_schema(
            schema_id="context.wp-cp-040",
            packs=(context_pack,),
            subagent_slices=context_slices,
        ),
    )


def exact_fixture(
    *,
    include_mcp: bool = False,
    package_versions: dict[str, str] | None = None,
    sync_subagents: tuple[SyncSubagentProfile, ...] = (),
    with_child_slices: bool = False,
    model_name: str = "fixture-model",
    model_settings: dict[str, object] | None = None,
    sandbox_backend: Literal["langsmith", "daytona", "docker", "state"] = "state",
    sandbox_credentials: tuple[SecretRef, ...] = (),
) -> tuple[DeepAgentExecutionBinding, DeepAgentProfile, ResolvedSkillBundle]:
    request = operation_request()
    state_packs, context_pack, state_schema, context_schema = cognitive_schemas(
        with_child_slices=with_child_slices
    )
    model_ref = exact(DefinitionKind.MODEL, "model.wp-cp-040", "model")
    sandbox_ref = exact(DefinitionKind.SANDBOX_PROFILE, "sandbox.wp-cp-040", "sandbox")
    skill_ref = exact(DefinitionKind.SKILL, "skill.wp-cp-040", "skill")
    bundle = skill_bundle()
    mcp_servers: tuple[DeepAgentMCPServerComponent, ...] = ()
    if include_mcp:
        mcp_servers = (
            DeepAgentMCPServerComponent(
                ref=exact(DefinitionKind.MCP_SERVER, "mcp.wp-cp-040", "mcp"),
                server_name="qualification",
                transport="stdio",
                command=sys.executable,
                arguments=(
                    "-m",
                    "mission_control.adapters.agent_server.qualification.wp_cp_040_mcp",
                ),
                tools=(
                    DeepAgentMCPToolComponent(
                        tool_name="lookup_binding_marker",
                        schema_digest=MCP_TOOL_SCHEMA_DIGEST,
                    ),
                ),
                schema_digest=sha256_digest("qualification-mcp-schema-v1"),
                attachment_target="agent.main",
            ),
        )
    profile = DeepAgentProfile.create(
        logical_id="agent.wp-cp-040",
        revision=1,
        model=DeepAgentModelComponent(
            ref=model_ref,
            provider="openai",
            model_name=model_name,
            settings=model_settings or {},
            # W1 D16: a node output schema binds only through a declared strategy; the fixture
            # model keeps the forced-tool strategy auto-detection gave it before.
            structured_output="tool_forced",
        ),
        prompt_refs=(exact(DefinitionKind.PROMPT, "prompt.wp-cp-040", "prompt"),),
        context_assembly_ref=exact(
            DefinitionKind.WORKFLOW_CONFIGURATION,
            "context.wp-cp-040",
            "context-assembly",
        ),
        backend_ref=exact(DefinitionKind.RUNTIME_PROFILE, "backend.wp-cp-040", "backend"),
        store_ref=exact(DefinitionKind.MEMORY_POLICY, "store.wp-cp-040", "store"),
        checkpointer_ref=exact(
            DefinitionKind.RUNTIME_PROFILE,
            "checkpointer.wp-cp-040",
            "checkpointer",
        ),
        mcp_servers=mcp_servers,
        skills=(
            DeepAgentSkillComponent(
                ref=skill_ref,
                skill_name="exact-binding-proof",
                bundle_digest=bundle.bundle_digest,
                skill_md_digest=sha256_digest(SKILL_TEXT),
                mount_root="/skills/exact-binding-proof",
                attachment_target="agent.main",
            ),
        ),
        sandbox=DeepAgentSandboxComponent(
            ref=sandbox_ref,
            backend=sandbox_backend,
            runtime_digest=sha256_digest(f"{sandbox_backend}-backend-runtime"),
            credential_refs=sandbox_credentials,
        ),
        sync_subagents=sync_subagents,
        tracing_policy_ref=exact(
            DefinitionKind.EVALUATION_PROFILE,
            "trace.wp-cp-040",
            "trace",
        ),
        cognitive_state_pack_refs=tuple(
            CognitiveChannelPackRef(
                logical_id=pack.logical_id,
                revision=pack.revision,
                digest=pack.digest,
                contributor=pack.contributor,
            )
            for pack in state_packs
        ),
        cognitive_context_pack_refs=(
            CognitiveChannelPackRef(
                logical_id=context_pack.logical_id,
                revision=context_pack.revision,
                digest=context_pack.digest,
                contributor=context_pack.contributor,
            ),
        ),
        compatible_placement_ids=frozenset({"placement.wp-cp-040"}),
    )
    placement = DeepAgentExecutionPlacementProfile.create(
        logical_id="placement.wp-cp-040",
        revision=1,
        placement="local_in_worker",
        python_runtime="3.12",
        package_versions=package_versions or {"deepagents": "0.7.5"},
        task_queue="agent-cognitive",
        checkpoint_behavior="local_checkpointer",
        cancellation_behavior="cooperative",
        streaming_behavior="state_updates",
        message_injection_behavior="invoke_only",
        reconnect_behavior="checkpoint_resume",
        sandbox_backends=frozenset({sandbox_backend}),
        qualification_refs=("QUAL-CP-DEEP-AGENT-MATERIALIZATION",),
    )
    binding = compile_deep_agent_execution_binding(
        profile=profile,
        placement=placement,
        state_schema=state_schema,
        context_schema=context_schema,
        context_values={
            "run_id": request.identity.run_id,
            "operation_id": request.identity.operation_id,
            "operation_attempt": request.identity.operation_attempt,
            "execution_generation": 1,
            "capability_grant_ref": "ref:capability-grant:wp-cp-040",
            "workspace_handle": "handle:workspace:wp-cp-040",
        },
        run_id=request.identity.run_id,
        operation_id=request.identity.operation_id,
        operation_attempt=request.identity.operation_attempt,
        execution_generation=1,
        erc_digest=request.effective_configuration_digest,
        control_revision=request.run_control_revision,
        workspace=request.workspace,
        capability_grant=request.capability_grant,
        reservation_id=request.budget_reservation_id,
        authority_refs=("authority:wp-cp-040",),
        redaction_policy_ref=request.sensitive_data_policy_ref,
        initial_context_manifest={"digest": sha256_digest("context-manifest"), "entries": []},
    )
    return binding, profile, bundle


class SkillReadingModel(BaseChatModel):
    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "wp-cp-040-scripted"

    def bind_tools(
        self,
        tools: Sequence[BaseTool | dict[str, Any] | type | Any],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> BaseChatModel:
        del tools, tool_choice, kwargs
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager, kwargs
        self.calls += 1
        read = next((item for item in messages if isinstance(item, ToolMessage)), None)
        if read is None:
            message = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "read_file",
                        "args": {
                            "file_path": "/skills/exact-binding-proof/SKILL.md",
                            "limit": 1000,
                        },
                        "id": "skill-read-040",
                        "type": "tool_call",
                    }
                ],
            )
        else:
            message = AIMessage(content="SKILL-MD-IN-MESSAGES-040 observed and followed.")
        return ChatResult(generations=[ChatGeneration(message=message)])


class SessionProbeModel(BaseChatModel):
    observed_human_counts: list[int] = []

    @property
    def _llm_type(self) -> str:
        return "wp-cp-040-session-probe"

    def bind_tools(
        self,
        tools: Sequence[BaseTool | dict[str, Any] | type | Any],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> BaseChatModel:
        del tools, tool_choice, kwargs
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager, kwargs
        human_count = sum(message.type == "human" for message in messages)
        self.observed_human_counts.append(human_count)
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content=f"human-count:{human_count}",
                        usage_metadata={
                            "input_tokens": 2,
                            "output_tokens": 3,
                            "total_tokens": 5,
                        },
                    )
                )
            ]
        )


def runtime_invocation(binding: DeepAgentExecutionBinding) -> RuntimeInvocation:
    base = operation_request()
    payload = base.model_dump(mode="python")
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
    )
    request = OperationExecutionRequest.model_validate(payload)
    operation_binding = bind_operation_execution_request(request)
    return RuntimeInvocation(
        binding=operation_binding,
        prompt_segments=request.prompt_segments,
        workspace=MaterializedWorkspace(
            workspace_id=request.workspace.workspace_id,
            namespace_id=request.workspace.namespace_id,
            provider=request.workspace.provider,
            runtime_digest=request.workspace.runtime_digest,
            image_digest=request.workspace.image_digest,
            mount_manifest_digest=sha256_digest("mounts"),
        ),
    )


def unit_bound(
    binding: DeepAgentExecutionBinding,
    *,
    iteration: int | None = None,
    session_generation: int = 1,
) -> DeepAgentExecutionBinding:
    """Freeze a fixture binding to a StageGraph unit, or to a GoalDirected executor unit."""

    if iteration is None:
        unit = stage_unit(
            request_scope="tenant-1",
            run_id=binding.run_id,
            operation_id=binding.operation_id,
        )
    else:
        unit = goal_unit(
            request_scope="tenant-1",
            run_id=binding.run_id,
            operation_id=f"goal-iteration/{iteration}/executor",
            goal_iteration=iteration,
            session_generation=session_generation,
        )
    return bind_unit(binding, unit)


async def planned_invocation(
    binding: DeepAgentExecutionBinding,
    lineage: CheckpointLineageService,
    *,
    attempt: int = 1,
) -> RuntimeInvocation:
    invocation = runtime_invocation(binding)
    plan = await lineage.observe_attempt(
        invocation.binding, activity_attempt(attempt), dispatching=True
    )
    return invocation.model_copy(update={"checkpoint_plan": plan})


def registry(
    binding: DeepAgentExecutionBinding,
    bundle: ResolvedSkillBundle,
    model: BaseChatModel | None = None,
) -> ExactComponentRegistry:
    selected = model or SkillReadingModel()
    return ExactComponentRegistry(
        model_factories={binding.model.ref.digest: lambda _binding, _secrets: selected},
        skill_bundles={bundle.bundle_digest: bundle},
        sandbox_factories={binding.sandbox.ref.digest: StateSandboxFactory()},
        checkpointers={binding.checkpointer_ref.digest: InMemorySaver()},
        stores={binding.store_ref.digest: InMemoryStore()},
    )


NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
GRAPH_BINDING_DIGEST = sha256_digest("research-graph-binding")
SERVED = AsyncServedGraphIdentity(
    graph_id="research-graph",
    graph_revision="agent.research@1",
    graph_binding_digest=GRAPH_BINDING_DIGEST,
    deepagents_version="0.7.5",
)


def contract() -> AsyncSubagentContract:
    return AsyncSubagentContract.create(
        contract_id="async-researcher-v1",
        name="researcher",
        description="Bounded background research",
        graph_id="research-graph",
        graph_revision="agent.research@1",
        graph_binding_digest=GRAPH_BINDING_DIGEST,
        agent_protocol_url="https://agent.example.test",
        deployment_credential_ref="environment:AGENT_SERVER_TOKEN",
        objective_schema_ref="schema:objective:v1",
        result_schema_ref="schema:result:v1",
        context_slice_id="context:child",
        state_slice_id="state:child",
        capability_ceiling=CapabilityGrant(capabilities=frozenset({"search"})),
        authority_refs=("authority:parent-operation",),
        budget_limits={"model.turns": 1, "tokens.total": 1_000},
        dependency_classes=frozenset(AsyncSubagentDependencyClass),
        timeout_seconds=300,
        cancellation_propagation="required",
        late_result_policy="quarantine",
        fallback_policy="degrade",
        result_admission_policy_ref="policy:async-result:v1",
    )


def request(
    dependency: AsyncSubagentDependencyClass = AsyncSubagentDependencyClass.REQUIRED_BLOCKING,
) -> AsyncSubagentSpawnRequest:
    return AsyncSubagentSpawnRequest(
        request_scope="tenant-a",
        parent_run_id="run-1",
        parent_operation_id="operation-1",
        parent_binding_id="binding-1",
        execution_generation=1,
        contract=contract(),
        dependency_class=dependency,
        objective_ref="ref:objective:1",
        objective="Research the exact bounded question.",
        context_slice_ref="ref:context-slice:1",
        reservation_id="reservation-child-1",
        idempotency_key="spawn-1",
        requested_at=NOW,
    )


def checkpoint() -> AsyncProviderCheckpointKey:
    return AsyncProviderCheckpointKey(
        agent_protocol_url="https://agent.example.test",
        thread_id="provider-thread-1",
        checkpoint_id="checkpoint-1",
        graph_id="research-graph",
        graph_revision="agent.research@1",
        graph_binding_digest=GRAPH_BINDING_DIGEST,
    )


class DeterministicProvider:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.starts = 0
        self.next_status = "running"

    async def verify_served_graph(
        self, _contract: AsyncSubagentContract
    ) -> AsyncServedGraphIdentity:
        self.events.append("provider.verify")
        return SERVED

    async def start(
        self,
        _contract: AsyncSubagentContract,
        _execution: AsyncSubagentExecution,
        _objective: str,
    ) -> ProviderAsyncObservation:
        self.events.append("provider.start")
        self.starts += 1
        return self._observation("running")

    async def observe_spawn_key(
        self, _contract: AsyncSubagentContract, execution: AsyncSubagentExecution
    ) -> AsyncSpawnKeyObservation:
        self.events.append("provider.observe")
        return AsyncSpawnKeyObservation(
            thread_id=execution.child_execution_id,
            runs=(
                (AsyncProviderRunObservation(run_id="provider-run-1", status="running"),)
                if self.starts
                else ()
            ),
            observed_at=NOW,
        )

    async def check(
        self, _contract: AsyncSubagentContract, _execution: AsyncSubagentExecution
    ) -> ProviderAsyncObservation:
        self.events.append("provider.check")
        return self._observation(self.next_status)

    async def update(
        self,
        _contract: AsyncSubagentContract,
        _execution: AsyncSubagentExecution,
        _message: AsyncSubagentMessage,
    ) -> ProviderAsyncObservation:
        self.events.append("provider.update")
        return self._observation("running", run_id="provider-run-2")

    async def cancel(
        self, _contract: AsyncSubagentContract, _execution: AsyncSubagentExecution
    ) -> ProviderAsyncObservation:
        self.events.append("provider.cancel")
        return self._observation("cancelled", receipt="provider_acknowledged")

    async def cancel_run(
        self,
        _contract: AsyncSubagentContract,
        execution: AsyncSubagentExecution,
        run_id: str,
    ) -> AsyncProviderRunRecord:
        self.events.append("provider.cancel_run")
        return AsyncProviderRunRecord(
            child_execution_id=execution.child_execution_id,
            provider_thread_id=execution.child_execution_id,
            provider_run_id=run_id,
            disposition="duplicate_cancelled",
            provider_status="interrupted",
            usage=AsyncSubagentUsage(provider_run_id=run_id, attribution="pending"),
            observed_at=NOW,
        )

    async def list(
        self, executions: tuple[tuple[AsyncSubagentContract, AsyncSubagentExecution], ...]
    ) -> tuple[ProviderAsyncObservation, ...]:
        return tuple(self._observation("running") for _ in executions)

    @staticmethod
    def _observation(
        status: str, run_id: str = "provider-run-1", receipt: str | None = None
    ) -> ProviderAsyncObservation:
        terminal = status == "success"
        return ProviderAsyncObservation(
            status=status,  # type: ignore[arg-type]
            thread_id="provider-thread-1",
            run_id=run_id,
            output_ref="ref:output:1" if terminal else None,
            output_text="canonical child result" if terminal else None,
            evidence_refs=("ref:evidence:1",) if terminal else (),
            usage=(
                AsyncSubagentUsage(
                    provider_run_id=run_id,
                    attribution="provider_attributed",
                    attributed_amounts={"model.turns": 1, "tokens.total": 7},
                )
                if terminal
                else None
            ),
            checkpoint=checkpoint() if terminal else None,
            cancellation_receipt=receipt,  # type: ignore[arg-type]
            observed_at=NOW,
        )
