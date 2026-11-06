"""Derived launch identity. Never modifies or substitutes for a sealed execution binding."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import Any

from mission_control.application.authoring.manifest_launch_inputs import ManifestLaunchBindings
from mission_control.application.execution.harness.describe import declared_matrix
from mission_control.domain.authoring.canonical import stable_json_digest


def binding_summary(bindings: ManifestLaunchBindings) -> dict[str, Any]:
    """Summarize reviewed selections; provider observations and freshness remain unknown.

    Only identity fields are projected. Provider options, credentials, URLs and free-form
    configuration are deliberately absent. The digest names the launch configuration,
    not a per-operation binding or the effective-configuration approval seal.
    """
    lanes: list[dict[str, Any]] = []
    if bindings.providers is not None:
        for name in (
            "claude_agent_sdk",
            "claude_managed",
            "cursor_local",
            "cursor_cloud",
            "codex_agents",
            "codex",
        ):
            lane = getattr(bindings.providers, name, None)
            if lane is None:
                continue
            pins = lane.pins if isinstance(lane.pins, dict) else lane.pins.model_dump(mode="json")
            hosts = getattr(lane, "host_profiles", {})
            lanes.append(
                {
                    "lane": name,
                    "runtime": "OpenAI hosted Agents API (HTTP)"
                    if name == "codex_agents"
                    else name,
                    "placement": "local_workspace"
                    if name in {"claude_agent_sdk", "codex", "cursor_local"}
                    else "provider_hosted",
                    "task_queue": lane.task_queue,
                    "models": [
                        {
                            "profile": key,
                            "requested_model_id": model.model_id,
                            "provider_reported_model_id": None,
                        }
                        for key, model in sorted(lane.model_profiles.items())
                    ],
                    "auth": [
                        {"profile": key, "billing_mode": auth.billing_mode}
                        for key, auth in sorted(lane.auth_profiles.items())
                    ],
                    "hosts": sorted(hosts),
                    "pins": dict(sorted(pins.items())),
                    "workspace_digests": {
                        key: value
                        for key, value in lane.workspace.model_dump(mode="json").items()
                        if key.endswith("_digest")
                    },
                    "describe_digest": stable_json_digest(declared_matrix(name)),
                    "execution_binding_digest": None,
                    "materialization_digest": None,
                    "prerequisite_freshness": "unverified",
                    "evidence_level": "declared",
                }
            )
    try:
        openai_version: str | None = version("openai")
    except PackageNotFoundError:
        openai_version = None
    return {
        "schema_version": "mc.launch_identity_summary.v1",
        "launch_configuration_digest": stable_json_digest(bindings),
        "runtime_dependencies": {"openai": openai_version},
        "lanes": lanes,
        "qualification": "unverified",
    }
