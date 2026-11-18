"""Builders, constants and fakes that other test files import.

Moved from tests/integration/temporal/test_manifest_v2_provider_launch.py.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mission_control.application.authoring.manifest_launch_inputs import ManifestLaunchBindings
from mission_control.application.authoring.provider_launch import ProviderLaneBinding

ROOT = Path(__file__).resolve().parents[4]


BINDINGS_EXAMPLE = (
    ROOT / "deployments/examples/manifest-launch-bindings.multi-provider.codex-0.162.1.example.json"
)
AUTH_PROFILES = {
    "claude_agent_sdk": "claude-sdk-owner-subscription",
    "codex": "codex-owner-chatgpt",
}


def provider_lane(
    bindings: ManifestLaunchBindings, profile: str, task_queue: str
) -> ProviderLaneBinding:
    """The example's provider lane, on the test queue and the stack's own scaffold refs."""

    document = json.loads(BINDINGS_EXAMPLE.read_text(encoding="utf-8"))
    lane = document["providers"][profile]
    scaffold = bindings.deep_agents
    lane.update(
        task_queue=task_queue,
        agent_profile_ref=scaffold.agent_profile_ref.model_dump(mode="json"),
        tracing_policy_ref=scaffold.tracing_policy_ref,
        sensitive_data_policy_ref=scaffold.sensitive_data_policy_ref,
        snapshot_policy_ref=scaffold.snapshot_policy_ref,
        workspace=scaffold.workspace.model_dump(mode="json"),
    )
    return ProviderLaneBinding.model_validate(lane)


class _PayloadInputs:
    """Governed read-only workspace inputs from the content-addressed payload store (the
    production worker's reader, `deployment_composition._DurableInputsFromPayloads`)."""

    def __init__(self, payloads: Any) -> None:
        self._payloads = payloads

    async def retrieve(self, durable_ref: str) -> bytes:
        from mission_control.application.artifacts.artifact_promotion import ArtifactPayloadAddress

        object_ref, _, rest = durable_ref.partition("#")
        digest, _, size = rest.rpartition(":")
        data: bytes = await self._payloads.retrieve(
            ArtifactPayloadAddress(
                object_ref=object_ref, content_digest=digest, size_bytes=int(size)
            )
        )
        return data
