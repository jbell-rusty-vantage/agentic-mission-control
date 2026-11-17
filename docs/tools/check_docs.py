#!/usr/bin/env python3
"""Run every offline documentation check in one command and report them separately.

The checks, in order (names for ``--only``):

  okf       docs/tools/validate_okf.py                 the docs/knowledge OKF bundle
  index     docs/tools/agents_docs_index.py --check    the compiled index in AGENTS.md
  ledgers   docs/tools/program_ledger.py check         every docs/specs/<program>/LEDGER.md
  links     docs/tools/check_links.py                  relative Markdown links
  skills    scripts/skills_manifest.py --check         shipped bundle manifests under skills/
  bench     docs/tools/bench_retrieval.py --gate       the retrieval fixtures (slow; --bench)
  upstream  scripts/dev/check_matt_pocock_skills.py    the Matt Pocock set (network; --upstream)

Usage:
  python docs/tools/check_docs.py                 # all offline checks; exit 1 when any fails
  python docs/tools/check_docs.py --only ledgers,index
  python docs/tools/check_docs.py --upstream      # add the network check of the upstream set
  python docs/tools/check_docs.py --bench         # add the slow retrieval-fixture gate
  python docs/tools/check_docs.py --hook          # exit 2 on failure, failures on stderr (hooks)
  python docs/tools/check_docs.py --list

Convention: ``docs/agents/documentation-surfaces.md`` (where a fact goes) and the
``belllabs-method`` skill (when to run this). Each underlying tool keeps its own usage; this one
only runs them and reports passed, failed and unrun, never fixing anything.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SPECS = REPO_ROOT / "docs" / "specs"


def utf8_console() -> None:
    """Print UTF-8 on a Windows console; a no-op where the stream cannot be reconfigured."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


@dataclass(frozen=True)
class Check:
    name: str
    argv: tuple[str, ...]
    what: str
    network: bool = False
    slow: bool = False


def programs() -> list[Path]:
    """Every program folder directly under docs/specs with a LEDGER.md (the archive has none)."""
    if not SPECS.is_dir():
        return []
    return sorted(p for p in SPECS.iterdir() if p.is_dir() and (p / "LEDGER.md").is_file())


def all_checks() -> list[Check]:
    py = sys.executable
    checks = [
        Check("okf", (py, "docs/tools/validate_okf.py"), "docs/knowledge OKF bundle"),
        Check(
            "index", (py, "docs/tools/agents_docs_index.py", "--check"), "AGENTS.md compiled index"
        ),
    ]
    for program in programs():
        rel = program.relative_to(REPO_ROOT).as_posix()
        argv = (py, "docs/tools/program_ledger.py", "check", "--program", rel)
        checks.append(Check("ledgers", argv, f"{rel}/LEDGER.md"))
    checks += [
        Check("links", (py, "docs/tools/check_links.py"), "relative Markdown links"),
        Check(
            "skills",
            (py, "scripts/skills_manifest.py", "--check"),
            "shipped skill bundle manifests",
        ),
        Check(
            "bench",
            (py, "docs/tools/bench_retrieval.py", "--gate"),
            "retrieval fixtures (critical cases and regressions)",
            slow=True,
        ),
        Check(
            "upstream",
            (py, "scripts/dev/check_matt_pocock_skills.py"),
            "Matt Pocock skills byte-identical to upstream",
            network=True,
        ),
    ]
    return checks


def run(check: Check) -> tuple[str, str]:
    """Return (result, output): result is passed, failed or unrun (tool missing)."""
    script = REPO_ROOT / check.argv[1]
    if not script.is_file():
        return "unrun", f"{check.argv[1]} does not exist"
    completed = subprocess.run(
        list(check.argv),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    output = (completed.stdout + completed.stderr).strip()
    return ("passed" if completed.returncode == 0 else "failed"), output


def select(
    checks: list[Check], wanted: set[str] | None, upstream: bool, bench: bool = False
) -> list[Check]:
    """The checks to run: the named ones, or every offline one plus the network one on request."""
    chosen = []
    for check in checks:
        named = wanted is not None and check.name in wanted
        if wanted is not None and not named:
            continue
        if check.network and not (upstream or named):
            continue
        if check.slow and not (bench or named):
            continue
        chosen.append(check)
    return chosen


def main() -> int:
    utf8_console()
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--only", help="comma-separated check names to run")
    parser.add_argument("--upstream", action="store_true", help="include the network check")
    parser.add_argument(
        "--bench", action="store_true", help="include the slow retrieval-fixture gate"
    )
    parser.add_argument("--hook", action="store_true", help="exit 2 on failure; failures to stderr")
    parser.add_argument("--list", action="store_true", help="list the checks and exit")
    parser.add_argument("--quiet", action="store_true", help="print only the summary line")
    args = parser.parse_args()

    checks = all_checks()
    if args.list:
        for check in checks:
            tag = " (network)" if check.network else " (slow)" if check.slow else ""
            print(f"{check.name:9} {check.what}{tag}")
        return 0
    wanted = {n.strip() for n in args.only.split(",")} if args.only else None
    unknown = (wanted or set()) - {c.name for c in checks}
    if unknown:
        print(f"unknown check(s): {', '.join(sorted(unknown))}", file=sys.stderr)
        return 2

    results: list[tuple[Check, str, str]] = []
    for check in select(checks, wanted, args.upstream, args.bench):
        result, output = run(check)
        results.append((check, result, output))
        if not args.quiet and not args.hook:
            print(f"[{result}] {check.name}: {check.what}")
            if output and result != "passed":
                print("\n".join(f"    {line}" for line in output.splitlines()[-40:]))

    failed = [(c, o) for c, r, o in results if r == "failed"]
    unrun = [c for c, r, _ in results if r == "unrun"]
    passed = len(results) - len(failed) - len(unrun)
    summary = f"{passed} passed, {len(failed)} failed, {len(unrun)} unrun ({len(results)} checks)"
    if args.hook:
        if failed:
            for check, output in failed:
                tail = "\n".join(output.splitlines()[-15:])
                print(f"docs check failed: {check.name} ({check.what})\n{tail}", file=sys.stderr)
            print(summary, file=sys.stderr)
            return 2
        return 0
    print(summary)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
