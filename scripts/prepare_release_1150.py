"""Prepare additive 1.15.0 (Deep Agents steer-with-context describe, 0074) from the built 1.14.0.

Owner 2026-11-06 (steer with context): Deep Agents declares `interrupt_and_inject:
cooperative_inject` (`adapters/deep_agents/steering.py`). `mission_control.lane_profile` holds
the describe each profile persisted through release 1.14.0 (0073 was the last refresh); this
release revises exactly the profiles whose declared describe moved, each UPDATE guarded by the
exact prior literal (`lane_describe_refresh.render_successor_section`, the 0042/0046/0073
pattern), so a drifted row refuses instead of being overwritten; Deep Agents stays qualified.

    uv run --no-sync python scripts/prepare_release_1150.py --render   # (re)write 0074 only
    uv run --no-sync python scripts/prepare_release_1150.py            # 0074 + releases/1.15.0

The rendered migration lives in `scripts/release_1150/`; the release tree is the byte-identical
1.14.0 prefix (0001..0073) plus 0074. Build it with
`mission-db release-build --component-root <releases/1.15.0/component> --admin-dsn-env
MCDB_RELEASE_ADMIN_DSN` on a disposable PostgreSQL 17 (never a live target).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages/mission-control-db-contract"
BASE = PACKAGE / "releases/1.14.0"
CANONICAL = PACKAGE / "releases/1.15.0"
VERSION = "1.15.0"
MIGRATION = "0074_deep_agents_cooperative_inject_describe.sql"
SOURCES = ROOT / "scripts/release_1150"
LABEL = "release 1.15.0: Deep Agents steer with context (cooperative_inject)"
# The complete predecessor prefix through the 1.14.0 cross-provider lane describes.
PREFIX_LAST = "0073_cross_provider_lane_describes.sql"
QUALIFIED_PROFILES = ("deep_agents",)


def generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "lane_describe_refresh", PACKAGE / "scripts/lane_describe_refresh.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def changed_profiles(gen: ModuleType) -> tuple[dict, dict, tuple[str, ...]]:
    """Declared and persisted documents, and the profiles whose declared describe moved."""

    declared = gen.declared_documents()
    prior = gen.persisted_documents(BASE / "component/migrations")
    moved = tuple(profile for profile in declared if declared[profile] != prior.get(profile))
    return declared, prior, moved


def render() -> Path:
    gen = generator()
    declared, prior, moved = changed_profiles(gen)
    if not moved:
        raise SystemExit("no lane describe moved since 1.14.0; nothing to render")
    sql = gen.render_successor_section(
        label=LABEL,
        documents=declared,
        prior=prior,
        profiles=moved,
        qualified_profiles=tuple(p for p in QUALIFIED_PROFILES if p in moved),
    )
    SOURCES.mkdir(parents=True, exist_ok=True)
    target = SOURCES / MIGRATION
    target.write_text(sql, encoding="utf-8", newline="\n")
    print(json.dumps({"migration": str(target), "profiles": list(moved)}))
    return target


def frozen_inputs() -> tuple[dict, dict]:
    """Verify the built 1.14.0 inputs against its manifest before copying them."""

    component = BASE / "component"
    manifest = json.loads((component / "manifest.json").read_bytes())
    if manifest["component_version"] != "1.14.0":
        raise ValueError("the base release is not the built 1.14.0")
    expected = {item["path"]: item["sha256"] for item in manifest["ordered_migrations"]}
    actual = {}
    for path in (component / "migrations").iterdir():
        if path.is_symlink() or path.is_junction() or not path.is_file():
            raise ValueError("frozen migrations must be regular files")
        actual[path.relative_to(component).as_posix()] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
    if actual != expected:
        raise ValueError("frozen migration set or bytes differ from release 1.14.0")
    if max(expected) != f"migrations/{PREFIX_LAST}":
        raise ValueError("release 1.14.0 is not the complete prefix through 0073")
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
        raise ValueError("only releases/1.15.0 is an allowed destination inside the package")
    if destination.exists():
        raise FileExistsError(destination)
    manifest, spec = frozen_inputs()
    source = (SOURCES / MIGRATION).read_bytes().decode("utf-8")
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
    (component / "migrations" / MIGRATION).write_text(source, encoding="utf-8", newline="\n")
    return component


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=CANONICAL)
    parser.add_argument("--render", action="store_true", help="render 0074 only")
    args = parser.parse_args()
    render()
    if args.render:
        return
    print(json.dumps({"component_root": str(prepare(args.out)), "state": "unbuilt"}))


if __name__ == "__main__":
    main()
