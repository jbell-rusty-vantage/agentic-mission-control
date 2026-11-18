"""Builders, constants and fakes that other test files import.

Moved from tests/unit/runtime/test_local_readiness.py.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mission_control.bootstrap.preflight import LocalRunProfile
from mission_control.domain.authoring.canonical import sha256_digest

ROOT = Path(__file__).resolve().parents[4]
EXAMPLES = ROOT / "deployments" / "examples"
BINDINGS_EXAMPLE = EXAMPLES / "manifest-launch-bindings.deep-agents.example.json"
AUTH_EXAMPLE = EXAMPLES / "provider-auth-profiles.example.json"
PROFILE_EXAMPLE = EXAMPLES / "local-run-profile.example.json"


EXPECTED_OWNER_POINTERS = {
    "/deep_agents/agent_profile_ref/digest",
    "/deep_agents/authority_refs/0",
    "/deep_agents/profile/backend_ref/digest",
    "/deep_agents/profile/context_assembly_ref/digest",
    "/deep_agents/profile/model/model_name",
    "/deep_agents/profile/prompt_refs/0/digest",
    "/deep_agents/profile/tracing_policy_ref/digest",
    "/deep_agents/redaction_policy_ref",
    "/deep_agents/sensitive_data_policy_ref",
    "/deep_agents/snapshot_policy_ref",
    "/deep_agents/tracing_policy_ref",
    "/deep_agents/workspace/environment_digest",
    "/deep_agents/workspace/image_digest",
    "/deep_agents/workspace/package_digest",
    "/deep_agents/workspace/provider",
    "/deep_agents/workspace/runtime_digest",
}


def profile(**changes: Any) -> LocalRunProfile:
    document = json.loads(PROFILE_EXAMPLE.read_text(encoding="utf-8"))
    document["temporal_clusters"] = document["temporal_clusters"][:1]
    document.update(changes)
    return LocalRunProfile.model_validate(document)


def owner_selections() -> dict[str, object]:
    """Values standing for an owner's reviewed choices (FIXTURE: not real policy refs)."""

    digest = sha256_digest("fixture-owner-choice")
    return {
        pointer: digest
        if pointer.endswith("digest")
        else ["authority:fixture"]
        if pointer == "/deep_agents/authority_refs"
        else f"fixture:{pointer.rsplit('/', 1)[-1]}"
        for pointer in (
            *(p for p in EXPECTED_OWNER_POINTERS if p != "/deep_agents/authority_refs/0"),
            "/deep_agents/authority_refs",
        )
    }
