"""Prepare the additive component release 1.7.0; build it with `mission-db release-build`.

1.7.0 (Sprint OC WI-01 / OVE-163; OUTPUT-CONTRACTS §§2-4, ADR-0058) is the byte-identical
built 1.6.0 prefix (0001..0055, verified against the 1.6.0 manifest) plus the migrations
authored in `scripts/release_170/`:

- `0056_output_contracts_and_fulfillment.sql`: immutable `output_obligation_revision`
  (named promises with form, enforcement and pinned contract) and the CAS
  `output_obligation_head`; immutable `output_revision` (one exact revision per deliverable of
  a submission act) and the CAS `output_accepted_head` (expected head and generation);
  immutable `output_set` / `output_set_member` (pinned frontier, membership digest without
  assessments), `output_assessment` (exact subject digest, never self-assessed),
  `obligation_fulfillment` and `obligation_association_step`; the finalization basis gains
  `declared_obligations` and `no_declared_obligations`.
- `0057_sealed_transfer_attempts.sql` (Sprint OC WI-02 / OVE-164; §6, ADR-0061): retires the
  Sprint V M04 per-boundary `context_transfer_plan`, `context_delivery_receipt` and
  `context_delivery_outbox`; adds the one immutable sealed `transfer_plan` per receiver key and
  the append-only `transfer_delivery_receipt` (receiver attempt, generation and realized backend
  in its identity, per-plan sequence) with its `transfer_member_delivery` rows.
- `0058_saved_execution_settlement.sql` (Sprint OC WI-04 / OVE-166; §4): `invocation_settlement`,
  one saved provider result per bound operation attempt (immutable bytes and digest, written
  before any settlement wait) and its durable settlement (pending, waiting with a typed reason
  and pending review/effect refs, settled), advanced by compare-and-set under a monotonic claim
  fence by its recovery owner; a stop fence is never lifted.
- `0059_recorded_use_decisions.sql` (Sprint OC WI-03 / OVE-165; §5): `knowledge_use_decision`,
  the immutable exact KS use decisions the trusted knowledge bridge records (replacing the
  process-memory store `knowledge_apply` resolved).
- `0060_hook_candidate_installs.sql` (Sprint OC WI-17 / OVE-180; §11, ADR-0062):
  `context_candidate_install` (one claim per receiver path, attempt and generation) and its one
  install outcome, the durable exactly-once record of host-validated hook candidates.

Minor, not patch: new tables and an outcome-basis constraint that only admits new values;
existing rows keep their meaning and the reader/writer protocol stays `mission-control-runtime/1`.
The runtime's `submit_output`, promotion and fulfillment require it, so `>=1.7.0` names that
floor. The destination is a fresh directory (the canonical one is `releases/1.7.0`); nothing in
1.6.0 or earlier is rewritten and no manifest is produced here. Build afterwards:

    .venv/Scripts/mission-db.exe release-build \
        --component-root packages/mission-control-db-contract/releases/1.7.0/component \
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
BASE = PACKAGE / "releases/1.6.0"
CANONICAL = PACKAGE / "releases/1.7.0"
VERSION = "1.7.0"
MIGRATIONS = (
    "0056_output_contracts_and_fulfillment.sql",
    "0057_sealed_transfer_attempts.sql",
    "0058_saved_execution_settlement.sql",
    "0059_recorded_use_decisions.sql",
    "0060_hook_candidate_installs.sql",
)
# The complete predecessor prefix through the Sprint V 1.6.0 knowledge handles.
PREFIX_LAST = "0055_knowledge_handles_assessment_delivery_attempts.sql"


def frozen_inputs() -> tuple[dict, dict]:
    """Verify the built 1.6.0 inputs against its manifest before copying them."""

    component = BASE / "component"
    manifest = json.loads((component / "manifest.json").read_bytes())
    if manifest["component_version"] != "1.6.0":
        raise ValueError("the base release is not the built 1.6.0")
    expected = {item["path"]: item["sha256"] for item in manifest["ordered_migrations"]}
    actual = {}
    for path in (component / "migrations").iterdir():
        if path.is_symlink() or path.is_junction() or not path.is_file():
            raise ValueError("frozen migrations must be regular files")
        actual[path.relative_to(component).as_posix()] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
    if actual != expected:
        raise ValueError("frozen migration set or bytes differ from release 1.6.0")
    if max(expected) != f"migrations/{PREFIX_LAST}" or not all(
        any(path.startswith(f"migrations/{number:04d}_") for path in expected)
        for number in range(42, 56)
    ):
        raise ValueError("release 1.6.0 is not the complete prefix through 0055")
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
        raise ValueError("only releases/1.7.0 is an allowed destination inside the package")
    if destination.exists():
        raise FileExistsError(destination)
    manifest, spec = frozen_inputs()
    sources = {
        name: (ROOT / "scripts/release_170" / name).read_bytes().decode("utf-8")
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
