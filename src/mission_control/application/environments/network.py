"""Per-lane projection of a resolved network policy (materialization SPEC-01 section 5; MO-15).

One resolved policy (``domain.execution.network_policy``) becomes each lane's native egress
control, and the projection is the receipt entry that says honestly what that control does:

- ``enforced``: the provider or sandbox restricts egress to the policy (or the policy restricts
  nothing). A lane may be *narrower* than the policy; the hosts it cannot reach are listed in
  ``omitted_hosts``, and an omitted Signal Ingress host marks observation as degraded to
  provider-API observation only (SPEC-01 section 5, SPEC-04);
- ``advisory``: the policy is projected but something wider governs (a sandbox that confines
  only shell commands, an all-or-nothing switch, an organisation-wide list, an environment
  Mission Control does not own);
- ``unsupported``: nothing on the lane restricts egress to the policy.

``delivery`` says who puts the settings in place: Mission Control at session start
(``session_options``), Mission Control through the provider's environment API
(``provider_environment``), the owner from generated text (``owner_prerequisite``, SPEC-05), the
Sandbox Host at create (``sandbox_host``), or nobody (``none``). ``settings`` are the provider's
own field names, so the adapter that delivers them passes them through unchanged.
Deep Agents instead seals finite worker-tool hosts into the operation's capability grant
(``operation_grant``). This governs tools that consume that grant and leaves executable
sandbox networking unchanged; it is advisory for lane-wide egress.

Sources per lane: Cursor ``egressMode``/``egressAllowlist`` (research/cursor.md, environment
schema and security-network); Claude Code ``SandboxSettings.network.allowedDomains`` (pinned
``claude_agent_sdk`` types) and the cloud environment network levels (research/claude-code.md);
Codex ``sandbox_workspace_write.network_access`` as a ``thread/start`` config override (pinned
app-server schema) and the cloud agent-internet settings (research/codex.md); Managed Agents
``networking`` (research/anthropic-managed-agents.md section 3a); Agents API ``network``
(research/openai-hosted-agents.md); Sandbox Host egress control (SPEC-06 section 12,
research/daytona.md section 4).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from mission_control.domain.authoring.mission_environment import (
    ProviderEnvironmentStrategyName,
    host_covers,
)
from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.execution.lanes import DIGEST_PATTERN
from mission_control.domain.execution.network_policy import ResolvedNetworkPolicy

SANDBOX_EGRESS_UNAVAILABLE: Final = "SANDBOX_EGRESS_UNAVAILABLE"
# The Agents API takes 1 to 100 exact domains (research/openai-hosted-agents.md "Network").
AGENTS_API_MAX_DOMAINS: Final = 100
# The Codex config key the workspace-write sandbox reads (`thread/start` `config` override).
CODEX_NETWORK_ACCESS: Final = "sandbox_workspace_write.network_access"

CodexSandboxMode = Literal["read-only", "workspace-write", "danger-full-access"]
SandboxEgressControl = Literal["domain_allowlist", "org_essential_services_only", "none"]


class NetworkEnforcement(StrEnum):
    ENFORCED = "enforced"
    ADVISORY = "advisory"
    UNSUPPORTED = "unsupported"


class NetworkDelivery(StrEnum):
    SESSION_OPTIONS = "session_options"
    PROVIDER_ENVIRONMENT = "provider_environment"
    OWNER_PREREQUISITE = "owner_prerequisite"
    SANDBOX_HOST = "sandbox_host"
    OPERATION_GRANT = "operation_grant"
    NONE = "none"


class NetworkProjectionRefused(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class NetworkProjection(BaseModel):
    """One lane's receipt entry for the network policy (secret-free: hosts and settings)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    lane_profile: LaneProfile
    policy_ref: str = Field(pattern=DIGEST_PATTERN)
    enforcement: NetworkEnforcement
    delivery: NetworkDelivery
    settings: dict[str, JsonValue] = Field(default_factory=dict)
    omitted_hosts: tuple[str, ...] = ()
    observation_degraded: bool = False
    note: str = Field(min_length=1)

    def native_details(self) -> dict[str, str]:
        """What a lane records with its native session identity (``SessionHandle``)."""

        details = {
            "network_policy_ref": self.policy_ref,
            "network_enforcement": self.enforcement.value,
            "network_delivery": self.delivery.value,
        }
        if self.observation_degraded:
            details["network_observation"] = "provider_api_only"
        return details


@dataclass(frozen=True)
class LaneNetworkContext:
    """The lane facts a projection depends on, from the sealed binding and the manifest."""

    # cursor_cloud: how its base-layer environment is provided (SPEC-01 section 7).
    strategy: ProviderEnvironmentStrategyName | None = None
    # cursor_local: the deployment's Cursor sandbox flag.
    cursor_sandbox: bool = False
    # codex: the bound sandbox mode.
    codex_sandbox: CodexSandboxMode = "workspace-write"
    # claude_managed / codex_agents: where tools run (a Sandbox Host placement is projected by
    # `project_sandbox_egress`).
    self_hosted_tools: bool = False


def _projection(
    profile: LaneProfile,
    policy: ResolvedNetworkPolicy,
    enforcement: NetworkEnforcement,
    delivery: NetworkDelivery,
    note: str,
    *,
    settings: dict[str, JsonValue] | None = None,
    omitted: Sequence[str] = (),
) -> NetworkProjection:
    return NetworkProjection(
        lane_profile=profile,
        policy_ref=policy.digest,
        enforcement=enforcement,
        delivery=delivery,
        settings=settings or {},
        omitted_hosts=tuple(omitted),
        observation_degraded=policy.signal_ingress is not None and policy.signal_ingress in omitted,
        note=note,
    )


def _unrestricted(
    profile: LaneProfile, policy: ResolvedNetworkPolicy, mechanism: str
) -> NetworkProjection:
    """A lane without its own control: it realizes ``allow_all`` and nothing narrower."""

    if policy.mode == "allow_all":
        return _projection(
            profile,
            policy,
            NetworkEnforcement.ENFORCED,
            NetworkDelivery.NONE,
            f"unrestricted egress needs no projection ({mechanism})",
        )
    return _projection(
        profile,
        policy,
        NetworkEnforcement.UNSUPPORTED,
        NetworkDelivery.NONE,
        f"nothing restricts egress to the {policy.mode} policy: {mechanism}",
    )


def _cursor_local(policy: ResolvedNetworkPolicy, context: LaneNetworkContext) -> NetworkProjection:
    profile = LaneProfile.CURSOR_LOCAL
    if not context.cursor_sandbox:
        return _unrestricted(profile, policy, "the deployment runs the Cursor bridge unsandboxed")
    return _projection(
        profile,
        policy,
        NetworkEnforcement.ADVISORY,
        NetworkDelivery.SESSION_OPTIONS,
        "the Cursor sandbox applies its own network rules (team allowlist, sandbox.json), not "
        "this policy's hosts; per-run domains are not projected (format UNVERIFIED)",
        settings={"sandbox_enabled": True},
    )


def _cursor_cloud(policy: ResolvedNetworkPolicy, context: LaneNetworkContext) -> NetworkProjection:
    """The base-layer environment's ``egressMode``/``egressAllowlist``; "allowlist only" still
    reaches Cursor services and SCM, and user or team policy may restrict further."""

    settings: dict[str, JsonValue] = (
        {"egressMode": "allow_all"}
        if policy.mode == "allow_all"
        else {"egressMode": "network_settings_only", "egressAllowlist": list(policy.hosts)}
    )
    reach = "Cursor services and SCM stay reachable; user and team policy may restrict further"
    if context.strategy == "sync":
        return _projection(
            LaneProfile.CURSOR_CLOUD,
            policy,
            NetworkEnforcement.ENFORCED,
            NetworkDelivery.PROVIDER_ENVIRONMENT,
            f"synced into the mc-owned environment; {reach}",
            settings=settings,
        )
    if context.strategy == "generate":
        return _projection(
            LaneProfile.CURSOR_CLOUD,
            policy,
            NetworkEnforcement.ENFORCED,
            NetworkDelivery.OWNER_PREREQUISITE,
            f"the owner applies the generated egress fields; {reach}",
            settings=settings,
        )
    return _projection(
        LaneProfile.CURSOR_CLOUD,
        policy,
        NetworkEnforcement.ADVISORY,
        NetworkDelivery.NONE,
        "the bound environment's egress is the owner's; Mission Control does not write it",
        settings=settings,
    )


def _claude_agent_sdk(
    policy: ResolvedNetworkPolicy, _context: LaneNetworkContext
) -> NetworkProjection:
    """``ClaudeAgentOptions.sandbox``: Bash runs sandboxed with the policy's domains, never
    unsandboxed, and sandboxing never auto-approves a command past Mission Control's gate."""

    profile = LaneProfile.CLAUDE_AGENT_SDK
    if policy.mode == "allow_all":
        return _unrestricted(profile, policy, "the Claude Code sandbox is left off")
    sandbox: dict[str, JsonValue] = {
        "enabled": True,
        "autoAllowBashIfSandboxed": False,
        "allowUnsandboxedCommands": False,
        "network": {"allowedDomains": list(policy.hosts)},
    }
    return _projection(
        profile,
        policy,
        NetworkEnforcement.ADVISORY,
        NetworkDelivery.SESSION_OPTIONS,
        "the Claude Code sandbox confines Bash only; WebFetch, MCP servers and hooks run "
        "outside it, and it needs a macOS or Linux worker (claude_agent_sdk SandboxSettings)",
        settings={"sandbox": sandbox},
    )


def _codex(policy: ResolvedNetworkPolicy, context: LaneNetworkContext) -> NetworkProjection:
    profile = LaneProfile.CODEX
    mode = context.codex_sandbox
    if mode == "danger-full-access":
        return _unrestricted(profile, policy, "danger-full-access runs commands unsandboxed")
    if mode == "read-only":
        omitted = policy.hosts if policy.mode == "allowlist" else policy.required
        return _projection(
            profile,
            policy,
            NetworkEnforcement.ENFORCED,
            NetworkDelivery.NONE,
            "the read-only sandbox has no network access, narrower than the policy",
            omitted=omitted,
        )
    settings: dict[str, JsonValue] = {CODEX_NETWORK_ACCESS: policy.mode != "none"}
    if policy.mode == "allowlist":
        return _projection(
            profile,
            policy,
            NetworkEnforcement.ADVISORY,
            NetworkDelivery.SESSION_OPTIONS,
            "the workspace-write sandbox switches network access on or off; the domain list "
            "is not enforced (per-domain permission profiles are beta and not projected)",
            settings=settings,
        )
    return _projection(
        profile,
        policy,
        NetworkEnforcement.ENFORCED,
        NetworkDelivery.SESSION_OPTIONS,
        "the workspace-write sandbox has network access "
        + ("on" if policy.mode != "none" else "off"),
        settings=settings,
    )


def _claude_cloud(policy: ResolvedNetworkPolicy, _context: LaneNetworkContext) -> NetworkProjection:
    level = {"allow_all": "Full", "allowlist": "Custom", "none": "None"}[policy.mode]
    settings: dict[str, JsonValue] = {"network_access": level}
    if policy.mode == "allowlist":
        settings |= {"allowed_domains": list(policy.hosts), "include_default_domains": False}
    return _projection(
        LaneProfile.CLAUDE_CLOUD,
        policy,
        NetworkEnforcement.ENFORCED,
        NetworkDelivery.OWNER_PREREQUISITE,
        f"enforced by Anthropic once the owner sets network access {level} on the environment "
        "(UI only); the Anthropic API and the GitHub proxy stay reachable at every level",
        settings=settings,
    )


def _codex_cloud(policy: ResolvedNetworkPolicy, _context: LaneNetworkContext) -> NetworkProjection:
    settings: dict[str, JsonValue] = {"agent_internet_access": policy.mode != "none"}
    if policy.mode == "allow_all":
        settings["domain_allowlist"] = "all"
    elif policy.mode == "allowlist":
        settings |= {"domain_allowlist": "custom", "additional_domains": list(policy.hosts)}
    return _projection(
        LaneProfile.CODEX_CLOUD,
        policy,
        NetworkEnforcement.ENFORCED,
        NetworkDelivery.OWNER_PREREQUISITE,
        "enforced by OpenAI once the owner sets the environment's agent internet access (UI "
        "only, republished)",
        settings=settings,
    )


def _claude_managed(
    policy: ResolvedNetworkPolicy, context: LaneNetworkContext
) -> NetworkProjection:
    profile = LaneProfile.CLAUDE_MANAGED
    if context.self_hosted_tools:
        return _self_hosted(profile, policy)
    networking: dict[str, JsonValue] = (
        {"type": "unrestricted"}
        if policy.mode == "allow_all"
        else {
            "type": "limited",
            "allowed_hosts": list(policy.hosts),
            "allow_package_managers": False,
            "allow_mcp_servers": False,
        }
    )
    return _projection(
        profile,
        policy,
        NetworkEnforcement.ENFORCED,
        NetworkDelivery.PROVIDER_ENVIRONMENT,
        "the environment's networking is always explicit (the API default is unrestricted); "
        "allowed_hosts also bounds web_fetch and web_search",
        settings={"networking": networking},
    )


def _codex_agents(policy: ResolvedNetworkPolicy, context: LaneNetworkContext) -> NetworkProjection:
    profile = LaneProfile.CODEX_AGENTS
    if context.self_hosted_tools:
        return _self_hosted(profile, policy)
    # The Agents API takes exact domains only: a wildcard entry cannot be carried.
    exact: list[JsonValue] = [host for host in policy.hosts if not host.startswith("*.")]
    omitted = [host for host in policy.hosts if host.startswith("*.")]
    if len(exact) > AGENTS_API_MAX_DOMAINS:
        return _projection(
            profile,
            policy,
            NetworkEnforcement.UNSUPPORTED,
            NetworkDelivery.NONE,
            f"the Agents API takes at most {AGENTS_API_MAX_DOMAINS} allowed domains; the policy "
            f"names {len(exact)}",
        )
    if policy.mode == "allow_all":
        network: dict[str, JsonValue] = {"access": "enabled"}
    elif exact:
        network = {"access": "restricted", "allowed_domains": exact}
    else:
        network = {"access": "disabled"}
    return _projection(
        profile,
        policy,
        NetworkEnforcement.ENFORCED,
        NetworkDelivery.PROVIDER_ENVIRONMENT,
        "the hosted environment's network access, with exact domains only"
        + (f"; wildcard entries are not reachable: {', '.join(omitted)}" if omitted else ""),
        settings={"network": network},
        omitted=omitted,
    )


def _self_hosted(profile: LaneProfile, policy: ResolvedNetworkPolicy) -> NetworkProjection:
    return _projection(
        profile,
        policy,
        NetworkEnforcement.UNSUPPORTED,
        NetworkDelivery.NONE,
        "tools run on a Sandbox Host; its egress control governs (project_sandbox_egress)",
    )


def _deep_agents(policy: ResolvedNetworkPolicy, _context: LaneNetworkContext) -> NetworkProjection:
    if policy.mode == "allow_all" or any(host.startswith("*.") for host in policy.hosts):
        return _projection(
            LaneProfile.DEEP_AGENTS,
            policy,
            NetworkEnforcement.UNSUPPORTED,
            NetworkDelivery.NONE,
            "Deep Agents operation grants require exact worker-tool hosts; "
            "unrestricted or wildcard network policies are refused at launch",
        )
    return _projection(
        LaneProfile.DEEP_AGENTS,
        policy,
        NetworkEnforcement.ADVISORY,
        NetworkDelivery.OPERATION_GRANT,
        "Operation-scoped network_hosts govern worker-mediated tools that consume the grant; "
        "agent_browser_page enforces exact hosts. Executable sandbox networking is unchanged "
        "and third-party tools or MCP egress are not generally constrained by this grant",
        settings={"network_hosts": list(policy.hosts)},
    )


_PROJECTORS: Final = {
    LaneProfile.DEEP_AGENTS: _deep_agents,
    LaneProfile.CURSOR_LOCAL: _cursor_local,
    LaneProfile.CURSOR_CLOUD: _cursor_cloud,
    LaneProfile.CLAUDE_AGENT_SDK: _claude_agent_sdk,
    LaneProfile.CODEX: _codex,
    LaneProfile.CLAUDE_CLOUD: _claude_cloud,
    LaneProfile.CODEX_CLOUD: _codex_cloud,
    LaneProfile.CLAUDE_MANAGED: _claude_managed,
    LaneProfile.CODEX_AGENTS: _codex_agents,
}

if set(_PROJECTORS) != set(LaneProfile):  # pragma: no cover
    raise RuntimeError("every LaneProfile projects the network policy")


def project_network_policy(
    profile: LaneProfile | str,
    policy: ResolvedNetworkPolicy,
    context: LaneNetworkContext | None = None,
) -> NetworkProjection:
    """The lane's native egress settings for ``policy`` and how far they enforce it."""

    return _PROJECTORS[LaneProfile(profile)](policy, context or LaneNetworkContext())


def project_sandbox_egress(
    profile: LaneProfile | str,
    policy: ResolvedNetworkPolicy,
    *,
    egress_control: SandboxEgressControl,
    essential_services: Sequence[str] = (),
) -> NetworkProjection:
    """A lane placed on a Sandbox Host: the sandbox's own egress control (its ``describe``).

    ``domain_allowlist`` enforces the policy per sandbox. ``org_essential_services_only`` (a
    Daytona tier below 3) reaches only the organisation's essential-services list: a policy
    whose hosts that list covers runs there, advisory, and any other host is refused rather
    than silently unreachable (SPEC-06 section 2). Without egress control nothing narrower than
    ``allow_all`` holds."""

    profile = LaneProfile(profile)
    if egress_control == "none":
        return _unrestricted(profile, policy, "the Sandbox Host has no egress control")
    if egress_control == "domain_allowlist":
        settings: dict[str, JsonValue] = (
            {"egress": "allow_all"}
            if policy.mode == "allow_all"
            else {"egress": "block_all"}
            if policy.mode == "none"
            else {"egress": "allowlist", "domains": list(policy.hosts)}
        )
        return _projection(
            profile,
            policy,
            NetworkEnforcement.ENFORCED,
            NetworkDelivery.SANDBOX_HOST,
            "the Sandbox Host enforces the policy per sandbox",
            settings=settings,
        )
    needed = policy.hosts if policy.mode == "allowlist" else policy.required
    beyond = [
        host for host in needed if not any(host_covers(entry, host) for entry in essential_services)
    ]
    if beyond:
        raise NetworkProjectionRefused(
            SANDBOX_EGRESS_UNAVAILABLE,
            f"the Sandbox Host reaches only its organisation's essential services, not "
            f"{', '.join(beyond)}; run on a host with per-sandbox egress control",
        )
    return _projection(
        profile,
        policy,
        NetworkEnforcement.ADVISORY,
        NetworkDelivery.SANDBOX_HOST,
        "only the organisation's essential-services list is reachable, which covers the "
        "policy's hosts but is wider than the policy",
        settings={"egress": "organisation"},
    )


__all__ = [
    "AGENTS_API_MAX_DOMAINS",
    "CODEX_NETWORK_ACCESS",
    "SANDBOX_EGRESS_UNAVAILABLE",
    "LaneNetworkContext",
    "NetworkDelivery",
    "NetworkEnforcement",
    "NetworkProjection",
    "NetworkProjectionRefused",
    "project_network_policy",
    "project_sandbox_egress",
]
