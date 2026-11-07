from pathlib import Path
from types import SimpleNamespace

import pytest

from mission_control.adapters.codex.auth_preflight import (
    CODEX_OWNER_HOME_REQUIRED,
    owner_login_preflight,
    require_auth_home,
)
from mission_control.application.agentic_components.placement import LaneProjectionError


def test_owner_login_refuses_isolated_home() -> None:
    with pytest.raises(LaneProjectionError) as caught:
        require_auth_home("owner_cli_login", "isolated", Path("owner"))
    assert caught.value.code == CODEX_OWNER_HOME_REQUIRED
    require_auth_home("owner_cli_login", "owner", Path("owner"))
    require_auth_home("api_key", "isolated", None)


@pytest.mark.asyncio
async def test_selected_home_probe_scrubs_keys_without_reading_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mission_control.adapters.codex import auth_preflight

    def run(argv: list[str], **kwargs: object) -> SimpleNamespace:
        assert argv == ["fixture-codex", "login", "status"]
        assert kwargs["env"] == {"PATH": "bin", "CODEX_HOME": str(tmp_path)}
        return SimpleNamespace(returncode=0, stdout="", stderr="Logged in using ChatGPT")

    monkeypatch.setattr(auth_preflight.subprocess, "run", run)
    result = await owner_login_preflight(
        "fixture-codex",
        tmp_path,
        environ={
            "PATH": "bin",
            "OPENAI_API_KEY": "sentinel",
            "CODEX_API_KEY": "sentinel2",
            "CODEX_HOME": "wrong",
            "MC_BIOTECH_DB_ADMIN_DSN": "private",
        },
    )
    assert result.ready and result.home == str(tmp_path)
    assert not (tmp_path / "auth.json").exists()


@pytest.mark.asyncio
async def test_api_only_status_does_not_pass_subscription_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mission_control.adapters.codex import auth_preflight

    monkeypatch.setattr(
        auth_preflight.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout="Logged in using an API key", stderr=""
        ),
    )
    assert not (await owner_login_preflight("fixture", tmp_path, environ={})).ready
