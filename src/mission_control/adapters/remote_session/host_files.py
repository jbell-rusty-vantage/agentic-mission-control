"""The hosted agent APIs' Host Projection writer (SPEC-06; HL-21; moved here by OC-R3).

`claude_managed` and `codex_agents` take no repository files: the instruction, the Skills and
the streamable-HTTPS MCP servers become provider API targets in `send_options`
(`hosted_skills`, `hosted_mcp_servers`) that `projection.py` turns into each lane's reviewed
agent definition. Catalog hooks and subagent programs have no trusted executor on a hosted
API, so they are reported and skipped, never silently dropped. It lives in the remote-session
base (ADR-0052) because both hosted lanes share it. The lane-neutral checks, reports and
helpers are `application/agentic_components/projections.py`; bootstrap composes `HOST_FILES`.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from typing import Final

from mission_control.application.agentic_components.projections import (
    KernelSurface,
    LaneHostFiles,
    ProjectionInputs,
    ProjectionState,
    mcp_launch,
    server_name,
)
from mission_control.domain.agentic_components.projection import (
    InProcessProjection,
    ResolvedCapability,
)
from mission_control.domain.authoring.contracts import SkillDefinition


class HostedAgentApiHostFiles:
    """`LaneHostFiles` of the hosted agent API profiles."""

    kernel_surface: KernelSurface = "native_hook"

    def write(self, inputs: ProjectionInputs, state: ProjectionState) -> InProcessProjection | None:
        _hosted_agent_api(
            inputs.skills,
            inputs.servers,
            inputs.hooks,
            inputs.agents,
            inputs.instructions,
            state,
        )
        return None


def _hosted_agent_api(
    skills: Sequence[ResolvedCapability],
    servers: Sequence[ResolvedCapability],
    hooks: Sequence[ResolvedCapability],
    agents: Sequence[ResolvedCapability],
    instructions: str,
    state: ProjectionState,
) -> None:
    """Provider API targets consumed by the hosted projection adapter (HL-21)."""
    state.send_options["instructions"] = instructions
    projected_skills = []
    for row in skills:
        definition = row.definition
        assert isinstance(definition, SkillDefinition)
        projected_skills.append(
            {
                "name": definition.skill_name,
                "description": str(
                    definition.frontmatter.get("description") or definition.body_summary
                ),
                "files": [
                    {"path": item.path, "content_base64": base64.b64encode(item.content).decode()}
                    for item in row.files
                ],
            }
        )
    state.send_options["hosted_skills"] = projected_skills
    projected_servers = []
    for row in servers:
        launch = mcp_launch(row, state.lane)
        if launch.transport != "streamable_http" or launch.url is None:
            state.skipped.append(row.pin.render())
            state.degraded.append(f"{row.pin.render()}: hosted MCP requires streamable HTTPS")
            continue
        if not launch.url.startswith("https://") or launch.env_refs or launch.header_refs:
            state.skipped.append(row.pin.render())
            state.degraded.append(
                f"{row.pin.render()}: hosted MCP credential transport is unavailable"
            )
            continue
        projected_servers.append(
            {"name": server_name(row), "url": launch.url, "allowed_tools": list(launch.tools)}
        )
    state.send_options["hosted_mcp_servers"] = projected_servers
    # Arbitrary catalog callbacks and subagent programs have no implemented trusted executor.
    # Refuse rather than silently omit selected behavior from the provider definition.
    if hooks or agents:
        names = ", ".join(row.pin.render() for row in (*hooks, *agents))
        state.skipped.extend(row.pin.render() for row in (*hooks, *agents))
        state.degraded.append(f"hosted catalog hooks/subagent execution unavailable: {names}")


HOST_FILES: Final[Mapping[str, LaneHostFiles]] = {
    "claude_managed": HostedAgentApiHostFiles(),
    "codex_agents": HostedAgentApiHostFiles(),
}

__all__ = ["HOST_FILES", "HostedAgentApiHostFiles"]
