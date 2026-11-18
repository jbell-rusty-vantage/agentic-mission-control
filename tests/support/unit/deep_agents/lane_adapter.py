"""Builders, constants and fakes that other test files import.

Moved from tests/unit/deep_agents/test_lane_adapter.py.
"""

from __future__ import annotations

from typing import Any

from mission_control.adapters.deep_agents.lane import DeepAgentsNodeInputs
from mission_control.domain.capabilities.subagents import SubagentProfile
from tests.support.deep_agents import exact_fixture

POINTER = "/mission/program/nodes/0"


def _inputs(**overrides: Any) -> DeepAgentsNodeInputs:
    binding, profile, _bundle = exact_fixture(include_mcp=True)
    values: dict[str, Any] = {
        "pointer": POINTER,
        "model": binding.model,
        "sandbox": binding.sandbox,
        "mcp_servers": binding.mcp_servers,
        "skills": binding.skills,
        "tools": binding.tools,
        "subagents": (),
        "provider_options": None,
        "delegation_ceiling": profile.delegation_ceiling,
        "state_schema": binding.cognitive_state_schema,
        "context_schema": binding.cognitive_context_schema,
        "placement_sandbox_backends": frozenset({"state"}),
        "authority_refs": binding.authority_refs,
        "model_profiles": {},
        "served_models": frozenset({binding.model.ref.digest}),
        "async_graphs": {},
    }
    values.update(overrides)
    return DeepAgentsNodeInputs(**values)


def _profile(**overrides: Any) -> SubagentProfile:
    values: dict[str, Any] = {
        "name": "reviewer",
        "description": "Reviews the draft.",
        "prompt": "You review drafts and answer with findings.",
    }
    values.update(overrides)
    return SubagentProfile.model_validate(values)
