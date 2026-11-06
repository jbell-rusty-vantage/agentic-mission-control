"""Offline operator token minting from an existing, trusted application auth configuration."""

from __future__ import annotations

import json
import time
from pathlib import Path
from uuid import UUID

from joserfc import jwk, jwt

from mission_control.adapters.auth.jwt import ApplicationAuthentication, MissionTokenVerifier


def mint_operator_token(
    configuration: ApplicationAuthentication,
    *,
    private_key_file: Path,
    key_id: str,
    subject: str,
    tenant_id: UUID,
    scopes: frozenset[str],
    expires_in: int = 900,
    algorithm: str = "RS256",
    now: int | None = None,
) -> str:
    """Never grants more than the operator configuration; verify the result before release."""
    if not 1 <= expires_in <= 3600 or algorithm not in configuration.algorithms:
        raise ValueError("unsupported token expiry or signature algorithm")
    grant = next((item for item in configuration.grants if item.subject == subject), None)
    if (
        grant is None
        or tenant_id not in grant.tenant_ids
        or not scopes
        or not scopes <= grant.permissions
    ):
        raise ValueError("requested subject, tenant or scopes are not granted")
    issued = int(time.time()) if now is None else now
    claims: dict[str, object] = {
        "iss": configuration.issuer,
        "aud": configuration.audience,
        "sub": subject,
        "iat": issued,
        "nbf": issued,
        "exp": issued + expires_in,
        "mc_scope": " ".join(sorted(scopes)),
    }
    for path, value in (
        (configuration.application_claim, configuration.binding.application_id),
        (configuration.tenant_claim, str(tenant_id)),
    ):
        node = claims
        for part in path[:-1]:
            child = node.setdefault(part, {})
            if not isinstance(child, dict):
                raise ValueError("scope claim overlaps a registered claim")
            node = child
        if path[-1] in node:
            raise ValueError("scope claim overlaps a registered claim")
        node[path[-1]] = value
    raw = private_key_file.read_bytes()
    key = jwk.import_key(json.loads(raw) if raw.lstrip().startswith(b"{") else raw)
    token = jwt.encode({"alg": algorithm, "kid": key_id, "typ": "JWT"}, claims, key)
    MissionTokenVerifier((configuration,), clock=lambda: issued).authenticate(
        configuration.binding.application_id, token
    )
    return token
