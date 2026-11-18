"""Builders, constants and fakes that other test files import.

Moved from tests/unit/mission_control/test_authentication.py.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from joserfc import jwt
from joserfc.jwk import RSAKey

from mission_control.adapters.auth.jwt import (
    ActorGrant,
    ApplicationAuthentication,
    MissionTokenVerifier,
)
from mission_control.application.installations.registry import ApplicationBinding

NOW = 1_800_000_000


@pytest.fixture
def authenticated_world(tmp_path):
    tenant = uuid4()
    key = RSAKey.generate_key(2048, parameters={"kid": "test-key", "use": "sig"})
    key_file = tmp_path / "public.json"
    key_file.write_text(json.dumps({"keys": [key.as_dict(private=False)]}))
    binding = ApplicationBinding.seal(
        application_id="biotech",
        installation_id=uuid4(),
        binding_version="1",
        supabase_project_ref="local-test",
        database_secret_ref="TEST_DATABASE_DSN",
        accepted_issuers={"https://issuer.invalid"},
        accepted_audiences={"authenticated"},
        required_component_version="1.0.0",
    )
    config = ApplicationAuthentication(
        binding=binding,
        issuer="https://issuer.invalid",
        audience="authenticated",
        public_jwks_file=key_file,
        grants=(
            ActorGrant(
                subject="signed-subject",
                actor_id="operator",
                tenant_ids={tenant},
                permissions={"workflow_run.read"},
                authority_refs={"authority:read"},
            ),
        ),
    )
    claims = {
        "iss": config.issuer,
        "aud": config.audience,
        "sub": "signed-subject",
        "exp": NOW + 60,
        "iat": NOW,
        "app_metadata": {"application_id": "biotech", "tenant_id": str(tenant)},
        "permissions": ["workflow_run.cancel", "*"],
    }
    return key, config, claims, MissionTokenVerifier((config,), clock=lambda: NOW)


def token(key, claims):
    return jwt.encode({"alg": "RS256", "kid": "test-key"}, claims, key)
