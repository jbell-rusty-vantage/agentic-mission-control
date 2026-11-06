#!/usr/bin/env python3
"""Give Claude Code the same skills Cursor and Codex read from ``.agents/skills``.

Cursor and Codex discover ``.agents/skills/<name>/SKILL.md`` natively. Claude Code reads
``.claude/skills/``, so this repository keeps machine-local links there (git-ignored; see
``.gitignore``). This script creates the missing links and reports the rest. It never deletes a
real directory under ``.claude/skills`` (``mission-control-docs`` is a local copy there) and never
touches ``.agents/skills``.

Usage:
  python scripts/dev/link_claude_skills.py            # create missing links, report state
  python scripts/dev/link_claude_skills.py --check    # report only; exit 1 on missing or dangling

On Windows a directory symlink needs Developer Mode or elevation; when the symlink is refused the
script falls back to a directory junction (``mklink /J``), which Claude Code reads the same way.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE = REPO_ROOT / ".agents" / "skills"
TARGET = REPO_ROOT / ".claude" / "skills"


def utf8_console() -> None:
    """Print UTF-8 on a Windows console; a no-op where the stream cannot be reconfigured."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def is_link(path: Path) -> bool:
    """A symlink or an NTFS junction (``is_junction`` exists on Python 3.12+)."""
    return path.is_symlink() or bool(getattr(path, "is_junction", lambda: False)())


def link(source: Path, dest: Path) -> str:
    try:
        dest.symlink_to(source, target_is_directory=True)
        return "symlink"
    except OSError:
        if os.name != "nt":
            raise
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(dest), str(source)], check=True, capture_output=True
        )
        return "junction"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--check", action="store_true", help="report only; exit 1 on a missing or dangling link"
    )
    args = parser.parse_args()
    utf8_console()

    skills = sorted(p for p in SOURCE.iterdir() if p.is_dir() and (p / "SKILL.md").is_file())
    TARGET.mkdir(parents=True, exist_ok=True)
    missing: list[str] = []
    created: list[str] = []
    local_copies: list[str] = []
    for skill in skills:
        dest = TARGET / skill.name
        if is_link(dest):
            if not (dest / "SKILL.md").is_file():
                missing.append(f"{skill.name} (dangling link)")
            continue
        if dest.is_dir():
            local_copies.append(skill.name)
            continue
        if args.check:
            missing.append(skill.name)
            continue
        created.append(f"{skill.name} ({link(skill, dest)})")
    reported = {m.split(" ")[0] for m in missing}
    dangling = [
        p.name
        for p in TARGET.iterdir()
        if is_link(p) and not (p / "SKILL.md").is_file() and p.name not in reported
    ]

    for name in created:
        print(f"linked   {name}")
    for name in local_copies:
        print(f"copy     {name} (real directory under .claude/skills; left alone)")
    for name in missing:
        print(f"missing  {name}")
    for name in dangling:
        print(f"dangling {name} (points nowhere; remove by hand)")
    linked = sum(
        1 for s in skills if is_link(TARGET / s.name) and (TARGET / s.name / "SKILL.md").is_file()
    )
    print(
        f"{len(skills)} skills in .agents/skills; {linked} linked, "
        f"{len(local_copies)} local copies, {len(missing)} missing"
    )
    return 1 if (missing or dangling) else 0


if __name__ == "__main__":
    sys.exit(main())
