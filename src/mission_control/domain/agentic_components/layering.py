"""Additive instruction layering and structural config merge (SPEC-02 §4, ADR-0044).

The repository's own instructions always load unchanged; the mission overlay goes through
each provider's additive channel instead of overwriting or refusing ``AGENTS.md`` /
``CLAUDE.md``. Structured config files the repository may already own are merged, never
replaced: repository entries are preserved, Mission Control's entries carry a provenance
marker, and a conflict resolves by the manifest's ``materialization.conflicts`` policy.

This module is the policy, kept apart from the merge itself
(``application/agentic_components/layering.py``); where each lane's overlay goes and which
repository instruction files, cognition roots and config files it reads are rows of the
per-lane layout table (``domain/capabilities/layouts.py``, ``LAYERING_LAYOUTS``):

- :class:`MaterializationPolicy`, the manifest's ``materialization`` block;
- :data:`MERGED_FILES`, the structured config files merged and their formats;
- the provenance markers: paths under ``.mission/``, names with the ``mc-`` prefix, and
  hook entries whose command runs a script under ``.mission/hooks/``.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

MISSION_ROOT: Final = ".mission/"
MISSION_HOOK_ROOT: Final = ".mission/hooks/"
MISSION_NAME_PREFIX: Final = "mc-"
OPERATING_CONTRACT_PATH: Final = ".mission/operating-contract.md"


class ConflictPolicy(StrEnum):
    """How a repository entry and a Mission Control entry with the same key resolve."""

    REFUSE = "refuse"
    MISSION_WINS = "mission_wins"
    REPO_WINS = "repo_wins"


class ConflictCategory(StrEnum):
    PERMISSION = "permission"
    HOOK = "hook"
    OTHER = "other"


DEFAULT_CONFLICT_POLICY: Final[Mapping[ConflictCategory, ConflictPolicy]] = {
    ConflictCategory.PERMISSION: ConflictPolicy.REFUSE,
    ConflictCategory.HOOK: ConflictPolicy.REFUSE,
    ConflictCategory.OTHER: ConflictPolicy.REPO_WINS,
}


class MaterializationPolicy(BaseModel):
    """The manifest's ``materialization`` block. ``conflicts`` absent: ``refuse`` for
    permission and hook conflicts, ``repo_wins`` for the rest; a declared value applies to
    every category."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    conflicts: ConflictPolicy | None = None
    ambient: Literal["allow", "inventory", "refuse_conflicts"] = Field(
        default="inventory",
        exclude_if=lambda value: value == "inventory",
        json_schema_extra={"digest_omit_default": True},
    )

    def resolution(self, category: ConflictCategory) -> ConflictPolicy:
        return self.conflicts or DEFAULT_CONFLICT_POLICY[category]


class MergeFormat(StrEnum):
    # Claude Code and Codex: ``{"hooks": {Event: [{"matcher", "hooks": [handler]}]}}``.
    MATCHER_HOOKS = "matcher_hooks"
    # Cursor: ``{"version": 1, "hooks": {event: [handler]}}``.
    CURSOR_HOOKS = "cursor_hooks"
    # ``{"mcpServers": {name: server}}`` (Claude Code `.mcp.json`, Cursor `.cursor/mcp.json`).
    MCP_JSON = "mcp_json"
    # Codex project config: ``[mcp_servers.<name>]`` tables.
    CODEX_CONFIG = "codex_config"
    # codex_cloud `AGENTS.override.md`: repository `AGENTS.md` plus a delimited mission section.
    INSTRUCTIONS_OVERRIDE = "instructions_override"


MERGED_FILES: Final[Mapping[str, MergeFormat]] = {
    ".claude/settings.json": MergeFormat.MATCHER_HOOKS,
    ".codex/hooks.json": MergeFormat.MATCHER_HOOKS,
    ".cursor/hooks.json": MergeFormat.CURSOR_HOOKS,
    ".mcp.json": MergeFormat.MCP_JSON,
    ".cursor/mcp.json": MergeFormat.MCP_JSON,
    ".codex/config.toml": MergeFormat.CODEX_CONFIG,
    "AGENTS.override.md": MergeFormat.INSTRUCTIONS_OVERRIDE,
}
HOOK_FORMATS: Final = frozenset({MergeFormat.MATCHER_HOOKS, MergeFormat.CURSOR_HOOKS})
# Keys that grant or withhold permissions wherever they appear in a merged file.
PERMISSION_KEYS: Final = frozenset(
    {"permissions", "approval_policy", "sandbox_mode", "sandbox_workspace_write"}
)


def conflict_category(merge_format: MergeFormat, key: str) -> ConflictCategory:
    """The category a conflicting key falls in (its default resolution follows from it)."""

    if key.split(".", 1)[0] in PERMISSION_KEYS:
        return ConflictCategory.PERMISSION
    if merge_format in HOOK_FORMATS:
        return ConflictCategory.HOOK
    return ConflictCategory.OTHER


def mission_owned(path: str) -> bool:
    """Files Mission Control owns outright: under ``.mission/`` or named with ``mc-``."""

    normalized = path.replace("\\", "/")
    return normalized.startswith(MISSION_ROOT) or any(
        part.startswith(MISSION_NAME_PREFIX) for part in PurePosixPath(normalized).parts
    )


def mission_name(name: str) -> str:
    """A Mission Control entry name in a merged file (its provenance marker)."""

    return name if name.startswith(MISSION_NAME_PREFIX) else MISSION_NAME_PREFIX + name


MISSION_SECTION_BEGIN: Final = "<!-- mission-control: begin mission section (generated) -->"
MISSION_SECTION_END: Final = "<!-- mission-control: end mission section -->"
MISSION_SECTION_POINTER: Final = (
    f"Mission instructions: read {OPERATING_CONTRACT_PATH} before acting. They are kept out "
    "of this file because it would exceed the Codex instruction size limit."
)


def mission_section(instructions: str) -> str:
    """The delimited mission section appended after the repository's own instructions."""

    return f"{MISSION_SECTION_BEGIN}\n## Mission\n\n{instructions.strip()}\n{MISSION_SECTION_END}\n"


__all__ = [
    "DEFAULT_CONFLICT_POLICY",
    "HOOK_FORMATS",
    "MERGED_FILES",
    "MISSION_HOOK_ROOT",
    "MISSION_NAME_PREFIX",
    "MISSION_ROOT",
    "MISSION_SECTION_BEGIN",
    "MISSION_SECTION_END",
    "MISSION_SECTION_POINTER",
    "OPERATING_CONTRACT_PATH",
    "PERMISSION_KEYS",
    "ConflictCategory",
    "ConflictPolicy",
    "MaterializationPolicy",
    "MergeFormat",
    "conflict_category",
    "mission_name",
    "mission_owned",
    "mission_section",
]
