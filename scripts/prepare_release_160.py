"""Prepare the additive component release 1.6.0; build it with `mission-db release-build`.

1.6.0 (Sprint V SV-16, SV-15 reopened; Checkpoint A schema-fit rows for 0050, 0053 and 0054)
is the byte-identical built 1.5.0 prefix (0001..0054, verified against the 1.5.0 manifest)
plus one migration authored in `scripts/release_160/`:

- `0055_knowledge_handles_assessment_delivery_attempts.sql`: the durable
  `knowledge_operation_handle` (K01 status, monotonic remote revision, first cancel request
  id, pending review, result, unresolved effects) and `knowledge_operation_state_reachable`;
  the independent assessment handoff on `output_submission` (`assessing`,
  `assessment_operation_id`, `assessment_binding`, `assessment_requested_at`);
  `invocation_finalization.outcome_basis`; `context_delivery_receipt.attempt` and the
  generated `outcome_code`, with the receipt-attempt guard and the plan readiness guard
  (`delivering -> delivered` only on verified receipts for every required item, `blocked`
  only after a failed repair).

Minor, not patch: a new table and new columns, plus guard changes that only refuse states
1.5.0 could not represent (`assessing`, attempt 2); existing rows keep their meaning
(`outcome_basis` defaults to `submission_coverage`, receipts are attempt 1) and the reader/
writer protocol stays `mission-control-runtime/1`. The runtime's knowledge gateway, assessment
handoff and delivery require it, so `>=1.6.0` names that floor. The destination is a fresh
directory (the canonical one is `releases/1.6.0`); nothing in 1.5.0 or earlier is rewritten
and no manifest is produced here. Build afterwards:

    .venv/Scripts/mission-db.exe release-build \
        --component-root packages/mission-control-db-contract/releases/1.6.0/component \
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
BASE = PACKAGE / "releases/1.5.0"
CANONICAL = PACKAGE / "releases/1.6.0"
VERSION = "1.6.0"
MIGRATIONS = ("0055_knowledge_handles_assessment_delivery_attempts.sql",)
# The complete predecessor prefix through the Sprint V 1.5.0 knowledge-boundary records.
PREFIX_LAST = "0054_transfer_plans_delivery_receipts.sql"


def frozen_inputs() -> tuple[dict, dict]:
    """Verify the built 1.5.0 inputs against its manifest before copying them."""

    component = BASE / "component"
    manifest = json.loads((component / "manifest.json").read_bytes())
    if manifest["component_version"] != "1.5.0":
        raise ValueError("the base release is not the built 1.5.0")
    expected = {item["path"]: item["sha256"] for item in manifest["ordered_migrations"]}
    actual = {}
    for path in (component / "migrations").iterdir():
        if path.is_symlink() or path.is_junction() or not path.is_file():
            raise ValueError("frozen migrations must be regular files")
        actual[path.relative_to(component).as_posix()] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
    if actual != expected:
        raise ValueError("frozen migration set or bytes differ from release 1.5.0")
    if max(expected) != f"migrations/{PREFIX_LAST}" or not all(
        any(path.startswith(f"migrations/{number:04d}_") for path in expected)
        for number in range(42, 55)
    ):
        raise ValueError("release 1.5.0 is not the complete prefix through 0054")
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
        raise ValueError("only releases/1.6.0 is an allowed destination inside the package")
    if destination.exists():
        raise FileExistsError(destination)
    manifest, spec = frozen_inputs()
    sources = {
        name: (ROOT / "scripts/release_160" / name).read_bytes().decode("utf-8")
        for name in MIGRATIONS
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
