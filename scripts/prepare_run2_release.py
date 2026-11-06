"""Prepare the complete additive Run 2 release 1.4.1; build with mission-db separately.

The earlier Codex-only candidate remains reproducible and untouched. The canonical
release is a fresh version directory alongside the frozen component/ release 1.4.0.
"""

from __future__ import annotations

import argparse
import json
import runpy
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages/mission-control-db-contract"
CANONICAL = PACKAGE / "releases/1.4.1"
MIGRATION = "0043_cursor_cost_observation_contract.sql"
OLD_CONTRACTS = (
    "goal.revision/1",
    "goal.iteration/1",
    "goal.handoff/1",
    "goal.verification/1",
    "goal.template/1",
    "stagegraph.template/1",
    "operation.binding/1",
    "operation.binding-index/1",
    "operation.settlement/1",
    "operation.claim/1",
)
NEW_CONTRACT = "mc.cursor-cost-observation/1"


def observation_sql() -> str:
    # Match the PG17 catalog representation, including order, before replacing it.
    # The installer also checks the complete predecessor fingerprint before apply.
    old = (
        "CHECK (contract = ANY (ARRAY["
        + ", ".join(f"'{name}'::text" for name in OLD_CONTRACTS)
        + "]))"
    )
    literal = old.replace("'", "''")
    values = ",\n        ".join(f"'{name}'" for name in (*OLD_CONTRACTS, NEW_CONTRACT))
    return f"""-- Release 1.4.1: append immutable Cursor cost observations to runtime_document.
-- Preserve all ten existing contracts and every other constraint, policy, trigger and grant.
DO $cursor_cost_contract$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint
        WHERE conrelid = 'mission_control.runtime_document'::regclass
          AND conname = 'runtime_document_contract_check' AND contype = 'c'
          AND convalidated
          AND pg_catalog.pg_get_constraintdef(oid, true) = '{literal}'
    ) THEN
        RAISE EXCEPTION 'runtime_document contract constraint differs from release 1.4.0'
            USING ERRCODE = 'data_exception';
    END IF;
END
$cursor_cost_contract$;
ALTER TABLE mission_control.runtime_document
    DROP CONSTRAINT runtime_document_contract_check,
    ADD CONSTRAINT runtime_document_contract_check CHECK (contract IN (
        {values}
    ));
"""


def prepare(destination: Path) -> Path:
    destination = destination.resolve()
    package = PACKAGE.resolve()
    if (
        destination == package or package in destination.parents
    ) and destination != CANONICAL.resolve():
        raise ValueError("only releases/1.4.1 is an allowed destination inside the package")
    if destination.exists():
        raise FileExistsError(destination)
    original = runpy.run_path(str(ROOT / "scripts/prepare_codex_describe_successor.py"))
    # Original preparer verifies the complete frozen manifest and all input digests.
    with tempfile.TemporaryDirectory(prefix="mc_run2_release_") as scratch:
        staged = Path(scratch) / "release"
        component = original["prepare"](staged)
        spec_path = component / "release-spec.json"
        spec = json.loads(spec_path.read_bytes())
        spec["seed_compatibility"]["seed_keys"].append("mc.catalog.artifact-schemas")
        spec_path.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8", newline="\n")
        (component / "migrations" / MIGRATION).write_text(
            observation_sql(), encoding="utf-8", newline="\n"
        )
        # copytree refuses a destination created concurrently; no existing tree is replaced.
        shutil.copytree(staged, destination)
    return destination / "component"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=CANONICAL)
    args = parser.parse_args()
    print(json.dumps({"component_root": str(prepare(args.out)), "state": "unbuilt"}))


if __name__ == "__main__":
    main()
