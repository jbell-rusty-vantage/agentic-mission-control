"""The `provider_oidc` tier: a Cursor VM JWT is accepted only in its documented shape."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from joserfc import jwt
from joserfc.jwk import KeySet, RSAKey

from mission_control.adapters.auth.provider_oidc import CursorOidcVerifier
from mission_control.application.signals.contracts import IngressRejected

NOW = 1_800_000_000
AUDIENCE = "https://mc-ingress.vercel.app"
KEY = RSAKey.generate_key(2048, parameters={"kid": "cursor-1", "use": "sig"})
OTHER = RSAKey.generate_key(2048, parameters={"kid": "cursor-1", "use": "sig"})


class Keys:
    def __init__(self, *keys: RSAKey) -> None:
        self.keys = list(keys)
        self.fetches = 0

    async def fetch(self) -> Mapping[str, Any]:
        self.fetches += 1
        return KeySet(self.keys).as_dict(private=False)


def token(key: RSAKey = KEY, kid: str = "cursor-1", **overrides: Any) -> str:
    claims = {
        "iss": "https://api.cursor.com",
        "aud": AUDIENCE,
        "sub": "service_account:sa-1",
        "iat": NOW,
        "exp": NOW + 300,
        "cloud_agent_id": "bc-agent-1",
        "environment_id": "env_1",
        **overrides,
    }
    return jwt.encode({"alg": "RS256", "kid": kid}, claims, key)


def verifier(keys: Keys, clock: list[float] | None = None) -> CursorOidcVerifier:
    now = clock or [float(NOW)]
    return CursorOidcVerifier(audience=AUDIENCE, keys=keys, clock=lambda: now[0])


async def test_a_genuine_token_names_its_cloud_agent_session() -> None:
    identity = await verifier(Keys(KEY)).verify(token())
    assert (identity.provider, identity.session_id, identity.environment_ref) == (
        "cursor",
        "bc-agent-1",
        "env_1",
    )


@pytest.mark.parametrize(
    "bad",
    [
        token(aud="https://elsewhere.example"),
        token(iss="https://evil.example"),
        token(exp=NOW - 60),
        token(exp=NOW + 3600),  # longer than the documented 300 s lifetime
        token(cloud_agent_id=""),
        token(key=OTHER),
        token(kid="unknown"),
        "not.a.jwt",
        "x" * 20_000,
    ],
    ids=["audience", "issuer", "expired", "lifetime", "agent", "signature", "kid", "shape", "size"],
)
async def test_any_other_token_is_refused(bad: str) -> None:
    with pytest.raises(IngressRejected) as refusal:
        await verifier(Keys(KEY)).verify(bad)
    assert (refusal.value.status_code, refusal.value.code) == (401, "invalid_token")


async def test_published_keys_are_cached_and_refetched_on_rotation_at_most_once_a_minute() -> None:
    keys = Keys(KEY)
    clock = [float(NOW)]
    oidc = verifier(keys, clock)
    await oidc.verify(token())
    await oidc.verify(token())
    assert keys.fetches == 1

    rotated = RSAKey.generate_key(2048, parameters={"kid": "cursor-2", "use": "sig"})
    keys.keys.append(rotated)
    with pytest.raises(IngressRejected):
        await oidc.verify(token(rotated, kid="cursor-2"))  # within the refresh interval
    clock[0] += 61
    rotated_token = jwt.encode(
        {"alg": "RS256", "kid": "cursor-2"},
        {
            "iss": "https://api.cursor.com",
            "aud": AUDIENCE,
            "exp": int(clock[0]) + 300,
            "cloud_agent_id": "bc-agent-2",
        },
        rotated,
    )
    assert (await oidc.verify(rotated_token)).session_id == "bc-agent-2"
    assert keys.fetches == 2
