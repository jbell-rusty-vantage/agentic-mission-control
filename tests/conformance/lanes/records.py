"""Qualification records the describe-honesty gate reads (docs/qualification/lanes/README.md).

A profile flips `qualified` only with a recorded live drill: a `<profile>-<date>.md` record
whose front matter says `outcome: qualified` and `evidence: live_drill`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[3]
QUALIFICATION_DIR: Final = ROOT / "docs" / "qualification" / "lanes"
# Qualified before live-drill records existed: the FT-G1 Deep Agents lane, qualified by its
# acceptance suite (application/execution/harness/describe.py, DEEP_AGENTS_DESCRIBE).
BASELINE_QUALIFICATIONS: Final = {"deep_agents": "tests/acceptance/control_plane/test_wp_cp_040.py"}


def front_matter(profile: str, root: Path = QUALIFICATION_DIR) -> list[dict[str, str]]:
    """The front matter of every `<profile>-*.md` record under `root`."""

    records: list[dict[str, str]] = []
    for path in sorted(root.glob(f"{profile}-*.md")):
        text = path.read_text("utf-8")
        if not text.startswith("---"):
            continue
        header = text.split("---", 2)[1]
        values = dict(line.split(":", 1) for line in header.strip().splitlines() if ":" in line)
        records.append({key.strip(): value.strip().strip('"') for key, value in values.items()})
    return records


def live_drills(profile: str, root: Path = QUALIFICATION_DIR) -> list[dict[str, str]]:
    """The records that qualify `profile`: a recorded live drill with outcome `qualified`."""

    return [
        record
        for record in front_matter(profile, root)
        if record.get("outcome") == "qualified" and record.get("evidence") == "live_drill"
    ]


__all__ = ["BASELINE_QUALIFICATIONS", "QUALIFICATION_DIR", "ROOT", "front_matter", "live_drills"]
