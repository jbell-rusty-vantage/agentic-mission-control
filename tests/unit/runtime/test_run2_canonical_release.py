"""The canonical successor is additive, reproducible and preserves frozen history."""

import hashlib
import json
import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "packages/mission-control-db-contract"
SUCCESSOR = PACKAGE / "releases/1.4.1/component"
PREPARER = runpy.run_path(str(ROOT / "scripts/prepare_run2_release.py"))


def test_canonical_successor_reproduces_inputs_and_preserves_frozen_history(tmp_path):
    prepared = PREPARER["prepare"](tmp_path / "successor")
    base = PACKAGE / "component"
    manifest = json.loads((base / "manifest.json").read_bytes())
    for item in manifest["ordered_migrations"]:
        payload = (base / item["path"]).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == item["sha256"]
        assert (SUCCESSOR / item["path"]).read_bytes() == payload
    for path in prepared.rglob("*"):
        if path.is_file():
            assert (SUCCESSOR / path.relative_to(prepared)).read_bytes() == path.read_bytes()
    assert (prepared.parent / "runtime/descriptor.json").read_bytes() == (
        SUCCESSOR.parent / "runtime/descriptor.json"
    ).read_bytes()
    spec = json.loads((SUCCESSOR / "release-spec.json").read_bytes())
    original = json.loads((base / "release-spec.json").read_bytes())
    assert spec.pop("component_version") == "1.4.1"
    original.pop("component_version")
    assert spec["compatible_previous_fingerprints"].pop() == manifest["schema_fingerprint"]
    assert spec["seed_compatibility"]["seed_keys"].pop() == "mc.catalog.artifact-schemas"
    assert spec == original
    with pytest.raises(FileExistsError):
        PREPARER["prepare"](tmp_path / "successor")


def test_successor_destination_guard_and_exact_observation_migration():
    with pytest.raises(ValueError, match="only releases/1.4.1"):
        PREPARER["prepare"](PACKAGE / "component/replacement")
    sql = (SUCCESSOR / "migrations" / PREPARER["MIGRATION"]).read_text("utf-8")
    assert sql == PREPARER["observation_sql"]()
    assert len(PREPARER["OLD_CONTRACTS"]) == 10
    assert "NO FORCE" not in sql and "DISABLE TRIGGER" not in sql


def test_built_successor_changes_only_the_runtime_document_contract_constraint():
    before = json.loads((PACKAGE / "component/generated/contract.json").read_bytes())
    after = json.loads((SUCCESSOR / "generated/contract.json").read_bytes())
    old_table = before["schemas"]["mission_control"]["tables"]["runtime_document"]
    new_table = after["schemas"]["mission_control"]["tables"]["runtime_document"]
    old_check = next(
        c for c in old_table["constraints"] if c["name"] == "runtime_document_contract_check"
    )
    new_check = next(
        c for c in new_table["constraints"] if c["name"] == "runtime_document_contract_check"
    )
    assert new_check["definition"] == old_check["definition"].replace(
        "]))", ", 'mc.cursor-cost-observation/1'::text]))"
    )
    new_check["definition"] = old_check["definition"]
    assert after.pop("component_version") == "1.4.1"
    assert before.pop("component_version") == "1.4.0"
    # Catalog output excludes row values; the Codex describe assertion lives in lane tests.
    assert after == before
