"""Layer a Host Projection over the repository it lands in (SPEC-02 §4, ADR-0044).

The renderer is pure and never sees the repository; this step does, right before the lane
places the files (worktree write on local lanes, branch commit on cursor_cloud). It reads
the repository through a :class:`RepoView` and decides, per projected file:

- **merged files** (:data:`MERGED_FILES`): parsed and merged structurally. Repository entries
  are kept as they are; Mission Control's entries (hook entries running a script under
  ``.mission/hooks/``, servers named ``mc-*``, the delimited ``AGENTS.override.md`` section,
  the marked ``.codex/config.toml`` block) replace the ones an earlier layering left, so a
  re-run is idempotent. A merge that changes nothing keeps the repository's exact bytes;
- **owned files** (under ``.mission/`` or named ``mc-*``): placed as projected;
- **everything else**, grouped per skill directory or subagent file: placed when the path is
  free or already holds the same bytes, otherwise a conflict.

A conflict resolves by ``materialization.conflicts`` (:class:`MaterializationPolicy`):
``refuse`` raises :class:`LayeringRefused` before anything is written, ``repo_wins`` keeps the
repository's entry (the projected one is skipped), ``mission_wins`` places Mission Control's.
Repository files are never deleted. The ``mc.layering_receipt.v1`` lists every merged,
preserved, overridden and kept key, each conflict and its resolution, the skipped paths and
what the lane's native roots hold afterwards from the repository and from the mission
(:class:`DiscoveredItem`), for receipts and discovery reports.

The repository bytes of every file layering changes are kept in a record under ``.mission/``
so a local lane puts them back before it captures the workspace
(:func:`restore_repository_files`): the run leaves repository files byte-identical.
"""

from __future__ import annotations

import base64
import json
import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any, Final, Literal, Protocol

from pydantic import BaseModel, ConfigDict

from mission_control.domain.agentic_components.layering import (
    HOOK_FORMATS,
    MERGED_FILES,
    MISSION_HOOK_ROOT,
    MISSION_NAME_PREFIX,
    MISSION_SECTION_BEGIN,
    MISSION_SECTION_END,
    MISSION_SECTION_POINTER,
    ConflictCategory,
    ConflictPolicy,
    MaterializationPolicy,
    MergeFormat,
    conflict_category,
    mission_owned,
    mission_section,
)
from mission_control.domain.agentic_components.projection import HostProjection, ProjectedFile
from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.capabilities.layouts import (
    CODEX_INSTRUCTIONS_LIMIT,
    LAYERING_LAYOUTS,
    LayeringLayout,
)
from mission_control.domain.execution.discovery import DiscoveryKind

LAYERING_RECEIPT_SCHEMA: Final = "mc.layering_receipt.v1"
LAYERING_RECORD_SCHEMA: Final = "mc.layering_record.v1"
LAYERING_RECORD_PATH: Final = ".mission/layering.json"
MATERIALIZATION_CONFLICT: Final = "MATERIALIZATION_CONFLICT"
CODEX_CONFIG_BEGIN: Final = "# >>> mission-control: generated MCP servers, do not edit"
CODEX_CONFIG_END: Final = "# <<< mission-control"
_TABLE_HEADER = re.compile(r"^\s*\[")


class LayeringRefused(ValueError):
    """A conflict resolved ``refuse``: nothing was written (code ``MATERIALIZATION_CONFLICT``)."""

    code = MATERIALIZATION_CONFLICT


class _Unmergeable(Exception):
    """The repository file does not have the shape its format needs."""


class RepoView(Protocol):
    """Read access to the repository a projection lands in (POSIX paths from its root)."""

    def read(self, path: str) -> bytes | None: ...

    def children(self, path: str) -> tuple[str, ...]: ...


class DirectoryView:
    """A workspace on disk. Symlinks are never followed: a symlinked entry reads as absent
    and the materializer refuses to write through it."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def _path(self, path: str) -> Path:
        return self._root.joinpath(*PurePosixPath(path).parts)

    def read(self, path: str) -> bytes | None:
        target = self._path(path)
        if target.is_symlink() or not target.is_file():
            return None
        return target.read_bytes()

    def children(self, path: str) -> tuple[str, ...]:
        target = self._path(path)
        if target.is_symlink() or not target.is_dir():
            return ()
        return tuple(sorted(entry.name for entry in target.iterdir()))


class TreeView:
    """An in-memory tree, such as the files of one commit (``GitBranchPublisher.read_tree``)."""

    def __init__(self, files: Mapping[str, bytes]) -> None:
        self._files = dict(files)

    def read(self, path: str) -> bytes | None:
        return self._files.get(path)

    def children(self, path: str) -> tuple[str, ...]:
        prefix = path.rstrip("/") + "/"
        return tuple(
            sorted(
                {
                    key[len(prefix) :].split("/", 1)[0]
                    for key in self._files
                    if key.startswith(prefix)
                }
            )
        )


# --- the receipt ---------------------------------------------------------------------------------


class _Receipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MergedConfig(_Receipt):
    path: str
    format: MergeFormat
    mission_keys: tuple[str, ...] = ()
    repo_keys: tuple[str, ...] = ()
    # Repository values replaced under `mission_wins`, and Mission Control values dropped
    # under `repo_wins`.
    overridden: tuple[str, ...] = ()
    kept_repo: tuple[str, ...] = ()


class LayeringConflict(_Receipt):
    path: str
    key: str | None = None
    category: ConflictCategory
    resolution: ConflictPolicy


class DiscoveredItem(_Receipt):
    kind: DiscoveryKind
    name: str
    path: str
    origin: Literal["repo", "mission"]


class LayeringReceipt(_Receipt):
    """`mc.layering_receipt.v1`: how a projection was layered over one repository."""

    schema_version: Literal["mc.layering_receipt.v1"] = LAYERING_RECEIPT_SCHEMA
    lane_profile: LaneProfile
    conflicts_policy: ConflictPolicy | None = None
    merged: tuple[MergedConfig, ...] = ()
    conflicts: tuple[LayeringConflict, ...] = ()
    skipped: tuple[str, ...] = ()
    overflow: tuple[str, ...] = ()
    discovery: tuple[DiscoveredItem, ...] = ()

    def discovered(self, origin: Literal["repo", "mission"]) -> tuple[DiscoveredItem, ...]:
        return tuple(item for item in self.discovery if item.origin == origin)


@dataclass(frozen=True)
class LayeredProjection:
    """The files to place (merged bytes where a merge happened; skipped paths left out), the
    repository bytes of each repository file they change, and the receipt."""

    files: tuple[ProjectedFile, ...]
    originals: Mapping[str, bytes]
    receipt: LayeringReceipt


# --- layering ------------------------------------------------------------------------------------


def layer_projection(
    projection: HostProjection,
    repo: RepoView,
    policy: MaterializationPolicy | None = None,
) -> LayeredProjection:
    """Layer ``projection`` over ``repo`` under ``policy`` (default resolutions when absent).

    Deterministic: the same projection, repository bytes and policy give the same files and
    receipt, and layering its own output again changes nothing.
    """

    return _Layering(projection.profile, repo, policy or MaterializationPolicy()).run(projection)


def repository_roots(projection: HostProjection) -> tuple[str, ...]:
    """The repository paths layering reads for ``projection`` (for a :class:`TreeView` built
    from a commit): the lane's instruction files, cognition roots and config files, and every
    projected path Mission Control does not own."""

    layout = LAYERING_LAYOUTS.get(projection.profile)
    roots: list[str] = []
    if layout is not None:
        roots.extend((*layout.repo_instructions, layout.skills, *layout.config_files))
        if layout.agents is not None:
            roots.append(layout.agents)
    roots.extend(item.path for item in projection.files if not mission_owned(item.path))
    return tuple(dict.fromkeys(roots))


@dataclass
class _Keys:
    mission: list[str] = field(default_factory=list)
    repo: list[str] = field(default_factory=list)
    overridden: list[str] = field(default_factory=list)
    kept_repo: list[str] = field(default_factory=list)

    def record(self, path: str, merge_format: MergeFormat) -> MergedConfig:
        return MergedConfig(
            path=path,
            format=merge_format,
            mission_keys=tuple(dict.fromkeys(self.mission)),
            repo_keys=tuple(dict.fromkeys(self.repo)),
            overridden=tuple(self.overridden),
            kept_repo=tuple(self.kept_repo),
        )


class _Layering:
    def __init__(self, lane: LaneProfile, repo: RepoView, policy: MaterializationPolicy) -> None:
        self._lane = lane
        self._repo = repo
        self._policy = policy
        self._layout: LayeringLayout | None = LAYERING_LAYOUTS.get(lane)
        self._files: list[ProjectedFile] = []
        self._originals: dict[str, bytes] = {}
        self._merged: list[MergedConfig] = []
        self._conflicts: list[LayeringConflict] = []
        self._skipped: list[str] = []
        self._overflow: list[str] = []
        # Skill directories and subagent files the mission placed: (kind, name) -> path.
        self._placed: dict[tuple[DiscoveryKind, str], str] = {}

    def run(self, projection: HostProjection) -> LayeredProjection:
        for label, files in self._groups(projection.files):
            self._place(label, files)
        receipt = LayeringReceipt(
            lane_profile=self._lane,
            conflicts_policy=self._policy.conflicts,
            merged=tuple(self._merged),
            conflicts=tuple(self._conflicts),
            skipped=tuple(self._skipped),
            overflow=tuple(self._overflow),
            discovery=self._discovery(),
        )
        return LayeredProjection(
            files=tuple(sorted(self._files, key=lambda item: item.path)),
            originals=dict(sorted(self._originals.items())),
            receipt=receipt,
        )

    # -- grouping and placement ------------------------------------------------------------------

    def _item(self, path: str) -> tuple[DiscoveryKind, str] | None:
        """(kind, name) when ``path`` belongs to a skill directory or is a subagent file."""

        layout = self._layout
        if layout is None:
            return None
        if path.startswith(layout.skills + "/"):
            return "skill", path[len(layout.skills) + 1 :].split("/", 1)[0]
        if layout.agents is not None and path.startswith(layout.agents + "/"):
            name = path[len(layout.agents) + 1 :]
            if "/" not in name and name.endswith(layout.agent_suffix):
                return "subagent", name.removesuffix(layout.agent_suffix)
        return None

    def _groups(
        self, files: Sequence[ProjectedFile]
    ) -> list[tuple[str, tuple[ProjectedFile, ...]]]:
        groups: dict[str, list[ProjectedFile]] = {}
        for item in files:
            owner = self._item(item.path)
            label = item.path
            if owner is not None and owner[0] == "skill" and self._layout is not None:
                label = f"{self._layout.skills}/{owner[1]}/"
            groups.setdefault(label, []).append(item)
        return [(label, tuple(group)) for label, group in groups.items()]

    def _place(self, label: str, files: tuple[ProjectedFile, ...]) -> None:
        if len(files) == 1 and files[0].path in MERGED_FILES:
            self._merge(files[0], MERGED_FILES[files[0].path])
            return
        if all(mission_owned(item.path) for item in files):
            self._files.extend(files)
            return
        existing = {item.path: self._repo.read(item.path) for item in files}
        collides = [item for item in files if existing[item.path] not in (None, item.content)]
        resolution = self._resolve(label, None, ConflictCategory.OTHER) if collides else None
        if resolution is ConflictPolicy.REPO_WINS:
            self._skipped.extend(item.path for item in files)
            return
        for item in collides:
            original = existing[item.path]
            assert original is not None
            self._originals[item.path] = original
        self._files.extend(files)
        owner = self._item(files[0].path)
        if owner is not None:
            self._placed[owner] = label.rstrip("/")

    def _resolve(self, path: str, key: str | None, category: ConflictCategory) -> ConflictPolicy:
        resolution = self._policy.resolution(category)
        self._conflicts.append(
            LayeringConflict(path=path, key=key, category=category, resolution=resolution)
        )
        if resolution is ConflictPolicy.REFUSE:
            where = f"{path} {key}" if key else path
            raise LayeringRefused(
                f"{where}: the repository already defines it differently "
                f"(materialization.conflicts resolves {category.value} conflicts as refuse)"
            )
        return resolution

    # -- structural merges -----------------------------------------------------------------------

    def _merge(self, item: ProjectedFile, merge_format: MergeFormat) -> None:
        repo = self._repo.read(item.path)
        keys = _Keys()
        if merge_format is MergeFormat.INSTRUCTIONS_OVERRIDE:
            content: bytes | None = self._merge_instructions(item, keys)
        elif repo is None:
            content = (
                _codex_block(item.content.decode("utf-8"), keys)
                if merge_format is MergeFormat.CODEX_CONFIG
                else _json_keys(item.content, merge_format, keys)
            )
        else:
            try:
                if merge_format is MergeFormat.CODEX_CONFIG:
                    content = self._merge_codex_config(item, repo, keys)
                else:
                    content = self._merge_json(item, repo, merge_format, keys)
            except (
                _Unmergeable,
                json.JSONDecodeError,
                tomllib.TOMLDecodeError,
                UnicodeDecodeError,
            ):
                content = self._unmergeable(item, merge_format, keys)
        self._merged.append(keys.record(item.path, merge_format))
        if content is None:
            self._skipped.append(item.path)
            return
        if repo is not None and content != repo:
            self._originals[item.path] = repo
        self._files.append(ProjectedFile(path=item.path, content=content, mode=item.mode))

    def _unmergeable(
        self, item: ProjectedFile, merge_format: MergeFormat, keys: _Keys
    ) -> bytes | None:
        """The repository file cannot be parsed: the whole file is the conflict."""

        category = ConflictCategory.HOOK if merge_format in HOOK_FORMATS else ConflictCategory.OTHER
        if self._resolve(item.path, None, category) is ConflictPolicy.REPO_WINS:
            keys.kept_repo.append("*")
            return None
        keys.overridden.append("*")
        return item.content

    def _merge_json(
        self, item: ProjectedFile, repo_bytes: bytes, merge_format: MergeFormat, keys: _Keys
    ) -> bytes:
        repo = json.loads(repo_bytes)
        if not isinstance(repo, dict):
            raise _Unmergeable("not a JSON object")
        mission = json.loads(item.content)
        collection = _collection(merge_format)
        out: dict[str, Any] = dict(repo)
        for key, value in mission.items():
            if key == collection:
                self._merge_collection(item.path, merge_format, out, key, value, keys)
            elif key not in out:
                out[key] = value
                keys.mission.append(key)
            elif out[key] == value:
                keys.repo.append(key)
            elif (
                self._resolve(item.path, key, conflict_category(merge_format, key))
                is ConflictPolicy.MISSION_WINS
            ):
                out[key] = value
                keys.overridden.append(key)
            else:
                keys.kept_repo.append(key)
        keys.repo.extend(key for key in repo if key not in mission)
        if out == repo:
            return repo_bytes
        return (json.dumps(out, indent=2, ensure_ascii=False) + "\n").encode("utf-8")

    def _merge_collection(
        self,
        path: str,
        merge_format: MergeFormat,
        out: dict[str, Any],
        key: str,
        value: dict[str, Any],
        keys: _Keys,
    ) -> None:
        current = out.get(key)
        if current is None:
            out[key] = value
            keys.mission.extend(f"{key}.{name}" for name in value)
            return
        if not isinstance(current, dict):
            if (
                self._resolve(path, key, conflict_category(merge_format, key))
                is ConflictPolicy.MISSION_WINS
            ):
                out[key] = value
                keys.overridden.append(key)
            else:
                keys.kept_repo.append(key)
            return
        merged: dict[str, Any] = {}
        if merge_format in HOOK_FORMATS:
            for event, entries in current.items():
                kept = (
                    [entry for entry in entries if not _mission_hook(merge_format, entry)]
                    if isinstance(entries, list)
                    else entries
                )
                if kept:
                    merged[event] = kept
                    keys.repo.append(f"{key}.{event}")
            for event, entries in value.items():
                repo_entries = merged.get(event, [])
                if not isinstance(repo_entries, list):
                    if (
                        self._resolve(path, f"{key}.{event}", conflict_category(merge_format, key))
                        is ConflictPolicy.REPO_WINS
                    ):
                        keys.kept_repo.append(f"{key}.{event}")
                        continue
                    keys.overridden.append(f"{key}.{event}")
                    repo_entries = []
                # Mission Control's entries first: Kernel Hooks lead every hook array.
                merged[event] = [*entries, *repo_entries]
                keys.mission.append(f"{key}.{event}")
        else:
            for name, server in current.items():
                if not name.startswith(MISSION_NAME_PREFIX):
                    merged[name] = server
                    keys.repo.append(f"{key}.{name}")
            for name, server in value.items():
                if name in merged and merged[name] != server:
                    if (
                        self._resolve(path, f"{key}.{name}", conflict_category(merge_format, key))
                        is ConflictPolicy.REPO_WINS
                    ):
                        keys.kept_repo.append(f"{key}.{name}")
                        continue
                    keys.overridden.append(f"{key}.{name}")
                merged[name] = server
                keys.mission.append(f"{key}.{name}")
        out[key] = merged

    def _merge_codex_config(self, item: ProjectedFile, repo_bytes: bytes, keys: _Keys) -> bytes:
        base = _strip_marked(repo_bytes.decode("utf-8"), CODEX_CONFIG_BEGIN, CODEX_CONFIG_END)
        repo = tomllib.loads(base)
        keys.repo.extend(key for key in repo if key != "mcp_servers")
        servers = repo.get("mcp_servers", {})
        if not isinstance(servers, dict):
            raise _Unmergeable("mcp_servers is not a table")
        keys.repo.extend(f"mcp_servers.{name}" for name in servers)
        tables = _codex_tables(item.content.decode("utf-8"))
        kept: list[str] = []
        for name, table in tables.items():
            if name in servers:
                resolution = self._resolve(item.path, f"mcp_servers.{name}", ConflictCategory.OTHER)
                if resolution is ConflictPolicy.REPO_WINS:
                    keys.kept_repo.append(f"mcp_servers.{name}")
                    continue
                base = _remove_codex_table(base, name)
                if name in tomllib.loads(base).get("mcp_servers", {}):
                    raise LayeringRefused(
                        f"{item.path} mcp_servers.{name}: the repository table cannot be "
                        "replaced in place"
                    )
                keys.overridden.append(f"mcp_servers.{name}")
            kept.append(table)
            keys.mission.append(f"mcp_servers.{name}")
        block = _marked_block(kept)
        merged = (base.rstrip("\n") + "\n\n" + block if base.strip() else block).encode("utf-8")
        tomllib.loads(merged.decode("utf-8"))
        return repo_bytes if merged == repo_bytes else merged

    def _merge_instructions(self, item: ProjectedFile, keys: _Keys) -> bytes:
        """``AGENTS.override.md``: the repository's own override (outside the mission
        section) or else its ``AGENTS.md``, verbatim, then the mission section."""

        base = self._own_override(item.path)
        agents = self._repo.read("AGENTS.md")
        if base:
            keys.repo.append(item.path)
        elif agents:
            base = agents.decode("utf-8")
            keys.repo.append("AGENTS.md")
        keys.mission.append("mission section")
        section = item.content.decode("utf-8")
        merged = _join(base, section)
        if len(merged.encode("utf-8")) > CODEX_INSTRUCTIONS_LIMIT:
            merged = _join(base, mission_section(MISSION_SECTION_POINTER))
            self._overflow.append(
                f"{item.path}: the merged instructions exceed {CODEX_INSTRUCTIONS_LIMIT} bytes; "
                "the mission section is a pointer to the operating contract"
            )
            if len(merged.encode("utf-8")) > CODEX_INSTRUCTIONS_LIMIT:
                self._overflow.append(
                    f"{item.path}: the repository instructions alone exceed "
                    f"{CODEX_INSTRUCTIONS_LIMIT} bytes; Codex reads only the first part"
                )
        return merged.encode("utf-8")

    def _own_override(self, path: str) -> str:
        """The repository's own ``AGENTS.override.md`` text: outside the mission section and
        not the copy of ``AGENTS.md`` an earlier layering put there."""

        override = self._repo.read(path)
        if override is None:
            return ""
        own = _strip_section(override.decode("utf-8"))
        agents = self._repo.read("AGENTS.md")
        if not own.strip() or (agents is not None and own.strip() == agents.decode().strip()):
            return ""
        return own

    # -- discovery -------------------------------------------------------------------------------

    def _discovery(self) -> tuple[DiscoveredItem, ...]:
        layout = self._layout
        if layout is None:
            return ()
        items: list[DiscoveredItem] = []
        for entry in layout.repo_instructions:
            if self._repo.read(entry) is not None:
                if entry != layout.overlay or self._own_override(entry):
                    items.append(
                        DiscoveredItem(kind="instructions", name=entry, path=entry, origin="repo")
                    )
                continue
            for name in self._repo.children(entry):
                path = f"{entry}/{name}"
                if not mission_owned(path) and self._repo.read(path) is not None:
                    items.append(DiscoveredItem(kind="rule", name=name, path=path, origin="repo"))
        items.append(
            DiscoveredItem(
                kind="instructions", name="mission overlay", path=layout.overlay, origin="mission"
            )
        )
        items.extend(self._repo_items(layout))
        items.extend(
            DiscoveredItem(kind=kind, name=name, path=path, origin="mission")
            for (kind, name), path in sorted(self._placed.items())
        )
        placed = {item.path: item.content for item in self._files}
        for path in layout.config_files:
            fmt = MERGED_FILES[path]
            repo = self._repo.read(path)
            if repo is not None:
                items.extend(
                    DiscoveredItem(kind=kind, name=name, path=path, origin="repo")
                    for kind, name in _config_entries(repo, fmt, mission=False)
                )
            if path in placed:
                items.extend(
                    DiscoveredItem(kind=kind, name=name, path=path, origin="mission")
                    for kind, name in _config_entries(placed[path], fmt, mission=True)
                )
        return tuple(dict.fromkeys(items))

    def _repo_items(self, layout: LayeringLayout) -> list[DiscoveredItem]:
        conflicted = {conflict.path.rstrip("/") for conflict in self._conflicts}
        mission = set(self._placed.values()) - conflicted
        items: list[DiscoveredItem] = []
        for name in self._repo.children(layout.skills):
            path = f"{layout.skills}/{name}"
            if path not in mission and self._repo.read(f"{path}/SKILL.md") is not None:
                items.append(DiscoveredItem(kind="skill", name=name, path=path, origin="repo"))
        if layout.agents is not None:
            for name in self._repo.children(layout.agents):
                path = f"{layout.agents}/{name}"
                if name.endswith(layout.agent_suffix) and path not in mission:
                    items.append(
                        DiscoveredItem(
                            kind="subagent",
                            name=name.removesuffix(layout.agent_suffix),
                            path=path,
                            origin="repo",
                        )
                    )
        return items


# --- format helpers ------------------------------------------------------------------------------


def _collection(merge_format: MergeFormat) -> str:
    return "hooks" if merge_format in HOOK_FORMATS else "mcpServers"


def _runs_mission_script(handler: object) -> bool:
    if not isinstance(handler, dict):
        return False
    parts = [handler.get("command"), *(handler.get("args") or ())]
    return any(isinstance(part, str) and MISSION_HOOK_ROOT in part for part in parts)


def _mission_hook(merge_format: MergeFormat, entry: object) -> bool:
    """A hook entry Mission Control wrote: every handler runs a script under `.mission/hooks/`."""

    if merge_format is MergeFormat.CURSOR_HOOKS:
        return _runs_mission_script(entry)
    handlers = entry.get("hooks") if isinstance(entry, dict) else None
    return bool(handlers) and all(_runs_mission_script(handler) for handler in handlers or ())


def _json_keys(content: bytes, merge_format: MergeFormat, keys: _Keys) -> bytes:
    document = json.loads(content)
    collection = _collection(merge_format)
    for key, value in document.items():
        if key == collection and isinstance(value, dict):
            keys.mission.extend(f"{key}.{name}" for name in value)
        else:
            keys.mission.append(key)
    return content


def _config_entries(
    content: bytes, merge_format: MergeFormat, *, mission: bool
) -> list[tuple[DiscoveryKind, str]]:
    """(kind, name) of the hook events or MCP servers one side of a config file declares."""

    try:
        if merge_format is MergeFormat.CODEX_CONFIG:
            text = content.decode("utf-8")
            marked = _marked(text, CODEX_CONFIG_BEGIN, CODEX_CONFIG_END)
            if not mission:
                marked = _strip_marked(text, CODEX_CONFIG_BEGIN, CODEX_CONFIG_END)
            servers = tomllib.loads(marked or "").get("mcp_servers", {})
            return [("mcp_server", str(name)) for name in servers]
        document = json.loads(content)
    except (ValueError, UnicodeDecodeError):
        return []
    collection = document.get(_collection(merge_format)) if isinstance(document, dict) else None
    if not isinstance(collection, dict):
        return []
    if merge_format in HOOK_FORMATS:
        return [
            ("hook", str(event))
            for event, entries in collection.items()
            if isinstance(entries, list)
            and any(_mission_hook(merge_format, entry) is mission for entry in entries)
        ]
    return [
        ("mcp_server", str(name))
        for name in collection
        if str(name).startswith(MISSION_NAME_PREFIX) is mission
    ]


def _marked(text: str, begin: str, end: str) -> str | None:
    lines = text.splitlines()
    if begin not in lines:
        return None
    start = lines.index(begin)
    stop = lines.index(end, start) if end in lines[start:] else len(lines) - 1
    return "\n".join(lines[start + 1 : stop]) + "\n"


def _strip_marked(text: str, begin: str, end: str) -> str:
    """``text`` without the block between ``begin`` and ``end`` (inclusive)."""

    lines = text.splitlines(keepends=True)
    stripped = [line.rstrip("\r\n") for line in lines]
    if begin not in stripped:
        return text
    start = stripped.index(begin)
    stop = stripped.index(end, start) if end in stripped[start:] else len(lines) - 1
    head = "".join(lines[:start]).rstrip("\n")
    tail = "".join(lines[stop + 1 :]).lstrip("\n")
    return "\n\n".join(part for part in (head, tail) if part) + ("\n" if head or tail else "")


def _strip_section(text: str) -> str:
    return _strip_marked(text, MISSION_SECTION_BEGIN, MISSION_SECTION_END)


def _join(base: str, section: str) -> str:
    return base.rstrip("\n") + "\n\n" + section if base.strip() else section


def _codex_tables(text: str) -> dict[str, str]:
    """The rendered ``[mcp_servers.<name>]`` tables of a projected Codex config, by name."""

    tables: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in text.splitlines():
        if _TABLE_HEADER.match(line):
            name = next(iter(tomllib.loads(line + "\n").get("mcp_servers", {})), None)
            if name is None:
                raise ValueError(f"unexpected table in a projected Codex config: {line}")
            current = tables.setdefault(str(name), [])
        if current is not None and line.strip():
            current.append(line)
    return {name: "\n".join(lines) + "\n" for name, lines in tables.items()}


def _codex_block(text: str, keys: _Keys) -> bytes:
    tables = _codex_tables(text)
    keys.mission.extend(f"mcp_servers.{name}" for name in tables)
    return _marked_block(list(tables.values())).encode("utf-8")


def _marked_block(tables: Sequence[str]) -> str:
    return CODEX_CONFIG_BEGIN + "\n" + "\n".join(tables) + CODEX_CONFIG_END + "\n"


def _remove_codex_table(text: str, name: str) -> str:
    """``text`` without the ``[mcp_servers.<name>]`` table (and its sub-tables)."""

    out: list[str] = []
    skipping = False
    for line in text.splitlines(keepends=True):
        if _TABLE_HEADER.match(line):
            try:
                parsed = tomllib.loads(line.strip() + "\n")
            except tomllib.TOMLDecodeError:
                parsed = {}
            skipping = name in parsed.get("mcp_servers", {})
        if not skipping:
            out.append(line)
    return "".join(out)


# --- restoring repository files ------------------------------------------------------------------


def _digest(content: bytes) -> str:
    return "sha256:" + sha256(content).hexdigest()


def write_layering_record(root: Path, layered: LayeredProjection) -> None:
    """Keep the repository bytes of every file this layering changes under ``.mission/``.

    A record left by an earlier layering in the same workspace (a reused lease) is carried
    over for files still holding what that layering wrote, so the original kept is always the
    repository's, never an earlier merge.
    """

    target = root / LAYERING_RECORD_PATH
    previous = _read_record(target)
    written = {item.path: _digest(item.content) for item in layered.files}
    entries = {
        path: entry
        for path, entry in previous.items()
        if written.get(path) == entry["written_digest"]
    }
    for path, original in layered.originals.items():
        earlier = previous.get(path)
        if earlier is not None and _digest(original) == earlier["written_digest"]:
            original = base64.b64decode(earlier["original"])
        entries[path] = {
            "path": path,
            "original": base64.b64encode(original).decode("ascii"),
            "written_digest": written[path],
        }
    if not entries:
        target.unlink(missing_ok=True)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "schema_version": LAYERING_RECORD_SCHEMA,
        "files": [entries[path] for path in sorted(entries)],
    }
    target.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_record(target: Path) -> dict[str, dict[str, str]]:
    if not target.is_file():
        return {}
    document = json.loads(target.read_text(encoding="utf-8"))
    return {entry["path"]: entry for entry in document.get("files", ())}


def restore_repository_files(root: Path) -> tuple[str, ...]:
    """Put back the repository bytes of every file layering changed in this workspace.

    A file the session changed since (its bytes differ from what layering wrote) is left as
    the session left it. Returns the restored paths; the record is removed.
    """

    target = root / LAYERING_RECORD_PATH
    restored: list[str] = []
    for path, entry in _read_record(target).items():
        file = root.joinpath(*PurePosixPath(path).parts)
        if file.is_symlink() or not file.is_file():
            continue
        if _digest(file.read_bytes()) != entry["written_digest"]:
            continue
        file.write_bytes(base64.b64decode(entry["original"]))
        restored.append(path)
    target.unlink(missing_ok=True)
    return tuple(restored)


__all__ = [
    "LAYERING_RECEIPT_SCHEMA",
    "LAYERING_RECORD_PATH",
    "MATERIALIZATION_CONFLICT",
    "DirectoryView",
    "DiscoveredItem",
    "LayeredProjection",
    "LayeringConflict",
    "LayeringReceipt",
    "LayeringRefused",
    "MergedConfig",
    "RepoView",
    "TreeView",
    "layer_projection",
    "repository_roots",
    "restore_repository_files",
    "write_layering_record",
]
