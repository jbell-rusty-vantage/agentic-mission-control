"""The byte-order digest release never rewrites the previously built 1.15.0 release."""

import hashlib
import json
from pathlib import Path


def test_1160_retains_exact_1150_prefix() -> None:
    root = Path(__file__).resolve().parents[3]
    releases = root / "packages/mission-control-db-contract/releases"
    old = releases / "1.15.0/component/migrations"
    new = releases / "1.16.0/component/migrations"
    added = "0075_capability_search_byte_order_digest.sql"
    assert sorted(path.name for path in new.iterdir()) == sorted(
        path.name for path in old.iterdir()
    ) + [added]
    for path in old.iterdir():
        assert (new / path.name).read_bytes() == path.read_bytes()
    authored = (root / "scripts/release_1160" / added).read_bytes()
    assert (new / added).read_bytes() == authored
    assert b"\r" not in authored


def test_1160_manifest_pins_its_inputs_and_accepts_the_1150_schema() -> None:
    component = Path(__file__).resolve().parents[1] / "releases/1.16.0/component"
    manifest = json.loads((component / "manifest.json").read_bytes())
    assert manifest["component_version"] == "1.16.0"
    assert manifest["schema_fingerprint"] == (
        "sha256:5a4d6983a3b8f0ec702bc1a17e3b5d2054b4b0f64cdce4b358156067b6ed66d5"
    )
    for item in manifest["ordered_migrations"]:
        assert hashlib.sha256((component / item["path"]).read_bytes()).hexdigest() == item["sha256"]
    assert manifest["ordered_migrations"][-1]["key"] == "0075_capability_search_byte_order_digest"
    previous = json.loads((component.parents[1] / "1.15.0/component/manifest.json").read_bytes())[
        "schema_fingerprint"
    ]
    assert previous in manifest["compatible_previous_fingerprints"]
