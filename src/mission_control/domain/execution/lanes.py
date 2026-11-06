"""Lane contracts: `mc.lane_describe.v1`/`.v2`, the AgentHarness request and handle contracts
and `mc.cursor_binding.v2` (SPEC-07 sections 1 to 3, ADR-0018, ADR-0030; FT-G1; MP-01; MO-31).

A Harness is the provider-neutral protocol; a Lane is a qualified implementation; a Lane
Profile is one placement of a lane with its own control matrix. Everything here is a strict,
frozen, secret-free value: handles carry native identity, never credentials. The protocol
itself lives in `application/execution/harness/protocol.py`; these contracts are domain values
so that `domain/execution/contracts.py` can pair a runtime with its binding.

Profile identity (MP-01, multi-provider ARCHITECTURE "Profile identity"): the single source of
the Lane Profile vocabulary is `domain/capabilities/host_support.LaneProfile`; the `Literal`
below is checked against it at import so the runtime, projection, frame and manifest
vocabularies cannot drift. `claude_cloud` and `codex_cloud` name the provider-hosted
products only; an Anthropic model running through Cursor, or our own remote worker running
the Claude SDK, is not that profile. `claude_managed` (Anthropic Managed Agents) and
`codex_agents` (the OpenAI Agents API running the Codex harness) are the API-billed hosted
agent APIs on the existing `claude` and `codex` lanes (ADR-0050): the provider runs the agent
loop, so their profile placement is `cloud`; where their tools execute is the binding's
`tool_placement` (SPEC-06 section 1).
"""

from __future__ import annotations

from typing import Any, Final, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from mission_control.domain.agentic_components.layering import MaterializationPolicy
from mission_control.domain.authoring.canonical import stable_json_digest
from mission_control.domain.authoring.mission_environment import ProviderEnvironmentStrategyName
from mission_control.domain.capabilities.gates import SignalGatePolicy
from mission_control.domain.capabilities.hooks import HookEvent
from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.execution.discovery import DiscoveryExpectation
from mission_control.domain.execution.network_policy import ResolvedNetworkPolicy
from mission_control.domain.resolution.sealed import CarriesLaneBinding, SealedLaneBinding

LANE_DESCRIBE_SCHEMA: Final = "mc.lane_describe.v1"
LANE_DESCRIBE_SCHEMA_V2: Final = "mc.lane_describe.v2"
CURSOR_BINDING_SCHEMA: Final = "mc.cursor_binding.v2"
CURSOR_BINDING_SCHEMA_V1: Final = "mc.cursor_binding.v1"
DIGEST_PATTERN: Final = r"^sha256:[0-9a-f]{64}$"

LaneProfileName = Literal[
    "deep_agents",
    "cursor_local",
    "cursor_cloud",
    "claude_agent_sdk",
    "codex",
    "claude_cloud",
    "codex_cloud",
    "claude_managed",
    "codex_agents",
]
LaneName = Literal["deep_agents", "cursor", "claude", "codex"]
ExecutionRuntime = Literal["native", "deep_agent", "cursor", "claude", "codex"]
ControlSupport = Literal["native", "emulated", "unsupported", "unqualified"]
DeliverySemantics = Literal[
    "turn_boundary_guaranteed",
    "cooperative_inject",
    "cancel_and_replace",
    "wait_then_send",
    "pause_at_tool_gate",
    "emulated",
    "unsupported",
]
Placement = Literal["worker_hosted", "cloud"]
UsageDisposition = Literal["settled", "estimated", "unknown"]

LANE_PROFILES: Final[tuple[LaneProfileName, ...]] = (
    "deep_agents",
    "cursor_local",
    "cursor_cloud",
    "claude_agent_sdk",
    "codex",
    "claude_cloud",
    "codex_cloud",
    "claude_managed",
    "codex_agents",
)
LANE_OF_PROFILE: Final[dict[str, LaneName]] = {
    "deep_agents": "deep_agents",
    "cursor_local": "cursor",
    "cursor_cloud": "cursor",
    "claude_agent_sdk": "claude",
    "claude_cloud": "claude",
    "claude_managed": "claude",
    "codex": "codex",
    "codex_cloud": "codex",
    "codex_agents": "codex",
}
PLACEMENT_OF_PROFILE: Final[dict[str, Placement]] = {
    "deep_agents": "worker_hosted",
    "cursor_local": "worker_hosted",
    "cursor_cloud": "cloud",
    "claude_agent_sdk": "worker_hosted",
    "claude_cloud": "cloud",
    "claude_managed": "cloud",
    "codex": "worker_hosted",
    "codex_cloud": "cloud",
    "codex_agents": "cloud",
}
RUNTIME_OF_LANE: Final[dict[str, ExecutionRuntime]] = {
    "deep_agents": "deep_agent",
    "cursor": "cursor",
    "claude": "claude",
    "codex": "codex",
}
# The execution runtimes each lane's harness serves: its own, and on `deep_agents` also the
# `native` placement its runtime adapter executes (the pairing rule the lane registry checks
# against a profile's describe, OC-R2).
RUNTIMES_OF_LANE: Final[dict[str, frozenset[ExecutionRuntime]]] = {
    "deep_agents": frozenset({"native", "deep_agent"}),
    "cursor": frozenset({"cursor"}),
    "claude": frozenset({"claude"}),
    "codex": frozenset({"codex"}),
}
# The sealed binding schema ids each lane produces (OC-R2): a request whose sealed binding is
# not its profile's lane's schema is refused at validation, before any lane reads the bytes.
# The ids are the typed bindings' own `schema_version` constants (`contracts.DEEP_AGENT_
# BINDING_SCHEMA`, `CURSOR_BINDING_SCHEMA*`, `bindings.EXECUTION_BINDING_SCHEMA`).
BINDING_SCHEMAS_OF_LANE: Final[dict[str, frozenset[str]]] = {
    "deep_agents": frozenset({"belllabs.deep-agent-binding.v1"}),
    "cursor": frozenset({CURSOR_BINDING_SCHEMA_V1, CURSOR_BINDING_SCHEMA}),
    "claude": frozenset({"mc.execution_binding.v2"}),
    "codex": frozenset({"mc.execution_binding.v2"}),
}
# Lanes whose attempts carry a typed provider binding beside the operation (`cursor` carries
# `mc.cursor_binding.v2`; `claude` and `codex` carry `mc.execution_binding.v2`).
BOUND_LANES: Final[frozenset[LaneName]] = frozenset({"cursor", "claude", "codex"})
# Profiles whose agent loop the provider runs (not our own remote workers).
HOSTED_PROFILES: Final[frozenset[LaneProfileName]] = frozenset(
    {"cursor_cloud", "claude_cloud", "codex_cloud", "claude_managed", "codex_agents"}
)
# The API-billed hosted agent APIs (ADR-0050). Neither is ZDR-eligible (DECISIONS C3), so they
# admit missions by Data Class (`domain/execution/data_class.py`), and their tools execute
# either on the provider's sandbox or, funding-gated (DECISIONS R31), on our Sandbox Host.
HOSTED_AGENT_API_PROFILES: Final[frozenset[LaneProfileName]] = frozenset(
    {"claude_managed", "codex_agents"}
)
# Their binding options name the tool placement (`cloud` or `openai_hosted`, else
# `self_hosted`); the Sandbox Host placement has no declared matrix until it is funded.
FUNDING_GATED_TOOL_PLACEMENTS: Final[frozenset[str]] = frozenset({"self_hosted"})
DEFAULT_LANE_PROFILE: Final[LaneProfileName] = "deep_agents"

if {profile.value for profile in LaneProfile} != set(LANE_PROFILES):  # pragma: no cover
    raise RuntimeError(
        "lane profile vocabularies drifted: host_support.LaneProfile "
        f"{sorted(profile.value for profile in LaneProfile)} vs lanes.LANE_PROFILES "
        f"{sorted(LANE_PROFILES)}"
    )
if set(LANE_OF_PROFILE) != set(LANE_PROFILES) or set(PLACEMENT_OF_PROFILE) != set(
    LANE_PROFILES
):  # pragma: no cover
    raise RuntimeError("every lane profile needs exactly one lane and one placement")

# The hosted-feasibility checklist (RESEARCH "Provider-hosted feasibility exit criteria"):
# the features a `mc.lane_describe.v2` carries evidence for, one cell each.
LANE_FEATURES: Final[tuple[str, ...]] = (
    "launch",
    "status",
    "observe",
    "follow_up",
    "cancel",
    "usage",
    "output_custody",
    "environment_selection",
    "configuration_materialization",
    "approval_suspension",
    "subordinate_lineage",
    "continuation",
)
ApprovalMode = Literal[
    "workflow_gate",
    "provider_permission",
    "provider_question",
    "mcp_elicitation",
    "governed_effect",
]
APPROVAL_MODES: Final[tuple[ApprovalMode, ...]] = (
    "workflow_gate",
    "provider_permission",
    "provider_question",
    "mcp_elicitation",
    "governed_effect",
)
ObservationFeature = Literal[
    "terminal_result", "tool_lifecycle", "subordinate_lifecycle", "usage", "compaction"
]
OBSERVATION_FEATURES: Final[tuple[ObservationFeature, ...]] = (
    "terminal_result",
    "tool_lifecycle",
    "subordinate_lifecycle",
    "usage",
    "compaction",
)
SubordinateVisibility = Literal["full", "lifecycle_only", "unavailable", "unqualified"]
AccountEnablement = Literal["enabled", "disabled", "unknown"]

# The nine AgentHarness operations beside `describe` (SPEC-07 section 1).
HARNESS_OPERATIONS: Final = (
    "prepare",
    "start",
    "reattach",
    "send_turn",
    "cancel_turn",
    "observe",
    "snapshot",
    "usage",
    "end_session",
)
# `controls` of a describe: the operations plus the two run-level controls.
LANE_CONTROLS: Final = (*HARNESS_OPERATIONS, "pause", "fork")
# `delivery_semantics` of a describe: what each command kind actually does on the lane.
DELIVERY_COMMANDS: Final = (
    "queue_instruction",
    "interrupt_and_inject",
    "pause",
    "hard_pause",
    "resume",
    "cancel",
    "fork",
    "request_continuation",
)
# `mc.hook_event` vocabulary (SPEC-01 / SPEC-07 section 5.4).
HOOK_EVENTS: Final = frozenset(
    {
        "session_start",
        "before_prompt",
        "before_tool",
        "after_tool",
        "after_tool_failure",
        "before_shell",
        "after_shell",
        "before_mcp",
        "after_file_edit",
        "before_model",
        "after_model",
        "before_compaction",
        "after_compaction",
        "subagent_start",
        "subagent_stop",
        "stop",
        "session_end",
    }
)
if {event.value for event in HookEvent} != HOOK_EVENTS:  # pragma: no cover - import guard
    raise RuntimeError("lanes.HOOK_EVENTS drifted from capabilities.hooks.HookEvent")


class LaneContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LaneIdentityMap(LaneContract):
    """How the provider's native identities map onto Mission Control's."""

    session_ref: str = Field(min_length=1)
    turn_ref: str = Field(min_length=1)
    effect_ref: str = Field(min_length=1)
    cursor: str = Field(min_length=1)


class LaneHooks(LaneContract):
    mechanism: str = Field(min_length=1)
    events_supported: tuple[str, ...] = ()
    fail_closed: bool

    @model_validator(mode="after")
    def known_events(self) -> LaneHooks:
        if not self.events_supported and self.mechanism != "none":
            raise ValueError("a lane with a hook mechanism declares its supported events")
        if self.events_supported and self.mechanism == "none":
            raise ValueError("a lane without a hook mechanism declares no events")
        if self.fail_closed and not self.events_supported:
            raise ValueError("no hook can fail closed on a lane that runs none")
        unknown = set(self.events_supported) - HOOK_EVENTS
        if unknown:
            raise ValueError(f"undeclared hook events: {sorted(unknown)}")
        if len(set(self.events_supported)) != len(self.events_supported):
            raise ValueError("hook events must be unique")
        return self


SubagentFieldVerdict = Literal["native", "degraded", "unsupported"]
"""What a lane does with one `SUBAGENT_FIELDS` name (`domain/capabilities/subagents.py`):
the provider's own mechanism, a documented loss, or a refusal when the mission names it. The
per-lane table lives beside the lane adapters (`application/authoring/subagent_support.py`) and
is served beside the describe document; folding it into the persisted `mc.lane_describe.v2`
is a lane-describe migration (P1 subagents, deferred decision)."""


class LaneSubagents(LaneContract):
    file: str | None = None
    inline: str | None = None
    readonly_supported_inline: bool = False
    # P1 subagents (release 1.4.3, migration 0046): the lane's verdict per `SUBAGENT_FIELDS`
    # name, the table compile enforces. Absent from the digest of a document that lacks it,
    # so describes persisted before 1.4.3 keep their digests.
    fields: dict[str, SubagentFieldVerdict] = Field(
        default_factory=dict, exclude_if=lambda value: not value
    )


RestoreLevel = Literal["R0", "R1", "R2", "R3"]
"""How much of a point a lane can read back or seed a fork from (program §6.1): R0 the
packet only; R1 plus the transcript to the point; R2 plus the workspace files as of the
point; R3 the provider's own state at the point (a checkpoint, a forked session)."""


class LaneTimeTravel(LaneContract):
    """What the lane's `read_as_of` and `seed_fork` ports reach (`mc.cognition_coordinate.v1`)."""

    read: RestoreLevel = "R0"
    fork: RestoreLevel = "R0"


class LaneUsage(LaneContract):
    tokens: str = Field(min_length=1)
    cost: str = Field(min_length=1)


class FeatureEvidence(LaneContract):
    """One `mc.lane_describe.v2` feature cell: support plus the evidence behind it.

    `implemented` (an adapter exists), `account_enabled` (the bound account/product exposes
    it) and `qualified` (a recorded live drill for this exact profile) are separate facts; no
    one of them proves another. Evidence names the transport, SDK language/version, provider
    scope, OS and deployment digest the qualification applies to, so a different pin or
    placement cannot inherit it.
    """

    status: ControlSupport
    implemented: bool = False
    account_enabled: AccountEnablement = "unknown"
    qualified: bool = False
    evidence_ref: str | None = Field(default=None, min_length=1, max_length=1_024)
    transport: str | None = Field(default=None, min_length=1, max_length=128)
    sdk_language: str | None = Field(default=None, min_length=1, max_length=32)
    sdk_version: str | None = Field(default=None, min_length=1, max_length=128)
    provider_scope: str | None = Field(default=None, min_length=1, max_length=256)
    os: str | None = Field(default=None, min_length=1, max_length=64)
    deployment_digest: str | None = Field(default=None, pattern=DIGEST_PATTERN)
    qualified_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def evidence_backs_the_claim(self) -> FeatureEvidence:
        if self.qualified:
            if self.status == "unqualified":
                raise ValueError("a qualified feature cannot carry status unqualified")
            if self.evidence_ref is None or self.qualified_at is None:
                raise ValueError("a qualified feature cites evidence_ref and qualified_at")
            if not self.implemented and self.status in {"native", "emulated"}:
                raise ValueError("a qualified native/emulated feature must be implemented")
        if self.status == "unsupported" and self.implemented:
            raise ValueError("an unsupported feature cannot be implemented")
        return self


def unqualified_features() -> dict[str, FeatureEvidence]:
    """Every feature `unqualified` with no evidence: the v2 stub of a lane without a drill."""

    return {feature: FeatureEvidence(status="unqualified") for feature in LANE_FEATURES}


class LaneDescribe(LaneContract):
    """`mc.lane_describe.v1`/`.v2`: one lane profile's honest control matrix (pure, cheap).

    v1 is the FT-G1 shape and stays readable and digest-stable. v2 (MP-01) adds per-feature
    evidence, the approval modes the lane can bind to Human Tasks, whether native compaction
    can be controlled, how much of a subordinate's lifecycle is visible, and which tool
    families a required approval can actually be enforced on. A v1 describe carries none of
    the v2 fields; a v2 describe carries evidence for every feature in `LANE_FEATURES`.
    """

    schema_version: Literal["mc.lane_describe.v1", "mc.lane_describe.v2"] = LANE_DESCRIBE_SCHEMA
    lane: LaneName
    lane_profile: LaneProfileName
    versions: dict[str, str] = Field(default_factory=dict)
    controls: dict[str, ControlSupport]
    delivery_semantics: dict[str, DeliverySemantics]
    identity: LaneIdentityMap
    hooks: LaneHooks
    instruction_channel: tuple[str, ...] = Field(min_length=1)
    subagents: LaneSubagents
    usage: LaneUsage
    placement: Placement
    qualified: bool = False
    # --- mc.lane_describe.v2 (absent from v1 dumps and digests) ---
    features: dict[str, FeatureEvidence] = Field(default_factory=dict, exclude_if=lambda v: not v)
    approval_modes: tuple[ApprovalMode, ...] = Field(default=(), exclude_if=lambda v: not v)
    compaction_control: ControlSupport | None = Field(default=None, exclude_if=lambda v: v is None)
    subordinate_visibility: SubordinateVisibility | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    enforcement_coverage: dict[str, ControlSupport] = Field(
        default_factory=dict, exclude_if=lambda v: not v
    )
    # --- release 1.4.3 (valid on v1 and v2; absent from earlier documents' digests) ---
    time_travel: LaneTimeTravel | None = Field(default=None, exclude_if=lambda v: v is None)

    @model_validator(mode="after")
    def complete_matrix(self) -> LaneDescribe:
        if LANE_OF_PROFILE[self.lane_profile] != self.lane:
            raise ValueError(f"lane profile {self.lane_profile} does not belong to {self.lane}")
        if PLACEMENT_OF_PROFILE[self.lane_profile] != self.placement:
            raise ValueError(
                f"lane profile {self.lane_profile} is placed "
                f"{PLACEMENT_OF_PROFILE[self.lane_profile]}, not {self.placement}"
            )
        if set(self.controls) != set(LANE_CONTROLS):
            raise ValueError(f"controls must name exactly {list(LANE_CONTROLS)}")
        if set(self.delivery_semantics) != set(DELIVERY_COMMANDS):
            raise ValueError(f"delivery_semantics must name exactly {list(DELIVERY_COMMANDS)}")
        if self.qualified and "unqualified" in self.controls.values():
            raise ValueError("a qualified lane cannot report unqualified controls")
        v2_present = (
            bool(self.features)
            or bool(self.approval_modes)
            or self.compaction_control is not None
            or self.subordinate_visibility is not None
            or bool(self.enforcement_coverage)
        )
        if self.schema_version == LANE_DESCRIBE_SCHEMA:
            if v2_present:
                raise ValueError("feature evidence requires schema_version mc.lane_describe.v2")
            return self
        if set(self.features) != set(LANE_FEATURES):
            raise ValueError(f"a v2 describe carries evidence for exactly {list(LANE_FEATURES)}")
        if self.compaction_control is None or self.subordinate_visibility is None:
            raise ValueError("a v2 describe states compaction_control and subordinate_visibility")
        if len(set(self.approval_modes)) != len(self.approval_modes):
            raise ValueError("approval modes must be unique")
        if self.qualified:
            unproven = sorted(
                name
                for name, evidence in self.features.items()
                if evidence.status != "unsupported" and not evidence.qualified
            )
            if unproven:
                raise ValueError(f"a qualified lane cannot carry unqualified features: {unproven}")
        return self

    @property
    def is_v2(self) -> bool:
        return self.schema_version == LANE_DESCRIBE_SCHEMA_V2

    def feature(self, name: str) -> FeatureEvidence:
        """The evidence cell of one feature; a v1 describe reports every feature unqualified."""

        if name not in LANE_FEATURES:
            raise ValueError(f"undeclared lane feature: {name}")
        return self.features.get(name) or FeatureEvidence(status="unqualified")

    def feature_implemented(self, name: str) -> bool:
        return self.feature(name).status in {"native", "emulated"}

    def control(self, operation: str) -> ControlSupport:
        try:
            return self.controls[operation]
        except KeyError as error:
            raise ValueError(f"undeclared lane control: {operation}") from error

    def implemented(self, operation: str) -> bool:
        return self.control(operation) in {"native", "emulated"}

    @property
    def digest(self) -> str:
        """Digest a Validation Report records as the describe it validated against."""

        return stable_json_digest(self)

    def unqualified(self) -> LaneDescribe:
        """The same profile with every control (and v2 feature) `unqualified`: a registered
        stub whose declared delivery semantics are design intent, not proof."""

        update: dict[str, Any] = {
            "controls": dict.fromkeys(LANE_CONTROLS, "unqualified"),
            "qualified": False,
        }
        if self.is_v2:
            # `unsupported` is a stronger, still-honest statement than `unqualified`: a stub
            # keeps it (the hosted feasibility findings survive registration).
            update["features"] = {
                name: (
                    evidence
                    if evidence.status == "unsupported"
                    else FeatureEvidence(status="unqualified")
                )
                for name, evidence in self.features.items()
            }
        return self.model_copy(update=update)


# --- Segmented lane turns (FT-G2) ----------------------------------------------------------


class LaneSegmentBounds(LaneContract):
    """How long one `lane.turn` segment may observe before the workflow re-schedules it.

    `start_to_close_s` bounds the activity (30 to 60 min per SPEC-07); a segment returns
    `done=False` at `max_duration_s` or `max_frames`, well inside it. `heartbeat_timeout_s`
    detects a lost worker; heartbeats are throttled, so the persisted frames, not the
    heartbeat details, are the resume truth. `status_poll_*` bound the cancel path's
    `lane.status` reconciliation, after which the unit is `in_doubt`; `busy_wait_s` bounds
    `wait_then_send` before the attempt classifies `failed(capacity)`.
    """

    max_duration_s: int = Field(default=1_800, ge=1, le=3_600)
    max_frames: int = Field(default=5_000, ge=1, le=100_000)
    start_to_close_s: int = Field(default=2_700, ge=2, le=3_600)
    heartbeat_timeout_s: int = Field(default=30, ge=1, le=600)
    status_poll_limit: int = Field(default=12, ge=1, le=1_000)
    status_poll_interval_s: int = Field(default=5, ge=1, le=600)
    busy_wait_s: int = Field(default=900, ge=1, le=86_400)
    max_segments: int = Field(default=400, ge=1, le=100_000)

    @model_validator(mode="after")
    def segment_ends_inside_the_activity(self) -> LaneSegmentBounds:
        if self.max_duration_s >= self.start_to_close_s:
            raise ValueError("a segment must end before its activity's start-to-close timeout")
        return self


class LaneSeedHead(LaneContract):
    """`mc.lane_seed_head.v1` (cross-provider control, 2026-11-05): what a derived unit's first
    lane turn continues from after a fork seeded a cognition point of another lane session.

    The kernel records it on the derived run's `fork_seed` point (`channel_facts.seed_head`)
    and hands it to the lane in `PrepareRequest.seed` / `StartRequest.seed`. `point` is the
    serialized `mc.cognition_coordinate.v1` point union of the *source* coordinate (the lane
    reads it exactly; the kernel never interprets it); `native_artifacts` is what the lane's
    `seed_fork` created (a forked session id, a branch@sha, a staged transcript ref), never a
    credential; `message` is the injected human message when the fork delivered one at the
    seed head. `restore_level` and `history` are what the lane declared it reached.
    """

    schema_version: Literal["mc.lane_seed_head.v1"] = "mc.lane_seed_head.v1"
    source_run_id: str = Field(min_length=1, max_length=512)
    source_unit_key: str = Field(min_length=1, max_length=512)
    source_execution_generation: int = Field(ge=1)
    point_kind: str = Field(min_length=1, max_length=64)
    point_locator: str = Field(min_length=1, max_length=1_024)
    point: dict[str, Any] = Field(default_factory=dict)
    restore_level: RestoreLevel = "R1"
    history: Literal["native", "reconstructed"] = "reconstructed"
    native_artifacts: dict[str, str] = Field(default_factory=dict)
    message: str | None = Field(default=None, max_length=65_536)
    fork_request_id: str = Field(min_length=1, max_length=512)


class LaneResumePoint(LaneContract):
    """Where the segment loop stands, carried across continue-as-new (SPEC-07 section 4.4)."""

    phase: Literal["start", "resume"] = "start"
    cursor: str | None = Field(default=None, min_length=1, max_length=1_024)
    segment_no: int = Field(default=1, ge=1)
    turn_no: int = Field(default=1, ge=1)


# --- AgentHarness request and handle contracts --------------------------------------------------


class HarnessScope(LaneContract):
    installation_id: str = Field(min_length=1)
    application_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)


class HarnessLease(LaneContract):
    """A fenced lease over the harness execution (workspace, bridge, turn)."""

    lease_id: str = Field(min_length=1)
    fence: int = Field(ge=0)
    expires_at: AwareDatetime


class HarnessRequest(LaneContract):
    """Fields every AgentHarness request carries (SPEC-07 section 1)."""

    scope: HarnessScope
    lane_profile: LaneProfileName
    harness_execution_id: str = Field(min_length=1)
    binding_digest: str = Field(pattern=DIGEST_PATTERN)
    idempotency_key: str = Field(min_length=1, max_length=512)
    generation: int = Field(ge=1)
    lease: HarnessLease | None = None
    deadline: AwareDatetime | None = None


class PrepareRequest(HarnessRequest):
    run_id: str = Field(min_length=1)
    operation_id: str = Field(min_length=1)
    attempt_no: int = Field(ge=1)
    packet_ref: str | None = Field(default=None, min_length=1)
    # Cross-provider control (2026-11-05): the seed head a forked unit's first session
    # continues from (None for every ordinary attempt).
    seed: LaneSeedHead | None = None


class PreparedSession(LaneContract):
    lane_profile: LaneProfileName
    harness_execution_id: str = Field(min_length=1)
    generation: int = Field(ge=1)
    workspace_ref: str | None = None
    projection_digests: dict[str, str] = Field(default_factory=dict)
    materialization_ref: str | None = None
    # MO-34: what the lane's discovery mechanism must report of what this prepare placed.
    discovery: DiscoveryExpectation | None = None


class StartRequest(HarnessRequest):
    prepared: PreparedSession
    # Cross-provider control (2026-11-05): the same seed head `prepare` saw, so a lane that
    # restores at `start` (a forked provider session) needs no state between the two calls.
    seed: LaneSeedHead | None = None


class SessionHandle(LaneContract):
    """Native session identity (agent id, thread id); never a credential."""

    lane_profile: LaneProfileName
    harness_execution_id: str = Field(min_length=1)
    generation: int = Field(ge=1)
    native_session_ref: str | None = Field(default=None, min_length=1)
    # FT-G3: secret-free placement facts the lane records with the native identity
    # (`cursor_sdk_version`, `bridge_state_root`, `cloud_branch`, `cloud_agent_url`).
    native_details: dict[str, str] = Field(default_factory=dict)


class ReattachRequest(HarnessRequest):
    native_session_ref: str = Field(min_length=1)
    native_turn_ref: str | None = Field(default=None, min_length=1)


class SendTurnRequest(HarnessRequest):
    session: SessionHandle
    turn_no: int = Field(ge=1)
    instruction_ref: str = Field(min_length=1)
    packet_ref: str | None = Field(default=None, min_length=1)


class TurnHandle(LaneContract):
    session: SessionHandle
    turn_no: int = Field(ge=1)
    native_turn_ref: str | None = Field(default=None, min_length=1)
    status: Literal["accepted", "busy"] = "accepted"


class CancelTurnRequest(HarnessRequest):
    turn: TurnHandle
    reason: str = Field(min_length=1, max_length=512)
    urgency: Literal["normal", "immediate"] = "normal"


class CancelReceipt(LaneContract):
    acknowledged: bool
    already_terminal: bool = False
    native_status: str | None = None


class ObserveRequest(HarnessRequest):
    turn: TurnHandle
    after: str | None = Field(default=None, min_length=1)
    max_frames: int = Field(default=1_000, ge=1, le=100_000)


class LaneFrame(LaneContract):
    """One observed provider event as the harness yields it (maps onto `mc.provider_frame.v1`,
    SPEC-03): identity, resumable cursor, kind and a digest plus bounded excerpt, never a
    full body or a secret."""

    harness_execution_id: str = Field(min_length=1)
    generation: int = Field(ge=1)
    provider_key: str = Field(min_length=1, max_length=512)
    cursor: str = Field(min_length=1, max_length=512)
    kind: str = Field(min_length=1, max_length=64)
    terminal: bool = False
    digest: str = Field(pattern=DIGEST_PATTERN)
    excerpt: str = Field(default="", max_length=4_096)
    # FT-G2: what `lane.turn` hands the frame writer (SPEC-03 `FrameObservation`). The body
    # is the provider payload as JSON values; the writer redacts, digests and excerpts it
    # before anything is stored. Absent on lanes that persist their own frames.
    raw_kind: str | None = Field(default=None, min_length=1, max_length=256)
    body: Any = None
    native_turn_ref: str | None = Field(default=None, min_length=1, max_length=1_024)
    tool_call_ref: str | None = Field(default=None, min_length=1, max_length=1_024)
    provider_timestamp: AwareDatetime | None = None
    # MP-13/MP-07: the provider subordinate (subagent/task) this frame belongs to, by its
    # stable native identity; absent for the parent session's own frames.
    subordinate_ref: str | None = Field(default=None, min_length=1, max_length=1_024)


class SnapshotRequest(HarnessRequest):
    session: SessionHandle
    reason: str = Field(min_length=1, max_length=512)


class SnapshotManifest(LaneContract):
    lane_profile: LaneProfileName
    harness_execution_id: str = Field(min_length=1)
    generation: int = Field(ge=1)
    kind: Literal["checkpoint", "git_patch", "branch"]
    refs: tuple[str, ...] = Field(min_length=1)
    emulated: bool
    digest: str = Field(pattern=DIGEST_PATTERN)


class UsageRequest(HarnessRequest):
    session: SessionHandle
    turn: TurnHandle | None = None


class UsageReport(LaneContract):
    disposition: UsageDisposition
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    cost_micros_usd: int | None = Field(default=None, ge=0)

    cache_read_tokens: int | None = Field(
        default=None, ge=0, exclude_if=lambda value: value is None
    )
    cache_write_tokens: int | None = Field(
        default=None, ge=0, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def unknown_is_not_zero(self) -> UsageReport:
        if self.disposition == "unknown" and (
            self.input_tokens or self.output_tokens or self.total_tokens
        ):
            raise ValueError("unknown usage carries no token counts")
        return self


class EndSessionRequest(HarnessRequest):
    session: SessionHandle
    reason: str = Field(min_length=1, max_length=512)


class CleanupReceipt(LaneContract):
    released: bool
    artifact_refs: tuple[str, ...] = ()
    # FT-G3: the session's patch artifact (git diff plus untracked files), stored before the
    # workspace lease was released.
    patch_ref: str | None = None


class StatusRequest(HarnessRequest):
    """`lane.status`: reconcile a session (and turn) by native identity (FT-G2)."""

    session: SessionHandle
    turn: TurnHandle | None = None


class ProviderStatus(LaneContract):
    """What the provider says about a session now: run status, terminal or not, idle."""

    status: str = Field(min_length=1, max_length=64)
    terminal: bool
    idle: bool = False
    usage: UsageReport | None = None


# --- the core's view of a sealed lane binding (OC-R2) -----------------------------------------

# RRM-009: the heartbeat timeout class of a bound operation. The lane that sealed the binding
# states it (`LaneDispatch.heartbeat_class`); the deployment maps each class to a timeout.
OperationHeartbeatClass = Literal["deep_agent", "deep_agent_async_children", "bound"]
# Boundary controls a lane's binding declares on its dispatch (OC-R3). `budget_gate`: the lane
# applies an accepted budget pause or resume natively at the boundary (`lane.budget_control`;
# the Managed Agents lane today). `external_cost_settlement`: a settled turn may leave an
# estimated external cost that the cost workflow settles later (the Cursor lanes today).
BoundaryControl = Literal["budget_gate", "external_cost_settlement"]


class LaneDispatch(LaneContract):
    """What the core schedules a lane-bound attempt by (OC-R2, design §8 two-lane rule).

    The lane that seals a `SealedLaneBinding` states these facts beside it and verifies them
    when it decodes its own bytes; the core reads these and never the payload. Each has a
    meaning on two or more lanes: the worker queue serving the lane's activities (Deep Agents,
    Cursor, claude/codex), the attempt's execution generation (every harness request carries
    one), the heartbeat class the deployment maps to a timeout, and the session lanes'
    wall-clock bound on a busy wait (Cursor, claude, codex).
    """

    task_queue: str | None = Field(default=None, min_length=1, max_length=255)
    execution_generation: int = Field(default=1, ge=1)
    heartbeat_class: OperationHeartbeatClass = "bound"
    wall_clock_s: int | None = Field(default=None, ge=1, exclude_if=lambda value: value is None)
    # The boundary controls the lane's binding declares (OC-R3): what a deterministic family
    # workflow and the operation boundary branch on instead of a lane name. Sorted, unique.
    boundary_controls: tuple[BoundaryControl, ...] = Field(
        default=(), exclude_if=lambda value: not value
    )

    @field_validator("boundary_controls")
    @classmethod
    def canonical_controls(cls, value: tuple[BoundaryControl, ...]) -> tuple[BoundaryControl, ...]:
        if list(value) != sorted(set(value)):
            raise ValueError("boundary_controls are sorted and unique")
        return value

    def declares(self, control: BoundaryControl) -> bool:
        return control in self.boundary_controls


# --- mc.cursor_binding.v2 ----------------------------------------------------------------------


class CursorPins(LaneContract):
    cursor_sdk: str = Field(min_length=1)
    bridge: str = Field(min_length=1)
    protocol: str = Field(min_length=1)
    cloud_api: str = Field(min_length=1)


class WorkspacePolicyPin(LaneContract):
    """The admitted `workspace.policy` a binding pins (re-exported by `bindings`)."""

    mode: Literal["managed_worktree", "provider_workspace", "shared_checkout"]
    reuse: Literal["none", "within_run", "within_session"]
    dirty_input: Literal["reject", "snapshot"]
    cleanup: Literal["retain_until_artifacts_registered", "retain", "immediate"]


class CursorWorkspace(LaneContract):
    repo_url: str | None = Field(default=None, min_length=1)
    base_ref: str = Field(min_length=1)
    lease_root: str | None = Field(default=None, min_length=1)
    branch_prefix: str = Field(default="mc/", min_length=1)
    # MO-05: the manifest's admitted workspace policy (cursor_local). Absent on bindings
    # sealed before it, which lease under `CURSOR_LOCAL_POLICY` (one slot per holder
    # generation) and keep their dumps and digests.
    policy: WorkspacePolicyPin | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        json_schema_extra={"digest_omit_default": True},
    )


class CursorProjections(LaneContract):
    """Exact catalog pins of the files the lane places (digests, never bodies).

    `mc.cursor_binding.v2` adds the catalog hook scripts and plugins by exact pin, and the
    digest of the plugin expansion the projection rendered (each plugin and the members it
    took), so a re-resolution that expands differently is drift. Left out of dumps and digests
    when empty, as on every v1 binding."""

    rules_digest: str = Field(pattern=DIGEST_PATTERN)
    agents_digest: str = Field(pattern=DIGEST_PATTERN)
    skills: tuple[str, ...] = ()
    mcp_servers: tuple[str, ...] = ()
    hooks_digest: str = Field(pattern=DIGEST_PATTERN)
    hook_script_pins: tuple[str, ...] = Field(
        default=(),
        exclude_if=lambda value: not value,
        json_schema_extra={"digest_omit_default": True},
    )
    plugin_pins: tuple[str, ...] = Field(
        default=(),
        exclude_if=lambda value: not value,
        json_schema_extra={"digest_omit_default": True},
    )
    plugin_expansion_digest: str | None = Field(
        default=None,
        pattern=DIGEST_PATTERN,
        exclude_if=lambda value: value is None,
        json_schema_extra={"digest_omit_default": True},
    )

    @model_validator(mode="after")
    def plugins_pin_their_expansion(self) -> CursorProjections:
        if bool(self.plugin_pins) != (self.plugin_expansion_digest is not None):
            raise ValueError("plugin pins and plugin_expansion_digest are bound together")
        return self

    @property
    def v2_slots(self) -> bool:
        return bool(self.hook_script_pins or self.plugin_pins)


class CursorHookCallback(LaneContract):
    listen: str = Field(pattern=r"^127\.0\.0\.1:[0-9]{1,5}$")
    token_ttl_s: int = Field(ge=30, le=86_400)


class CursorProviderEnvironment(LaneContract):
    """MO-13: how a cursor_cloud agent gets its base layer (SPEC-01 section 7), from the
    manifest's `provider_environment`: `sync` provisions the kit's environment through the
    environments API, `bind` uses the environment (or committed file) `ref` names, `generate`
    leaves it to the owner. `secret_refs` are the broker declarations a synced environment
    holds (names and references, never values)."""

    strategy: ProviderEnvironmentStrategyName
    ref: str | None = Field(default=None, min_length=1, max_length=512)
    kit_pin: str | None = Field(default=None, min_length=1, max_length=512)
    secret_refs: tuple[str, ...] = ()

    @model_validator(mode="after")
    def strategy_inputs(self) -> CursorProviderEnvironment:
        if (self.strategy == "bind") != (self.ref is not None):
            raise ValueError("ref is required for bind and only for bind")
        if self.strategy == "sync" and self.kit_pin is None:
            raise ValueError("sync renders the environment from a kit pin")
        return self


class CursorCloudOptions(LaneContract):
    auto_create_pr: bool = False
    env_vars_ref: str | None = Field(default=None, min_length=1)
    metadata: dict[str, str] = Field(default_factory=dict)
    environment: Literal["cloud", "pool", "machine"] = "cloud"
    # MO-13: absent on bindings sealed before it and when the manifest names no strategy.
    provider_environment: CursorProviderEnvironment | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        json_schema_extra={"digest_omit_default": True},
    )
    # FT-G5: create idempotently with a client-supplied `agentId` (`409 agent_id_conflict`
    # means already created). The API refuses `envVars` with `agentId`, so a binding that
    # needs env vars sets this false and creates with an `Idempotency-Key` (dedupe window
    # UNVERIFIED). Omitted from dumps and digests at its default.
    client_agent_id: bool = Field(default=True, exclude_if=lambda value: value is True)

    @model_validator(mode="after")
    def env_vars_need_server_minted_ids(self) -> CursorCloudOptions:
        if self.env_vars_ref is not None and self.client_agent_id:
            raise ValueError(
                "env_vars cannot be combined with a client-supplied agent id; "
                "set client_agent_id false (Idempotency-Key create)"
            )
        return self


class CursorBudgets(LaneContract):
    max_turns: int = Field(ge=1)
    max_segments: int = Field(ge=1)
    wall_clock_s: int = Field(ge=1)


def cursor_projected_pins(
    *,
    skills: tuple[str, ...],
    mcp_servers: tuple[str, ...],
    inline_subagents: tuple[str, ...],
    hook_scripts: tuple[str, ...],
    plugins: tuple[str, ...],
) -> tuple[str, ...]:
    """The pin order a Cursor binding's rows render in (de-duplicated): the launch author
    seals the projection of exactly this order and the worker re-renders it."""

    return tuple(dict.fromkeys((*skills, *mcp_servers, *inline_subagents, *hook_scripts, *plugins)))


class CursorExecutionBinding(LaneContract):
    """`mc.cursor_binding.v2`: SDK and bridge pins, model, mode, workspace, projections and
    the hook callback of one Cursor execution. Secret values never appear here.

    v2 (MO-31) is v1 plus the projections' hook-script and plugin slots; a sealed v1 binding
    still reads, unchanged, and cannot carry them."""

    schema_version: Literal["mc.cursor_binding.v1", "mc.cursor_binding.v2"] = CURSOR_BINDING_SCHEMA
    lane_profile: Literal["cursor_local", "cursor_cloud"]
    pins: CursorPins
    model_id: str = Field(min_length=1)
    mode: Literal["agent", "plan"] = "agent"
    workspace: CursorWorkspace
    projections: CursorProjections
    inline_subagents: tuple[str, ...] = ()
    disallowed_tools: tuple[str, ...] = ()
    sandbox_enabled: bool = False
    hook_callback: CursorHookCallback | None = None
    cloud: CursorCloudOptions | None = None
    budgets: CursorBudgets
    # MO-02: the manifest's `materialization` policy (how layering resolves a repository entry
    # that conflicts with Mission Control's). Absent when none is declared and on bindings
    # sealed before it, which keep their dumps and digests.
    materialization: MaterializationPolicy | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        json_schema_extra={"digest_omit_default": True},
    )
    # MO-12: the Environment Kit pin whose mission layer `cursor_local`'s prepare step runs
    # (SPEC-01 section 1). Absent without a kit and on bindings sealed before it.
    setup_pin: str | None = Field(
        default=None,
        min_length=1,
        max_length=512,
        exclude_if=lambda value: value is None,
        json_schema_extra={"digest_omit_default": True},
    )
    # MO-15: the manifest's resolved network policy, which the lane projects and records.
    # Absent when none is declared and on bindings sealed before it.
    network: ResolvedNetworkPolicy | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        json_schema_extra={"digest_omit_default": True},
    )
    # FT-G2: the worker task queue that serves this binding's `lane.*` activities (absent:
    # left out of dumps and digests, as for every binding sealed before it existed).
    task_queue: str | None = Field(
        default=None, min_length=1, max_length=255, exclude_if=lambda value: value is None
    )
    binding_digest: str = Field(pattern=DIGEST_PATTERN)
    in_environment_observation: bool | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        json_schema_extra={"digest_omit_default": True},
    )
    signal_gates: SignalGatePolicy | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        json_schema_extra={"digest_omit_default": True},
    )

    @model_validator(mode="after")
    def profile_shape(self, info: ValidationInfo) -> CursorExecutionBinding:
        if self.lane_profile == "cursor_cloud":
            if self.cloud is None or self.workspace.repo_url is None:
                raise ValueError("cursor_cloud binds a repository and cloud options")
            if self.disallowed_tools:
                raise ValueError("disallowed_tools applies to cursor_local only")
        else:
            if self.cloud is not None:
                raise ValueError("cursor_local carries no cloud options")
            if self.hook_callback is None:
                raise ValueError("cursor_local requires the loopback hook callback")
        if self.schema_version == CURSOR_BINDING_SCHEMA_V1 and self.projections.v2_slots:
            raise ValueError(f"{CURSOR_BINDING_SCHEMA_V1} carries no hook-script or plugin pins")
        sealing = bool(info.context and info.context.get("seal_cursor"))
        if not sealing and self.binding_digest != self.computed_digest():
            raise ValueError("binding_digest does not match the binding content")
        return self

    def computed_digest(self) -> str:
        return stable_json_digest(self, exclude={"binding_digest"})

    def projected_pins(self) -> tuple[str, ...]:
        """Every catalog pin the projection renders, in the order the rows are resolved."""

        return cursor_projected_pins(
            skills=self.projections.skills,
            mcp_servers=self.projections.mcp_servers,
            inline_subagents=self.inline_subagents,
            hook_scripts=self.projections.hook_script_pins,
            plugins=self.projections.plugin_pins,
        )

    @classmethod
    def sealed(cls, **fields: Any) -> CursorExecutionBinding:
        """Build a binding and compute its digest."""

        draft = cls.model_validate(
            {**fields, "binding_digest": "sha256:" + "0" * 64},
            context={"seal_cursor": True},
        )
        return cls.model_validate({**fields, "binding_digest": draft.computed_digest()})

    def seal(self) -> SealedLaneBinding:
        """This binding as its Cursor profile's opaque bytes (only the Cursor lane unseals them)."""

        return SealedLaneBinding.seal_contract(
            self, lane_profile=self.lane_profile, schema_id=self.schema_version
        )

    @classmethod
    def unseal(cls, binding: SealedLaneBinding) -> CursorExecutionBinding:
        decoded = binding.unseal(cls, schema_ids=(CURSOR_BINDING_SCHEMA_V1, CURSOR_BINDING_SCHEMA))
        if decoded.lane_profile != binding.lane_profile:
            raise ValueError("a sealed Cursor binding names another lane profile")
        return decoded

    @classmethod
    def carried_by(cls, operation: CarriesLaneBinding) -> CursorExecutionBinding | None:
        """The Cursor binding an operation carries, or `None` for another lane's bytes."""

        binding = operation.lane_binding
        if binding is None or binding.schema_id not in {
            CURSOR_BINDING_SCHEMA_V1,
            CURSOR_BINDING_SCHEMA,
        }:
            return None
        decoded = cls.unseal(binding)
        dispatch = operation.lane_dispatch
        stated = decoded.lane_dispatch(dispatch.execution_generation) if dispatch else None
        if dispatch is not None and stated != dispatch:
            raise ValueError("the operation's lane dispatch differs from its sealed Cursor binding")
        return decoded

    def lane_dispatch(self, execution_generation: int = 1) -> LaneDispatch:
        """The worker queue serving its `lane.*` activities, its wall-clock busy-wait bound and
        its boundary control: a Cursor turn's estimated cost settles later (`mc.cursor_costs`)."""

        return LaneDispatch(
            task_queue=self.task_queue,
            execution_generation=execution_generation,
            wall_clock_s=self.budgets.wall_clock_s,
            boundary_controls=("external_cost_settlement",),
        )


LANE_CONTRACTS: Final[dict[str, type[BaseModel]]] = {
    "lane_describe": LaneDescribe,
    "feature_evidence": FeatureEvidence,
    "cursor_execution_binding": CursorExecutionBinding,
    "prepare_request": PrepareRequest,
    "prepared_session": PreparedSession,
    "start_request": StartRequest,
    "session_handle": SessionHandle,
    "reattach_request": ReattachRequest,
    "send_turn_request": SendTurnRequest,
    "turn_handle": TurnHandle,
    "cancel_turn_request": CancelTurnRequest,
    "cancel_receipt": CancelReceipt,
    "observe_request": ObserveRequest,
    "lane_frame": LaneFrame,
    "snapshot_request": SnapshotRequest,
    "snapshot_manifest": SnapshotManifest,
    "usage_request": UsageRequest,
    "usage_report": UsageReport,
    "end_session_request": EndSessionRequest,
    "cleanup_receipt": CleanupReceipt,
    "status_request": StatusRequest,
    "provider_status": ProviderStatus,
}


def lane_contract_schemas() -> dict[str, dict[str, Any]]:
    """JSON Schema export of every lane contract (`mc.lane_describe.v1` and the harness)."""

    return {name: model.model_json_schema() for name, model in LANE_CONTRACTS.items()}
