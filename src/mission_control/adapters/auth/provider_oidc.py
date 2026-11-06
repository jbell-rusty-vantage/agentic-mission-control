"""Cursor OIDC verification for the `provider_oidc` ingress tier (SPEC-10 section 2).

A cloud agent's VM mints an RS256 JWT on `/run/cursor/api.sock`: issuer
`https://api.cursor.com`, keys at `https://api.cursor.com/keys`, audience the ingress origin,
`exp = iat + 300`, claims `cloud_agent_id` and `environment_id`
(docs/specs/archive/materialization-observation-2026-10/research/cursor.md section 2.6). The
verifier
accepts only that shape and returns the session it names; which run that session belongs to is
decided in SQL from the worker's session binding. Published keys are cached per process and
refetched on an unknown key id at most once per refresh interval.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import Any, Final, Protocol, cast

import httpx
from joserfc import jws, jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet, KeySetSerialization

from mission_control.application.signals.contracts import IngressRejected
from mission_control.application.signals.ports import OidcIdentity
from mission_control.contracts.json import parse_json_object

CURSOR_ISSUER: Final = "https://api.cursor.com"
CURSOR_JWKS_URL: Final = "https://api.cursor.com/keys"
MAX_TOKEN_CHARS: Final = 16_384


def _invalid() -> IngressRejected:
    return IngressRejected(401, "invalid_token")


class JwksSource(Protocol):
    async def fetch(self) -> Mapping[str, Any]: ...


class HttpJwks:
    """The provider's published key set over HTTPS (redirects refused)."""

    def __init__(self, client: httpx.AsyncClient, url: str = CURSOR_JWKS_URL) -> None:
        if client.follow_redirects:
            raise ValueError("the JWKS transport must not follow redirects")
        self._client = client
        self._url = url

    async def fetch(self) -> Mapping[str, Any]:
        response = await self._client.get(self._url)
        response.raise_for_status()
        return parse_json_object(response.content)


class CursorOidcVerifier:
    def __init__(
        self,
        *,
        audience: str,
        keys: JwksSource,
        issuer: str = CURSOR_ISSUER,
        max_lifetime_seconds: int = 300,
        leeway_seconds: int = 30,
        refresh_interval_seconds: float = 60.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._audience = audience
        self._issuer = issuer
        self._source = keys
        self._max_lifetime = max_lifetime_seconds
        self._leeway = leeway_seconds
        self._refresh_interval = refresh_interval_seconds
        self._clock = clock
        self._keys: KeySet | None = None
        self._fetched_at: float | None = None

    async def _key_set(self, kid: str) -> KeySet:
        known = self._keys is not None and any(key.kid == kid for key in self._keys.keys)
        recent = (
            self._fetched_at is not None
            and self._clock() - self._fetched_at < self._refresh_interval
        )
        if not known and not recent:
            document = await self._source.fetch()
            self._keys = KeySet.import_key_set(cast(KeySetSerialization, dict(document)))
            self._fetched_at = self._clock()
        if self._keys is None or not any(key.kid == kid for key in self._keys.keys):
            raise _invalid()
        return self._keys

    async def verify(self, token: str) -> OidcIdentity:
        if not 1 <= len(token) <= MAX_TOKEN_CHARS or token.count(".") != 2:
            raise _invalid()
        try:
            header = jws.extract_compact(token.encode()).protected
        except (JoseError, ValueError):
            raise _invalid() from None
        kid = header.get("kid")
        if header.get("alg") != "RS256" or not isinstance(kid, str) or not kid:
            raise _invalid()
        keys = await self._key_set(kid)
        now = self._clock()
        try:
            claims = jwt.decode(token, keys, algorithms=["RS256"]).claims
            jwt.JWTClaimsRegistry(
                now=int(now),
                leeway=self._leeway,
                iss={"essential": True, "value": self._issuer},
                aud={"essential": True, "value": self._audience},
                exp={"essential": True},
            ).validate(claims)
        except (JoseError, ValueError, TypeError):
            raise _invalid() from None
        expires = claims.get("exp")
        if not isinstance(expires, int | float) or isinstance(expires, bool):
            raise _invalid()
        if expires - now > self._max_lifetime + self._leeway:
            raise _invalid()
        agent = claims.get("cloud_agent_id")
        environment = claims.get("environment_id")
        if not isinstance(agent, str) or not agent or len(agent) > 512:
            raise _invalid()
        if environment is not None and (not isinstance(environment, str) or not environment):
            raise _invalid()
        return OidcIdentity(provider="cursor", session_id=agent, environment_ref=environment)


__all__ = ["CURSOR_ISSUER", "CURSOR_JWKS_URL", "CursorOidcVerifier", "HttpJwks", "JwksSource"]
