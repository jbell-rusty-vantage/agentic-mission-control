from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.fixtures.qualia_recovery import retained_runtime


def _retained(root: Path) -> dict:
    (root / "temporal.sqlite").touch()
    (root / "payloads").mkdir()
    return {
        "schema": "qualia-local-runtime-recovery.v1",
        "root": str(root),
        "temporal_database": str(root / "temporal.sqlite"),
        "checkpoint_dsn": "postgresql://saver:local@127.0.0.1:55434/mct_abc123",
        "database": {
            "name": "mct_abc123",
            "application_id": "biotech",
            "installation_id": "0192a4f0-0000-7000-8000-00000000b10e",
            "project_ref": "mcdisposablebiotech",
            "owner_dsn": "postgresql://owner:local@127.0.0.1:55434/mct_abc123",
            "role_dsns": {
                "mission_control_runtime": "postgresql://runtime:local@127.0.0.1:55434/mct_abc123"
            },
            "login_roles": {"mission_control_runtime": "mct_abc123_runtime"},
            "tenants": {},
        },
    }


def _write(root: Path, document: dict) -> None:
    (root / "runtime-recovery.private.json").write_text(json.dumps(document), encoding="utf-8")


def test_retained_custody_does_not_reconstruct_missing_runtime(tmp_path: Path) -> None:
    document = _retained(tmp_path)
    _write(tmp_path, document)
    database, checkpoint = retained_runtime(tmp_path)
    assert database.name == "mct_abc123" and checkpoint == document["checkpoint_dsn"]
    (tmp_path / "temporal.sqlite").unlink()
    with pytest.raises(FileNotFoundError):
        retained_runtime(tmp_path)


@pytest.mark.parametrize(
    "mismatch",
    [
        "remote",
        "other_database",
        "other_port",
        "other_host",
        "other_root",
        "other_temporal",
        "application",
    ],
)
def test_retained_runtime_refuses_mixed_or_external_targets(tmp_path: Path, mismatch: str) -> None:
    document = _retained(tmp_path)
    if mismatch == "remote":
        document["checkpoint_dsn"] = document["checkpoint_dsn"].replace("127.0.0.1", "example.com")
    elif mismatch == "other_database":
        document["checkpoint_dsn"] = document["checkpoint_dsn"].replace("mct_abc123", "mct_other")
    elif mismatch == "other_port":
        document["checkpoint_dsn"] = document["checkpoint_dsn"].replace("55434", "5432")
    elif mismatch == "other_host":
        document["checkpoint_dsn"] = document["checkpoint_dsn"].replace("127.0.0.1", "[::1]")
    elif mismatch == "other_root":
        document["root"] = str(tmp_path.parent)
    elif mismatch == "other_temporal":
        document["temporal_database"] = str(tmp_path.parent / "temporal.sqlite")
    else:
        document["database"]["application_id"] = "ai-engineer"
    _write(tmp_path, document)
    with pytest.raises(ValueError):
        retained_runtime(tmp_path)


def test_retained_fork_uses_original_authored_pair_without_regeneration(tmp_path):
    from tests.fixtures.qualia_recovery import retained_fork_manifests

    source, target = "exact-original-source", "exact-original-target"
    (tmp_path / "01-authored-mission.yml").write_text(source, encoding="utf-8")
    fork = tmp_path / "tavily-fork"
    fork.mkdir()
    (fork / "01-prepared-manifest.json").write_text(
        json.dumps({"manifest_yaml": target}), encoding="utf-8"
    )
    assert retained_fork_manifests(tmp_path) == (source, target)
    (fork / "01-prepared-manifest.json").unlink()
    with pytest.raises(FileNotFoundError):
        retained_fork_manifests(tmp_path)
