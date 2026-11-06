"""Seal one dynamic async child's exact configuration (OVE-184, P1 WP-S3 option A).

The lane adapter calls :func:`seal_async_child_binding` for a ``kind: async`` profile whose
launch graph binding names the generic sealed-child graph (``binding_mode: sealed_child``).
The result is a :class:`SealedAsyncChildBinding`: the child's own prompt, model, tools,
Skills and MCP servers (or the parent's set for an inheriting child), compiled with the same
domain compiler as every Deep Agents binding, on a remote-managed Agent Server placement with
a state backend of its own. The Agent Server materializes it per run with the shared
materializer; nothing here is a provider call.

The child binding's identity is deliberately independent of the parent run: two parents that
seal the same child configuration get the same digest, so one Agent Server assistant per
binding and audience serves every spawn of it (``sealed_child_assistant_id``).

Pure: no I/O, no clock, no provider.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Final, Literal

from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import DefinitionKind, ExactDefinitionRef
from mission_control.domain.capabilities.features import AgentConfiguration
from mission_control.domain.execution.contracts import (
    CapabilityGrant,
    CognitiveChannelDefinition,
    CognitiveChannelPack,
    CognitiveChannelPackRef,
    CognitiveReducer,
    CognitiveRuntimeContextPack,
    CognitiveRuntimeField,
    DeepAgentExecutionPlacementProfile,
    DeepAgentMCPServerComponent,
    DeepAgentModelComponent,
    DeepAgentProfile,
    DeepAgentSandboxComponent,
    DeepAgentSkillComponent,
    DeepAgentToolComponent,
    SealedAsyncChildBinding,
    WorkspaceContract,
)
from mission_control.domain.execution.materialization import (
    compile_deep_agent_execution_binding,
    compose_cognitive_context_schema,
    compose_cognitive_state_schema,
)

SEALED_CHILD_PLACEMENT_ID: Final = "placement.async-agent-server-sealed-child"
SEALED_CHILD_RUN_ID: Final = "belllabs-async-child"
SEALED_CHILD_CONTEXT_FIELD: Final = "hosted_child_name"
DEEPAGENTS_VERSION: Final = "0.7.5"
# Every sealed child runs on its own state backend inside the Agent Server process; the
# server registers this exact sandbox component's factory (a hosted child never shares the
# parent's sandbox or reaches a shell).
SEALED_CHILD_SANDBOX: Final = DeepAgentSandboxComponent(
    ref=ExactDefinitionRef(
        kind=DefinitionKind.SANDBOX_PROFILE,
        logical_id="sandbox.async-child-state",
        revision=1,
        digest=sha256_digest("sandbox.async-child-state"),
    ),
    backend="state",
    runtime_digest=sha256_digest("state-backend-runtime"),
)

_BASE_STATE_CHANNELS: Final = (
    CognitiveChannelDefinition(
        name="artifact_index",
        value_kind="map",
        value_schema_ref="schema:artifact-index@1",
        reducer=CognitiveReducer.MERGE_BY_KEY,
    ),
    CognitiveChannelDefinition(
        name="child_result_index",
        value_kind="append_list",
        value_schema_ref="schema:child-result-index@1",
        reducer=CognitiveReducer.APPEND_UNIQUE_BY_ID,
    ),
    CognitiveChannelDefinition(
        name="context_manifest",
        value_kind="object",
        value_schema_ref="schema:context-manifest@1",
        reducer=CognitiveReducer.REPLACE,
    ),
)
# The deepagents 0.7.5 Skills middleware channels a child with Skills must declare.
_SKILL_STATE_CHANNELS: Final = (
    CognitiveChannelDefinition(
        name="skills_load_errors",
        value_kind="string_list",
        value_schema_ref="schema:deepagents-skill-load-errors@0.7.5",
        reducer=CognitiveReducer.REPLACE,
    ),
    CognitiveChannelDefinition(
        name="skills_metadata",
        value_kind="append_list",
        value_schema_ref="schema:deepagents-skill-metadata@0.7.5",
        reducer=CognitiveReducer.REPLACE,
    ),
)


def _ref(kind: DefinitionKind, logical_id: str) -> ExactDefinitionRef:
    return ExactDefinitionRef(
        kind=kind, logical_id=logical_id, revision=1, digest=sha256_digest(logical_id)
    )


def _pack_ref(pack: CognitiveChannelPack | CognitiveRuntimeContextPack) -> CognitiveChannelPackRef:
    return CognitiveChannelPackRef(
        logical_id=pack.logical_id,
        revision=pack.revision,
        digest=pack.digest,
        contributor=pack.contributor,
    )


def sealed_child_placement() -> DeepAgentExecutionPlacementProfile:
    """The one placement every sealed child compiles against: the Agent Server hosts it."""

    return DeepAgentExecutionPlacementProfile.create(
        logical_id=SEALED_CHILD_PLACEMENT_ID,
        revision=1,
        placement="remote_langsmith_deployment",
        python_runtime="3.12",
        package_versions={"deepagents": DEEPAGENTS_VERSION},
        deployment_id="belllabs-async-agent-server",
        task_queue="agent-server-hosted",
        checkpoint_behavior="remote_managed",
        cancellation_behavior="remote_reconcile",
        streaming_behavior="state_updates",
        message_injection_behavior="remote_thread",
        reconnect_behavior="remote_run_reconnect",
        sandbox_backends=frozenset({"state"}),
        qualification_refs=("QUAL-CP-ASYNC-SUBAGENT-LIFECYCLE",),
    )


def seal_async_child_binding(
    *,
    name: str,
    shape: Literal["inherit", "seeded"],
    system_prompt: str,
    model: DeepAgentModelComponent,
    tools: Sequence[DeepAgentToolComponent],
    skills: Sequence[DeepAgentSkillComponent],
    mcp_servers: Sequence[DeepAgentMCPServerComponent],
    agent_configuration: AgentConfiguration,
    authority_refs: tuple[str, ...],
    budget_limits: Mapping[str, int],
) -> SealedAsyncChildBinding:
    """Compile and seal one child's exact binding (see the module doc)."""

    state_pack = CognitiveChannelPack.create(
        logical_id="pack.belllabs.async-child-state",
        revision=1,
        contributor="base",
        channels=(*_BASE_STATE_CHANNELS, *(_SKILL_STATE_CHANNELS if skills else ())),
    )
    context_pack = CognitiveRuntimeContextPack.create(
        logical_id="pack.belllabs.async-child-context",
        revision=1,
        contributor="base",
        fields=(CognitiveRuntimeField(name=SEALED_CHILD_CONTEXT_FIELD, value_kind="string"),),
    )
    state_schema = compose_cognitive_state_schema(
        schema_id=f"state.async-child.{name}", packs=(state_pack,)
    )
    context_schema = compose_cognitive_context_schema(
        schema_id=f"context.async-child.{name}", packs=(context_pack,)
    )
    prompt_ref = ExactDefinitionRef(
        kind=DefinitionKind.PROMPT,
        logical_id=f"prompt.async-child.{name}",
        revision=1,
        digest=sha256_digest(system_prompt),
    )
    placement = sealed_child_placement()
    profile = DeepAgentProfile.create(
        logical_id=f"agent.async-child.{name}",
        revision=1,
        model=model,
        prompt_refs=(prompt_ref,),
        context_assembly_ref=_ref(
            DefinitionKind.WORKFLOW_CONFIGURATION, "context.async-child-assembly"
        ),
        backend_ref=_ref(DefinitionKind.RUNTIME_PROFILE, "backend.async-child-state"),
        store_ref=_ref(DefinitionKind.MEMORY_POLICY, "store.agent-server-managed"),
        checkpointer_ref=_ref(DefinitionKind.RUNTIME_PROFILE, "checkpointer.agent-server-managed"),
        tools=tuple(tools),
        mcp_servers=tuple(mcp_servers),
        skills=tuple(skills),
        sandbox=SEALED_CHILD_SANDBOX,
        tracing_policy_ref=_ref(DefinitionKind.EVALUATION_PROFILE, "trace.async-child"),
        cognitive_state_pack_refs=(_pack_ref(state_pack),),
        cognitive_context_pack_refs=(_pack_ref(context_pack),),
        compatible_placement_ids=frozenset({placement.logical_id}),
        limits=dict(budget_limits),
        agent_configuration=agent_configuration,
    )
    workspace_digest = sha256_digest(f"async-child-workspace:{name}")
    binding = compile_deep_agent_execution_binding(
        profile=profile,
        placement=placement,
        state_schema=state_schema,
        context_schema=context_schema,
        context_values={SEALED_CHILD_CONTEXT_FIELD: name},
        run_id=SEALED_CHILD_RUN_ID,
        operation_id=f"async-child:{name}",
        operation_attempt=1,
        execution_generation=1,
        erc_digest=profile.profile_digest,
        control_revision=1,
        workspace=WorkspaceContract(
            namespace_id=f"workspace-namespace:async-child:{name}",
            workspace_id=f"workspace:async-child:{name}",
            provider="state-backend",
            template_ref=_ref(DefinitionKind.WORKSPACE_TEMPLATE, "workspace.async-child"),
            exclusive_write_paths=("/workspace/child-output",),
            runtime_digest=workspace_digest,
            image_digest=workspace_digest,
            package_digest=workspace_digest,
            environment_digest=workspace_digest,
        ),
        capability_grant=CapabilityGrant(
            capabilities=frozenset({"model.invoke"}),
            tool_ids=frozenset(
                [item.tool_name for item in tools]
                + [tool.tool_name for server in mcp_servers for tool in server.tools]
            ),
            mcp_server_ids=frozenset(server.server_name for server in mcp_servers),
        ),
        reservation_id=f"reservation:async-child:{name}",
        authority_refs=authority_refs,
        redaction_policy_ref="sensitive:redact@1",
        initial_context_manifest={
            "digest": sha256_digest(f"async-child-context:{name}"),
            "entries": [],
        },
    )
    return SealedAsyncChildBinding.create(
        child_name=name,
        shape=shape,
        system_prompt_ref=prompt_ref,
        system_prompt=system_prompt,
        binding=binding,
    )


__all__ = [
    "SEALED_CHILD_PLACEMENT_ID",
    "SEALED_CHILD_SANDBOX",
    "seal_async_child_binding",
    "sealed_child_placement",
]
