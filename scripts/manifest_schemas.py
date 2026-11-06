#!/usr/bin/env python3
"""Write or verify the public Mission Manifest JSON Schemas under ``contracts/schemas/``.

``mc.mission_manifest.v1.json`` and ``mc.mission_manifest.v2.json`` are generated from the
Pydantic manifest models (``manifest_json_schema_text``/``manifest_v2_json_schema_text``);
they are never edited by hand. Keys are sorted and line endings are LF, so two runs produce
byte-identical files and ``--check`` after ``--write`` reports nothing.

Usage:
  python scripts/manifest_schemas.py --check   # exit 1 when a committed schema drifted
  python scripts/manifest_schemas.py --write   # regenerate the committed schemas
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

from mission_control.domain.authoring.manifest import (
    MANIFEST_SCHEMA_FILENAME,
    manifest_json_schema_text,
)
from mission_control.domain.authoring.manifest_v2 import (
    MANIFEST_V2_SCHEMA_FILENAME,
    manifest_v2_json_schema_text,
)

SCHEMAS = Path(__file__).resolve().parents[1] / "src/mission_control/contracts/schemas"
GENERATORS: dict[str, Callable[[], str]] = {
    MANIFEST_SCHEMA_FILENAME: manifest_json_schema_text,
    MANIFEST_V2_SCHEMA_FILENAME: manifest_v2_json_schema_text,
}


def drifted(directory: Path) -> list[str]:
    stale = []
    for name, generate in GENERATORS.items():
        path = directory / name
        # A checkout may convert line endings; the content is what must match.
        if not path.is_file() or path.read_text(encoding="utf-8") != generate():
            stale.append(name)
    return stale


def write(directory: Path) -> list[str]:
    directory.mkdir(parents=True, exist_ok=True)
    for name, generate in GENERATORS.items():
        (directory / name).write_bytes(generate().encode("utf-8"))
    return list(GENERATORS)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="fail when a schema drifted")
    mode.add_argument("--write", action="store_true", help="regenerate the schemas")
    parser.add_argument("--dir", type=Path, default=SCHEMAS, help="schema directory")
    args = parser.parse_args(argv)
    if args.write:
        for name in write(args.dir):
            sys.stdout.write(f"wrote {args.dir / name}\n")
        return 0
    stale = drifted(args.dir)
    for name in stale:
        sys.stderr.write(f"{args.dir / name} differs from the generated schema\n")
    return 1 if stale else 0


if __name__ == "__main__":
    raise SystemExit(main())
