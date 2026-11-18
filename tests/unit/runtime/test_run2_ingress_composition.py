"""Ingress drainer composition: separate claim pool, all-or-none quarantine storage and the
slim ingress lock. The launch resolver and the webhook binding refusals run on the disposable
database in tests/integration/postgres/test_ingress_launch_resolver_postgres.py and
test_ingress_webhook_binding_postgres.py."""

import pytest

from mission_control.bootstrap.ingress_drainer import (
    compose_ingress_drainer,
)


def test_separate_pool_required():
    pool = object()
    with pytest.raises(ValueError, match="separate pool"):
        compose_ingress_drainer(
            claim_pool=pool,
            runtime_pool=pool,
            request_scope="scope",
            authentication=None,
            manifest_services={},
            manifests={},
            temporal_client=None,
        )


@pytest.mark.parametrize("present", [(), ("MC_INGRESS_STORAGE_URL",)])
def test_optional_quarantine_storage_is_all_or_none(monkeypatch, present):
    from mission_control.bootstrap.ingress import quarantine_store

    for name in (
        "MC_INGRESS_STORAGE_URL",
        "MC_INGRESS_QUARANTINE_BUCKET",
        "MC_INGRESS_STORAGE_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    for name in present:
        monkeypatch.setenv(name, "https://fixture.invalid")
    if present:
        with pytest.raises(RuntimeError, match="together"):
            quarantine_store(None)
    else:
        assert quarantine_store(None) is None


def test_slim_ingress_lock_covers_external_imports():
    import runpy
    import tomllib
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    deploy = root / "deployments" / "ingress-vercel"
    vendor = runpy.run_path(str(deploy / "scripts" / "vendor_closure.py"))
    files = vendor["closure"]()
    lock = tomllib.loads((deploy / "uv.lock").read_text())
    assert "yaml" in vendor["external_imports"](files)
    vendor["validate_external_dependencies"](files, lock)
    # Reproduce the deployed failure even though the full test environment has PyYAML.
    missing_yaml = {**lock, "package": [p for p in lock["package"] if p["name"] != "pyyaml"]}
    with pytest.raises(ValueError, match="unlocked external imports.*yaml"):
        vendor["validate_external_dependencies"](files, missing_yaml)
