"""The installed Biotech version stays usable when the development component moves."""

import hashlib
import json
from pathlib import Path

from mission_control_db_contract.integrity import load_release, resolve_release_root

ROOT = Path(__file__).resolve().parents[3]


def test_biotech_default_release_resolves_to_immutable_applied_payload():
    lock_path = ROOT / "deployments/biotech/release.lock.json"
    root = resolve_release_root(lock_path, None)
    release = load_release(lock_path, root)
    assert root == ROOT / "packages/mission-control-db-contract/releases/1.3.0/component"
    assert release.manifest["component_version"] == "1.3.0"
    assert len(release.migrations) == 28
    assert release.manifest_digest == (
        "sha256:5bdb7563eb6b6b7182bad9bbbc99ea0d66c36cf638d2d5320f04f58610e08810"
    )
    assert release.lock["release_uri"] == "mission-control:" + release.lock["release_root"]
    lock = json.loads(lock_path.read_bytes())
    actual = {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }
    assert len(actual) == 32
    assert actual == lock["files"]


def test_ai_engineer_pin_remains_a_separate_current_release():
    lock_path = ROOT / "deployments/ai-engineer/release.lock.json"
    release = load_release(lock_path, resolve_release_root(lock_path, None))
    assert release.manifest["component_version"] == "1.4.2"
    assert len(release.migrations) == 37
