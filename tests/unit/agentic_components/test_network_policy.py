"""MO-15: network policy resolution and per-lane projection (materialization SPEC-01 section 5).

- Resolution turns the declared policy into exact hosts: declared entries, the kit's egress
  under ``include_kit`` and every Mission Control host the run requires. The Signal Ingress host
  is always included when callbacks are required (``include_signal_ingress`` or a minted signal
  token), the Model Gateway host when a harness reaches its model through it; an unconfigured
  required host, a closed network that forbids one, or unresolved kit egress is a refusal.
- Every lane profile projects the resolved policy into its own control and records honestly
  whether that control enforces it (``enforced``), only approximates it (``advisory``) or does
  nothing (``unsupported``), including the hosts it cannot reach.
- The resolved policy rides on ``mc.environment_binding.v1`` with its digest as
  ``network_policy_ref``; a binding without one keeps its dump.

Pure: no provider, catalog or installation is contacted.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from mission_control.application.environments import (
    BootstrapRoute,
    EnvironmentRequest,
    LaneNetworkContext,
    NetworkDelivery,
    NetworkEnforcement,
    NetworkProjectionRefused,
    project_network_policy,
    project_sandbox_egress,
    resolve_environment,
)
from mission_control.application.environments.network import (
    AGENTS_API_MAX_DOMAINS,
    CODEX_NETWORK_ACCESS,
    SANDBOX_EGRESS_UNAVAILABLE,
)
from mission_control.domain.authoring.manifest_v2 import EnvironmentV2
from mission_control.domain.authoring.mission_environment import KitSelection, NetworkPolicy
from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.execution.bindings import EnvironmentBinding
from mission_control.domain.execution.network_policy import (
    KIT_EGRESS_UNRESOLVED,
    MODEL_GATEWAY_UNCONFIGURED,
    NETWORK_FORBIDS_REQUIRED_HOST,
    SIGNAL_INGRESS_UNCONFIGURED,
    NetworkHosts,
    NetworkPolicyUnresolvable,
    ResolvedNetworkPolicy,
    requires_signal_ingress,
    resolve_network_policy,
)

KIT = KitSelection(pin="envkit.python-uv-node@3#sha256:" + "1" * 64)
KIT_EGRESS = ("registry.npmjs.org", "pypi.org")
INGRESS = "mc-ingress.vercel.app"
GATEWAY = "mc-gateway.vercel.app"
HOSTS = NetworkHosts(signal_ingress=INGRESS, model_gateway=GATEWAY)
ALLOWLIST = NetworkPolicy(allow=("api.firecrawl.dev",), include_signal_ingress=True)


def resolved(
    network: NetworkPolicy = ALLOWLIST, *, model_gateway: bool = False, **changes: Any
) -> ResolvedNetworkPolicy:
    arguments: dict[str, Any] = {
        "kit": KIT,
        "kit_egress": KIT_EGRESS,
        "hosts": HOSTS,
        "signal_ingress": network.include_signal_ingress,
        "model_gateway": model_gateway,
        **changes,
    }
    return resolve_network_policy(network, **arguments)


# --- Resolution ------------------------------------------------------------------------------


def test_an_allowlist_resolves_to_declared_kit_and_mission_control_hosts() -> None:
    policy = resolved(model_gateway=True)
    assert policy.mode == "allowlist"
    assert policy.hosts == (
        "api.firecrawl.dev",
        GATEWAY,
        INGRESS,
        "pypi.org",
        "registry.npmjs.org",
    )
    assert policy.required == (INGRESS, GATEWAY)
    assert policy.kit == KIT.pin
    assert policy.allows("pypi.org") and not policy.allows("evil.example.org")
    # Without include_kit the kit's egress is not granted (nor needed).
    excluded = resolved(
        NetworkPolicy(allow=("api.firecrawl.dev",), include_kit=False), kit_egress=None
    )
    assert excluded.hosts == ("api.firecrawl.dev",) and excluded.kit is None


def test_the_signal_ingress_host_is_included_whenever_callbacks_are_required() -> None:
    environment = EnvironmentV2.model_validate(
        {
            "network": {"allow": ["api.firecrawl.dev"]},
            "secrets": [{"name": "MC_SIGNAL_TOKEN", "ref": "mint:signal_token"}],
        }
    )
    # A minted signal token is useless without the ingress: it requires the host too.
    assert requires_signal_ingress(environment)
    assert environment.network is not None
    policy = resolved(environment.network, signal_ingress=True)
    assert INGRESS in policy.hosts and policy.signal_ingress == INGRESS
    assert not requires_signal_ingress(EnvironmentV2.model_validate({"network": {}}))
    # allow_all lists nothing but still records what the run requires.
    open_policy = resolved(NetworkPolicy(mode="allow_all", include_signal_ingress=True))
    assert open_policy.hosts == () and open_policy.required == (INGRESS,)
    assert open_policy.allows("anything.example.org")


@pytest.mark.parametrize(
    ("network", "changes", "code", "field"),
    [
        (ALLOWLIST, {"hosts": NetworkHosts()}, SIGNAL_INGRESS_UNCONFIGURED, "network"),
        (
            NetworkPolicy(allow=("a.example.org",)),
            {"hosts": NetworkHosts(signal_ingress=INGRESS), "model_gateway": True},
            MODEL_GATEWAY_UNCONFIGURED,
            "network",
        ),
        (
            NetworkPolicy(mode="none"),
            {"signal_ingress": True},
            NETWORK_FORBIDS_REQUIRED_HOST,
            "network",
        ),
        (ALLOWLIST, {"kit_egress": None}, KIT_EGRESS_UNRESOLVED, "kit.pin"),
    ],
)
def test_an_unresolvable_policy_is_refused_never_a_dropped_host(
    network: NetworkPolicy, changes: dict[str, Any], code: str, field: str
) -> None:
    with pytest.raises(NetworkPolicyUnresolvable) as refused:
        resolved(network, **changes)
    assert refused.value.code == code
    assert refused.value.field == field


def test_a_resolved_policy_is_exact_and_content_addressed() -> None:
    policy = resolved()
    assert policy.digest == resolved().digest
    assert policy.digest != resolved(kit_egress=("pypi.org",)).digest
    with pytest.raises(ValidationError, match="required Mission Control host"):
        ResolvedNetworkPolicy(mode="allowlist", hosts=("a.example.org",), signal_ingress=INGRESS)
    with pytest.raises(ValidationError, match="sorted and unique"):
        ResolvedNetworkPolicy(mode="allowlist", hosts=("b.example.org", "a.example.org"))
    with pytest.raises(ValidationError, match="closed network"):
        ResolvedNetworkPolicy(mode="none", signal_ingress=INGRESS)


def test_the_environment_binding_seals_the_policy_with_its_digest() -> None:
    base = {"kind": "local_workspace", "host_profile": "worker.linux.default"}
    policy = resolved()
    sealed = EnvironmentBinding.model_validate(
        {**base, "network": policy, "network_policy_ref": policy.digest}
    )
    assert sealed.network == policy
    with pytest.raises(ValidationError, match="digest of the resolved network policy"):
        EnvironmentBinding.model_validate(
            {**base, "network": policy, "network_policy_ref": "OWNER-SELECT:egress"}
        )
    # A binding without a resolved policy keeps its dump (and so its sealed digests).
    assert "network" not in EnvironmentBinding.model_validate(base).model_dump()


def test_the_environment_resolver_carries_the_policy_into_the_binding() -> None:
    policy = resolved()
    request = EnvironmentRequest(
        lane_profile=LaneProfile.CLAUDE_AGENT_SDK,
        kind="local_workspace",
        host_profile="worker.linux.default",
        bootstrap_route=BootstrapRoute.PRE_SESSION_FILES,
        network=policy,
    )
    resolution = resolve_environment(request, allow_unqualified=True)
    assert resolution.binding is not None
    assert resolution.binding.network == policy
    assert resolution.binding.network_policy_ref == policy.digest


# --- Per-lane projection -----------------------------------------------------------------------

# What each lane does with an allowlist (no lane-specific context), and where its hosts go.
ALLOWLIST_PROJECTIONS: dict[LaneProfile, tuple[NetworkEnforcement, NetworkDelivery]] = {
    LaneProfile.DEEP_AGENTS: (NetworkEnforcement.ADVISORY, NetworkDelivery.OPERATION_GRANT),
    LaneProfile.CURSOR_LOCAL: (NetworkEnforcement.UNSUPPORTED, NetworkDelivery.NONE),
    LaneProfile.CURSOR_CLOUD: (NetworkEnforcement.ADVISORY, NetworkDelivery.NONE),
    LaneProfile.CLAUDE_AGENT_SDK: (NetworkEnforcement.ADVISORY, NetworkDelivery.SESSION_OPTIONS),
    LaneProfile.CODEX: (NetworkEnforcement.ADVISORY, NetworkDelivery.SESSION_OPTIONS),
    LaneProfile.CLAUDE_CLOUD: (NetworkEnforcement.ENFORCED, NetworkDelivery.OWNER_PREREQUISITE),
    LaneProfile.CODEX_CLOUD: (NetworkEnforcement.ENFORCED, NetworkDelivery.OWNER_PREREQUISITE),
    LaneProfile.CLAUDE_MANAGED: (
        NetworkEnforcement.ENFORCED,
        NetworkDelivery.PROVIDER_ENVIRONMENT,
    ),
    LaneProfile.CODEX_AGENTS: (NetworkEnforcement.ENFORCED, NetworkDelivery.PROVIDER_ENVIRONMENT),
}


def _hosts_in(settings: Any) -> set[str]:
    """Every host string anywhere in a projection's settings."""

    if isinstance(settings, dict):
        return {host for value in settings.values() for host in _hosts_in(value)}
    if isinstance(settings, list):
        return {host for value in settings for host in _hosts_in(value)}
    return {settings} if isinstance(settings, str) and "." in settings else set()


@pytest.mark.parametrize("profile", list(LaneProfile))
def test_every_lane_records_an_honest_projection(profile: LaneProfile) -> None:
    policy = resolved()
    projection = project_network_policy(profile, policy)
    assert (projection.enforcement, projection.delivery) == ALLOWLIST_PROJECTIONS[profile]
    assert projection.policy_ref == policy.digest
    assert projection.note
    hosts = _hosts_in(projection.settings)
    if hosts:
        # A lane that carries hosts carries exactly the resolved list, ingress included.
        assert hosts == set(policy.hosts)
        assert INGRESS in hosts
    assert projection.native_details() == {
        "network_policy_ref": policy.digest,
        "network_enforcement": projection.enforcement.value,
        "network_delivery": projection.delivery.value,
    }


def test_provider_settings_use_each_providers_own_fields() -> None:
    policy = resolved()
    hosts = list(policy.hosts)
    settings = {
        profile: project_network_policy(profile, policy).settings for profile in LaneProfile
    }
    assert settings[LaneProfile.CURSOR_CLOUD] == {
        "egressMode": "network_settings_only",
        "egressAllowlist": hosts,
    }
    assert settings[LaneProfile.CLAUDE_AGENT_SDK] == {
        "sandbox": {
            "enabled": True,
            # Sandboxing never auto-approves Bash past Mission Control's permission gate.
            "autoAllowBashIfSandboxed": False,
            "allowUnsandboxedCommands": False,
            "network": {"allowedDomains": hosts},
        }
    }
    assert settings[LaneProfile.CODEX] == {CODEX_NETWORK_ACCESS: True}
    assert settings[LaneProfile.CLAUDE_CLOUD] == {
        "network_access": "Custom",
        "allowed_domains": hosts,
        "include_default_domains": False,
    }
    assert settings[LaneProfile.CODEX_CLOUD] == {
        "agent_internet_access": True,
        "domain_allowlist": "custom",
        "additional_domains": hosts,
    }
    assert settings[LaneProfile.CLAUDE_MANAGED] == {
        "networking": {
            "type": "limited",
            "allowed_hosts": hosts,
            "allow_package_managers": False,
            "allow_mcp_servers": False,
        }
    }
    assert settings[LaneProfile.CODEX_AGENTS] == {
        "network": {"access": "restricted", "allowed_domains": hosts}
    }


def test_closed_and_open_policies_per_provider() -> None:
    closed = resolved(NetworkPolicy(mode="none"), signal_ingress=False)
    opened = resolved(NetworkPolicy(mode="allow_all"), signal_ingress=False)
    assert project_network_policy("codex", closed).settings == {CODEX_NETWORK_ACCESS: False}
    assert project_network_policy("codex", closed).enforcement is NetworkEnforcement.ENFORCED
    assert project_network_policy("codex", opened).enforcement is NetworkEnforcement.ENFORCED
    assert project_network_policy("codex_agents", closed).settings == {
        "network": {"access": "disabled"}
    }
    assert project_network_policy("claude_managed", opened).settings == {
        "networking": {"type": "unrestricted"}
    }
    assert project_network_policy("cursor_cloud", opened).settings == {"egressMode": "allow_all"}
    # Nothing to restrict: lanes without a control realize allow_all, and only allow_all.
    for profile in ("cursor_local", "claude_agent_sdk"):
        assert project_network_policy(profile, opened).enforcement is NetworkEnforcement.ENFORCED
        assert project_network_policy(profile, closed).enforcement is not (
            NetworkEnforcement.ENFORCED
        )
    assert project_network_policy("claude_agent_sdk", opened).settings == {}


def test_deep_agents_projects_finite_worker_tool_grants_without_sandbox_network_claim() -> None:
    policy = resolved()
    projection = project_network_policy("deep_agents", policy)
    assert projection.settings == {"network_hosts": list(policy.hosts)}
    assert projection.delivery is NetworkDelivery.OPERATION_GRANT
    assert projection.enforcement is NetworkEnforcement.ADVISORY
    assert "Executable sandbox networking is unchanged" in projection.note
    closed = project_network_policy("deep_agents", resolved(NetworkPolicy(mode="none")))
    assert closed.settings == {"network_hosts": []}
    assert closed.delivery is NetworkDelivery.OPERATION_GRANT
    opened = project_network_policy("deep_agents", resolved(NetworkPolicy(mode="allow_all")))
    assert opened.enforcement is NetworkEnforcement.UNSUPPORTED
    assert opened.delivery is NetworkDelivery.NONE
    wildcard = project_network_policy(
        "deep_agents", resolved(NetworkPolicy(allow=("*.example.org",)))
    )
    assert wildcard.enforcement is NetworkEnforcement.UNSUPPORTED
    assert wildcard.delivery is NetworkDelivery.NONE


def test_the_codex_sandbox_mode_decides_what_the_lane_enforces() -> None:
    policy = resolved()

    def codex(mode: Any) -> Any:
        return project_network_policy("codex", policy, LaneNetworkContext(codex_sandbox=mode))

    full = codex("danger-full-access")
    assert full.enforcement is NetworkEnforcement.UNSUPPORTED and full.settings == {}
    # Read-only has no network: narrower than the policy, so callbacks cannot reach the ingress
    # and observation degrades to the provider API.
    read_only = codex("read-only")
    assert read_only.enforcement is NetworkEnforcement.ENFORCED
    assert read_only.omitted_hosts == policy.hosts
    assert read_only.observation_degraded
    assert read_only.native_details()["network_observation"] == "provider_api_only"
    assert not codex("workspace-write").observation_degraded


def test_cursor_lanes_follow_the_sandbox_flag_and_the_environment_strategy() -> None:
    policy = resolved()
    sandboxed = project_network_policy(
        "cursor_local", policy, LaneNetworkContext(cursor_sandbox=True)
    )
    assert sandboxed.enforcement is NetworkEnforcement.ADVISORY
    assert sandboxed.settings == {"sandbox_enabled": True}

    def cloud(strategy: Any) -> Any:
        return project_network_policy("cursor_cloud", policy, LaneNetworkContext(strategy=strategy))

    assert (cloud("sync").enforcement, cloud("sync").delivery) == (
        NetworkEnforcement.ENFORCED,
        NetworkDelivery.PROVIDER_ENVIRONMENT,
    )
    assert (cloud("generate").enforcement, cloud("generate").delivery) == (
        NetworkEnforcement.ENFORCED,
        NetworkDelivery.OWNER_PREREQUISITE,
    )
    assert cloud("bind").enforcement is NetworkEnforcement.ADVISORY
    assert cloud("sync").settings == cloud("bind").settings


def test_the_agents_api_carries_exact_domains_only() -> None:
    wildcard = resolved(NetworkPolicy(allow=("*.example.org", "api.firecrawl.dev")))
    projection = project_network_policy("codex_agents", wildcard)
    assert projection.omitted_hosts == ("*.example.org",)
    assert "*.example.org" not in _hosts_in(projection.settings)
    assert not projection.observation_degraded
    many = ResolvedNetworkPolicy(
        mode="allowlist",
        hosts=tuple(sorted(f"h{index}.example.org" for index in range(AGENTS_API_MAX_DOMAINS + 1))),
    )
    assert project_network_policy("codex_agents", many).enforcement is (
        NetworkEnforcement.UNSUPPORTED
    )


def test_self_hosted_tools_are_governed_by_the_sandbox_host() -> None:
    policy = resolved(model_gateway=True)
    for profile in ("claude_managed", "codex_agents"):
        projection = project_network_policy(
            profile, policy, LaneNetworkContext(self_hosted_tools=True)
        )
        assert projection.enforcement is NetworkEnforcement.UNSUPPORTED
    allowlisted = project_sandbox_egress(
        "claude_agent_sdk", policy, egress_control="domain_allowlist"
    )
    assert allowlisted.enforcement is NetworkEnforcement.ENFORCED
    assert allowlisted.delivery is NetworkDelivery.SANDBOX_HOST
    assert allowlisted.settings == {"egress": "allowlist", "domains": list(policy.hosts)}
    # The Model Gateway host rides with the ingress on every sandbox allowlist.
    assert {GATEWAY, INGRESS} <= _hosts_in(allowlisted.settings)
    closed = resolved(NetworkPolicy(mode="none"), signal_ingress=False)
    assert project_sandbox_egress("codex", closed, egress_control="domain_allowlist").settings == {
        "egress": "block_all"
    }
    assert (
        project_sandbox_egress("codex", policy, egress_control="none").enforcement
        is NetworkEnforcement.UNSUPPORTED
    )


def test_an_organisation_wide_sandbox_list_is_advisory_or_refused() -> None:
    policy = resolved(NetworkPolicy(allow=("api.firecrawl.dev",), include_kit=False))
    essential = ("*.vercel.app", "pypi.org", "registry.npmjs.org")
    with pytest.raises(NetworkProjectionRefused) as refused:
        project_sandbox_egress(
            "codex",
            policy,
            egress_control="org_essential_services_only",
            essential_services=essential,
        )
    assert refused.value.code == SANDBOX_EGRESS_UNAVAILABLE
    assert "api.firecrawl.dev" in refused.value.message
    covered = resolved(NetworkPolicy(include_signal_ingress=True), model_gateway=True)
    projection = project_sandbox_egress(
        "codex", covered, egress_control="org_essential_services_only", essential_services=essential
    )
    assert projection.enforcement is NetworkEnforcement.ADVISORY
