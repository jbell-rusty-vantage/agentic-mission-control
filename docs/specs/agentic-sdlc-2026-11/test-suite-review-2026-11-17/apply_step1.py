"""Step 1 of the test-suite review: delete the test files listed in step1-deletions.tsv.

Run from the Mission Control repository root:

    python docs/specs/agentic-sdlc-2026-11/test-suite-review-2026-11-17/apply_step1.py --dry-run
    python docs/specs/agentic-sdlc-2026-11/test-suite-review-2026-11-17/apply_step1.py --groups A-no-decision
    python docs/specs/agentic-sdlc-2026-11/test-suite-review-2026-11-17/apply_step1.py --groups all

It stages the deletions with `git rm` (recoverable with `git restore --staged --worktree <path>`
until committed), removes the unused Codex 0.162.0 schema fixture with group A, then runs
`pytest --collect-only` so an import that still points at a deleted file fails at once.
It never deletes src code; the src removals that pair with group B are listed in RECOMMENDATION.md.
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "step1-deletions.tsv"
UNUSED_FIXTURE_DIR = "tests/fixtures/provider_frames/codex/schema"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--groups", default="A-no-decision", help="comma list of groups, or 'all'")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    rows = list(csv.DictReader(MANIFEST.open(encoding="utf-8"), delimiter="\t"))
    known = sorted({row["group"] for row in rows})
    wanted = set(known) if args.groups == "all" else set(args.groups.split(","))
    unknown = wanted - set(known)
    if unknown:
        print(f"unknown groups {sorted(unknown)}; known: {known}", file=sys.stderr)
        return 2

    paths = [row["path"] for row in rows if row["group"] in wanted and Path(row["path"]).exists()]
    if "A-no-decision" in wanted and Path(UNUSED_FIXTURE_DIR).exists():
        paths.append(UNUSED_FIXTURE_DIR)
    tests = sum(int(row["tests"] or 0) for row in rows if row["group"] in wanted)
    print(f"{len(paths)} paths, ~{tests} test functions, groups {sorted(wanted)}")
    for path in paths:
        print("  ", path)
    if args.dry_run or not paths:
        return 0

    subprocess.run(["git", "rm", "-r", "-q", "--", *paths], check=True)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "--collect-only", "-q", "-p", "no:cacheprovider"],
        capture_output=True,
        check=False,
        text=True,
    )
    print(
        result.stdout.strip().splitlines()[-1] if result.stdout.strip() else result.stderr[-2000:]
    )
    if result.returncode != 0:
        print(result.stdout[-4000:], file=sys.stderr)
        print(
            "collection failed: restore with git restore --staged --worktree <paths>",
            file=sys.stderr,
        )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
