from __future__ import annotations

import base64
import json
from uuid import uuid4

import pytest
from joserfc import jwt
from tests.support.unit.mission_control.authentication import (
    NOW,
    authenticated_world,  # noqa: F401
    token,
)

from mission_control.adapters.auth.jwt import (
    ApplicationAuthentication,
    MissionAuthenticationRejected,
    MissionTokenVerifier,
)
from mission_control.application.installations.registry import ApplicationBinding


def test_signed_identity_maps_only_operator_configured_grants(authenticated_world):  # noqa: F811
    key, config, claims, verifier = authenticated_world
    principal = verifier.authenticate("biotech", token(key, claims))
    assert principal.identity.installation_id == config.binding.installation_id
    assert principal.actor.actor_id == "operator"
    assert principal.actor.permissions == frozenset({"workflow_run.read"})


@pytest.mark.parametrize(
    "patch",
    [
        {"iss": "https://attacker.invalid"},
        {"aud": "another-audience"},
        {"exp": NOW - 1},
        {"exp": NOW},
        {"exp": True},
        {"iat": NOW + 60},
        {"nbf": NOW + 60},
        {"sub": "not-granted"},
        {"app_metadata": {"application_id": "other", "tenant_id": str(uuid4())}},
        {"app_metadata": {"application_id": "biotech", "tenant_id": str(uuid4())}},
    ],
)
def test_scope_signature_and_time_fail_closed(authenticated_world, patch):  # noqa: F811
    key, _, claims, verifier = authenticated_world
    with pytest.raises(MissionAuthenticationRejected):
        verifier.authenticate("biotech", token(key, {**claims, **patch}))


def test_cross_application_token_denied(authenticated_world):  # noqa: F811
    key, config, claims, _ = authenticated_world
    other_binding = ApplicationBinding.seal(
        **{
            **config.binding.model_dump(exclude={"binding_digest"}),
            "application_id": "other",
            "installation_id": uuid4(),
        }
    )
    other = config.model_copy(update={"binding": other_binding})
    verifier = MissionTokenVerifier((config, other), clock=lambda: NOW)
    with pytest.raises(MissionAuthenticationRejected):
        verifier.authenticate("other", token(key, claims))


def test_unsigned_and_tampered_tokens_rejected(authenticated_world):  # noqa: F811
    key, _, claims, verifier = authenticated_world
    signed = token(key, claims)

    def encoded(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()

    unsigned = encoded({"alg": "none", "kid": "test-key"}) + "." + encoded(claims) + "."
    tampered = ".".join(
        [signed.split(".")[0], encoded({**claims, "sub": "attacker"}), signed.split(".")[2]]
    )
    for value in (unsigned, tampered):
        with pytest.raises(MissionAuthenticationRejected):
            verifier.authenticate("biotech", value)


def test_untrusted_embedded_key_rejected(authenticated_world):  # noqa: F811
    key, _, claims, verifier = authenticated_world
    signed = jwt.encode({"alg": "RS256", "kid": "test-key", "jwk": key.as_dict()}, claims, key)
    with pytest.raises(MissionAuthenticationRejected):
        verifier.authenticate("biotech", signed)


def test_private_keys_and_editable_tenant_claim_configuration_rejected(authenticated_world):  # noqa: F811
    key, config, _, _ = authenticated_world
    config.public_jwks_file.write_text(json.dumps({"keys": [key.as_dict(private=True)]}))
    with pytest.raises(ValueError, match="private"):
        MissionTokenVerifier((config,))
    with pytest.raises(ValueError, match="user-editable"):
        ApplicationAuthentication.model_validate(
            {
                **config.model_dump(),
                "tenant_claim": ("user_metadata", "tenant_id"),
            }
        )
