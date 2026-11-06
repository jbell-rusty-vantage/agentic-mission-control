"""The AI Engineer fixture's MC-owned issuer key, host config and parameterized budget driver."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from mission_control.adapters.knowledge.credentials import load_signing_key
from tests.fixtures import aieng_stagegraph as fixture

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))


def test_mc_generates_the_issuer_key_and_the_host_gets_only_its_jwks(tmp_path: Path) -> None:
    key_path, jwks_path, kid = fixture.write_issuer_key(tmp_path)
    assert load_signing_key(key_path).kid == kid
    jwks = json.loads(jwks_path.read_text(encoding="utf-8"))
    assert [key["kid"] for key in jwks["keys"]] == [kid]
    assert all("d" not in key for key in jwks["keys"])
    config = fixture.host_config(tmp_path, jwks_path)
    assert "keyPath" not in config and config["jwksPath"] == str(jwks_path)
    assert (config["issuer"], config["audience"]) == (
        "mission-control",
        "knowledge-services-executor",
    )
    assert config["origin"]["issuer"] == config["issuer"]
    assert config["migrationHead"] is None


def test_migration_head_override_reaches_the_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AIENG_FIXTURE_MIGRATION_HEAD", "20261031010000")
    _, jwks_path, _ = fixture.write_issuer_key(tmp_path)
    assert fixture.host_config(tmp_path, jwks_path)["migrationHead"] == "20261031010000"


def test_default_ledgers_keep_the_recorded_policy_and_new_roots_are_fresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fixture, "EVIDENCE", tmp_path / "default")
    models, web = fixture.ledgers(tmp_path / "default")
    assert models.limit == 24.0 and web.max_reserved_usd == 30.0 and web.max_calls == 140
    assert len(web.prior_limit_policies) == 1
    models, web = fixture.ledgers(tmp_path / "provenance", model_cap_usd=10, web_cap_usd=5)
    assert models.limit == 10 and models.path.parent == tmp_path / "provenance" / "budget"
    assert web.max_reserved_usd == 5 and web.max_calls == 25 and web.max_calls_per_tool == 25
    assert web.prior_limit_policies == ()
    with pytest.raises(ValueError):
        fixture.ledgers(tmp_path / "x", web_cap_usd=40)


def test_driver_defaults_preserve_the_usd60_packet_and_new_runs_stay_within_authority() -> None:
    import aieng_stagegraph as driver  # type: ignore[import-not-found]

    defaults = driver.parse_args(["--attempt", "a", "--authorized-budget-usd", "60"])
    assert defaults.evidence_root == fixture.EVIDENCE.resolve()
    assert (defaults.model_cap_usd, defaults.web_cap_usd) == (24.0, 30.0)
    with pytest.raises(SystemExit):
        driver.parse_args(["--attempt", "a", "--authorized-budget-usd", "15"])
    run = driver.parse_args(
        [
            "--attempt",
            "a",
            "--authorized-budget-usd",
            "15",
            "--evidence-root",
            ".scratch/provenance-2026-10-31/aieng",
            "--model-cap-usd",
            "10",
            "--web-cap-usd",
            "5",
        ]
    )
    assert run.evidence_root == (ROOT / ".scratch/provenance-2026-10-31/aieng").resolve()
    for extra in (
        ["--model-cap-usd", "11", "--web-cap-usd", "5"],
        ["--evidence-root", "elsewhere"],
    ):
        with pytest.raises(SystemExit):
            driver.parse_args(
                [
                    "--attempt",
                    "a",
                    "--authorized-budget-usd",
                    "15",
                    "--evidence-root",
                    ".scratch/p",
                    "--model-cap-usd",
                    "10",
                    "--web-cap-usd",
                    "5",
                    *extra,
                ]
            )
