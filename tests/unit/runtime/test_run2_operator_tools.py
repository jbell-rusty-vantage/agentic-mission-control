"""Run 2 operator helpers preserve grants, old files and declared identity semantics."""

import json
from pathlib import Path

import pytest

from mission_control.adapters.auth.jwt import MissionTokenVerifier
from mission_control.adapters.auth.operator_token import mint_operator_token
from mission_control.bootstrap import preflight
from mission_control.bootstrap.binding_summary import binding_summary
from mission_control.interfaces.cli.main import main
from tests.unit.mission_control.test_authentication import NOW
from tests.unit.mission_control.test_authentication import (
    authenticated_world as authenticated_world,
)
from tests.unit.runtime.test_mp22_local_readiness import (
    BINDINGS_EXAMPLE,
    owner_selections,
    profile,
)


def test_optional_deployment_dir_preserves_existing_profile_dump():
    original = profile()
    assert "deployment_dir" not in original.model_dump(mode="json")
    assert (
        profile(deployment_dir=".scratch/local-install").deployment_dir == ".scratch/local-install"
    )


def test_identity_summary_does_not_change_binding_or_claim_discovery():
    bindings = preflight.compose_launch_bindings(
        json.loads(BINDINGS_EXAMPLE.read_text()), owner_selections()
    )
    before = bindings.model_dump_json()
    first = binding_summary(bindings)
    assert first == binding_summary(bindings)
    assert first["qualification"] == "unverified"
    assert first["launch_configuration_digest"].startswith("sha256:")
    assert bindings.model_dump_json() == before


def test_provider_summary_keeps_requested_and_observed_identity_separate():
    from tests.unit.authoring.test_manifest_v2_launch import bindings

    source = bindings()
    before = source.model_dump_json()
    summary = binding_summary(source)
    assert {lane["lane"] for lane in summary["lanes"]} >= {"claude_agent_sdk", "codex"}
    for lane in summary["lanes"]:
        assert lane["pins"]
        assert lane["describe_digest"].startswith("sha256:")
        assert lane["prerequisite_freshness"] == "unverified"
        assert all(model["provider_reported_model_id"] is None for model in lane["models"])
    assert source.model_dump_json() == before


async def test_unresolved_compose_preserves_existing_output(tmp_path, monkeypatch, capsys):
    selections = tmp_path / "selections.json"
    selections.write_text("{}")
    output = tmp_path / "binding.json"
    output.write_text("preserved")
    assert (
        await preflight.main(
            [
                "compose-bindings",
                "--base",
                str(BINDINGS_EXAMPLE),
                "--selections",
                str(selections),
                "--out",
                str(output),
            ]
        )
        == 2
    )
    assert output.read_text() == "preserved"


def mint(world, tmp_path: Path, **overrides):
    key, config, claims, _ = world
    private = tmp_path / "private.json"
    private.write_text(json.dumps(key.as_dict(private=True)))
    args = {
        "configuration": config,
        "private_key_file": private,
        "key_id": "test-key",
        "subject": claims["sub"],
        "tenant_id": next(iter(config.grants[0].tenant_ids)),
        "scopes": frozenset({"workflow_run.read"}),
        "now": NOW,
    }
    args.update(overrides)
    return mint_operator_token(**args)


def test_minted_token_round_trips_and_cannot_widen_grants(authenticated_world, tmp_path):
    token = mint(authenticated_world, tmp_path)
    config = authenticated_world[1]
    verified = MissionTokenVerifier((config,), clock=lambda: NOW).authenticate("biotech", token)
    assert verified.actor.permissions == {"workflow_run.read"}
    with pytest.raises(ValueError, match="not granted"):
        mint(authenticated_world, tmp_path, scopes=frozenset({"workflow_run.cancel"}))
    with pytest.raises(ValueError, match="expiry"):
        mint(authenticated_world, tmp_path, expires_in=3601)


def test_token_cli_errors_never_echo_key_material(tmp_path, capsys):
    secret = "PRIVATE-KEY-SENTINEL"
    config = tmp_path / "bad.json"
    config.write_text(secret)
    assert (
        main(
            [
                "token",
                "mint",
                "--auth-config",
                str(config),
                "--private-key-file",
                str(config),
                "--key-id",
                "test",
                "--subject",
                "test",
                "--tenant",
                "00000000-0000-0000-0000-000000000001",
                "--scope",
                "mission.read",
                "--out",
                str(tmp_path / "token"),
            ]
        )
        == 2
    )
    assert secret not in capsys.readouterr().out


def test_signed_scope_attenuates_existing_operator_grants(authenticated_world):
    from tests.unit.mission_control.test_authentication import token

    key, _, claims, verifier = authenticated_world
    claims["mc_scope"] = "workflow_run.cancel"
    assert not verifier.authenticate("biotech", token(key, claims)).actor.permissions
