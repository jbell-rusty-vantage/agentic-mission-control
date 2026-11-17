#!/usr/bin/env python3
"""./dev: one front door for a coding agent working on this repository.

Not the service CLI: ``missionctl`` stays the product surface. ``./dev`` wraps what exists
(make targets, docs/tools) behind one grammar: every input is a flag, ``--help`` everywhere, JSON on
stdout where a result is data, typed exit codes, and an error names the fix. Groups are added
only when a feature needs them (handoff 2026-11-17 §3.1; SPEC-02). Standard library only, so
``./dev status`` and ``./dev doctor`` work before ``uv sync``.

  ./dev status                         orient in one call: branch, ahead, dirty, hooks, trace
  ./dev doctor                         read-only readiness; each failure prints its fix
  ./dev check [--full]                 make check (fast gate) or make ci + the provenance check
  ./dev test LAYER [-k EXPR] [PATH..]  unit, arch, conformance, integration, acceptance, db-contract
  ./dev trace show|build|check|linear  the provenance chain (docs/tools/trace.py)

Exit codes: 0 ok, 1 a check or test failed, 2 usage error, 3 the environment is not ready.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRACE = ROOT / "docs" / "tools" / "trace.py"
ENTRYPOINTS = [
    "AGENTS.md",
    "docs/specs/provider-consolidation-2026-10/sprint-oc/NEXT-SESSION.md",
    "docs/specs/agentic-sdlc-2026-11/SPEC-02-PROVENANCE-CHAIN.md",
]
LAYERS = {
    "unit": ["tests/unit"],
    "arch": ["tests/architecture"],
    "conformance": ["tests/conformance"],
    "integration": ["tests/integration"],
    "acceptance": ["tests/acceptance"],
    "db-contract": ["packages/mission-control-db-contract/tests"],
}
NEEDS_STACK = {"integration", "acceptance"}


def git(*args: str) -> str:
    done = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return done.stdout.strip() if done.returncode == 0 else ""


def emit(data: object) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def fail(message: str, fix: str, code: int = 2) -> int:
    print(f"dev: {message}\n  fix: {fix}", file=sys.stderr)
    return code


def run(command: list[str], env: dict[str, str] | None = None) -> int:
    print(f"$ {' '.join(command)}", file=sys.stderr, flush=True)
    return subprocess.run(command, cwd=ROOT, check=False, env=env).returncode


# ------------------------------------------------------------------------------------- status


def status() -> int:
    upstream = git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    ahead = behind = None
    if upstream:
        counts = git("rev-list", "--left-right", "--count", f"{upstream}...HEAD").split()
        if len(counts) == 2:
            behind, ahead = int(counts[0]), int(counts[1])
    porcelain = [line for line in git("status", "--porcelain").splitlines() if line]
    hooks = ROOT / ".git" / "hooks"
    trace_dir = ROOT / ".sdlc" / "trace"
    snapshot = trace_dir / "linear-snapshot.json"
    fetched = None
    if snapshot.is_file():
        try:
            fetched = json.loads(snapshot.read_text(encoding="utf-8")).get("fetched_at")
        except (OSError, json.JSONDecodeError):
            fetched = "unreadable"
    hints = []
    if ahead:
        hints.append(f"{ahead} commit(s) not pushed to {upstream}")
    if not (hooks / "commit-msg").is_file():
        hints.append("the commit-msg hook is missing: run `make hooks`")
    if fetched is None:
        hints.append(
            "no Linear snapshot: `./dev trace linear pull` (or write it from the Linear MCP)"
        )
    emit(
        {
            "repo": "mission-control",
            "branch": git("branch", "--show-current"),
            "head": git("log", "-1", "--format=%h %s"),
            "upstream": upstream or None,
            "ahead": ahead,
            "behind": behind,
            "modified": sum(1 for line in porcelain if not line.startswith("??")),
            "untracked": sum(1 for line in porcelain if line.startswith("??")),
            "hooks": {name: (hooks / name).is_file() for name in ("pre-commit", "commit-msg")},
            "trace": {
                "snapshot_fetched_at": fetched,
                "coverage": ".sdlc/trace/COVERAGE.md"
                if (trace_dir / "COVERAGE.md").is_file()
                else None,
            },
            "entrypoints": ENTRYPOINTS,
            "hints": hints,
        }
    )
    return 0


# ------------------------------------------------------------------------------------- doctor


def doctor() -> int:
    checks: list[dict[str, object]] = []

    def record(name: str, ok: bool, detail: str, fix: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail, "fix": None if ok else fix})

    for tool, fix in (
        ("git", "install Git for Windows"),
        ("uv", "install uv: https://docs.astral.sh/uv/"),
        ("make", "install GNU make (choco install make)"),
        ("docker", "install Docker Desktop; only the runtime stack needs it"),
    ):
        found = shutil.which(tool)
        record(tool, found is not None, found or "not on PATH", fix)
    record(
        "python",
        sys.version_info >= (3, 12),
        sys.version.split()[0],
        "use Python 3.12 or newer (uv python install)",
    )
    venv = ROOT / ".venv"
    record("venv", venv.is_dir(), ".venv present" if venv.is_dir() else "absent", "make install")
    env_file = ROOT / ".env"
    record(
        ".env",
        env_file.is_file(),
        "present (values not read)" if env_file.is_file() else "absent",
        "copy .env.example to .env; then `make env-check` lists missing names",
    )
    hooks = ROOT / ".git" / "hooks"
    for hook in ("pre-commit", "commit-msg"):
        record(f"hook {hook}", (hooks / hook).is_file(), str(hooks / hook), "make hooks")
    if shutil.which("docker"):
        try:
            daemon = subprocess.run(
                ["docker", "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            ok, detail = daemon.returncode == 0, daemon.stdout.strip() or "daemon not reachable"
        except subprocess.TimeoutExpired:
            ok, detail = False, "docker info timed out"
        record(
            "docker daemon", ok, detail, "start Docker Desktop (only the runtime stack needs it)"
        )
    failed = [c for c in checks if not c["ok"] and c["name"] not in ("docker", "docker daemon")]
    emit({"ok": not failed, "checks": checks})
    return 3 if failed else 0


# ---------------------------------------------------------------------------- check and test


def check(full: bool) -> int:
    if not shutil.which("make"):
        return fail("make is not on PATH", "install GNU make, or run `./dev doctor`", 3)
    code = run(["make", "ci" if full else "check"])
    if full:
        upstream = git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
        revision_range = f"{upstream}..HEAD" if upstream else "HEAD~1..HEAD"
        trace_code = run(
            [sys.executable, "-X", "utf8", str(TRACE), "check", "--range", revision_range]
        )
        code = code or trace_code
    return 1 if code else 0


def test(layer: str, expression: str | None, paths: list[str]) -> int:
    if not shutil.which("uv"):
        return fail("uv is not on PATH", "install uv, then `make install`", 3)
    command = ["uv", "run", "--no-sync", "pytest", *(paths or LAYERS[layer])]
    if expression:
        command += ["-k", expression]
    if layer in NEEDS_STACK:
        print(
            f"dev: {layer} tests need the compose services (`make dev`); unreachable services "
            "fail the run",
            file=sys.stderr,
        )
    return 1 if run(command) else 0


def trace(args: list[str]) -> int:
    if not args:
        args = ["--help"]
    return run([sys.executable, "-X", "utf8", str(TRACE), *args], env=dict(os.environ))


# --------------------------------------------------------------------------------------- main


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    parser = argparse.ArgumentParser(
        prog="./dev", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.add_parser("status", help="orient in one call (JSON)", description="Example: ./dev status")
    sub.add_parser(
        "doctor", help="read-only readiness (JSON); each failure names its fix",
        description="Example: ./dev doctor",
    )  # fmt: skip
    p_check = sub.add_parser(
        "check",
        help="the gate: make check, or --full for make ci + the provenance check",
        description="Examples: ./dev check   ./dev check --full",
    )
    p_check.add_argument("--full", action="store_true", help="what CI runs")
    p_test = sub.add_parser(
        "test",
        help="one test layer",
        description="Examples: ./dev test unit -k trace   ./dev test unit tests/unit/docs_tools",
    )
    p_test.add_argument("layer", choices=sorted(LAYERS))
    p_test.add_argument("-k", dest="expression", help="pytest -k expression")
    p_test.add_argument("paths", nargs="*", help="narrow to these paths")
    sub.add_parser(
        "trace",
        help="the provenance chain: show ID | build | check | linear pull",
        description="Examples: ./dev trace show OVE-225   ./dev trace check   ./dev trace build",
        add_help=False,
    )
    argv = sys.argv[1:]
    if argv and argv[0] == "trace":
        return trace(argv[1:])
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 2
    if args.command == "status":
        return status()
    if args.command == "doctor":
        return doctor()
    if args.command == "check":
        return check(args.full)
    return test(args.layer, args.expression, args.paths)


if __name__ == "__main__":
    sys.exit(main())
