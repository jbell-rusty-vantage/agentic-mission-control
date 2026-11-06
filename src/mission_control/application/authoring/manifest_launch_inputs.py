"""Production launch inputs of a manifest run (MP-02, SPEC-05 "Mapping", ADR-0029).

Lowering pins every resolved capability by exact ref and leaves the lane execution binding to
the semantic input binding at launch. :class:`ManifestLaunchInputAuthor` is that binding's
production author: from the admitted Effective Run Configuration and the run's committed
``MissionDefinition@1`` it resolves, per lowered stage or Goal Loop role, the effective node
environment against the deployment's operator-reviewed ``mc.manifest_launch_bindings.v1``
(Deep Agent profile scaffold and placement, model and sandbox profile components, catalog
capability components) and the components the deployment actually serves. Nothing is
fabricated: a lane, model, sandbox, credential or capability without an exact deployment
binding fails before any provider dispatch with :class:`ManifestLaunchBindingError`, which
names the manifest pointer that selected it. Credentials are ``SecretRef`` names only.

Templates persist once under ``semantic-input:manifest:{run_id}`` in the immutable template
stores; a later call (a duplicate chain delivery, a retried start) reuses the frozen templates
and never authors different ones.

MP-02 for the local provider lanes: a ``claude_agent_sdk`` or ``codex`` stage or Goal Loop role
of a ``mission/v2`` definition resolves against the ``providers`` section of
``mc.manifest_launch_bindings.v2`` (``provider_launch``) into a ``mc.execution_binding.v2``
sealed as the template's ``lane_binding``, whose ``execution_runtime``, ``lane_profile`` and
``lane_dispatch`` route it to the lane's task queue. Hosted profiles (``claude_cloud``,
``codex_cloud``) are refused at their lane pointer (evidence-blocked, MP-18/19).

The Cursor lanes: a ``cursor_local`` or ``cursor_cloud`` stage or Goal Loop role of a
``mission/v1`` or ``mission/v2`` definition resolves against ``providers.cursor_local`` /
``providers.cursor_cloud`` (``cursor_launch``) into a sealed ``mc.cursor_binding.v2`` routed to
the lane's task queue, pinning its skills, MCP servers, subagents, hook scripts and plugins and
the projection digests the Cursor harness re-renders at ``prepare``. What that binding cannot
carry (other kinds such as deterministic executors, model settings) is refused at its pointer.

MO-15: a declared ``network`` policy is resolved per node role (the kit's egress through the
author's kit port, the installation's Signal Ingress host) and sealed on the binding the lane
projects it from; a policy that cannot resolve fails at its pointer, never as a dropped host.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Final, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from pydantic_core import to_jsonable_python

from mission_control.application.agentic_components.projections import HostProjectors
from mission_control.application.authoring.cursor_launch import (
    CURSOR_PROFILES,
    CURSOR_PROJECTED_KINDS,
    CursorCloudLane,
    CursorLocalLane,
    CursorRepository,
    cursor_projection,
    cursor_projection_digests,
)
from mission_control.application.authoring.goal_verifier_objective import goal_verifier_objective
from mission_control.application.authoring.manifest_submit import (
    LaunchInputPort,
    ManifestStartUnavailable,
)
from mission_control.application.authoring.provider_launch import (
    HOSTED_API_PROFILES,
    HOSTED_PROVIDER_PROFILES,
    LAUNCH_BINDINGS_SCHEMA_V2,
    LOCAL_PROVIDER_PROFILES,
    ProjectionRowsPort,
    ProviderLaneBinding,
    ProviderLanes,
    WorkspaceProvision,
    binding_capability_pins,
    capability_pin_key,
    materialization_digest,
    model_vendor,
)
from mission_control.application.authoring.service import ControlPlaneService
from mission_control.application.authoring.subagent_discriminator import (
    seed_owner,
)
from mission_control.application.capabilities.bundle_custody import BundleCustodyUnavailable
from mission_control.application.chains.relay import ChainIntent
from mission_control.application.context.pack_service import session_lane_output_path
from mission_control.application.execution.approvals_coverage import (
    GateCoverageRequirement,
    admit_gate_coverage,
)
from mission_control.application.execution.harness.describe import declared_matrix
from mission_control.application.execution.service import RunControlService
from mission_control.application.knowledge.roles import PRODUCER_TOOL_CAPABILITIES
from mission_control.application.programs.human_gates import (
    DEFAULT_GOAL_REVIEWERS,
    goal_human_review,
    stagegraph_human_gates,
)
from mission_control.application.programs.service import (
    GoalDirectedLaunchService,
    StageGraphLaunchService,
    WorkflowLaunchDispatcher,
)
from mission_control.application.programs.stage_inputs import stagegraph_authored_inputs
from mission_control.application.resolution.lane_bindings import (
    LaneTemplateBinder,
    LaneTemplateCoordinates,
)
from mission_control.application.resolution.ports import ApplicationRegistry, ModelCatalog
from mission_control.application.resolution.resolver import RuntimeResolver
from mission_control.application.workspaces.errors import WorkspaceError
from mission_control.application.workspaces.policy import admit_policy, policy_pin
from mission_control.domain.agentic_components.projection import ResolvedCapability
from mission_control.domain.authoring.canonical import (
    sha256_digest,
    stable_json_digest,
    stable_json_dump,
)
from mission_control.domain.authoring.contracts import (
    AuthorityCeiling,
    DefinitionKind,
    EffectiveRunConfiguration,
    ExactDefinitionRef,
    GoalDirectedBlueprint,
    SecretRef,
    StageGraphBlueprint,
    SubagentProfileDefinition,
    WorkflowWorkspaceContract,
)
from mission_control.domain.authoring.manifest import Behavior
from mission_control.domain.authoring.manifest_v2 import (
    ContinuationPolicy,
    RequiredFeatures,
    WorkspaceSelectionV2,
)
from mission_control.domain.authoring.mission_definition import (
    DefinitionCapability,
    DefinitionNode,
    EnvironmentSelections,
    MissionDefinition,
)
from mission_control.domain.authoring.mission_environment import KitRequirements
from mission_control.domain.capabilities.subagents import SubagentProfile
from mission_control.domain.context import transfer_builders
from mission_control.domain.execution.bindings import (
    REPOSITORY_BOUND_PROFILES,
    BindingBudgets,
    ClaudeManagedOptions,
    ClaudeSdkOptions,
    CodexAgentsOptions,
    CodexAppServerOptions,
    EnvironmentBinding,
    ModelPin,
    ProviderExecutionBinding,
    WorkflowRequirements,
    WorkspacePolicyPin,
)
from mission_control.domain.execution.contracts import (
    SESSION_LANE_RUNTIMES,
    AsyncSubagentDependencyClass,
    CapabilityGrant,
    CognitiveRuntimeContextSchema,
    CognitiveStateSchema,
    DeepAgentExecutionPlacementProfile,
    DeepAgentMCPServerComponent,
    DeepAgentProfile,
    DeepAgentSandboxComponent,
    DeepAgentSkillComponent,
    DeepAgentToolComponent,
    ModelPolicy,
    OperationAttemptIdentity,
    OperationExecutionRequest,
    PromptSegment,
    PromptTrustClass,
    StructuredOutputBinding,
    WorkspaceContract,
    WorkspaceOwner,
    WorkspaceOwnerKind,
    WorkspaceSlotBinding,
)
from mission_control.domain.execution.data_class import (
    DATA_CLASSES,
    DEFAULT_DATA_CLASS_POLICY,
    DataClass,
    DataClassPolicy,
    DataClassSource,
    admit_data_class,
    undeclared_data_class,
)
from mission_control.domain.execution.lane_requirements import RequirementSet, admit_requirements
from mission_control.domain.execution.lanes import (
    LANE_OF_PROFILE,
    RUNTIME_OF_LANE,
    CursorBudgets,
    CursorCloudOptions,
    CursorExecutionBinding,
    CursorProjections,
    CursorProviderEnvironment,
    CursorWorkspace,
    cursor_projected_pins,
)
from mission_control.domain.execution.network_policy import (
    NetworkHosts,
    NetworkPolicyUnresolvable,
    ResolvedNetworkPolicy,
    requires_signal_ingress,
    resolve_network_policy,
)
from mission_control.domain.outputs.contracts import Enforcement, OutputForm
from mission_control.domain.programs.contracts import StageAuthoredInput
from mission_control.domain.programs.goal_directed_runtime import GoalNamedExecutorObservation
from mission_control.domain.programs.human_gate import HumanGateSpec
from mission_control.domain.resolution import item_config
from mission_control.domain.resolution.configuration import (
    AgentConfiguration,
    ConfigurationItem,
    ConfigurationItemKind,
    Family,
    Vendor,
)
from mission_control.domain.resolution.configuration import ModelPin as AgentModelPin
from mission_control.domain.resolution.resolved import (
    ResolutionRefused,
    ResolvedRuntime,
    receiver_transfer_base,
)
from mission_control.domain.resolution.selection import LaneAdmission, RuntimeSelection


def _submits_named_outputs(runtime: ResolvedRuntime) -> bool:
    """Whether a resolved agent carries the knowledge ``submit_output`` tool (WI-02)."""

    return any(
        item.name in {"submit_output", "tool.knowledge-submit-output"}
        or item.pin.startswith("tool.knowledge-submit-output")
        for item in runtime.agent.items
    )


def _goal_assessment_subjects(definition: MissionDefinition) -> tuple[tuple[str, str], ...]:
    """Nominate declared criterion evidence, separately from final output fulfillment.

    A Goal Loop can produce a required effect only after its report is independently
    assessed. The criterion's evidence names that assessment's subjects; the run's
    remaining promises are still checked by convergence. Legacy criteria which name
    external evidence rather than output slots retain their required-output subjects.
    Merely declaring an expected or optional output does not nominate it for assessment.
    An explicitly nominated subject remains mandatory at the transfer boundary.
    """

    root = definition.program
    evidence = {name for criterion in definition.criteria for name in criterion.evidence}
    nominated = tuple(
        output for output in root.outputs if output.name in evidence or output.key in evidence
    )
    subjects = nominated or tuple(output for output in root.outputs if output.required)
    return tuple((root.key, output.key) for output in subjects)


LAUNCH_BINDINGS_SCHEMA: Literal["mc.manifest_launch_bindings.v1"] = "mc.manifest_launch_bindings.v1"
DEEP_AGENTS_LANE = "deep_agents"
PROVIDER_PROFILES = frozenset(
    (*LOCAL_PROVIDER_PROFILES, *HOSTED_PROVIDER_PROFILES, *HOSTED_API_PROFILES)
)
CURSOR_LANE_PROFILES = frozenset(CURSOR_PROFILES)
# Manifest capability kinds a Cursor binding can project (`cursor_launch.CURSOR_PROJECTED_KINDS`).
_CURSOR_MANIFEST_KINDS = frozenset(
    {"skill_bundle", "mcp_server", "subagent_profile", "hook_script", "plugin"}
)
GOAL_ROLES: tuple[Literal["executor", "verifier"], ...] = ("executor", "verifier")
TEMPLATE_REVISION = 1
"""Templates are frozen per run; the runtime rebinds revision, identity and reservation."""
_CAPABILITY_GROUPS = (
    "capabilities",
    "workspace.skills",
    "workspace.context",
    "agents",
    "hooks",
    "plugins",
)
_MODEL_SETTINGS: dict[str, str] = {
    "temperature": "temperature",
    "reasoning.effort": "reasoning_effort",
    "verbosity": "verbosity",
    "max_output_tokens": "max_completion_tokens",
    "service_tier": "service_tier",
}
_REASONING = ("minimal", "low", "medium", "high")
_VERBOSITY = ("low", "medium", "high")


def binding_ref(run_id: str) -> str:
    """The semantic input binding of a manifest run (one per run, frozen at first launch)."""

    return f"semantic-input:manifest:{run_id}"


def template_key(stage_id: str, slot_id: str, variant_id: str) -> str:
    """The StageGraph template key the stage service resolves an operation slot by."""

    return f"{stage_id}/{slot_id}/{variant_id}"


class ManifestLaunchBindingError(ManifestStartUnavailable):
    """A launch input the manifest selected has no exact deployment binding."""

    code = "launch_binding_unavailable"

    def __init__(self, pointer: str, message: str) -> None:
        self.pointer = pointer
        self.reason = message
        super().__init__(f"{pointer}: {message}")


class ManifestCompletionUnavailable(ManifestLaunchBindingError):
    code = "completion_evaluator_unavailable"


class ManifestDependentInputsUnavailable(ManifestLaunchBindingError):
    """OVE-169: a Stage Graph stage declares `from: <producer>.<output>` inputs, which are
    required (`DEPENDENT_INPUT_REQUIRED`) and admitted only from an accepted revision; without a
    composed trusted settlement (both independent evaluator credentials) nothing can promote, so
    the launch refuses instead of starting a run whose dependent stages would wait forever."""

    code = "dependent_inputs_unavailable"


class ManifestTrustedAssessmentUnavailable(ManifestDependentInputsUnavailable):
    """W1 D30: a promise's requirement names the application's trusted assessment pin (for
    example `knowledge.report.assess@1`), which only a composed trusted settlement (both
    independent evaluator credentials) can judge; without one the revision would get no
    assessment and no wait, the promise would stay missing and the run would fail. Any family
    refuses at launch with this typed code (the dependent-input refusal covers Stage Graph
    dependent inputs only)."""

    code = "trusted_assessment_unavailable"


class ManifestOutputValidationUnavailable(ManifestLaunchBindingError):
    code = "output_schema_validator_unavailable"


class ManifestBundleCustodyUnavailable(ManifestLaunchBindingError):
    """A selected skill bundle or hook script cannot materialize: no bundle custody is
    composed, so the launch refuses before any worker prepares a lane (MO-01)."""

    code = "bundle_custody_unavailable"


# --- The deployment file (`mc.manifest_launch_bindings.v1`) -------------------------------


class _File(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DeepAgentScaffold(_File):
    """The reviewed profile and placement a manifest node's components are bound into.

    The scaffold carries no MCP server, Skill, tool or subagent: those come only from what
    the manifest selected (``capabilities``) and the deployment serves.
    """

    profile: DeepAgentProfile
    placement: DeepAgentExecutionPlacementProfile
    state_schema: CognitiveStateSchema
    context_schema: CognitiveRuntimeContextSchema
    context_values: dict[str, object]
    initial_context_manifest: dict[str, object]
    authority_refs: tuple[str, ...] = Field(min_length=1)
    redaction_policy_ref: str = Field(min_length=1)
    agent_profile_ref: ExactDefinitionRef
    tracing_policy_ref: str = Field(min_length=1)
    sensitive_data_policy_ref: str = Field(min_length=1)
    snapshot_policy_ref: str = Field(min_length=1)
    workspace: WorkspaceProvision
    goal_output_schemas: dict[Literal["executor", "verifier"], StructuredOutputBinding] = Field(
        default_factory=dict
    )

    @model_validator(mode="after")
    def scaffold_selects_nothing(self) -> DeepAgentScaffold:
        profile = self.profile
        if (
            profile.mcp_servers
            or profile.skills
            or profile.tools
            or profile.sync_subagents
            or profile.async_subagents
        ):
            raise ValueError(
                "the Deep Agent scaffold carries no MCP server, Skill, tool or subagent; "
                "manifest capabilities bind them"
            )
        if self.placement.logical_id not in profile.compatible_placement_ids:
            raise ValueError("the scaffold profile is not compatible with its placement")
        return self


class DeepAgentModelBinding(_File):
    """What the Deep Agents lane serves for one Model Catalog profile (OC-R6).

    A reference to the catalog: the key is the Model Profile name in
    `deployments/<app>/models.toml`, which alone fixes the vendor and model id; this entry names
    only the exact model definition the workers serve it as (the `ExactComponentRegistry` key)
    and the deployment's default model settings. A legacy entry that still states `provider` or
    `model_name` is refused.
    """

    ref: ExactDefinitionRef
    settings: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def exact_model_ref(self) -> DeepAgentModelBinding:
        if self.ref.kind.value != "model":
            raise ValueError("a Deep Agents model binding requires an exact model ref")
        return self


class CapabilityComponentBinding(_File):
    """The exact component a deployment serves for one catalog capability revision.

    ``pinned`` names a capability-pin entry (MCP ``server_id``, Skill ``skill_name`` or tool
    ``tool_name``) the bootstrap resolves into the inline component.
    """

    catalog_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    kind: Literal["mcp_server", "skill", "tool"]
    pinned: str | None = Field(default=None, min_length=1)
    mcp_server: DeepAgentMCPServerComponent | None = None
    skill: DeepAgentSkillComponent | None = None
    tool: DeepAgentToolComponent | None = None

    @model_validator(mode="after")
    def one_component(self) -> CapabilityComponentBinding:
        inline = {
            "mcp_server": self.mcp_server,
            "skill": self.skill,
            "tool": self.tool,
        }
        present = [name for name, value in inline.items() if value is not None]
        if self.pinned is None and present != [self.kind]:
            raise ValueError(f"a {self.kind} binding needs exactly its inline component")
        if self.pinned is not None and present and present != [self.kind]:
            raise ValueError(f"a pinned {self.kind} binding cannot carry another component")
        return self

    @property
    def resolved(self) -> bool:
        return getattr(self, self.kind) is not None


class AsyncSubagentGraphBinding(_File):
    """A hosted child graph the deployment serves, named by the manifest subagent's name.

    Part of ``mc.manifest_launch_bindings`` (``deep_agents_async_graphs``): the operator
    reviews which Agent Server graph a ``kind: async`` profile may spawn, with the exact
    graph identity the parent verifies before every submission (REQ-CP-DA-019).
    ``dependency_classes`` defaults to the class the worker spawns with
    (``required_blocking``: the parent's completion waits for the child), so a binding that
    names nothing else matches the deployment; the spawn path picks the strongest class the
    contract allows when the worker's default is not among them.
    """

    graph_id: str = Field(min_length=1)
    graph_revision: str = Field(min_length=1, max_length=256)
    graph_binding_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    agent_protocol_url: str = Field(min_length=1)
    deployment_credential_ref: str | None = Field(
        default=None, pattern=r"^(environment|vault|aws-secrets-manager):[A-Za-z0-9_./:-]+$"
    )
    objective_schema_ref: str = Field(min_length=1)
    result_schema_ref: str = Field(min_length=1)
    result_admission_policy_ref: str = Field(min_length=1)
    default_budget_limits: dict[str, int] = Field(min_length=1)
    timeout_seconds: int = Field(default=3_600, ge=1, le=604_800)
    dependency_classes: frozenset[AsyncSubagentDependencyClass] = frozenset(
        {AsyncSubagentDependencyClass.REQUIRED_BLOCKING}
    )
    cancellation_propagation: Literal["required", "best_effort", "none"] = "required"
    late_result_policy: Literal["quarantine", "record_only", "eligible_if_parent_open"] = (
        "quarantine"
    )
    fallback_policy: Literal["fail_parent", "degrade", "continue_without_result"] = "degrade"
    # OVE-184: `sealed_child` names the generic graph that materializes the child's own sealed
    # binding per run (the profile's prompt, model, tools, Skills and MCP servers reach the
    # child; `graph_binding_digest` is then the served host template's). `exact` keeps a graph
    # whose one binding the server hosts (the technical child); the profile's configuration
    # does not reach it. Excluded while `exact`, so earlier bindings files read unchanged.
    binding_mode: Literal["exact", "sealed_child"] = Field(
        default="exact", exclude_if=lambda value: value == "exact"
    )

    @property
    def credential_secret_ref(self) -> SecretRef | None:
        """The launch secret reference the parent needs to mint its scope claim."""

        if self.deployment_credential_ref is None:
            return None
        provider, _, key = self.deployment_credential_ref.partition(":")
        return SecretRef(provider=provider, key=key)


class ManifestLaunchBindings(_File):
    """``mc.manifest_launch_bindings.v1``, or ``.v2`` = v1 plus the ``providers`` section of
    the local provider lanes (``provider_launch.ProviderLanes``). A v1 file reads unchanged."""

    schema_version: Literal["mc.manifest_launch_bindings.v1", "mc.manifest_launch_bindings.v2"] = (
        LAUNCH_BINDINGS_SCHEMA
    )
    deep_agents: DeepAgentScaffold | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    # OC-R6: references to the Model Catalog (`deployments/<app>/models.toml`), keyed by profile.
    model_profiles: dict[str, DeepAgentModelBinding] = Field(default_factory=dict)
    sandbox_profiles: dict[str, DeepAgentSandboxComponent] = Field(default_factory=dict)
    capabilities: dict[str, CapabilityComponentBinding] = Field(default_factory=dict)
    # P1-S3: the served Agent Server graphs a `kind: async` subagent profile may spawn, keyed
    # by the profile's name. Absent files read unchanged.
    deep_agents_async_graphs: dict[str, AsyncSubagentGraphBinding] = Field(
        default_factory=dict, exclude_if=lambda value: not value
    )
    providers: ProviderLanes | None = Field(default=None, exclude_if=lambda value: value is None)
    knowledge_workspace_repository: CursorRepository | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def providers_need_v2(self) -> ManifestLaunchBindings:
        if self.schema_version == LAUNCH_BINDINGS_SCHEMA and self.deep_agents is None:
            raise ValueError("v1 manifest launch bindings require the Deep Agents scaffold")
        if self.providers is not None and self.schema_version != LAUNCH_BINDINGS_SCHEMA_V2:
            raise ValueError(
                f"a providers section needs schema_version {LAUNCH_BINDINGS_SCHEMA_V2}"
            )
        return self

    @classmethod
    def load(cls, path: Path) -> ManifestLaunchBindings:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"manifest launch bindings are unavailable: {path}") from error
        return cls.model_validate(payload)


@dataclass(frozen=True)
class ServedModel:
    """The vendor and model id a served model definition serves (OC-R6)."""

    vendor: str
    model_id: str


@dataclass(frozen=True)
class ServedComponents:
    """Digests of the components the executing workers can materialize.

    Pinned components (capability pins) plus those a deployment registers beside them;
    keyed like ``ExactComponentRegistry`` (Skills by bundle digest).
    """

    models: frozenset[str] = frozenset()
    # OC-R6: what each served model definition serves, by digest: the pin file's
    # `models[].provider` and `model_id`, and each registered extra's declared identity.
    # Enforced against the Model Catalog row at composition (`MODEL_PIN_VENDOR_MISMATCH`,
    # `MODEL_PIN_MODEL_MISMATCH`); a served digest with no identity is refused
    # (`MODEL_PIN_UNDECLARED`) unless the composition is explicitly a test or qualification one.
    model_identities: Mapping[str, ServedModel] = field(default_factory=dict)
    # Explicit, never inferred: a test or qualification composition whose deterministic models
    # declare no identity (`DeploymentCapabilityComponents.qualification`).
    qualification: bool = False
    sandboxes: frozenset[str] = frozenset()
    checkpointers: frozenset[str] = frozenset()
    stores: frozenset[str] = frozenset()
    mcp_servers: frozenset[str] = frozenset()
    skills: frozenset[str] = frozenset()
    tools: frozenset[str] = frozenset()


# --- Resolution (pure) ----------------------------------------------------------------------


@dataclass(frozen=True)
class LaunchResolution:
    """The resolution seam as the launch author uses it (ADR-0063, OC-R1), composed by bootstrap.

    ``runtime`` resolves a node over the lane, application and model registries. ``models`` is
    the same Model Catalog, which the author reads a requested profile's vendor from (the
    selection carries a whole model pin). ``applications`` is the same Application Registry,
    which the author reads an undeclared mission's Data Class ceiling from (OC-R4).
    ``templates`` is the template step of the lane that sealed the node binding
    (`LaneTemplateBinder`): it seals the template's `lane_binding` for the author's template
    coordinates and returns the request facts it derived (OC-R2).
    """

    runtime: RuntimeResolver
    models: ModelCatalog
    applications: ApplicationRegistry
    templates: LaneTemplateBinder


@dataclass(frozen=True)
class DeepAgentsNodeLaunch:
    """One Deep Agents node role, resolved through the seam."""

    runtime: ResolvedRuntime
    # The model vendor's credential reference, resolved by the operation before cognition.
    model_secret: SecretRef
    network: ResolvedNetworkPolicy | None = None


@dataclass(frozen=True)
class AdmittedLaunch:
    """What the admitted configuration fixes about the templates of one run."""

    request_scope: str
    run_id: str
    configuration_digest: str
    blueprint: StageGraphBlueprint | GoalDirectedBlueprint
    workspace_ref: ExactDefinitionRef
    workspace_contract: WorkflowWorkspaceContract
    authority: AuthorityCeiling
    operation_binding_refs: frozenset[ExactDefinitionRef]
    compiled_at: datetime

    @classmethod
    def from_configuration(
        cls, request_scope: str, run_id: str, configuration: EffectiveRunConfiguration
    ) -> AdmittedLaunch:
        workspace_ref = next(
            (
                ref
                for ref in configuration.source_refs
                if ref.kind == DefinitionKind.WORKSPACE_TEMPLATE
            ),
            None,
        )
        if workspace_ref is None:
            raise ValueError("the admitted configuration names no workspace template")
        return cls(
            request_scope=request_scope,
            run_id=run_id,
            configuration_digest=configuration.digest,
            blueprint=configuration.selected_blueprint,
            workspace_ref=workspace_ref,
            workspace_contract=configuration.workflow_workspace_contract,
            authority=configuration.effective_authority,
            operation_binding_refs=configuration.runtime_profile.operation_binding_refs,
            compiled_at=configuration.context.compiled_at,
        )


def _authored_value(environment: Any, field: str) -> Any:
    value: Any = environment.authored() if environment is not None else {}
    for part in field.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _source(
    definition: MissionDefinition,
    path: Sequence[DefinitionNode],
    field: str,
    *,
    verifier: bool = False,
) -> str:
    """The manifest pointer that set ``field`` of the node's effective environment."""

    suffix = "/environment/" + field.replace(".", "/")
    node = path[-1]
    if (
        verifier
        and node.verifier_environment is not None
        and _authored_value(node.verifier_environment, field)
        != _authored_value(node.environment, field)
    ):
        return f"{node.pointer}/verifier{suffix}"
    for item in reversed(path):
        if any(
            origin == "overlay" and (key == field or key.startswith(field + "."))
            for key, origin in item.field_provenance.items()
        ):
            return f"{item.pointer}{suffix}"
    return f"{definition.manifest_pointer}{suffix}"


def _finite_number(value: object) -> Decimal | None:
    """A manifest number; the committed definition stores decimals as JSON strings."""

    if isinstance(value, bool) or not isinstance(value, int | float | Decimal | str):
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _flatten(settings: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in settings.items():
        name = f"{prefix}{key}"
        if isinstance(value, Mapping):
            flat.update(_flatten(value, f"{name}."))
        else:
            flat[name] = value
    return flat


class ManifestLaunchResolver:
    """Author the frozen operation templates of a manifest run (pure, no I/O).

    A Deep Agents node role resolves through the resolution seam (`deep_agents_node`). A
    provider or Cursor node role is admitted through the seam (`RuntimeResolver.admit`: lane,
    application, declared vendor route, Data Class, family; OC-R3) and still resolves against
    its section of the deployment bindings here, because those lanes compile describe-only
    until the provider sweep (OC-D199).
    """

    def __init__(
        self,
        bindings: ManifestLaunchBindings,
        *,
        provider_secret_env: Mapping[str, str],
        network_hosts: NetworkHosts | None = None,
        hosted_digest: Any = None,
        resolution: LaunchResolution | None = None,
        projectors: HostProjectors | None = None,
    ) -> None:
        unresolved = sorted(
            name for name, item in bindings.capabilities.items() if not item.resolved
        )
        if unresolved:
            raise ValueError(f"pinned capability bindings are unresolved: {unresolved}")
        self._hosted_digest = hosted_digest
        self._bindings = bindings
        self._secrets = dict(provider_secret_env)
        # The installation's own hosts a network policy may need (none configured: a run that
        # requires one is refused at its network pointer).
        self._network_hosts = network_hosts or NetworkHosts()
        # The resolution seam the Deep Agents node roles go through (ADR-0063); bootstrap
        # composes it with the lane package that owns the deployment's Deep Agents facts.
        self._resolution = resolution
        # The Host Projection port the provider and Cursor templates pin their projection
        # digests through (OC-R3; bootstrap composes it from the lane packages).
        self._projectors = projectors

    def _projection_port(self) -> HostProjectors:
        if self._projectors is None:
            raise ValueError("no Host Projection port is composed for the launch author")
        return self._projectors

    def _deep_scaffold(self, pointer: str = "/deep_agents") -> DeepAgentScaffold:
        scaffold = self._bindings.deep_agents
        if scaffold is None:
            raise ManifestLaunchBindingError(pointer, "selected Deep Agents lane has no scaffold")
        return scaffold

    @property
    def bindings(self) -> ManifestLaunchBindings:
        return self._bindings

    # -- one Deep Agents node role, through the resolution seam (ADR-0063) ------------------

    def deep_agents_node(
        self,
        definition: MissionDefinition,
        path: Sequence[DefinitionNode],
        *,
        verifier: bool,
        admitted: AdmittedLaunch,
        rows: Mapping[str, ResolvedCapability] | None = None,
        kit_egress: Mapping[str, Sequence[str]] | None = None,
    ) -> DeepAgentsNodeLaunch:
        """One Deep Agents node role: the neutral selection, then `RuntimeResolver.resolve`.

        The author builds the node's `mc.agent_configuration.v2` from its effective capability
        selection (skills, MCP servers with their tool subsets, tools, hook scripts, context
        bundles, subagent profiles with their catalog bodies and seeds, the sandbox profile)
        and its model profile, and resolves it on the ``deep_agents`` lane. The lane's compile
        maps every pin to its exact deployment component; a refusal becomes the pointed
        :class:`ManifestLaunchBindingError` it always was.
        """

        node = path[-1]
        environment = (
            node.verifier_environment
            if verifier and node.verifier_environment is not None
            else node.environment
        )
        lane_pointer = _source(definition, path, "lane", verifier=verifier)
        lane = environment.lane or node.lane
        if str(lane) != DEEP_AGENTS_LANE:
            raise ManifestLaunchBindingError(
                lane_pointer,
                f"lane {lane} has no production launch author; manifest runs launch on "
                f"{DEEP_AGENTS_LANE} only",
            )
        self._deep_scaffold(lane_pointer)
        resolution = self._resolution
        if resolution is None:
            raise ManifestLaunchBindingError(
                lane_pointer,
                "no resolution seam is composed for the deep_agents lane (bootstrap registers "
                "the lane package, the applications and the model catalog)",
            )
        node_pointer = lane_pointer.rsplit("/lane", 1)[0]
        model_pointer = _source(definition, path, "model.profile", verifier=verifier)
        model = self._requested_model(
            definition, path, environment, verifier=verifier, models=resolution.models
        )
        sandbox_pointer = _source(definition, path, "sandbox.profile", verifier=verifier)
        sandbox = environment.sandbox
        if sandbox is None or sandbox.profile is None:
            raise ManifestLaunchBindingError(sandbox_pointer, "no sandbox profile is bound")
        selected = self._configuration_items(
            definition,
            path,
            verifier=verifier,
            operation_binding_refs=admitted.operation_binding_refs,
            rows=rows,
        )
        selected.append(
            (
                _selected_profile_item(
                    "sandbox_profile",
                    str(sandbox.profile),
                    {
                        item_config.PROFILE_NAME: str(sandbox.profile),
                        "egress": list(sandbox.egress or ()),
                    },
                ),
                sandbox_pointer,
            )
        )
        instruction = _stage_authored_instruction(node) if len(path) > 1 else None
        data_class, data_class_source = launch_data_class(
            definition,
            DEEP_AGENTS_LANE,
            pointer=lane_pointer,
            ceiling=_application_ceiling(resolution.applications, definition.application),
        )
        agent = AgentConfiguration.create(
            lane_profile=DEEP_AGENTS_LANE,
            node_ref=f"{node.pointer}/verifier" if verifier else node.pointer,
            instructions_ref=sha256_digest(instruction.content if instruction else ""),
            model=model,
            items=[item for item, _ in selected],
            budgets=_jsonable(dict(admitted.authority.budgets.dimensions)),
            data_class=data_class,
            data_class_source=data_class_source,
        )
        by_name = {item.name: pointer for item, pointer in selected}
        options = (getattr(environment, "provider_options", None) or {}).get(DEEP_AGENTS_LANE)
        result = resolution.runtime.resolve(
            RuntimeSelection(
                lane_profile=DEEP_AGENTS_LANE,
                model_profile=model.profile,
                family=(
                    "StageGraph"
                    if isinstance(admitted.blueprint, StageGraphBlueprint)
                    else "GoalDirected"
                ),
                node_role="verifier" if verifier else "executor",
                application_id=definition.application,
                agent=agent,
                lane_options=dict(options or {}),
            )
        )
        if isinstance(result, ResolutionRefused):
            raise ManifestLaunchBindingError(
                _manifest_pointer(
                    result.pointer,
                    items={
                        f"/items/{index}": by_name[item.name]
                        for index, item in enumerate(agent.items)
                    },
                    lane=lane_pointer,
                    model=model_pointer,
                    node=node_pointer,
                    mission=definition.manifest_pointer,
                ),
                result.reason,
            )
        vendor = result.agent.model.vendor
        secret_env = self._secrets.get(vendor)
        if not secret_env:
            raise ManifestLaunchBindingError(
                model_pointer,
                f"no credential reference is declared for model provider {vendor} "
                "(MANIFEST_PROVIDER_SECRET_ENV)",
            )
        selections = (
            node.verifier_selections
            if verifier and node.verifier_selections is not None
            else node.selections
        )
        network = self._network(
            selections or EnvironmentSelections(),
            lambda field: _selection_source(definition, path, field, verifier=verifier),
            kit_egress,
        )
        if network is not None and network.mode == "allow_all":
            raise ManifestLaunchBindingError(
                _selection_source(definition, path, "network", verifier=verifier),
                "the Deep Agents operation grant supports finite network allowlists only",
            )
        if network is not None and any(host.startswith("*.") for host in network.hosts):
            raise ManifestLaunchBindingError(
                _selection_source(definition, path, "network", verifier=verifier) + "/allow",
                "the Deep Agents worker-tool operation grant supports exact network hosts; "
                "wildcard hosts are not enforceable by agent_browser_page",
            )
        return DeepAgentsNodeLaunch(
            runtime=result,
            model_secret=SecretRef(provider="environment", key=secret_env),
            network=network,
        )

    def _requested_model(
        self,
        definition: MissionDefinition,
        path: Sequence[DefinitionNode],
        environment: Any,
        *,
        verifier: bool,
        models: ModelCatalog,
    ) -> AgentModelPin:
        """The node's model profile as the catalog pins it, with its mapped settings.

        A catalog-pinned model (`profile: {pin: ...}`) must be bound at exactly its pinned
        revision: `models.toml` rows carry no catalog digest, so the author checks the pin
        against the Deep Agents model binding's exact ref.
        """

        pointer = _source(definition, path, "model.profile", verifier=verifier)
        selection = environment.model
        if selection is None or selection.profile is None:
            raise ManifestLaunchBindingError(pointer, "no model profile is bound")
        profile = selection.profile
        if isinstance(profile, str):
            name = profile
        else:
            capability = next(
                (
                    item
                    for item in definition.capabilities
                    if item.role == "model" and item.pointer.startswith(pointer)
                ),
                None,
            )
            pin = (capability.resolved or capability.pin) if capability is not None else None
            if pin is None or pin.digest is None:
                raise ManifestLaunchBindingError(
                    pointer, "the model capability is not resolved to an exact catalog revision"
                )
            name = pin.capability_id
            component = self._bindings.model_profiles.get(name)
            if component is not None and component.ref.digest != pin.digest:
                raise ManifestLaunchBindingError(
                    pointer,
                    f"model {pin.capability_id}@{pin.version} is pinned at {pin.digest} but the "
                    f"deployment binds {component.ref.digest}",
                )
        try:
            catalogued = models.get(name)
        except KeyError:
            raise ManifestLaunchBindingError(
                pointer,
                f"model profile {name} is not in the model catalog (deployments/"
                f"{definition.application}/models.toml); `missionctl model list` shows the "
                "catalog and each lane's route",
            ) from None
        settings, _, _ = self._model_settings(definition, path, environment, verifier=verifier)
        return catalogued.pin(settings)

    def _configuration_items(
        self,
        definition: MissionDefinition,
        path: Sequence[DefinitionNode],
        *,
        verifier: bool,
        operation_binding_refs: frozenset[ExactDefinitionRef],
        rows: Mapping[str, ResolvedCapability] | None,
    ) -> list[tuple[ConfigurationItem, str]]:
        """The node role's selection as neutral items, each with the pointer that selected it.

        The author checks what admission fixed (an exact catalog revision the admitted runtime
        profile pins) and reads each subagent profile's catalog body; which component serves a
        pin is the lane's question. Every item is ``required``: an unbound selection refuses
        the launch (the manifest has no optional selections yet, and plugin members marked
        ``optional`` are not distinguished either).
        """

        node = path[-1]
        environment = (
            node.verifier_environment
            if verifier and node.verifier_environment is not None
            else node.environment
        )
        contexts = environment.workspace.context if environment.workspace is not None else None
        for index, entry in enumerate(contexts or ()):
            if isinstance(entry, str):
                raise ManifestLaunchBindingError(
                    f"{_source(definition, path, 'workspace.context', verifier=verifier)}/{index}",
                    f"context profile {entry} has no deployment binding",
                )
        pinned = {(ref.logical_id, ref.digest) for ref in operation_binding_refs}
        available: Mapping[str, ResolvedCapability] = rows or {}
        names: set[str] = set()
        selected: list[tuple[ConfigurationItem, str]] = []
        children = 0
        capabilities = _selected_capabilities(definition, path, verifier=verifier)
        # A node's own plugin rows: compile expanded each into its members, which are the items
        # (each names the plugin that expanded it). A seed plugin's members carry their owner.
        plugins = {
            item.pointer: item
            for item in capabilities
            if item.role == "plugin" and not _plugin_member(item) and seed_owner(item) is None
        }
        for pointer, plugin in plugins.items():
            if not any(item.pointer.startswith(f"{pointer}/members/") for item in capabilities):
                pin = plugin.resolved or plugin.pin
                label = f"{pin.capability_id}@{pin.version}" if pin is not None else pointer
                raise ManifestLaunchBindingError(
                    pointer,
                    f"plugin {label} expanded to no members; mc.agent_configuration.v2 carries a "
                    "plugin only as its members, so nothing of it can be configured",
                )
        for item in capabilities:
            owner = seed_owner(item)
            if item.role == "plugin":
                continue  # expanded by compile: its members are the items (and carry the owner)
            pin = item.resolved or item.pin
            if verifier and pin is not None and pin.capability_id in PRODUCER_TOOL_CAPABILITIES:
                # W1 D27 (ADR-0058): the independent verifier never gets the producer's
                # register/apply/submit tools. Inherited from the node environment they are
                # left out; selected in the verifier's own environment they refuse the launch.
                if item.pointer.startswith(f"{node.pointer}/verifier/"):
                    raise ManifestLaunchBindingError(
                        item.pointer,
                        f"{pin.capability_id} is a producer tool; an independent verifier may "
                        "not register, apply or submit for the promises it evaluates",
                    )
                continue
            config: dict[str, Any]
            if item.role == "agent" and owner is None and not _plugin_member(item):
                profile = _subagent_profile(item, pinned, available)
                overlay = item.attributes.get("overlay")
                config = {
                    item_config.ROLE: item.role,
                    item_config.PROFILE: profile.model_dump(mode="json"),
                    item_config.OVERLAY: (
                        _jsonable(dict(overlay)) if isinstance(overlay, Mapping) else {}
                    ),
                    item_config.POSITION: children,
                }
                children += 1
            else:
                if pin is None or pin.digest is None:
                    raise ManifestLaunchBindingError(
                        item.pointer,
                        "the subagent seed is not resolved to an exact catalog revision"
                        if owner is not None
                        else "the capability is not resolved to an exact catalog revision",
                    )
                member_role = item.attributes.get("plugin_member_role")
                deferred = owner is not None and member_role not in (None, "skill", "mcp_server")
                if not deferred and (pin.capability_id, pin.digest) not in pinned:
                    raise ManifestLaunchBindingError(
                        item.pointer,
                        f"{item.role} {pin.capability_id}@{pin.version} is not pinned by the "
                        "admitted runtime profile",
                    )
                config = {item_config.ROLE: item.role, **_jsonable(dict(item.attributes))}
                if owner is not None:
                    # The child this capability seeds (the discriminator's attribute, named
                    # neutrally for the lane).
                    config[item_config.SEED_OF] = owner
                expanded_by = next(
                    (
                        row
                        for row_pointer, row in plugins.items()
                        if item.pointer.startswith(f"{row_pointer}/members/")
                    ),
                    None,
                )
                if expanded_by is not None:
                    row_pin = expanded_by.resolved or expanded_by.pin
                    assert row_pin is not None
                    config[item_config.PLUGIN] = f"{row_pin.capability_id}@{row_pin.version}"
            assert pin is not None and pin.digest is not None
            kind = _item_kind(item)
            if kind is None:
                raise ManifestLaunchBindingError(
                    item.pointer,
                    f"{item.role} {pin.capability_id}@{pin.version} is a {item.kind} capability; "
                    "mc.agent_configuration.v2 has no item kind for it, so no lane can be "
                    "configured with it",
                )
            base = item.alias or pin.capability_id
            name = f"{owner}/{base}" if owner is not None else base
            unique, suffix = name, 2
            while unique in names:
                unique, suffix = f"{name}~{suffix}", suffix + 1
            names.add(unique)
            selected.append(
                (
                    ConfigurationItem.create(
                        kind=kind,
                        name=unique,
                        pin=f"{pin.capability_id}@{pin.version}#{pin.digest}",
                        required=True,
                        config=config,
                    ),
                    item.pointer,
                )
            )
        return selected

    def _model_settings(
        self,
        definition: MissionDefinition,
        path: Sequence[DefinitionNode],
        environment: Any,
        *,
        verifier: bool,
    ) -> tuple[dict[str, object], Any, Any]:
        authored = environment.model.settings or {}
        result: dict[str, object] = {}
        for name, value in sorted(_flatten(authored).items()):
            pointer = _source(definition, path, f"model.settings.{name}", verifier=verifier)
            target = _MODEL_SETTINGS.get(name)
            if target is None:
                raise ManifestLaunchBindingError(
                    pointer, f"model setting {name} has no provider mapping"
                )
            if target == "temperature":
                number = _finite_number(value)
                if number is None:
                    raise ManifestLaunchBindingError(pointer, "temperature must be a number")
                result[target] = float(number)
            elif target == "reasoning_effort" and value not in _REASONING:
                raise ManifestLaunchBindingError(
                    pointer, f"reasoning effort must be one of {', '.join(_REASONING)}"
                )
            elif target == "verbosity" and value not in _VERBOSITY:
                raise ManifestLaunchBindingError(
                    pointer, f"verbosity must be one of {', '.join(_VERBOSITY)}"
                )
            elif target == "max_completion_tokens" and (
                not isinstance(value, int) or isinstance(value, bool) or value < 1
            ):
                raise ManifestLaunchBindingError(pointer, "max_output_tokens must be positive")
            else:
                result[target] = value
        return result, result.get("reasoning_effort"), result.get("verbosity")

    # -- one provider node role (claude_agent_sdk, codex) ---------------------------------------

    def provider_node(
        self,
        definition: MissionDefinition,
        path: Sequence[DefinitionNode],
        *,
        verifier: bool,
        operation_binding_refs: frozenset[ExactDefinitionRef],
        rows: Mapping[str, ResolvedCapability] | None = None,
        kit_egress: Mapping[str, Sequence[str]] | None = None,
        family: Family,
    ) -> ProviderNodeLaunch:
        """Resolve one claude/codex node role to its sealed-binding inputs, or fail pointed.

        Every value comes from the committed definition (the v2 selections compile admitted)
        and the deployment's ``providers`` section; nothing is defaulted from another lane.
        """

        node = path[-1]
        environment = (
            node.verifier_environment
            if verifier and node.verifier_environment is not None
            else node.environment
        )
        selections = (
            node.verifier_selections
            if verifier and node.verifier_selections is not None
            else node.selections
        )
        profile = _lane_of(path, verifier=verifier)

        def source(field: str) -> str:
            return _selection_source(definition, path, field, verifier=verifier)

        lane_pointer = source("lane")
        if profile in HOSTED_PROVIDER_PROFILES:
            raise ManifestLaunchBindingError(
                lane_pointer,
                f"lane {profile} compiles structurally but its launch is refused: the "
                "provider-hosted lifecycle is evidence-blocked (MP-18/19, "
                f"docs/qualification/lanes/{profile}/REVALIDATION-2026-10-09.md)",
            )
        providers = self._bindings.providers
        lane = providers.lane(profile) if providers is not None else None
        if lane is None:
            raise ManifestLaunchBindingError(
                lane_pointer,
                f"lane profile {profile} has no deployment binding "
                f"({LAUNCH_BINDINGS_SCHEMA_V2} providers.{profile})",
            )
        if selections is None:
            raise ManifestLaunchBindingError(
                lane_pointer,
                f"lane {profile} needs the mission/v2 environment selections "
                "(auth, execution_environment, workspace policy); the definition carries none",
            )
        model, options = self._provider_model(
            definition, path, environment, lane, profile, verifier=verifier
        )
        if selections.auth is None:
            raise ManifestLaunchBindingError(source("auth"), "no auth profile is selected")
        auth = lane.auth_profiles.get(selections.auth.profile)
        if auth is None:
            raise ManifestLaunchBindingError(
                source("auth.profile"),
                f"auth profile {selections.auth.profile} has no deployment binding "
                f"(providers.{profile}.auth_profiles)",
            )
        placement = selections.execution_environment
        if placement is None:
            raise ManifestLaunchBindingError(
                source("execution_environment"), "no execution_environment is selected"
            )
        if profile in HOSTED_API_PROFILES:
            if placement.kind != "provider_hosted":
                raise ManifestLaunchBindingError(
                    source("execution_environment.kind"),
                    "hosted API needs provider_hosted placement",
                )
            host = next(
                (
                    item
                    for item in lane.host_profiles.values()
                    if item.environment_ref == placement.environment_ref
                    and item.provider == placement.provider
                ),
                None,
            )
        elif placement.kind != "local_workspace" or placement.profile is None:
            raise ManifestLaunchBindingError(
                source("execution_environment.profile"),
                f"lane {profile} runs on a worker and needs a local_workspace host profile",
            )
        else:
            host = lane.host_profiles.get(placement.profile)
        if host is None:
            raise ManifestLaunchBindingError(
                source("execution_environment.profile"),
                f"host profile {placement.profile} has no deployment binding "
                f"(providers.{profile}.host_profiles)",
            )
        try:
            policy = admit_policy(profile, policy_pin(selections.workspace_policy))
        except WorkspaceError as error:
            raise ManifestLaunchBindingError(source("workspace.policy"), error.message) from error
        repo = environment.workspace.repo if environment.workspace is not None else None
        if repo is None:
            raise ManifestLaunchBindingError(
                source("workspace.repo"), f"lane {profile} requires workspace.repo"
            )
        repo_commit = None
        if profile in HOSTED_API_PROFILES:
            repo_commit = lane.repository_commits.get(f"{repo.url or repo.path}#{repo.ref}")
            if not repo_commit:
                raise ManifestLaunchBindingError(
                    source("workspace.repo"),
                    "hosted code launch needs an explicitly reviewed repository_commits SHA",
                )
        bound_environment = _populated_environment(
            host, selections, source, self._network(selections, source, kit_egress)
        )
        describe = declared_matrix(profile)
        requires = selections.requires or RequiredFeatures()
        refused = [
            *admit_requirements(
                describe,
                RequirementSet(controls=requires.controls, observation=requires.observation),
            ),
            *admit_gate_coverage(
                describe,
                GateCoverageRequirement(
                    approvals=requires.approvals, all_writes_gated=requires.all_writes_gated
                ),
            ),
        ]
        if refused:
            raise ManifestLaunchBindingError(
                source("requires"), "; ".join(item.message for item in refused)
            )
        self._admit_lane(
            definition,
            path,
            verifier=verifier,
            profile=profile,
            family=family,
            vendor=model_vendor(profile),
        )
        requirements = WorkflowRequirements(
            controls=requires.controls,
            approvals=requires.approvals,
            observation=requires.observation,
            describe_digest=describe.digest,
        )
        pins, ordered = self._provider_capabilities(
            definition, path, verifier=verifier, refs=operation_binding_refs, rows=rows
        )
        continuation = selections.continuation
        policy_digest = sha256_digest(
            {
                "lane_profile": profile,
                "requirements": stable_json_dump(requirements),
                "workspace_policy": stable_json_dump(policy),
                "continuation": stable_json_dump(continuation) if continuation else None,
                "side_effects": [item.value for item in environment.side_effects or ()],
                "egress": (
                    list(environment.sandbox.egress)
                    if environment.sandbox is not None and environment.sandbox.egress is not None
                    else None
                ),
                "commands_allowed": (
                    [item.value for item in definition.policies.commands_allowed]
                    if definition.policies.commands_allowed is not None
                    else None
                ),
            }
        )
        return ProviderNodeLaunch(
            profile=profile,
            lane=lane,
            lane_pointer=lane_pointer,
            model=model,
            rows=ordered,
            binding_fields={
                "lane_profile": profile,
                "model": model,
                "auth": auth,
                "environment": bound_environment,
                "workspace_policy": policy,
                "repo_url": repo.url or repo.path,
                "repo_ref": repo.ref,
                **({"repo_commit": repo_commit} if repo_commit else {}),
                "requirements": requirements,
                "policy_digest": policy_digest,
                "pins": {**lane.pins, **pins},
                "provider_options": options,
                "budgets": _narrowed_budgets(lane.budgets, environment, continuation),
                "materialization": selections.materialization,
            },
        )

    def _admit_lane(
        self,
        definition: MissionDefinition,
        path: Sequence[DefinitionNode],
        *,
        verifier: bool,
        profile: str,
        family: Family,
        vendor: Vendor | None,
    ) -> None:
        """The resolution seam's admission of a node whose lane compiles describe-only (OC-R3):
        the lane and application lookups, the declared vendor's model route, the Data Class
        against the lane's policy and the application's ceiling, and the family
        (`RuntimeResolver.admit`). A refusal is pointed into the manifest like any other."""

        lane_pointer = _source(definition, path, "lane", verifier=verifier)
        resolution = self._resolution
        if resolution is None:
            raise ManifestLaunchBindingError(
                lane_pointer,
                f"no resolution seam is composed for the {profile} lane (bootstrap registers "
                "the lane packages, the applications and the model catalog)",
            )
        data_class, _ = launch_data_class(
            definition,
            profile,
            pointer=lane_pointer,
            ceiling=_application_ceiling(resolution.applications, definition.application),
        )
        refused = resolution.runtime.admit(
            LaneAdmission(
                lane_profile=profile,
                application_id=definition.application,
                family=family,
                data_class=data_class,
                vendor=vendor,
            )
        )
        if refused is not None:
            raise ManifestLaunchBindingError(
                _manifest_pointer(
                    refused.pointer,
                    items={},
                    lane=lane_pointer,
                    model=_source(definition, path, "model.profile", verifier=verifier),
                    node=lane_pointer.rsplit("/lane", 1)[0],
                    mission=definition.manifest_pointer,
                ),
                refused.reason,
            )

    def _network(
        self,
        selections: EnvironmentSelections,
        source: Any,
        kit_egress: Mapping[str, Sequence[str]] | None,
    ) -> ResolvedNetworkPolicy | None:
        """The node role's declared network policy resolved for its binding (MO-15).

        No worker lane reaches its model through the Model Gateway yet (a Sandbox Host
        placement does, HL-03/HL-15), so only the Signal Ingress host can be required here."""

        if selections.network is None:
            return None
        kit = selections.kit
        try:
            return resolve_network_policy(
                selections.network,
                kit=kit,
                kit_egress=(kit_egress or {}).get(kit.pin) if kit is not None else None,
                hosts=self._network_hosts,
                signal_ingress=requires_signal_ingress(selections),
            )
        except NetworkPolicyUnresolvable as error:
            raise ManifestLaunchBindingError(
                source(error.field), f"{error.code}: {error.message}"
            ) from error

    def _provider_model(
        self,
        definition: MissionDefinition,
        path: Sequence[DefinitionNode],
        environment: Any,
        lane: ProviderLaneBinding,
        profile: str,
        *,
        verifier: bool,
    ) -> tuple[
        ModelPin,
        ClaudeSdkOptions | CodexAppServerOptions | ClaudeManagedOptions | CodexAgentsOptions,
    ]:
        pointer = _source(definition, path, "model.profile", verifier=verifier)
        selection = environment.model
        if selection is None or selection.profile is None:
            raise ManifestLaunchBindingError(pointer, "no model profile is bound")
        if not isinstance(selection.profile, str):
            raise ManifestLaunchBindingError(
                pointer,
                f"a catalog model capability has no {profile} lane binding; select a model "
                f"profile bound in providers.{profile}.model_profiles",
            )
        model = lane.model_profiles.get(selection.profile)
        if model is None:
            raise ManifestLaunchBindingError(
                pointer,
                f"model profile {selection.profile} has no deployment model binding for lane "
                f"{profile} (providers.{profile}.model_profiles)",
            )
        options = lane.provider_options
        for name, value in sorted(_flatten(selection.settings or {}).items()):
            setting = _source(definition, path, f"model.settings.{name}", verifier=verifier)
            if (
                isinstance(options, CodexAppServerOptions)
                and name == "reasoning.effort"
                and value in _REASONING
            ):
                options = CodexAppServerOptions.model_validate(
                    {**options.model_dump(mode="python"), "reasoning_effort": value}
                )
                continue
            raise ManifestLaunchBindingError(
                setting, f"model setting {name} has no {profile} provider option mapping"
            )
        return model, options

    def _provider_capabilities(
        self,
        definition: MissionDefinition,
        path: Sequence[DefinitionNode],
        *,
        verifier: bool,
        refs: frozenset[ExactDefinitionRef],
        rows: Mapping[str, ResolvedCapability] | None,
    ) -> tuple[dict[str, str], tuple[ResolvedCapability, ...]]:
        """The node's projected capabilities: binding pin entries and rows in render order."""

        node = path[-1]
        environment = (
            node.verifier_environment
            if verifier and node.verifier_environment is not None
            else node.environment
        )
        contexts = environment.workspace.context if environment.workspace is not None else None
        for index, entry in enumerate(contexts or ()):
            if isinstance(entry, str):
                pointer = _source(definition, path, "workspace.context", verifier=verifier)
                raise ManifestLaunchBindingError(
                    f"{pointer}/{index}", f"context profile {entry} has no deployment binding"
                )
        selected = _selected_capabilities(definition, path, verifier=verifier)
        pinned = {(ref.logical_id, ref.digest) for ref in refs}
        pins: dict[str, str] = {}
        available: Mapping[str, ResolvedCapability] = rows or {}
        for item in selected:
            if _plugin_member(item):
                continue  # the plugin's row expands it at render, as on the Cursor lanes
            pin = item.resolved or item.pin
            if pin is None or pin.digest is None:
                raise ManifestLaunchBindingError(
                    item.pointer, "the capability is not resolved to an exact catalog revision"
                )
            text = f"{pin.capability_id}@{pin.version}#{pin.digest}"
            if (pin.capability_id, pin.digest) not in pinned:
                raise ManifestLaunchBindingError(
                    item.pointer, f"{text} is not pinned by the admitted runtime profile"
                )
            if text not in available:
                raise ManifestLaunchBindingError(
                    item.pointer,
                    f"{text} has no projection row: no catalog projection rows resolver is "
                    "composed for the provider lanes",
                )
            pins[capability_pin_key(item.role, pin.capability_id)] = text
        ordered = tuple(available[text] for text in binding_capability_pins(pins))
        return pins, ordered

    # -- one Cursor node role (cursor_local, cursor_cloud) --------------------------------------

    def cursor_node(
        self,
        definition: MissionDefinition,
        path: Sequence[DefinitionNode],
        *,
        verifier: bool,
        operation_binding_refs: frozenset[ExactDefinitionRef],
        rows: Mapping[str, ResolvedCapability] | None = None,
        kit_egress: Mapping[str, Sequence[str]] | None = None,
        family: Family,
    ) -> CursorNodeLaunch:
        """Resolve one Cursor node role to its ``mc.cursor_binding.v2`` inputs, or fail pointed.

        A ``mission/v2`` definition's selections (auth, execution environment, workspace policy,
        requires) are admitted against ``providers.<profile>``; a ``mission/v1`` definition has
        none: the worker's Cursor credential applies, ``cursor_local`` runs on the worker that
        serves the lane's queue and ``cursor_cloud`` in the deployment's reviewed
        ``v1_environment``. Model, repository, capabilities and budgets bind for both.
        """

        node = path[-1]
        environment = (
            node.verifier_environment
            if verifier and node.verifier_environment is not None
            else node.environment
        )
        selections = (
            node.verifier_selections
            if verifier and node.verifier_selections is not None
            else node.selections
        )
        profile = _lane_of(path, verifier=verifier)

        def source(field: str) -> str:
            return _selection_source(definition, path, field, verifier=verifier)

        lane_pointer = source("lane")
        providers = self._bindings.providers
        lane = providers.cursor(profile) if providers is not None else None
        if lane is None:
            raise ManifestLaunchBindingError(
                lane_pointer,
                f"lane profile {profile} has no deployment binding "
                f"({LAUNCH_BINDINGS_SCHEMA_V2} providers.{profile})",
            )
        model = self._cursor_model(definition, path, environment, lane, profile, verifier=verifier)
        cloud = self._cursor_placement(selections, lane, profile, source, lane_pointer)
        local = lane if isinstance(lane, CursorLocalLane) else None
        policy: WorkspacePolicyPin | None = None
        if selections is not None:
            try:
                policy = admit_policy(profile, policy_pin(selections.workspace_policy))
            except WorkspaceError as error:
                raise ManifestLaunchBindingError(
                    source("workspace.policy"), error.message
                ) from error
            describe = declared_matrix(profile)
            requires = selections.requires or RequiredFeatures()
            refused = [
                *admit_requirements(
                    describe,
                    RequirementSet(controls=requires.controls, observation=requires.observation),
                ),
                *admit_gate_coverage(
                    describe,
                    GateCoverageRequirement(
                        approvals=requires.approvals, all_writes_gated=requires.all_writes_gated
                    ),
                ),
            ]
            if refused:
                raise ManifestLaunchBindingError(
                    source("requires"), "; ".join(item.message for item in refused)
                )
        # The deployment pins a Cursor model id with no declared vendor until the Model
        # Catalog declares it (R6), so no model route is checked here.
        self._admit_lane(
            definition, path, verifier=verifier, profile=profile, family=family, vendor=None
        )
        workspace_selection = selections.knowledge_workspace if selections is not None else None
        repo = environment.workspace.repo if environment.workspace is not None else None
        repo_pointer = source("workspace.repo")
        knowledge = workspace_selection is not None and workspace_selection.kind == "knowledge"
        named = (
            workspace_selection is not None
            and workspace_selection.repo is not None
            and workspace_selection.repo.use is not None
        )
        # The repository identity the deployment keys: the worker path a cursor_local node must
        # name (compile requires it), the URL a cursor_cloud agent clones.
        identity = (
            None
            if repo is None
            else (repo.path or repo.url)
            if isinstance(lane, CursorLocalLane)
            else repo.url
        )
        research = local is not None and knowledge and repo is None and not named
        knowledge_repository = (
            self._bindings.knowledge_workspace_repository
            if (named or (knowledge and local is None and repo is None))
            else None
        )
        if (
            named or (knowledge and local is None and repo is None)
        ) and knowledge_repository is None:
            raise ManifestLaunchBindingError(
                repo_pointer, "the Application knowledge workspace repository is not bound"
            )
        if (
            repo is None
            and profile not in REPOSITORY_BOUND_PROFILES
            and not research
            and knowledge_repository is None
        ):
            # mission/v2 compiles a repo-less cursor_cloud node (SPEC-03 §4); its binding
            # cannot express one until the repo-less agent launch exists (CM-22).
            raise ManifestLaunchBindingError(
                repo_pointer,
                f"a repo-less {profile} launch is not bound yet (CM-22); bind workspace.repo",
            )
        if (repo is None or identity is None) and not research and knowledge_repository is None:
            raise ManifestLaunchBindingError(
                repo_pointer, f"lane {profile} requires workspace.repo"
            )
        repository = knowledge_repository or (
            CursorRepository(base_refs=("HEAD",))
            if research
            else lane.repositories.get(str(identity))
        )
        if repository is None:
            raise ManifestLaunchBindingError(
                repo_pointer,
                f"repository {identity} is not bound for lane {profile} "
                f"(providers.{profile}.repositories)",
            )
        if local is None and repository.repo_url is None:
            raise ManifestLaunchBindingError(
                repo_pointer, "the cloud knowledge repository needs a clone URL"
            )
        if repository.repo_url is None and not research:
            raise ManifestLaunchBindingError(
                repo_pointer, "the selected repository has no worker path or clone URL"
            )
        if repo is not None and repo.ref is not None and repo.ref not in repository.base_refs:
            raise ManifestLaunchBindingError(
                f"{repo_pointer}/ref",
                f"ref {repo.ref} of repository {identity} is not admitted for lane {profile} "
                f"(providers.{profile}.repositories base_refs {list(repository.base_refs)})",
            )
        slots, ordered = self._cursor_capabilities(
            definition, path, profile, verifier=verifier, refs=operation_binding_refs, rows=rows
        )
        continuation = selections.continuation if selections is not None else None
        return CursorNodeLaunch(
            profile=profile,
            lane=lane,
            lane_pointer=lane_pointer,
            model=model,
            rows=ordered,
            binding_fields={
                "lane_profile": profile,
                "pins": lane.pins,
                "model_id": model.model_id,
                "mode": lane.mode,
                "workspace": CursorWorkspace(
                    repo_url=repository.repo_url,
                    base_ref=(repo.ref if repo is not None else None) or repository.base_refs[0],
                    lease_root=local.lease_root if local is not None else None,
                    branch_prefix=repository.branch_prefix,
                    # MO-05: the local lane leases under the manifest's admitted policy.
                    policy=policy if local is not None else None,
                ),
                "inline_subagents": slots["inline_subagents"],
                "disallowed_tools": local.disallowed_tools if local is not None else (),
                "sandbox_enabled": local.sandbox_enabled if local is not None else False,
                "hook_callback": local.hook_callback if local is not None else None,
                "cloud": cloud,
                "budgets": _narrowed_cursor_budgets(lane.budgets, environment, continuation),
                "materialization": selections.materialization if selections is not None else None,
                "in_environment_observation": (
                    selections.binding_fields().get("in_environment_observation")
                    if selections is not None
                    else None
                ),
                "signal_gates": selections.observation.gates
                if selections is not None and selections.observation is not None
                else None,
                # MO-12: cursor_local's prepare step runs the kit's mission layer; cursor_cloud
                # prepares through its provider environment (MO-13).
                "setup_pin": (
                    selections.binding_fields().get("setup_pin")
                    if selections is not None and local is not None
                    else None
                ),
                "network": (
                    self._network(selections, source, kit_egress)
                    if selections is not None
                    else None
                ),
                "task_queue": lane.task_queue,
            },
            skills=slots["skills"],
            mcp_servers=slots["mcp_servers"],
            hook_scripts=slots["hook_scripts"],
            plugins=slots["plugins"],
            knowledge_workspace=workspace_selection,
        )

    def _cursor_model(
        self,
        definition: MissionDefinition,
        path: Sequence[DefinitionNode],
        environment: Any,
        lane: CursorLocalLane | CursorCloudLane,
        profile: str,
        *,
        verifier: bool,
    ) -> ModelPin:
        pointer = _source(definition, path, "model.profile", verifier=verifier)
        selection = environment.model
        if selection is None or selection.profile is None:
            raise ManifestLaunchBindingError(pointer, "no model profile is bound")
        if not isinstance(selection.profile, str):
            raise ManifestLaunchBindingError(
                pointer,
                f"a catalog model capability has no {profile} lane binding; select a model "
                f"profile bound in providers.{profile}.model_profiles",
            )
        model = lane.model_profiles.get(selection.profile)
        if model is None:
            raise ManifestLaunchBindingError(
                pointer,
                f"model profile {selection.profile} has no deployment model binding for lane "
                f"{profile} (providers.{profile}.model_profiles)",
            )
        for name in sorted(_flatten(selection.settings or {})):
            raise ManifestLaunchBindingError(
                _source(definition, path, f"model.settings.{name}", verifier=verifier),
                f"model setting {name} has no {profile} provider option mapping "
                "(mc.cursor_binding.v2 carries the model ID and mode only)",
            )
        return model

    def _cursor_placement(
        self,
        selections: EnvironmentSelections | None,
        lane: CursorLocalLane | CursorCloudLane,
        profile: str,
        source: Any,
        lane_pointer: str,
    ) -> CursorCloudOptions | None:
        """Admit the auth and execution environment selections; the cloud options to seal."""

        if selections is not None:
            if selections.auth is None:
                raise ManifestLaunchBindingError(source("auth"), "no auth profile is selected")
            if selections.auth.profile not in lane.auth_profiles:
                raise ManifestLaunchBindingError(
                    source("auth.profile"),
                    f"auth profile {selections.auth.profile} has no deployment binding "
                    f"(providers.{profile}.auth_profiles)",
                )
        placement = selections.execution_environment if selections is not None else None
        if isinstance(lane, CursorLocalLane):
            if selections is None:
                return None
            if placement is None:
                raise ManifestLaunchBindingError(
                    source("execution_environment"), "no execution_environment is selected"
                )
            if placement.kind != "local_workspace" or placement.profile is None:
                raise ManifestLaunchBindingError(
                    source("execution_environment.profile"),
                    f"lane {profile} runs on a worker and needs a local_workspace host profile",
                )
            if placement.profile not in lane.host_profiles:
                raise ManifestLaunchBindingError(
                    source("execution_environment.profile"),
                    f"host profile {placement.profile} has no deployment binding "
                    f"(providers.{profile}.host_profiles)",
                )
            return None
        if selections is None:
            if lane.v1_environment is None:
                raise ManifestLaunchBindingError(
                    lane_pointer,
                    f"a mission/v1 {profile} node cannot select a provider-hosted environment "
                    f"and providers.{profile} names no v1_environment",
                )
            return lane.environments[lane.v1_environment].options
        if placement is None or placement.environment_ref is None:
            raise ManifestLaunchBindingError(
                source("execution_environment"),
                f"lane {profile} needs a provider_hosted environment_ref",
            )
        bound = lane.environments.get(placement.environment_ref)
        if bound is None:
            raise ManifestLaunchBindingError(
                source("execution_environment.environment_ref"),
                f"environment {placement.environment_ref} has no deployment binding "
                f"(providers.{profile}.environments)",
            )
        expected = bound.environment
        if (
            placement.expected_revision is not None
            and placement.expected_revision != expected.expected_revision
        ):
            raise ManifestLaunchBindingError(
                source("execution_environment.expected_revision"),
                f"environment {placement.environment_ref} is bound at revision "
                f"{expected.expected_revision}, not {placement.expected_revision}",
            )
        if placement.setup is not None and placement.setup.pin != expected.setup_pin:
            raise ManifestLaunchBindingError(
                source("execution_environment.setup.pin"),
                f"environment {placement.environment_ref} is bound with setup "
                f"{expected.setup_pin}, not {placement.setup.pin}",
            )
        return _with_provider_environment(bound.options, selections, source)

    def _cursor_capabilities(
        self,
        definition: MissionDefinition,
        path: Sequence[DefinitionNode],
        profile: str,
        *,
        verifier: bool,
        refs: frozenset[ExactDefinitionRef],
        rows: Mapping[str, ResolvedCapability] | None,
    ) -> tuple[dict[str, tuple[str, ...]], tuple[ResolvedCapability, ...]]:
        """The binding's projected pins by slot and the rows in ``CatalogRows`` order."""

        node = path[-1]
        environment = (
            node.verifier_environment
            if verifier and node.verifier_environment is not None
            else node.environment
        )
        contexts = environment.workspace.context if environment.workspace is not None else None
        for index, entry in enumerate(contexts or ()):
            if isinstance(entry, str):
                pointer = _source(definition, path, "workspace.context", verifier=verifier)
                raise ManifestLaunchBindingError(
                    f"{pointer}/{index}", f"context profile {entry} has no deployment binding"
                )
        pinned = {(ref.logical_id, ref.digest) for ref in refs}
        available: Mapping[str, ResolvedCapability] = rows or {}
        slots: dict[str, list[str]] = {slot: [] for slot in CURSOR_PROJECTED_KINDS.values()}
        for item in _selected_capabilities(definition, path, verifier=verifier):
            if _plugin_member(item):
                continue  # the plugin's row expands it at render (`plugin_expansion_digest`)
            refused = (
                f"mc.cursor_binding.v2 projects skills, MCP servers, subagent profiles, hook "
                f"scripts and plugins only; a {{kind}} has no {profile} launch binding"
            )
            if item.kind is not None and str(item.kind) not in _CURSOR_MANIFEST_KINDS:
                raise ManifestLaunchBindingError(item.pointer, refused.format(kind=str(item.kind)))
            pin = item.resolved or item.pin
            if pin is None or pin.digest is None:
                raise ManifestLaunchBindingError(
                    item.pointer, "the capability is not resolved to an exact catalog revision"
                )
            text = f"{pin.capability_id}@{pin.version}#{pin.digest}"
            if (pin.capability_id, pin.digest) not in pinned:
                raise ManifestLaunchBindingError(
                    item.pointer, f"{text} is not pinned by the admitted runtime profile"
                )
            row = available.get(text)
            if row is None:
                raise ManifestLaunchBindingError(
                    item.pointer,
                    f"{text} has no projection row: no catalog projection rows resolver is "
                    "composed for the Cursor lanes",
                )
            # Every projection row kind has its slot (a selection without a declared kind is
            # classified by its row).
            slots[CURSOR_PROJECTED_KINDS[row.definition.kind]].append(text)
        fixed = {name: tuple(dict.fromkeys(values)) for name, values in slots.items()}
        order = cursor_projected_pins(**fixed)
        return fixed, tuple(available[text] for text in order)

    # -- templates ----------------------------------------------------------------------------

    def stage_templates(
        self,
        definition: MissionDefinition,
        admitted: AdmittedLaunch,
        *,
        rows: Mapping[str, ResolvedCapability] | None = None,
        kit_egress: Mapping[str, Sequence[str]] | None = None,
    ) -> dict[str, OperationExecutionRequest]:
        blueprint = admitted.blueprint
        if not isinstance(blueprint, StageGraphBlueprint):
            raise ValueError("the admitted blueprint is not a Stage Graph")
        root = definition.program
        children = root.nodes if root.behavior is Behavior.STAGE_GRAPH else (root,)
        paths = {child.key: ((root, child) if child is not root else (root,)) for child in children}
        templates: dict[str, OperationExecutionRequest] = {}
        # L1-07: Deep Agents stages whose agent carries `submit_output` (named promises).
        named_submitters: set[str] = set()
        for stage in blueprint.stages:
            path = paths.get(stage.stage_id)
            if path is None:
                raise ValueError(f"stage {stage.stage_id} has no manifest node")
            node = path[-1]
            objective = _stage_objective(definition, node)
            instruction = _stage_authored_instruction(node)
            namespace = f"workspace-namespace:{{run_id}}:stage:{stage.stage_id}"
            workspace_id = f"workspace:{{run_id}}:stage:{stage.stage_id}"
            owner = WorkspaceOwner(
                kind=WorkspaceOwnerKind.STAGE, owner_id=f"stage:{stage.stage_id}"
            )
            if _lane_of(path, verifier=False) in PROVIDER_PROFILES:
                provider = self.provider_node(
                    definition,
                    path,
                    verifier=False,
                    operation_binding_refs=admitted.operation_binding_refs,
                    rows=rows,
                    kit_egress=kit_egress,
                    family="StageGraph",
                )
                workspace = self._workspace(
                    admitted,
                    namespace=namespace,
                    workspace_id=workspace_id,
                    owner=owner,
                    provision=provider.lane.workspace,
                )
                for slot in stage.operation_slots:
                    for variant in slot.allowed_variants:
                        key = template_key(
                            stage.stage_id, slot.operation_slot_id, variant.operation_variant_id
                        )
                        templates[key] = self._provider_request(
                            admitted,
                            key=key,
                            provider=provider,
                            objective=objective,
                            source=f"input:{node.pointer}",
                            workspace=workspace,
                            operation_contract_ref=variant.operation_contract_ref,
                            output_schema=None,
                            authored_instruction=instruction,
                        )
                continue
            if _lane_of(path, verifier=False) in CURSOR_LANE_PROFILES:
                cursor = self.cursor_node(
                    definition,
                    path,
                    verifier=False,
                    operation_binding_refs=admitted.operation_binding_refs,
                    rows=rows,
                    kit_egress=kit_egress,
                    family="StageGraph",
                )
                workspace = self._workspace(
                    admitted,
                    namespace=namespace,
                    workspace_id=workspace_id,
                    owner=owner,
                    provision=cursor.lane.workspace,
                )
                for slot in stage.operation_slots:
                    for variant in slot.allowed_variants:
                        key = template_key(
                            stage.stage_id, slot.operation_slot_id, variant.operation_variant_id
                        )
                        templates[key] = self._cursor_request(
                            admitted,
                            key=key,
                            cursor=cursor,
                            objective=objective,
                            source=f"input:{node.pointer}",
                            workspace=workspace,
                            operation_contract_ref=variant.operation_contract_ref,
                            output_schema=None,
                            authored_instruction=instruction,
                        )
                continue
            resolved = self.deep_agents_node(
                definition,
                path,
                verifier=False,
                admitted=admitted,
                rows=rows,
                kit_egress=kit_egress,
            )
            workspace = self._workspace(
                admitted, namespace=namespace, workspace_id=workspace_id, owner=owner
            )
            if _submits_named_outputs(resolved.runtime):
                named_submitters.add(stage.stage_id)
            for slot in stage.operation_slots:
                for variant in slot.allowed_variants:
                    key = template_key(
                        stage.stage_id, slot.operation_slot_id, variant.operation_variant_id
                    )
                    templates[key] = self._request(
                        admitted,
                        key=key,
                        position=stage.stage_id,
                        resolved=resolved,
                        model_pointer=_source(definition, path, "model.profile", verifier=False),
                        objective=objective,
                        source=f"input:{node.pointer}",
                        workspace=workspace,
                        operation_contract_ref=variant.operation_contract_ref,
                        output_schema=None,
                        authored_instruction=instruction,
                    )
        for stage in blueprint.stages:
            bound = [slot for slot in stage.output_slots if slot.validation_schema is not None]
            if not bound:
                continue
            contract = {
                "stage_id": stage.stage_id,
                "outputs": [
                    {
                        "slot": slot.output_slot_id,
                        "required": slot.required,
                        "schema_ref": slot.output_contract_ref,
                        "schema": slot.validation_schema.json_schema,
                    }
                    for slot in bound
                    if slot.validation_schema is not None
                ],
            }
            declared = "Declared output contract: " + json.dumps(contract, sort_keys=True) + "\n"
            promises = blueprint.output_promises
            named = (
                stage.stage_id in named_submitters
                and promises is not None
                and all(
                    (promise := promises.obligation(f"{stage.stage_id}.{slot.output_slot_id}"))
                    is not None
                    and promise.form in {OutputForm.STRUCTURED, OutputForm.CONTROL_RECORD}
                    for slot in bound
                )
            )
            # L1-07: a stage that submits named promises is told that act, never custody tools.
            submissions = "; ".join(
                f"obligation {stage.stage_id}.{slot.output_slot_id}" for slot in bound
            )
            instructions = (
                declared
                + (
                    "Submit each declared output with the submit_output tool, one call per output "
                    f"({submissions}): action submit, that obligation key and items "
                    '[{"kind": "inline", "value": <the JSON value>}], the value conforming to the '
                    "output's schema. A file, a workspace path or a reference in your final answer "
                    "is not a submission. An accepted acknowledgement records a draft; Mission "
                    "Control validates the exact submitted value and promotes it. Do not assert "
                    "obligation_refs as evidence of schema acceptance."
                )
                if named
                else declared
                + (
                    "Publish the JSON artifact bytes using the available artifact custody tools. "
                    "Return JSON with output_refs containing the registered durable references and "
                    "output_bindings mapping each output slot name to its references. "
                    "A workspace path or an invented reference is not a published artifact. "
                    "Mission Control evaluates the captured bytes; do not assert obligation_refs "
                    "as evidence of schema acceptance."
                )
            )
            # P5c: a Session Lane has no custody tool; its `outputs/` files are registered at
            # `end_session` and the settlement fills `output_refs` (`lane_completion_candidate`).
            files = "; ".join(
                f"{slot.output_slot_id} -> {session_lane_output_path(slot)}" for slot in bound
            )
            session_instructions = declared + (
                "Write each declared output's JSON bytes to its file, relative to your working "
                f"directory: {files}. Mission Control registers the files under outputs/ when "
                "the session ends. Your final answer must be exactly one JSON object and no "
                'other text, containing "output_refs": [] and no output_bindings; Mission '
                "Control fills output_refs with the registered "
                "references. A file outside outputs/ or an invented reference is not a "
                "published artifact. Mission Control evaluates the captured bytes; do not "
                "assert obligation_refs as evidence of schema acceptance."
            )
            segments = {
                session: PromptSegment(
                    source_ref=f"input:stage-output-contract:{stage.stage_id}",
                    source_revision=1,
                    trust_class=PromptTrustClass.ADMITTED_INPUT,
                    content=text,
                    rendered_digest=sha256_digest(text),
                )
                for session, text in ((False, instructions), (True, session_instructions))
            }
            for slot in stage.operation_slots:
                for variant in slot.allowed_variants:
                    key = template_key(
                        stage.stage_id, slot.operation_slot_id, variant.operation_variant_id
                    )
                    template = templates[key]
                    segment = segments[template.execution_runtime in SESSION_LANE_RUNTIMES]
                    templates[key] = template.model_copy(
                        update={
                            "prompt_segments": (*template.prompt_segments, segment),
                        }
                    )
        return templates

    def goal_templates(
        self,
        definition: MissionDefinition,
        admitted: AdmittedLaunch,
        *,
        rows: Mapping[str, ResolvedCapability] | None = None,
        kit_egress: Mapping[str, Sequence[str]] | None = None,
    ) -> dict[str, OperationExecutionRequest]:
        blueprint = admitted.blueprint
        if not isinstance(blueprint, GoalDirectedBlueprint):
            raise ValueError("the admitted blueprint is not a Goal Loop")
        root = definition.program
        base_id = blueprint.logical_id.removesuffix(".blueprint")
        templates: dict[str, OperationExecutionRequest] = {}
        executor_submits = False
        for role in GOAL_ROLES:
            verifier = role == "verifier"
            objective = (
                f"Mission {definition.mission_key} Goal Loop {role}: {blueprint.objective_contract}"
            )
            # W1 D35: the reconciler admits only the frozen required output contracts
            # (`GoalDirectedService._parsed`); name them so the observation cites one exactly.
            objective += (
                "\nSet output_contract_ref to exactly one of: "
                + ", ".join(sorted(blueprint.required_output_contracts))
                + " (not the objective reference above)."
            )
            if verifier:
                # L1-06: the verifier judges with its own objective (subject, inputs, rubric,
                # decision procedure, verdict contract incl. D35), never the executor's. A
                # non-Deep-Agents verifier gets no plan-borne subject (re-rendered below).
                objective = goal_verifier_objective(
                    definition,
                    blueprint,
                    plan_subjects=(),
                    budget_limits=admitted.authority.budgets.dimensions,
                )
            elif blueprint.output_slots:
                objective += (
                    "\nDeclared output requirements: "
                    + json.dumps(
                        [slot.model_dump(mode="json") for slot in blueprint.output_slots],
                        sort_keys=True,
                    )
                    + "\nReturn output_refs containing registered durable references and "
                    "output_bindings mapping declared slot names to their references. "
                    "Multiple declared outputs require explicit bindings. Every returned "
                    "reference must be bound, and each artifact must satisfy its slot's "
                    "schema; provider success is not output acceptance."
                )
            namespace = "workspace-namespace:{run_id}"
            workspace_id = f"workspace:{{run_id}}:{role}"
            owner = WorkspaceOwner(kind=WorkspaceOwnerKind.RUN, owner_id="goal-template")
            output_schema = (
                self._bindings.deep_agents.goal_output_schemas.get(role)
                if self._bindings.deep_agents is not None
                else None
            )
            if _lane_of((root,), verifier=verifier) in PROVIDER_PROFILES:
                provider = self.provider_node(
                    definition,
                    (root,),
                    verifier=verifier,
                    operation_binding_refs=admitted.operation_binding_refs,
                    rows=rows,
                    kit_egress=kit_egress,
                    family="GoalDirected",
                )
                templates[role] = self._provider_request(
                    admitted,
                    key=role,
                    provider=provider,
                    objective=objective,
                    source=f"input:{root.pointer}/{role}",
                    workspace=self._workspace(
                        admitted,
                        namespace=namespace,
                        workspace_id=workspace_id,
                        owner=owner,
                        provision=provider.lane.workspace,
                    ),
                    operation_contract_ref=f"operation:{base_id}:goal-{role}@1",
                    output_schema=output_schema,
                )
                continue
            if _lane_of((root,), verifier=verifier) in CURSOR_LANE_PROFILES:
                cursor = self.cursor_node(
                    definition,
                    (root,),
                    verifier=verifier,
                    operation_binding_refs=admitted.operation_binding_refs,
                    rows=rows,
                    kit_egress=kit_egress,
                    family="GoalDirected",
                )
                templates[role] = self._cursor_request(
                    admitted,
                    key=role,
                    cursor=cursor,
                    objective=objective,
                    source=f"input:{root.pointer}/{role}",
                    workspace=self._workspace(
                        admitted,
                        namespace=namespace,
                        workspace_id=workspace_id,
                        owner=owner,
                        provision=cursor.lane.workspace,
                    ),
                    operation_contract_ref=f"operation:{base_id}:goal-{role}@1",
                    output_schema=output_schema,
                )
                continue
            resolved = self.deep_agents_node(
                definition,
                (root,),
                verifier=verifier,
                admitted=admitted,
                rows=rows,
                kit_egress=kit_egress,
            )
            subjects = _goal_assessment_subjects(definition)
            if verifier:
                # The subjects its evaluator plan delivers (the condition below attaches it).
                planned = (
                    subjects
                    if subjects
                    and executor_submits
                    and receiver_transfer_base(resolved.runtime, root.key).bounds is not None
                    else ()
                )
                objective = goal_verifier_objective(
                    definition,
                    blueprint,
                    plan_subjects=planned,
                    budget_limits=admitted.authority.budgets.dimensions,
                )
            if (
                not verifier
                and len(blueprint.output_slots) > 1
                and (
                    output_schema is None
                    or output_schema.schema_digest
                    != sha256_digest(GoalNamedExecutorObservation.model_json_schema())
                )
            ):
                raise ManifestLaunchBindingError(
                    f"{root.pointer}/executor",
                    "multiple GoalDirected outputs require the configured "
                    "GoalNamedExecutorObservation structured-output schema",
                )
            templates[role] = self._request(
                admitted,
                key=role,
                position=root.key,
                resolved=resolved,
                model_pointer=_source(definition, (root,), "model.profile", verifier=verifier),
                objective=objective,
                source=f"input:{root.pointer}/{role}",
                workspace=self._workspace(
                    admitted, namespace=namespace, workspace_id=workspace_id, owner=owner
                ),
                operation_contract_ref=f"operation:{base_id}:goal-{role}@1",
                output_schema=output_schema,
            )
            base = templates[role].transfer
            outputs = tuple((root.key, output.key) for output in root.outputs)
            if not verifier:
                executor_submits = _submits_named_outputs(resolved.runtime)
            if base is not None and verifier and not (subjects and executor_submits):
                # R1: no plan-borne subject, still an independent evaluator (isolated reads).
                templates[role] = templates[role].model_copy(
                    update={"transfer": transfer_builders.isolated_evaluator(base)}
                )
            elif base is not None and outputs and (not verifier or executor_submits):
                # The verifier receives the criterion's nominated output evidence, not every
                # final promise (which may depend on this assessment). Missing nominated
                # subjects still refuse delivery. Attach only
                # when the executor can submit them (`submit_output`); otherwise its subject
                # stays the executor's registered outputs in its isolated packet. A later
                # executor iteration receives the same predecessors (none for iteration 1).
                selection = (
                    transfer_builders.evaluator(base, subjects)
                    if verifier
                    else transfer_builders.next_iteration(base, outputs)
                )
                templates[role] = templates[role].model_copy(update={"transfer": selection})
        return templates

    def _workspace(
        self,
        admitted: AdmittedLaunch,
        *,
        namespace: str,
        workspace_id: str,
        owner: WorkspaceOwner,
        provision: WorkspaceProvision | None = None,
    ) -> WorkspaceContract:
        contract = admitted.workspace_contract
        provision = provision or self._deep_scaffold().workspace
        writable = [slot for slot in contract.slots if slot.access == "exclusive_write"]
        if not writable:
            raise ValueError("the admitted workspace contract has no writable slot")
        return WorkspaceContract(
            namespace_id=namespace,
            workspace_id=workspace_id,
            provider=provision.provider,
            template_ref=admitted.workspace_ref,
            workflow_contract_digest=stable_json_digest(contract),
            slot_bindings=tuple(
                WorkspaceSlotBinding(
                    slot_name=slot.name,
                    logical_path=slot.path,
                    access="exclusive_write",
                    owner=owner,
                )
                for slot in writable
            ),
            exclusive_write_paths=tuple(slot.path for slot in writable),
            network_policy=provision.network_policy,
            runtime_digest=provision.runtime_digest,
            image_digest=provision.image_digest,
            package_digest=provision.package_digest,
            environment_digest=provision.environment_digest,
        )

    def _request(
        self,
        admitted: AdmittedLaunch,
        *,
        key: str,
        resolved: DeepAgentsNodeLaunch,
        objective: str,
        position: str | None = None,
        source: str,
        workspace: WorkspaceContract,
        operation_contract_ref: str,
        output_schema: StructuredOutputBinding | None,
        model_pointer: str,
        authored_instruction: PromptSegment | None = None,
    ) -> OperationExecutionRequest:
        """One Deep Agents template: the neutral request around the lane's sealed binding.

        The lane that sealed the node's binding seals the template's `lane_binding` for these
        template coordinates (`LaneTemplateBinder`); the author never reads the bytes. W1 D16,
        every family: a template that binds a structured-output schema is refused when the
        node's model row declares no structured_output strategy (never framework detection).
        """

        assert self._resolution is not None  # `deep_agents_node` refuses without a seam
        if resolved.network is not None:
            workspace = workspace.model_copy(
                update={
                    "network_policy": (
                        "allowlisted" if resolved.network.mode == "allowlist" else "none"
                    )
                }
            )
        pin = resolved.runtime.agent.model
        if output_schema is not None and pin.structured_output is None:
            raise ManifestLaunchBindingError(
                model_pointer,
                f"model profile {pin.profile} ({pin.model_id}) declares no structured_output "
                f"strategy, but template {key} binds a structured-output schema",
            )
        identity = OperationAttemptIdentity(
            run_id=admitted.run_id,
            operation_id=f"manifest-template/{key}",
            operation_attempt=1,
        )
        reservation_id = f"reservation:{admitted.run_id}:manifest-template"
        part = self._resolution.templates(
            resolved.runtime.lane_binding,
            LaneTemplateCoordinates(
                run_id=admitted.run_id,
                operation_id=identity.operation_id,
                operation_attempt=1,
                execution_generation=1,
                control_revision=TEMPLATE_REVISION,
                erc_digest=admitted.configuration_digest,
                workspace=workspace,
                capabilities=admitted.authority.capabilities,
                reservation_id=reservation_id,
                network_hosts=(
                    frozenset(resolved.network.hosts) if resolved.network else frozenset()
                ),
            ),
        )
        return OperationExecutionRequest(
            identity=identity,
            request_scope=admitted.request_scope,
            effective_configuration_digest=admitted.configuration_digest,
            run_control_revision=TEMPLATE_REVISION,
            operation_contract_ref=operation_contract_ref,
            prompt_segments=_request_prompt_segments(objective, source, authored_instruction),
            model_policy=part.model_policy,
            output_schema=output_schema,
            agent_profile_ref=part.agent_profile_ref,
            capability_grant=part.capability_grant,
            workspace=workspace,
            secret_refs=tuple(dict.fromkeys((resolved.model_secret, *part.secret_refs))),
            execution_runtime=part.execution_runtime,
            native_placement=None,
            lane_binding=part.lane_binding,
            lane_dispatch=part.lane_dispatch,
            budget_reservation_id=reservation_id,
            budget_limits=dict(admitted.authority.budgets.dimensions),
            tracing_policy_ref=part.tracing_policy_ref,
            sensitive_data_policy_ref=part.sensitive_data_policy_ref,
            snapshot_policy_ref=part.snapshot_policy_ref,
            requested_at=admitted.compiled_at,
            idempotency_key=f"manifest-template:{admitted.run_id}:{key}",
            # WI-02: the receiver's base transfer selection (bounds from the resolved model and
            # the application's transfer profile); families add their admitted inputs.
            transfer=(
                None if position is None else receiver_transfer_base(resolved.runtime, position)
            ),
        )

    def _provider_request(
        self,
        admitted: AdmittedLaunch,
        *,
        key: str,
        provider: ProviderNodeLaunch,
        objective: str,
        source: str,
        workspace: WorkspaceContract,
        operation_contract_ref: str,
        output_schema: StructuredOutputBinding | None,
        authored_instruction: PromptSegment | None = None,
    ) -> OperationExecutionRequest:
        """A claude/codex template: a sealed ``mc.execution_binding.v2`` routed to its lane."""

        lane = provider.lane
        segments = _request_prompt_segments(objective, source, authored_instruction)
        try:
            if provider.profile in HOSTED_API_PROFILES:
                if self._hosted_digest is None or lane.hosted_projection is None:
                    raise ValueError("hosted projection is not composed")
                digest = self._hosted_digest(
                    provider.profile,
                    lane.hosted_projection,
                    provider.rows,
                    provider.binding_fields["environment"],
                )
            else:
                digest = materialization_digest(
                    provider.rows,
                    provider.profile,
                    segments,
                    projectors=self._projection_port(),
                    telemetry=provider.binding_fields["environment"].in_environment_observation
                    is not False,
                    gates=provider.binding_fields["environment"].signal_gates,
                )
        except ValueError as error:
            raise ManifestLaunchBindingError(
                provider.lane_pointer, f"the {provider.profile} host projection is refused: {error}"
            ) from error
        binding = ProviderExecutionBinding.sealed(
            **provider.binding_fields,
            materialization_digest=digest,
            task_queue=lane.task_queue,
        )
        identity = OperationAttemptIdentity(
            run_id=admitted.run_id,
            operation_id=f"manifest-template/{key}",
            operation_attempt=1,
        )
        reservation_id = f"reservation:{admitted.run_id}:manifest-template"
        options = binding.provider_options
        return OperationExecutionRequest(
            identity=identity,
            request_scope=admitted.request_scope,
            effective_configuration_digest=admitted.configuration_digest,
            run_control_revision=TEMPLATE_REVISION,
            operation_contract_ref=operation_contract_ref,
            prompt_segments=segments,
            model_policy=ModelPolicy(
                provider=model_vendor(provider.profile),
                model=provider.model.model_id,
                reasoning_effort=(
                    options.reasoning_effort if isinstance(options, CodexAppServerOptions) else None
                ),
            ),
            output_schema=output_schema,
            agent_profile_ref=lane.agent_profile_ref,
            capability_grant=CapabilityGrant(capabilities=admitted.authority.capabilities),
            workspace=workspace,
            secret_refs=(),
            execution_runtime=RUNTIME_OF_LANE[LANE_OF_PROFILE[provider.profile]],
            native_placement=None,
            lane_profile=binding.lane_profile,
            # The one place the typed `mc.execution_binding.v2` is produced seals it (OC-R2);
            # only the claude/codex lane adapters unseal it.
            lane_binding=binding.seal(),
            lane_dispatch=binding.lane_dispatch(),
            budget_reservation_id=reservation_id,
            budget_limits=dict(admitted.authority.budgets.dimensions),
            tracing_policy_ref=lane.tracing_policy_ref,
            sensitive_data_policy_ref=lane.sensitive_data_policy_ref,
            snapshot_policy_ref=lane.snapshot_policy_ref,
            requested_at=admitted.compiled_at,
            idempotency_key=f"manifest-template:{admitted.run_id}:{key}",
        )

    def _cursor_request(
        self,
        admitted: AdmittedLaunch,
        *,
        key: str,
        cursor: CursorNodeLaunch,
        objective: str,
        source: str,
        workspace: WorkspaceContract,
        operation_contract_ref: str,
        output_schema: StructuredOutputBinding | None,
        authored_instruction: PromptSegment | None = None,
    ) -> OperationExecutionRequest:
        """A Cursor template: a sealed ``mc.cursor_binding.v2`` routed to its lane queue, whose
        projection digests are those the harness re-renders at ``prepare``."""

        lane = cursor.lane
        if cursor.knowledge_workspace is not None:
            selected = cursor.knowledge_workspace
            workspace = workspace.model_copy(
                update={
                    "kind": selected.kind,
                    "output_channels": selected.outputs.collect if selected.outputs else None,
                    "output_evidence_channel": selected.outputs.evidence_channel
                    if selected.outputs
                    else None,
                }
            )
            if selected.outputs is not None:
                outputs = selected.outputs
                objective += (
                    f"\nWrite the {selected.kind} outputs under {outputs.dir}. "
                    f"Collect through {', '.join(outputs.collect)}. "
                    "Completion evidence channel: "
                    f"{outputs.evidence_channel or outputs.collect[0]}. "
                    "Register output custody; execution completion is not mission acceptance."
                )
        segments = _request_prompt_segments(objective, source, authored_instruction)
        try:
            projection = cursor_projection(
                cursor.rows,
                cursor.profile,
                segments,
                projectors=self._projection_port(),
                telemetry=cursor.binding_fields.get("in_environment_observation") is not False,
                gates=cursor.binding_fields.get("signal_gates"),
            )
        except ValueError as error:
            raise ManifestLaunchBindingError(
                cursor.lane_pointer, f"the {cursor.profile} host projection is refused: {error}"
            ) from error
        digests = cursor_projection_digests(projection)
        binding = CursorExecutionBinding.sealed(
            **cursor.binding_fields,
            projections=CursorProjections(
                **digests,
                skills=cursor.skills,
                mcp_servers=cursor.mcp_servers,
                hook_script_pins=cursor.hook_scripts,
                plugin_pins=cursor.plugins,
            ),
        )
        identity = OperationAttemptIdentity(
            run_id=admitted.run_id,
            operation_id=f"manifest-template/{key}",
            operation_attempt=1,
        )
        reservation_id = f"reservation:{admitted.run_id}:manifest-template"
        return OperationExecutionRequest(
            identity=identity,
            request_scope=admitted.request_scope,
            effective_configuration_digest=admitted.configuration_digest,
            run_control_revision=TEMPLATE_REVISION,
            operation_contract_ref=operation_contract_ref,
            prompt_segments=segments,
            model_policy=ModelPolicy(provider="cursor", model=cursor.model.model_id),
            output_schema=output_schema,
            agent_profile_ref=lane.agent_profile_ref,
            capability_grant=CapabilityGrant(capabilities=admitted.authority.capabilities),
            workspace=workspace,
            # The Cursor credential is the serving worker's (`CURSOR_API_KEY`), never the run's.
            secret_refs=(),
            execution_runtime=RUNTIME_OF_LANE[LANE_OF_PROFILE[cursor.profile]],
            native_placement=None,
            lane_profile=binding.lane_profile,
            # The one place the typed `mc.cursor_binding.v2` is produced seals it (OC-R2); only
            # the Cursor lane adapters unseal it.
            lane_binding=binding.seal(),
            lane_dispatch=binding.lane_dispatch(),
            budget_reservation_id=reservation_id,
            budget_limits=dict(admitted.authority.budgets.dimensions),
            tracing_policy_ref=lane.tracing_policy_ref,
            sensitive_data_policy_ref=lane.sensitive_data_policy_ref,
            snapshot_policy_ref=lane.snapshot_policy_ref,
            requested_at=admitted.compiled_at,
            idempotency_key=f"manifest-template:{admitted.run_id}:{key}",
        )


@dataclass(frozen=True)
class CursorNodeLaunch:
    """One Cursor node role's resolved binding inputs (sealed per template with the
    projection digests of that template's operating contract)."""

    profile: str
    lane: CursorLocalLane | CursorCloudLane
    lane_pointer: str
    model: ModelPin
    rows: tuple[ResolvedCapability, ...]
    binding_fields: dict[str, Any]
    skills: tuple[str, ...]
    mcp_servers: tuple[str, ...]
    hook_scripts: tuple[str, ...]
    plugins: tuple[str, ...]
    knowledge_workspace: WorkspaceSelectionV2 | None = None


@dataclass(frozen=True)
class ProviderNodeLaunch:
    """One claude/codex node role's resolved binding inputs (sealed per template)."""

    profile: str
    lane: ProviderLaneBinding
    lane_pointer: str
    model: ModelPin
    rows: tuple[ResolvedCapability, ...]
    binding_fields: dict[str, Any]


def _selected_capabilities(
    definition: MissionDefinition, path: Sequence[DefinitionNode], *, verifier: bool
) -> list[DefinitionCapability]:
    """The capabilities a node role's effective environment selects (by source pointer)."""

    selected: list[DefinitionCapability] = []
    for group in _CAPABILITY_GROUPS:
        prefix = _source(definition, path, group, verifier=verifier) + "/"
        selected.extend(item for item in definition.capabilities if item.pointer.startswith(prefix))
    return selected


def provider_roles(
    definition: MissionDefinition,
) -> tuple[tuple[tuple[DefinitionNode, ...], bool], ...]:
    """The (path, verifier) node roles a manifest run launches on a provider lane profile
    (claude/codex, hosted or local, and the Cursor profiles)."""

    root = definition.program
    roles: list[tuple[tuple[DefinitionNode, ...], bool]] = []
    if root.behavior is Behavior.GOAL_LOOP:
        roles.extend(((root,), verifier) for verifier in (False, True))
    else:
        children = root.nodes if root.behavior is Behavior.STAGE_GRAPH else (root,)
        roles.extend(
            (((root, child) if child is not root else (root,)), False) for child in children
        )
    return tuple(
        (path, verifier)
        for path, verifier in roles
        if _lane_of(path, verifier=verifier) in PROVIDER_PROFILES | CURSOR_LANE_PROFILES
    )


def _included_kit_pins(definition: MissionDefinition) -> tuple[str, ...]:
    """The kits whose egress some launched node role's network policy includes."""

    pins: list[str] = []
    for path, verifier in provider_roles(definition):
        node = path[-1]
        selections = (
            node.verifier_selections
            if verifier and node.verifier_selections is not None
            else node.selections
        )
        if (
            selections is not None
            and selections.kit is not None
            and selections.network is not None
            and selections.network.include_kit
        ):
            pins.append(selections.kit.pin)
    return tuple(dict.fromkeys(pins))


def provider_capability_pins(definition: MissionDefinition) -> tuple[str, ...]:
    """Exact pin texts the provider node roles project (resolved before the pure resolver).

    A selected plugin is asked for whole, not the members compile expanded from it (its row
    carries and expands them at render). A Cursor role asks only for the kinds its binding can
    project; any other selected kind is refused at its pointer by the resolver, never resolved
    as a projection row."""

    return tuple(_provider_capability_pointers(definition))


def _provider_capability_pointers(definition: MissionDefinition) -> dict[str, str]:
    """:func:`provider_capability_pins` with the first manifest pointer selecting each pin."""

    pointers: dict[str, str] = {}
    for path, verifier in provider_roles(definition):
        cursor = _lane_of(path, verifier=verifier) in CURSOR_LANE_PROFILES
        for item in _selected_capabilities(definition, path, verifier=verifier):
            if _plugin_member(item) or (
                cursor and item.kind is not None and str(item.kind) not in _CURSOR_MANIFEST_KINDS
            ):
                continue
            pin = item.resolved or item.pin
            if pin is not None and pin.digest is not None:
                pointers.setdefault(f"{pin.capability_id}@{pin.version}#{pin.digest}", item.pointer)
    # The Deep Agents lane reads its subagent profiles from their catalog rows too (P1-S3);
    # every other kind it needs comes from the deployment component bindings.
    for path, verifier in deep_agents_roles(definition):
        for item in _selected_capabilities(definition, path, verifier=verifier):
            pin = item.resolved or item.pin
            if item.role == "agent" and pin is not None and pin.digest is not None:
                pointers.setdefault(f"{pin.capability_id}@{pin.version}#{pin.digest}", item.pointer)
    return pointers


def deep_agents_roles(
    definition: MissionDefinition,
) -> tuple[tuple[tuple[DefinitionNode, ...], bool], ...]:
    """The (path, verifier) node roles a manifest run launches on the Deep Agents lane."""

    root = definition.program
    roles: list[tuple[tuple[DefinitionNode, ...], bool]] = []
    if root.behavior is Behavior.GOAL_LOOP:
        roles.extend(((root,), verifier) for verifier in (False, True))
    else:
        children = root.nodes if root.behavior is Behavior.STAGE_GRAPH else (root,)
        roles.extend(
            (((root, child) if child is not root else (root,)), False) for child in children
        )
    return tuple(
        (path, verifier)
        for path, verifier in roles
        if _lane_of(path, verifier=verifier) == DEEP_AGENTS_LANE
    )


def _plugin_member(item: DefinitionCapability) -> bool:
    """A capability compile added by expanding a selected plugin (its ``members/<n>``)."""

    return "plugin_member_role" in item.attributes


def _lane_of(path: Sequence[DefinitionNode], *, verifier: bool) -> str:
    node = path[-1]
    environment = (
        node.verifier_environment
        if verifier and node.verifier_environment is not None
        else node.environment
    )
    return str(environment.lane or node.lane)


def launch_data_class(
    definition: MissionDefinition,
    lane_profile: str,
    *,
    pointer: str,
    ceiling: DataClass,
    policy: DataClassPolicy = DEFAULT_DATA_CLASS_POLICY,
) -> tuple[DataClass, DataClassSource]:
    """The Data Class a node role resolves under and where it came from: the manifest's
    declared class (admitted at compile, `MissionDefinition.data_class`, source `declared`),
    else fail closed (OC-R4): the most sensitive class the lane and the application's
    ``ceiling`` admit (`undeclared_data_class`, source `ceiling_default`), never a fixed
    stand-in; a lane that admits only declared classes refuses `DATA_CLASS_UNDECLARED`."""

    if definition.data_class is not None:
        return definition.data_class, "declared"
    resolved = undeclared_data_class(lane_profile, ceiling, policy=policy)
    if resolved is None:
        issue = admit_data_class(lane_profile, None, policy=policy, pointer=pointer)
        assert issue is not None
        raise ManifestLaunchBindingError(issue.pointer, f"{issue.code}: {issue.message}")
    return resolved, "ceiling_default"


def _application_ceiling(applications: ApplicationRegistry, application_id: str) -> DataClass:
    """The application's Data Class ceiling; an unknown application is refused by the resolver
    (`APPLICATION_UNKNOWN`), so its undeclared class is the most sensitive meanwhile."""

    try:
        return applications.get(application_id).data_class_ceiling
    except KeyError:
        return DATA_CLASSES[-1]


# `mc.agent_configuration.v2` item kinds by manifest role, plugin member role and declared kind.
_ROLE_KINDS: Final[Mapping[str, ConfigurationItemKind]] = {
    "skill": "skill_bundle",
    "hook": "hook_script",
    "context": "context_bundle",
    "agent": "subagent_profile",
}
_MEMBER_KINDS: Final[Mapping[str, ConfigurationItemKind]] = {
    "skill": "skill_bundle",
    "mcp_server": "mcp_server",
    "hook": "hook_script",
    "subagent": "subagent_profile",
    "resource": "context_bundle",
    "prompt": "context_bundle",
}
_DECLARED_KINDS: Final[Mapping[str, ConfigurationItemKind]] = {
    "mcp_server": "mcp_server",
    "mcp_tool": "tool",
    "tool": "tool",
    "skill_bundle": "skill_bundle",
    "hook_script": "hook_script",
    "subagent_profile": "subagent_profile",
    "context_bundle": "context_bundle",
    "sandbox_profile": "sandbox_profile",
}


def _item_kind(item: DefinitionCapability) -> ConfigurationItemKind | None:
    """The neutral item kind of one selection; `None` when v2 has no kind for it (an executor,
    an assessment or a model profile selected as a capability).

    A pinned `capabilities:` entry need not declare its kind; it is classified `tool`, the
    catalog's generic host capability, and the lane maps it by its deployment component (the
    receipt names the component's own kind).
    """

    member = item.attributes.get("plugin_member_role")
    if member is not None:
        return _MEMBER_KINDS.get(str(member))
    if item.role in _ROLE_KINDS:
        return _ROLE_KINDS[item.role]
    if item.kind is None:
        return "tool"
    return _DECLARED_KINDS.get(str(item.kind))


def _selected_profile_item(
    kind: ConfigurationItemKind, name: str, config: Mapping[str, Any]
) -> ConfigurationItem:
    """An item a deployment profile name selects (a sandbox profile), not a catalog pin.

    Until a catalog or registry pins such profiles, the item's pin addresses the selection
    itself (`<kind>.<name>@selected#<digest of the selection>`); the lane maps the name to its
    exact deployment component.
    """

    digest = sha256_digest({"kind": kind, "profile": name})
    return ConfigurationItem.create(
        kind=kind,
        name=f"{kind}:{name}",
        pin=f"{kind.replace('_', '-')}.{name}@selected#{digest}",
        required=True,
        config=config,
    )


def _subagent_profile(
    item: DefinitionCapability,
    pinned: set[tuple[str, str]],
    available: Mapping[str, ResolvedCapability],
) -> SubagentProfile:
    """A selected `agents:` entry's catalog profile body (the lane's child input)."""

    pin = item.resolved or item.pin
    if pin is None or pin.digest is None:
        raise ManifestLaunchBindingError(
            item.pointer, "the subagent profile is not resolved to an exact catalog revision"
        )
    text = f"{pin.capability_id}@{pin.version}#{pin.digest}"
    if (pin.capability_id, pin.digest) not in pinned:
        raise ManifestLaunchBindingError(
            item.pointer, f"{text} is not pinned by the admitted runtime profile"
        )
    row = available.get(text)
    if row is None:
        raise ManifestLaunchBindingError(
            item.pointer,
            f"{text} has no catalog row: no catalog projection rows resolver is "
            "composed, so the subagent profile body cannot be read",
        )
    if not isinstance(row.definition, SubagentProfileDefinition):
        raise ManifestLaunchBindingError(
            item.pointer, f"{text} is not a subagent profile (it is {row.definition.kind})"
        )
    return row.definition.profile


def _jsonable(value: Mapping[str, Any]) -> dict[str, Any]:
    """A neutral configuration value in plain JSON types (decimals as their strings)."""

    return dict(to_jsonable_python(value))


def _manifest_pointer(
    pointer: str,
    *,
    items: Mapping[str, str],
    lane: str,
    model: str,
    node: str,
    mission: str,
) -> str:
    """A resolution refusal's selection pointer as the manifest pointer that selected it.

    ``/items/<i>[/<rest>]`` is the pointer that selected item ``i`` (with ``rest``), and
    ``/items/<i>/plugin`` the plugin row that expanded member ``i``; ``/lane`` and
    ``/model/profile`` are the node's; ``/model/<rest>`` sits beside the model profile;
    ``/application`` and ``/data_class`` are the mission's; anything else (the lane's options
    block, a whole-``/items`` refusal) is under the node's environment.
    """

    if pointer.startswith("/items/"):
        head, _, rest = pointer.removeprefix("/items/").partition("/")
        base = items.get(f"/items/{head}")
        if base is not None:
            if rest == "plugin" and "/members/" in base:
                return base.rsplit("/members/", 1)[0]
            return base + (f"/{rest}" if rest else "")
    if pointer == "/lane" or pointer.startswith("/lane/"):
        return lane + pointer.removeprefix("/lane")
    if pointer == "/model/profile" or pointer.startswith("/model/profile/"):
        return model + pointer.removeprefix("/model/profile")
    if pointer.startswith("/model/"):
        return model.removesuffix("/profile") + pointer.removeprefix("/model")
    if pointer in {"/application", "/data_class"}:
        return mission + pointer
    return node + pointer


_SELECTION_FIELDS: dict[str, str] = {
    "auth": "auth",
    "execution_environment": "execution_environment",
    "workspace.policy": "workspace_policy",
    "continuation": "continuation",
    "requires": "requires",
    "kit": "kit",
    "variables": "variables",
    "secrets": "secrets",
    "network": "network",
    "git": "git",
    "provider_environment": "provider_environment",
}


def _with_provider_environment(
    options: CursorCloudOptions, selections: EnvironmentSelections, source: Any
) -> CursorCloudOptions:
    """MO-13: the manifest's ``provider_environment`` sealed on the cloud options, with the
    kit and the secret declarations a synced environment holds (names and references)."""

    provider = selections.provider_environment
    if provider is None:
        return options
    try:
        sealed = CursorProviderEnvironment(
            strategy=provider.strategy,
            ref=provider.ref,
            kit_pin=selections.kit.pin if selections.kit is not None else None,
            secret_refs=tuple(item.binding_ref for item in selections.secrets or ()),
        )
    except ValidationError as error:
        raise ManifestLaunchBindingError(
            source("provider_environment"), "; ".join(item["msg"] for item in error.errors())
        ) from error
    return options.model_copy(update={"provider_environment": sealed})


def _populated_environment(
    host: EnvironmentBinding,
    selections: EnvironmentSelections,
    source: Any,
    network: ResolvedNetworkPolicy | None,
) -> EnvironmentBinding:
    """The deployment's environment binding populated from the manifest (SPEC-01 §3): the kit
    as ``setup_pin``, secret names and references, and the resolved network policy with its
    digest. Identity, verification and readiness stay the deployment's (or a later
    attestation's)."""

    fields = selections.binding_fields()
    if network is not None:
        fields |= {"network": network, "network_policy_ref": network.digest}
    if not fields:
        return host
    try:
        return EnvironmentBinding.model_validate({**host.model_dump(exclude_unset=True), **fields})
    except ValidationError as error:
        raise ManifestLaunchBindingError(
            source("execution_environment"), "; ".join(item["msg"] for item in error.errors())
        ) from error


def _selection_value(selections: EnvironmentSelections | None, field: str) -> Any:
    """A v2 selection's value by environment field path (``auth.profile``, ...)."""

    if selections is None:
        return None
    name = _SELECTION_FIELDS.get(field)
    rest: list[str] = []
    if name is None:
        head, _, tail = field.partition(".")
        name = _SELECTION_FIELDS.get(head)
        rest = tail.split(".") if tail else []
    if name is None:
        return None
    value: Any = selections.model_dump(mode="json").get(name)
    for part in rest:
        value = value.get(part) if isinstance(value, dict) else None
    return value


def _selection_source(
    definition: MissionDefinition, path: Sequence[DefinitionNode], field: str, *, verifier: bool
) -> str:
    """The manifest pointer that set a v2 selection (or any field) of a node role."""

    node = path[-1]
    if (
        verifier
        and node.verifier_selections is not None
        and _selection_value(node.verifier_selections, field)
        != _selection_value(node.selections, field)
    ):
        return f"{node.pointer}/verifier/environment/" + field.replace(".", "/")
    return _source(definition, path, field, verifier=verifier)


def _narrowed_budgets(
    budgets: BindingBudgets, environment: Any, continuation: ContinuationPolicy | None
) -> BindingBudgets:
    """The deployment's session budgets, narrowed (never raised) by the node's own limits."""

    update: dict[str, int] = {}
    authored = environment.budget
    if authored is not None and authored.wall_clock is not None:
        update["wall_clock_s"] = min(budgets.wall_clock_s, authored.wall_clock)
    if authored is not None and authored.tokens is not None and authored.tokens > 0:
        ceiling = budgets.token_ceiling
        update["token_ceiling"] = min(ceiling, authored.tokens) if ceiling else authored.tokens
    if continuation is not None and continuation.max_session_turns is not None:
        update["max_turns"] = min(budgets.max_turns, continuation.max_session_turns)
    if not update:
        return budgets
    return BindingBudgets.model_validate({**budgets.model_dump(mode="python"), **update})


def _narrowed_cursor_budgets(
    budgets: CursorBudgets, environment: Any, continuation: ContinuationPolicy | None
) -> CursorBudgets:
    """The deployment's Cursor session budgets, narrowed (never raised) by the node's own
    wall clock and session-turn limits (``mc.cursor_binding.v2`` has no token ceiling)."""

    update: dict[str, int] = {}
    authored = environment.budget
    if authored is not None and authored.wall_clock is not None:
        update["wall_clock_s"] = min(budgets.wall_clock_s, authored.wall_clock)
    if continuation is not None and continuation.max_session_turns is not None:
        update["max_turns"] = min(budgets.max_turns, continuation.max_session_turns)
    if not update:
        return budgets
    return CursorBudgets.model_validate({**budgets.model_dump(mode="python"), **update})


def _stage_authored_instruction(node: DefinitionNode) -> PromptSegment | None:
    if node.behavior is not Behavior.AGENT_EXECUTOR or "instruction" not in node.body:
        return None
    instruction = node.body.get("instruction")
    if not isinstance(instruction, str) or not instruction.strip():
        raise ManifestLaunchBindingError(
            f"{node.pointer}/instruction", "an agent executor requires its authored instruction"
        )
    return PromptSegment(
        source_ref=f"input:{node.pointer}/instruction",
        source_revision=1,
        # Manifest node text is admitted run input. Privileged instruction segments
        # require an exact published Prompt source in the accepted configuration.
        trust_class=PromptTrustClass.ADMITTED_INPUT,
        content=instruction,
        rendered_digest=sha256_digest(instruction),
    )


def _request_prompt_segments(
    objective: str, source: str, authored_instruction: PromptSegment | None
) -> tuple[PromptSegment, ...]:
    objective_segment = PromptSegment(
        source_ref=source,
        source_revision=1,
        trust_class=PromptTrustClass.ADMITTED_INPUT,
        content=objective,
        rendered_digest=sha256_digest(objective),
    )
    return (
        (objective_segment, authored_instruction)
        if authored_instruction is not None
        else (objective_segment,)
    )


def _stage_objective(definition: MissionDefinition, node: DefinitionNode) -> str:
    descriptions = {goal.key: goal.description for goal in definition.goals}
    descriptions.update({item.key: item.description for item in definition.objectives})
    texts = [descriptions[key] for key in node.objectives if key in descriptions]
    body = node.body.get("objective") or node.body.get("description")
    detail = "; ".join(texts) or (str(body) if body else node.key)
    return f"Mission {definition.mission_key} stage {node.key}: {detail}"


# --- The author (I/O) -----------------------------------------------------------------------


class KitRequirementsPort(Protocol):
    """An exact Environment Kit pin's ``requires``, read offline (the compile service's
    ``EnvironmentInputsPort`` is one); ``None`` means no such published kit."""

    async def kit_requirements(self, pin: str) -> KitRequirements | None: ...


class ManifestRunDefinitions(Protocol):
    async def run_subscriptions(self, request_scope: str, run_key: str) -> dict[str, Any] | None:
        """The run's mission and the committed ``MissionDefinition@1`` (``definition``)."""


class StageTemplateStore(Protocol):
    async def persist_templates(
        self,
        *,
        request_scope: str,
        semantic_input_binding_ref: str,
        templates: Mapping[str, OperationExecutionRequest],
        recorded_at: datetime,
    ) -> None: ...

    async def list_templates(
        self, *, request_scope: str, semantic_input_binding_ref: str
    ) -> dict[str, OperationExecutionRequest]: ...


class GoalTemplateStore(Protocol):
    async def persist_templates(
        self,
        *,
        request_scope: str,
        semantic_input_binding_ref: str,
        executor: OperationExecutionRequest,
        verifier: OperationExecutionRequest,
        recorded_at: datetime,
    ) -> None: ...

    async def get_template(
        self,
        *,
        semantic_input_binding_ref: str,
        operation_role: str,
        request_scope: str,
        run_id: str,
    ) -> OperationExecutionRequest: ...


def _gate_reviewers(node: Any) -> tuple[str, ...]:
    """Reviewers of a manifest gate node, whether it carries `task` or a `body["task"]`."""

    task = getattr(node, "task", None)
    if task is None:
        task = (getattr(node, "body", None) or {}).get("task")
    if task is None:
        return ()
    if not isinstance(task, dict):
        task = task.model_dump(mode="python", by_alias=True)
    return tuple(str(item) for item in task.get("reviewers", ()) if item)


def _human_gate_nodes(definition: MissionDefinition) -> list[Any]:
    root = definition.program
    children = root.nodes if root.behavior is Behavior.STAGE_GRAPH else (root,)
    return [child for child in children if child.behavior is Behavior.HUMAN_GATE]


# W1 D30: a FALLBACK that duplicates the checked-in application profiles' pin
# (`deployments/<app>/application.toml` `[outputs] assessment_pin`). The bootstrap passes the
# installed application's own pin; this value applies only when that profile cannot be read, and
# must change with the profiles.
TRUSTED_ASSESSMENT_PIN = "knowledge.report.assess@1"


def trusted_requirement_pointer(promises: Any, pin: str) -> str | None:
    """W1 D30: the pointer of the first promise requirement validated by ``pin`` (the trusted
    assessment), or ``None`` when no promise needs it."""

    for obligation in getattr(promises, "obligations", ()) or ():
        for requirement in obligation.contract.requirements:
            if requirement.validator == pin:
                return f"/outputs/{obligation.key}/requirements/{requirement.key}"
    return None


class ManifestLaunchInputAuthor:
    """The production ``LaunchInputPort`` of manifest runs (see module doc)."""

    def __init__(
        self,
        *,
        resolver: ManifestLaunchResolver,
        run_control: RunControlService,
        control_plane: ControlPlaneService,
        definitions: ManifestRunDefinitions,
        stage_templates: StageTemplateStore,
        goal_templates: GoalTemplateStore,
        task_timeout_seconds: int = 300,
        projection_rows: ProjectionRowsPort | None = None,
        kits: KitRequirementsPort | None = None,
        dependent_inputs_admitted: bool = True,
        trusted_assessment_pin: str = TRUSTED_ASSESSMENT_PIN,
    ) -> None:
        self._resolver = resolver
        # OVE-169: whether this installation promotes outputs (a trusted settlement composes).
        self._dependent_inputs_admitted = dependent_inputs_admitted
        # W1 D30: the application's trusted assessment pin; a promise requiring it is refused
        # at launch when no trusted settlement composes.
        self._trusted_assessment_pin = trusted_assessment_pin
        # Catalog rows of the capabilities claude/codex nodes project (MP-03); without it a
        # provider node that selects any capability fails at that capability's pointer.
        self._projection_rows = projection_rows
        # The kits whose egress a network policy includes (MO-15); without it such a policy
        # fails at the kit's pointer.
        self._kits = kits
        self._run_control = run_control
        self._control_plane = control_plane
        self._definitions = definitions
        self._stages = stage_templates
        self._goals = goal_templates
        self._timeout = task_timeout_seconds
        self._dispatcher = WorkflowLaunchDispatcher(
            stagegraph=StageGraphLaunchService(run_control, control_plane),
            goal_directed=GoalDirectedLaunchService(run_control, control_plane),
            run_control=run_control,
            control_plane=control_plane,
        )

    async def family_input(
        self,
        *,
        request_scope: str,
        run_id: str,
        family: Literal["StageGraph", "GoalDirected"],
        initial_goal: str | None,
    ) -> dict[str, Any]:
        await self.bind(request_scope, run_id, family=family)
        gates, review = await self._human_control(request_scope, run_id, family)
        # MP-20: a Stage Graph consumer's authored input names and expand modes travel beside
        # the blueprint (no blueprint digest change) to its Context Packet bindings.
        stage_inputs: tuple[StageAuthoredInput, ...] = ()
        if family == "StageGraph":
            info = await self._definitions.run_subscriptions(request_scope, run_id)
            if info is not None:
                stage_inputs = stagegraph_authored_inputs(
                    MissionDefinition.model_validate(info["definition"])
                )
        await self._admit_inputs(request_scope, run_id, stage_inputs)
        prepared = await self._dispatcher.prepare(
            request_scope,
            run_id,
            initial_goal=initial_goal if family == "GoalDirected" else None,
            task_timeout_seconds=self._timeout,
            semantic_input_binding_ref=binding_ref(run_id),
            human_gates=gates,
            human_review=review,
            stage_inputs=stage_inputs,
        )
        return asdict(prepared)

    async def fork_family_input(
        self,
        *,
        request_scope: str,
        run_id: str,
        source_run_id: str,
        fork_request_id: str,
        family: Literal["StageGraph", "GoalDirected"],
    ) -> tuple[dict[str, Any], str]:
        """F1-G2: a fork-derived Stage Graph run's family input, derived from its source run's
        manifest submission exactly as the source's own was (human gates, authored inputs), but
        bound to the derived run's admission and the fork's semantic input binding. The launch
        derives the run's templates from the source's frozen ones (``_apply_stage_graph_fork``),
        so nothing is frozen here. Returns the input and the source's binding ref."""

        if family != "StageGraph":
            raise ManifestStartUnavailable(
                f"run {run_id}: only a Stage Graph fork derives its input from its source"
            )
        info = await self._definitions.run_subscriptions(request_scope, source_run_id)
        if info is None:
            raise ManifestStartUnavailable(
                f"source run {source_run_id} was not submitted from a manifest"
            )
        source_ref = binding_ref(source_run_id)
        if not await self._stages.list_templates(
            request_scope=request_scope, semantic_input_binding_ref=source_ref
        ):
            raise ManifestStartUnavailable(
                f"source run {source_run_id} has no frozen launch templates (it never launched)"
            )
        definition = MissionDefinition.model_validate(info["definition"])
        stage_inputs = stagegraph_authored_inputs(definition)
        await self._admit_inputs(request_scope, run_id, stage_inputs)
        from mission_control.application.execution.run_launch import (
            fork_semantic_input_binding_ref,
        )

        prepared = await self._dispatcher.prepare(
            request_scope,
            run_id,
            task_timeout_seconds=self._timeout,
            semantic_input_binding_ref=fork_semantic_input_binding_ref(fork_request_id),
            human_gates=stagegraph_human_gates(definition),
            stage_inputs=stage_inputs,
        )
        return asdict(prepared), source_ref

    async def frozen_templates(
        self, request_scope: str, semantic_input_binding_ref: str
    ) -> dict[str, OperationExecutionRequest]:
        """The Stage Graph templates frozen under a semantic input binding (read only)."""

        return await self._stages.list_templates(
            request_scope=request_scope, semantic_input_binding_ref=semantic_input_binding_ref
        )

    async def _admit_inputs(
        self, request_scope: str, run_id: str, stage_inputs: tuple[StageAuthoredInput, ...]
    ) -> None:
        """Dependent inputs and trusted requirements need a composed trusted settlement."""

        if (
            stage_inputs
            and not self._dependent_inputs_admitted
            and not await self._schema_only_dependent_inputs(request_scope, run_id, stage_inputs)
        ):
            raise ManifestDependentInputsUnavailable(
                f"/stages/{stage_inputs[0].consumer_stage_id}/inputs",
                "dependent stage inputs need an accepted revision; no trusted settlement is "
                "composed (set MC_JUDGE_OPENAI_API_KEY and MC_AUDITOR_ANTHROPIC_API_KEY)",
            )
        if not self._dependent_inputs_admitted:
            pointer = trusted_requirement_pointer(
                await self._admitted_promises(request_scope, run_id),
                self._trusted_assessment_pin,
            )
            if pointer is not None:
                raise ManifestTrustedAssessmentUnavailable(
                    pointer,
                    f"the requirement names {self._trusted_assessment_pin}, which only a trusted "
                    "settlement can judge; none is composed (set MC_JUDGE_OPENAI_API_KEY and "
                    "MC_AUDITOR_ANTHROPIC_API_KEY)",
                )

    async def _schema_only_dependent_inputs(
        self, request_scope: str, run_id: str, inputs: tuple[StageAuthoredInput, ...]
    ) -> bool:
        """Bound structured values use the existing schema validator and exact output transfer.

        This changes launch eligibility only. Ordinary submission, schema assessment,
        fulfillment, accepted-head selection and transfer custody still gate actual delivery.
        Optional plain text inputs may also be omitted or delivered through their ordinary
        byte/form checks; they add no assessment guarantee. Reference/report uses and
        additional guarantees still require trusted settlement.
        """
        if self._control_plane is None or self._run_control is None:
            return False
        run = await self._run_control.get_run(request_scope, run_id)
        configuration = await self._control_plane.retrieve_for_admission(
            run.effective_configuration_digest
        )
        blueprint = configuration.selected_blueprint
        if not isinstance(blueprint, StageGraphBlueprint) or blueprint.output_promises is None:
            return False
        for item in inputs:
            key = f"{item.producer_stage_id}.{item.producer_output_slot_id}"
            promise = blueprint.output_promises.obligation(key)
            if (
                promise is None
                or promise.owner_position != item.producer_stage_id
                or promise.contract.requirements
            ):
                return False
            stage = next(
                (stage for stage in blueprint.stages if stage.stage_id == item.producer_stage_id),
                None,
            )
            slot = (
                next(
                    (
                        slot
                        for slot in stage.output_slots
                        if slot.output_slot_id == item.producer_output_slot_id
                    ),
                    None,
                )
                if stage is not None
                else None
            )
            schema = slot.validation_schema if slot is not None else None
            if (
                slot is not None
                and not slot.required
                and not item.required
                and promise.enforcement is Enforcement.OPTIONAL
                and promise.form is OutputForm.TEXT
                and promise.contract.schema_pin is None
            ):
                continue
            if (
                promise.form not in {OutputForm.STRUCTURED, OutputForm.CONTROL_RECORD}
                or promise.contract.schema_pin is None
                or not promise.contract.schema_pin.bound
            ):
                return False
            if (
                schema is None
                or schema.schema_ref != promise.contract.schema_pin.ref
                or schema.schema_digest != promise.contract.schema_pin.digest
            ):
                return False
        return True

    async def _admitted_promises(self, request_scope: str, run_id: str) -> Any:
        """The admitted configuration's output promises (`None` when it declares none). Read
        from the selected blueprint directly, so it needs nothing else of the configuration (a
        workspace template, for example) and adds no failure mode to a launch."""

        projection = await self._run_control.get_run(request_scope, run_id)
        configuration = await self._control_plane.retrieve_for_admission(
            projection.effective_configuration_digest
        )
        return getattr(configuration.selected_blueprint, "output_promises", None)

    async def _human_control(
        self, request_scope: str, run_id: str, family: Literal["StageGraph", "GoalDirected"]
    ) -> tuple[tuple[HumanGateSpec, ...], HumanGateSpec | None]:
        """MP-10 (SPEC-03): the manifest's `human_gate` nodes become Stage Graph gate stages;
        a Goal Loop whose acceptance requires `human` gets one review activation.

        The manifest schema names reviewers only on `human_gate` tasks, which cannot sit under
        a Goal Loop root, so a Goal Loop review borrows the reviewers its definition declares
        on any human gate, else the `owner` reviewer role (`DEFAULT_GOAL_REVIEWERS`). The
        requirement is never dropped: the review still waits for an attributable resolution
        by a principal holding that role.
        """

        info = await self._definitions.run_subscriptions(request_scope, run_id)
        if info is None:
            return (), None
        definition = MissionDefinition.model_validate(info["definition"])
        if family == "StageGraph":
            return stagegraph_human_gates(definition), None
        reviewers = tuple(
            dict.fromkeys(
                reviewer
                for node in _human_gate_nodes(definition)
                for reviewer in _gate_reviewers(node)
            )
        )
        return (), goal_human_review(definition, reviewers=reviewers or DEFAULT_GOAL_REVIEWERS)

    async def bind(
        self,
        request_scope: str,
        run_id: str,
        *,
        family: Literal["StageGraph", "GoalDirected"],
    ) -> dict[str, OperationExecutionRequest]:
        """Freeze the run's templates under its binding ref (once) and return them."""

        reference = binding_ref(run_id)
        projection = await self._run_control.get_run(request_scope, run_id)
        configuration = await self._control_plane.retrieve_for_admission(
            projection.effective_configuration_digest
        )
        admitted = AdmittedLaunch.from_configuration(request_scope, run_id, configuration)
        expected = (
            "StageGraph" if isinstance(admitted.blueprint, StageGraphBlueprint) else "GoalDirected"
        )
        if family != expected:
            raise ValueError(f"run {run_id} admitted a {expected} blueprint, not {family}")
        frozen = await self._frozen(admitted, reference)
        if frozen is not None:
            return frozen
        info = await self._definitions.run_subscriptions(request_scope, run_id)
        if info is None:
            raise ManifestStartUnavailable(f"run {run_id} was not submitted from a manifest")
        definition = MissionDefinition.model_validate(info["definition"])
        recorded_at = admitted.compiled_at
        from mission_control.application.authoring.completion_support import (
            completion_support_issues,
        )

        issues = completion_support_issues(
            definition,
            admitted.blueprint,
        )
        if issues:
            if issues[0].reason == "output_schema_validator_unavailable":
                raise ManifestOutputValidationUnavailable(issues[0].pointer, issues[0].message)
            raise ManifestCompletionUnavailable(issues[0].pointer, issues[0].message)
        rows = await self._rows(definition)
        kit_egress = await self._kit_egress(definition)
        if isinstance(admitted.blueprint, StageGraphBlueprint):
            templates = self._resolver.stage_templates(
                definition, admitted, rows=rows, kit_egress=kit_egress
            )
            await self._stages.persist_templates(
                request_scope=request_scope,
                semantic_input_binding_ref=reference,
                templates=templates,
                recorded_at=recorded_at,
            )
            return templates
        templates = self._resolver.goal_templates(
            definition, admitted, rows=rows, kit_egress=kit_egress
        )
        await self._goals.persist_templates(
            request_scope=request_scope,
            semantic_input_binding_ref=reference,
            executor=templates["executor"],
            verifier=templates["verifier"],
            recorded_at=recorded_at,
        )
        return templates

    async def _rows(self, definition: MissionDefinition) -> Mapping[str, ResolvedCapability]:
        pointers = _provider_capability_pointers(definition)
        if not pointers or self._projection_rows is None:
            return {}
        rows: dict[str, ResolvedCapability] = {}
        for text, pointer in pointers.items():
            try:
                rows.update(await self._projection_rows((text,)))
            except BundleCustodyUnavailable as error:
                raise ManifestBundleCustodyUnavailable(pointer, str(error)) from error
        return rows

    async def _kit_egress(self, definition: MissionDefinition) -> dict[str, tuple[str, ...]]:
        """The resolved egress of every kit a node role's network policy includes."""

        if self._kits is None:
            return {}
        egress: dict[str, tuple[str, ...]] = {}
        for pin in _included_kit_pins(definition):
            requirements = await self._kits.kit_requirements(pin)
            if requirements is not None:
                egress[pin] = requirements.egress
        return egress

    async def _frozen(
        self, admitted: AdmittedLaunch, reference: str
    ) -> dict[str, OperationExecutionRequest] | None:
        if isinstance(admitted.blueprint, StageGraphBlueprint):
            keys = {
                template_key(stage.stage_id, slot.operation_slot_id, variant.operation_variant_id)
                for stage in admitted.blueprint.stages
                for slot in stage.operation_slots
                for variant in slot.allowed_variants
            }
            existing = await self._stages.list_templates(
                request_scope=admitted.request_scope, semantic_input_binding_ref=reference
            )
            return existing if keys and keys <= set(existing) else None
        found: dict[str, OperationExecutionRequest] = {}
        for role in GOAL_ROLES:
            try:
                found[role] = await self._goals.get_template(
                    semantic_input_binding_ref=reference,
                    operation_role=role,
                    request_scope=admitted.request_scope,
                    run_id=admitted.run_id,
                )
            except ValueError:
                return None
        return found


class ManifestChainLaunchInputs:
    """The chain relay's launch input port over the manifest launch author."""

    def __init__(self, author: LaunchInputPort) -> None:
        self._author = author

    async def family_input(self, intent: ChainIntent) -> dict[str, Any]:
        if intent.family is None:
            raise ValueError("a start_run intent names the consumer's family")
        return await self._author.family_input(
            request_scope=intent.request_scope,
            run_id=intent.run_key,
            family=intent.family,
            initial_goal=intent.initial_goal,
        )
