"""Prepare additive 1.13.0 (nested activations, native plan decisions) from the built 1.12.0."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages/mission-control-db-contract"
BASE = PACKAGE / "releases/1.12.0"
CANONICAL = PACKAGE / "releases/1.13.0"
VERSION = "1.13.0"
# Authored as the "2.0.0 candidate"; additive, so they ship as a minor (W1 D31, 2026-11-02):
# OVE-176 WI-13 nested activations and the W1 native-write plan decision columns.
MIGRATIONS = (
    ("scripts/release_1130", "0071_nested_program_activations.sql"),
    ("scripts/release_1130", "0072_native_plan_decisions.sql"),
)
# The complete predecessor prefix through the 1.12.0 Workspace Closures.
PREFIX_LAST = "0070_workspace_closure.sql"


def frozen_inputs() -> tuple[dict, dict]:
    """Verify the built 1.12.0 inputs against its manifest before copying them."""

    component = BASE / "component"
    manifest = json.loads((component / "manifest.json").read_bytes())
    if manifest["component_version"] != "1.12.0":
        raise ValueError("the base release is not the built 1.12.0")
    expected = {item["path"]: item["sha256"] for item in manifest["ordered_migrations"]}
    actual = {}
    for path in (component / "migrations").iterdir():
        if path.is_symlink() or path.is_junction() or not path.is_file():
            raise ValueError("frozen migrations must be regular files")
        actual[path.relative_to(component).as_posix()] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
    if actual != expected:
        raise ValueError("frozen migration set or bytes differ from release 1.12.0")
    if max(expected) != f"migrations/{PREFIX_LAST}":
        raise ValueError("release 1.12.0 is not the complete prefix through 0070")
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
        raise ValueError("only releases/1.13.0 is an allowed destination inside the package")
    if destination.exists():
        raise FileExistsError(destination)
    manifest, spec = frozen_inputs()
    sources = {
        name: (ROOT / directory / name).read_bytes().decode("utf-8")
        for directory, name in MIGRATIONS
    }
    component = destination / "component"
    shutil.copytree(BASE / "component/migrations", component / "migrations")
    shutil.copytree(BASE / "runtime", destination / "runtime")
    spec["component_version"] = VERSION
    fingerprint = manifest["schema_fingerprint"]
    if fingerprint not in spec["compatible_previous_fingerprints"]:
        spec["compatible_previous_fingerprints"].append(fingerprint)
    (component / "release-spec.json").write_text(
        json.dumps(spec, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    for name, sql in sources.items():
        (component / "migrations" / name).write_text(sql, encoding="utf-8", newline="\n")
    return component


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=CANONICAL)
    args = parser.parse_args()
    print(json.dumps({"component_root": str(prepare(args.out)), "state": "unbuilt"}))


if __name__ == "__main__":
    main()
