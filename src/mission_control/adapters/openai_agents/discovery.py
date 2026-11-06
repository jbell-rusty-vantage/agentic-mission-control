"""The `codex_agents` Discovery Proof: an API read-back of the saved agent and environment
template a session will run (SPEC-06 section 5.1, SPEC-02 section 6; MO-34).

A session is created from the prepared saved agent and template, so what the Agents API
returns for them is what the session loads. The expectation (`discovery_expectation`) is the
pack: its inline skills, its MCP servers and its pack digest. The read-back (`read_back`) finds
both resources by id through the listings prepare already uses, and reports the template's
inline skills by name, the agent's `mcp` tools by `server_label` and the agent's `mc_pack`
metadata as the digest it carries.

The read-back shapes follow the request bodies prepare sends (pinned `openai` 3.29.0 types;
`tests/unit/openai_agents/support.py`); the live response shape is UNVERIFIED until the
HL-11..HL-13 drills record it, so a field the API leaves out fails the proof instead of passing it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import Any, Final

from mission_control.adapters.openai_agents.client import AgentsApiClient
from mission_control.adapters.openai_agents.pack import CodexAgentsPack
from mission_control.adapters.openai_agents.prepare import PACK_KEY, PreparedCodexAgents
from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.execution.discovery import (
    DiscoveryExpectation,
    DiscoveryItem,
    DiscoveryReport,
    as_digest,
)

AGENT_DIGEST: Final = "agent"
_NAME_LIMIT: Final = 256


def discovery_expectation(pack: CodexAgentsPack) -> DiscoveryExpectation:
    """What the read-back must report of `pack`."""

    return DiscoveryExpectation(
        mechanism="api_readback",
        items=(
            *(DiscoveryItem(kind="skill", name=skill.name) for skill in pack.skills),
            *(
                DiscoveryItem(kind="mcp_server", name=server.server_label)
                for server in pack.document.agent.mcp_servers
            ),
        ),
        digests={AGENT_DIGEST: pack.digest},
    )


async def _by_id(listing: AsyncIterator[dict[str, Any]], resource_id: str) -> dict[str, Any]:
    async for item in listing:
        if item.get("id") == resource_id:
            return item
    return {}


def _named(values: Any, field: str) -> list[str]:
    return [
        str(item[field])
        for item in (values if isinstance(values, list) else ())
        if isinstance(item, Mapping)
        and isinstance(item.get(field), str)
        and 0 < len(item[field]) <= _NAME_LIMIT
    ]


async def read_back(client: AgentsApiClient, prepared: PreparedCodexAgents) -> DiscoveryReport:
    """Find the prepared agent and template and report what they carry."""

    agent = await _by_id(client.agents(), prepared.agent.id)
    template = await _by_id(client.environment_templates(), prepared.template.id)
    metadata = agent.get("metadata")
    listed = agent.get("tools")
    tools = [
        tool
        for tool in (listed if isinstance(listed, list) else ())
        if isinstance(tool, Mapping) and tool.get("type") == "mcp"
    ]
    return DiscoveryReport(
        lane_profile=LaneProfile.CODEX_AGENTS,
        mechanism="api_readback",
        items=(
            *(
                DiscoveryItem(kind="skill", name=name)
                for name in _named(template.get("skills"), "name")
            ),
            *(
                DiscoveryItem(kind="mcp_server", name=name)
                for name in _named(tools, "server_label")
            ),
        ),
        digests={
            AGENT_DIGEST: (
                as_digest(metadata.get(PACK_KEY)) if isinstance(metadata, Mapping) else None
            )
        },
        source=f"api:agents/{prepared.agent.id}+templates/{prepared.template.id}",
    )


__all__ = ["AGENT_DIGEST", "discovery_expectation", "read_back"]
