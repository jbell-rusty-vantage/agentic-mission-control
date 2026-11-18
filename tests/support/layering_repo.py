"""A repository that already owns its cognition (MO-02, SPEC-02 §9 acceptance fixture).

Its own ``AGENTS.md``, a ``.claude/skills`` skill and a ``.cursor/hooks.json``, plus the other
structured files Mission Control merges into (``.claude/settings.json``, ``.mcp.json``,
``.codex/config.toml``), each with a repository entry the merge must keep.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path


def _json(document: object) -> bytes:
    return (json.dumps(document, indent=2) + "\n").encode("utf-8")


REPO_FILES: Mapping[str, bytes] = {
    "AGENTS.md": b"# Repository guide\n\nOwned by the repository; never rewritten.\n",
    ".claude/skills/repo-notes/SKILL.md": (
        b"---\nname: repo-notes\ndescription: The repository's own note-taking skill.\n---\n\n"
        b"Keep notes in docs/notes.md.\n"
    ),
    ".cursor/hooks.json": _json(
        {"version": 1, "hooks": {"beforeShellExecution": [{"command": "./scripts/audit.sh"}]}}
    ),
    ".claude/settings.json": _json(
        {
            "permissions": {"allow": ["Bash(make test)"]},
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [{"type": "command", "command": "./scripts/audit.sh"}],
                    }
                ]
            },
        }
    ),
    ".mcp.json": _json({"mcpServers": {"repo-docs": {"type": "stdio", "command": "repo-docs"}}}),
    ".codex/config.toml": (
        b"# The repository's own Codex settings.\n"
        b'model_reasoning_effort = "high"\n\n'
        b"[mcp_servers.repo-docs]\n"
        b'command = "repo-docs"\n'
    ),
}


def write_repository_files(root: Path, files: Mapping[str, bytes] = REPO_FILES) -> None:
    for path, content in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def repository_bytes(root: Path, files: Mapping[str, bytes] = REPO_FILES) -> dict[str, bytes]:
    """What ``root`` holds at each repository path (the comparison the acceptance makes)."""

    return {path: (root / path).read_bytes() for path in files}


__all__ = ["REPO_FILES", "repository_bytes", "write_repository_files"]
