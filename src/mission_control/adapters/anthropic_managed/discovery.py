"""The `claude_managed` Discovery Proof: an API read-back of the agent a session will run
(SPEC-02 section 6; MO-34).

A Managed Agents session runs exactly the agent version `sessions.create` pins, so what the API
returns for that agent is what the session loads. The expectation (`discovery_expectation`) is
the rendered pack: its skills, its MCP servers and its materialization digest. The read-back
(`read_back`) retrieves the prepared agent and reports a skill loaded only when the agent pins
the prepared skill id at the prepared version, an MCP server when the agent declares it, and the
agent's `mc_digest` metadata as the digest it carries. A sync that drifted (another writer
updated the agent, a skill version moved) therefore fails the proof instead of passing it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from mission_control.adapters.anthropic_managed.client import ManagedAgentsClient
from mission_control.adapters.anthropic_managed.pack import RenderedPack
from mission_control.adapters.anthropic_managed.prepare import METADATA_DIGEST, PreparedPack
from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.execution.discovery import (
    DiscoveryExpectation,
    DiscoveryItem,
    DiscoveryReport,
    as_digest,
)

AGENT_DIGEST: Final = "agent"


def discovery_expectation(rendered: RenderedPack) -> DiscoveryExpectation:
    """What the read-back must report of `rendered`."""

    return DiscoveryExpectation(
        mechanism="api_readback",
        items=(
            *(DiscoveryItem(kind="skill", name=skill.name) for skill in rendered.skills),
            *(
                DiscoveryItem(kind="mcp_server", name=server.name)
                for server in rendered.pack.agent.mcp_servers
            ),
        ),
        digests={AGENT_DIGEST: rendered.materialization_digest},
    )


def _list(value: Any) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


async def read_back(client: ManagedAgentsClient, prepared: PreparedPack) -> DiscoveryReport:
    """Retrieve the prepared agent and report what it pins."""

    agent = await client.retrieve_agent(prepared.agent.agent_id)
    pinned = {
        (str(skill.get("skill_id")), str(skill.get("version")))
        for skill in _list(agent.get("skills"))
    }
    metadata = agent.get("metadata")
    digest = as_digest(metadata.get(METADATA_DIGEST)) if isinstance(metadata, Mapping) else None
    return DiscoveryReport(
        lane_profile=LaneProfile.CLAUDE_MANAGED,
        mechanism="api_readback",
        items=(
            *(
                DiscoveryItem(kind="skill", name=skill.name)
                for skill in prepared.skills
                if (skill.skill_id, skill.version_id) in pinned
            ),
            *(
                DiscoveryItem(kind="mcp_server", name=str(server["name"]))
                for server in _list(agent.get("mcp_servers"))
                if isinstance(server.get("name"), str) and 0 < len(server["name"]) <= 256
            ),
        ),
        digests={AGENT_DIGEST: digest},
        source=f"api:agents/{prepared.agent.agent_id}@{agent.get('version')}",
    )


__all__ = ["AGENT_DIGEST", "discovery_expectation", "read_back"]
