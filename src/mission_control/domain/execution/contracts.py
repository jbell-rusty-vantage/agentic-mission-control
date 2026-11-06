from __future__ import annotations

from enum import StrEnum
from typing import Annotated, ClassVar, Final, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import ExactDefinitionRef, SecretRef
from mission_control.domain.authoring.provider_options import DeepAgentsProviderOptions
from mission_control.domain.capabilities.features.configuration import AgentConfiguration
from mission_control.domain.context.contributions import HostReadScope, StageGrant
from mission_control.domain.context.transfer import TransferSelection
from mission_control.domain.execution.checkpoint_lineage import (
    CheckpointCapture,
    CheckpointInvocationPlan,
    cognitive_session_namespace,
)
from mission_control.domain.execution.cognition_points import CognitionPointObservation
from mission_control.domain.execution.lanes import (
    BINDING_SCHEMAS_OF_LANE,
    DEFAULT_LANE_PROFILE,
    LANE_OF_PROFILE,
    RUNTIMES_OF_LANE,
    ExecutionRuntime,
    LaneDispatch,
    LaneProfileName,
    LaneResumePoint,
    LaneSegmentBounds,
)
from mission_control.domain.execution.materialization_receipt import MaterializationReceipt
from mission_control.domain.execution.usage_admission import LimitWaitPolicy
from mission_control.domain.graph_runtime.identities import (
    QualifiedCheckpointKey,
    RuntimeUnitIdentity,
)
from mission_control.domain.programs.search_attributes import SearchAttributePolicy
from mission_control.domain.resolution.sealed import CarriesLaneBinding, SealedLaneBinding

DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"
PLACEHOLDER_DIGEST = "sha256:" + "0" * 64
MAX_OPERATION_WORKFLOW_PAYLOAD_BYTES = 2_000_000
MAX_OPERATION_SEMANTIC_ATTEMPT_ID_LENGTH = 512
MAX_NATIVE_PLACEMENT_ID_LENGTH = 255
MAX_TEMPORAL_TASK_QUEUE_LENGTH = 255
MAX_EFFECT_FRONTIER_ITEMS = 1_024
MAX_EFFECT_FRONTIER_ITEM_LENGTH = 2_048
MAX_ACTIVE_ASYNC_CHILDREN = 1_024
MAX_ASYNC_CHILD_ID_LENGTH = 512

EffectFrontierItem = Annotated[
    str,
    Field(min_length=1, max_length=MAX_EFFECT_FRONTIER_ITEM_LENGTH),
]
AsyncChildId = Annotated[
    str,
    Field(min_length=1, max_length=MAX_ASYNC_CHILD_ID_LENGTH),
]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _absent(value: object) -> bool:
    """`exclude_if` predicate: an optional FT field that is absent is left out of dumps and of
    every canonical digest, so contracts and fingerprints recorded before it existed hold."""

    return value is None


def _empty(value: object) -> bool:
    """`exclude_if` predicate for an FT collection field that is empty (digest-neutral)."""

    return not value


def _verify_lane_pairing(
    execution_runtime: str,
    lane_profile: str | None,
    lane_binding: SealedLaneBinding | None,
    lane_dispatch: LaneDispatch | None,
) -> None:
    """Pairing rule (OC-R2, replacing FT-G1/MP-01's three typed slots), checked when a request
    or bound operation validates. The profile's lane serves the runtime (`LANE_OF_PROFILE`,
    `RUNTIMES_OF_LANE`: `native` and `deep_agent` run on `deep_agents`, each session runtime on
    its own lane). A `native` attempt carries no lane binding; every other runtime carries
    exactly one sealed binding with its dispatch facts, sealed for the operation's profile under
    a schema that profile's lane produces (`BINDING_SCHEMAS_OF_LANE`). Dispatch repeats the
    lane check against the registered describe (`registries.LaneRegistry.lane_for`)."""

    profile = lane_profile or DEFAULT_LANE_PROFILE
    lane = LANE_OF_PROFILE[profile]
    if execution_runtime not in RUNTIMES_OF_LANE[lane]:
        raise ValueError(f"lane profile {profile} does not serve a {execution_runtime} runtime")
    bound = execution_runtime != "native"
    if bound != (lane_binding is not None) or bound != (lane_dispatch is not None):
        raise ValueError(
            f"{execution_runtime} execution requires exactly one sealed lane binding"
            if bound
            else "a native execution carries no lane binding"
        )
    if lane_binding is None:
        return
    if lane_binding.lane_profile != profile:
        raise ValueError("the sealed lane binding belongs to another lane profile")
    if lane_binding.schema_id not in BINDING_SCHEMAS_OF_LANE[lane]:
        raise ValueError(
            f"a {profile} lane binding cannot carry the {lane_binding.schema_id} schema"
        )


class PromptTrustClass(StrEnum):
    SYSTEM_AUTHORITY = "system_authority"
    AUTHORED_INSTRUCTION = "authored_instruction"
    ADMITTED_INPUT = "admitted_input"
    UNTRUSTED_CONTENT = "untrusted_content"


class OperationAttemptIdentity(Contract):
    run_id: str = Field(min_length=1)
    operation_id: str = Field(min_length=1)
    operation_attempt: int = Field(ge=1)

    @property
    def semantic_key(self) -> str:
        return f"{self.run_id}:operation:{self.operation_id}:attempt:{self.operation_attempt}"


class PromptSegment(Contract):
    source_ref: str = Field(min_length=1)
    source_revision: int = Field(ge=1)
    trust_class: PromptTrustClass
    content: str = Field(max_length=100_000)
    rendered_digest: str = Field(pattern=DIGEST_PATTERN)

    @model_validator(mode="after")
    def rendered_content_matches_digest(self) -> PromptSegment:
        if sha256_digest(self.content) != self.rendered_digest:
            raise ValueError("prompt segment content does not match its rendered digest")
        return self


class ModelPolicy(Contract):
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    reasoning_effort: Literal["minimal", "low", "medium", "high"] | None = None
    verbosity: Literal["low", "medium", "high"] | None = None
    max_turns: int = Field(default=3, ge=1, le=50)
    fallback_models: tuple[str, ...] = ()


class ToolBinding(Contract):
    tool_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    schema_digest: str = Field(pattern=DIGEST_PATTERN)
    approval_policy: Literal["never", "always", "policy"] = "policy"
    configuration: dict[str, object] = Field(default_factory=dict)


class GuardrailBinding(Contract):
    guardrail_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    implementation_digest: str = Field(pattern=DIGEST_PATTERN)
    stage: Literal["input", "output"]


class StructuredOutputBinding(Contract):
    schema_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    schema_digest: str = Field(pattern=DIGEST_PATTERN)
    strict: bool = True


class MCPServerBinding(Contract):
    server_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    transport: Literal["stdio", "sse", "streamable_http"]
    endpoint_ref: str = Field(min_length=1)
    allowed_tools: frozenset[str]
    schema_digest: str = Field(pattern=DIGEST_PATTERN)
    timeout_seconds: int = Field(default=30, ge=1)
    max_retries: int = Field(default=2, ge=0)
    approval_policy: Literal["never", "always", "policy"] = "policy"


class ImmutableAssetBinding(Contract):
    ref: ExactDefinitionRef
    manifest_digest: str = Field(pattern=DIGEST_PATTERN)
    mount_path: str = Field(min_length=1)


class WorkspaceMount(Contract):
    logical_path: str = Field(min_length=1)
    durable_ref: str = Field(min_length=1)
    content_digest: str = Field(pattern=DIGEST_PATTERN)
    read_only: Literal[True] = True


def workspace_durable_reference(namespace_id: str, workspace_id: str) -> str:
    """Return the opaque local durable reference for a governed workspace."""

    identity = sha256_digest(
        {"workspace_id": workspace_id, "namespace_id": namespace_id}
    ).removeprefix("sha256:")
    return f"workspace://{identity}"


class WorkspaceContract(Contract):
    namespace_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    template_ref: ExactDefinitionRef
    workflow_contract_digest: str | None = Field(default=None, pattern=DIGEST_PATTERN)
    slot_bindings: tuple[WorkspaceSlotBinding, ...] = ()
    exclusive_write_paths: tuple[str, ...]
    read_mounts: tuple[WorkspaceMount, ...] = ()
    network_policy: Literal["none", "allowlisted"] = "none"
    runtime_digest: str = Field(pattern=DIGEST_PATTERN)
    image_digest: str = Field(pattern=DIGEST_PATTERN)
    package_digest: str = Field(pattern=DIGEST_PATTERN)
    environment_digest: str = Field(pattern=DIGEST_PATTERN)
    restore_snapshot_id: str | None = None
    kind: Literal["code", "knowledge", "mixed"] = Field(
        default="code",
        exclude_if=lambda v: v == "code",
        json_schema_extra={"digest_omit_default": True},
    )
    output_channels: (
        tuple[Literal["artifact_upload", "branch_commit", "provider_artifacts"], ...] | None
    ) = Field(default=None, exclude_if=_absent, json_schema_extra={"digest_omit_default": True})
    output_evidence_channel: (
        Literal["artifact_upload", "branch_commit", "provider_artifacts"] | None
    ) = Field(default=None, exclude_if=_absent, json_schema_extra={"digest_omit_default": True})

    @field_validator("exclusive_write_paths")
    @classmethod
    def unique_writable_paths(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or len(value) != len(set(value)):
            raise ValueError("workspace requires unique exclusive writable paths")
        return value

    @model_validator(mode="after")
    def compiled_slots_match_legacy_projection(self) -> WorkspaceContract:
        if not self.slot_bindings:
            return self
        paths = [slot.logical_path for slot in self.slot_bindings]
        if any(
            _workspace_paths_overlap(left, right)
            for index, left in enumerate(paths)
            for right in paths[index + 1 :]
        ):
            raise ValueError("compiled workspace slot paths cannot overlap")
        writable = tuple(
            slot.logical_path for slot in self.slot_bindings if slot.access == "exclusive_write"
        )
        if set(writable) != set(self.exclusive_write_paths):
            raise ValueError("compiled workspace slots do not match writable path projection")
        if self.workflow_contract_digest is None:
            raise ValueError("compiled workspace slots require the workflow contract digest")
        return self


class CapabilityGrant(Contract):
    capabilities: frozenset[str]
    tool_ids: frozenset[str] = Field(default_factory=frozenset)
    mcp_server_ids: frozenset[str] = Field(default_factory=frozenset)
    data_scope_refs: frozenset[str] = Field(default_factory=frozenset)
    network_hosts: frozenset[str] = Field(default_factory=frozenset)


class AgentDefinition(Contract):
    definition_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=2_000)
    instructions: str = Field(min_length=1, max_length=100_000)
    model_policy: ModelPolicy
    tools: tuple[ToolBinding, ...] = ()
    mcp_servers: tuple[MCPServerBinding, ...] = ()
    skills: tuple[ImmutableAssetBinding, ...] = ()
    plugins: tuple[ImmutableAssetBinding, ...] = ()
    capability_grant: CapabilityGrant
    output_schema: StructuredOutputBinding | None = None
    guardrails: tuple[GuardrailBinding, ...] = ()
    requested_workflow_type_ref: ExactDefinitionRef | None = None

    @model_validator(mode="after")
    def capabilities_cover_agent_bindings(self) -> AgentDefinition:
        if not {tool.tool_id for tool in self.tools} <= self.capability_grant.tool_ids:
            raise ValueError("agent tool binding exceeds its capability grant")
        if (
            not {server.server_id for server in self.mcp_servers}
            <= self.capability_grant.mcp_server_ids
        ):
            raise ValueError("agent MCP binding exceeds its capability grant")
        return self


class DelegationBinding(Contract):
    mode: Literal["handoff", "task_subagent"]
    agent: AgentDefinition
    tool_name: str | None = Field(default=None, pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
    tool_description: str | None = Field(default=None, max_length=2_000)
    needs_approval: bool = False
    budget_limits: dict[str, int] = Field(default_factory=dict)
    child_workspace_id: str = Field(min_length=1)
    child_namespace_id: str = Field(min_length=1)
    read_mounts: tuple[WorkspaceMount, ...] = ()

    @model_validator(mode="after")
    def task_subagent_has_tool_identity(self) -> DelegationBinding:
        if self.mode == "task_subagent" and (
            self.tool_name is None or self.tool_description is None
        ):
            raise ValueError("task subagents require an exact tool name and description")
        if self.mode == "handoff" and (
            self.tool_name is not None or self.tool_description is not None
        ):
            raise ValueError("handoffs cannot declare an agent-tool identity")
        return self


class DelegationCeiling(Contract):
    allowed_modes: frozenset[Literal["handoff", "task_subagent"]] = frozenset()
    max_depth: int = Field(default=0, ge=0, le=10)
    max_concurrency: int = Field(default=0, ge=0, le=100)
    max_delegations: int = Field(default=0, ge=0, le=1_000)
    allowed_models: frozenset[str] = frozenset()
    tool_ids: frozenset[str] = frozenset()
    mcp_server_ids: frozenset[str] = frozenset()
    data_scope_refs: frozenset[str] = frozenset()
    network_hosts: frozenset[str] = frozenset()
    budget_limits: dict[str, int] = Field(default_factory=dict)


class UnsupportedPolicy(Contract):
    policy: str = Field(min_length=1)
    required: bool = True
    authored_degradation: str | None = None

    @model_validator(mode="after")
    def required_policy_cannot_silently_degrade(self) -> UnsupportedPolicy:
        if self.required and self.authored_degradation is not None:
            raise ValueError("required policies cannot declare degradation")
        return self


class CognitiveChannelContributor(StrEnum):
    BASE = "base"
    MIDDLEWARE = "middleware"
    WORKFLOW_TYPE = "workflow_type"
    OPERATION_ROLE = "operation_role"


class CognitiveReducer(StrEnum):
    REPLACE = "replace"
    MERGE_BY_KEY = "merge_by_key"
    APPEND_UNIQUE_BY_ID = "append_unique_by_id"


class CognitiveChannelDefinition(Contract):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    value_kind: Literal["object", "map", "append_list", "string_list"]
    value_schema_ref: str = Field(min_length=1)
    reducer: CognitiveReducer
    sensitivity: Literal["public", "internal", "restricted"] = "internal"


class CognitiveChannelPack(Contract):
    schema_version: Literal["belllabs.cognitive-channel-pack.v1"] = (
        "belllabs.cognitive-channel-pack.v1"
    )
    logical_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]*$")
    revision: int = Field(ge=1)
    contributor: CognitiveChannelContributor
    channels: tuple[CognitiveChannelDefinition, ...] = Field(min_length=1)
    digest: str = Field(pattern=DIGEST_PATTERN)

    @model_validator(mode="after")
    def validate_pack(self, info: ValidationInfo) -> CognitiveChannelPack:
        names = [channel.name for channel in self.channels]
        if len(names) != len(set(names)):
            raise ValueError("cognitive channel pack names must be unique")
        built_ins = {"messages", "files", "todos", "structured_response"}
        if built_ins & set(names):
            raise ValueError("Deep Agents built-in channels must be inherited, not redeclared")
        if (
            not (info.context or {}).get("allow_placeholder_digest")
            and sha256_digest(self.model_dump(mode="python", exclude={"digest"})) != self.digest
        ):
            raise ValueError("cognitive channel pack digest mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> CognitiveChannelPack:
        payload = dict(values)
        payload.pop("digest", None)
        payload.setdefault("schema_version", "belllabs.cognitive-channel-pack.v1")
        draft = cls.model_validate(
            {**payload, "digest": PLACEHOLDER_DIGEST},
            context={"allow_placeholder_digest": True},
        )
        complete = draft.model_dump(mode="python", exclude={"digest"})
        return cls(**complete, digest=sha256_digest(complete))


class CognitiveChannelPackRef(Contract):
    logical_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]*$")
    revision: int = Field(ge=1)
    digest: str = Field(pattern=DIGEST_PATTERN)
    contributor: CognitiveChannelContributor


class CognitiveRuntimeField(Contract):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    value_kind: Literal["string", "integer", "boolean", "string_list", "string_map"]
    required: bool = True
    sensitivity: Literal["public", "internal", "restricted"] = "internal"
    reference_only: bool = False


class CognitiveRuntimeContextPack(Contract):
    schema_version: Literal["belllabs.cognitive-context-pack.v1"] = (
        "belllabs.cognitive-context-pack.v1"
    )
    logical_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]*$")
    revision: int = Field(ge=1)
    contributor: CognitiveChannelContributor
    fields: tuple[CognitiveRuntimeField, ...] = Field(min_length=1)
    digest: str = Field(pattern=DIGEST_PATTERN)

    @model_validator(mode="after")
    def validate_pack(self, info: ValidationInfo) -> CognitiveRuntimeContextPack:
        names = [field.name for field in self.fields]
        if len(names) != len(set(names)):
            raise ValueError("cognitive runtime-context pack fields must be unique")
        if (
            not (info.context or {}).get("allow_placeholder_digest")
            and sha256_digest(self.model_dump(mode="python", exclude={"digest"})) != self.digest
        ):
            raise ValueError("cognitive runtime-context pack digest mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> CognitiveRuntimeContextPack:
        payload = dict(values)
        payload.pop("digest", None)
        payload.setdefault("schema_version", "belllabs.cognitive-context-pack.v1")
        draft = cls.model_validate(
            {**payload, "digest": PLACEHOLDER_DIGEST},
            context={"allow_placeholder_digest": True},
        )
        complete = draft.model_dump(mode="python", exclude={"digest"})
        return cls(**complete, digest=sha256_digest(complete))


class SubagentStateSlice(Contract):
    slice_id: str = Field(min_length=1)
    channel_names: frozenset[str]
    include_parent_messages: Literal[False] = False


class SubagentContextSlice(Contract):
    slice_id: str = Field(min_length=1)
    field_names: frozenset[str]
    include_secret_fields: Literal[False] = False


class CognitiveStateSchema(Contract):
    schema_version: Literal["belllabs.cognitive-state-schema.v1"] = (
        "belllabs.cognitive-state-schema.v1"
    )
    schema_id: str = Field(min_length=1)
    pack_refs: tuple[CognitiveChannelPackRef, ...] = Field(min_length=1)
    channels: tuple[CognitiveChannelDefinition, ...] = Field(min_length=3)
    reducer_registry_digest: str = Field(pattern=DIGEST_PATTERN)
    deepagents_version: Literal["0.7.5"] = "0.7.5"
    subagent_slices: tuple[SubagentStateSlice, ...] = ()
    schema_digest: str = Field(pattern=DIGEST_PATTERN)

    @model_validator(mode="after")
    def validate_schema(self, info: ValidationInfo) -> CognitiveStateSchema:
        names = [channel.name for channel in self.channels]
        if len(names) != len(set(names)):
            raise ValueError("effective cognitive state channel collision")
        minimum = {"artifact_index", "context_manifest", "child_result_index"}
        if not minimum <= set(names):
            raise ValueError("effective cognitive state schema omits a BellLabs base channel")
        if len({item.slice_id for item in self.subagent_slices}) != len(self.subagent_slices):
            raise ValueError("subagent state slice identities must be unique")
        if any(not item.channel_names <= set(names) for item in self.subagent_slices):
            raise ValueError("subagent state slice contains an unknown channel")
        if (
            not (info.context or {}).get("allow_placeholder_digest")
            and sha256_digest(self.model_dump(mode="python", exclude={"schema_digest"}))
            != self.schema_digest
        ):
            raise ValueError("cognitive state schema digest mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> CognitiveStateSchema:
        payload = dict(values)
        payload.pop("schema_digest", None)
        payload.setdefault("schema_version", "belllabs.cognitive-state-schema.v1")
        payload.setdefault("deepagents_version", "0.7.5")
        payload.setdefault("subagent_slices", ())
        draft = cls.model_validate(
            {**payload, "schema_digest": PLACEHOLDER_DIGEST},
            context={"allow_placeholder_digest": True},
        )
        complete = draft.model_dump(mode="python", exclude={"schema_digest"})
        return cls(**complete, schema_digest=sha256_digest(complete))


class CognitiveRuntimeContextSchema(Contract):
    schema_version: Literal["belllabs.cognitive-context-schema.v1"] = (
        "belllabs.cognitive-context-schema.v1"
    )
    schema_id: str = Field(min_length=1)
    pack_refs: tuple[CognitiveChannelPackRef, ...] = Field(min_length=1)
    fields: tuple[CognitiveRuntimeField, ...] = Field(min_length=1)
    subagent_slices: tuple[SubagentContextSlice, ...] = ()
    schema_digest: str = Field(pattern=DIGEST_PATTERN)

    @model_validator(mode="after")
    def validate_schema(self, info: ValidationInfo) -> CognitiveRuntimeContextSchema:
        names = [field.name for field in self.fields]
        if len(names) != len(set(names)):
            raise ValueError("effective cognitive runtime-context field collision")
        forbidden = {"api_key", "password", "secret", "token", "credential"}
        for field in self.fields:
            normalized = field.name.lower()
            if any(fragment in normalized for fragment in forbidden) and not field.reference_only:
                raise ValueError("sensitive cognitive context fields must contain references only")
        if len({item.slice_id for item in self.subagent_slices}) != len(self.subagent_slices):
            raise ValueError("subagent context slice identities must be unique")
        if any(not item.field_names <= set(names) for item in self.subagent_slices):
            raise ValueError("subagent context slice contains an unknown field")
        if (
            not (info.context or {}).get("allow_placeholder_digest")
            and sha256_digest(self.model_dump(mode="python", exclude={"schema_digest"}))
            != self.schema_digest
        ):
            raise ValueError("cognitive runtime-context schema digest mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> CognitiveRuntimeContextSchema:
        payload = dict(values)
        payload.pop("schema_digest", None)
        payload.setdefault("schema_version", "belllabs.cognitive-context-schema.v1")
        payload.setdefault("subagent_slices", ())
        draft = cls.model_validate(
            {**payload, "schema_digest": PLACEHOLDER_DIGEST},
            context={"allow_placeholder_digest": True},
        )
        complete = draft.model_dump(mode="python", exclude={"schema_digest"})
        return cls(**complete, schema_digest=sha256_digest(complete))


class DeepAgentModelComponent(Contract):
    ref: ExactDefinitionRef
    # The API behind the model (OWNER-INTERVIEW R3 axis 2); each provider has an exact
    # factory in the Deep Agents lane (`materializer.ExactModelFactory`); OC-R6: compiled from
    # the resolved Model Catalog pin, never from the deployment bindings.
    provider: Literal["openai", "anthropic"]
    model_name: str = Field(min_length=1)
    settings: dict[str, object] = Field(default_factory=dict)
    # W1 D16: the resolved Model Catalog row's structured-output strategy; the materializer
    # binds a node's output schema only through it (absent: no structured response can bind).
    structured_output: Literal["tool_forced", "provider_native", "tool_auto"] | None = Field(
        default=None, exclude_if=_absent
    )

    @model_validator(mode="after")
    def exact_model_ref(self) -> DeepAgentModelComponent:
        if self.ref.kind.value != "model":
            raise ValueError("Deep Agent model component requires an exact model ref")
        return self


class DeepAgentMiddlewareComponent(Contract):
    ref: ExactDefinitionRef
    order: int = Field(ge=0)
    contributed_channels: tuple[CognitiveChannelDefinition, ...] = ()

    @model_validator(mode="after")
    def exact_middleware_ref(self) -> DeepAgentMiddlewareComponent:
        if self.ref.kind.value != "middleware":
            raise ValueError("Deep Agent middleware component requires an exact middleware ref")
        return self


class DeepAgentHookScriptComponent(Contract):
    """A catalog Hook Script pinned into a Deep Agents attempt (ADR-0026, SPEC-01)."""

    ref: ExactDefinitionRef
    hook_id: str = Field(min_length=1)
    order: int = Field(ge=0)
    events: tuple[str, ...] = Field(min_length=1)
    matcher: str | None = None
    timeout_seconds: int = Field(default=30, ge=1, le=600)
    fail_closed: bool = False
    interpreter: Literal["sh", "bash", "python", "node"]
    entrypoint: str = Field(min_length=1)
    manifest_digest: str = Field(pattern=DIGEST_PATTERN)
    callback: Literal["none", "service"] = "none"
    # WI-17 (ADR-0062): the hook's admitted host-mediated read scopes and stage grant. Absent
    # from the canonical form (and every recorded digest) while the hook declares none.
    host_reads: tuple[HostReadScope, ...] = Field(default=(), exclude_if=lambda value: not value)
    stage: StageGrant | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def exact_hook_ref(self) -> DeepAgentHookScriptComponent:
        if self.ref.kind.value != "hook_script":
            raise ValueError("Deep Agent hook component requires an exact hook_script ref")
        return self


class DeepAgentToolComponent(Contract):
    ref: ExactDefinitionRef
    tool_name: str = Field(min_length=1)
    schema_digest: str = Field(pattern=DIGEST_PATTERN)
    attachment_target: str = Field(min_length=1)


class DeepAgentSkillComponent(Contract):
    ref: ExactDefinitionRef
    skill_name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    bundle_digest: str = Field(pattern=DIGEST_PATTERN)
    skill_md_digest: str = Field(pattern=DIGEST_PATTERN)
    mount_root: str = Field(pattern=r"^/.*[^/]$")
    attachment_target: str = Field(min_length=1)

    @model_validator(mode="after")
    def exact_skill_ref(self) -> DeepAgentSkillComponent:
        if self.ref.kind.value != "skill":
            raise ValueError("Deep Agent skill component requires an exact Skill ref")
        return self


class DeepAgentMCPToolComponent(Contract):
    tool_name: str = Field(min_length=1)
    schema_digest: str = Field(pattern=DIGEST_PATTERN)


class DeepAgentMCPServerComponent(Contract):
    ref: ExactDefinitionRef
    server_name: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    transport: Literal["stdio", "sse", "streamable_http"]
    endpoint: str | None = None
    command: str | None = None
    arguments: tuple[str, ...] = ()
    credential_refs: tuple[SecretRef, ...] = ()
    tools: tuple[DeepAgentMCPToolComponent, ...] = Field(min_length=1)
    schema_digest: str = Field(pattern=DIGEST_PATTERN)
    attachment_target: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_transport(self) -> DeepAgentMCPServerComponent:
        if self.ref.kind.value != "mcp_server":
            raise ValueError("Deep Agent MCP component requires an exact MCP server ref")
        if self.transport == "stdio":
            if not self.command or self.endpoint is not None:
                raise ValueError("stdio MCP binding requires only command/arguments")
        elif not self.endpoint or self.command is not None or self.arguments:
            raise ValueError("remote MCP binding requires only an endpoint")
        names = [tool.tool_name for tool in self.tools]
        if len(names) != len(set(names)):
            raise ValueError("MCP tool names must be unique per exact server binding")
        return self


class DeepAgentSandboxComponent(Contract):
    ref: ExactDefinitionRef
    backend: Literal["langsmith", "daytona", "docker", "state"]
    runtime_digest: str = Field(pattern=DIGEST_PATTERN)
    snapshot_ref: str | None = None
    credential_refs: tuple[SecretRef, ...] = ()
    idle_ttl_seconds: int = Field(default=300, ge=60, le=86_400)

    @model_validator(mode="after")
    def exact_sandbox_ref(self) -> DeepAgentSandboxComponent:
        if self.ref.kind.value != "sandbox_profile":
            raise ValueError("Deep Agent sandbox component requires an exact sandbox profile ref")
        return self


class SyncSubagentProfile(Contract):
    """One in-process Deep Agents child, exact by digest.

    ``system_prompt_ref`` pins the prompt; the prompt text itself is either served by the
    worker's component registry under that digest or carried inline in ``system_prompt``
    (a manifest-selected profile), which must hash to the same digest. ``mcp_server_refs``
    name parent MCP servers whose tools the child receives (P1-S3; absent before it, so
    bindings sealed earlier keep their digests through ``exclude_if``).
    """

    name: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    description: str = Field(min_length=1)
    system_prompt_ref: ExactDefinitionRef
    model: DeepAgentModelComponent
    tool_refs: tuple[ExactDefinitionRef, ...] = ()
    skill_refs: tuple[ExactDefinitionRef, ...] = ()
    state_slice_id: str = Field(min_length=1)
    context_slice_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    writable_paths: tuple[str, ...] = Field(min_length=1)
    budget_limits: dict[str, int] = Field(default_factory=dict)
    system_prompt: str | None = Field(
        default=None, min_length=1, max_length=8192, exclude_if=lambda value: value is None
    )
    mcp_server_refs: tuple[ExactDefinitionRef, ...] = Field(
        default=(), exclude_if=lambda value: not value
    )
    interrupt_on: tuple[str, ...] = Field(default=(), exclude_if=lambda value: not value)
    # P1 subagents (Q7): the two child shapes. An inheriting child takes every parent tool,
    # MCP tool and Skill root and names nothing of its own; a seeded child may carry exact
    # components the parent does not select (`seeded_*`), loaded and mounted for the child
    # only. All excluded while default, so bindings sealed before them keep their digests.
    inherits_parent: bool = Field(default=False, exclude_if=lambda value: not value)
    seeded_tools: tuple[DeepAgentToolComponent, ...] = Field(
        default=(), exclude_if=lambda value: not value
    )
    seeded_skills: tuple[DeepAgentSkillComponent, ...] = Field(
        default=(), exclude_if=lambda value: not value
    )
    seeded_mcp_servers: tuple[DeepAgentMCPServerComponent, ...] = Field(
        default=(), exclude_if=lambda value: not value
    )

    @model_validator(mode="after")
    def inline_prompt_is_the_pinned_prompt(self) -> SyncSubagentProfile:
        if self.system_prompt_ref.kind.value != "prompt":
            raise ValueError("synchronous subagent system prompt requires an exact prompt ref")
        if (
            self.system_prompt is not None
            and sha256_digest(self.system_prompt) != self.system_prompt_ref.digest
        ):
            raise ValueError("synchronous subagent inline prompt differs from its pinned digest")
        if any(ref.kind.value != "mcp_server" for ref in self.mcp_server_refs):
            raise ValueError("synchronous subagent MCP refs must be exact MCP server refs")
        return self

    @model_validator(mode="after")
    def child_shape_is_exact(self) -> SyncSubagentProfile:
        if self.inherits_parent and (
            self.tool_refs
            or self.skill_refs
            or self.mcp_server_refs
            or self.seeded_tools
            or self.seeded_skills
            or self.seeded_mcp_servers
        ):
            raise ValueError("an inheriting subagent names no components of its own")
        seeded_names = [item.tool_name for item in self.seeded_tools] + [
            tool.tool_name for server in self.seeded_mcp_servers for tool in server.tools
        ]
        if len(seeded_names) != len(set(seeded_names)):
            raise ValueError("synchronous subagent seeded tool namespace collision")
        seeded_servers = [item.server_name for item in self.seeded_mcp_servers]
        if len(seeded_servers) != len(set(seeded_servers)):
            raise ValueError("synchronous subagent seeds an MCP server twice")
        if {item.ref for item in self.seeded_mcp_servers} & set(self.mcp_server_refs):
            raise ValueError("a seeded MCP server cannot also be narrowed from the parent")
        return self

    @property
    def seeded_component_refs(self) -> frozenset[ExactDefinitionRef]:
        """The exact refs of every component this child brings beside the parent's."""

        return frozenset(
            item.ref
            for group in (self.seeded_tools, self.seeded_skills, self.seeded_mcp_servers)
            for item in group
        )


class AsyncSubagentDependencyClass(StrEnum):
    REQUIRED_BLOCKING = "required_blocking"
    DEGRADABLE_BLOCKING = "degradable_blocking"
    NONBLOCKING = "nonblocking"
    ADVISORY = "advisory"


class AsyncSubagentLifecycle(StrEnum):
    PROPOSED = "proposed"
    ADMITTED = "admitted"
    SUBMITTED = "submitted"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ORPHANED = "orphaned"
    # AMD-RRM-001 (REQ-CP-DA-008): an ambiguous submission or observation. It exits only by
    # observation (exactly one verified provider run, or none) or by the typed operator
    # decisions `adopt_provider_run` / `orphan_child`; never by a second spawn.
    IN_DOUBT = "in_doubt"


ACTIVE_ASYNC_SUBAGENT_LIFECYCLES: Final = frozenset(
    {
        AsyncSubagentLifecycle.ADMITTED,
        AsyncSubagentLifecycle.SUBMITTED,
        AsyncSubagentLifecycle.RUNNING,
        AsyncSubagentLifecycle.WAITING,
        AsyncSubagentLifecycle.IN_DOUBT,
    }
)
"""Lifecycles under which a child may still hold or produce provider work (REQ-CP-EXEC-016)."""

AsyncSubagentInDoubtReason = Literal[
    "submission_unobservable",
    "multiple_provider_runs",
    "graph_identity_mismatch",
    "provider_binding_lost",
]


class AsyncSubagentContract(Contract):
    """Immutable BellLabs ceiling for one permitted background subordinate.

    AMD-RRM-001 (REQ-CP-DA-019): the hosted graph is identified exactly by `graph_id`,
    `graph_revision` and `graph_binding_digest` (the digest of the exact BellLabs binding the
    Agent Server materializes it from). `deployment_credential_ref` names the credential the
    parent presents to the deployment; it is a reference only and never a secret value.
    """

    schema_version: Literal["belllabs.async-subagent-contract.v1"] = (
        "belllabs.async-subagent-contract.v1"
    )
    contract_id: str = Field(min_length=1)
    name: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    description: str = Field(min_length=1)
    graph_id: str = Field(min_length=1)
    graph_revision: str = Field(min_length=1, max_length=256)
    graph_binding_digest: str = Field(pattern=DIGEST_PATTERN)
    agent_protocol_url: str = Field(min_length=1)
    deployment_credential_ref: str | None = Field(
        default=None, pattern=r"^(environment|vault|aws-secrets-manager):[A-Za-z0-9_./:-]+$"
    )
    objective_schema_ref: str = Field(min_length=1)
    result_schema_ref: str = Field(min_length=1)
    context_slice_id: str = Field(min_length=1)
    state_slice_id: str = Field(min_length=1)
    capability_ceiling: CapabilityGrant
    authority_refs: tuple[str, ...] = Field(min_length=1)
    budget_limits: dict[str, int] = Field(min_length=1)
    dependency_classes: frozenset[AsyncSubagentDependencyClass] = Field(min_length=1)
    timeout_seconds: int = Field(ge=1, le=604_800)
    cancellation_propagation: Literal["required", "best_effort", "none"]
    late_result_policy: Literal["quarantine", "record_only", "eligible_if_parent_open"]
    fallback_policy: Literal["fail_parent", "degrade", "continue_without_result"]
    result_admission_policy_ref: str = Field(min_length=1)
    # OVE-184 (OUTPUT-CONTRACTS §11): a dynamic child's exact configuration in sealed custody.
    # The generic sealed-child graph materializes it per run on the Agent Server; its digest is
    # the contract's `graph_binding_digest`, so the identity the server stamps into thread state
    # verifies exactly per run. Excluded while absent, so contracts sealed before keep digests.
    child_binding: SealedAsyncChildBinding | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    contract_digest: str = Field(pattern=DIGEST_PATTERN)

    @property
    def sealed(self) -> bool:
        """Whether the child runs from a sealed child binding (the dynamic, per-run graph)."""

        return self.child_binding is not None

    @model_validator(mode="after")
    def sealed_child_is_this_contract(self) -> AsyncSubagentContract:
        child = self.child_binding
        if child is None:
            return self
        if child.sealed_digest != self.graph_binding_digest:
            raise ValueError("a sealed child contract names its binding digest as the graph digest")
        if child.child_name != self.name:
            raise ValueError("a sealed child binding belongs to the contract's subagent name")
        return self

    @model_validator(mode="after")
    def validate_digest(self, info: ValidationInfo) -> AsyncSubagentContract:
        if (
            not (info.context or {}).get("allow_placeholder_digest")
            and sha256_digest(self.model_dump(mode="python", exclude={"contract_digest"}))
            != self.contract_digest
        ):
            raise ValueError("async subagent contract digest mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> AsyncSubagentContract:
        payload = dict(values)
        payload.pop("contract_digest", None)
        payload.setdefault("schema_version", "belllabs.async-subagent-contract.v1")
        draft = cls.model_validate(
            {**payload, "contract_digest": PLACEHOLDER_DIGEST},
            context={"allow_placeholder_digest": True},
        )
        complete = draft.model_dump(mode="python", exclude={"contract_digest"})
        return cls(**complete, contract_digest=sha256_digest(complete))


class AsyncProviderCheckpointKey(Contract):
    """The provider's qualified checkpoint key of an async child (REQ-CP-DA-011, AMD-RRM-001).

    Thread, namespace as reported, checkpoint ID, and the served graph identity verified under
    REQ-CP-DA-019. A thread-only reference is insufficient.
    """

    schema_version: Literal["belllabs.async-provider-checkpoint-key.v1"] = (
        "belllabs.async-provider-checkpoint-key.v1"
    )
    agent_protocol_url: str = Field(min_length=1)
    thread_id: str = Field(min_length=1, max_length=1024)
    checkpoint_ns: str = Field(default="", max_length=1024)
    checkpoint_id: str = Field(min_length=1, max_length=256)
    graph_id: str = Field(min_length=1)
    graph_revision: str = Field(min_length=1, max_length=256)
    graph_binding_digest: str = Field(pattern=DIGEST_PATTERN)

    @property
    def ref(self) -> str:
        return (
            f"agent-protocol-checkpoint:{self.graph_id}@{self.graph_revision}:"
            f"{self.thread_id}:{self.checkpoint_ns}:{self.checkpoint_id}"
        )


class AsyncSubagentUsage(Contract):
    """Provider-attributed child usage, or the pending amounts the provider could not attribute.

    REQ-CP-DA-011 / REQ-CP-RUN-009 (AMD-RRM-001): attributed amounts settle exactly once against
    the parent run's budget; pending or ambiguous amounts stay pending and are never dropped.
    """

    schema_version: Literal["belllabs.async-subagent-usage.v1"] = "belllabs.async-subagent-usage.v1"
    provider_run_id: str = Field(min_length=1)
    attribution: Literal["provider_attributed", "pending", "ambiguous"]
    attributed_amounts: dict[str, int] = Field(default_factory=dict)
    pending_amounts: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def amounts_follow_attribution(self) -> AsyncSubagentUsage:
        amounts = (*self.attributed_amounts.values(), *self.pending_amounts.values())
        if any(amount < 0 for amount in amounts):
            raise ValueError("async child usage amounts cannot be negative")
        if self.attribution != "provider_attributed" and self.attributed_amounts:
            raise ValueError("only provider-attributed usage carries attributed amounts")
        return self

    @property
    def usage_ref(self) -> str:
        return "ref:async-usage:" + sha256_digest(
            self.model_dump(mode="python", exclude={"schema_version"})
        ).removeprefix("sha256:")


class AsyncSubagentResultManifest(Contract):
    schema_version: Literal["belllabs.async-subagent-result.v1"] = (
        "belllabs.async-subagent-result.v1"
    )
    manifest_id: str = Field(min_length=1)
    child_execution_id: str = Field(min_length=1)
    execution_generation: int = Field(ge=1)
    output_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    usage_ref: str = Field(min_length=1)
    checkpoint_ref: str = Field(min_length=1)
    # AMD-RRM-001 (REQ-CP-DA-011): the typed provider checkpoint key and attributed usage the
    # flat refs above are derived from. `checkpoint_ref` is the key's canonical ref and
    # `usage_ref` is the usage's content address.
    provider_checkpoint: AsyncProviderCheckpointKey
    usage: AsyncSubagentUsage
    effect_refs: tuple[str, ...] = ()
    completed_at: AwareDatetime
    manifest_digest: str = Field(pattern=DIGEST_PATTERN)

    @model_validator(mode="after")
    def validate_digest(self, info: ValidationInfo) -> AsyncSubagentResultManifest:
        if self.checkpoint_ref != self.provider_checkpoint.ref:
            raise ValueError("checkpoint_ref must be the provider checkpoint key's canonical ref")
        if self.usage_ref != self.usage.usage_ref:
            raise ValueError("usage_ref must be the typed usage's content address")
        if (
            not (info.context or {}).get("allow_placeholder_digest")
            and sha256_digest(self.model_dump(mode="python", exclude={"manifest_digest"}))
            != self.manifest_digest
        ):
            raise ValueError("async subagent result manifest digest mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> AsyncSubagentResultManifest:
        payload = dict(values)
        payload.pop("manifest_digest", None)
        payload.setdefault("schema_version", "belllabs.async-subagent-result.v1")
        draft = cls.model_validate(
            {**payload, "manifest_digest": PLACEHOLDER_DIGEST},
            context={"allow_placeholder_digest": True},
        )
        complete = draft.model_dump(mode="python", exclude={"manifest_digest"})
        return cls(**complete, manifest_digest=sha256_digest(complete))


class AsyncSubagentExecution(Contract):
    schema_version: Literal["belllabs.async-subagent-execution.v1"] = (
        "belllabs.async-subagent-execution.v1"
    )
    child_execution_id: str = Field(min_length=1)
    contract_id: str = Field(min_length=1)
    contract_digest: str = Field(pattern=DIGEST_PATTERN)
    parent_run_id: str = Field(min_length=1)
    parent_operation_id: str = Field(min_length=1)
    parent_binding_id: str = Field(min_length=1)
    execution_generation: int = Field(ge=1)
    objective_ref: str = Field(min_length=1)
    context_slice_ref: str = Field(min_length=1)
    reservation_id: str = Field(min_length=1)
    lifecycle: AsyncSubagentLifecycle
    provider_thread_id: str | None = Field(default=None, min_length=1)
    provider_run_id: str | None = Field(default=None, min_length=1)
    result_manifest: AsyncSubagentResultManifest | None = None
    # Provider evidence of the completed child's final message, addressed by the manifest's
    # output ref. It reaches the parent's cognition only after result admission (DA-011).
    result_output_text: str | None = Field(default=None, max_length=200_000)
    # AMD-RRM-001 (REQ-CP-DA-008): why the child is `in_doubt` and the governed incident that
    # awaits observation or an operator decision. Both are set exactly while in doubt.
    in_doubt_reason: AsyncSubagentInDoubtReason | None = None
    incident_id: str | None = Field(default=None, min_length=1, max_length=256)
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def provider_identity_follows_submission(self) -> AsyncSubagentExecution:
        bound = self.provider_thread_id is not None and self.provider_run_id is not None
        if (self.provider_thread_id is None) != (self.provider_run_id is None):
            raise ValueError("provider thread and run identities bind together")
        if (
            self.lifecycle in {AsyncSubagentLifecycle.PROPOSED, AsyncSubagentLifecycle.ADMITTED}
            and bound
        ):
            raise ValueError("provider identity cannot precede BellLabs admission")
        if self.lifecycle == AsyncSubagentLifecycle.COMPLETED and self.result_manifest is None:
            raise ValueError("completed async child requires a typed result manifest")
        in_doubt = self.lifecycle == AsyncSubagentLifecycle.IN_DOUBT
        if in_doubt != (self.in_doubt_reason is not None) or in_doubt != (
            self.incident_id is not None
        ):
            raise ValueError("exactly an in_doubt child carries its reason and incident")
        return self


class AsyncSubagentMessage(Contract):
    schema_version: Literal["belllabs.async-subagent-message.v1"] = (
        "belllabs.async-subagent-message.v1"
    )
    message_id: str = Field(min_length=1)
    child_execution_id: str = Field(min_length=1)
    direction: Literal["parent_to_child", "child_to_parent"]
    target_sequence: int = Field(ge=1)
    correlation_id: str = Field(min_length=1)
    causation_id: str | None = Field(default=None, min_length=1)
    payload_ref: str = Field(min_length=1)
    context_authority: Literal["instruction", "admitted_context", "untrusted_observation"]
    expires_at: AwareDatetime | None = None
    supersedes_message_id: str | None = Field(default=None, min_length=1)
    receipt: Literal[
        "accepted", "claimed", "provider_applied", "checkpoint_committed", "terminal_rejected"
    ] = "accepted"
    created_at: AwareDatetime


class ParentAsyncSubagentLink(Contract):
    schema_version: Literal["belllabs.parent-async-subagent-link.v1"] = (
        "belllabs.parent-async-subagent-link.v1"
    )
    link_id: str = Field(min_length=1)
    child_execution_id: str = Field(min_length=1)
    parent_run_id: str = Field(min_length=1)
    parent_operation_id: str = Field(min_length=1)
    dependency_class: AsyncSubagentDependencyClass
    timeout_at: AwareDatetime
    cancellation_propagation: Literal["required", "best_effort", "none"]
    late_result_policy: Literal["quarantine", "record_only", "eligible_if_parent_open"]
    fallback_policy: Literal["fail_parent", "degrade", "continue_without_result"]
    result_admission_policy_ref: str = Field(min_length=1)
    messages: tuple[AsyncSubagentMessage, ...] = ()
    cancellation_requested: bool = False
    cancellation_reason: str | None = None
    # AMD-RRM-001 (REQ-CP-DA-011 / REQ-CP-EXEC-008): whether the provider acknowledged the
    # cancel request or its outcome stayed ambiguous; recorded, never inferred.
    cancellation_receipt: Literal["provider_acknowledged", "ambiguous"] | None = None
    # AMD-RRM-001 (REQ-CP-DA-008): the typed operator decision that resolved `in_doubt`.
    reconciliation_decision: Literal["adopt_provider_run", "orphan_child"] | None = None
    adopted_provider_run_id: str | None = Field(default=None, min_length=1)
    result_decision: Literal["admit", "conditionally_admit", "reject", "defer"] | None = None
    admitted_manifest_digest: str | None = Field(default=None, pattern=DIGEST_PATTERN)
    # REQ-CP-RUN-009 (RRM-013 review): a settlement attempt is numbered; `settled` is true only
    # once the parent ledger holds the child's usage with nothing pending.
    settled: bool = False
    settlement_revision: int = Field(default=0, ge=0)
    usage_disposition: Literal["settled", "pending_usage"] | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime


class DeepAgentProfile(Contract):
    schema_version: Literal["belllabs.deep-agent-profile.v1"] = "belllabs.deep-agent-profile.v1"
    logical_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]*$")
    revision: int = Field(ge=1)
    framework_family: Literal["deepagents"] = "deepagents"
    model: DeepAgentModelComponent
    structured_output_ref: ExactDefinitionRef | None = None
    prompt_refs: tuple[ExactDefinitionRef, ...] = Field(min_length=1)
    context_assembly_ref: ExactDefinitionRef
    middleware: tuple[DeepAgentMiddlewareComponent, ...] = ()
    backend_ref: ExactDefinitionRef
    store_ref: ExactDefinitionRef
    checkpointer_ref: ExactDefinitionRef
    tools: tuple[DeepAgentToolComponent, ...] = ()
    mcp_servers: tuple[DeepAgentMCPServerComponent, ...] = ()
    skills: tuple[DeepAgentSkillComponent, ...] = ()
    memory_refs: tuple[ExactDefinitionRef, ...] = ()
    sandbox: DeepAgentSandboxComponent
    sync_subagents: tuple[SyncSubagentProfile, ...] = ()
    async_subagents: tuple[AsyncSubagentContract, ...] = ()
    async_subagent_policy_refs: tuple[ExactDefinitionRef, ...] = ()
    delegation_ceiling: DelegationCeiling = Field(default_factory=DelegationCeiling)
    hitl_policy_ref: ExactDefinitionRef | None = None
    limits: dict[str, int] = Field(default_factory=dict)
    tracing_policy_ref: ExactDefinitionRef
    cognitive_state_pack_refs: tuple[CognitiveChannelPackRef, ...] = Field(min_length=1)
    cognitive_context_pack_refs: tuple[CognitiveChannelPackRef, ...] = Field(min_length=1)
    compatible_placement_ids: frozenset[str] = Field(min_length=1)
    # P1-S2: the manifest's `provider_options.deep_agents`, applied by the lane adapter.
    # Excluded while absent so profiles sealed before it keep their digests.
    provider_options: DeepAgentsProviderOptions | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    # Sprint B: the sealed lane-feature and model-tool selection the lane adapter resolved
    # (defaults included). Excluded while absent so earlier profiles keep their digests.
    agent_configuration: AgentConfiguration | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    profile_digest: str = Field(pattern=DIGEST_PATTERN)

    @model_validator(mode="after")
    def validate_profile(self, info: ValidationInfo) -> DeepAgentProfile:
        orders = [item.order for item in self.middleware]
        if orders != sorted(orders) or len(orders) != len(set(orders)):
            raise ValueError("Deep Agent middleware order must be exact and collision-free")
        names = [item.name for item in self.sync_subagents]
        if len(names) != len(set(names)):
            raise ValueError("synchronous subagent names must be unique")
        async_names = [item.name for item in self.async_subagents]
        if len(async_names) != len(set(async_names)):
            raise ValueError("asynchronous subagent names must be unique")
        if (
            not (info.context or {}).get("allow_placeholder_digest")
            and sha256_digest(self.model_dump(mode="python", exclude={"profile_digest"}))
            != self.profile_digest
        ):
            raise ValueError("Deep Agent profile digest mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> DeepAgentProfile:
        payload = dict(values)
        payload.pop("profile_digest", None)
        payload.setdefault("schema_version", "belllabs.deep-agent-profile.v1")
        payload.setdefault("framework_family", "deepagents")
        draft = cls.model_validate(
            {**payload, "profile_digest": PLACEHOLDER_DIGEST},
            context={"allow_placeholder_digest": True},
        )
        complete = draft.model_dump(mode="python", exclude={"profile_digest"})
        return cls(**complete, profile_digest=sha256_digest(complete))


class DeepAgentExecutionPlacementProfile(Contract):
    schema_version: Literal["belllabs.deep-agent-placement.v1"] = "belllabs.deep-agent-placement.v1"
    logical_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]*$")
    revision: int = Field(ge=1)
    placement: Literal["local_in_worker", "remote_langsmith_deployment"]
    deepagents_version: Literal["0.7.5"] = "0.7.5"
    python_runtime: str = Field(min_length=1)
    package_versions: dict[str, str] = Field(min_length=1)
    deployment_id: str | None = None
    task_queue: str = Field(min_length=1)
    checkpoint_behavior: Literal["local_checkpointer", "remote_managed"]
    cancellation_behavior: Literal["cooperative", "remote_reconcile"]
    streaming_behavior: Literal["state_updates", "messages"]
    message_injection_behavior: Literal["invoke_only", "remote_thread"]
    reconnect_behavior: Literal["checkpoint_resume", "remote_run_reconnect"]
    sandbox_backends: frozenset[Literal["langsmith", "daytona", "docker", "state"]]
    trace_behavior: Literal["langsmith"] = "langsmith"
    qualification_refs: tuple[str, ...] = Field(min_length=1)
    silent_fallback: Literal[False] = False
    placement_digest: str = Field(pattern=DIGEST_PATTERN)

    @model_validator(mode="after")
    def validate_placement(self, info: ValidationInfo) -> DeepAgentExecutionPlacementProfile:
        if self.placement == "local_in_worker" and self.deployment_id is not None:
            raise ValueError("local Deep Agent placement cannot declare a remote deployment")
        if self.placement == "remote_langsmith_deployment" and not self.deployment_id:
            raise ValueError("remote Deep Agent placement requires an exact deployment identity")
        if (
            not (info.context or {}).get("allow_placeholder_digest")
            and sha256_digest(self.model_dump(mode="python", exclude={"placement_digest"}))
            != self.placement_digest
        ):
            raise ValueError("Deep Agent placement digest mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> DeepAgentExecutionPlacementProfile:
        payload = dict(values)
        payload.pop("placement_digest", None)
        payload.setdefault("schema_version", "belllabs.deep-agent-placement.v1")
        payload.setdefault("deepagents_version", "0.7.5")
        payload.setdefault("trace_behavior", "langsmith")
        payload.setdefault("silent_fallback", False)
        draft = cls.model_validate(
            {**payload, "placement_digest": PLACEHOLDER_DIGEST},
            context={"allow_placeholder_digest": True},
        )
        complete = draft.model_dump(mode="python", exclude={"placement_digest"})
        return cls(**complete, placement_digest=sha256_digest(complete))


class DeepAgentAttachmentRecord(Contract):
    component_kind: Literal["model", "middleware", "tool", "mcp", "skill", "sandbox"]
    component_digest: str = Field(pattern=DIGEST_PATTERN)
    attachment_target: str = Field(min_length=1)
    status: Literal["intended", "resolved"] = "intended"


DEEP_AGENT_BINDING_SCHEMA: Final = "belllabs.deep-agent-binding.v1"


class DeepAgentExecutionBinding(Contract):
    schema_version: Literal["belllabs.deep-agent-binding.v1"] = "belllabs.deep-agent-binding.v1"
    binding_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    operation_id: str = Field(min_length=1)
    operation_attempt: int = Field(ge=1)
    execution_generation: int = Field(ge=1)
    erc_digest: str = Field(pattern=DIGEST_PATTERN)
    control_revision: int = Field(ge=1)
    profile_id: str = Field(min_length=1)
    profile_revision: int = Field(ge=1)
    profile_digest: str = Field(pattern=DIGEST_PATTERN)
    placement_id: str = Field(min_length=1)
    placement_revision: int = Field(ge=1)
    placement_digest: str = Field(pattern=DIGEST_PATTERN)
    placement: Literal["local_in_worker", "remote_langsmith_deployment"]
    task_queue: str = Field(min_length=1)
    checkpoint_behavior: Literal["local_checkpointer", "remote_managed"]
    cancellation_behavior: Literal["cooperative", "remote_reconcile"]
    streaming_behavior: Literal["state_updates", "messages"]
    message_injection_behavior: Literal["invoke_only", "remote_thread"]
    reconnect_behavior: Literal["checkpoint_resume", "remote_run_reconnect"]
    model: DeepAgentModelComponent
    backend_ref: ExactDefinitionRef
    store_ref: ExactDefinitionRef
    checkpointer_ref: ExactDefinitionRef
    middleware: tuple[DeepAgentMiddlewareComponent, ...] = ()
    # FT-A5: catalog hook scripts; kernel hooks are composed by the materializer, never here.
    # Excluded from the digest while empty so earlier bindings keep their content address.
    hook_scripts: tuple[DeepAgentHookScriptComponent, ...] = ()
    tools: tuple[DeepAgentToolComponent, ...] = ()
    mcp_servers: tuple[DeepAgentMCPServerComponent, ...] = ()
    skills: tuple[DeepAgentSkillComponent, ...] = ()
    sandbox: DeepAgentSandboxComponent
    sync_subagents: tuple[SyncSubagentProfile, ...] = ()
    async_subagents: tuple[AsyncSubagentContract, ...] = ()
    cognitive_state_schema: CognitiveStateSchema
    cognitive_context_schema: CognitiveRuntimeContextSchema
    cognitive_context_values: dict[str, object]
    initial_artifact_index: dict[str, object] = Field(default_factory=dict)
    initial_context_manifest: dict[str, object]
    initial_child_result_index: tuple[dict[str, object], ...] = ()
    workspace: WorkspaceContract
    capability_grant: CapabilityGrant
    reservation_id: str = Field(min_length=1)
    authority_refs: tuple[str, ...] = Field(min_length=1)
    redaction_policy_ref: str = Field(min_length=1)
    package_versions: dict[str, str] = Field(min_length=1)
    intended_attachments: tuple[DeepAgentAttachmentRecord, ...] = Field(min_length=1)
    applied_degradations: tuple[str, ...] = ()
    silent_fallback: Literal[False] = False
    # AMD-RRM-001 (REQ-CP-DA-016, REQ-CP-EXEC-013): the frozen runtime unit and the
    # cognitive session namespace the worker must address. Absent fields are excluded
    # from the digest so earlier bindings keep their content address.
    runtime_unit: RuntimeUnitIdentity | None = None
    cognitive_session_namespace: str | None = Field(default=None, min_length=1, max_length=1024)
    # P1-S1/S2: the lane options the adapter honoured and its receipt for every configured
    # item. Both are excluded while absent so earlier bindings keep their content address.
    provider_options: DeepAgentsProviderOptions | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    materialization_receipt: MaterializationReceipt | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    # Sprint B: what the materializer realizes beyond the components above (lane features
    # and model tools, `mc.agent_configuration.v1`). Excluded while absent.
    agent_configuration: AgentConfiguration | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    binding_digest: str = Field(pattern=DIGEST_PATTERN)

    @model_validator(mode="after")
    def validate_binding(self, info: ValidationInfo) -> DeepAgentExecutionBinding:
        if (self.runtime_unit is None) != (self.cognitive_session_namespace is None):
            raise ValueError(
                "Deep Agent runtime unit and cognitive session namespace are bound together"
            )
        unit = self.runtime_unit
        if unit is not None:
            if (
                unit.belllabs_run_id != self.run_id
                or unit.semantic_operation_id != self.operation_id
                or unit.semantic_attempt != self.operation_attempt
            ):
                raise ValueError("Deep Agent runtime unit does not match its binding identity")
            if self.cognitive_session_namespace != cognitive_session_namespace(
                unit, self.execution_generation
            ):
                raise ValueError(
                    "Deep Agent cognitive session namespace is not the unit generation's"
                )
        context_fields = {field.name: field for field in self.cognitive_context_schema.fields}
        if set(self.cognitive_context_values) != set(context_fields):
            raise ValueError("Deep Agent context values do not exactly match the frozen schema")
        for name, field in context_fields.items():
            value = self.cognitive_context_values[name]
            if (
                field.reference_only
                and isinstance(value, str)
                and not (value.startswith(("ref:", "handle:")))
            ):
                raise ValueError("reference-only cognitive context value contains material")
        contributed = {
            channel.name: channel
            for component in self.middleware
            for channel in component.contributed_channels
        }
        effective = {channel.name: channel for channel in self.cognitive_state_schema.channels}
        if any(effective.get(name) != channel for name, channel in contributed.items()):
            raise ValueError("middleware cognitive channels drift from the frozen state schema")
        if self.skills and not {"skills_metadata", "skills_load_errors"} <= set(effective):
            raise ValueError("Skills middleware channels are absent from the frozen state schema")
        attachment_keys = [
            (item.component_kind, item.component_digest, item.attachment_target)
            for item in self.intended_attachments
        ]
        if len(attachment_keys) != len(set(attachment_keys)):
            raise ValueError("Deep Agent attachment collision")
        hook_ids = [item.hook_id for item in self.hook_scripts]
        if len(hook_ids) != len(set(hook_ids)) or any(i.startswith("mc.") for i in hook_ids):
            raise ValueError("Deep Agent hook scripts need unique, non-kernel hook ids")
        options = self.provider_options
        if (
            options is not None
            and options.sandbox_backend is not None
            and options.sandbox_backend != self.sandbox.backend
        ):
            raise ValueError(
                "Deep Agent provider options pin a sandbox backend the bound sandbox lacks"
            )
        receipt = self.materialization_receipt
        if receipt is not None and receipt.lane_profile != "deep_agents":
            raise ValueError("Deep Agent binding carries another lane's materialization receipt")
        if (
            not (info.context or {}).get("allow_placeholder_digest")
            and self.content_digest() != self.binding_digest
        ):
            raise ValueError("Deep Agent execution binding digest mismatch")
        return self

    def seal(self) -> SealedLaneBinding:
        """This binding as the `deep_agents` lane's opaque bytes (only that lane unseals them)."""

        return SealedLaneBinding.seal_contract(
            self, lane_profile="deep_agents", schema_id=DEEP_AGENT_BINDING_SCHEMA
        )

    @classmethod
    def unseal(cls, binding: SealedLaneBinding) -> DeepAgentExecutionBinding:
        if binding.lane_profile != "deep_agents":
            raise ValueError(f"a {binding.lane_profile} binding is not a Deep Agents binding")
        return binding.unseal(cls, schema_ids=(DEEP_AGENT_BINDING_SCHEMA,))

    @classmethod
    def carried_by(cls, operation: CarriesLaneBinding) -> DeepAgentExecutionBinding | None:
        """The Deep Agents binding an operation carries, or `None` for another lane's bytes."""

        binding = operation.lane_binding
        if binding is None or binding.schema_id != DEEP_AGENT_BINDING_SCHEMA:
            return None
        decoded = cls.unseal(binding)
        dispatch = operation.lane_dispatch
        if dispatch is not None and decoded.lane_dispatch() != dispatch:
            raise ValueError(
                "the operation's lane dispatch differs from its sealed Deep Agents binding"
            )
        return decoded

    def verify_operation_envelope(
        self, operation: OperationExecutionRequest | OperationExecutionBinding
    ) -> None:
        """Refuse bytes that do not belong to this operation: its run, operation, attempt,
        configuration digest, control revision, workspace, grant, reservation and unit (the
        check the request validator made on the typed slot before OC-R2; the lane runs it at
        admission, `ValidatesOperationRequest`, and again wherever it decodes)."""

        if isinstance(operation, OperationExecutionRequest):
            run_id = operation.identity.run_id
            operation_id = operation.identity.operation_id
            operation_attempt = operation.identity.operation_attempt
        else:
            run_id, operation_id = operation.run_id, operation.operation_id
            operation_attempt = operation.operation_attempt
        if (
            self.run_id != run_id
            or self.operation_id != operation_id
            or self.operation_attempt != operation_attempt
            or self.erc_digest != operation.effective_configuration_digest
            or self.control_revision != operation.run_control_revision
            or self.workspace != operation.workspace
            or self.capability_grant != operation.capability_grant
            or self.reservation_id != operation.budget_reservation_id
            or (self.runtime_unit is not None and self.runtime_unit != operation.runtime_unit)
        ):
            raise ValueError("Deep Agent binding does not match the operation authority envelope")

    def lane_dispatch(self) -> LaneDispatch:
        """What the core schedules this attempt by: its worker queue, generation and class."""

        return LaneDispatch(
            task_queue=self.task_queue,
            execution_generation=self.execution_generation,
            heartbeat_class="deep_agent_async_children" if self.async_subagents else "deep_agent",
        )

    def content_digest(self) -> str:
        excluded = {"binding_digest"}
        if self.runtime_unit is None:
            excluded |= {"runtime_unit", "cognitive_session_namespace"}
        if not self.hook_scripts:
            excluded.add("hook_scripts")
        return sha256_digest(self.model_dump(mode="python", exclude=excluded))

    @classmethod
    def create(cls, **values: object) -> DeepAgentExecutionBinding:
        payload = dict(values)
        payload.pop("binding_digest", None)
        payload.setdefault("schema_version", "belllabs.deep-agent-binding.v1")
        payload.setdefault("silent_fallback", False)
        draft = cls.model_validate(
            {**payload, "binding_digest": PLACEHOLDER_DIGEST},
            context={"allow_placeholder_digest": True},
        )
        complete = draft.model_dump(mode="python", exclude={"binding_digest"})
        return cls(**complete, binding_digest=draft.content_digest())


ASYNC_CHILD_BINDING_SCHEMA: Final = "belllabs.async-child-binding.v1"


class SealedAsyncChildBinding(Contract):
    """One dynamic async child's exact configuration, sealed at launch (OVE-184, WP-S3).

    The lane adapter seals it from the child's ``mc.subagent_profile.v1`` (its own prompt,
    model, tools, Skills and MCP servers, or the parent's set for an inheriting child) into
    the parent's ``AsyncSubagentContract``; the governed spawn writes that contract to custody
    (``subordinate_contract``) before any provider call, and the Agent Server's sealed-child
    graph fetches it there under the caller's verified scope, recomputes this digest and
    materializes ``binding`` with the same materializer the worker uses. ``sealed_digest``
    covers the prompt text as well as the binding, and it is the identity the server stamps
    into the child's thread state.
    """

    schema_version: Literal["belllabs.async-child-binding.v1"] = ASYNC_CHILD_BINDING_SCHEMA
    child_name: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    shape: Literal["inherit", "seeded"]
    system_prompt_ref: ExactDefinitionRef
    system_prompt: str = Field(min_length=1, max_length=8192)
    binding: DeepAgentExecutionBinding
    sealed_digest: str = Field(pattern=DIGEST_PATTERN)

    @model_validator(mode="after")
    def validate_sealed_child(self, info: ValidationInfo) -> SealedAsyncChildBinding:
        if self.system_prompt_ref.kind.value != "prompt":
            raise ValueError("a sealed async child pins its prompt with an exact prompt ref")
        if sha256_digest(self.system_prompt) != self.system_prompt_ref.digest:
            raise ValueError("a sealed async child's prompt differs from its pinned digest")
        binding = self.binding
        if (
            binding.placement != "remote_langsmith_deployment"
            or binding.checkpoint_behavior != "remote_managed"
            or binding.reconnect_behavior != "remote_run_reconnect"
        ):
            raise ValueError("a sealed async child runs on a remote-managed Agent Server placement")
        if binding.async_subagents or binding.sync_subagents:
            raise ValueError("a sealed async child carries no children of its own")
        if (
            not (info.context or {}).get("allow_placeholder_digest")
            and self.content_digest() != self.sealed_digest
        ):
            raise ValueError("sealed async child binding digest mismatch")
        return self

    def content_digest(self) -> str:
        return sha256_digest(self.model_dump(mode="python", exclude={"sealed_digest"}))

    @classmethod
    def create(cls, **values: object) -> SealedAsyncChildBinding:
        payload = dict(values)
        payload.pop("sealed_digest", None)
        payload.setdefault("schema_version", ASYNC_CHILD_BINDING_SCHEMA)
        draft = cls.model_validate(
            {**payload, "sealed_digest": PLACEHOLDER_DIGEST},
            context={"allow_placeholder_digest": True},
        )
        complete = draft.model_dump(mode="python", exclude={"sealed_digest"})
        return cls(**complete, sealed_digest=draft.content_digest())


class NativeOperationExecutionPlacement(Contract):
    """Content-addressed placement authority for a native operation activity."""

    schema_version: Literal["belllabs.native-operation-placement.v1"] = (
        "belllabs.native-operation-placement.v1"
    )
    placement_id: str = Field(
        max_length=MAX_NATIVE_PLACEMENT_ID_LENGTH,
        pattern=r"^[a-z0-9][a-z0-9._:-]*$",
    )
    revision: int = Field(ge=1)
    execution_runtime: Literal["native"] = "native"
    task_queue: str = Field(
        min_length=1,
        max_length=MAX_TEMPORAL_TASK_QUEUE_LENGTH,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]*$",
    )
    qualification_refs: tuple[str, ...] = Field(min_length=1, max_length=64)
    placement_digest: str = Field(pattern=DIGEST_PATTERN)

    @model_validator(mode="after")
    def validate_digest(self, info: ValidationInfo) -> NativeOperationExecutionPlacement:
        if (
            not (info.context or {}).get("allow_placeholder_digest")
            and sha256_digest(self.model_dump(mode="python", exclude={"placement_digest"}))
            != self.placement_digest
        ):
            raise ValueError("native operation placement digest mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> NativeOperationExecutionPlacement:
        payload = dict(values)
        payload.pop("placement_digest", None)
        payload.setdefault("schema_version", "belllabs.native-operation-placement.v1")
        payload.setdefault("execution_runtime", "native")
        draft = cls.model_validate(
            {**payload, "placement_digest": PLACEHOLDER_DIGEST},
            context={"allow_placeholder_digest": True},
        )
        complete = draft.model_dump(mode="python", exclude={"placement_digest"})
        return cls(**complete, placement_digest=sha256_digest(complete))


class OperationExecutionRequest(Contract):
    identity: OperationAttemptIdentity
    request_scope: str = Field(min_length=1)
    effective_configuration_digest: str = Field(pattern=DIGEST_PATTERN)
    run_control_revision: int = Field(ge=1)
    operation_contract_ref: str = Field(min_length=1)
    prompt_segments: tuple[PromptSegment, ...] = Field(min_length=1, max_length=64)
    model_policy: ModelPolicy
    tools: tuple[ToolBinding, ...] = ()
    mcp_servers: tuple[MCPServerBinding, ...] = ()
    skills: tuple[ImmutableAssetBinding, ...] = ()
    plugins: tuple[ImmutableAssetBinding, ...] = ()
    output_schema: StructuredOutputBinding | None = None
    guardrails: tuple[GuardrailBinding, ...] = ()
    delegations: tuple[DelegationBinding, ...] = ()
    delegation_ceiling: DelegationCeiling = Field(default_factory=DelegationCeiling)
    session_id: str | None = Field(default=None, min_length=1, max_length=256)
    agent_profile_ref: ExactDefinitionRef
    capability_grant: CapabilityGrant
    workspace: WorkspaceContract
    secret_refs: tuple[SecretRef, ...] = ()
    unsupported_policies: tuple[UnsupportedPolicy, ...] = ()
    # The lane's runtime, derived from the lane registry by the template author.
    execution_runtime: ExecutionRuntime = "native"
    native_placement: NativeOperationExecutionPlacement | None = None
    # FT-G1 (SPEC-07 section 3): the Lane Profile (absent: `deep_agents`). OC-R2 (ADR-0063):
    # one sealed lane binding replaces the three typed slots; only its lane reads the bytes,
    # the core moves it by digest and schedules by the dispatch facts the lane stated.
    lane_profile: LaneProfileName | None = Field(default=None, exclude_if=_absent)
    lane_binding: SealedLaneBinding | None = Field(default=None, exclude_if=_absent)
    lane_dispatch: LaneDispatch | None = Field(default=None, exclude_if=_absent)
    # Sprint OC WI-02 (ADR-0061): the receiver's admitted transfer selection; the one
    # materializer seals it into the receiver's plan. Absent: the operation receives no inputs
    # beyond its host state, and the request digest is unchanged.
    transfer: TransferSelection | None = Field(default=None, exclude_if=_absent)
    budget_reservation_id: str = Field(min_length=1)
    budget_limits: dict[str, int]
    tracing_policy_ref: str = Field(min_length=1)
    sensitive_data_policy_ref: str = Field(min_length=1)
    snapshot_policy_ref: str = Field(min_length=1)
    prior_binding_id: str | None = None
    requested_at: AwareDatetime
    idempotency_key: str = Field(min_length=1)
    # REQ-CP-EXEC-013: the structured runtime unit travels beside the wire identity.
    runtime_unit: RuntimeUnitIdentity | None = None

    @model_validator(mode="after")
    def capabilities_cover_exact_bindings(self) -> OperationExecutionRequest:
        unit = self.runtime_unit
        if unit is not None and (
            unit.request_scope != self.request_scope
            or unit.belllabs_run_id != self.identity.run_id
            or unit.semantic_operation_id != self.identity.operation_id
            or unit.semantic_attempt != self.identity.operation_attempt
        ):
            raise ValueError("runtime unit does not match the operation attempt identity")
        if (self.execution_runtime == "native") != (self.native_placement is not None):
            raise ValueError("native execution requires exactly one canonical native placement")
        # The lane verifies its own bytes against this envelope (identity, configuration and
        # control revision, workspace, grant, reservation, unit) when it decodes them.
        _verify_lane_pairing(
            self.execution_runtime, self.lane_profile, self.lane_binding, self.lane_dispatch
        )
        if not {tool.tool_id for tool in self.tools} <= self.capability_grant.tool_ids:
            raise ValueError("tool binding exceeds the operation capability grant")
        if (
            not {server.server_id for server in self.mcp_servers}
            <= self.capability_grant.mcp_server_ids
        ):
            raise ValueError("MCP binding exceeds the operation capability grant")
        ceiling = self.delegation_ceiling
        if len(self.delegations) > ceiling.max_delegations:
            raise ValueError("delegations exceed the operation delegation count ceiling")
        if self.delegations and ceiling.max_depth < 1:
            raise ValueError("delegations exceed the operation delegation depth ceiling")
        if self.delegations and ceiling.max_concurrency < 1:
            raise ValueError("delegations exceed the operation concurrency ceiling")
        for delegation in self.delegations:
            agent = delegation.agent
            if delegation.mode not in ceiling.allowed_modes:
                raise ValueError("delegation mode exceeds the operation delegation ceiling")
            if agent.model_policy.model not in ceiling.allowed_models:
                raise ValueError("delegate model exceeds the operation delegation ceiling")
            if not agent.capability_grant.capabilities <= self.capability_grant.capabilities:
                raise ValueError("delegate capabilities exceed operation authority")
            if not agent.capability_grant.tool_ids <= (
                self.capability_grant.tool_ids & ceiling.tool_ids
            ):
                raise ValueError("delegate tools exceed intersected delegation authority")
            if not agent.capability_grant.mcp_server_ids <= (
                self.capability_grant.mcp_server_ids & ceiling.mcp_server_ids
            ):
                raise ValueError("delegate MCP servers exceed intersected delegation authority")
            if not agent.capability_grant.data_scope_refs <= (
                self.capability_grant.data_scope_refs & ceiling.data_scope_refs
            ):
                raise ValueError("delegate data scope exceeds intersected delegation authority")
            if not agent.capability_grant.network_hosts <= (
                self.capability_grant.network_hosts & ceiling.network_hosts
            ):
                raise ValueError("delegate network access exceeds intersected delegation authority")
            if any(
                amount > self.budget_limits.get(dimension, 0)
                or amount > ceiling.budget_limits.get(dimension, 0)
                for dimension, amount in delegation.budget_limits.items()
            ):
                raise ValueError("delegate budget exceeds intersected delegation authority")
        return self


class OperationExecutionBinding(Contract):
    binding_id: str = Field(min_length=1)
    semantic_attempt_key: str = Field(min_length=1)
    request_fingerprint: str = Field(pattern=DIGEST_PATTERN)
    request_scope: str
    run_id: str
    operation_id: str
    operation_attempt: int = Field(ge=1)
    prior_binding_id: str | None = None
    effective_configuration_digest: str = Field(pattern=DIGEST_PATTERN)
    run_control_revision: int = Field(ge=1)
    operation_contract_ref: str
    prompt_sources: tuple[tuple[str, int, PromptTrustClass, str], ...]
    model_policy: ModelPolicy
    tools: tuple[ToolBinding, ...]
    mcp_servers: tuple[MCPServerBinding, ...]
    skills: tuple[ImmutableAssetBinding, ...]
    plugins: tuple[ImmutableAssetBinding, ...]
    output_schema: StructuredOutputBinding | None = None
    guardrails: tuple[GuardrailBinding, ...] = ()
    delegations: tuple[DelegationBinding, ...] = ()
    delegation_ceiling: DelegationCeiling = Field(default_factory=DelegationCeiling)
    session_id: str | None = None
    agent_profile_ref: ExactDefinitionRef
    capability_grant: CapabilityGrant
    workspace: WorkspaceContract
    secret_refs: tuple[SecretRef, ...]
    budget_reservation_id: str
    budget_limits: dict[str, int]
    tracing_policy_ref: str
    sensitive_data_policy_ref: str
    snapshot_policy_ref: str
    applied_degradations: tuple[str, ...] = ()
    execution_runtime: ExecutionRuntime = "native"
    native_placement: NativeOperationExecutionPlacement | None = None
    lane_profile: LaneProfileName | None = Field(default=None, exclude_if=_absent)
    lane_binding: SealedLaneBinding | None = Field(default=None, exclude_if=_absent)
    lane_dispatch: LaneDispatch | None = Field(default=None, exclude_if=_absent)
    transfer: TransferSelection | None = Field(default=None, exclude_if=_absent)
    side_effect_key: str
    bound_at: AwareDatetime
    runtime_unit: RuntimeUnitIdentity | None = None

    @model_validator(mode="after")
    def exact_runtime_placement(self) -> OperationExecutionBinding:
        if (self.execution_runtime == "native") != (self.native_placement is not None):
            raise ValueError("native binding runtime placement is not exact")
        _verify_lane_pairing(
            self.execution_runtime, self.lane_profile, self.lane_binding, self.lane_dispatch
        )
        return self


class MaterializedWorkspace(Contract):
    workspace_id: str
    provider: str
    runtime_digest: str = Field(pattern=DIGEST_PATTERN)
    image_digest: str = Field(pattern=DIGEST_PATTERN)
    mount_manifest_digest: str = Field(pattern=DIGEST_PATTERN)
    namespace_id: str | None = None
    manifest_revision: int | None = Field(default=None, ge=1)
    materialization_manifest: WorkspaceMaterializationManifest | None = None


class RuntimeInvocation(Contract):
    binding: OperationExecutionBinding
    prompt_segments: tuple[PromptSegment, ...]
    workspace: MaterializedWorkspace
    resolved_secret_names: tuple[str, ...] = ()
    # REQ-CP-DA-016/017: namespace, pinned expected source, and stamps for cognition.
    checkpoint_plan: CheckpointInvocationPlan | None = None
    # FT-F2 (cancel_and_replace): the replacement turn's injected item, one more admitted
    # user message on the same session after the interrupted turn's durable state.
    follow_up: PromptSegment | None = Field(default=None, exclude_if=_absent)
    # A queued native follow-up is a new Session Turn, without interrupting the prior one.
    # The durable delivery key also identifies its native input for crash-safe replay.
    follow_up_kind: Literal["queued_instruction"] | None = Field(default=None, exclude_if=_absent)
    follow_up_key: str | None = Field(default=None, min_length=1, exclude_if=_absent)
    follow_up_prior_usage: dict[str, int] = Field(
        default_factory=dict, exclude_if=lambda value: not value
    )
    follow_up_source_checkpoint: QualifiedCheckpointKey | None = Field(
        default=None, exclude_if=_absent
    )
    # W1 D38/D41: the authored run budget inside the turn. `run_budget_dimensions` are the
    # run's declared, applicable in-turn dimensions (`IN_TURN_RUN_DIMENSIONS`) the turn's
    # usage is charged on even when its own reservation does not bound them (a Goal Loop
    # iteration reserves `goal.iterations`). `run_budget_remaining` is, per bounded one, what
    # the run's hard cap leaves for this turn; the lane stops the turn once its spend
    # exceeds it. Both are empty when the authority cannot read the run budget.
    run_budget_dimensions: tuple[str, ...] = Field(default=(), exclude_if=lambda value: not value)
    run_budget_remaining: dict[str, int] = Field(
        default_factory=dict, exclude_if=lambda value: not value
    )


# W1 D41: the usage dimensions a lane turn spends and the run budget bounds inside the turn.
IN_TURN_RUN_DIMENSIONS: tuple[str, ...] = ("model.turns", "tokens.total", "tool.calls.total")


class RuntimeUsage(Contract):
    amounts: dict[str, int] = Field(default_factory=dict)
    pending_external_amounts: dict[str, int] = Field(default_factory=dict)


class RuntimeResult(Contract):
    output_text: str
    structured_output: dict[str, object] | None = None
    output_refs: tuple[str, ...] = ()
    usage: RuntimeUsage = Field(default_factory=RuntimeUsage)
    provider_run_id: str | None = None
    event_payloads: tuple[dict[str, object], ...] = ()
    # REQ-CP-DA-017: captured source/result checkpoint of the invocation, keys only.
    checkpoint: CheckpointCapture | None = None
    # P1 turn 4 (`mc.cognition_point.v1`): every point of the invocation's own lineage the
    # lane observed (a Deep Agents root checkpoint per step), keys and redacted facts only.
    # The settlement writes them with the transition; a lane without points reports none.
    cognition_points: tuple[CognitionPointObservation, ...] = ()
    # W1 D41: the lane ended the turn because a budget dimension was exhausted (dimension ->
    # `{"limit", "spent"}`). The attempt settles `failed/budget_exceeded`, never `completed`.
    budget_stop: dict[str, dict[str, int]] = Field(
        default_factory=dict, exclude_if=lambda value: not value
    )


class RuntimeEventEnvelope(Contract):
    schema_version: Literal["1"] = "1"
    event_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    request_scope: str = Field(min_length=1)
    binding_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    operation_id: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    occurred_at: AwareDatetime
    durable: bool = True
    payload: dict[str, object] = Field(default_factory=dict)


class RuntimeApprovalRequest(Contract):
    approval_id: str = Field(min_length=1)
    request_scope: str = Field(min_length=1)
    binding_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    operation_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    arguments_digest: str = Field(pattern=DIGEST_PATTERN)
    argument_names: tuple[str, ...] = ()
    requested_at: AwareDatetime
    expires_at: AwareDatetime


class RuntimeApprovalDecision(Contract):
    approval_id: str = Field(min_length=1)
    request_scope: str = Field(min_length=1)
    binding_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    decision: Literal["approved", "rejected"]
    reason: str | None = Field(default=None, max_length=2_000)
    decided_at: AwareDatetime


class ReusedResultRef(Contract):
    """REQ-CP-EXEC-012: a fork-derived unit settled by an immutable source result.

    The derived run references the reused result; it never re-settles it in the source run.
    """

    fork_request_id: str = Field(min_length=1, max_length=512)
    source_run_id: str = Field(min_length=1, max_length=512)
    source_unit_key: str = Field(pattern=r"^bl-unit-v1:[0-9a-f]{64}$")
    source_settlement_id: str = Field(min_length=1, max_length=512)
    source_result_manifest_ref: str = Field(min_length=1, max_length=1024)
    source_result_manifest_digest: str = Field(pattern=DIGEST_PATTERN)


class OperationSettlement(Contract):
    settlement_id: str
    binding_id: str
    status: Literal["completed", "failed", "cancelled", "timed_out"]
    output_text: str = ""
    structured_output: dict[str, object] | None = None
    output_refs: tuple[str, ...] = ()
    usage: RuntimeUsage = Field(default_factory=RuntimeUsage)
    provider_run_id: str | None = None
    event_payloads: tuple[dict[str, object], ...] = ()
    failure_code: str | None = None
    failure_message: str | None = None
    settled_at: AwareDatetime
    # REQ-CP-DA-017: the settlement references the result key of the transition it settles.
    checkpoint_transition_id: str | None = None
    result_checkpoint: QualifiedCheckpointKey | None = None
    # RRM-004: the digest-bound address of the output payload (`output_text`,
    # `structured_output`). The result manifest excludes the payload itself but commits to
    # it, so a settled replay or a settlement recovered from the manifest returns the same
    # output unchanged.
    output_payload_ref: str | None = None
    output_payload_digest: str | None = Field(default=None, pattern=DIGEST_PATTERN)
    output_payload_size_bytes: int | None = Field(default=None, ge=1)
    # RRM-006: present only on a fork-derived unit settled by a reused source result.
    reused_result: ReusedResultRef | None = None

    @model_validator(mode="after")
    def output_payload_address_is_exact(self) -> OperationSettlement:
        fields = (
            self.output_payload_ref,
            self.output_payload_digest,
            self.output_payload_size_bytes,
        )
        if any(value is not None for value in fields) and not all(
            value is not None for value in fields
        ):
            raise ValueError("output payload ref, digest, and size form one exact address")
        if self.reused_result is not None and (
            self.status != "completed"
            or self.checkpoint_transition_id is not None
            or self.result_checkpoint is not None
            or self.provider_run_id is not None
            or self.event_payloads
            or any(self.usage.amounts.values())
            or any(self.usage.pending_external_amounts.values())
        ):
            raise ValueError(
                "a reused result settles completed, with no cognition, provider run, "
                "events, or usage of its own"
            )
        return self


class OperationExecutionResult(Contract):
    binding_id: str
    semantic_attempt_key: str
    # `waiting` (Sprint OC WI-04): cognition completed and its result is saved; its settlement
    # waits (typed reason in `settlement_wait`). Nothing is settled; the operation workflow
    # waits durably and runs the boundary again, which consumes the saved result.
    status: Literal["completed", "failed", "cancelled", "timed_out", "in_doubt", "waiting"]
    output_text: str = ""
    structured_output: dict[str, object] | None = None
    output_refs: tuple[str, ...] = ()
    usage: RuntimeUsage = Field(default_factory=RuntimeUsage)
    failure_code: str | None = None
    failure_message: str | None = None
    unit_key: str | None = None
    checkpoint_transition_id: str | None = None
    result_checkpoint: QualifiedCheckpointKey | None = None
    # RRM-004: the typed `in_doubt` incident awaiting operator `reconcile_unit`.
    reconciliation_incident_id: str | None = None
    # WI-04: `mc.invocation_settlement.v1` `SettlementWait` of a `waiting` result (excluded when
    # absent, so every earlier result payload keeps its bytes).
    settlement_wait: dict[str, object] | None = Field(default=None, exclude_if=lambda v: v is None)


class AsyncChildCancellationRecord(Contract):
    """RRM-008 (REQ-CP-EXEC-008 step 4): one async child the cancellation saga reached.

    The provider's acknowledgement or its absence is recorded, never assumed; a child whose
    usage the provider could not attribute leaves its parent effect pending (REQ-CP-RUN-009)
    until a privileged usage reconciliation settles it.
    """

    schema_version: Literal["belllabs.async-child-cancellation.v1"] = (
        "belllabs.async-child-cancellation.v1"
    )
    child_execution_id: str = Field(min_length=1)
    # The child's effect claim in the parent run (`async_subagent.child`), whose pending
    # usage blocks the parent's terminal settlement until reconciled.
    effect_id: str = Field(min_length=1)
    lifecycle: AsyncSubagentLifecycle
    cancellation_receipt: Literal["provider_acknowledged", "ambiguous", "not_requested"]
    usage_disposition: Literal["settled", "pending_usage", "unsettled"]
    result_decision: str | None = None


# The runtimes whose units are Session Lanes: they always run through `lane.turn` segments.
SESSION_LANE_RUNTIMES: frozenset[str] = frozenset({"cursor", "claude", "codex"})


class OperationWorkflowRequest(Contract):
    """Typed durable wrapper for exactly one semantic operation attempt."""

    # W1 D10: a run-control contract that embeds this request leaves it to these bounds
    # (segment, sealed-binding and 2,000,000-byte payload ceilings) instead of its own 8192
    # character string limit (`domain/policies/contracts._run_control_view`).
    bounds_own_payload: ClassVar[bool] = True

    schema_version: Literal["belllabs.operation-workflow.v2"] = "belllabs.operation-workflow.v2"
    semantic_attempt_id: str = Field(
        min_length=1,
        max_length=MAX_OPERATION_SEMANTIC_ATTEMPT_ID_LENGTH,
    )
    execution_generation: int = Field(default=1, ge=1)
    operation_kind: Literal["bound_operation"]
    operation: OperationExecutionRequest
    timeout_seconds: int = Field(default=300, ge=1, le=86_400)
    # RRM-008 (REQ-CP-EXEC-008 step 3): the cognitive Activity's heartbeat timeout. A lost
    # worker is detected after it (not after `timeout_seconds`) and a cancel reaches the
    # running Activity through its heartbeat. Absent in recorded histories: the default.
    heartbeat_timeout_seconds: int = Field(default=30, ge=1, le=3_600)
    message_cursor: int = Field(default=0, ge=0)
    effect_frontier: tuple[EffectFrontierItem, ...] = Field(
        default=(),
        max_length=MAX_EFFECT_FRONTIER_ITEMS,
    )
    active_async_child_ids: tuple[AsyncChildId, ...] = Field(
        default=(),
        max_length=MAX_ACTIVE_ASYNC_CHILDREN,
    )
    # REQ-CP-EXEC-015: the family passes its Search Attribute policy to the operation
    # child; absent means `disabled` (time-skipping tests and captured-history replay).
    search_attribute_policy: SearchAttributePolicy = "disabled"
    # FT-G2 (SPEC-07 section 4.2): `lane.turn` segment bounds. Present (or a `cursor`
    # operation) means the segment loop drives the unit; absent keeps `operation.execute`.
    segments: LaneSegmentBounds | None = Field(default=None, exclude_if=_absent)
    # FT-G2 (SPEC-07 section 4.4): command ids already applied by earlier runs of this
    # workflow id, and where the segment loop stands, carried across continue-as-new.
    seen_cmds: tuple[str, ...] = Field(default=(), max_length=4_096, exclude_if=_empty)
    lane_resume: LaneResumePoint | None = Field(default=None, exclude_if=_absent)
    # MP-05: the deployment's finite capacity-wait bounds for provider limit responses;
    # absent in recorded histories (the defaults apply, exactly as before).
    capacity_wait: LimitWaitPolicy | None = Field(default=None, exclude_if=_absent)
    # Sprint OC WI-04: the saved-result settlement wait carried across continue-as-new (the
    # new run sleeps on it before the next pass), and the bound of settlement waits one run
    # takes before it continues as new (absent: 500; the server's suggestion applies too).
    settlement_wait: dict[str, object] | None = Field(default=None, exclude_if=_absent)
    settlement_waits_per_run: int | None = Field(default=None, ge=1, exclude_if=_absent)

    @property
    def segment_driven(self) -> bool:
        """Whether the unit runs through `lane.turn` segments (always for the Session Lane
        runtimes `cursor`, `claude` and `codex`)."""

        return (
            self.segments is not None or self.operation.execution_runtime in SESSION_LANE_RUNTIMES
        )

    @model_validator(mode="after")
    def exact_bound_operation(self) -> OperationWorkflowRequest:
        if self.semantic_attempt_id != self.operation.identity.semantic_key:
            raise ValueError(
                "operation workflow semantic attempt must match the bound execution request"
            )
        dispatch = self.operation.lane_dispatch
        if dispatch is not None and self.execution_generation != dispatch.execution_generation:
            raise ValueError(
                "operation workflow generation must match the sealed lane binding's dispatch"
            )
        if len(set(self.active_async_child_ids)) != len(self.active_async_child_ids):
            raise ValueError("active async child identities must be unique")
        if len(self.model_dump_json().encode("utf-8")) > MAX_OPERATION_WORKFLOW_PAYLOAD_BYTES:
            raise ValueError("operation workflow payload exceeds 2,000,000 bytes")
        return self

    @property
    def activity_task_queue(self) -> str:
        dispatch = self.operation.lane_dispatch
        if dispatch is not None and dispatch.task_queue is not None:
            # The worker queue serving the lane's activities, as the lane's sealing stated it.
            return dispatch.task_queue
        placement = self.operation.native_placement
        if placement is None:
            raise ValueError("operation execution has no exact activity placement")
        return placement.task_queue

    @property
    def workflow_id(self) -> str:
        return f"operation/{self.semantic_attempt_id}"


class OperationWorkflowResult(Contract):
    # W1 D10: bounded by its own contract and the Temporal payload ceiling; a run-control
    # contract embedding it (the GoalDirected reconciliation request) does not re-walk it,
    # so a long provider answer cannot make that request undecodable.
    bounds_own_payload: ClassVar[bool] = True
    schema_version: Literal["belllabs.operation-result.v1"] = "belllabs.operation-result.v1"
    semantic_attempt_id: str
    execution_generation: int = Field(ge=1)
    disposition: Literal["completed", "cancelled", "failed", "in_doubt"]
    result: dict[str, object] = Field(default_factory=dict)
    message_cursor: int = Field(ge=0)
    effect_frontier: tuple[EffectFrontierItem, ...] = Field(
        default=(),
        max_length=MAX_EFFECT_FRONTIER_ITEMS,
    )
    active_async_child_ids: tuple[AsyncChildId, ...] = Field(
        default=(),
        max_length=MAX_ACTIVE_ASYNC_CHILDREN,
    )


class ArtifactCheckEvidence(Contract):
    check_id: str = Field(min_length=1)
    required: bool = True
    outcome: Literal["passed", "failed", "not_applicable"]
    evidence_ref: str = Field(min_length=1)


class ArtifactPromotionDeclaration(Contract):
    namespace_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    output_slot: str = Field(min_length=1)
    logical_path: str = Field(min_length=1)
    owner: WorkspaceOwner
    candidate_id: str = Field(min_length=1)
    content_digest: str = Field(pattern=DIGEST_PATTERN)
    media_type: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)
    permission_ref: str = Field(min_length=1)
    permission_outcome: Literal[
        "allowed", "allowed_with_conditions", "requires_review", "unknown", "prohibited"
    ]
    output_contract_ref: str = Field(min_length=1)
    checks: tuple[ArtifactCheckEvidence, ...] = ()
    requested_at: AwareDatetime

    @field_validator("checks")
    @classmethod
    def check_identities_are_unique(
        cls, value: tuple[ArtifactCheckEvidence, ...]
    ) -> tuple[ArtifactCheckEvidence, ...]:
        identities = [item.check_id for item in value]
        if len(identities) != len(set(identities)):
            raise ValueError("artifact check identities must be unique")
        return value


class ArtifactPromotionRequest(ArtifactPromotionDeclaration):
    request_scope: str = Field(min_length=1)
    binding_id: str = Field(min_length=1)
    requested_at: AwareDatetime


class ArtifactPromotionState(StrEnum):
    CANDIDATE = "candidate"
    PAYLOAD_STAGED = "payload_staged"
    METADATA_COMMITTED = "metadata_committed"
    ADMITTED = "admitted"
    REJECTED = "rejected"
    RECONCILIATION_REQUIRED = "reconciliation_required"


class ArtifactMetadataRevision(Contract):
    promotion_id: str = Field(min_length=1)
    artifact_id: str = Field(min_length=1)
    intent_key: str = Field(min_length=1)
    promotion_identity: str = Field(pattern=DIGEST_PATTERN)
    revision: int = Field(ge=1)
    state: ArtifactPromotionState
    request_scope: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    semantic_attempt_key: str = Field(min_length=1)
    producer_binding_id: str = Field(min_length=1)
    namespace_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    output_slot: str = Field(min_length=1)
    logical_path: str = Field(min_length=1)
    owner: WorkspaceOwner
    candidate_id: str = Field(min_length=1)
    content_digest: str = Field(pattern=DIGEST_PATTERN)
    media_type: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)
    permission_ref: str = Field(min_length=1)
    permission_outcome: Literal[
        "allowed", "allowed_with_conditions", "requires_review", "unknown", "prohibited"
    ]
    output_contract_ref: str = Field(min_length=1)
    checks: tuple[ArtifactCheckEvidence, ...] = ()
    object_ref: str | None = None
    manifest_revision: int | None = Field(default=None, ge=1)
    durable_reference: str | None = None
    reason: str | None = None
    recorded_at: AwareDatetime


class PromotedArtifact(Contract):
    artifact_id: str
    content_digest: str = Field(pattern=DIGEST_PATTERN)
    object_ref: str
    metadata_revision: int = Field(ge=1)
    manifest_revision: int = Field(ge=1)
    durable_reference: str = Field(min_length=1)
    status: Literal["admitted"]


class ArtifactPromotionPlan(Contract):
    namespace_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    output_slot: str = Field(min_length=1)
    logical_path: str = Field(min_length=1)
    owner: WorkspaceOwner
    permission_ref: str = Field(min_length=1)
    permission_outcome: Literal[
        "allowed", "allowed_with_conditions", "requires_review", "unknown", "prohibited"
    ]
    output_contract_ref: str = Field(min_length=1)
    checks: tuple[ArtifactCheckEvidence, ...] = ()


class CapturedWorkspaceCandidate(Contract):
    namespace_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    output_slot: str = Field(min_length=1)
    logical_path: str = Field(min_length=1)
    owner: WorkspaceOwner
    candidate_id: str = Field(min_length=1)
    content_digest: str = Field(pattern=DIGEST_PATTERN)
    media_type: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)


class GenericArtifactWorkflowRequest(Contract):
    request_scope: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    operation: OperationExecutionRequest
    promotion: ArtifactPromotionPlan

    @model_validator(mode="after")
    def operation_and_promotion_share_run_workspace(
        self,
    ) -> GenericArtifactWorkflowRequest:
        if (
            self.operation.request_scope != self.request_scope
            or self.operation.identity.run_id != self.run_id
            or self.operation.workspace.namespace_id != self.promotion.namespace_id
            or self.operation.workspace.workspace_id != self.promotion.workspace_id
        ):
            raise ValueError("generic artifact workflow inputs do not share one run workspace")
        return self


class GenericArtifactWorkflowResult(Contract):
    workflow_id: str = Field(min_length=1)
    operation: OperationExecutionResult
    artifact: PromotedArtifact


class WorkspaceOwnerKind(StrEnum):
    RUN = "run"
    STAGE = "stage"
    CYCLE = "cycle"
    ITERATION = "iteration"
    EVALUATOR = "evaluator"
    AGENT = "agent"
    DELEGATE = "delegate"


class WorkspaceOwner(Contract):
    kind: WorkspaceOwnerKind
    owner_id: str = Field(min_length=1)
    parent_owner_id: str | None = None

    @model_validator(mode="after")
    def delegates_require_parent(self) -> WorkspaceOwner:
        if self.kind == WorkspaceOwnerKind.DELEGATE and self.parent_owner_id is None:
            raise ValueError("delegate workspace owners require an explicit parent")
        return self


class WorkspaceSlotBinding(Contract):
    slot_name: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    logical_path: str = Field(pattern=r"^/[A-Za-z0-9._/-]+$")
    access: Literal["read_only", "exclusive_write"]
    owner: WorkspaceOwner
    durable_ref: str | None = None
    content_digest: str | None = Field(default=None, pattern=DIGEST_PATTERN)
    sensitive: bool = Field(default=False, exclude_if=_empty)

    @model_validator(mode="after")
    def mounted_inputs_are_complete(self) -> WorkspaceSlotBinding:
        if self.access == "read_only":
            if self.durable_ref is None or self.content_digest is None:
                raise ValueError("read-only slots require a durable reference and digest")
        elif self.durable_ref is not None or self.content_digest is not None:
            raise ValueError("writable slots cannot declare a durable input")
        if ".." in self.logical_path.split("/"):
            raise ValueError("logical workspace paths cannot traverse parents")
        return self


class DurableInputManifestEntry(Contract):
    kind: Literal["durable_input"] = "durable_input"
    entry_id: str = Field(min_length=1)
    slot_name: str = Field(min_length=1)
    logical_path: str = Field(min_length=1)
    owner: WorkspaceOwner
    durable_ref: str = Field(min_length=1)
    content_digest: str = Field(pattern=DIGEST_PATTERN)
    read_only: Literal[True] = True


class LocalCandidateManifestEntry(Contract):
    kind: Literal["local_candidate"] = "local_candidate"
    entry_id: str = Field(min_length=1)
    slot_name: str = Field(min_length=1)
    logical_path: str = Field(min_length=1)
    owner: WorkspaceOwner
    candidate_id: str = Field(min_length=1)
    content_digest: str = Field(pattern=DIGEST_PATTERN)
    media_type: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)


class PromotedArtifactManifestEntry(Contract):
    kind: Literal["promoted_artifact"] = "promoted_artifact"
    entry_id: str = Field(min_length=1)
    slot_name: str = Field(min_length=1)
    logical_path: str = Field(min_length=1)
    owner: WorkspaceOwner
    candidate_id: str = Field(min_length=1)
    artifact_id: str = Field(min_length=1)
    artifact_metadata_revision: int = Field(ge=1)
    content_digest: str = Field(pattern=DIGEST_PATTERN)


class StaleManifestEntry(Contract):
    kind: Literal["stale"] = "stale"
    entry_id: str = Field(min_length=1)
    slot_name: str = Field(min_length=1)
    logical_path: str = Field(min_length=1)
    owner: WorkspaceOwner
    superseded_entry_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)


WorkspaceMaterializationEntry = Annotated[
    DurableInputManifestEntry
    | LocalCandidateManifestEntry
    | PromotedArtifactManifestEntry
    | StaleManifestEntry,
    Field(discriminator="kind"),
]


class WorkspaceMaterializationManifest(Contract):
    manifest_id: str = Field(min_length=1)
    namespace_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    template_ref: ExactDefinitionRef
    workflow_contract_digest: str = Field(pattern=DIGEST_PATTERN)
    slots: tuple[WorkspaceSlotBinding, ...] = Field(min_length=1)
    entries: tuple[WorkspaceMaterializationEntry, ...]
    prior_manifest_digest: str | None = Field(default=None, pattern=DIGEST_PATTERN)
    manifest_digest: str = Field(pattern=DIGEST_PATTERN)
    created_at: AwareDatetime

    @model_validator(mode="after")
    def governed_paths_are_unique(self) -> WorkspaceMaterializationManifest:
        paths = [entry.logical_path for entry in self.entries if entry.kind != "stale"]
        if len(paths) != len(set(paths)):
            raise ValueError("current manifest entries require unique logical paths")
        return self


class WorkspaceMaterializationRequest(Contract):
    namespace_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    template_ref: ExactDefinitionRef
    workflow_contract_digest: str = Field(pattern=DIGEST_PATTERN)
    slots: tuple[WorkspaceSlotBinding, ...] = Field(min_length=1)
    runtime_digest: str = Field(pattern=DIGEST_PATTERN)
    image_digest: str = Field(pattern=DIGEST_PATTERN)
    created_at: AwareDatetime

    @model_validator(mode="after")
    def slots_are_unique_and_exclusive(self) -> WorkspaceMaterializationRequest:
        names = [slot.slot_name for slot in self.slots]
        paths = [slot.logical_path for slot in self.slots]
        if len(names) != len(set(names)) or len(paths) != len(set(paths)):
            raise ValueError("workspace slot names and logical paths must be unique")
        if any(
            _workspace_paths_overlap(left, right)
            for index, left in enumerate(paths)
            for right in paths[index + 1 :]
        ):
            raise ValueError("workspace slot paths cannot overlap")
        writable_owners = [
            (slot.logical_path, slot.owner.owner_id)
            for slot in self.slots
            if slot.access == "exclusive_write"
        ]
        if len(writable_owners) != len(set(writable_owners)):
            raise ValueError("writable workspace slots require one owner")
        return self


def _workspace_paths_overlap(left: str, right: str) -> bool:
    normalized_left = left.rstrip("/")
    normalized_right = right.rstrip("/")
    return (
        normalized_left == normalized_right
        or normalized_left.startswith(normalized_right + "/")
        or normalized_right.startswith(normalized_left + "/")
    )


class SnapshotCreationReason(StrEnum):
    REPRODUCIBILITY = "reproducibility"
    DEBUGGING = "debugging"
    RESUMPTION = "resumption"
    AUDIT = "audit"
    FAILURE = "failure"
    CYCLE = "cycle"


class SnapshotCapabilityShape(Contract):
    """Non-secret historical shape; never an authority grant."""

    capabilities: frozenset[str] = frozenset()
    tool_ids: frozenset[str] = frozenset()
    mcp_server_ids: frozenset[str] = frozenset()
    data_scope_refs: frozenset[str] = frozenset()
    network_hosts: frozenset[str] = frozenset()
    network_policy: Literal["none", "allowlisted"] = "none"


class SnapshotRetention(Contract):
    policy_ref: str = Field(min_length=1)
    retain_until: AwareDatetime | None = None
    deletion_protected: bool = False


class SnapshotPayloadAddress(Contract):
    object_ref: str = Field(min_length=1)
    content_digest: str = Field(pattern=DIGEST_PATTERN)
    size_bytes: int = Field(ge=0)
    media_type: str = Field(min_length=1)


class SandboxSnapshotCreateRequest(Contract):
    snapshot_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    request_scope: str = Field(min_length=1)
    source_namespace_id: str = Field(min_length=1)
    source_workspace_id: str = Field(min_length=1)
    parent_snapshot_id: str | None = Field(default=None, min_length=1)
    provider: str = Field(min_length=1)
    reason: SnapshotCreationReason
    producer_binding_id: str = Field(min_length=1)
    snapshot_policy_ref: str = Field(min_length=1)
    runtime_digest: str = Field(pattern=DIGEST_PATTERN)
    image_digest: str = Field(pattern=DIGEST_PATTERN)
    package_digest: str = Field(pattern=DIGEST_PATTERN)
    environment_digest: str = Field(pattern=DIGEST_PATTERN)
    workspace_contract_digest: str = Field(pattern=DIGEST_PATTERN)
    mount_manifest_digest: str = Field(pattern=DIGEST_PATTERN)
    capability_shape: SnapshotCapabilityShape
    retention: SnapshotRetention
    created_at: AwareDatetime


class SandboxSnapshotCapture(Contract):
    provider_snapshot_id: str = Field(min_length=1)
    filesystem_digest: str = Field(pattern=DIGEST_PATTERN)
    content_manifest_digest: str = Field(pattern=DIGEST_PATTERN)
    payload: bytes = Field(repr=False, max_length=268_435_456)
    media_type: str = Field(default="application/x-tar", min_length=1)


class SandboxSnapshot(Contract):
    snapshot_id: str = Field(min_length=1)
    creation_identity: str = Field(pattern=DIGEST_PATTERN)
    request_scope: str = Field(min_length=1)
    source_namespace_id: str = Field(min_length=1)
    source_workspace_id: str = Field(min_length=1)
    parent_snapshot_id: str | None = None
    provider: str = Field(min_length=1)
    provider_snapshot_id: str = Field(min_length=1)
    filesystem_digest: str = Field(pattern=DIGEST_PATTERN)
    content_manifest_digest: str = Field(pattern=DIGEST_PATTERN)
    payload: SnapshotPayloadAddress
    runtime_digest: str = Field(pattern=DIGEST_PATTERN)
    image_digest: str = Field(pattern=DIGEST_PATTERN)
    package_digest: str = Field(pattern=DIGEST_PATTERN)
    environment_digest: str = Field(pattern=DIGEST_PATTERN)
    workspace_contract_digest: str = Field(pattern=DIGEST_PATTERN)
    mount_manifest_digest: str = Field(pattern=DIGEST_PATTERN)
    reason: SnapshotCreationReason
    producer_binding_id: str = Field(min_length=1)
    snapshot_policy_ref: str = Field(min_length=1)
    capability_shape: SnapshotCapabilityShape
    retention: SnapshotRetention
    created_at: AwareDatetime


class SnapshotCloneRequest(Contract):
    snapshot_id: str = Field(min_length=1)
    clone_id: str = Field(min_length=1)
    request_scope: str = Field(min_length=1)
    target_namespace_id: str = Field(min_length=1)
    target_workspace_id: str = Field(min_length=1)
    binding_id: str = Field(min_length=1)
    runtime_digest: str = Field(pattern=DIGEST_PATTERN)
    image_digest: str = Field(pattern=DIGEST_PATTERN)
    package_digest: str = Field(pattern=DIGEST_PATTERN)
    environment_digest: str = Field(pattern=DIGEST_PATTERN)
    workspace_contract_digest: str = Field(pattern=DIGEST_PATTERN)
    target_mount_manifest_digest: str = Field(pattern=DIGEST_PATTERN)
    capability_shape: SnapshotCapabilityShape
    requested_at: AwareDatetime


class SnapshotCloneRecord(Contract):
    clone_id: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1)
    parent_workspace_id: str = Field(min_length=1)
    target_namespace_id: str = Field(min_length=1)
    target_workspace_id: str = Field(min_length=1)
    binding_id: str = Field(min_length=1)
    resources: ReacquiredRuntimeResources
    created_at: AwareDatetime


class ReacquiredRuntimeResources(Contract):
    secret_names: tuple[str, ...] = ()
    credential_names: tuple[str, ...] = ()
    lease_names: tuple[str, ...] = ()
    mcp_connection_names: tuple[str, ...] = ()
    socket_names: tuple[str, ...] = ()


class SnapshotCloneResult(Contract):
    clone_id: str
    workspace: MaterializedWorkspace
    parent_snapshot_id: str
    parent_workspace_id: str
    resources: ReacquiredRuntimeResources = Field(default_factory=ReacquiredRuntimeResources)
    credentials_reresolved: Literal[True] = True
    external_leases_reresolved: Literal[True] = True
    live_resources_restored: tuple[()] = ()
    artifact_promotion_required: Literal[True] = True
