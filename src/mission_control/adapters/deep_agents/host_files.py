"""The Deep Agents lane's Host Projection (SPEC-01; ADR-0005; moved here by OC-R3).

No repository files: the lane's in-process objects (`InProcessProjection`): the instruction as
`/memory/AGENTS.md`, Skills under `/skills/{kernel,mission}/`, MCP connections with unresolved
`*_refs`, hook middleware (Kernel Hooks first, then catalog hook scripts with their entrypoints)
and the `SubAgent` dicts. The lane-neutral checks, reports and helpers are
`application/agentic_components/projections.py`; bootstrap composes `HOST_FILES`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Final

from mission_control.application.agentic_components.projections import (
    KernelSurface,
    LaneHostFiles,
    ProjectionInputs,
    ProjectionState,
    hook_dir,
    host_overlay,
    mcp_launch,
    server_name,
    skill_files,
    skill_name,
    subagent,
    subagent_model,
    subagent_prompt,
    write_hook_scripts,
)
from mission_control.domain.agentic_components.projection import (
    InProcessProjection,
    KernelHook,
    ResolvedCapability,
)
from mission_control.domain.authoring.contracts import HookScriptDefinition
from mission_control.domain.capabilities.hooks import native_hook

_INTERPRETER_COMMAND = {"sh": "sh", "bash": "bash", "python": "python", "node": "node"}


class DeepAgentsHostFiles:
    """`LaneHostFiles` of `deep_agents`."""

    kernel_surface: KernelSurface = "native_hook"

    def write(self, inputs: ProjectionInputs, state: ProjectionState) -> InProcessProjection | None:
        return _deep_agents(
            inputs.skills,
            inputs.servers,
            inputs.hooks,
            inputs.agents,
            inputs.kernel_hooks,
            state,
            inputs.instructions,
            system_prompt=inputs.instruction,
            agent_server_bound=inputs.agent_server_bound,
        )


def _deep_agents(
    skills: Sequence[ResolvedCapability],
    servers: Sequence[ResolvedCapability],
    hooks: Sequence[ResolvedCapability],
    agents: Sequence[ResolvedCapability],
    kernel_hooks: Sequence[KernelHook],
    state: ProjectionState,
    instructions: str,
    *,
    system_prompt: str,
    agent_server_bound: bool,
) -> InProcessProjection:
    lane = state.lane
    state.write("memory/AGENTS.md", instructions)
    scopes: list[str] = []
    for scope in ("kernel", "mission"):
        scoped = [row for row in skills if row.scope == scope]
        if scoped:
            scopes.append(f"/skills/{scope}/")
            for row in scoped:
                for path, content, mode in skill_files(row, state):
                    state.write(f"skills/{scope}/{skill_name(row)}/{path}", content, mode)
    write_hook_scripts(hooks, state, runner=False)
    connections: dict[str, dict[str, object]] = {}
    for row in servers:
        launch = mcp_launch(row, lane)
        connection: dict[str, object] = {"transport": launch.transport}
        if launch.transport == "stdio":
            connection.update(command=launch.command, args=list(launch.args))
            if launch.env:
                connection["env"] = dict(launch.env)
            if launch.env_refs:
                connection["env_refs"] = dict(launch.env_refs)
        else:
            connection["url"] = launch.url
            if launch.header_refs:
                connection["header_refs"] = dict(launch.header_refs)
        if launch.tools:
            connection["tool_allowlist"] = list(launch.tools)
        connections[server_name(row)] = connection
    middleware: list[dict[str, object]] = [
        {"hook_id": hook.hook_id, "kernel": True, "events": [e.value for e in hook.events]}
        for hook in kernel_hooks
    ]
    for row in hooks:
        definition = row.definition
        assert isinstance(definition, HookScriptDefinition)
        supported = [e.value for e in definition.events if native_hook(lane, e) is not None]
        middleware.append(
            {
                "hook_id": definition.logical_id,
                "kernel": False,
                "events": supported,
                "matcher": host_overlay(row, lane).get("matcher", definition.matcher),
                "timeout_seconds": definition.timeout_seconds,
                "fail_closed": definition.fail_closed,
                "interpreter": _INTERPRETER_COMMAND[definition.interpreter.value],
                "entrypoint": f"{hook_dir(row)}/{definition.entrypoint}",
                "callback": definition.callback.value,
            }
        )
    subagents: list[dict[str, object]] = []
    for row in agents:
        profile = subagent(row).profile
        agent: dict[str, object] = {
            "name": profile.name,
            "description": profile.description,
            "system_prompt": subagent_prompt(row),
        }
        model = subagent_model(row, lane)
        if model != "inherit":
            agent["model"] = model
        if profile.tools:
            agent["tools"] = list(profile.tools)
        if profile.skills:
            agent["skills"] = list(profile.skills)
        if profile.interrupt_on:
            agent["interrupt_on"] = dict.fromkeys(profile.interrupt_on, True)
        if profile.readonly:
            agent["permissions"] = [
                {"operations": ["write", "edit", "execute"], "mode": "deny", "path": "/"}
            ]
        if profile.background:
            if agent_server_bound:
                agent["background"] = True
            else:
                state.degraded.append(
                    f"subagent {profile.name}: background requested without an Agent Server; "
                    "projected synchronous"
                )
        subagents.append(agent)
    return InProcessProjection(
        system_prompt=system_prompt,
        memory=("/memory/AGENTS.md",),
        skills=tuple(scopes),
        subagents=tuple(subagents),
        mcp_connections=connections,
        hook_middleware=tuple(middleware),
    )


HOST_FILES: Final[Mapping[str, LaneHostFiles]] = {"deep_agents": DeepAgentsHostFiles()}

__all__ = ["HOST_FILES", "DeepAgentsHostFiles"]
