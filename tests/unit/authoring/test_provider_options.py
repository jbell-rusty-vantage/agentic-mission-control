"""Manifest `provider_options` (P1-S2): discriminated by lane profile, refused off-lane."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mission_control.domain.authoring.manifest import Environment, _lane_issues
from mission_control.domain.authoring.provider_options import (
    PROVIDER_OPTIONS_MODELS,
    DeepAgentsProviderOptions,
    parse_provider_options,
    provider_options_lane_mismatch,
)


def test_deep_agents_options_validate_and_store_canonically() -> None:
    environment = Environment.model_validate(
        {
            "lane": "deep_agents",
            "provider_options": {
                "deep_agents": {
                    "sandbox_backend": "docker",
                    "summarization": {"trigger_messages": 30},
                }
            },
        }
    )
    assert environment.provider_options is not None
    stored = environment.provider_options["deep_agents"]
    assert stored["schema_version"] == "mc.provider_options.deep_agents.v1"
    assert stored["summarization"] == {
        "trigger_messages": 30,
        "trigger_tokens": None,
        "keep_messages": 20,
    }
    parsed = parse_provider_options("deep_agents", stored)
    assert isinstance(parsed, DeepAgentsProviderOptions)
    # Unset options leave the authored document and its digest untouched.
    assert "provider_options" not in Environment.model_validate({"lane": "deep_agents"}).authored()


def test_unknown_lanes_and_unknown_fields_are_refused() -> None:
    with pytest.raises(ValidationError, match="has no provider options"):
        Environment.model_validate({"lane": "codex", "provider_options": {"codex": {}}})
    with pytest.raises(ValidationError, match="extra_forbidden|Extra inputs"):
        Environment.model_validate(
            {"lane": "deep_agents", "provider_options": {"deep_agents": {"bogus": 1}}}
        )
    with pytest.raises(ValidationError, match="trigger_messages or trigger_tokens"):
        Environment.model_validate(
            {"lane": "deep_agents", "provider_options": {"deep_agents": {"summarization": {}}}}
        )
    assert set(PROVIDER_OPTIONS_MODELS) == {"deep_agents"}


def test_options_for_a_lane_the_node_does_not_run_on_are_a_blocker() -> None:
    assert provider_options_lane_mismatch(
        {"deep_agents": {}}, lane="codex", candidate_lanes=()
    ) == ("deep_agents",)
    assert (
        provider_options_lane_mismatch(
            {"deep_agents": {}}, lane="codex", candidate_lanes=("deep_agents",)
        )
        == ()
    )
    assert provider_options_lane_mismatch({"deep_agents": {}}, lane=None, candidate_lanes=()) == ()
    environment = Environment.model_validate(
        {"lane": "cursor_local", "provider_options": {"deep_agents": {}}}
    )
    blockers, _warnings = _lane_issues(environment, "/mission/environment", mission_level=False)
    assert [
        (item.pointer, item.reason)
        for item in blockers
        if item.reason == "provider_options_lane_mismatch"
    ] == [("/mission/environment/provider_options/deep_agents", "provider_options_lane_mismatch")]
