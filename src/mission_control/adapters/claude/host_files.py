"""The Claude profiles' Host Projection writer (SPEC-01; MP-03; moved here by OC-R3).

Claude settings-file hooks and the Python SDK callback union differ
(`CLAUDE_SDK_CALLBACK_EVENTS`), so on `claude_agent_sdk` the Kernel Hooks are in-process
callbacks described in `send_options` and only catalog hooks reach `.claude/settings.json`; the
mission instruction is appended to the `claude_code` system prompt preset there. `claude_cloud`
reads the overlay `.claude/rules/mc-mission.md` and its settings-file hooks run in the cloud
session without a fail-closed Kernel Hook. MCP servers go to `.mcp.json` with `${NAME}`
references, subagents to `.claude/agents/*.md`. Never a `CLAUDE.md`: Claude Code reads the
repository's `AGENTS.md` only while none exists. The hook runner and the gate answer in this
package's `hook_output.py`. The lane-neutral checks, reports and helpers are
`application/agentic_components/projections.py`; bootstrap composes `HOST_FILES`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from mission_control.application.agentic_components.projections import (
    KERNEL_HOOK_TIMEOUT_SECONDS,
    KernelSurface,
    LaneHostFiles,
    ProjectionInputs,
    ProjectionState,
    dumps_json,
    file_server_name,
    frontmatter,
    host_overlay,
    json_mcp_entry,
    kernel_delivers,
    matcher_hooks,
    mcp_environment_names,
    place_native_output,
    subagent,
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
    ResolvedCapability,
)
from mission_control.domain.capabilities.host_support import LaneProfile

HOOK_OUTPUT_SOURCE: Final = Path(__file__).with_name("hook_output.py")


@dataclass(frozen=True)
class ClaudeHostFiles:
    """`LaneHostFiles` of one Claude profile."""

    kernel_surface: KernelSurface

    def write(self, inputs: ProjectionInputs, state: ProjectionState) -> InProcessProjection | None:
        write_skills(inputs.skills, state.layering.skills, state)
        if state.telemetry:
            write_telemetry_pack(inputs.skills, state)
        write_hook_scripts(inputs.hooks, state)
        place_native_output(inputs.hooks, state, HOOK_OUTPUT_SOURCE)
        _claude(
            inputs.servers,
            inputs.hooks,
            inputs.agents,
            inputs.kernel_hooks,
            inputs.instructions,
            state,
        )
        return None


def _kernel_callbacks(
    lane: LaneProfile, kernel_hooks: Sequence[KernelHook]
) -> list[dict[str, object]]:
    """In-process callback registrations, in Kernel Hook order, for the lane's SDK adapter."""
    callbacks: list[dict[str, object]] = []
    for kernel in kernel_hooks:
        for event in kernel.events:
            native = kernel_delivers(lane, event, in_process=True)
            if native is None:
                continue
            callback: dict[str, object] = {
                "hook_id": kernel.hook_id,
                "mc_event": event.value,
                "native_event": native.native_event,
                "timeout": KERNEL_HOOK_TIMEOUT_SECONDS,
                "fail_closed": True,
            }
            if native.matcher:
                callback["matcher"] = native.matcher
            callbacks.append(callback)
    return callbacks


def _claude_agent_md(row: ResolvedCapability, lane: LaneProfile, servers: dict[str, str]) -> str:
    profile = subagent(row).profile
    overlay = host_overlay(row, lane)
    mcp = [servers.get(ref, ref) for ref in profile.mcp_servers]
    permission = overlay.get("permission_mode", "plan" if profile.readonly else None)
    return frontmatter(
        (
            ("name", profile.name),
            ("description", profile.description),
            ("tools", ", ".join(profile.tools) if profile.tools else None),
            ("model", subagent_model(row, lane)),
            ("permissionMode", permission),
            ("skills", list(profile.skills) if profile.skills else None),
            ("mcpServers", mcp or None),
            ("maxTurns", profile.max_turns),
            ("background", profile.background or None),
        ),
        subagent_prompt(row),
    )


def _claude(
    servers: Sequence[ResolvedCapability],
    hooks: Sequence[ResolvedCapability],
    agents: Sequence[ResolvedCapability],
    kernel_hooks: Sequence[KernelHook],
    instructions: str,
    state: ProjectionState,
) -> None:
    lane, layout, layering = state.lane, state.layout, state.layering
    # Never a CLAUDE.md: Claude Code reads the repository's AGENTS.md only while none exists.
    if layering.overlay_inline:
        state.send_options["system_prompt"] = {
            "type": "preset",
            "preset": "claude_code",
            "append": instructions,
        }
    else:
        state.write(layering.overlay, instructions)
    if servers:
        assert layout.mcp_file is not None
        state.write(
            layout.mcp_file,
            dumps_json(
                {
                    "mcpServers": {
                        file_server_name(row): json_mcp_entry(row, lane, cursor=False)
                        for row in servers
                    }
                }
            ),
        )
        state.environment_names.update(mcp_environment_names(servers, lane))
    in_process = lane is LaneProfile.CLAUDE_AGENT_SDK
    # Exec form (`command` + `args`): fired by Claude Code 2.1.295 in the recorded discovery
    # fixture tests/fixtures/projections/discovery/claude_agent_sdk.recorded.json.
    settings = matcher_hooks(
        lane, () if in_process else kernel_hooks, hooks, state.telemetry_hooks, exec_form=True
    )
    if settings:
        assert layout.hooks_file is not None
        state.write(layout.hooks_file, dumps_json({"hooks": settings}))
    if in_process:
        # Omitting setting_sources loads user, project and local settings (Agent SDK migration
        # guide, "Settings sources default"); pin the projected project layer only.
        state.send_options["setting_sources"] = ["project"]
        callbacks = _kernel_callbacks(lane, kernel_hooks)
        if callbacks:
            state.send_options["hook_callbacks"] = callbacks
    if lane is LaneProfile.CLAUDE_CLOUD and kernel_hooks:
        # The repository's settings-file hooks run in the cloud session, but the session
        # cannot reach the worker's loopback callback: no Kernel Hook fails closed there
        # (docs/qualification/lanes/claude_cloud/FEASIBILITY.md; mirrors cursor_cloud).
        state.degraded.extend(
            f"{hook.hook_id}: claude_cloud cannot reach the worker loopback callback; "
            "the hook runs without a fail-closed decision"
            for hook in kernel_hooks
        )
    names = {row.pin.capability_id: file_server_name(row) for row in servers}
    for row in agents:
        profile = subagent(row).profile
        state.write(subagent_path(layering, profile.name), _claude_agent_md(row, lane, names))


HOST_FILES: Final[Mapping[str, LaneHostFiles]] = {
    # Kernel Hooks run as SDK callbacks, outside agent-writable files, on the local SDK lane.
    "claude_agent_sdk": ClaudeHostFiles(kernel_surface="sdk_callback"),
    "claude_cloud": ClaudeHostFiles(kernel_surface="native_hook"),
}

__all__ = ["HOOK_OUTPUT_SOURCE", "HOST_FILES", "ClaudeHostFiles"]
