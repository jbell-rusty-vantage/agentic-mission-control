"""Compare variable *names* in .env against .env.example. Values are never read or printed.

Informational by default: many example names have defaults in Settings, so a missing
name is reported but exits 0. ``--strict`` exits 1 on any missing name. A missing .env
always exits 1.

The database scope is also checked in code, independent of ``.env``: the database names in
``config/env.registry.yaml`` must equal the database fields of ``Settings`` and the database
block of ``.env.example``; a difference exits 1 (see ``database_registry_problems``). The
registry's other entries (GitHub, Biotech graph) must each appear in ``.env.example``.

Usage::

    uv run python scripts/dev/env_check.py [--strict] [--example .env.example] [--env .env]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NAME = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")
DB_NAME = re.compile(r"^MC_(AIENG|BIOTECH|LOCAL)_DB_[A-Z_]+$")
REGISTRY = "config/env.registry.yaml"


def registry_names(path: Path) -> set[str]:
    """Every variable name the registry lists (names only)."""

    import yaml

    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {entry["name"] for entry in document["variables"]}


def registry_database_names(path: Path) -> set[str]:
    """The database variable names the registry lists (names only)."""

    return {name for name in registry_names(path) if DB_NAME.match(name)}


def settings_database_names() -> set[str]:
    """The ``MC_<PLANE>_DB_*`` environment names of the ``Settings`` fields."""

    sys.path.insert(0, str(ROOT / "src"))
    from mission_control.bootstrap.settings import Settings

    return {name.upper() for name in Settings.model_fields if DB_NAME.match(name.upper())}


def database_registry_problems(
    registry: set[str], settings: set[str], example: set[str]
) -> list[str]:
    """Differences between the registry, the Settings fields and the .env.example block."""

    problems = []
    for label, other in (("Settings fields", settings), (".env.example", example)):
        for name in sorted(registry - other):
            problems.append(f"{name}: in the registry, not in {label}")
        for name in sorted(other - registry):
            problems.append(f"{name}: in {label}, not in the registry")
    return problems


def names(path: Path) -> set[str]:
    found: set[str] = set()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = NAME.match(line)
        if match:
            found.add(match.group(1))
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--example", default=".env.example")
    parser.add_argument("--env", default=".env")
    parser.add_argument("--strict", action="store_true", help="exit 1 when names are missing")
    args = parser.parse_args()

    example = ROOT / args.example
    env = ROOT / args.env
    if not example.exists():
        print(f"error: {args.example} not found")
        return 1
    if not env.exists():
        print(f"error: {args.env} not found; copy the missing names from {args.example}")
        return 1

    expected = names(example)
    registry_path = ROOT / REGISTRY
    problems: list[str] = []
    if registry_path.exists():
        problems = database_registry_problems(
            registry_database_names(registry_path),
            settings_database_names(),
            {name for name in expected if DB_NAME.match(name)},
        )
        problems += [
            f"{name}: in the registry, not in {args.example}"
            for name in sorted(registry_names(registry_path) - expected)
            if not DB_NAME.match(name)
        ]
        print(f"database registry: {len(problems)} difference(s)")
        for problem in problems:
            print(f"  {problem}")
    else:
        problems = [f"{REGISTRY} not found"]
        print(f"error: {REGISTRY} not found")
    present = names(env)
    missing = sorted(expected - present)
    extra = sorted(present - expected)
    print(f"{args.env}: {len(present)} names; {args.example}: {len(expected)} names")
    if missing:
        print(f"missing from {args.env} ({len(missing)}):")
        for name in missing:
            print(f"  {name}")
    if extra:
        print(f"only in {args.env} ({len(extra)}; fine, listed for awareness):")
        for name in extra:
            print(f"  {name}")
    if not missing:
        print("ok: every example name is present")
    return 1 if (problems or (missing and args.strict)) else 0


if __name__ == "__main__":
    raise SystemExit(main())
