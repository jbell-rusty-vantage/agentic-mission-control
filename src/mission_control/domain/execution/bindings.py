"""Provider execution bindings: `mc.execution_binding.v2`, `mc.environment_binding.v1` and
`mc.workspace_snapshot.v1` (multi-provider ARCHITECTURE "Contract delta"; MP-01).

A binding is the immutable, secret-free record of *exactly* what one attempt runs on: lane
profile, model/auth/environment pins, repository commit, materialization digest, the
workflow's required features and the policy digest, plus the provider-specific settings
validated against the pinned adapter's typed options (never a free-form options bag).
`mc.cursor_binding.v2` stays the Cursor lanes' binding; `claude`/`codex` lanes carry this
v2 binding. Both are sealed with a content digest the way `CursorExecutionBinding` is.

Model IDs, auth profiles, environment IDs and secret names are deployment-registry values
resolved by the launch service; the contracts here only make them exact and checkable.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Final, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationInfo, model_validator

from mission_control.domain.agentic_components.layering import MaterializationPolicy
from mission_control.domain.authoring.canonical import stable_json_digest
from mission_control.domain.authoring.mission_environment import BINDING_SECRET_REF_PATTERN
from mission_control.domain.capabilities.gates import SignalGatePolicy
from mission_control.domain.context.snapshot_evidence import ConversationEvidence
from mission_control.domain.execution.lanes import (
    DIGEST_PATTERN,
    FUNDING_GATED_TOOL_PLACEMENTS,
    HOSTED_AGENT_API_PROFILES,
    HOSTED_PROFILES,
    LANE_OF_PROFILE,
    PLACEMENT_OF_PROFILE,
    ApprovalMode,
    LaneDispatch,
    LaneProfileName,
    ObservationFeature,
    WorkspacePolicyPin,
)
from mission_control.domain.execution.network_policy import ResolvedNetworkPolicy
from mission_control.domain.resolution.sealed import CarriesLaneBinding, SealedLaneBinding

EXECUTION_BINDING_SCHEMA: Final = "mc.execution_binding.v2"
ENVIRONMENT_BINDING_SCHEMA: Final = "mc.environment_binding.v1"
WORKSPACE_SNAPSHOT_SCHEMA: Final = "mc.workspace_snapshot.v1"

BillingMode = Literal["subscription", "api", "enterprise", "provider_account", "unknown"]
EnvironmentReadiness = Literal["unverified", "ready", "failed"]
ProviderName = Literal[
    "claude_agent_sdk",
    "codex_app_server",
    "claude_cloud",
    "codex_cloud",
    "claude_managed",
    "codex_agents",
]

# Which provider options a lane profile's binding carries.
PROVIDER_OF_PROFILE: Final[dict[str, ProviderName]] = {
    "claude_agent_sdk": "claude_agent_sdk",
    "codex": "codex_app_server",
    "claude_cloud": "claude_cloud",
    "codex_cloud": "codex_cloud",
    "claude_managed": "claude_managed",
    "codex_agents": "codex_agents",
}
V2_BINDING_PROFILES: Final[tuple[LaneProfileName, ...]] = (
    "claude_agent_sdk",
    "codex",
    "claude_cloud",
    "codex_cloud",
    "claude_managed",
    "codex_agents",
)
# Profiles that only launch against a repository (SPEC-03 §4, corrected 2026-10-12): Claude
# Code cloud and Codex Cloud need a GitHub repository and the worker lanes lease a checkout;
# cursor_cloud agents and the hosted agent APIs (ADR-0050) can run without one, and
# repo-less profiles are simply not listed.
REPOSITORY_BOUND_PROFILES: Final[frozenset[LaneProfileName]] = frozenset(
    {"cursor_local", "claude_agent_sdk", "codex", "claude_cloud", "codex_cloud"}
)
_BINDING_SECRET_REF = re.compile(BINDING_SECRET_REF_PATTERN)


class BindingContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --- Pins -------------------------------------------------------------------------------------


class ModelPin(BindingContract):
    """The admitted model profile and the exact provider model it resolved to."""

    profile: str = Field(min_length=1, max_length=192)
    model_id: str = Field(min_length=1, max_length=256)
    context_window_tokens: int | None = Field(default=None, ge=1)


class AuthPin(BindingContract):
    """The authentication route: profile reference, billing mode and account reference.

    `account_ref` is an opaque registry reference, never an e-mail address, token or key.
    `billing_mode` is what the route is believed to consume; `unknown` is allowed and must be
    disclosed, never silently treated as free (SPEC-02 "Authentication").
    """

    profile: str = Field(min_length=1, max_length=192)
    billing_mode: BillingMode = "unknown"
    account_ref: str | None = Field(default=None, min_length=1, max_length=256)
    entitlement_refs: tuple[str, ...] = ()


# --- mc.environment_binding.v1 ----------------------------------------------------------------


class EnvironmentBinding(BindingContract):
    """`mc.environment_binding.v1`: where the session runs and how that was verified.

    `local_workspace` names the admitted worker host profile. `provider_hosted` names the
    provider, its published environment ID and either its native immutable revision or an
    observed configuration digest with the method and time of verification. Readiness is a
    separate attestation from identity: a binding can be exact and still `unverified`.

    A `mission/v2` environment populates `setup_pin` (its Environment Kit, on either kind),
    `secret_refs` (the Secret Broker's `NAME[?]=<ref>[;phase,...]` entries: names and
    references, never values), `network` (the resolved policy the lane projects, MO-15) and
    `network_policy_ref` (its digest).
    """

    schema_version: Literal["mc.environment_binding.v1"] = ENVIRONMENT_BINDING_SCHEMA
    kind: Literal["local_workspace", "provider_hosted"]
    host_profile: str | None = Field(default=None, min_length=1, max_length=192)
    provider: Literal["cursor", "anthropic", "openai"] | None = None
    environment_ref: str | None = Field(default=None, min_length=1, max_length=512)
    expected_revision: str | None = Field(default=None, min_length=1, max_length=512)
    observed_config_digest: str | None = Field(default=None, pattern=DIGEST_PATTERN)
    verified_by: str | None = Field(default=None, min_length=1, max_length=128)
    verified_at: AwareDatetime | None = None
    setup_pin: str | None = Field(default=None, min_length=1, max_length=512)
    network_policy_ref: str | None = Field(default=None, min_length=1, max_length=256)
    # MO-15: absent on bindings sealed before it (and when no policy is declared), which keep
    # their dumps and digests.
    network: ResolvedNetworkPolicy | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        json_schema_extra={"digest_omit_default": True},
    )
    secret_refs: tuple[str, ...] = ()
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
    storage_policy_ref: str | None = Field(default=None, min_length=1, max_length=256)
    timeout_ceiling_s: int | None = Field(default=None, ge=1)
    readiness: EnvironmentReadiness = "unverified"
    readiness_evidence_ref: str | None = Field(default=None, min_length=1, max_length=1_024)

    @model_validator(mode="after")
    def shape_by_kind(self) -> EnvironmentBinding:
        if self.kind == "local_workspace":
            if self.host_profile is None:
                raise ValueError("a local_workspace binding names its host_profile")
            hosted = [
                name
                for name in ("provider", "environment_ref", "expected_revision")
                if getattr(self, name) is not None
            ]
            if hosted:
                raise ValueError(f"a local_workspace binding does not carry {', '.join(hosted)}")
        else:
            if self.provider is None or self.environment_ref is None:
                raise ValueError("a provider_hosted binding names provider and environment_ref")
            if self.host_profile is not None:
                raise ValueError("a provider_hosted binding carries no local host_profile")
            if self.expected_revision is None and self.observed_config_digest is None:
                raise ValueError(
                    "a provider_hosted binding pins expected_revision or observed_config_digest"
                )
            if self.observed_config_digest is not None and (
                self.verified_by is None or self.verified_at is None
            ):
                raise ValueError("an observed configuration digest records verified_by/verified_at")
        if self.readiness == "ready" and self.readiness_evidence_ref is None:
            raise ValueError("a ready environment cites readiness_evidence_ref")
        if self.network is not None and self.network_policy_ref != self.network.digest:
            raise ValueError("network_policy_ref is the digest of the resolved network policy")
        if not all(_BINDING_SECRET_REF.fullmatch(ref) for ref in self.secret_refs):
            raise ValueError(
                "secret_refs are NAME[?]=<ref>[;phase,...] declarations of secret:, vault:, "
                "environment: or mint: references, never secret values or addresses"
            )
        return self


# --- Workspace policy and requirements ----------------------------------------------------------


class WorkflowRequirements(BindingContract):
    """The features the workflow required at compile; admission checked them against the
    lane's describe and recorded the describe digest it checked."""

    controls: tuple[str, ...] = ()
    approvals: tuple[ApprovalMode, ...] = ()
    observation: tuple[ObservationFeature, ...] = ()
    describe_digest: str = Field(pattern=DIGEST_PATTERN)


class BindingBudgets(BindingContract):
    max_turns: int = Field(ge=1)
    max_segments: int = Field(ge=1)
    wall_clock_s: int = Field(ge=1)
    token_ceiling: int | None = Field(default=None, ge=1)


# --- Provider options (typed, discriminated; no free-form bag) -----------------------------------


class ClaudeSdkOptions(BindingContract):
    """Local Claude Agent SDK (Python) session options that the pinned SDK accepts."""

    provider: Literal["claude_agent_sdk"] = "claude_agent_sdk"
    permission_mode: Literal["default", "acceptEdits", "plan", "bypassPermissions"] = "default"
    allowed_tools: tuple[str, ...] = ()
    disallowed_tools: tuple[str, ...] = ()
    setting_sources: tuple[Literal["user", "project", "local"], ...] = ("project",)
    max_turns: int | None = Field(default=None, ge=1)
    cli_path_ref: str | None = Field(default=None, min_length=1, max_length=256)


class CodexAppServerOptions(BindingContract):
    """Local Codex app-server thread/turn options from the pinned JSON-RPC schema."""

    provider: Literal["codex_app_server"] = "codex_app_server"
    # The pinned app-server `AskForApproval` (codex-cli 0.162.0) has no "on-failure".
    approval_policy: Literal["untrusted", "on-request", "never"] = "on-request"
    sandbox_mode: Literal["read-only", "workspace-write", "danger-full-access"] = "workspace-write"
    reasoning_effort: Literal["minimal", "low", "medium", "high"] | None = None
    app_server_schema_version: str = Field(min_length=1, max_length=64)


class ClaudeCloudOptions(BindingContract):
    """Anthropic-hosted Claude Code session options. Every control here must be backed by the
    MP-16 feasibility record before an adapter claims it; the contract only names them."""

    provider: Literal["claude_cloud"] = "claude_cloud"
    repository_ref: str = Field(min_length=1, max_length=512)
    branch: str | None = Field(default=None, min_length=1, max_length=256)
    create_pr: bool = False


class CodexCloudOptions(BindingContract):
    """OpenAI-hosted Codex task options. Same evidence rule as above (MP-17)."""

    provider: Literal["codex_cloud"] = "codex_cloud"
    repository_ref: str = Field(min_length=1, max_length=512)
    branch: str | None = Field(default=None, min_length=1, max_length=256)
    attempts: int = Field(default=1, ge=1, le=4)


class ClaudeManagedOptions(BindingContract):
    """Anthropic Managed Agents session options (SPEC-06 section 4; ADR-0050).

    `tool_placement` is where the agent's tools execute: Anthropic's cloud sandbox, or our
    Sandbox Host through the work queue (funding-gated, DECISIONS R31). Every session sets a
    `budget.max_list_cost`, in USD minor units as the API takes it (SPEC-06 section 4.2;
    research/provider-smoke-2026-10.md section 2.1). `multiagent` stays off unless a read-only
    knowledge mission enables it (DECISIONS R33).
    """

    provider: Literal["claude_managed"] = "claude_managed"
    tool_placement: Literal["cloud", "self_hosted"] = "cloud"
    max_list_cost_minor_units: int = Field(ge=1)
    multiagent: bool = False


class CodexAgentsOptions(BindingContract):
    """OpenAI Agents API session options with the Codex harness (SPEC-06 section 5; ADR-0050).

    `tool_placement` is OpenAI's hosted sandbox or, funding-gated, our Sandbox Host running
    `codex exec-server`. Subagents cannot call Mission Control function tools, so
    `multi_agent` stays off unless the mission is read-only (SPEC-06 section 5.3).
    """

    provider: Literal["codex_agents"] = "codex_agents"
    tool_placement: Literal["openai_hosted", "self_hosted"] = "openai_hosted"
    multi_agent: bool = False


ProviderOptions = Annotated[
    ClaudeSdkOptions
    | CodexAppServerOptions
    | ClaudeCloudOptions
    | CodexCloudOptions
    | ClaudeManagedOptions
    | CodexAgentsOptions,
    Field(discriminator="provider"),
]


# --- mc.execution_binding.v2 --------------------------------------------------------------------


class ProviderExecutionBinding(BindingContract):
    """`mc.execution_binding.v2`: one attempt's exact, sealed provider binding.

    Consistency rules: the profile's lane/placement, the provider options' discriminator,
    the environment binding's kind and the repository pins must all agree; hosted profiles
    bind a repository URL and commit, local profiles bind a host profile. The hosted agent
    APIs also run knowledge work without a repository, so there the repository is optional
    but, when bound, pinned to a commit; their funding-gated `self_hosted` tool placement has
    no declared matrix yet and is refused (DECISIONS R31). `binding_digest`
    is the content digest over every other field, so two bindings with equal digests run
    identically.
    """

    schema_version: Literal["mc.execution_binding.v2"] = EXECUTION_BINDING_SCHEMA
    lane_profile: Literal[
        "claude_agent_sdk", "codex", "claude_cloud", "codex_cloud", "claude_managed", "codex_agents"
    ]
    model: ModelPin
    auth: AuthPin
    environment: EnvironmentBinding
    workspace_policy: WorkspacePolicyPin
    repo_url: str | None = Field(default=None, min_length=1, max_length=1_024)
    repo_ref: str | None = Field(default=None, min_length=1, max_length=256)
    repo_commit: str | None = Field(default=None, pattern=r"^[0-9a-f]{7,64}$")
    materialization_digest: str = Field(pattern=DIGEST_PATTERN)
    requirements: WorkflowRequirements
    policy_digest: str = Field(pattern=DIGEST_PATTERN)
    pins: dict[str, str] = Field(default_factory=dict)
    provider_options: ProviderOptions
    budgets: BindingBudgets
    # MO-02: the manifest's `materialization` policy (how layering resolves a repository entry
    # that conflicts with Mission Control's). Absent when none is declared and on bindings
    # sealed before it, which keep their dumps and digests.
    materialization: MaterializationPolicy | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        json_schema_extra={"digest_omit_default": True},
    )
    task_queue: str | None = Field(
        default=None, min_length=1, max_length=255, exclude_if=lambda value: value is None
    )
    binding_digest: str = Field(pattern=DIGEST_PATTERN)

    @model_validator(mode="after")
    def consistent(self, info: ValidationInfo) -> ProviderExecutionBinding:
        expected_provider = PROVIDER_OF_PROFILE[self.lane_profile]
        if self.provider_options.provider != expected_provider:
            raise ValueError(
                f"lane profile {self.lane_profile} carries {expected_provider} options, "
                f"not {self.provider_options.provider}"
            )
        hosted = self.lane_profile in HOSTED_PROFILES
        if hosted != (self.environment.kind == "provider_hosted"):
            raise ValueError(
                f"lane profile {self.lane_profile} is placed "
                f"{PLACEMENT_OF_PROFILE[self.lane_profile]}; environment kind "
                f"{self.environment.kind} does not match"
            )
        if hosted:
            if self.lane_profile in HOSTED_AGENT_API_PROFILES:
                if (self.repo_url is None) != (self.repo_commit is None):
                    raise ValueError("a bound repository pins both repo_url and repo_commit")
            elif self.repo_url is None or self.repo_commit is None:
                raise ValueError("a provider-hosted binding pins repo_url and repo_commit")
            if self.workspace_policy.mode == "managed_worktree":
                raise ValueError("managed_worktree is not valid for a provider-hosted lane")
        elif self.workspace_policy.mode == "provider_workspace":
            raise ValueError("provider_workspace needs a provider-hosted lane")
        placement = getattr(self.provider_options, "tool_placement", None)
        if placement in FUNDING_GATED_TOOL_PLACEMENTS:
            raise ValueError(
                f"tool placement {placement} of {self.lane_profile} is funding-gated and has no "
                "declared lane matrix yet (DECISIONS R31)"
            )
        if not any(key.startswith(("sdk", "cli", "schema", "app_server")) for key in self.pins):
            raise ValueError("a binding pins at least one sdk/cli/schema version")
        sealing = bool(info.context and info.context.get("seal_execution_binding"))
        if not sealing and self.binding_digest != self.computed_digest():
            raise ValueError("binding_digest does not match the binding content")
        return self

    @property
    def lane(self) -> str:
        return LANE_OF_PROFILE[self.lane_profile]

    def computed_digest(self) -> str:
        return stable_json_digest(self, exclude={"binding_digest"})

    @classmethod
    def sealed(cls, **fields: Any) -> ProviderExecutionBinding:
        """Build a binding and compute its digest."""

        draft = cls.model_validate(
            {**fields, "binding_digest": "sha256:" + "0" * 64},
            context={"seal_execution_binding": True},
        )
        return cls.model_validate({**fields, "binding_digest": draft.computed_digest()})

    def seal(self) -> SealedLaneBinding:
        """This binding as its profile's opaque bytes (only that lane's adapter unseals them)."""

        return SealedLaneBinding.seal_contract(
            self, lane_profile=self.lane_profile, schema_id=EXECUTION_BINDING_SCHEMA
        )

    @classmethod
    def unseal(cls, binding: SealedLaneBinding) -> ProviderExecutionBinding:
        decoded = binding.unseal(cls, schema_ids=(EXECUTION_BINDING_SCHEMA,))
        if decoded.lane_profile != binding.lane_profile:
            raise ValueError("a sealed mc.execution_binding.v2 names another lane profile")
        return decoded

    @classmethod
    def carried_by(cls, operation: CarriesLaneBinding) -> ProviderExecutionBinding | None:
        """The `mc.execution_binding.v2` an operation carries, or `None` for another lane's."""

        binding = operation.lane_binding
        if binding is None or binding.schema_id != EXECUTION_BINDING_SCHEMA:
            return None
        decoded = cls.unseal(binding)
        dispatch = operation.lane_dispatch
        stated = decoded.lane_dispatch(dispatch.execution_generation) if dispatch else None
        if dispatch is not None and stated != dispatch:
            raise ValueError(
                "the operation's lane dispatch differs from its sealed mc.execution_binding.v2"
            )
        return decoded

    def budget_gate_ceiling(self) -> int | None:
        """The list-cost ceiling of the budget gate this binding declares (`None`: no gate)."""

        options = self.provider_options
        return (
            options.max_list_cost_minor_units if isinstance(options, ClaudeManagedOptions) else None
        )

    def lane_dispatch(self, execution_generation: int = 1) -> LaneDispatch:
        """The worker queue serving its `lane.*` activities, its wall-clock busy-wait bound and
        its boundary controls: Managed Agents options apply a budget gate natively."""

        return LaneDispatch(
            task_queue=self.task_queue,
            execution_generation=execution_generation,
            wall_clock_s=self.budgets.wall_clock_s,
            boundary_controls=(
                ("budget_gate",) if isinstance(self.provider_options, ClaudeManagedOptions) else ()
            ),
        )


# --- mc.workspace_snapshot.v1 -------------------------------------------------------------------


class WorkspaceSnapshot(BindingContract):
    """`mc.workspace_snapshot.v1`: what a leased workspace contained when it was captured.

    A plain `git diff` cannot carry untracked or binary content, so the snapshot names the
    base commit and branch, the patch artifact (tracked changes, deletions, modes), the
    untracked-file artifact, the exclusion rules that applied, and the lease/generation that
    produced it. A cloud branch ref must be recorded as an immutable commit here
    (`branch:<branch>@<sha>` needs a producer, not just a parser).
    """

    schema_version: Literal["mc.workspace_snapshot.v1"] = WORKSPACE_SNAPSHOT_SCHEMA
    lane_profile: LaneProfileName
    base_commit: str = Field(pattern=r"^[0-9a-f]{7,64}$")
    branch: str | None = Field(default=None, min_length=1, max_length=256)
    head_commit: str | None = Field(default=None, pattern=r"^[0-9a-f]{7,64}$")
    patch_artifact_ref: str | None = Field(default=None, min_length=1, max_length=2_048)
    untracked_artifact_ref: str | None = Field(default=None, min_length=1, max_length=2_048)
    tracked_deletions: tuple[str, ...] = ()
    file_modes: dict[str, str] = Field(default_factory=dict)
    submodule_commits: dict[str, str] = Field(default_factory=dict)
    exclusions: tuple[str, ...] = ()
    manifest_digest: str = Field(pattern=DIGEST_PATTERN)
    conversation: ConversationEvidence | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        json_schema_extra={"digest_omit_default": True},
    )
    producer_lease_id: str = Field(min_length=1, max_length=512)
    producer_generation: int = Field(ge=1)
    captured_at: AwareDatetime
    emulated: bool = True

    @model_validator(mode="after")
    def something_was_captured(self) -> WorkspaceSnapshot:
        if self.conversation is not None and (self.branch, self.head_commit) != (
            self.conversation.origin.branch,
            self.conversation.origin.head_commit,
        ):
            raise ValueError("conversation and workspace branch origins differ")
        if (
            self.patch_artifact_ref is None
            and self.untracked_artifact_ref is None
            and self.head_commit is None
        ):
            raise ValueError("a snapshot carries a patch, an untracked artifact or a head commit")
        for path in (*self.tracked_deletions, *self.file_modes):
            if path.startswith("/") or ".." in path.split("/"):
                raise ValueError(f"snapshot paths are repository-relative: {path}")
        return self


BINDING_CONTRACTS: Final[dict[str, type[BaseModel]]] = {
    "execution_binding": ProviderExecutionBinding,
    "environment_binding": EnvironmentBinding,
    "workspace_snapshot": WorkspaceSnapshot,
}


def binding_contract_schemas() -> dict[str, dict[str, Any]]:
    return {name: model.model_json_schema() for name, model in BINDING_CONTRACTS.items()}


__all__ = [
    "BINDING_CONTRACTS",
    "ENVIRONMENT_BINDING_SCHEMA",
    "EXECUTION_BINDING_SCHEMA",
    "PROVIDER_OF_PROFILE",
    "REPOSITORY_BOUND_PROFILES",
    "V2_BINDING_PROFILES",
    "WORKSPACE_SNAPSHOT_SCHEMA",
    "AuthPin",
    "BindingBudgets",
    "ClaudeCloudOptions",
    "ClaudeSdkOptions",
    "CodexAppServerOptions",
    "CodexCloudOptions",
    "EnvironmentBinding",
    "ModelPin",
    "ProviderExecutionBinding",
    "ProviderOptions",
    "WorkflowRequirements",
    "WorkspacePolicyPin",
    "WorkspaceSnapshot",
    "binding_contract_schemas",
]
