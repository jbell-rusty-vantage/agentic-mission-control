"""Prepare the additive component release 1.5.0; build it with `mission-db release-build`.

1.5.0 (Sprint V SV-13, design M05; findings E10/D0) is the first release authored from the
complete built 1.4.4 prefix (0001..0049, verified against the 1.4.4 manifest), never from the
frozen 1.4.0 root `component/` that ends at 0041. It adds the five knowledge-boundary
migrations authored in `scripts/release_150/`:

- `0050_knowledge_operations.sql`: `knowledge_operation_journal` (prepared -> dispatched ->
  applied | noop | partial | rejected | uncertain, scoped effect key, EFFECT_CONFLICT) and its
  append-only `knowledge_operation_transition`, plus `admit_knowledge_operation(jsonb)`.
- `0051_content_lineage.sql`: append-only `content_lineage` in the seven provenance roles.
- `0052_source_bindings_retained_observations.sql`: `context_source_binding` and
  `retained_read_observation`.
- `0053_submissions.sql`: `output_submission` (`submit_output`) and `invocation_finalization`.
- `0054_transfer_plans_delivery_receipts.sql`: `context_transfer_plan`,
  `context_delivery_receipt` and `context_delivery_outbox`.

Minor, not patch: the five migrations only add objects (no existing table, constraint, grant
or describe changes; reader/writer protocol stays `mission-control-runtime/1`), so every
1.4.x reader keeps working; but they add a new capability family a runtime will require,
and `>=1.5.0` names that floor. No lane-describe migration. The destination is a fresh
directory (the canonical one is `releases/1.5.0`); nothing in 1.4.4 or earlier is rewritten
and no manifest is produced here. Build afterwards:

    .venv/Scripts/mission-db.exe release-build \\
        --component-root packages/mission-control-db-contract/releases/1.5.0/component \\
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
BASE = PACKAGE / "releases/1.4.4"
CANONICAL = PACKAGE / "releases/1.5.0"
VERSION = "1.5.0"
MIGRATIONS = (
    "0050_knowledge_operations.sql",
    "0051_content_lineage.sql",
    "0052_source_bindings_retained_observations.sql",
    "0053_submissions.sql",
    "0054_transfer_plans_delivery_receipts.sql",
)
# The complete predecessor prefix: E10 forbids a source that drops 0042..0049.
PREFIX_LAST = "0049_frame_body_refs.sql"


def frozen_inputs() -> tuple[dict, dict]:
    """Verify the built 1.4.4 inputs against its manifest before copying them."""

    component = BASE / "component"
    manifest = json.loads((component / "manifest.json").read_bytes())
    if manifest["component_version"] != "1.4.4":
        raise ValueError("the base release is not the built 1.4.4")
    expected = {item["path"]: item["sha256"] for item in manifest["ordered_migrations"]}
    actual = {}
    for path in (component / "migrations").iterdir():
        if path.is_symlink() or path.is_junction() or not path.is_file():
            raise ValueError("frozen migrations must be regular files")
        actual[path.relative_to(component).as_posix()] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
    if actual != expected:
        raise ValueError("frozen migration set or bytes differ from release 1.4.4")
    if max(expected) != f"migrations/{PREFIX_LAST}" or not all(
        any(path.startswith(f"migrations/{number:04d}_") for path in expected)
        for number in range(42, 50)
    ):
        raise ValueError("release 1.4.4 is not the complete prefix through 0049")
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
        raise ValueError("only releases/1.5.0 is an allowed destination inside the package")
    if destination.exists():
        raise FileExistsError(destination)
    manifest, spec = frozen_inputs()
    sources = {
        name: (ROOT / "scripts/release_150" / name).read_bytes().decode("utf-8")
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
