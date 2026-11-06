"""The Cursor profiles' Host Projection writer (SPEC-01; ADR-0030; moved here by OC-R3).

`cursor_local` and `cursor_cloud`: the always-apply rule `.cursor/rules/mc-mission.mdc` (the
repository's `AGENTS.md` stays), `.cursor/skills`, `.cursor/mcp.json` with `${env:NAME}`
references (the cloud profile ignores the project MCP file, so its servers travel inline in
`send_options["mcp_servers"]`, sent with every create and every run), `.cursor/hooks.json` with
the Kernel Hooks first and fail-closed, `.cursor/agents/*.md` and the inline subagents the
launch definition carries. The hook runner and the gate answer in this package's
`hook_output.py`. The lane-neutral checks, reports and helpers are
`application/agentic_components/projections.py`; bootstrap composes `HOST_FILES`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

from mission_control.application.agentic_components.projections import (
    KernelSurface,
    LaneHostFiles,
    ProjectionInputs,
    ProjectionState,
    dumps_json,
    file_server_name,
    frontmatter,
    hook_entries,
    host_overlay,
    json_mcp_entry,
    mcp_environment_names,
    mcp_launch,
    place_native_output,
    server_name,
    shell_join,
    subagent,
    subagent_file_only,
    subagent_model,
    subagent_path,
    subagent_prompt,
    write_hook_scripts,
    write_skills,
    write_telemetry_pack,
)
from mission_control.domain.agentic_components.projection import (
    InProcessProjection,
    KernelHook,
    ProjectionError,
    ResolvedCapability,
)
from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.capabilities.layouts import LaneLayout

HOOK_OUTPUT_SOURCE: Final = Path(__file__).with_name("hook_output.py")


class CursorHostFiles:
    """`LaneHostFiles` of both Cursor profiles (the layout table tells them apart)."""

    kernel_surface: KernelSurface = "native_hook"

    def write(self, inputs: ProjectionInputs, state: ProjectionState) -> InProcessProjection | None:
        write_skills(inputs.skills, state.layering.skills, state)
        if state.telemetry:
            write_telemetry_pack(inputs.skills, state)
        write_hook_scripts(inputs.hooks, state)
        place_native_output(inputs.hooks, state, HOOK_OUTPUT_SOURCE)
        _cursor(
            inputs.servers,
            inputs.hooks,
            inputs.agents,
            inputs.kernel_hooks,
            inputs.instructions,
            state,
        )
        return None


def _cursor_agent_md(row: ResolvedCapability, lane: LaneProfile) -> str:
    profile = subagent(row).profile
    overlay = host_overlay(row, lane)
    return frontmatter(
        (
            ("name", profile.name),
            ("description", profile.description),
            ("model", subagent_model(row, lane)),
            ("readonly", bool(overlay.get("readonly", profile.readonly))),
            ("is_background", bool(overlay.get("is_background", profile.background))),
        ),
        subagent_prompt(row),
    )


def _cursor(
    servers: Sequence[ResolvedCapability],
    hooks: Sequence[ResolvedCapability],
    agents: Sequence[ResolvedCapability],
    kernel_hooks: Sequence[KernelHook],
    instructions: str,
    state: ProjectionState,
) -> None:
    lane, layout, layering = state.lane, state.layout, state.layering
    # Cursor ignores a plain `.md` file in `.cursor/rules`; the repository's AGENTS.md stays.
    state.write(
        layering.overlay,
        "---\ndescription: Mission Control mission instructions\nalwaysApply: true\n---\n\n"
        + instructions,
    )
    if servers:
        entries = {file_server_name(row): json_mcp_entry(row, lane, cursor=True) for row in servers}
        if layout.mcp_inline is not None:
            _inline_mcp_servers(servers, entries, layout, state)
        else:
            assert layout.mcp_file is not None
            state.write(layout.mcp_file, dumps_json({"mcpServers": entries}))
        state.environment_names.update(mcp_environment_names(servers, lane, oauth_refs=True))
    events: dict[str, list[dict[str, object]]] = {}
    for entry in hook_entries(lane, kernel_hooks, hooks, state.telemetry_hooks):
        item: dict[str, object] = {
            "type": "command",
            "command": shell_join(entry.command),
            "timeout": entry.timeout,
            "failClosed": entry.fail_closed,
        }
        if entry.matcher:
            item["matcher"] = entry.matcher
        events.setdefault(entry.native.native_event, []).append(item)
    if events:
        assert layout.hooks_file is not None
        state.write(layout.hooks_file, dumps_json({"version": 1, "hooks": events}))
    subagents = layout.subagents
    assert subagents is not None
    inline: list[dict[str, object]] = []
    for row in agents:
        profile = subagent(row).profile
        state.write(subagent_path(layering, profile.name), _cursor_agent_md(row, lane))
        if not subagent_file_only(row, subagents, lane) and not subagent(row).secret_refs:
            inline.append(
                {
                    "name": profile.name,
                    "description": profile.description,
                    "prompt": subagent_prompt(row),
                    "model": subagent_model(row, lane),
                }
            )
    limit = subagents.inline_limit
    if limit is not None and len(inline) > limit:
        state.overflow.append(
            f"{lane.value} inline subagent limit {limit} exceeded ({len(inline)} inline "
            f"subagents); the rest load from {layering.agents} only"
        )
        inline = inline[:limit]
    state.send_options["setting_sources"] = ["project"]
    if inline:
        state.send_options["agents"] = inline


def _inline_mcp_servers(
    servers: Sequence[ResolvedCapability],
    entries: dict[str, dict[str, object]],
    layout: LaneLayout,
    state: ProjectionState,
) -> None:
    """MCP servers the lane sends with every create and run, since the provider ignores the
    project file: Cursor's ``mcpServers`` list of ``{name, type, url | command, args, env,
    headers, auth}``. They carry the same secret references as the file would; whether the
    provider resolves them from its own secrets is unproven until a drill records it."""
    assert layout.mcp_inline is not None
    limit = layout.mcp_inline_limit
    if limit is not None and len(entries) > limit:
        raise ProjectionError(
            f"{state.lane.value} accepts at most {limit} inline MCP servers, not {len(entries)}"
        )
    state.send_options[layout.mcp_inline] = [
        {"name": name, **entry} for name, entry in entries.items()
    ]
    for row in servers:
        launch = mcp_launch(row, state.lane)
        if launch.transport == "sse":
            state.unqualified.append(
                f"{server_name(row)}: SSE transport for inline MCP servers on "
                f"{state.lane.value} is unverified (HTTP and stdio are documented)"
            )
        if launch.env_refs or launch.header_refs:
            state.unqualified.append(
                f"{server_name(row)}: inline MCP secret references on {state.lane.value} are "
                "unverified; the provider must resolve them from its own secrets"
            )


HOST_FILES: Final[Mapping[str, LaneHostFiles]] = {
    "cursor_local": CursorHostFiles(),
    "cursor_cloud": CursorHostFiles(),
}

__all__ = ["HOOK_OUTPUT_SOURCE", "HOST_FILES", "CursorHostFiles"]
