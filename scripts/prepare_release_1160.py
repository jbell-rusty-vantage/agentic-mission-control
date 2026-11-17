"""Prepare additive 1.16.0 (byte-order capability search digest, 0075) from the built 1.15.0.

MC-F (2026-11-16): `mission_control_search.activate_generation` sorted the text keys of its
source-set digest under the database's default collation, while the application computes the
expected digest in codepoint (byte) order. On a locale database (`en_US.utf8`: the compose
PostgreSQL, CI, Supabase) the two disagree once the seeded ids include
`mcp.github.tool.list-issue-fields` / `list-issues` / `list-issue-types`, and no rebuild can
activate. 0075 replaces the function body with `COLLATE "C"` on every text sort key.

    uv run --no-sync python scripts/prepare_release_1160.py   # releases/1.16.0 (unbuilt)

The authored migration lives in `scripts/release_1160/`; the release tree is the byte-identical
1.15.0 prefix (0001..0074) plus 0075. Build it with
`mission-db release-build --component-root <releases/1.16.0/component> --admin-dsn-env
MCDB_RELEASE_ADMIN_DSN` on a disposable PostgreSQL 17 (never a live target).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages/mission-control-db-contract"
BASE = PACKAGE / "releases/1.15.0"
CANONICAL = PACKAGE / "releases/1.16.0"
BASE_VERSION = "1.15.0"
VERSION = "1.16.0"
MIGRATION = "0075_capability_search_byte_order_digest.sql"
SOURCES = ROOT / "scripts/release_1160"
# The complete predecessor prefix through the 1.15.0 Deep Agents describe.
PREFIX_LAST = "0074_deep_agents_cooperative_inject_describe.sql"


def frozen_inputs() -> tuple[dict, dict]:
    """Verify the built 1.15.0 inputs against its manifest before copying them."""

    component = BASE / "component"
    manifest = json.loads((component / "manifest.json").read_bytes())
    if manifest["component_version"] != BASE_VERSION:
        raise ValueError("the base release is not the built 1.15.0")
    expected = {item["path"]: item["sha256"] for item in manifest["ordered_migrations"]}
    actual = {}
    for path in (component / "migrations").iterdir():
        if path.is_symlink() or path.is_junction() or not path.is_file():
            raise ValueError("frozen migrations must be regular files")
        actual[path.relative_to(component).as_posix()] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
    if actual != expected:
        raise ValueError("frozen migration set or bytes differ from release 1.15.0")
    if max(expected) != f"migrations/{PREFIX_LAST}":
        raise ValueError("release 1.15.0 is not the complete prefix through 0074")
    spec = json.loads((component / "release-spec.json").read_bytes())
    descriptor = manifest["runtime_descriptor"]
    descriptor_path = component / descriptor["path"]
    if hashlib.sha256(descriptor_path.read_bytes()).hexdigest() != descriptor["sha256"]:
        raise ValueError("frozen runtime descriptor bytes differ")
    return manifest, spec


def prepare(destination: Path) -> Path:
    destination = destination.resolve()
    package = PACKAGE.resolve()
    if (
        destination == package or package in destination.parents
    ) and destination != CANONICAL.resolve():
        raise ValueError("only releases/1.16.0 is an allowed destination inside the package")
    if destination.exists():
        raise FileExistsError(destination)
    source = (SOURCES / MIGRATION).read_bytes()
    if b"\r" in source:
        raise ValueError("the authored migration must use LF line endings")
    manifest, spec = frozen_inputs()
    component = destination / "component"
    shutil.copytree(BASE / "component/migrations", component / "migrations")
    shutil.copytree(BASE / "runtime", destination / "runtime")
    spec["component_version"] = VERSION
    fingerprint = manifest["schema_fingerprint"]
    if fingerprint not in spec["compatible_previous_fingerprints"]:
        spec["compatible_previous_fingerprints"].append(fingerprint)
    (component / "release-spec.json").write_bytes(
        (json.dumps(spec, indent=2) + "\n").encode("utf-8")
    )
    (component / "migrations" / MIGRATION).write_bytes(source)
    return component


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--out", type=Path, default=CANONICAL)
    args = parser.parse_args()
    print(json.dumps({"component_root": str(prepare(args.out)), "state": "unbuilt"}))


if __name__ == "__main__":
    main()
