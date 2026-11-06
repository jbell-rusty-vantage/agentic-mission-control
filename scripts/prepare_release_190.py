"""Prepare the additive component release 1.9.0; build it with `mission-db release-build`.

1.9.0 (Sprint OC W1 / OVE-169) is the byte-identical built 1.8.0 prefix (0001..0064, verified
against the 1.8.0 manifest; 1.8.0 is installed on both Sprint OC remotes and is never rebuilt)
plus two authored migrations:

- `0066_collection_member_assessments.sql` (`scripts/release_190/`, Sprint OC WI-07 / OVE-170;
  OUTPUT-CONTRACTS §§2, 4, 8, ADR-0058): the output-assessment subject guard also admits a
  `member` subject that a collection revision lists in `candidate.members` (function body only).
- `0067_knowledge_handle_trusted_operations.sql` (`scripts/release_190/`, W1 defect D22): the
  `knowledge_operation_handle` operation check becomes the exact set of operations Mission
  Control records a handle for, adding the trusted assessment operations (report.observe,
  report.seal, report.decide, report.review, decision.resolve) to the 1.6.0 six.

Key 0065 is unused. The installer requires unique, sorted migration keys and an ordered receipt
prefix, not contiguous numbers (the released prefix already skips 0006..0009, 0018, 0019, 0039 and
0062), so no placeholder migration is written.

Minor, not patch: a guard that admits more subjects and a check that admits more operations;
existing rows keep their meaning and the reader/writer protocol stays `mission-control-runtime/1`.
The destination is a fresh directory (the canonical one is `releases/1.9.0`); nothing in 1.8.0 or
earlier is rewritten and no manifest is produced here. Build afterwards:

    .venv/Scripts/mission-db.exe release-build \
        --component-root packages/mission-control-db-contract/releases/1.9.0/component \
        --admin-dsn-env MCDB_RELEASE_ADMIN_DSN
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages/mission-control-db-contract"
BASE = PACKAGE / "releases/1.8.0"
CANONICAL = PACKAGE / "releases/1.9.0"
VERSION = "1.9.0"
# (authoring directory, migration file); keys stay sorted and unique, 0065 is unused.
MIGRATIONS = (
    ("scripts/release_190", "0066_collection_member_assessments.sql"),
    ("scripts/release_190", "0067_knowledge_handle_trusted_operations.sql"),
)
# The complete predecessor prefix through the Sprint OC 1.8.0 search extension privileges.
PREFIX_LAST = "0064_search_extension_privileges.sql"


def frozen_inputs() -> tuple[dict, dict]:
    """Verify the built 1.8.0 inputs against its manifest before copying them."""

    component = BASE / "component"
    manifest = json.loads((component / "manifest.json").read_bytes())
    if manifest["component_version"] != "1.8.0":
        raise ValueError("the base release is not the built 1.8.0")
    expected = {item["path"]: item["sha256"] for item in manifest["ordered_migrations"]}
    actual = {}
    for path in (component / "migrations").iterdir():
        if path.is_symlink() or path.is_junction() or not path.is_file():
            raise ValueError("frozen migrations must be regular files")
        actual[path.relative_to(component).as_posix()] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
    if actual != expected:
        raise ValueError("frozen migration set or bytes differ from release 1.8.0")
    if max(expected) != f"migrations/{PREFIX_LAST}" or not all(
        any(path.startswith(f"migrations/{number:04d}_") for path in expected)
        for number in (*range(42, 62), 63, 64)
    ):
        raise ValueError("release 1.8.0 is not the complete prefix through 0064")
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
        raise ValueError("only releases/1.9.0 is an allowed destination inside the package")
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
