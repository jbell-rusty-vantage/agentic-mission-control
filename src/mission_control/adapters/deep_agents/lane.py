"""Deep Agents lane adapter: a compiled node configuration → the Deep Agents exact input.

This is the one place where lane-neutral authoring becomes Deep Agents-specific. The lane's
pure compile (``compile.py::DeepAgentsCompileAdapter.compile``, the ``LaneAdapter`` the
resolution seam calls, ADR-0063) maps every ``mc.agent_configuration.v2`` item to its exact
deployment component and then calls :meth:`DeepAgentsLaneAdapter.adapt`; the lane's template
step (``binding.py::DeepAgentsLaneBindings``, OC-R2) later seals the exact binding with
``compile_deep_agent_execution_binding`` as the template's ``lane_binding``. Moved unchanged from
``application/authoring/lanes/deep_agents.py`` by OC-R1 (OVE-196). It owns three translations
and signs one receipt:

1. **Subagent profiles → Deep Agents children** (P1-S3, P1 subagents). A
   ``mc.subagent_profile.v1`` of ``kind: sync`` becomes a :class:`SyncSubagentProfile` in one
   of the two child shapes the owner decided (Q2/Q7):

   - ``capabilities: inherit`` → the lane's **general child**: the parent's model, every
     parent tool and MCP tool, every parent Skill root, the lane's default child prompt when
     the profile has none (:data:`INHERIT_CHILD_PROMPT`, receipted by digest). It is the
     explicit, receipted form of the ``general-purpose`` child deepagents would otherwise add
     silently; the materializer disables the implicit one.
   - ``capabilities: seeded`` → a child with its own selection: ``tools``, ``skills`` and
     ``mcp_servers`` narrowed from the parent's exact components, plus ``seeds`` the compiler
     resolved for the child alone (``seeded_*`` components, loaded and mounted for the child
     only), admitted against the scaffold's delegation ceiling.

   ``kind: async`` becomes an :class:`AsyncSubagentContract` against a graph the deployment
   serves (:class:`AsyncSubagentGraphBinding`) whose admission policy is registered.
   ``kind: linked_run`` is not materialized on this lane yet and is refused with the reason.
2. **Provider options and overrides → binding options** (P1-S2). ``provider_options.deep_agents``
   is parsed once, checked against the bound sandbox and placement, and sealed into the
   binding. A profile's typed ``provider_overrides.deep_agents``
   (``DeepAgentsSubagentOverrides``) moves the child's writable root and widens its state
   slice; an unknown channel is refused.
3. **Slices**. Every child gets a state slice (the BellLabs base channels) and a context slice
   (the non-restricted runtime fields), appended to the scaffold's schemas.

The receipt (:class:`MaterializationReceipt`) names every item it saw, the children's own
components included (``<child>/<component>``). A field a profile sets that this lane cannot
honour is ``degraded`` with the reason when the node still runs correctly without it
(``readonly``, ``background``, ``context_mode: fork``, ``max_turns``, a plugin seed's hook,
prompt, resource or subagent members), and refused (:class:`DeepAgentsAdaptationRefused`)
when honouring it is what the mission asked for and nothing equivalent exists (an unknown
tool, a seed outside the delegation ceiling, an unserved async graph, an unregistered
admission policy, a linked run). :data:`SUBAGENT_FIELDS` is this lane's row of the per-lane
support matrix the compile-time discriminator and ``lane describe`` read.

Pure: no I/O, no provider, no clock. Everything it needs arrives in :class:`DeepAgentsNodeInputs`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

from mission_control.adapters.deep_agents.child_binding import (
    SEALED_CHILD_SANDBOX,
    seal_async_child_binding,
)
from mission_control.adapters.deep_agents.describe import (
    DEEP_AGENTS_SUBAGENT_FIELDS as SUBAGENT_FIELDS,
)
from mission_control.adapters.deep_agents.routes import AGENT_FEATURES
from mission_control.application.authoring.manifest_launch_inputs import (
    AsyncSubagentGraphBinding,
)
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import (
    DefinitionKind,
    ExactDefinitionRef,
    SecretRef,
)
from mission_control.domain.authoring.provider_options import (
    DeepAgentsProviderOptions,
    parse_provider_options,
)
from mission_control.domain.capabilities.features import (
    AgentConfiguration,
    AgentConfigurationRefused,
    FeatureAxis,
    resolve_agent_configuration,
)
from mission_control.domain.capabilities.subagent_overrides import (
    DeepAgentsSubagentOverrides,
    parse_subagent_overrides,
)
from mission_control.domain.capabilities.subagents import SubagentProfile
from mission_control.domain.execution.contracts import (
    AsyncSubagentContract,
    CapabilityGrant,
    CognitiveRuntimeContextSchema,
    CognitiveStateSchema,
    DeepAgentMCPServerComponent,
    DeepAgentModelComponent,
    DeepAgentSandboxComponent,
    DeepAgentSkillComponent,
    DeepAgentToolComponent,
    DelegationCeiling,
    SealedAsyncChildBinding,
    SubagentContextSlice,
    SubagentStateSlice,
    SyncSubagentProfile,
)
from mission_control.domain.execution.materialization_receipt import (
    MaterializationItem,
    MaterializationReceipt,
)
from mission_control.domain.resolution.resolved import RefusalCode

LANE_PROFILE: Final = "deep_agents"
# The BellLabs base channels every child may read; never the parent's messages.
CHILD_STATE_CHANNELS: Final = frozenset(
    {"artifact_index", "child_result_index", "context_manifest"}
)
# Where a sync child may write inside the parent's backend unless its overrides move it.
CHILD_WRITABLE_ROOT: Final = "/subagents"
# The lane's default prompt for an inheriting child that declares none (Q7). It is the
# contract of the general child every framework has: do the delegated objective with the
# parent's tools and return the whole answer in the final message.
INHERIT_CHILD_PROMPT: Final = (
    "You are the parent agent's general-purpose child. You have the parent's tools, MCP tools "
    "and Skills. Complete the objective you are given with them. The parent sees only your "
    "final message, never your intermediate work, so put the complete answer there."
)
# Plugin member roles a seeded child receives today; the rest are reported degraded.
SEEDED_PLUGIN_MEMBER_ROLES: Final = frozenset({"skill", "mcp_server"})

# This lane's row of the per-lane subagent support matrix (SUBAGENT_FIELDS vocabulary) is
# declared with the lane's describe matrix (`describe.py` in this package) and re-exported here.


class DeepAgentsAdaptationRefused(ValueError):
    """The lane cannot honour what the mission asked for at this pointer; nothing degrades.

    ``code`` is the resolution refusal code the lane's compile reports (ADR-0063): set where a
    deployment fact is missing (``ITEM_PIN_UNSERVED``); otherwise the compile derives it from
    the pointer (an options or overrides block is ``LANE_OPTIONS_INVALID``, anything else
    ``ITEM_UNSUPPORTED_ON_LANE``).
    """

    def __init__(self, pointer: str, message: str, *, code: RefusalCode | None = None) -> None:
        super().__init__(f"{pointer}: {message}")
        self.pointer = pointer
        self.message = message
        self.code = code


@dataclass(frozen=True)
class SeedComponents:
    """The exact components the compiler resolved for one child alone (its ``seeds``).

    ``deferred`` lists plugin members the lane does not seed into a child yet
    (``(role, capability_id)``); they become a ``degraded`` receipt row, never a silent drop.
    """

    mcp_servers: tuple[DeepAgentMCPServerComponent, ...] = ()
    skills: tuple[DeepAgentSkillComponent, ...] = ()
    tools: tuple[DeepAgentToolComponent, ...] = ()
    deferred: tuple[tuple[str, str], ...] = ()

    @property
    def empty(self) -> bool:
        return not (self.mcp_servers or self.skills or self.tools or self.deferred)


@dataclass(frozen=True)
class SelectedSubagent:
    """One ``agents:`` entry a node selected, with the catalog profile it resolved to."""

    pointer: str
    capability_id: str
    profile: SubagentProfile
    seeds: SeedComponents = field(default_factory=SeedComponents)
    # The manifest `agents[].overlay` (readonly, is_background, model) for this node.
    overlay: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DeepAgentsNodeInputs:
    """Everything the adapter reads: neutral resolution results plus deployment facts."""

    pointer: str
    model: DeepAgentModelComponent
    sandbox: DeepAgentSandboxComponent
    mcp_servers: tuple[DeepAgentMCPServerComponent, ...]
    skills: tuple[DeepAgentSkillComponent, ...]
    tools: tuple[DeepAgentToolComponent, ...]
    subagents: tuple[SelectedSubagent, ...]
    provider_options: Mapping[str, object] | None
    delegation_ceiling: DelegationCeiling
    state_schema: CognitiveStateSchema
    context_schema: CognitiveRuntimeContextSchema
    placement_sandbox_backends: frozenset[str]
    authority_refs: tuple[str, ...]
    # Deployment model profiles a child may name instead of inheriting, and the served digests.
    model_profiles: Mapping[str, DeepAgentModelComponent] = field(default_factory=dict)
    served_models: frozenset[str] = frozenset()
    async_graphs: Mapping[str, AsyncSubagentGraphBinding] = field(default_factory=dict)
    # The result admission policies the deployment registers; None leaves the check to the
    # caller (tests), a set refuses a graph binding naming any other policy at launch.
    async_result_policy_refs: frozenset[str] | None = None


@dataclass(frozen=True)
class DeepAgentsAdaptation:
    """The lane's exact input for one node role, with its receipt."""

    sync_subagents: tuple[SyncSubagentProfile, ...]
    async_subagents: tuple[AsyncSubagentContract, ...]
    state_schema: CognitiveStateSchema
    context_schema: CognitiveRuntimeContextSchema
    provider_options: DeepAgentsProviderOptions | None
    # Sprint B: the sealed lane-feature and model-tool selection, defaults included.
    agent_configuration: AgentConfiguration
    receipt: MaterializationReceipt
    # Launch secrets the node needs beyond its model and sandbox (the async deployment
    # credentials the parent mints its scope claims from).
    secret_refs: tuple[SecretRef, ...] = ()

    @property
    def applied_degradations(self) -> tuple[str, ...]:
        return self.receipt.degradations


class DeepAgentsLaneAdapter:
    """Contract → Deep Agents adaptation (see the module doc)."""

    def adapt(self, inputs: DeepAgentsNodeInputs) -> DeepAgentsAdaptation:
        items: list[MaterializationItem] = []
        options = self._options(inputs, items)
        configuration = self._agent_configuration(inputs, options, items)
        items.extend(self._parent_items(inputs))
        sync: list[SyncSubagentProfile] = []
        asynchronous: list[AsyncSubagentContract] = []
        state_slices: list[SubagentStateSlice] = []
        context_slices: list[SubagentContextSlice] = []
        secret_refs: list[SecretRef] = []
        for selected in inputs.subagents:
            profile = selected.profile
            if profile.kind == "linked_run":
                raise DeepAgentsAdaptationRefused(
                    selected.pointer,
                    f"subagent {profile.name} is a linked_run; the deep_agents lane has no "
                    "spawning tool for linked runs yet (P1 WP-3)",
                )
            overrides = self._overrides(selected)
            state_slice, context_slice = _slices(selected, inputs, overrides)
            state_slices.append(state_slice)
            context_slices.append(context_slice)
            if profile.kind == "async":
                contract, graph = self._async_child(
                    selected, inputs, state_slice, context_slice, items
                )
                asynchronous.append(contract)
                credential = graph.credential_secret_ref
                if credential is not None:
                    secret_refs.append(credential)
            else:
                sync.append(
                    self._sync_child(selected, inputs, overrides, state_slice, context_slice, items)
                )
        receipt = MaterializationReceipt.create(lane_profile=LANE_PROFILE, items=items)
        return DeepAgentsAdaptation(
            sync_subagents=tuple(sync),
            async_subagents=tuple(asynchronous),
            state_schema=_with_state_slices(inputs.state_schema, tuple(state_slices)),
            context_schema=_with_context_slices(inputs.context_schema, tuple(context_slices)),
            provider_options=options,
            agent_configuration=configuration,
            receipt=receipt,
            secret_refs=tuple(dict.fromkeys(secret_refs)),
        )

    # -- agent configuration: lane features and model tools (sprint B) --------------------

    @staticmethod
    def _agent_configuration(
        inputs: DeepAgentsNodeInputs,
        options: DeepAgentsProviderOptions | None,
        items: list[MaterializationItem],
    ) -> AgentConfiguration:
        """Resolve the selection against the registry and receipt every item.

        Defaults (the file tools, a shell, prompt caching on Anthropic) are inserted here,
        so the sealed binding names them explicitly and the materializer never relies on
        an implicit stack. A model tool of another provider, an unknown or unavailable row,
        or an invalid configuration is a launch refusal at the manifest pointer.
        """

        pointer = f"{inputs.pointer}/provider_options/deep_agents"
        try:
            configuration, notes = resolve_agent_configuration(
                AGENT_FEATURES,
                lane=LANE_PROFILE,
                model_provider=inputs.model.provider,
                sandbox_backend=inputs.sandbox.backend,
                lane_features=options.lane_features if options is not None else None,
                model_tools=options.model_tools if options is not None else None,
            )
        except AgentConfigurationRefused as error:
            raise DeepAgentsAdaptationRefused(f"{pointer}{error.pointer}", error.message) from error
        for note in notes:
            selection = note.selection
            items.append(
                MaterializationItem(
                    kind="feature" if selection.axis is FeatureAxis.LANE_FEATURE else "model_tool",
                    name=selection.id,
                    verdict=note.verdict,
                    native_locator=note.native_locator,
                    digest=selection.config_digest,
                    reason=note.reason,
                )
            )
        return configuration

    # -- provider options and overrides ---------------------------------------------------

    @staticmethod
    def _options(
        inputs: DeepAgentsNodeInputs, items: list[MaterializationItem]
    ) -> DeepAgentsProviderOptions | None:
        if inputs.provider_options is None:
            items.append(
                MaterializationItem(
                    kind="compaction",
                    name="summarization",
                    verdict="native",
                    native_locator="worker default trigger",
                )
            )
            return None
        pointer = f"{inputs.pointer}/provider_options/deep_agents"
        try:
            parsed = parse_provider_options(LANE_PROFILE, inputs.provider_options)
        except ValueError as error:
            raise DeepAgentsAdaptationRefused(pointer, str(error)) from error
        assert isinstance(parsed, DeepAgentsProviderOptions)
        if parsed.sandbox_backend is not None:
            if parsed.sandbox_backend != inputs.sandbox.backend:
                raise DeepAgentsAdaptationRefused(
                    f"{pointer}/sandbox_backend",
                    f"the bound sandbox profile runs on {inputs.sandbox.backend}, not "
                    f"{parsed.sandbox_backend}; select a sandbox profile with that backend",
                )
            if parsed.sandbox_backend not in inputs.placement_sandbox_backends:
                raise DeepAgentsAdaptationRefused(
                    f"{pointer}/sandbox_backend",
                    f"the placement does not qualify the {parsed.sandbox_backend} backend",
                )
        items.append(
            MaterializationItem(
                kind="compaction",
                name="summarization",
                verdict="native",
                native_locator=(
                    "node summarization trigger"
                    if parsed.summarization is not None
                    else "worker default trigger"
                ),
            )
        )
        if parsed.interrupt_on:
            items.append(
                MaterializationItem(
                    kind="human_control",
                    name="interrupt_on",
                    verdict="degraded",
                    native_locator="HumanInTheLoopMiddleware interrupt",
                    reason=(
                        "declared and sealed into the binding only; the materializer wires "
                        "it once the Human Task binding lands (P1 WP-5)"
                    ),
                )
            )
        return parsed

    @staticmethod
    def _overrides(selected: SelectedSubagent) -> DeepAgentsSubagentOverrides:
        payload = selected.profile.overrides_for(LANE_PROFILE)
        try:
            parsed = parse_subagent_overrides(LANE_PROFILE, payload)
        except ValueError as error:
            raise DeepAgentsAdaptationRefused(
                f"{selected.pointer}/provider_overrides/deep_agents", str(error)
            ) from error
        assert isinstance(parsed, DeepAgentsSubagentOverrides)
        return parsed

    # -- the parent's own components -------------------------------------------------------

    @staticmethod
    def _parent_items(inputs: DeepAgentsNodeInputs) -> list[MaterializationItem]:
        items = [
            MaterializationItem(
                kind="model",
                name=inputs.model.ref.logical_id,
                verdict="native",
                native_locator=f"{inputs.model.provider}:{inputs.model.model_name}",
                digest=inputs.model.ref.digest,
                vendor=inputs.model.provider,
                model_id=inputs.model.model_name,
            ),
            MaterializationItem(
                kind="sandbox",
                name=inputs.sandbox.ref.logical_id,
                verdict="native",
                native_locator=f"backend:{inputs.sandbox.backend}",
                digest=inputs.sandbox.runtime_digest,
            ),
        ]
        items.extend(_component_items(inputs.mcp_servers, inputs.skills, inputs.tools))
        return items

    # -- sync children ---------------------------------------------------------------------

    def _sync_child(
        self,
        selected: SelectedSubagent,
        inputs: DeepAgentsNodeInputs,
        overrides: DeepAgentsSubagentOverrides,
        state_slice: SubagentStateSlice,
        context_slice: SubagentContextSlice,
        items: list[MaterializationItem],
    ) -> SyncSubagentProfile:
        profile = selected.profile
        pointer = selected.pointer
        losses: list[str] = []
        prompt = profile.prompt
        if prompt is None:
            if not profile.inherits:
                raise DeepAgentsAdaptationRefused(
                    pointer,
                    f"subagent {profile.name} pins its prompt to a bundle; the deep_agents "
                    "lane carries inline prompts only",
                )
            prompt = INHERIT_CHILD_PROMPT
        model = self._child_model(profile, inputs, pointer, selected.overlay)
        if profile.inherits:
            tool_refs: tuple[ExactDefinitionRef, ...] = ()
            skill_refs: tuple[ExactDefinitionRef, ...] = ()
            mcp_refs: tuple[ExactDefinitionRef, ...] = ()
            seeds = SeedComponents()
            if not selected.seeds.empty:
                raise DeepAgentsAdaptationRefused(
                    pointer, f"subagent {profile.name} inherits the parent's set and has seeds"
                )
        else:
            tool_refs = _narrow(
                pointer,
                profile.name,
                "tool",
                profile.tools,
                {t.tool_name: t.ref for t in inputs.tools},
            )
            skill_refs = _narrow(
                pointer,
                profile.name,
                "skill",
                profile.skills,
                {s.skill_name: s.ref for s in inputs.skills},
            )
            mcp_refs = _narrow(
                pointer,
                profile.name,
                "mcp_server",
                profile.mcp_servers,
                {m.server_name: m.ref for m in inputs.mcp_servers},
            )
            tool_refs, skill_refs, mcp_refs, seeds = _fold_shared_seeds(
                inputs, tool_refs, skill_refs, mcp_refs, self._admitted_seeds(selected, inputs)
            )
        if bool(selected.overlay.get("readonly", profile.readonly)):
            losses.append("readonly is not enforceable on an inline SubAgent (same backend rule)")
        if bool(selected.overlay.get("is_background", profile.background)):
            losses.append("a sync child runs to completion before the parent continues")
        if profile.context_mode == "fork":
            losses.append("a Deep Agents child starts isolated; the parent's messages never fork")
        if profile.max_turns is not None:
            losses.append("max_turns has no native cap on this lane")
        if profile.sandbox != "shared":
            losses.append(
                f"sandbox: {profile.sandbox} is not available; the child shares the parent's"
            )
        if profile.interrupt_on:
            losses.append(
                "interrupt_on is sealed into the binding only until the Human Task binding lands"
            )
        for role, capability_id in seeds.deferred:
            losses.append(
                f"plugin member {capability_id} ({role}) is not seeded into a child yet; "
                "skill and mcp_server members are"
            )
        budget = _budget_within_ceiling(profile, inputs.delegation_ceiling, losses)
        writable_root = overrides.writable_root or f"{CHILD_WRITABLE_ROOT}/{profile.name}"
        child = SyncSubagentProfile(
            name=profile.name,
            description=profile.description,
            system_prompt_ref=ExactDefinitionRef(
                kind=DefinitionKind.PROMPT,
                logical_id=f"prompt.subagent.{profile.name}",
                revision=1,
                digest=sha256_digest(prompt),
            ),
            system_prompt=prompt,
            model=model,
            tool_refs=tool_refs,
            skill_refs=skill_refs,
            mcp_server_refs=mcp_refs,
            state_slice_id=state_slice.slice_id,
            context_slice_id=context_slice.slice_id,
            workspace_id=f"subagent:{profile.name}",
            writable_paths=(writable_root,),
            budget_limits=budget,
            interrupt_on=profile.interrupt_on,
            inherits_parent=profile.inherits,
            seeded_tools=seeds.tools,
            seeded_skills=seeds.skills,
            seeded_mcp_servers=seeds.mcp_servers,
        )
        items.append(
            MaterializationItem(
                kind="subagent",
                name=profile.name,
                verdict="degraded" if losses else "native",
                native_locator=(
                    "create_deep_agent(subagents=[SubAgent]) inheriting every parent tool, "
                    "MCP tool and Skill"
                    if profile.inherits
                    else "create_deep_agent(subagents=[SubAgent])"
                ),
                digest=child.system_prompt_ref.digest,
                reason="; ".join(losses) or None,
            )
        )
        items.extend(
            _component_items(seeds.mcp_servers, seeds.skills, seeds.tools, child=profile.name)
        )
        return child

    @staticmethod
    def _admitted_seeds(selected: SelectedSubagent, inputs: DeepAgentsNodeInputs) -> SeedComponents:
        """The child's own components, each inside the scaffold's delegation ceiling.

        A ceiling that names tool or MCP server ids bounds what a child may bring; an empty
        ceiling set leaves admission to the compile-time pin (the catalog already admitted
        the capability for this lane and this node).
        """

        seeds = selected.seeds
        ceiling = inputs.delegation_ceiling
        name = selected.profile.name
        if ceiling.mcp_server_ids:
            outside = sorted(
                server.server_name
                for server in seeds.mcp_servers
                if server.server_name not in ceiling.mcp_server_ids
            )
            if outside:
                raise DeepAgentsAdaptationRefused(
                    f"{selected.pointer}/seeds/mcp_servers",
                    f"subagent {name} seeds MCP servers outside the delegation ceiling: {outside}",
                )
        if ceiling.tool_ids:
            outside = sorted(
                tool.tool_name for tool in seeds.tools if tool.tool_name not in ceiling.tool_ids
            )
            if outside:
                raise DeepAgentsAdaptationRefused(
                    f"{selected.pointer}/seeds/tools",
                    f"subagent {name} seeds tools outside the delegation ceiling: {outside}",
                )
        parent_tool_names = {tool.tool_name for tool in inputs.tools} | {
            tool.tool_name for server in inputs.mcp_servers for tool in server.tools
        }
        # A seed that is the parent's own exact component is shared, not a second copy
        # (`_fold_shared_seeds`); only a different component with the same tool name collides.
        parent_refs: set[ExactDefinitionRef] = {item.ref for item in inputs.tools} | {
            item.ref for item in inputs.mcp_servers
        }
        colliding = sorted(
            {tool.tool_name for tool in seeds.tools if tool.ref not in parent_refs}
            | {
                tool.tool_name
                for server in seeds.mcp_servers
                if server.ref not in parent_refs
                for tool in server.tools
            }
        )
        colliding = [item for item in colliding if item in parent_tool_names]
        if colliding:
            raise DeepAgentsAdaptationRefused(
                f"{selected.pointer}/seeds",
                f"subagent {name} seeds tools whose names the parent already has: {colliding}; "
                "narrow them from the parent instead",
            )
        return seeds

    @staticmethod
    def _child_model(
        profile: SubagentProfile,
        inputs: DeepAgentsNodeInputs,
        pointer: str,
        overlay: Mapping[str, object],
    ) -> DeepAgentModelComponent:
        requested = str(overlay.get("model", profile.model))
        if requested == "inherit":
            return inputs.model
        component = inputs.model_profiles.get(requested)
        if component is None:
            raise DeepAgentsAdaptationRefused(
                pointer,
                f"subagent {profile.name} names model profile {requested}, which has no "
                "deployment model binding",
                code="ITEM_PIN_UNSERVED",
            )
        if component.ref.digest not in inputs.served_models:
            raise DeepAgentsAdaptationRefused(
                pointer,
                f"subagent {profile.name} model {component.ref.logical_id} is not served by "
                "this deployment",
                code="ITEM_PIN_UNSERVED",
            )
        return component

    # -- async children --------------------------------------------------------------------

    def _async_child(
        self,
        selected: SelectedSubagent,
        inputs: DeepAgentsNodeInputs,
        state_slice: SubagentStateSlice,
        context_slice: SubagentContextSlice,
        items: list[MaterializationItem],
    ) -> tuple[AsyncSubagentContract, AsyncSubagentGraphBinding]:
        profile = selected.profile
        graph = inputs.async_graphs.get(profile.name)
        if graph is None:
            raise DeepAgentsAdaptationRefused(
                selected.pointer,
                f"subagent {profile.name} is async but no served Agent Server graph is bound "
                "for it (mc.manifest_launch_bindings deep_agents_async_graphs)",
                code="ITEM_PIN_UNSERVED",
            )
        if profile.effective_placement != "agent_server":
            raise DeepAgentsAdaptationRefused(
                selected.pointer,
                f"subagent {profile.name} asks for placement {profile.effective_placement}; "
                "the deep_agents lane runs async children on the Agent Server only",
            )
        known = inputs.async_result_policy_refs
        if known is not None and graph.result_admission_policy_ref not in known:
            raise DeepAgentsAdaptationRefused(
                selected.pointer,
                f"subagent {profile.name} names result admission policy "
                f"{graph.result_admission_policy_ref}, which this deployment does not "
                f"register; known: {sorted(known)}",
                code="ITEM_PIN_UNSERVED",
            )
        losses: list[str] = []
        if profile.readonly:
            losses.append("readonly is not a hosted graph setting; the graph's own ceiling applies")
        if profile.sandbox != "own":
            losses.append("a hosted child always runs in the graph's own sandbox")
        sealed: SealedAsyncChildBinding | None = None
        child_items: list[MaterializationItem] = []
        if graph.binding_mode == "sealed_child":
            sealed = self._seal_async_child(selected, inputs, losses, child_items)
            graph_binding_digest = sealed.sealed_digest
            locator = (
                f"agent_server:{graph.graph_id}@{graph.graph_revision} sealed child binding "
                "(one assistant per binding and scope)"
            )
        else:
            graph_binding_digest = graph.graph_binding_digest
            locator = f"agent_server:{graph.graph_id}@{graph.graph_revision}"
            if not selected.seeds.empty or profile.seeds is not None:
                losses.append(
                    "seeds do not reach an exact hosted graph; bind the profile to the "
                    "sealed-child graph (binding_mode: sealed_child) for its own configuration"
                )
        contract = AsyncSubagentContract.create(
            contract_id=f"async-subagent:{profile.name}:{graph_binding_digest}",
            name=profile.name,
            description=profile.description,
            graph_id=graph.graph_id,
            graph_revision=graph.graph_revision,
            graph_binding_digest=graph_binding_digest,
            agent_protocol_url=graph.agent_protocol_url,
            deployment_credential_ref=graph.deployment_credential_ref,
            objective_schema_ref=graph.objective_schema_ref,
            result_schema_ref=graph.result_schema_ref,
            context_slice_id=context_slice.slice_id,
            state_slice_id=state_slice.slice_id,
            capability_ceiling=CapabilityGrant(
                capabilities=frozenset(),
                tool_ids=frozenset(profile.tools),
                mcp_server_ids=frozenset(profile.mcp_servers),
            ),
            authority_refs=inputs.authority_refs,
            budget_limits=dict(profile.budget) or dict(graph.default_budget_limits),
            dependency_classes=graph.dependency_classes,
            timeout_seconds=graph.timeout_seconds,
            cancellation_propagation=graph.cancellation_propagation,
            late_result_policy=graph.late_result_policy,
            fallback_policy=graph.fallback_policy,
            result_admission_policy_ref=graph.result_admission_policy_ref,
            child_binding=sealed,
        )
        items.append(
            MaterializationItem(
                kind="subagent",
                name=profile.name,
                verdict="degraded" if losses else "native",
                native_locator=locator,
                digest=graph_binding_digest,
                reason="; ".join(losses) or None,
            )
        )
        items.extend(child_items)
        return contract, graph

    def _seal_async_child(
        self,
        selected: SelectedSubagent,
        inputs: DeepAgentsNodeInputs,
        losses: list[str],
        items: list[MaterializationItem],
    ) -> SealedAsyncChildBinding:
        """The child's own exact binding (OVE-184): prompt, model, tools, Skills, MCP.

        An inheriting child takes the parent's model, tools, MCP servers and Skills and the
        lane's general child prompt when it names none; a seeded child narrows the parent's
        components and brings its own seeds, admitted against the delegation ceiling exactly
        as a sync child's. A field the hosted child cannot honour and the mission named as a
        requirement refuses (a prompt bundle, an approval gate); a loss the child still runs
        correctly without is recorded ``degraded``. ``max_turns`` becomes the registry's
        ``deep_agents.call_limits`` row (OVE-148), so the child's own cap is native.
        """

        profile = selected.profile
        pointer = selected.pointer
        if profile.interrupt_on:
            raise DeepAgentsAdaptationRefused(
                f"{pointer}/interrupt_on",
                f"subagent {profile.name} names approval gates; a hosted async child cannot "
                "pause for the Human Task Service, so the gate would never be enforced",
            )
        prompt = profile.prompt
        if prompt is None:
            if not profile.inherits:
                raise DeepAgentsAdaptationRefused(
                    pointer,
                    f"subagent {profile.name} pins its prompt to a bundle; the sealed async "
                    "child carries inline prompts only",
                )
            prompt = INHERIT_CHILD_PROMPT
        model = self._child_model(profile, inputs, pointer, selected.overlay)
        tools: Sequence[DeepAgentToolComponent]
        skills: Sequence[DeepAgentSkillComponent]
        mcp_servers: Sequence[DeepAgentMCPServerComponent]
        if profile.inherits:
            if not selected.seeds.empty:
                raise DeepAgentsAdaptationRefused(
                    pointer, f"subagent {profile.name} inherits the parent's set and has seeds"
                )
            tools, skills, mcp_servers = inputs.tools, inputs.skills, inputs.mcp_servers
        else:
            seeds = self._admitted_seeds(selected, inputs)
            _narrow(
                pointer,
                profile.name,
                "tool",
                profile.tools,
                {item.tool_name: item.ref for item in inputs.tools},
            )
            _narrow(
                pointer,
                profile.name,
                "skill",
                profile.skills,
                {item.skill_name: item.ref for item in inputs.skills},
            )
            _narrow(
                pointer,
                profile.name,
                "mcp_server",
                profile.mcp_servers,
                {item.server_name: item.ref for item in inputs.mcp_servers},
            )
            tools = _unique(
                (*(item for item in inputs.tools if item.tool_name in profile.tools), *seeds.tools)
            )
            skills = _unique(
                (
                    *(item for item in inputs.skills if item.skill_name in profile.skills),
                    *seeds.skills,
                )
            )
            mcp_servers = _unique(
                (
                    *(
                        item
                        for item in inputs.mcp_servers
                        if item.server_name in profile.mcp_servers
                    ),
                    *seeds.mcp_servers,
                )
            )
            for role, capability_id in seeds.deferred:
                losses.append(
                    f"plugin member {capability_id} ({role}) is not seeded into a child yet; "
                    "skill and mcp_server members are"
                )
        if profile.context_mode == "fork":
            losses.append(
                "an async child starts from its objective; the parent's messages never fork"
            )
        lane_features: dict[str, dict[str, object]] | None = None
        if profile.max_turns is not None:
            lane_features = {"call_limits": {"model_calls_per_run": profile.max_turns}}
        try:
            configuration, notes = resolve_agent_configuration(
                AGENT_FEATURES,
                lane=LANE_PROFILE,
                model_provider=model.provider,
                sandbox_backend=SEALED_CHILD_SANDBOX.backend,
                lane_features=lane_features,
                model_tools=None,
            )
        except AgentConfigurationRefused as error:
            raise DeepAgentsAdaptationRefused(f"{pointer}{error.pointer}", error.message) from error
        sealed = seal_async_child_binding(
            name=profile.name,
            shape="inherit" if profile.inherits else "seeded",
            system_prompt=prompt,
            model=model,
            tools=tools,
            skills=skills,
            mcp_servers=mcp_servers,
            agent_configuration=configuration,
            authority_refs=inputs.authority_refs,
            budget_limits=_budget_within_ceiling(profile, inputs.delegation_ceiling, losses),
        )
        child = profile.name
        items.append(
            MaterializationItem(
                kind="model",
                name=f"{child}/{model.ref.logical_id}",
                verdict="native",
                native_locator=f"child {child}: {model.provider}:{model.model_name}",
                digest=model.ref.digest,
                vendor=model.provider,
                model_id=model.model_name,
            )
        )
        items.extend(
            MaterializationItem(
                kind="feature" if note.selection.axis is FeatureAxis.LANE_FEATURE else "model_tool",
                name=f"{child}/{note.selection.id}",
                verdict=note.verdict,
                native_locator=f"child {child}: {note.native_locator}",
                digest=note.selection.config_digest,
                reason=note.reason,
            )
            for note in notes
        )
        items.extend(_component_items(mcp_servers, skills, tools, child=child))
        return sealed


# -- helpers ----------------------------------------------------------------------------------


def _unique[T: (DeepAgentToolComponent, DeepAgentSkillComponent, DeepAgentMCPServerComponent)](
    items: Sequence[T],
) -> tuple[T, ...]:
    """Components in order, a shared exact component (a seed the parent also selects) once."""

    seen: set[ExactDefinitionRef] = set()
    unique: list[T] = []
    for item in items:
        if item.ref not in seen:
            seen.add(item.ref)
            unique.append(item)
    return tuple(unique)


def _component_items(
    mcp_servers: Sequence[DeepAgentMCPServerComponent],
    skills: Sequence[DeepAgentSkillComponent],
    tools: Sequence[DeepAgentToolComponent],
    *,
    child: str | None = None,
) -> list[MaterializationItem]:
    """Receipt rows for exact components; a child's rows are named ``<child>/<component>``."""

    prefix = f"{child}/" if child else ""
    where = f"child {child}: " if child else ""
    items: list[MaterializationItem] = []
    items.extend(
        MaterializationItem(
            kind="mcp_server",
            name=f"{prefix}{server.server_name}",
            verdict="native",
            native_locator=f"{where}in-process MCP client ({server.transport})",
            digest=server.schema_digest,
        )
        for server in mcp_servers
    )
    items.extend(
        MaterializationItem(
            kind="skill",
            name=f"{prefix}{skill.skill_name}",
            verdict="native",
            native_locator=f"{where}{skill.mount_root}",
            digest=skill.bundle_digest,
        )
        for skill in skills
    )
    items.extend(
        MaterializationItem(
            kind="tool",
            name=f"{prefix}{tool.tool_name}",
            verdict="native",
            native_locator=f"{where}in-process tool",
            digest=tool.schema_digest,
        )
        for tool in tools
    )
    return items


def _fold_shared_seeds(
    inputs: DeepAgentsNodeInputs,
    tool_refs: tuple[ExactDefinitionRef, ...],
    skill_refs: tuple[ExactDefinitionRef, ...],
    mcp_refs: tuple[ExactDefinitionRef, ...],
    seeds: SeedComponents,
) -> tuple[
    tuple[ExactDefinitionRef, ...],
    tuple[ExactDefinitionRef, ...],
    tuple[ExactDefinitionRef, ...],
    SeedComponents,
]:
    """A seed the parent already selects (same exact component) becomes a narrowing.

    Seeds are the child's own pins, independent of the parent's choice; when both resolve to
    the same exact component there is one server, one Skill or one tool to materialize, and
    the child shares the parent's loaded instance instead of connecting a second one.
    """

    parent_tools = {item.ref for item in inputs.tools}
    parent_skills = {item.ref for item in inputs.skills}
    parent_mcp = {item.ref for item in inputs.mcp_servers}

    def merged(
        refs: tuple[ExactDefinitionRef, ...], shared: list[ExactDefinitionRef]
    ) -> tuple[ExactDefinitionRef, ...]:
        return tuple(dict.fromkeys((*refs, *shared)))

    shared_tools = [item.ref for item in seeds.tools if item.ref in parent_tools]
    shared_skills = [item.ref for item in seeds.skills if item.ref in parent_skills]
    shared_mcp = [item.ref for item in seeds.mcp_servers if item.ref in parent_mcp]
    remaining = SeedComponents(
        mcp_servers=tuple(item for item in seeds.mcp_servers if item.ref not in parent_mcp),
        skills=tuple(item for item in seeds.skills if item.ref not in parent_skills),
        tools=tuple(item for item in seeds.tools if item.ref not in parent_tools),
        deferred=seeds.deferred,
    )
    return (
        merged(tool_refs, shared_tools),
        merged(skill_refs, shared_skills),
        merged(mcp_refs, shared_mcp),
        remaining,
    )


def _narrow(
    pointer: str,
    child: str,
    kind: str,
    requested: Sequence[str],
    available: Mapping[str, ExactDefinitionRef],
) -> tuple[ExactDefinitionRef, ...]:
    """The parent components a child names; an unknown name is refused, never dropped."""

    refs: list[ExactDefinitionRef] = []
    for name in requested:
        ref = available.get(name)
        if ref is None:
            raise DeepAgentsAdaptationRefused(
                pointer,
                f"subagent {child} names {kind} {name!r}, which the parent node does not "
                f"select; available: {sorted(available)} (a capability of the child's own "
                "is a seed)",
            )
        refs.append(ref)
    return tuple(refs)


def _budget_within_ceiling(
    profile: SubagentProfile, ceiling: DelegationCeiling, losses: list[str]
) -> dict[str, int]:
    """A child spends its own budget only where the scaffold ceiling grants that dimension."""

    budget: dict[str, int] = {}
    for dimension, amount in profile.budget.items():
        limit = ceiling.budget_limits.get(dimension)
        if limit is None:
            losses.append(
                f"budget {dimension} is not in the delegation ceiling; the child spends from "
                "the parent's reservation"
            )
        else:
            budget[dimension] = min(amount, limit)
            if amount > limit:
                losses.append(f"budget {dimension} capped at the delegation ceiling {limit}")
    return budget


def _slices(
    selected: SelectedSubagent,
    inputs: DeepAgentsNodeInputs,
    overrides: DeepAgentsSubagentOverrides,
) -> tuple[SubagentStateSlice, SubagentContextSlice]:
    name = selected.profile.name
    channels = frozenset(channel.name for channel in inputs.state_schema.channels)
    extra = frozenset(overrides.state_channels)
    unknown = sorted(extra - channels)
    if unknown:
        raise DeepAgentsAdaptationRefused(
            f"{selected.pointer}/provider_overrides/deep_agents/state_channels",
            f"subagent {name} asks for state channels the parent schema does not carry: {unknown}",
        )
    fields = frozenset(
        item.name for item in inputs.context_schema.fields if item.sensitivity != "restricted"
    )
    return (
        SubagentStateSlice(
            slice_id=f"subagent:{name}:state",
            channel_names=(CHILD_STATE_CHANNELS | extra) & channels,
        ),
        SubagentContextSlice(slice_id=f"subagent:{name}:context", field_names=fields),
    )


def _with_state_slices(
    schema: CognitiveStateSchema, slices: tuple[SubagentStateSlice, ...]
) -> CognitiveStateSchema:
    if not slices:
        return schema
    existing = {item.slice_id for item in schema.subagent_slices}
    added = tuple(item for item in slices if item.slice_id not in existing)
    return CognitiveStateSchema.create(
        **schema.model_dump(mode="python", exclude={"schema_digest", "subagent_slices"}),
        subagent_slices=(*schema.subagent_slices, *added),
    )


def _with_context_slices(
    schema: CognitiveRuntimeContextSchema, slices: tuple[SubagentContextSlice, ...]
) -> CognitiveRuntimeContextSchema:
    if not slices:
        return schema
    existing = {item.slice_id for item in schema.subagent_slices}
    added = tuple(item for item in slices if item.slice_id not in existing)
    return CognitiveRuntimeContextSchema.create(
        **schema.model_dump(mode="python", exclude={"schema_digest", "subagent_slices"}),
        subagent_slices=(*schema.subagent_slices, *added),
    )


__all__ = [
    "CHILD_STATE_CHANNELS",
    "INHERIT_CHILD_PROMPT",
    "LANE_PROFILE",
    "SEEDED_PLUGIN_MEMBER_ROLES",
    "SUBAGENT_FIELDS",
    "DeepAgentsAdaptation",
    "DeepAgentsAdaptationRefused",
    "DeepAgentsLaneAdapter",
    "DeepAgentsNodeInputs",
    "SeedComponents",
    "SelectedSubagent",
]
