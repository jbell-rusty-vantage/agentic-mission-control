#!/usr/bin/env python3
"""Compare the Matt Pocock skills in .agents/skills with upstream (mattpocock/skills, main).

Read-only. Compares the promoted buckets (``engineering`` and ``productivity``) file by file,
ignoring line endings, and lists upstream skills this repository does not carry. Skills that only
exist locally are ours and are listed for information.

Usage:
  python scripts/dev/check_matt_pocock_skills.py            # exit 1 when a carried skill drifted
  python scripts/dev/check_matt_pocock_skills.py --ref v1.3.1

Needs network access (one GitHub API call for the tree, then raw file downloads).
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

REPO = "mattpocock/skills"
PROMOTED = ("engineering", "productivity")
SKILLS_DIR = Path(__file__).resolve().parents[2] / ".agents" / "skills"


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", default="main", help="branch, tag or commit (default: main)")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    tree = json.loads(
        fetch(f"https://api.github.com/repos/{REPO}/git/trees/{args.ref}?recursive=1")
    )
    upstream: dict[str, list[tuple[str, str]]] = {}
    for entry in tree["tree"]:
        parts = entry["path"].split("/")
        if entry["type"] == "blob" and len(parts) >= 4 and parts[0] == "skills":
            if parts[1] in PROMOTED:
                upstream.setdefault(parts[2], []).append((parts[1], "/".join(parts[3:])))

    local = {p.name for p in SKILLS_DIR.iterdir() if p.is_dir()}
    drift: list[str] = []
    for skill, files in sorted(upstream.items()):
        if skill not in local:
            print(f"not carried: {skill} ({files[0][0]})")
            continue
        for bucket, rel in files:
            local_file = SKILLS_DIR / skill / rel
            if not local_file.is_file():
                drift.append(f"missing locally: {skill}/{rel}")
                continue
            raw = fetch(
                f"https://raw.githubusercontent.com/{REPO}/{args.ref}/skills/{bucket}/{skill}/{rel}"
            )
            if local_file.read_bytes().replace(b"\r\n", b"\n") != raw.replace(b"\r\n", b"\n"):
                drift.append(f"differs: {skill}/{rel}")

    ours = sorted(local - set(upstream))
    print(f"\nlocal only ({len(ours)}): {', '.join(ours)}")
    print(
        f"\nupstream ref {args.ref}: {len(upstream)} promoted skills, {len(drift)} drifted file(s)"
    )
    for line in drift:
        print(f"  {line}")
    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit(main())
