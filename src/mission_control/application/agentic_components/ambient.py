"""Inventory cognition without retaining its contents or following symlinks (MO-33)."""

from __future__ import annotations

import json
import re
import tomllib
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from mission_control.domain.agentic_components.projection import HostProjection
from mission_control.domain.capabilities.hooks import (
    KERNEL_HOOK_EVENTS,
    HookMode,
    native_hook,
)
from mission_control.domain.capabilities.host_support import LaneProfile


class AmbientItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["skill", "subagent", "instructions", "config"]
    name: str
    path: str
    digest: str
    origin: Literal["repo", "home"]
    hook_events: tuple[str, ...] = ()


_ROOTS = {
    "cursor": (".cursor", ".claude", ".codex", ".agents"),
    "claude": (".claude",),
    "codex": (".codex", ".agents"),
}
_LOCAL = {LaneProfile.CURSOR_LOCAL, LaneProfile.CLAUDE_AGENT_SDK, LaneProfile.CODEX}
AmbientKind = Literal["skill", "subagent", "instructions", "config"]


def _family(lane: LaneProfile) -> str | None:
    if lane in {LaneProfile.CURSOR_LOCAL, LaneProfile.CURSOR_CLOUD}:
        return "cursor"
    if lane in {LaneProfile.CLAUDE_AGENT_SDK, LaneProfile.CLAUDE_CLOUD}:
        return "claude"
    if lane in {LaneProfile.CODEX, LaneProfile.CODEX_CLOUD}:
        return "codex"
    return None


def _files(root: Path) -> tuple[Path, ...]:
    if root.is_symlink() or root.is_junction():
        return ()
    if root.is_file():
        return (root,)
    if not root.is_dir():
        return ()
    return tuple(file for child in sorted(root.iterdir()) for file in _files(child))


def _hooks(path: Path) -> tuple[str, ...]:
    try:
        data = (
            tomllib.loads(path.read_text(encoding="utf-8"))
            if path.suffix == ".toml"
            else json.loads(path.read_bytes())
        )
    except (ValueError, UnicodeError):
        # An unreadable hook config cannot establish that enforcement is unaffected.
        return (
            ("*",)
            if path.name in {"hooks.json", "settings.json", "settings.local.json", "config.toml"}
            else ()
        )
    hooks = data.get("hooks", {}) if isinstance(data, dict) else {}
    return (
        tuple(sorted(str(key) for key, value in hooks.items() if value))
        if isinstance(hooks, dict)
        else ("*",)
    )


def _name(path: Path, fallback: str) -> str:
    """Providers discover skills/agents by declared names as well as filenames."""
    candidate = path / "SKILL.md" if path.is_dir() else path
    if candidate.is_symlink():
        return fallback
    try:
        content = candidate.read_text(encoding="utf-8")
        if candidate.suffix == ".toml":
            value = tomllib.loads(content).get("name")
            return value if isinstance(value, str) else fallback
        if content.startswith("---\n"):
            frontmatter = content.split("---", 2)[1]
            match = re.search(r"^name:\s*([^\n]+)", frontmatter, re.MULTILINE)
            if match:
                return match[1].strip().strip("\"'")
    except (OSError, UnicodeError, ValueError):
        pass
    return fallback


def inventory_ambient(
    workspace: Path, projection: HostProjection, *, home: Path | None = None
) -> tuple[AmbientItem, ...]:
    family = _family(projection.profile)
    if family is None:
        return ()
    items: list[AmbientItem] = []

    projected = {file.path: file.content for file in projection.files}

    def add(
        path: Path, base: Path, origin: Literal["repo", "home"], kind: AmbientKind, name: str
    ) -> None:
        files = _files(path)
        if not files:
            return
        if origin == "repo" and all(
            projected.get(file.relative_to(base).as_posix()) == file.read_bytes() for file in files
        ):
            return
        digest = sha256()
        for file in files:
            digest.update(file.relative_to(base).as_posix().encode() + b"\0")
            digest.update(sha256(file.read_bytes()).digest())
        items.append(
            AmbientItem(
                kind=kind,
                name=name,
                path=path.relative_to(base).as_posix(),
                digest="sha256:" + digest.hexdigest(),
                origin=origin,
                hook_events=_hooks(path) if kind == "config" else (),
            )
        )

    bases: list[tuple[Path, Literal["repo", "home"]]] = [(workspace, "repo")]
    if projection.profile in _LOCAL and home is not None:
        bases.append((home, "home"))
    for base, origin in bases:
        for instruction in ("AGENTS.md", "AGENTS.override.md", "CLAUDE.md"):
            add(base / instruction, base, origin, "instructions", instruction)
        for root_name in _ROOTS[family]:
            root = base / root_name
            if root.is_symlink() or root.is_junction():
                continue
            directories: tuple[tuple[AmbientKind, str], ...] = (
                ("skill", "skills"),
                ("subagent", "agents"),
            )
            for kind, directory in directories:
                target = root / directory
                if target.is_dir() and not target.is_symlink() and not target.is_junction():
                    for child in sorted(target.iterdir()):
                        if kind == "skill" and not (child / "SKILL.md").is_file():
                            continue
                        fallback = child.name if kind == "skill" else child.stem
                        add(child, base, origin, kind, _name(child, fallback))
            for name in (
                "settings.json",
                "settings.local.json",
                "hooks.json",
                "config.toml",
                "mcp.json",
            ):
                add(root / name, base, origin, "config", name)
            add(root / "rules", base, origin, "instructions", "rules")
            add(root / "CLAUDE.md", base, origin, "instructions", "CLAUDE.md")
        add(base / ".mcp.json", base, origin, "config", ".mcp.json")
    return tuple(items)


def ambient_conflicts(
    items: tuple[AmbientItem, ...], projection: HostProjection
) -> tuple[str, ...]:
    names: set[tuple[str, str]] = set()
    for file in projection.files:
        parts = Path(file.path).parts
        if "skills" in parts:
            names.add(("skill", parts[parts.index("skills") + 1]))
        if "agents" in parts:
            names.add(("subagent", Path(parts[parts.index("agents") + 1]).stem))
    hook_lanes = {projection.profile}
    if projection.profile in {LaneProfile.CURSOR_LOCAL, LaneProfile.CURSOR_CLOUD}:
        hook_lanes.add(LaneProfile.CLAUDE_AGENT_SDK)
    enforced = {
        mapped.native_event
        for lane in hook_lanes
        for events in KERNEL_HOOK_EVENTS.values()
        for event in events
        if (mapped := native_hook(lane, event)) is not None and mapped.mode is HookMode.ENFORCE
    }
    return tuple(
        f"{item.origin}:{item.path}"
        for item in items
        if (item.kind, item.name) in names
        or (item.kind == "config" and bool(set(item.hook_events) & (enforced | {"*"})))
    )
