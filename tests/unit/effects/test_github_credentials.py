"""MO-14 push credentials: the Mission Control GitHub App installation token restricted to
the target repository (a FIXTURE App key and an `httpx.MockTransport` GitHub), the owner `gh`
fallback that always selects jbell-rusty-vantage (a FIXTURE command runner; `gh` is never
executed) and the configuration refusals (DECISIONS R26). No token is real and no request
leaves the machine.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest
from joserfc.jwk import RSAKey

from mission_control.adapters.github.credentials import (
    APP_ID_ENV,
    APP_INSTALLATION_ID_ENV,
    APP_PRIVATE_KEY_PATH_ENV,
    INSTALLATION_PERMISSIONS,
    GitHubAppInstallationTokens,
    GitHubCredentialError,
    OwnerGhCredentials,
    github_credentials,
)
from mission_control.adapters.github.repositories import GitHubError, GitHubRepository
from tests.unit.effects.support import (
    API,
    APP_ID,
    APP_TOKEN,
    INSTALLATION_ID,
    REPOSITORY,
    FakeGitHub,
    make_remote,
)

NOW = 1_791_892_800.0  # 2026-10-13T12:00:00Z


def _app(tmp_path: Path) -> tuple[FakeGitHub, GitHubAppInstallationTokens]:
    key = RSAKey.generate_key(2048)
    github = FakeGitHub(make_remote(tmp_path), app_key=key)
    tokens = GitHubAppInstallationTokens(
        app_id=APP_ID,
        installation_id=INSTALLATION_ID,
        private_key=key.as_pem(private=True),
        http=github.client(),
        api_url=API,
        clock=lambda: NOW,
    )
    return github, tokens


async def test_the_app_token_is_restricted_to_the_target_repository(tmp_path: Path) -> None:
    github, tokens = _app(tmp_path)

    credential = await tokens.credential(REPOSITORY + ".git")

    assert credential.source == "github_app_installation"
    assert credential.username == "x-access-token"
    assert credential.secret.get_secret_value() == APP_TOKEN
    assert APP_TOKEN not in repr(credential) and APP_TOKEN not in str(credential.model_dump())
    [minted] = github.token_requests
    assert minted["body"] == {
        "repositories": ["mission-control"],
        "permissions": INSTALLATION_PERMISSIONS,
    }
    claims = minted["claims"]
    assert claims["iss"] == APP_ID
    assert claims["iat"] == NOW - 60 and claims["exp"] - claims["iat"] <= 600


async def test_the_app_token_is_cached_until_close_to_expiry(tmp_path: Path) -> None:
    github, tokens = _app(tmp_path)

    first = await tokens.credential(REPOSITORY)
    second = await tokens.credential(REPOSITORY)

    assert first == second and len(github.token_requests) == 1


async def test_a_wrong_app_or_an_unrestricted_grant_is_refused(tmp_path: Path) -> None:
    github, _ = _app(tmp_path)
    impostor = GitHubAppInstallationTokens(
        app_id="1",
        installation_id=INSTALLATION_ID,
        private_key=RSAKey.generate_key(2048).as_pem(private=True),
        http=github.client(),
        api_url=API,
        clock=lambda: NOW,
    )
    with pytest.raises(GitHubCredentialError):
        await impostor.credential(REPOSITORY)
    with pytest.raises(GitHubError):
        await impostor.credential("https://gitlab.com/jbell-rusty-vantage/mission-control")


class RecordingRunner:
    def __init__(self, returncode: int = 0, stdout: bytes = b"gho_fixture_owner_token\n") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.calls: list[tuple[tuple[str, ...], dict[str, str]]] = []

    async def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> tuple[int, bytes]:
        self.calls.append((tuple(argv), dict(env)))
        return self.returncode, self.stdout


async def test_the_gh_fallback_selects_overton77_and_ignores_ambient_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GH_TOKEN", "ambient-token")
    monkeypatch.setenv("GITHUB_TOKEN", "ambient-token")
    runner = RecordingRunner()

    credential = await OwnerGhCredentials(runner=runner).credential(REPOSITORY)

    [(argv, env)] = runner.calls
    assert argv == (
        "gh",
        "auth",
        "token",
        "--hostname",
        "github.com",
        "--user",
        "jbell-rusty-vantage",
    )
    assert "GH_TOKEN" not in env and "GITHUB_TOKEN" not in env
    assert credential.source == "owner_gh" and credential.username == "jbell-rusty-vantage"
    assert credential.secret.get_secret_value() == "gho_fixture_owner_token"


async def test_a_missing_gh_login_is_refused_without_echoing_output() -> None:
    runner = RecordingRunner(returncode=1, stdout=b"")
    with pytest.raises(GitHubCredentialError, match="no login for jbell-rusty-vantage"):
        await OwnerGhCredentials(runner=runner).credential(REPOSITORY)


def test_the_factory_prefers_the_app_and_never_falls_back_silently(tmp_path: Path) -> None:
    github = FakeGitHub(make_remote(tmp_path))
    key_file = tmp_path / "app.pem"
    key_file.write_bytes(RSAKey.generate_key(2048).as_pem(private=True))
    app = {
        APP_ID_ENV: APP_ID,
        APP_INSTALLATION_ID_ENV: INSTALLATION_ID,
        APP_PRIVATE_KEY_PATH_ENV: str(key_file),
    }

    assert isinstance(github_credentials(app, github.client()), GitHubAppInstallationTokens)
    assert isinstance(
        github_credentials(app, github.client(), owner_gh_attested=True),
        GitHubAppInstallationTokens,
    )
    with pytest.raises(GitHubCredentialError, match="incomplete"):
        github_credentials({APP_ID_ENV: APP_ID}, github.client(), owner_gh_attested=True)
    with pytest.raises(GitHubCredentialError, match="not attested"):
        github_credentials({}, github.client())
    assert isinstance(
        github_credentials({}, github.client(), owner_gh_attested=True), OwnerGhCredentials
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/jbell-rusty-vantage/mission-control",
        "https://github.com/jbell-rusty-vantage/mission-control.git",
        "git@github.com:jbell-rusty-vantage/mission-control.git",
    ],
)
def test_github_repository_urls_parse_to_owner_and_name(url: str) -> None:
    assert GitHubRepository.parse(url) == GitHubRepository("jbell-rusty-vantage", "mission-control")
