"""The operations a guide page names, as each transport offers them.

A guide page is written once and names an operation by id (`{op:search}`); the service renders
the id in the caller's vocabulary: the MCP tool for an agent that has only the MCP server, the
`missionctl` command for a sandboxed agent, the route for an HTTP client. One page therefore
says the same thing on every transport without carrying the other two vocabularies.

Every name here is checked against the surface it claims (`tests/unit/guide/`): each MCP name
is a tool of the operator server, each `missionctl` path is in the argparse tree and each route
is mounted. An operation one transport does not offer says so and names the nearest transport
that does; an agent that has only the MCP server can perform every operation here.

HTTP routes are relative to `/v1/applications/{application_id}/`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Literal

Surface = Literal["mcp", "cli", "http"]
SURFACES: Final[tuple[Surface, ...]] = ("mcp", "cli", "http")
_PLACEHOLDER: Final = re.compile(r"\{op:([a-z_]+)\}")
_SURFACE_NAME: Final = {"mcp": "MCP tool", "cli": "missionctl command", "http": "HTTP route"}
# Where a surface without the operation looks next.
_FALLBACK: Final[dict[Surface, tuple[Surface, ...]]] = {
    "mcp": (),
    "cli": ("http", "mcp"),
    "http": ("mcp",),
}


@dataclass(frozen=True, slots=True)
class Operation:
    """One operation's call in each vocabulary (`None`: the transport does not offer it)."""

    mcp: str
    cli: str | None
    http: str | None

    def on(self, surface: Surface) -> str | None:
        return {"mcp": self.mcp, "cli": self.cli, "http": self.http}[surface]


OPERATIONS: Final[dict[str, Operation]] = {
    # -- the guide itself --------------------------------------------------------------------
    "guide_topic": Operation(
        'mission_guide("<topic>")', "missionctl guide TOPIC", "GET guide/{topic}"
    ),
    "describe": Operation(
        'mission_describe("<ref>")', "missionctl describe REF", "GET describe?ref=REF"
    ),
    "describe_lane": Operation(
        'mission_describe("lane:<profile>")',
        "missionctl describe lane:PROFILE",
        "GET describe?ref=lane:PROFILE",
    ),
    "describe_model": Operation(
        'mission_describe("model:<profile>")',
        "missionctl describe model:PROFILE",
        "GET describe?ref=model:PROFILE",
    ),
    "describe_feature": Operation(
        'mission_describe("feature:<id>")',
        "missionctl describe feature:ID",
        "GET describe?ref=feature:ID",
    ),
    "describe_tool": Operation(
        'mission_describe("tool:<name>")',
        "missionctl describe tool:NAME",
        "GET describe?ref=tool:NAME",
    ),
    "describe_template": Operation(
        'mission_describe("template:<id>")',
        "missionctl describe template:ID",
        "GET describe?ref=template:ID",
    ),
    "describe_manifest": Operation(
        'mission_describe("manifest")',
        "missionctl describe manifest",
        "GET describe?ref=manifest",
    ),
    "describe_manifest_section": Operation(
        'mission_describe("manifest:<section>")',
        "missionctl describe manifest:SECTION",
        "GET describe?ref=manifest:SECTION",
    ),
    # -- selection ---------------------------------------------------------------------------
    "search": Operation("mission_search", "missionctl search", "POST selection/search"),
    "list_lanes": Operation(
        'mission_search(facets=["lane"])',
        "missionctl search --facet lane",
        'POST selection/search {"facets": ["lane"]}',
    ),
    "list_models": Operation(
        'mission_search(facets=["model"])',
        "missionctl search --facet model",
        'POST selection/search {"facets": ["model"]}',
    ),
    "list_workflow_types": Operation(
        'mission_search(facets=["workflow_type"], limit=50)',
        "missionctl search --facet workflow_type --limit 50",
        'POST selection/search {"facets": ["workflow_type"], "limit": 50}',
    ),
    "list_lowered": Operation(
        'mission_search(facets=["workflow_type"], include_lowered=true)',
        "missionctl search --facet workflow_type --include-lowered",
        'POST selection/search {"facets": ["workflow_type"], "include_lowered": true}',
    ),
    "list_templates": Operation(
        'mission_search(facets=["template"])',
        "missionctl search --facet template",
        'POST selection/search {"facets": ["template"]}',
    ),
    "list_sandboxes": Operation(
        'mission_search(facets=["sandbox_profile"])',
        "missionctl search --facet sandbox_profile",
        'POST selection/search {"facets": ["sandbox_profile"]}',
    ),
    "list_kind": Operation(
        'mission_search(kinds=["skill"])',
        "missionctl search --kind skill",
        'POST selection/search {"kinds": ["skill"]}',
    ),
    "list_next_page": Operation(
        'mission_search(kinds=["skill"], offset=20)',
        "missionctl search --kind skill --offset 20",
        'POST selection/search {"kinds": ["skill"], "offset": 20}',
    ),
    "search_lane": Operation(
        'mission_search(query="...", lane_profile="<profile>")',
        "missionctl search QUERY --lane PROFILE",
        'POST selection/search {"query": "...", "lane_profile": "PROFILE"}',
    ),
    "check": Operation("selection_check", "missionctl workspace check", "POST selection/check"),
    # -- author and launch -------------------------------------------------------------------
    "compile": Operation(
        "mission_manifest_compile", "missionctl mission compile", "POST missions:compile"
    ),
    "preflight": Operation("mission_preflight", "missionctl preflight", "POST missions:preflight"),
    "submit": Operation(
        "mission_manifest_submit", "missionctl mission submit", "POST missions:submit"
    ),
    "start": Operation("mission_run_start", "missionctl mission start", "POST missions:start"),
    # -- check in ----------------------------------------------------------------------------
    "inbox_wait": Operation(
        "coordinator_inbox_wait",
        "missionctl wait",
        "GET coordinator-inboxes/{subscription_id}/notifications?wait=SECONDS",
    ),
    "inbox_list": Operation(
        "coordinator_inbox_list", "missionctl inbox list", "GET coordinator-inboxes"
    ),
    "inbox_ack": Operation(
        "coordinator_inbox_ack",
        "missionctl inbox ack",
        "POST coordinator-inboxes/{subscription_id}/acks",
    ),
    "inspect": Operation(
        "mission_run_inspect", "missionctl run inspect", "GET runs/{run_id}/inspection"
    ),
    "transcript": Operation(
        "mission_run_transcript", "missionctl run transcript", "GET runs/{run_id}/transcript"
    ),
    "run_search": Operation(
        "mission_run_search", "missionctl run search", "GET runs/{run_id}/transcript/search"
    ),
    "run_list": Operation("mission_run_list", "missionctl run list", "GET runs"),
    "outputs": Operation(
        "mission_run_outputs", "missionctl outputs show", "GET runs/{run_id}/outputs"
    ),
    "chain": Operation(
        "mission_chain_inspect", "missionctl chain inspect", "GET chains/{chain_id}"
    ),
    "points": Operation("mission_run_points", "missionctl run points", "GET runs/{run_id}/points"),
    "state_as_of": Operation(
        "mission_run_state_as_of",
        "missionctl run state-as-of",
        "GET runs/{run_id}/points/{point_id}/state-as-of",
    ),
    "human_task_list": Operation("mission_human_task_list", None, "GET human-tasks"),
    "human_task_resolve": Operation(
        "mission_human_task_resolve", None, "POST human-tasks/{human_task_id}/resolutions"
    ),
    # -- steer and fork ----------------------------------------------------------------------
    "command": Operation(
        "mission_command_send", "missionctl command send", "POST runs/{run_id}/commands"
    ),
    "command_queue": Operation(
        "mission_command_send", "missionctl command queue", "POST runs/{run_id}/commands"
    ),
    "command_add_context": Operation(
        "mission_command_send",
        "missionctl command queue --add-context",
        "POST runs/{run_id}/commands",
    ),
    "command_inject": Operation(
        "mission_command_send", "missionctl command inject", "POST runs/{run_id}/commands"
    ),
    "command_cancel": Operation(
        "mission_command_send", "missionctl command cancel", "POST runs/{run_id}/commands"
    ),
    "inbox_command": Operation(
        "coordinator_inbox_command",
        None,
        "POST coordinator-inboxes/{subscription_id}/notifications/{notification_id}/commands",
    ),
    "fork": Operation("mission_run_fork", "missionctl run fork", "POST runs/{run_id}/forks"),
}


class UnknownOperation(KeyError):
    """A guide page names an operation this registry does not hold."""


def render_operation(operation_id: str, surface: Surface) -> str:
    """The operation as a code span in the surface's vocabulary, with its fallback named."""

    try:
        operation = OPERATIONS[operation_id]
    except KeyError:
        raise UnknownOperation(operation_id) from None
    call = operation.on(surface)
    if call is not None:
        return f"`{call}`"
    for other in _FALLBACK[surface]:
        call = operation.on(other)
        if call is not None:
            return f"`{call}` ({_SURFACE_NAME[other]}; no {_SURFACE_NAME[surface]})"
    raise UnknownOperation(operation_id)


def render_operations(text: str, surface: Surface) -> str:
    """`text` with every `{op:<id>}` replaced by the surface's call."""

    return _PLACEHOLDER.sub(lambda match: render_operation(match.group(1), surface), text)


def operations_in(text: str) -> tuple[str, ...]:
    """The operation ids a page names, in order of first use."""

    return tuple(dict.fromkeys(_PLACEHOLDER.findall(text)))


__all__ = [
    "OPERATIONS",
    "SURFACES",
    "Operation",
    "Surface",
    "UnknownOperation",
    "operations_in",
    "render_operation",
    "render_operations",
]
