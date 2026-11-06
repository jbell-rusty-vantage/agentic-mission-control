"""HL-06 (ADR-0050): the `claude_managed` and `codex_agents` profiles across every vocabulary,
their declared describe-only stubs, the registry that publishes them, their typed binding
options and the Data Class policy that keeps PHI and secrets off them (SPEC-06 sections 1, 8
and 9). Pure: no provider, network or database."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from mission_control.adapters.provider_auth.detection import SURFACES
from mission_control.application.environments.bootstrap import ROUTE_EVIDENCE
from mission_control.application.execution.auth_admission import ROUTE_TABLE, route_spec
from mission_control.application.execution.harness.describe import (
    DECLARED_LANE_MATRICES,
    V2_IMPLEMENTED_LANE_PROFILES,
    V2_STUB_LANE_PROFILES,
)
from mission_control.application.frames.kinds import DEDUPE_KEY_RULES, KIND_TABLES
from mission_control.application.resolution.registries import LaneNotQualified
from mission_control.bootstrap.host_projection import HOST_PROJECTORS
from mission_control.bootstrap.lanes import bound_lane_profiles, describe_only_registry
from mission_control.domain.capabilities.hooks import HOOK_EVENT_MAPPING
from mission_control.domain.capabilities.host_support import (
    UNQUALIFIED_BY_DEFAULT,
    HostSupportStatus,
    LaneProfile,
    all_profiles,
)
from mission_control.domain.execution.bindings import (
    PROVIDER_OF_PROFILE,
    V2_BINDING_PROFILES,
    ProviderExecutionBinding,
)
from mission_control.domain.execution.data_class import (
    DATA_CLASS_NOT_ADMITTED,
    DATA_CLASS_UNDECLARED,
    DATA_CLASSES,
    DEFAULT_DATA_CLASS_POLICY,
    DataClassPolicy,
    admit_data_class,
)
from mission_control.domain.execution.lane_turns import (
    LANE_COMMAND_SEMANTICS,
    LANE_PAUSE_SEMANTICS,
    LANE_RESUME_SEMANTICS,
)
from mission_control.domain.execution.lanes import (
    HOSTED_AGENT_API_PROFILES,
    HOSTED_PROFILES,
    LANE_CONTROLS,
    LANE_OF_PROFILE,
    LANE_PROFILES,
    PLACEMENT_OF_PROFILE,
)
from mission_control.domain.programs.search_attributes import MC_LANES

API_PROFILES = ("claude_managed", "codex_agents")
DIGEST = "sha256:" + "a" * 64


# --- One vocabulary: every layer names both profiles (the import guards passed to get here) ----


def test_both_profiles_join_every_vocabulary_on_their_existing_lanes() -> None:
    assert set(API_PROFILES) == set(HOSTED_AGENT_API_PROFILES)
    assert {LANE_OF_PROFILE[p] for p in API_PROFILES} == {"claude", "codex"}
    assert LANE_OF_PROFILE["claude_managed"] == "claude"
    assert LANE_OF_PROFILE["codex_agents"] == "codex"
    for profile in API_PROFILES:
        assert profile in LANE_PROFILES and LaneProfile(profile) in UNQUALIFIED_BY_DEFAULT
        # The provider runs the agent loop, so the profile is `cloud` like the hosted products.
        assert PLACEMENT_OF_PROFILE[profile] == "cloud" and profile in HOSTED_PROFILES
        assert profile in MC_LANES and profile in V2_BINDING_PROFILES
        assert PROVIDER_OF_PROFILE[profile] == profile
        assert HOOK_EVENT_MAPPING[LaneProfile(profile)] == {}
        # HL-08 classifies Managed Agents session events; the Agents API rows land with HL-12.
        assert KIND_TABLES[LaneProfile(profile)]
        assert DEDUPE_KEY_RULES[LaneProfile(profile)]
        assert SURFACES[profile].login_route is None
        assert (LaneProfile(profile), "first_prompt") in ROUTE_EVIDENCE
        assert all_profiles().status(profile) is HostSupportStatus.UNQUALIFIED


def test_their_only_auth_route_is_a_metered_api_key_that_needs_api_consent() -> None:
    for profile in API_PROFILES:
        assert set(ROUTE_TABLE[profile]) == {"api_key"}  # type: ignore[index]
        spec = route_spec(profile, "api_key")  # type: ignore[arg-type]
        assert (spec.support, spec.billing_mode) == ("documented", "api")
        assert route_spec(profile, "owner_cli_login").support == "unsupported"  # type: ignore[arg-type]


# --- Declared matrices: honest per SPEC-06 section 9 ----------------------------------------------

# HL-08: the Managed Agents session lifecycle its harness implements; nothing else is claimed.
MANAGED_IMPLEMENTED = frozenset(
    {"prepare", "start", "reattach", "send_turn", "cancel_turn", "observe", "usage", "end_session"}
)


@pytest.mark.parametrize("profile", API_PROFILES)
def test_the_declared_matrix_claims_only_what_its_lane_implements(profile: str) -> None:
    describe = DECLARED_LANE_MATRICES[profile]  # type: ignore[index]
    implemented = MANAGED_IMPLEMENTED
    assert (profile in V2_STUB_LANE_PROFILES) is not implemented
    assert (profile in V2_IMPLEMENTED_LANE_PROFILES) is bool(implemented)
    assert describe.is_v2 and describe.placement == "cloud" and not describe.qualified
    assert describe.controls == {
        control: "native" if control in implemented else "unqualified" for control in LANE_CONTROLS
    }
    for name, evidence in describe.features.items():
        assert not evidence.qualified, name
        assert describe.feature_implemented(name) is evidence.implemented, name
    if not implemented:
        assert not any(describe.feature_implemented(name) for name in describe.features)
    # No hook file runs on a hosted agent API: Kernel Hooks become Mission Control tools.
    assert describe.hooks.mechanism == "none" and not describe.hooks.events_supported
    assert describe.delivery_semantics["hard_pause"] == "unsupported"
    # The workflow's frozen tables say the same thing (pause stays boundary-only for now).
    for command, table in LANE_COMMAND_SEMANTICS.items():
        assert table[profile] == describe.delivery_semantics[command]
    assert LANE_PAUSE_SEMANTICS[profile] == describe.delivery_semantics["pause"] == "unsupported"
    assert LANE_RESUME_SEMANTICS[profile] == describe.delivery_semantics["resume"]


def test_section_9_refusals_and_observed_facts_are_declared() -> None:
    managed = DECLARED_LANE_MATRICES["claude_managed"]
    agents = DECLARED_LANE_MATRICES["codex_agents"]
    # Managed Agents: per-tool allow/deny is a provider permission; `list_cost` settles cost.
    assert "provider_permission" in managed.approval_modes
    assert (managed.usage.tokens, managed.usage.cost) == ("settled", "settled")
    assert managed.delivery_semantics["interrupt_and_inject"] == "cancel_and_replace"
    # Agents API: per-command approval is unsupported (function tools only); steering was
    # observed in the HL-23 smoke; cost is estimated from the price table.
    assert "provider_permission" not in agents.approval_modes
    assert agents.enforcement_coverage["shell"] == agents.enforcement_coverage["file"]
    assert agents.enforcement_coverage["shell"] == "unsupported"
    assert agents.delivery_semantics["interrupt_and_inject"] == "cancel_and_replace"
    assert agents.usage.cost == "unknown"


# --- The describe-only registry the API publishes ---------------------------------------------


def test_the_describe_only_registry_lists_both_profiles_unqualified_when_their_keys_are_bound() -> (
    None
):
    registry = describe_only_registry(
        bound=bound_lane_profiles(anthropic_api=True, openai_api=True),
        allow_unqualified=False,
    )
    assert registry.profiles() == ("claude_managed", "codex_agents", "deep_agents")
    for profile in API_PROFILES:
        describe = registry.describe(profile)
        assert describe.lane_profile == profile and not describe.qualified
        assert set(describe.controls.values()) == {"unqualified"}
        with pytest.raises(LaneNotQualified):
            registry.admit(profile)


def test_a_lane_credential_alone_does_not_publish_the_api_billed_profiles() -> None:
    registry = describe_only_registry(
        bound=bound_lane_profiles(claude=True, codex=True), allow_unqualified=False
    )
    assert not set(API_PROFILES) & set(registry.profiles())
    only_anthropic = describe_only_registry(
        bound=bound_lane_profiles(anthropic_api=True), allow_unqualified=False
    )
    assert only_anthropic.profiles() == ("claude_managed", "deep_agents")


# --- Host Projection: no files; every row reported, nothing silently dropped -------------------


@pytest.mark.parametrize("profile", API_PROFILES)
def test_the_projection_carries_the_instructions_and_reports_every_row(profile: str) -> None:
    from tests.fixtures.projections.rows import INSTRUCTION, fixture_rows

    rows = fixture_rows()
    projection = HOST_PROJECTORS.render(rows, profile, INSTRUCTION)
    assert projection.files == ()
    assert set(projection.send_options) == {"instructions", "hosted_skills", "hosted_mcp_servers"}
    assert INSTRUCTION.strip() in str(projection.send_options["instructions"])
    (skill,) = projection.send_options["hosted_skills"]
    assert skill["name"] == "agent-browser"
    assert skill["files"]  # plugin's exact bundle is projected, not silently dropped
    assert projection.send_options["hosted_mcp_servers"] == []
    for row in rows[1:]:
        assert row.pin.render() in projection.report.skipped_members
        assert any(row.pin.render() in note for note in projection.report.degraded)
    assert all(
        "no native hook" in note
        or "hosted MCP requires streamable HTTPS" in note
        or "hosted MCP credential transport is unavailable" in note
        or "hosted catalog hooks/subagent execution unavailable" in note
        for note in projection.report.degraded
    )


# --- mc.execution_binding.v2 options --------------------------------------------------------------


def _hosted_binding(profile: str, options: dict[str, Any], **changes: Any) -> dict[str, Any]:
    return {
        "lane_profile": profile,
        "model": {"profile": "hosted.default", "model_id": "model-from-the-registry"},
        "auth": {"profile": f"{profile}.api", "billing_mode": "api"},
        "environment": {
            "kind": "provider_hosted",
            "provider": "anthropic" if profile == "claude_managed" else "openai",
            "environment_ref": "env_fixture",
            "expected_revision": "rev-1",
        },
        "workspace_policy": {
            "mode": "provider_workspace",
            "reuse": "none",
            "dirty_input": "reject",
            "cleanup": "retain",
        },
        "materialization_digest": DIGEST,
        "requirements": {"describe_digest": DIGEST},
        "policy_digest": DIGEST,
        "pins": {"sdk.provider": "1.0.0"},
        "provider_options": options,
        "budgets": {"max_turns": 4, "max_segments": 8, "wall_clock_s": 3600},
        **changes,
    }


MANAGED = {"provider": "claude_managed", "max_list_cost_minor_units": 90}
AGENTS = {"provider": "codex_agents"}


@pytest.mark.parametrize(
    ("profile", "options"), [("claude_managed", MANAGED), ("codex_agents", AGENTS)]
)
def test_a_knowledge_binding_needs_no_repository_but_a_bound_one_is_pinned(
    profile: str, options: dict[str, Any]
) -> None:
    binding = ProviderExecutionBinding.sealed(**_hosted_binding(profile, options))
    assert binding.repo_url is None and binding.lane == LANE_OF_PROFILE[profile]
    repo = {"repo_url": "https://github.com/acme/knowledge", "repo_commit": "0123456789abcdef"}
    assert ProviderExecutionBinding.sealed(**_hosted_binding(profile, options, **repo)).repo_commit
    with pytest.raises(ValidationError, match="pins both repo_url and repo_commit"):
        ProviderExecutionBinding.sealed(
            **_hosted_binding(profile, options, repo_url=repo["repo_url"])
        )
    with pytest.raises(ValidationError, match="does not match"):
        ProviderExecutionBinding.sealed(
            **_hosted_binding(
                profile,
                options,
                environment={"kind": "local_workspace", "host_profile": "worker.linux"},
            )
        )


def test_the_options_are_typed_per_profile_and_the_self_hosted_placement_is_funding_gated() -> None:
    managed = ProviderExecutionBinding.sealed(**_hosted_binding("claude_managed", MANAGED))
    options = managed.provider_options
    assert options.provider == "claude_managed"
    assert (options.tool_placement, options.multiagent) == ("cloud", False)  # type: ignore[union-attr]
    with pytest.raises(ValidationError, match="max_list_cost_minor_units"):
        ProviderExecutionBinding.sealed(
            **_hosted_binding("claude_managed", {"provider": "claude_managed"})
        )
    with pytest.raises(ValidationError, match="carries codex_agents options, not claude_managed"):
        ProviderExecutionBinding.sealed(**_hosted_binding("codex_agents", MANAGED))
    agents = ProviderExecutionBinding.sealed(**_hosted_binding("codex_agents", AGENTS))
    assert agents.provider_options.tool_placement == "openai_hosted"  # type: ignore[union-attr]
    for profile, options in (("claude_managed", MANAGED), ("codex_agents", AGENTS)):
        with pytest.raises(ValidationError, match="funding-gated"):
            ProviderExecutionBinding.sealed(
                **_hosted_binding(profile, {**options, "tool_placement": "self_hosted"})
            )
    with pytest.raises(ValidationError):
        ProviderExecutionBinding.sealed(
            **_hosted_binding("codex_agents", {**AGENTS, "tool_placement": "cloud"})
        )


# --- Data Class (SPEC-06 section 8) ---------------------------------------------------------------


@pytest.mark.parametrize("profile", API_PROFILES)
def test_the_hosted_agent_apis_admit_only_public_and_internal_by_default(profile: str) -> None:
    for data_class in ("public", "internal"):
        assert admit_data_class(profile, data_class) is None
    for data_class in ("confidential", "phi", "secret"):
        refused = admit_data_class(profile, data_class)  # type: ignore[arg-type]
        assert refused is not None and refused.code == DATA_CLASS_NOT_ADMITTED
        assert refused.lane_profile == profile and f"not {data_class}" in refused.message
    undeclared = admit_data_class(profile, None, pointer="/mission/environment/lane")
    assert undeclared is not None and undeclared.code == DATA_CLASS_UNDECLARED
    assert undeclared.pointer == "/mission/environment/lane"


def test_every_other_profile_admits_every_class() -> None:
    for profile in set(LANE_PROFILES) - set(API_PROFILES):
        for data_class in (*DATA_CLASSES, None):
            assert admit_data_class(profile, data_class) is None


def test_an_application_may_widen_to_confidential_but_never_to_phi_or_secret() -> None:
    widened = DEFAULT_DATA_CLASS_POLICY.widened("claude_managed", ["confidential"])
    assert admit_data_class("claude_managed", "confidential", policy=widened) is None
    assert admit_data_class("codex_agents", "confidential", policy=widened) is not None
    for data_class in ("phi", "secret"):
        with pytest.raises(ValidationError, match="ceiling is confidential"):
            DEFAULT_DATA_CLASS_POLICY.widened("claude_managed", [data_class])  # type: ignore[list-item]
        with pytest.raises(ValidationError, match="ceiling"):
            DataClassPolicy(
                admitted={"claude_managed": frozenset({data_class}), "codex_agents": frozenset()}
            )
    with pytest.raises(ValidationError, match="needs a data class policy"):
        DataClassPolicy(admitted={"claude_managed": frozenset({"public"})})
    with pytest.raises(ValueError, match="no data class policy to widen"):
        DEFAULT_DATA_CLASS_POLICY.widened("codex", ["public"])
