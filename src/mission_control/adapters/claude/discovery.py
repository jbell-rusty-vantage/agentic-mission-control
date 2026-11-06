"""The `claude_agent_sdk` Discovery Proof: what Claude Code's `system/init` says it loaded
(SPEC-02 section 6; MO-34).

`system/init` (cli-adapters.md "system/init") lists the session's `skills` and `agents` by name
and its `mcp_servers` with a connection `status`; it is emitted before the first model request,
so it proves what the CLI loaded from the project setting source and the SDK options, not what
the model did with it. Only a `connected` MCP server counts as loaded. The lane emits the report
as a `materialization.discovered` frame right after the init frame (`session.py`).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.execution.discovery import (
    DiscoveryItem,
    DiscoveryKind,
    DiscoveryReport,
)

CONNECTED = "connected"


def _names(kind: DiscoveryKind, values: Any) -> Iterable[DiscoveryItem]:
    if not isinstance(values, list):
        return ()
    return (
        DiscoveryItem(kind=kind, name=value)
        for value in values
        if isinstance(value, str) and 0 < len(value) <= 256
    )


def init_report(init: Mapping[str, Any], *, source: str) -> DiscoveryReport:
    """The report of one `system/init` payload (`SystemMessage.data`)."""

    servers = init.get("mcp_servers")
    connected = [
        str(server["name"])
        for server in (servers if isinstance(servers, list) else ())
        if isinstance(server, Mapping)
        and server.get("status") == CONNECTED
        and isinstance(server.get("name"), str)
    ]
    items = (
        *_names("skill", init.get("skills")),
        *_names("subagent", init.get("agents")),
        *_names("mcp_server", connected),
    )
    return DiscoveryReport(
        lane_profile=LaneProfile.CLAUDE_AGENT_SDK,
        mechanism="session_init",
        items=tuple(dict.fromkeys(items)),
        source=source,
    )


__all__ = ["CONNECTED", "init_report"]
