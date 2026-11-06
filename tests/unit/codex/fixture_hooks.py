"""FIXTURE stand-in for Codex's command-hook engine (MO-03 tests). Nothing here is Codex.

What the fixture app-server does with the projected `.codex/hooks.json`, modelled on the
pinned facts (research/codex.md "Hooks"; `adapters/codex/hook_trust.py`):

- the project layer loads only for a project trusted in `CODEX_HOME/config.toml`
  (`[projects."<path>"]`, the path in the host's form); `-c` overrides are ignored, as
  codex-cli 0.162.1 ignored them for hooks when probed;
- `hooks/list` reports each handler's key, current hash and trust status from the home's
  `[hooks.state]` (the hash is the production `hook_hash`, whose formula is pinned against
  the real 0.162.1 app-server by `tests/fixtures/provider_frames/codex/hooks_list/`);
- `PreToolUse` runs every enabled, trusted handler whose matcher matches the tool, as a
  subprocess in the workspace with the Codex payload on stdin; exit 2 or
  `permissionDecision: deny` blocks the tool;
- `skills/list` and `config/read` (MO-34) answer in the shapes the real 0.162.1 server
  recorded (`tests/fixtures/projections/discovery/codex.recorded.json`): the workspace's
  `.agents/skills` as `repo` skills, and the trusted project's `.codex/config.toml` MCP servers.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mission_control.adapters.codex.hook_trust import HOOKS_FILE, hook_hash

_EVENT_LABEL = re.compile(r"(?<!^)(?=[A-Z])")


@dataclass(frozen=True)
class HookRun:
    command: str
    exit_code: int
    stdout: str
    stderr: str

    @property
    def blocked(self) -> bool:
        if self.exit_code == 2:
            return True
        try:
            out = json.loads(self.stdout or "{}")
        except ValueError:
            return False
        specific = out.get("hookSpecificOutput") or {}
        return specific.get("permissionDecision") == "deny" or out.get("decision") == "block"


def _config(codex_home: Path | None) -> dict[str, Any]:
    path = None if codex_home is None else codex_home / "config.toml"
    if path is None or not path.is_file():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _handlers(cwd: Path, config: dict[str, Any]) -> list[dict[str, Any]]:
    """Every handler of the trusted project's hooks file, with Codex's listing fields."""

    project = (config.get("projects") or {}).get(str(cwd)) or {}
    source = cwd / HOOKS_FILE
    if project.get("trust_level") != "trusted" or not source.is_file():
        return []
    states = (config.get("hooks") or {}).get("state") or {}
    document = json.loads(source.read_text(encoding="utf-8"))
    handlers: list[dict[str, Any]] = []
    for event, groups in (document.get("hooks") or {}).items():
        label = _EVENT_LABEL.sub("_", event).lower()
        for group_index, group in enumerate(groups or ()):
            matcher = group.get("matcher")
            for handler_index, handler in enumerate(group.get("hooks") or ()):
                key = f"{source}:{label}:{group_index}:{handler_index}"
                current = hook_hash(event, matcher, handler)
                state = states.get(key) or {}
                trusted = state.get("trusted_hash")
                status = (
                    "untrusted"
                    if trusted is None
                    else ("trusted" if trusted == current else "modified")
                )
                handlers.append(
                    {
                        "key": key,
                        "eventName": event[0].lower() + event[1:],
                        "nativeEvent": event,
                        "handlerType": "command",
                        "command": handler.get("command"),
                        "matcher": matcher,
                        "sourcePath": str(source),
                        "source": "project",
                        "isManaged": False,
                        "enabled": state.get("enabled", True),
                        "currentHash": current,
                        "trustStatus": status,
                    }
                )
    return handlers


def hooks_list(cwds: list[str], codex_home: Path | None) -> dict[str, Any]:
    """The `hooks/list` result (`HooksListResponse`) for `cwds`."""

    config = _config(codex_home)
    data = []
    for cwd in cwds:
        listed = [
            {key: value for key, value in handler.items() if key != "nativeEvent"}
            for handler in _handlers(Path(cwd), config)
        ]
        data.append({"cwd": cwd, "hooks": listed, "warnings": [], "errors": []})
    return {"data": data}


def skills_list(cwds: list[str]) -> dict[str, Any]:
    """The `skills/list` result for `cwds` (repo skills only; no user or system skills)."""

    data = []
    for cwd in cwds:
        root = Path(cwd) / ".agents" / "skills"
        skills = [
            {
                "name": entry.name,
                "description": "",
                "path": str(entry / "SKILL.md"),
                "scope": "repo",
                "enabled": True,
                "pluginId": None,
            }
            for entry in (sorted(root.iterdir()) if root.is_dir() else ())
            if (entry / "SKILL.md").is_file()
        ]
        data.append({"cwd": cwd, "skills": skills, "errors": []})
    return {"data": data}


def config_read(cwd: str, codex_home: Path | None) -> dict[str, Any]:
    """The `config/read` result's MCP slice: the project layer loads only when trusted."""

    project = (_config(codex_home).get("projects") or {}).get(cwd) or {}
    source = Path(cwd) / ".codex" / "config.toml"
    servers: dict[str, Any] = {}
    if project.get("trust_level") == "trusted" and source.is_file():
        layer = tomllib.loads(source.read_text(encoding="utf-8")).get("mcp_servers") or {}
        servers = {name: {**server, "enabled": True} for name, server in layer.items()}
    return {"config": {"mcp_servers": servers}, "origins": {}}


def _matches(matcher: str | None, tool_name: str) -> bool:
    if matcher in {None, "", "*"}:
        return True
    return re.fullmatch(str(matcher), tool_name) is not None


def run_pre_tool_use(cwd: Path, codex_home: Path | None, payload: dict[str, Any]) -> list[HookRun]:
    """Run the trusted `PreToolUse` handlers matching `payload["tool_name"]` (blocking)."""

    runs: list[HookRun] = []
    for handler in _handlers(cwd, _config(codex_home)):
        if handler["nativeEvent"] != "PreToolUse" or not _matches(
            handler["matcher"], str(payload.get("tool_name", ""))
        ):
            continue
        if handler["trustStatus"] != "trusted" or handler["enabled"] is False:
            continue
        argv = shlex.split(str(handler["command"]))
        if argv and argv[0] == "python":
            argv[0] = sys.executable
        completed = subprocess.run(
            argv,
            input=json.dumps({**payload, "cwd": str(cwd), "hook_event_name": "PreToolUse"}),
            capture_output=True,
            text=True,
            cwd=cwd,
            env=dict(os.environ),
            timeout=60,
            check=False,
        )
        runs.append(
            HookRun(
                command=str(handler["command"]),
                exit_code=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
            )
        )
    return runs


__all__ = ["HookRun", "config_read", "hooks_list", "run_pre_tool_use", "skills_list"]
