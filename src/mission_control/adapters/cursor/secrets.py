"""Cursor secret delivery for `cursor_cloud` (research/cursor.md sections 2.1-2.5; ADR-0043).

Two channels reach a cloud agent:

* stored secrets (`CursorSecretsClient`): `PUT /v1/environments/{id}/secrets/{name}` and
  `PUT /v1/team/secrets/{name}` with `{value, type: runtime_secret}` (redacted to
  `[REDACTED]` in the agent's tool results, transcript and commits), and
  `DELETE /v1/environments/{id}/secrets/{name}`; the listings return names, never values, and
  serve provider-held verification. `CursorEnvironmentSecrets` and `CursorTeamSecrets` are the
  two `ProviderSecretStore`s. Kit-level secrets go here, synced into the environment that
  `adapters/cursor/environments.py` provisions (MO-13);
* launch `envVars` on the agent create request for per-run values (`launch_env_vars` checks
  Cursor's documented limits before the create, so a refusal names the variable, not a 400).

Values are case-insensitive and unique by name, 1 to 4,096 bytes; names containing
`CURSOR_SANDBOX` and the proxy variables are reserved. Build Secrets and user secrets have no
write API and stay owner prerequisites. A listing item is `{id, name, type, repos, createdAt}`
and a delete answers `{name}`, or `404 secret_not_found` for a name the environment does not
hold (observed 2026-10-14, MO-13 drill; values are never returned).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final
from urllib.parse import quote

import httpx
from pydantic import SecretStr

from mission_control.adapters.cursor.cloud_api import CLOUD_API_BASE, api_client
from mission_control.adapters.remote_session.errors import ErrorRule, raise_for_response
from mission_control.application.secrets.delivery import DeliveryChannel

MAX_VALUE_BYTES: Final = 4_096
MAX_LAUNCH_ENV_VARS: Final = 50
MAX_LAUNCH_NAME_BYTES: Final = 255
_RESERVED_NAMES: Final = frozenset({"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"})


class CursorSecretRefused(ValueError):
    """Cursor refused a secret operation, or a value would break a documented limit."""


class CursorSecretNotFound(CursorSecretRefused):
    """`404 secret_not_found`: the environment holds no secret under that name."""


SECRETS_ERRORS: Final[tuple[ErrorRule, ...]] = (
    ErrorRule(
        403,
        CursorSecretRefused,
        "this key type cannot manage secrets (team, webhook and grok keys are refused)",
        code="key_not_supported",
    ),
    ErrorRule(
        403,
        CursorSecretRefused,
        "a repository-limited key cannot set team secrets",
        code="repository_access",
    ),
    ErrorRule(
        403,
        CursorSecretRefused,
        "the team restricts secret changes to admins",
        code="team_admin_required",
    ),
    ErrorRule(400, CursorSecretRefused, "the provider refused the secret", code="validation_error"),
    ErrorRule(
        404, CursorSecretNotFound, "the environment holds no such secret", code="secret_not_found"
    ),
    ErrorRule(404, CursorSecretRefused, "the environment does not exist"),
)


def _check_value(name: str, value: str) -> None:
    upper = name.upper()
    if "CURSOR_SANDBOX" in upper or upper in _RESERVED_NAMES:
        raise CursorSecretRefused(f"{name} is a name Cursor reserves")
    if not 1 <= len(value.encode("utf-8")) <= MAX_VALUE_BYTES:
        raise CursorSecretRefused(f"{name}'s value is outside Cursor's 1 to 4,096 bytes")


def launch_env_vars(values: Mapping[str, str]) -> dict[str, str]:
    """The create request's `envVars`, checked against Cursor's documented launch limits
    (research/cursor.md section 2.5: 50 entries, names up to 255 bytes not starting with
    `CURSOR_`, values up to 4,096 bytes); the stored-secret rules do not apply here."""

    if len(values) > MAX_LAUNCH_ENV_VARS:
        raise CursorSecretRefused(f"Cursor accepts at most {MAX_LAUNCH_ENV_VARS} launch envVars")
    for name, value in values.items():
        if name.upper().startswith("CURSOR_"):
            raise CursorSecretRefused(f"launch envVars may not start with CURSOR_ ({name})")
        if len(name.encode("utf-8")) > MAX_LAUNCH_NAME_BYTES:
            raise CursorSecretRefused(f"launch envVar name {name[:32]}... exceeds 255 bytes")
        if len(value.encode("utf-8")) > MAX_VALUE_BYTES:
            raise CursorSecretRefused(f"{name}'s value exceeds Cursor's 4,096 bytes")
    return dict(values)


def _names(body: Any) -> frozenset[str]:
    items = body.get("items") if isinstance(body, Mapping) else None
    return frozenset(
        str(item["name"])
        for item in items or ()
        if isinstance(item, Mapping) and isinstance(item.get("name"), str)
    )


class CursorSecretsClient:
    """The environment and team secrets endpoints of the Cursor API (an HTTP fake in tests)."""

    def __init__(
        self,
        api_key: SecretStr,
        *,
        base_url: str = CLOUD_API_BASE,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_s: float = 30,
    ) -> None:
        self._client = api_client(
            api_key, base_url=base_url, transport=transport, timeout=timeout_s
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def put_environment_secret(self, environment_id: str, name: str, value: str) -> None:
        _check_value(name, value)
        response = await self._client.put(
            f"/v1/environments/{quote(environment_id, safe='')}/secrets/{quote(name, safe='')}",
            json={"value": value, "type": "runtime_secret"},
        )
        raise_for_response(
            response, "put environment secret", SECRETS_ERRORS, fallback=CursorSecretRefused
        )

    async def delete_environment_secret(self, environment_id: str, name: str) -> bool:
        """Remove one environment secret; False when the environment held no such name."""

        response = await self._client.delete(
            f"/v1/environments/{quote(environment_id, safe='')}/secrets/{quote(name, safe='')}"
        )
        try:
            raise_for_response(
                response, "delete environment secret", SECRETS_ERRORS, fallback=CursorSecretRefused
            )
        except CursorSecretNotFound:
            return False
        return True

    async def environment_secret_names(self, environment_id: str) -> frozenset[str]:
        response = await self._client.get(
            f"/v1/environments/{quote(environment_id, safe='')}/secrets"
        )
        raise_for_response(
            response, "list environment secrets", SECRETS_ERRORS, fallback=CursorSecretRefused
        )
        return _names(response.json())

    async def put_team_secret(self, name: str, value: str) -> None:
        _check_value(name, value)
        response = await self._client.put(
            f"/v1/team/secrets/{quote(name, safe='')}",
            json={"value": value, "type": "runtime_secret"},
        )
        raise_for_response(
            response, "put team secret", SECRETS_ERRORS, fallback=CursorSecretRefused
        )

    async def team_secret_names(self) -> frozenset[str]:
        response = await self._client.get("/v1/team/secrets")
        raise_for_response(
            response, "list team secrets", SECRETS_ERRORS, fallback=CursorSecretRefused
        )
        return _names(response.json())


class CursorEnvironmentSecrets:
    """One Cursor environment's secrets as a `ProviderSecretStore`."""

    channel = DeliveryChannel.CURSOR_ENVIRONMENT

    def __init__(self, client: CursorSecretsClient, environment_id: str) -> None:
        self._client = client
        self._environment_id = environment_id

    @property
    def target(self) -> str:
        return f"cursor:environment:{self._environment_id}"

    async def put(self, name: str, value: str) -> None:
        await self._client.put_environment_secret(self._environment_id, name, value)

    async def delete(self, name: str) -> bool:
        return await self._client.delete_environment_secret(self._environment_id, name)

    async def names(self) -> frozenset[str]:
        return await self._client.environment_secret_names(self._environment_id)


class CursorTeamSecrets:
    """The team's secrets as a `ProviderSecretStore`."""

    channel = DeliveryChannel.CURSOR_TEAM
    target = "cursor:team"

    def __init__(self, client: CursorSecretsClient) -> None:
        self._client = client

    async def put(self, name: str, value: str) -> None:
        await self._client.put_team_secret(name, value)

    async def names(self) -> frozenset[str]:
        return await self._client.team_secret_names()


__all__ = [
    "MAX_LAUNCH_ENV_VARS",
    "SECRETS_ERRORS",
    "CursorEnvironmentSecrets",
    "CursorSecretNotFound",
    "CursorSecretRefused",
    "CursorSecretsClient",
    "CursorTeamSecrets",
    "launch_env_vars",
]
