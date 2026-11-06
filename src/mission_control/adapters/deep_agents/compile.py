"""The Deep Agents lane's compile and its package registration (ADR-0063, OC-R1 / OVE-196).

`DeepAgentsCompileAdapter.compile(agent, lane_options)` is the `LaneAdapter` the resolution
seam calls for a `deep_agents` node. It is pure over the deployment facts bootstrap gave the
instance (:class:`DeepAgentsDeploymentFacts`: the Deep Agent scaffold, the exact components
`mc.manifest_launch_bindings` binds per model profile, sandbox profile and catalog capability,
the digests the workers serve, the served async graphs and the registered result policies),
the neutral `mc.agent_configuration.v2` and `provider_options.deep_agents`. It maps every item
pin to its exact deployment component, hands the result to the unchanged lane adapter
(:meth:`lane.DeepAgentsLaneAdapter.adapt`), and seals what the lane needs for one node role as
canonical UTF-8 JSON (:class:`DeepAgentNodeBinding`, ``mc.deep_agent_node_binding.v1``), with
the receipt the lane adapter signed. The application never reads those bytes; the lane's
template step (``binding.py::DeepAgentsLaneBindings``) is their one reader (OC-R2).

Checks run in the lane's materialization order, which is also the order the launch author used
to report them: the model, the sandbox, the parent's exact components (MCP servers, tools,
Skills), the kinds this lane has no launch binding for (context bundles, hook scripts, a
node's plugin members, environment kits), middleware, then the children with their seeds and
the lane adapter itself. Refusals are `LaneCompileRefused` pointed into the selection, and
the launch author maps each pointer back to the manifest pointer that selected it
(`manifest_launch_inputs._manifest_pointer`): ``/model/profile`` to the node's model profile,
``/items/<i>[/...]`` to the pointer that selected item ``i`` (index into the configuration's
ordered items) with the suffix kept, ``/items/<i>/plugin`` to the plugin row that expanded
member ``i``, ``/provider_options/deep_agents[/...]`` and anything else under the node's
environment, ``/lane`` to its lane. Item configuration keys are the neutral
``domain/resolution/item_config`` vocabulary.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict

from mission_control.adapters.deep_agents.describe import (
    DEEP_AGENTS_DECLARATION,
    DEEP_AGENTS_DESCRIBE,
)
from mission_control.adapters.deep_agents.lane import (
    LANE_PROFILE,
    SEEDED_PLUGIN_MEMBER_ROLES,
    DeepAgentsAdaptation,
    DeepAgentsAdaptationRefused,
    DeepAgentsLaneAdapter,
    DeepAgentsNodeInputs,
    SeedComponents,
    SelectedSubagent,
)
from mission_control.adapters.deep_agents.routes import (
    VENDOR_FEATURES,
)
from mission_control.application.agentic_components.layering import RepoView
from mission_control.application.authoring.manifest_launch_inputs import (
    AsyncSubagentGraphBinding,
    CapabilityComponentBinding,
    DeepAgentModelBinding,
    DeepAgentScaffold,
    ManifestLaunchBindings,
    ServedComponents,
)
from mission_control.application.resolution.ports import (
    LaneRegistration,
    LaneRuntimeDependencies,
)
from mission_control.application.resolution.registries import DescribeOnlyLane, ModelCatalog
from mission_control.domain.agentic_components.projection import HostProjection
from mission_control.domain.authoring.canonical import stable_json_dump
from mission_control.domain.authoring.contracts import ExactDefinitionRef, SecretRef
from mission_control.domain.capabilities.features import FeatureStatus
from mission_control.domain.capabilities.subagents import SubagentProfile
from mission_control.domain.execution.contracts import (
    CognitiveRuntimeContextSchema,
    CognitiveStateSchema,
    DeepAgentExecutionPlacementProfile,
    DeepAgentMCPServerComponent,
    DeepAgentModelComponent,
    DeepAgentProfile,
    DeepAgentSandboxComponent,
    DeepAgentSkillComponent,
    DeepAgentToolComponent,
)
from mission_control.domain.execution.materialization_receipt import (
    MaterializationItem,
    MaterializationReceipt,
)
from mission_control.domain.resolution import item_config
from mission_control.domain.resolution.configuration import (
    AgentConfiguration,
    ConfigurationItem,
    ConfigurationItemKind,
)
from mission_control.domain.resolution.resolved import (
    LaneCompileRefused,
    RefusalCode,
    ResolutionRefused,
    SealedLaneBinding,
)

DEEP_AGENT_NODE_BINDING_SCHEMA: Final = "mc.deep_agent_node_binding.v1"
MODEL_POINTER: Final = "/model/profile"
OPTIONS_POINTER: Final = f"/provider_options/{LANE_PROFILE}"
# The catalog item kinds this lane maps to an exact deployment component
# (`mc.manifest_launch_bindings` `capabilities`).
COMPONENT_KINDS: Final[frozenset[ConfigurationItemKind]] = frozenset(
    {"mcp_server", "tool", "skill_bundle"}
)
_NO_LAUNCH_BINDING: Final = (
    "MCP servers, Skills and tools bind through mc.manifest_launch_bindings.v1 capabilities "
    "and subagent profiles through the deep_agents lane adapter; hook scripts, plugins and "
    "context bundles have no Deep Agents launch binding"
)


@dataclass(frozen=True)
class DeepAgentsDeploymentFacts:
    """What the deployment serves to this lane, fixed at bootstrap composition.

    Read from the operator-reviewed `mc.manifest_launch_bindings` file and the components the
    executing workers serve. `scaffold` is `None` when the deployment binds no Deep Agents
    scaffold (a provider-only installation); compile then refuses every node.
    """

    scaffold: DeepAgentScaffold | None
    served: ServedComponents
    model_profiles: Mapping[str, DeepAgentModelComponent] = field(default_factory=dict)
    sandbox_profiles: Mapping[str, DeepAgentSandboxComponent] = field(default_factory=dict)
    capabilities: Mapping[str, CapabilityComponentBinding] = field(default_factory=dict)
    async_graphs: Mapping[str, AsyncSubagentGraphBinding] = field(default_factory=dict)
    # The result admission policies the deployment registers; `None` leaves the check to the
    # caller (tests), a set refuses an async graph binding naming any other policy.
    async_result_policy_refs: frozenset[str] | None = None

    def __post_init__(self) -> None:
        if self.scaffold is not None:
            profile = self.scaffold.profile
            if profile.checkpointer_ref.digest not in self.served.checkpointers:
                raise ValueError("the scaffold checkpointer is not served by this deployment")
            if profile.store_ref.digest not in self.served.stores:
                raise ValueError("the scaffold store is not served by this deployment")

    @classmethod
    def from_bindings(
        cls,
        bindings: ManifestLaunchBindings,
        served: ServedComponents,
        *,
        models: ModelCatalog,
        async_result_policy_refs: frozenset[str] | None = None,
    ) -> DeepAgentsDeploymentFacts:
        return cls(
            scaffold=bindings.deep_agents,
            served=served,
            model_profiles=catalog_model_components(bindings.model_profiles, models, served),
            sandbox_profiles=dict(bindings.sandbox_profiles),
            capabilities=dict(bindings.capabilities),
            async_graphs=dict(bindings.deep_agents_async_graphs),
            async_result_policy_refs=async_result_policy_refs,
        )


MODEL_PIN_VENDOR_MISMATCH: Final = "MODEL_PIN_VENDOR_MISMATCH"
MODEL_PIN_MODEL_MISMATCH: Final = "MODEL_PIN_MODEL_MISMATCH"
MODEL_PIN_UNDECLARED: Final = "MODEL_PIN_UNDECLARED"


class ModelPinMismatch(ValueError):
    """A served model definition does not serve its catalog row's vendor and model id (OC-R6)."""

    def __init__(self, code: str, profile: str, pointer: str, message: str) -> None:
        super().__init__(f"{code} at {pointer}: {message}")
        self.code = code
        self.profile = profile
        self.pointer = pointer


def model_pin_mismatch(
    name: str, binding: DeepAgentModelBinding, vendor: str, model_id: str, served: ServedComponents
) -> tuple[str, str] | None:
    """`(code, reason)` when the definition bound to catalog profile `name` does not serve
    `vendor:model_id`; `None` when it does or is not served at all (`ITEM_PIN_UNSERVED`, later).

    Fail closed: a served digest with no declared identity is refused unless the composition is
    explicitly a test or qualification one (`ServedComponents.qualification`).
    """

    digest = binding.ref.digest
    if digest not in served.models:
        return None
    identity = served.model_identities.get(digest)
    where = f"served definition {binding.ref.logical_id} ({digest})"
    if identity is None:
        if served.qualification:
            return None
        return (
            MODEL_PIN_UNDECLARED,
            f"{where} of model profile {name} declares no vendor and model id; pin it with "
            "both (capability pins `models[].provider` and `model_id`) or declare them for a "
            "registered component",
        )
    if identity.vendor != vendor:
        return (
            MODEL_PIN_VENDOR_MISMATCH,
            f"model profile {name} is {vendor} in the model catalog, but {where} is pinned "
            f"as {identity.vendor}",
        )
    if identity.model_id != model_id:
        return (
            MODEL_PIN_MODEL_MISMATCH,
            f"model profile {name} is {model_id} in the model catalog, but {where} is pinned "
            f"as {identity.model_id}",
        )
    return None


def catalog_model_components(
    bindings: Mapping[str, DeepAgentModelBinding],
    models: ModelCatalog,
    served: ServedComponents | None = None,
) -> dict[str, DeepAgentModelComponent]:
    """The lane's exact model component per bound catalog profile (OC-R6).

    The vendor and model id are the Model Catalog row's; the deployment binding names only the
    served definition ref and default settings. A binding for a profile the catalog does not
    declare, or whose served definition does not serve the row's vendor and model id
    (`model_pin_mismatch` over `served`), fails composition closed.
    """

    declared = set(models.profiles())
    uncatalogued = sorted(set(bindings) - declared)
    if uncatalogued:
        raise ValueError(
            "mc.manifest_launch_bindings model_profiles name profiles the model catalog "
            f"(deployments/<app>/models.toml) does not declare: {uncatalogued}"
        )
    components: dict[str, DeepAgentModelComponent] = {}
    for name, binding in sorted(bindings.items()):
        row = models.get(name)
        mismatch = (
            model_pin_mismatch(name, binding, row.vendor, row.model_id, served)
            if served is not None
            else None
        )
        if mismatch is not None:
            code, reason = mismatch
            raise ModelPinMismatch(code, name, f"/model_profiles/{name}/ref", reason)
        settings = dict(binding.settings)
        if row.api_surface == "responses":
            # W1 D24: the row's API surface is the catalog's, never a binding override.
            if settings.get("use_responses_api") is False:
                raise ModelPinMismatch(
                    "api_surface_conflict",
                    name,
                    f"/model_profiles/{name}/settings/use_responses_api",
                    "the model catalog row declares the Responses API",
                )
            settings["use_responses_api"] = True
        components[name] = DeepAgentModelComponent(
            ref=binding.ref,
            provider=row.vendor,
            model_name=row.model_id,
            settings=settings,
            structured_output=row.structured_output,
        )
    return components


class DeepAgentNodeBinding(BaseModel):
    """`mc.deep_agent_node_binding.v1`: one node role on Deep Agents, before template coordinates.

    The sealed profile (scaffold plus the node's exact components, children, options and lane
    configuration), its placement and schemas with the children's slices, the scaffold's
    context and policy references, the model's effort and verbosity, the lane's own secret
    references and the signed receipt. The lane's template step (`binding.py`) adds the run,
    operation, workspace and grant coordinates and seals the exact `DeepAgentExecutionBinding`
    as the template's `lane_binding`.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["mc.deep_agent_node_binding.v1"] = DEEP_AGENT_NODE_BINDING_SCHEMA
    profile: DeepAgentProfile
    placement: DeepAgentExecutionPlacementProfile
    state_schema: CognitiveStateSchema
    context_schema: CognitiveRuntimeContextSchema
    context_values: dict[str, object]
    initial_context_manifest: dict[str, object]
    authority_refs: tuple[str, ...]
    redaction_policy_ref: str
    agent_profile_ref: ExactDefinitionRef
    tracing_policy_ref: str
    sensitive_data_policy_ref: str
    snapshot_policy_ref: str
    reasoning_effort: Literal["minimal", "low", "medium", "high"] | None = None
    verbosity: Literal["low", "medium", "high"] | None = None
    secret_refs: tuple[SecretRef, ...] = ()
    receipt: MaterializationReceipt

    def canonical_bytes(self) -> bytes:
        """Canonical UTF-8 JSON: sorted keys, sets in canonical order, no whitespace."""

        return json.dumps(
            stable_json_dump(self),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")


def _refuse(code: RefusalCode, pointer: str, reason: str, remedy: str) -> LaneCompileRefused:
    return LaneCompileRefused(
        ResolutionRefused(
            code=code, pointer=pointer, lane_profile=LANE_PROFILE, reason=reason, remedy=remedy
        )
    )


def _pin_parts(item: ConfigurationItem) -> tuple[str, str]:
    capability_id, _, rest = item.pin.partition("@")
    version, _, _ = rest.partition("#")
    return capability_id, version


def _label(item: ConfigurationItem) -> str:
    """The launch author's label: the manifest role that selected the item, and its pin."""

    capability_id, version = _pin_parts(item)
    role = item.config.get(item_config.ROLE) or item.kind
    return f"{role} {capability_id}@{version}"


def _is_seed(item: ConfigurationItem) -> bool:
    return item.config.get(item_config.SEED_OF) is not None


def _is_plugin_member(item: ConfigurationItem) -> bool:
    return item.config.get(item_config.PLUGIN_MEMBER_ROLE) is not None


def _node_plugin_member(item: ConfigurationItem) -> bool:
    """A member of a plugin the node itself selected (not a child's plugin seed)."""

    return _is_plugin_member(item) and not _is_seed(item)


def _is_child(item: ConfigurationItem) -> bool:
    return (
        item.kind == "subagent_profile"
        and item_config.PROFILE in item.config
        and not _is_seed(item)
        and not _is_plugin_member(item)
    )


@dataclass
class _Compilation:
    """The mutable working state of one pure compile."""

    agent: AgentConfiguration
    index: Mapping[str, int]
    unsupported: list[MaterializationItem] = field(default_factory=list)

    def pointer(self, item: ConfigurationItem, suffix: str = "") -> str:
        return f"/items/{self.index[item.name]}{suffix}"


class DeepAgentsCompileAdapter:
    """The `LaneAdapter` of the `deep_agents` lane (see the module doc)."""

    def __init__(self, facts: DeepAgentsDeploymentFacts | None) -> None:
        self._facts = facts

    @property
    def profile(self) -> str:
        return LANE_PROFILE

    def compile(
        self, agent: AgentConfiguration, lane_options: Mapping[str, Any]
    ) -> tuple[SealedLaneBinding, MaterializationReceipt]:
        facts = self._facts
        if facts is None:
            raise _refuse(
                "LANE_UNKNOWN",
                "/lane",
                "this process composes no deployment facts for the deep_agents lane: it executes "
                "sealed bindings and compiles none",
                "resolve the node where the launch author composes the lane's deployment facts",
            )
        if facts.scaffold is None:
            raise _refuse(
                "ITEM_PIN_UNSERVED",
                "/lane",
                "selected Deep Agents lane has no scaffold",
                "bind a Deep Agents scaffold in mc.manifest_launch_bindings, or choose a lane",
            )
        scaffold = facts.scaffold
        work = _Compilation(agent, {item.name: index for index, item in enumerate(agent.items)})
        model, effort, verbosity = self._model(agent, facts)
        sandbox = self._sandbox(work, facts, scaffold)
        mcp, skills, tools = self._components(work, facts)
        self._unsupported(work)
        self._middleware(work, scaffold)
        subagents = self._subagents(work, facts)
        try:
            adaptation = DeepAgentsLaneAdapter().adapt(
                DeepAgentsNodeInputs(
                    pointer="",
                    model=model,
                    sandbox=sandbox,
                    mcp_servers=mcp,
                    skills=skills,
                    tools=tools,
                    subagents=subagents,
                    # An empty options block is no options block (no worker default changes).
                    provider_options=dict(lane_options) or None,
                    delegation_ceiling=scaffold.profile.delegation_ceiling,
                    state_schema=scaffold.state_schema,
                    context_schema=scaffold.context_schema,
                    placement_sandbox_backends=frozenset(scaffold.placement.sandbox_backends),
                    authority_refs=scaffold.authority_refs,
                    model_profiles=facts.model_profiles,
                    served_models=facts.served.models,
                    async_graphs=facts.async_graphs,
                    async_result_policy_refs=facts.async_result_policy_refs,
                )
            )
        except DeepAgentsAdaptationRefused as error:
            raise _refuse(
                error.code or _refusal_code(error.pointer),
                error.pointer,
                error.message,
                "change the selection at this pointer to what the deep_agents lane can honour",
            ) from error
        receipt = adaptation.receipt
        if work.unsupported:
            receipt = MaterializationReceipt.create(
                lane_profile=LANE_PROFILE, items=(*receipt.items, *work.unsupported)
            )
        node = self._node_binding(
            scaffold, adaptation, receipt, model, sandbox, mcp, skills, tools, effort, verbosity
        )
        sealed = SealedLaneBinding.seal(
            lane_profile=LANE_PROFILE,
            schema_id=DEEP_AGENT_NODE_BINDING_SCHEMA,
            payload=node.canonical_bytes(),
        )
        return sealed, receipt

    def project(
        self, agent: AgentConfiguration, repo_view: RepoView | None
    ) -> HostProjection | None:
        return None  # an in-process lane writes no host files

    def check_options(self, options: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
        """`ChecksLaneOptions` (OC-R6): the `model_tools` this lane's model routes realize.

        Each selection must be a known `(vendor, feature)` of `routes.VENDOR_FEATURES`, available
        on the installed stack, with a valid configuration; the manifest compile reports the
        rest as blockers. Whether the tool's vendor matches the node's model is a launch fact
        (the resolved pin), checked by `resolve_agent_configuration`.
        """

        issues: list[tuple[str, str]] = []
        selected = options.get("model_tools") or {}
        if not isinstance(selected, Mapping):
            return (("/model_tools", "model_tools must map a vendor to its tools"),)
        for vendor, tools in sorted(selected.items()):
            if not isinstance(tools, Mapping):
                issues.append((f"/model_tools/{vendor}", "tools must map a name to its config"))
                continue
            for name, payload in sorted(tools.items()):
                pointer = f"/model_tools/{vendor}/{name}"
                row = VENDOR_FEATURES.get((vendor, name))
                if row is None:
                    known = sorted(f"{v}.{n}" for v, n in VENDOR_FEATURES if v == vendor)
                    issues.append(
                        (
                            pointer,
                            f"model_tools: unknown {vendor} tool {name!r} on the deep_agents "
                            f"lane; known: {', '.join(known) or 'none'}",
                        )
                    )
                    continue
                if row.status is not FeatureStatus.AVAILABLE:
                    issues.append(
                        (
                            pointer,
                            f"{row.id} is {row.status.value} on the installed stack; requires "
                            f"{row.requires}",
                        )
                    )
                    continue
                try:
                    row.validate_config(payload if isinstance(payload, Mapping) else None)
                except ValueError as error:
                    issues.append((pointer, str(error)))
        return tuple(issues)

    # -- the model ------------------------------------------------------------------------

    @staticmethod
    def _model(
        agent: AgentConfiguration, facts: DeepAgentsDeploymentFacts
    ) -> tuple[DeepAgentModelComponent, Any, Any]:
        pin = agent.model
        route = DEEP_AGENTS_DECLARATION.route(pin.vendor)
        if route is None or route.verdict == "unsupported":
            raise _refuse(
                "MODEL_ROUTE_UNSUPPORTED",
                MODEL_POINTER,
                f"the deep_agents lane has no route for {pin.vendor} models",
                "choose a model profile whose vendor the deep_agents lane routes",
            )
        component = facts.model_profiles.get(pin.profile)
        if component is None:
            raise _refuse(
                "ITEM_PIN_UNSERVED",
                MODEL_POINTER,
                f"model profile {pin.profile} has no Deep Agents model binding "
                "(mc.manifest_launch_bindings model_profiles)",
                "bind the catalog profile in the deployment, or choose a bound one",
            )
        if component.ref.digest not in facts.served.models:
            raise _refuse(
                "ITEM_PIN_UNSERVED",
                MODEL_POINTER,
                f"model {component.ref.logical_id} ({component.ref.digest}) is not served by "
                "this deployment: no pinned model and no deployment model factory",
                "serve the model on the workers, or choose a served model profile",
            )
        # OC-R6: the vendor and model id come from the resolved pin only; the deployment
        # binding contributes the served definition ref and its default settings.
        if pin.structured_output is not None and pin.structured_output not in (
            route.structured_output
        ):
            raise _refuse(
                "MODEL_ROUTE_UNSUPPORTED",
                MODEL_POINTER,
                f"the deep_agents lane's {pin.vendor} route does not realize the "
                f"{pin.structured_output} structured-output strategy of {pin.profile}",
                "declare a strategy the route lists in the model row, or choose another profile",
            )
        component = DeepAgentModelComponent(
            ref=component.ref,
            provider=pin.vendor,
            model_name=pin.model_id,
            settings={**component.settings, **pin.settings},
            structured_output=pin.structured_output,
        )
        return (
            component,
            component.settings.get("reasoning_effort"),
            component.settings.get("verbosity"),
        )

    # -- the sandbox ----------------------------------------------------------------------

    @staticmethod
    def _sandbox(
        work: _Compilation, facts: DeepAgentsDeploymentFacts, scaffold: DeepAgentScaffold
    ) -> DeepAgentSandboxComponent:
        chosen = [item for item in work.agent.items if item.kind == "sandbox_profile"]
        if len(chosen) != 1:
            raise _refuse(
                "ITEM_UNSUPPORTED_ON_LANE",
                "/items",
                f"a deep_agents node runs in exactly one sandbox profile, not {len(chosen)}",
                "select one sandbox profile for the node",
            )
        (item,) = chosen
        name = str(item.config.get(item_config.PROFILE_NAME, ""))
        pointer = work.pointer(item)
        component = facts.sandbox_profiles.get(name)
        if component is None:
            raise _refuse(
                "ITEM_PIN_UNSERVED",
                pointer,
                f"sandbox profile {name} has no deployment sandbox binding "
                "(mc.manifest_launch_bindings.v1 sandbox_profiles)",
                "bind the sandbox profile in the deployment, or choose a bound one",
            )
        if component.ref.digest not in facts.served.sandboxes:
            raise _refuse(
                "ITEM_PIN_UNSERVED",
                pointer,
                f"sandbox {component.ref.logical_id} is not served by this deployment",
                "serve the sandbox on the workers, or choose a served sandbox profile",
            )
        if component.backend not in scaffold.placement.sandbox_backends:
            raise _refuse(
                "ITEM_UNSUPPORTED_ON_LANE",
                pointer,
                f"sandbox backend {component.backend} is not admitted by the Deep Agent placement",
                "choose a sandbox profile whose backend the placement qualifies",
            )
        return component

    # -- the parent's exact components ----------------------------------------------------

    @classmethod
    def _components(
        cls, work: _Compilation, facts: DeepAgentsDeploymentFacts
    ) -> tuple[
        tuple[DeepAgentMCPServerComponent, ...],
        tuple[DeepAgentSkillComponent, ...],
        tuple[DeepAgentToolComponent, ...],
    ]:
        mcp: dict[str, DeepAgentMCPServerComponent] = {}
        skills: dict[str, DeepAgentSkillComponent] = {}
        tools: dict[str, DeepAgentToolComponent] = {}
        for item in work.agent.items:
            parent = not (_is_seed(item) or _node_plugin_member(item) or _is_child(item))
            # A subagent profile without its catalog body was not selected as a child (`agents:`);
            # like any other capability it needs a component binding, which none can be.
            orphan = item.kind == "subagent_profile"
            if not parent or (item.kind not in COMPONENT_KINDS and not orphan):
                continue
            binding = cls._component(work, facts, item)
            _collect(binding, mcp, skills, tools)
        return (
            tuple(mcp[key] for key in sorted(mcp)),
            tuple(skills[key] for key in sorted(skills)),
            tuple(tools[key] for key in sorted(tools)),
        )

    @staticmethod
    def _component(
        work: _Compilation, facts: DeepAgentsDeploymentFacts, item: ConfigurationItem
    ) -> CapabilityComponentBinding:
        """One item's served deployment component, or a pointed refusal."""

        capability_id, _ = _pin_parts(item)
        label = _label(item)
        pointer = work.pointer(item)
        binding = facts.capabilities.get(capability_id)
        if binding is None:
            raise _refuse(
                "ITEM_PIN_UNSERVED",
                pointer,
                f"{label} has no deployment component binding ({_NO_LAUNCH_BINDING})",
                "bind the capability's exact component in the deployment, or drop it",
            )
        if binding.catalog_digest != item.digest:
            raise _refuse(
                "ITEM_PIN_UNSERVED",
                pointer,
                f"{label} is pinned at {item.digest} but the deployment binds "
                f"{binding.catalog_digest}",
                "pin the revision the deployment binds, or rebind the deployment",
            )
        served = facts.served
        digest, kind = (
            (binding.mcp_server.ref.digest, served.mcp_servers)
            if binding.mcp_server is not None
            else (binding.skill.bundle_digest, served.skills)
            if binding.skill is not None
            else (binding.tool.ref.digest, served.tools)
            if binding.tool is not None
            else ("", frozenset[str]())
        )
        if digest not in kind:
            raise _refuse(
                "ITEM_PIN_UNSERVED",
                pointer,
                f"{label} binds a component this deployment does not serve",
                "serve the component on the workers",
            )
        return binding

    # -- what this lane has no launch binding for -----------------------------------------

    @staticmethod
    def _unsupported(work: _Compilation) -> None:
        """Kinds declared unsupported, and a node's plugin members: a plugin the node selects
        has no Deep Agents launch binding (a child's plugin seeds do), so its first member is
        refused at the plugin row (``/items/<i>/plugin``) with the plugin's pin. A hook script
        or context bundle is refused even when its id has a `capabilities` binding. Required:
        refused. Otherwise: an `unsupported` receipt row with the reason (design D9)."""

        def rank(item: ConfigurationItem) -> int:
            if _node_plugin_member(item):
                return 2
            return {"context_bundle": 0, "hook_script": 1}.get(item.kind, 3)

        candidates = sorted(
            (
                item
                for item in work.agent.items
                if _node_plugin_member(item)
                or (
                    not _is_seed(item) and DEEP_AGENTS_DECLARATION.items[item.kind] == "unsupported"
                )
            ),
            key=lambda item: (rank(item), work.index[item.name]),
        )
        for item in candidates:
            pointer = work.pointer(item)
            if _node_plugin_member(item):
                plugin = item.config.get(item_config.PLUGIN) or _label(item)
                reason = (
                    f"plugin {plugin} has no deployment component binding ({_NO_LAUNCH_BINDING})"
                )
                pointer = work.pointer(item, "/plugin")
            elif item.kind == "environment_kit":
                reason = f"{_label(item)}: the deep_agents lane runs no Environment Kit bootstrap"
            else:
                reason = (
                    f"{_label(item)} has no deployment component binding ({_NO_LAUNCH_BINDING})"
                )
            if item.required:
                raise _refuse(
                    "ITEM_UNSUPPORTED_ON_LANE",
                    pointer,
                    reason,
                    "drop the selection from this node or run the node on a lane that carries it",
                )
            work.unsupported.append(
                MaterializationItem(
                    kind=item.receipt_kind,
                    name=item.name,
                    verdict="unsupported",
                    digest=item.digest,
                    reason=reason,
                )
            )

    @staticmethod
    def _middleware(work: _Compilation, scaffold: DeepAgentScaffold) -> None:
        """A middleware item resolves when the scaffold profile serves that exact component;
        the materializer then runs it in its declared order (it is already in the profile)."""

        served = {(item.ref.logical_id, item.ref.digest) for item in scaffold.profile.middleware}
        for item in work.agent.items:
            if item.kind != "middleware":
                continue
            capability_id, _ = _pin_parts(item)
            if (capability_id, item.digest) not in served:
                raise _refuse(
                    "ITEM_PIN_UNSERVED",
                    work.pointer(item),
                    f"{_label(item)} is not a middleware component the deployment's Deep Agent "
                    "scaffold serves",
                    "serve the middleware on the scaffold profile, or drop it",
                )

    # -- children and their seeds ---------------------------------------------------------

    @classmethod
    def _subagents(
        cls, work: _Compilation, facts: DeepAgentsDeploymentFacts
    ) -> tuple[SelectedSubagent, ...]:
        children = sorted(
            (item for item in work.agent.items if _is_child(item)),
            key=lambda item: (
                int(item.config.get(item_config.POSITION, 0)),
                work.index[item.name],
            ),
        )
        selected: list[SelectedSubagent] = []
        for item in children:
            profile = SubagentProfile.model_validate(item.config[item_config.PROFILE])
            overlay = item.config.get(item_config.OVERLAY)
            capability_id, _ = _pin_parts(item)
            selected.append(
                SelectedSubagent(
                    pointer=work.pointer(item),
                    capability_id=capability_id,
                    profile=profile,
                    seeds=cls._seeds(work, facts, profile.name),
                    overlay=dict(overlay) if isinstance(overlay, Mapping) else {},
                )
            )
        return tuple(selected)

    @classmethod
    def _seeds(
        cls, work: _Compilation, facts: DeepAgentsDeploymentFacts, child: str
    ) -> SeedComponents:
        """The exact components a child's ``seeds`` bind through, in the parent's bindings.

        A plugin seed's members arrive expanded; member roles this lane does not seed into a
        child are returned as ``deferred`` for the lane adapter's receipt.
        """

        mcp: dict[str, DeepAgentMCPServerComponent] = {}
        skills: dict[str, DeepAgentSkillComponent] = {}
        tools: dict[str, DeepAgentToolComponent] = {}
        deferred: list[tuple[str, str]] = []
        seeds = sorted(
            (item for item in work.agent.items if item.config.get(item_config.SEED_OF) == child),
            key=lambda item: work.index[item.name],
        )
        for item in seeds:
            member_role = item.config.get(item_config.PLUGIN_MEMBER_ROLE)
            if member_role is not None and member_role not in SEEDED_PLUGIN_MEMBER_ROLES:
                deferred.append((str(member_role), _pin_parts(item)[0]))
                continue
            _collect(cls._component(work, facts, item), mcp, skills, tools)
        return SeedComponents(
            mcp_servers=tuple(mcp[key] for key in sorted(mcp)),
            skills=tuple(skills[key] for key in sorted(skills)),
            tools=tuple(tools[key] for key in sorted(tools)),
            deferred=tuple(deferred),
        )

    # -- the sealed node binding ----------------------------------------------------------

    @staticmethod
    def _node_binding(
        scaffold: DeepAgentScaffold,
        adaptation: DeepAgentsAdaptation,
        receipt: MaterializationReceipt,
        model: DeepAgentModelComponent,
        sandbox: DeepAgentSandboxComponent,
        mcp: Sequence[DeepAgentMCPServerComponent],
        skills: Sequence[DeepAgentSkillComponent],
        tools: Sequence[DeepAgentToolComponent],
        effort: Any,
        verbosity: Any,
    ) -> DeepAgentNodeBinding:
        profile = DeepAgentProfile.create(
            **{
                **scaffold.profile.model_dump(mode="python", exclude={"profile_digest"}),
                "model": model,
                "sandbox": sandbox,
                "mcp_servers": tuple(mcp),
                "skills": tuple(skills),
                "tools": tuple(tools),
                # P1-S2/S3: what the lane adapter made of the node's subagent profiles and
                # provider options, and the sealed lane-feature selection.
                "sync_subagents": adaptation.sync_subagents,
                "async_subagents": adaptation.async_subagents,
                "provider_options": adaptation.provider_options,
                "agent_configuration": adaptation.agent_configuration,
            }
        )
        # The references the operation resolves before cognition besides the model's: the
        # sandbox's, the children's seeded MCP credentials and the async deployment credentials
        # the parent mints its Agent Server scope claims from (P1 WP-S2).
        secrets = (
            *sandbox.credential_refs,
            *(
                ref
                for child in adaptation.sync_subagents
                for server in child.seeded_mcp_servers
                for ref in server.credential_refs
            ),
            *adaptation.secret_refs,
        )
        return DeepAgentNodeBinding(
            profile=profile,
            placement=scaffold.placement,
            state_schema=adaptation.state_schema,
            context_schema=adaptation.context_schema,
            context_values=dict(scaffold.context_values),
            initial_context_manifest=dict(scaffold.initial_context_manifest),
            authority_refs=scaffold.authority_refs,
            redaction_policy_ref=scaffold.redaction_policy_ref,
            agent_profile_ref=scaffold.agent_profile_ref,
            tracing_policy_ref=scaffold.tracing_policy_ref,
            sensitive_data_policy_ref=scaffold.sensitive_data_policy_ref,
            snapshot_policy_ref=scaffold.snapshot_policy_ref,
            reasoning_effort=effort,
            verbosity=verbosity,
            secret_refs=tuple(dict.fromkeys(secrets)),
            receipt=receipt,
        )


def _collect(
    binding: CapabilityComponentBinding,
    mcp: dict[str, DeepAgentMCPServerComponent],
    skills: dict[str, DeepAgentSkillComponent],
    tools: dict[str, DeepAgentToolComponent],
) -> None:
    if binding.mcp_server is not None:
        mcp[binding.mcp_server.ref.digest] = binding.mcp_server
    elif binding.skill is not None:
        skills[binding.skill.bundle_digest] = binding.skill
    elif binding.tool is not None:
        tools[binding.tool.ref.digest] = binding.tool


def _refusal_code(pointer: str) -> RefusalCode:
    """A lane-adapter refusal without an explicit code: an options or overrides block is the
    lane's own option container; anything else is a selection this lane cannot honour."""

    if "/provider_options/" in pointer or "/provider_overrides/" in pointer:
        return "LANE_OPTIONS_INVALID"
    return "ITEM_UNSUPPORTED_ON_LANE"


def _describe_only_harness(_dependencies: LaneRuntimeDependencies) -> DescribeOnlyLane:
    """A process that does not execute the lane publishes its describe only; the worker passes
    its composed `DeepAgentsHarness` to `LaneRegistry.register` instead."""

    return DescribeOnlyLane(DEEP_AGENTS_DESCRIBE)


def deep_agents_lane(facts: DeepAgentsDeploymentFacts | None) -> LaneRegistration:
    """The lane package's registration, over the deployment facts of this process.

    `facts` is `None` in a process that never compiles a node (the worker executes the sealed
    bindings the launch author produced); its compile then refuses every node.
    """

    return LaneRegistration(
        profile=LANE_PROFILE,
        declaration=DEEP_AGENTS_DECLARATION,
        adapter=DeepAgentsCompileAdapter(facts),
        harness_factory=_describe_only_harness,
    )


__all__ = [
    "DEEP_AGENTS_DECLARATION",
    "DEEP_AGENT_NODE_BINDING_SCHEMA",
    "DeepAgentNodeBinding",
    "DeepAgentsCompileAdapter",
    "DeepAgentsDeploymentFacts",
    "deep_agents_lane",
]
