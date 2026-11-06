"""`mc.subagent_profile.v1` kinds and child shapes (P1-S3, P1 subagents Q7): additive,
digest-stable, placement-checked, typed per-lane overrides, the two child shapes."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.capabilities.subagent_overrides import (
    DeepAgentsSubagentOverrides,
    parse_subagent_overrides,
    subagent_overrides_lane_mismatch,
)
from mission_control.domain.capabilities.subagents import SUBAGENT_FIELDS, SubagentProfile

BASE = {"name": "reviewer", "description": "Reviews drafts.", "prompt": "Review."}
SKILL_PIN = "skill.probe@1#sha256:" + "a" * 64
MCP_PIN = "mcp.probe@1#sha256:" + "b" * 64
PLUGIN_PIN = "plugin.probe@1#sha256:" + "c" * 64


def test_defaults_are_sync_in_process_seeded_and_leave_published_digests_unchanged() -> None:
    profile = SubagentProfile.model_validate(BASE)
    assert profile.kind == "sync"
    assert profile.effective_placement == "in_process"
    assert profile.sandbox == "shared"
    assert profile.capabilities == "seeded" and profile.seeds is None
    dumped = profile.model_dump(mode="json")
    assert not {
        "kind",
        "placement",
        "sandbox",
        "budget",
        "provider_overrides",
        "capabilities",
        "seeds",
    } & set(dumped)
    # The digest of a profile published before these fields existed is reproduced exactly.
    assert sha256_digest(profile) == sha256_digest(SubagentProfile.model_validate(BASE))


def test_kinds_default_their_placement_and_refuse_impossible_ones() -> None:
    assert SubagentProfile.model_validate({**BASE, "kind": "async"}).effective_placement == (
        "agent_server"
    )
    assert SubagentProfile.model_validate({**BASE, "kind": "linked_run"}).effective_placement == (
        "lane"
    )
    with pytest.raises(ValidationError, match="cannot be placed"):
        SubagentProfile.model_validate({**BASE, "kind": "sync", "placement": "agent_server"})
    explicit = SubagentProfile.model_validate({**BASE, "kind": "async", "placement": "lane"})
    assert explicit.model_dump(mode="json")["placement"] == "lane"


def test_budget_and_overrides_are_validated_and_typed_per_lane() -> None:
    with pytest.raises(ValidationError, match="positive amount"):
        SubagentProfile.model_validate({**BASE, "budget": {"tokens.total": 0}})
    with pytest.raises(ValidationError, match="unknown lane profiles"):
        SubagentProfile.model_validate({**BASE, "provider_overrides": {"nope": {}}})
    # A lane without a registered overrides model accepts no key (the provider options rule).
    with pytest.raises(ValidationError, match="no typed subagent overrides"):
        SubagentProfile.model_validate({**BASE, "provider_overrides": {"codex": {"model": "x"}}})
    # A registered lane validates its block; unknown fields are refused, not carried.
    with pytest.raises(ValidationError, match="extra_forbidden|Extra inputs"):
        SubagentProfile.model_validate(
            {**BASE, "provider_overrides": {"deep_agents": {"interrupt_on": ["write_file"]}}}
        )
    profile = SubagentProfile.model_validate(
        {**BASE, "provider_overrides": {"deep_agents": {"writable_root": "/subagents/r"}}}
    )
    assert profile.overrides_for("deep_agents") == {"writable_root": "/subagents/r"}
    assert profile.overrides_for("codex") == {}
    parsed = parse_subagent_overrides("deep_agents", profile.overrides_for("deep_agents"))
    assert isinstance(parsed, DeepAgentsSubagentOverrides)
    assert parsed.writable_root == "/subagents/r"
    assert subagent_overrides_lane_mismatch(profile.provider_overrides, lanes=("codex",)) == (
        "deep_agents",
    )
    assert (
        subagent_overrides_lane_mismatch(profile.provider_overrides, lanes=("deep_agents",)) == ()
    )


def test_an_inherit_child_may_omit_its_prompt_and_names_nothing_of_its_own() -> None:
    general = SubagentProfile.model_validate(
        {"name": "general", "description": "The parent's general child.", "capabilities": "inherit"}
    )
    assert general.inherits and general.prompt is None
    assert general.model_dump(mode="json")["capabilities"] == "inherit"
    with pytest.raises(ValidationError, match="cannot name tools, skills, mcp_servers or seeds"):
        SubagentProfile.model_validate(
            {**BASE, "capabilities": "inherit", "tools": ("write_file",)}
        )
    with pytest.raises(ValidationError, match="exactly one of prompt or prompt_bundle_ref"):
        SubagentProfile.model_validate({"name": "bare", "description": "No prompt."})
    with pytest.raises(ValidationError, match="one of prompt or prompt_bundle_ref"):
        SubagentProfile.model_validate({**BASE, "prompt_bundle_ref": "bundle:x"})


def test_seeds_are_exact_distinct_pins_grouped_by_kind() -> None:
    profile = SubagentProfile.model_validate(
        {
            **BASE,
            "seeds": {"skills": [SKILL_PIN], "mcp_servers": [MCP_PIN], "plugins": [PLUGIN_PIN]},
        }
    )
    assert profile.seeds is not None
    assert profile.seeds.groups() == ("skills", "mcp_servers", "plugins")
    assert [(group, pin.capability_id) for group, pin in profile.seeds.items()] == [
        ("skills", "skill.probe"),
        ("mcp_servers", "mcp.probe"),
        ("plugins", "plugin.probe"),
    ]
    with pytest.raises(ValidationError, match="at least one pin"):
        SubagentProfile.model_validate({**BASE, "seeds": {}})
    with pytest.raises(ValidationError, match="each capability once"):
        SubagentProfile.model_validate(
            {**BASE, "seeds": {"skills": [SKILL_PIN], "tools": [SKILL_PIN]}}
        )
    with pytest.raises(ValidationError, match="Capability Pin"):
        SubagentProfile.model_validate({**BASE, "seeds": {"skills": ["skill.probe@latest"]}})


def test_requested_fields_speak_the_shared_vocabulary_including_the_manifest_overlay() -> None:
    profile = SubagentProfile.model_validate(
        {
            **BASE,
            "kind": "async",
            "mcp_servers": ("probe",),
            "max_turns": 3,
            "sandbox": "own",
            "budget": {"tokens.total": 10},
            "seeds": {"skills": [SKILL_PIN]},
        }
    )
    requested = profile.requested_fields()
    assert requested == (
        "kind.async",
        "capabilities.seeded",
        "seeds.skills",
        "mcp_servers",
        "max_turns",
        "sandbox.own",
        "budget",
        "placement.agent_server",
    )
    assert set(requested) <= set(SUBAGENT_FIELDS)
    with_overlay = profile.requested_fields({"readonly": True, "model": "frontier.fast"})
    assert "readonly" in with_overlay and "model" in with_overlay
    general = SubagentProfile.model_validate(
        {"name": "general", "description": "General.", "capabilities": "inherit"}
    )
    assert general.requested_fields() == (
        "kind.sync",
        "capabilities.inherit",
        "placement.in_process",
    )
