"""A describe successor is reviewable without rewriting or pretending to build 1.4.0."""

import hashlib
import json
import runpy
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
CANDIDATE = runpy.run_path(str(ROOT / "scripts/prepare_codex_describe_successor.py"))


def test_candidate_copies_immutable_inputs_and_refuses_an_existing_destination(tmp_path):
    original = ROOT / "packages/mission-control-db-contract/component"
    before = (original / "manifest.json").read_bytes()
    destination = tmp_path / "candidate"
    component = CANDIDATE["prepare"](destination)
    assert not (component / "manifest.json").exists()
    assert not (component / "generated").exists()
    assert (
        json.loads((component / "release-spec.json").read_bytes())["component_version"] == "1.4.1"
    )
    for source in (original / "migrations").iterdir():
        assert (component / "migrations" / source.name).read_bytes() == source.read_bytes()
    assert (original / "manifest.json").read_bytes() == before
    assert hashlib.sha256(before).hexdigest() == CANDIDATE["BASE_MANIFEST_SHA256"]
    sql = (component / "migrations" / CANDIDATE["MIGRATION"]).read_text()
    assert "AND NOT qualified AND describe =" in sql
    assert "FORCE ROW LEVEL SECURITY;" in sql
    assert "ENABLE TRIGGER lane_profile_immutable;" in sql
    with pytest.raises(FileExistsError):
        CANDIDATE["prepare"](destination)


@pytest.mark.parametrize("change", ["migration", "extra", "descriptor", "spec"])
def test_candidate_refuses_modified_frozen_inputs_before_creating_destination(
    tmp_path, monkeypatch, change
):
    source = ROOT / "packages/mission-control-db-contract"
    package = tmp_path / "package"
    shutil.copytree(source / "component", package / "component")
    shutil.copytree(source / "runtime", package / "runtime")
    if change == "migration":
        path = package / "component/migrations/0040_implemented_lane_describes.sql"
        path.write_bytes(path.read_bytes() + b"\n-- unauthorized historic edit\n")
    elif change == "extra":
        (package / "component/migrations/0042_unreviewed.sql").write_text("SELECT 1;")
    elif change == "descriptor":
        (package / "runtime/descriptor.json").write_text("{}")
    else:
        path = package / "component/release-spec.json"
        spec = json.loads(path.read_bytes())
        spec["supported_writer_versions"] = ["unreviewed/2"]
        path.write_text(json.dumps(spec))
    monkeypatch.setitem(CANDIDATE["prepare"].__globals__, "PACKAGE", package)
    destination = tmp_path / "candidate"
    with pytest.raises(ValueError, match="frozen"):
        CANDIDATE["prepare"](destination)
    assert not destination.exists()


def test_candidate_refuses_destination_inside_frozen_package():
    destination = ROOT / "packages/mission-control-db-contract/component/new-candidate"
    with pytest.raises(ValueError, match="outside"):
        CANDIDATE["prepare"](destination)
    assert not destination.exists()
