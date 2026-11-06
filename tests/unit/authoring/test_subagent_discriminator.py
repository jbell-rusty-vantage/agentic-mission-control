"""The compile-time subagent discriminator (P1 subagents): one profile, every lane the node
may run on, a verdict per requested field; seeds become the child's own capability requests;
off-lane overrides are refused. Pure over the lane support table."""

from __future__ import annotations

from mission_control.adapters.deep_agents.lane import SUBAGENT_FIELDS
from mission_control.application.authoring.subagent_discriminator import (
    SEED_OF_ATTRIBUTE,
    discriminate_subagent,
    is_subagent_seed,
    seed_owner,
)
from mission_control.application.authoring.subagent_support import (
    SUBAGENT_FIELD_SUPPORT,
    subagent_field_support,
)
from mission_control.domain.authoring.manifest import CapabilityKind
from mission_control.domain.authoring.mission_definition import (
    CapabilityPin,
    DefinitionCapability,
)
from mission_control.domain.capabilities.subagents import SUBAGENT_FIELDS as VOCABULARY
from mission_control.domain.capabilities.subagents import SubagentProfile

SKILL_PIN = "skill.probe@1#sha256:" + "a" * 64
MCP_PIN = "mcp.probe@1#sha256:" + "b" * 64
PLUGIN_PIN = "plugin.probe@1#sha256:" + "c" * 64
POINTER = "/mission/environment/agents/0"


def _entry(**attributes: object) -> DefinitionCapability:
    return DefinitionCapability(
        pointer=POINTER,
        role="agent",
        alias="reviewer",
        kind=CapabilityKind.SUBAGENT_PROFILE,
        pin=CapabilityPin(
            capability_id="subagent.reviewer", version="1", digest="sha256:" + "d" * 64
        ),
        attributes=dict(attributes),
    )


def _profile(**overrides: object) -> SubagentProfile:
    values: dict[str, object] = {
        "name": "reviewer",
        "description": "Reviews drafts.",
        "prompt": "Review the draft.",
    }
    values.update(overrides)
    return SubagentProfile.model_validate(values)


def test_every_lane_declares_every_field_once_in_the_shared_vocabulary() -> None:
    assert set(SUBAGENT_FIELD_SUPPORT) == {
        "deep_agents",
        "cursor_local",
        "cursor_cloud",
        "claude_agent_sdk",
        "codex",
        "claude_cloud",
        "codex_cloud",
        "claude_managed",
        "codex_agents",
    }
    for lane, row in SUBAGENT_FIELD_SUPPORT.items():
        assert tuple(row) == VOCABULARY, lane
    # The Deep Agents row is the adapter's own declaration, not a derivation.
    assert subagent_field_support("deep_agents") == dict(SUBAGENT_FIELDS)
    # Derived file-lane rows: what the projection writes is native, what it reports lost is
    # degraded, what it does not render at all is unsupported (until WP-S5).
    claude = subagent_field_support("claude_agent_sdk")
    assert claude["kind.sync"] == "native" and claude["max_turns"] == "native"
    assert claude["context_mode.fork"] == "degraded"
    assert claude["seeds.skills"] == "unsupported" and claude["kind.async"] == "unsupported"
    codex = subagent_field_support("codex")
    assert codex["readonly"] == "native" and codex["tools"] == "degraded"
    assert set(subagent_field_support("claude_managed").values()) == {"unsupported"}


def test_a_plain_sync_profile_is_native_on_deep_agents_and_degrades_only_what_it_sets() -> None:
    result = discriminate_subagent(
        capability=_entry(),
        profile=_profile(readonly=True),
        lanes=("deep_agents",),
        support=subagent_field_support,
    )
    assert not result.refused and result.seeds == ()
    assert result.requested == (
        "kind.sync",
        "capabilities.seeded",
        "readonly",
        "placement.in_process",
    )
    (warning,) = result.warnings
    assert warning.reason == "subagent_field_degraded"
    assert warning.pointer == f"{POINTER}/readonly"
    assert {(item.lane, item.field, item.verdict) for item in result.readings} == {
        ("deep_agents", "kind.sync", "native"),
        ("deep_agents", "capabilities.seeded", "native"),
        ("deep_agents", "readonly", "degraded"),
        ("deep_agents", "placement.in_process", "native"),
    }


def test_the_manifest_overlay_switches_fields_on_for_one_node() -> None:
    result = discriminate_subagent(
        capability=_entry(overlay={"readonly": True, "is_background": True}),
        profile=_profile(),
        lanes=("deep_agents",),
        support=subagent_field_support,
    )
    assert {item.pointer for item in result.warnings} == {
        f"{POINTER}/readonly",
        f"{POINTER}/background",
    }


def test_named_items_a_lane_cannot_honour_are_blockers_and_losses_are_warnings() -> None:
    # A seeded profile with seeds selected on a file lane: seeds are unsupported there until
    # WP-S5 renders them, and a seed is a named item, so compile refuses instead of dropping.
    result = discriminate_subagent(
        capability=_entry(),
        profile=_profile(seeds={"skills": [SKILL_PIN]}, max_turns=3),
        lanes=("claude_agent_sdk", "deep_agents"),
        support=subagent_field_support,
    )
    assert result.refused
    (blocker,) = result.blockers
    assert blocker.reason == "subagent_field_unsupported"
    assert blocker.pointer == f"{POINTER}/seeds" and "claude_agent_sdk" in blocker.message
    # max_turns degrades on deep_agents (warning) and is native on claude (no issue).
    assert [item.pointer for item in result.warnings] == [f"{POINTER}/max_turns"]
    # An async kind on a lane without async children is refused; sandbox: own only degrades.
    async_result = discriminate_subagent(
        capability=_entry(),
        profile=_profile(kind="async", sandbox="own"),
        lanes=("codex",),
        support=subagent_field_support,
    )
    assert {item.pointer for item in async_result.blockers} == {
        f"{POINTER}/kind",
        f"{POINTER}/placement",
    }
    assert {item.pointer for item in async_result.warnings} == {f"{POINTER}/sandbox"}
    # An inherit child is a named shape: refused where no adapter materializes it yet.
    inherit = discriminate_subagent(
        capability=_entry(),
        profile=SubagentProfile.model_validate(
            {"name": "general", "description": "General.", "capabilities": "inherit"}
        ),
        lanes=("cursor_local",),
        support=subagent_field_support,
    )
    assert [item.pointer for item in inherit.blockers] == [f"{POINTER}/capabilities"]


def test_seeds_become_the_childs_own_pointed_capability_requests() -> None:
    result = discriminate_subagent(
        capability=_entry(),
        profile=_profile(
            seeds={"skills": [SKILL_PIN], "mcp_servers": [MCP_PIN], "plugins": [PLUGIN_PIN]}
        ),
        lanes=("deep_agents",),
        support=subagent_field_support,
    )
    assert not result.refused
    assert [(item.pointer, item.role, item.kind) for item in result.seeds] == [
        (f"{POINTER}/seeds/skills/0", "skill", CapabilityKind.SKILL_BUNDLE),
        (f"{POINTER}/seeds/mcp_servers/0", "capability", CapabilityKind.MCP_SERVER),
        (f"{POINTER}/seeds/plugins/0", "plugin", CapabilityKind.PLUGIN),
    ]
    for seed in result.seeds:
        assert is_subagent_seed(seed) and seed_owner(seed) == "reviewer"
        assert seed.attributes["provenance"] == "subagent:reviewer"
        assert seed.attributes["lanes"] == ["deep_agents"]
        assert seed.pin is not None and seed.pin.digest is not None
    assert not is_subagent_seed(_entry()) and seed_owner(_entry()) is None
    # A plugin seed degrades on this lane (hook, prompt, resource members are deferred).
    assert [item.pointer for item in result.warnings] == [f"{POINTER}/seeds"]


def test_overrides_for_a_lane_the_node_does_not_run_on_are_refused() -> None:
    result = discriminate_subagent(
        capability=_entry(),
        profile=_profile(provider_overrides={"deep_agents": {"writable_root": "/subagents/r"}}),
        lanes=("claude_agent_sdk",),
        support=subagent_field_support,
    )
    (blocker,) = [item for item in result.blockers if "provider_overrides" in item.pointer]
    assert blocker.reason == "subagent_override_lane_mismatch"
    assert blocker.pointer == f"{POINTER}/provider_overrides/deep_agents"
    assert SEED_OF_ATTRIBUTE not in _entry().attributes
