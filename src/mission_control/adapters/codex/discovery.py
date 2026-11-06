"""The `codex` Discovery Proof: the app-server's own lists after `thread/start` (SPEC-02
section 6; MO-34).

Three requests answer what Codex loaded for the workspace (shapes recorded from codex-cli
0.162.1, `tests/fixtures/projections/discovery/codex.recorded.json`; no login and no model
turn is needed):

* `skills/list {cwds}`: `data[].skills[]` with `name`, `path` (`.../<dir>/SKILL.md`), `scope`
  (`repo`, `user`, `system`) and `enabled`. A skill is named by its directory, as Mission
  Control places it;
* `hooks/list {cwds}`: `data[].hooks[]` with `eventName` (`preToolUse`), `command`,
  `enabled` and `trustStatus` (Codex runs a non-managed hook only when `trusted`). An event
  is reported loaded when it has an enabled, trusted handler and none of its handlers that runs
  a Mission Control script (under `.mission/hooks/`) is skipped;
* `config/read {cwd}`: the effective `config`, whose `mcp_servers` names the servers of every
  trusted layer (the project `.codex/config.toml` only when the project is trusted).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any, Final

from mission_control.adapters.codex.hook_trust import TRUSTED_STATUSES
from mission_control.domain.agentic_components.layering import MISSION_HOOK_ROOT
from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.execution.discovery import DiscoveryItem, DiscoveryReport

SKILL_FILE: Final = "SKILL.md"
_SEPARATORS: Final = re.compile(r"[\\/]")


def _entries(listed: Mapping[str, Any], key: str) -> Iterable[Mapping[str, Any]]:
    for item in listed.get("data") or ():
        if isinstance(item, Mapping):
            yield from (entry for entry in item.get(key) or () if isinstance(entry, Mapping))


def _skill_directory(entry: Mapping[str, Any]) -> str | None:
    parts = _SEPARATORS.split(str(entry.get("path") or ""))
    if len(parts) >= 2 and parts[-1] == SKILL_FILE and parts[-2]:
        return parts[-2]
    name = entry.get("name")
    return name if isinstance(name, str) and name else None


def _event_name(event: str) -> str:
    """`preToolUse` as the `hooks.json` key Mission Control writes (`PreToolUse`)."""

    return event[:1].upper() + event[1:]


def _hook_events(listed: Mapping[str, Any]) -> list[str]:
    loaded: dict[str, bool] = {}
    for entry in _entries(listed, "hooks"):
        event = entry.get("eventName")
        if not isinstance(event, str) or not event:
            continue
        runs = entry.get("enabled") is not False and entry.get("trustStatus") in TRUSTED_STATUSES
        mission = MISSION_HOOK_ROOT in str(entry.get("command") or "")
        name = _event_name(event)
        if mission and not runs:
            loaded[name] = False
        elif runs:
            loaded.setdefault(name, True)
    return [name for name, ok in loaded.items() if ok]


def _mcp_servers(config: Mapping[str, Any]) -> list[str]:
    effective = config.get("config")
    servers = effective.get("mcp_servers") if isinstance(effective, Mapping) else None
    if not isinstance(servers, Mapping):
        return []
    return [
        str(name)
        for name, server in servers.items()
        if not (isinstance(server, Mapping) and server.get("enabled") is False)
    ]


def app_server_report(
    skills: Mapping[str, Any],
    hooks: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    source: str,
) -> DiscoveryReport:
    """The report of one `skills/list`, `hooks/list` and `config/read` answer."""

    items = [
        DiscoveryItem(kind="skill", name=name)
        for entry in _entries(skills, "skills")
        if entry.get("enabled") is not False
        and (name := _skill_directory(entry)) is not None
        and len(name) <= 256
    ]
    items.extend(DiscoveryItem(kind="hook", name=name) for name in _hook_events(hooks))
    items.extend(
        DiscoveryItem(kind="mcp_server", name=name)
        for name in _mcp_servers(config)
        if 0 < len(name) <= 256
    )
    return DiscoveryReport(
        lane_profile=LaneProfile.CODEX,
        mechanism="app_server",
        items=tuple(dict.fromkeys(items)),
        source=source,
    )


__all__ = ["app_server_report"]
