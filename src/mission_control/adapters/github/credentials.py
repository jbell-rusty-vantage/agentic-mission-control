"""Push credentials for the git write path (SPEC-01 section 6; DECISIONS R26; MO-14).

- **GitHub App installation token** (preferred). The Mission Control GitHub App signs a
  ten-minute RS256 JWT with its private key and exchanges it for an installation access token
  restricted to the one target repository and to `contents: write`, `pull_requests: write`
  and `metadata: read`. Tokens are cached per repository until five minutes before expiry.
  Configuration is by name only: `MC_GITHUB_APP_ID`, `MC_GITHUB_APP_INSTALLATION_ID` and
  `MC_GITHUB_APP_PRIVATE_KEY_PATH` (a `.pem` outside every repository).
- **Owner `gh` login** (owner-attested fallback until the App lands). It always selects the
  account explicitly (`gh auth token --hostname github.com --user Overton77`): the active `gh`
  account on the owner's machine is another one, and an ambient `GH_TOKEN`/`GITHUB_TOKEN`
  would override the selection, so those are removed from the child environment.

`github_credentials` refuses an incomplete App configuration and never falls back to `gh`
unless the caller passes the owner's attestation. The Secret Broker (MO-11) replaces the
environment and key-file reads behind the same `GitCredentialSource` port.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import httpx
from joserfc import jwt
from joserfc.jwk import RSAKey
from pydantic import SecretStr

from mission_control.adapters.github.repositories import (
    API_HEADERS,
    GITHUB_API,
    GITHUB_HOST,
    GitHubError,
    GitHubRepository,
)
from mission_control.application.effects.ports import GitCredential, GitCredentialSource

APP_ID_ENV: Final = "MC_GITHUB_APP_ID"
APP_INSTALLATION_ID_ENV: Final = "MC_GITHUB_APP_INSTALLATION_ID"
APP_PRIVATE_KEY_PATH_ENV: Final = "MC_GITHUB_APP_PRIVATE_KEY_PATH"
APP_ENVIRONMENT: Final = (APP_ID_ENV, APP_INSTALLATION_ID_ENV, APP_PRIVATE_KEY_PATH_ENV)
# DECISIONS R26: the owner's GitHub account for the `gh` fallback.
OWNER_GH_ACCOUNT: Final = "Overton77"
INSTALLATION_PERMISSIONS: Final = {
    "contents": "write",
    "pull_requests": "write",
    "metadata": "read",
}
APP_TOKEN_USERNAME: Final = "x-access-token"  # noqa: S105 - the fixed git username
_JWT_LIFETIME: Final = 540
_JWT_BACKDATE: Final = 60
_REFRESH_MARGIN: Final = timedelta(minutes=5)
# Environment variables that make `gh` ignore `--user` and use another credential.
_GH_TOKEN_OVERRIDES: Final = frozenset(
    {"GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN"}
)

CommandRunner = Callable[[Sequence[str], Mapping[str, str]], Awaitable[tuple[int, bytes]]]


class GitHubCredentialError(GitHubError):
    """No credential could be issued (never carries the credential itself)."""


class GitHubAppInstallationTokens:
    """`GitCredentialSource` over the Mission Control GitHub App installation."""

    def __init__(
        self,
        *,
        app_id: str,
        installation_id: str,
        private_key: bytes,
        http: httpx.AsyncClient,
        api_url: str = GITHUB_API,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._app_id = app_id
        self._installation_id = installation_id
        self._key = RSAKey.import_key(private_key)
        self._http = http
        self._api = api_url.rstrip("/")
        self._clock = clock
        self._cache: dict[str, GitCredential] = {}

    def _app_jwt(self) -> str:
        now = int(self._clock())
        claims = {"iat": now - _JWT_BACKDATE, "exp": now + _JWT_LIFETIME, "iss": self._app_id}
        return jwt.encode({"alg": "RS256", "typ": "JWT"}, claims, self._key)

    async def credential(self, repository: str) -> GitCredential:
        target = GitHubRepository.parse(repository)
        cached = self._cache.get(target.full_name)
        now = datetime.fromtimestamp(self._clock(), UTC)
        if cached is not None and cached.expires_at and cached.expires_at - _REFRESH_MARGIN > now:
            return cached
        response = await self._http.post(
            f"{self._api}/app/installations/{self._installation_id}/access_tokens",
            headers={**API_HEADERS, "Authorization": f"Bearer {self._app_jwt()}"},
            json={"repositories": [target.name], "permissions": INSTALLATION_PERMISSIONS},
        )
        if response.status_code != 201:
            raise GitHubCredentialError(
                f"installation token for {target.full_name} refused ({response.status_code})",
                status=response.status_code,
            )
        body = response.json()
        granted = [item.get("full_name") for item in body.get("repositories", [])]
        if granted and granted != [target.full_name]:
            raise GitHubCredentialError(
                f"the installation token is not restricted to {target.full_name}"
            )
        credential = GitCredential(
            repository=repository,
            username=APP_TOKEN_USERNAME,
            secret=SecretStr(str(body["token"])),
            source="github_app_installation",
            expires_at=datetime.fromisoformat(str(body["expires_at"]).replace("Z", "+00:00")),
        )
        self._cache[target.full_name] = credential
        return credential


def _run_blocking(argv: Sequence[str], env: Mapping[str, str]) -> tuple[int, bytes]:
    completed = subprocess.run(list(argv), capture_output=True, env=dict(env), check=False)
    return completed.returncode, completed.stdout


async def _run(argv: Sequence[str], env: Mapping[str, str]) -> tuple[int, bytes]:
    return await asyncio.to_thread(_run_blocking, argv, env)


class OwnerGhCredentials:
    """`GitCredentialSource` over the owner's `gh` login for one explicitly selected account."""

    def __init__(
        self,
        account: str = OWNER_GH_ACCOUNT,
        *,
        hostname: str = GITHUB_HOST,
        runner: CommandRunner = _run,
    ) -> None:
        self._account = account
        self._hostname = hostname
        self._runner = runner

    def command(self) -> tuple[str, ...]:
        return ("gh", "auth", "token", "--hostname", self._hostname, "--user", self._account)

    async def credential(self, repository: str) -> GitCredential:
        GitHubRepository.parse(repository)
        env = {name: value for name, value in os.environ.items() if name not in _GH_TOKEN_OVERRIDES}
        returncode, stdout = await self._runner(self.command(), env)
        token = stdout.decode("utf-8", "replace").strip()
        if returncode != 0 or not token:
            raise GitHubCredentialError(
                f"gh has no login for {self._account} on {self._hostname} ({returncode})"
            )
        return GitCredential(
            repository=repository,
            username=self._account,
            secret=SecretStr(token),
            source="owner_gh",
        )


def github_credentials(
    environ: Mapping[str, str],
    http: httpx.AsyncClient,
    *,
    owner_gh_attested: bool = False,
    api_url: str = GITHUB_API,
) -> GitCredentialSource:
    """The App source when its three settings are present; the owner's `gh` login only when
    the owner attested it; otherwise a refusal (never an ambient credential)."""

    present = [name for name in APP_ENVIRONMENT if environ.get(name)]
    if len(present) == len(APP_ENVIRONMENT):
        return GitHubAppInstallationTokens(
            app_id=environ[APP_ID_ENV],
            installation_id=environ[APP_INSTALLATION_ID_ENV],
            private_key=Path(environ[APP_PRIVATE_KEY_PATH_ENV]).read_bytes(),
            http=http,
            api_url=api_url,
        )
    if present:
        missing = sorted(set(APP_ENVIRONMENT) - set(present))
        raise GitHubCredentialError(f"the GitHub App configuration is incomplete: {missing}")
    if owner_gh_attested:
        return OwnerGhCredentials()
    raise GitHubCredentialError(
        "no GitHub App is configured and the owner gh fallback was not attested"
    )


__all__ = [
    "APP_ENVIRONMENT",
    "APP_ID_ENV",
    "APP_INSTALLATION_ID_ENV",
    "APP_PRIVATE_KEY_PATH_ENV",
    "APP_TOKEN_USERNAME",
    "INSTALLATION_PERMISSIONS",
    "OWNER_GH_ACCOUNT",
    "CommandRunner",
    "GitHubAppInstallationTokens",
    "GitHubCredentialError",
    "OwnerGhCredentials",
    "github_credentials",
]
