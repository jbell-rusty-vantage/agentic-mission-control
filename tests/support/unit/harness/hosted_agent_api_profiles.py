"""Builders, constants and fakes that other test files import.

Moved from tests/unit/harness/test_hosted_agent_api_profiles.py.
"""

from __future__ import annotations

from typing import Any

DIGEST = "sha256:" + "a" * 64


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
