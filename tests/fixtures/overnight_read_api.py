"""Signed read-only public API over the workflow fixture's actual application database."""

from __future__ import annotations

import json
import os
import time
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any
from unittest.mock import patch

import httpx
from joserfc import jwt
from joserfc.jwk import RSAKey
from tests.fixtures.mission_control_common_db import COMPONENT_VERSION
from tests.fixtures.rrm009_production_stack import technical_admission_policies

from mission_control.adapters.auth.jwt import ActorGrant, ApplicationAuthentication
from mission_control.adapters.operations.runtime_ports import FilesystemArtifactPayloadStore
from mission_control.adapters.storage.control_plane_payloads import UnavailablePayloadStore
from mission_control.adapters.temporal.deployment_composition import artifact_payload_store
from mission_control.application.installations.registry import ApplicationBinding
from mission_control.bootstrap.api import (
    ApplicationDeployment,
    MissionDeployment,
    RuntimeOptions,
    create_application,
)
from mission_control.domain.authoring.extensions import ExtensionRegistry


@asynccontextmanager
async def overnight_read_api(stack: Any) -> AsyncIterator[httpx.AsyncClient]:
    """Use production authentication/services; the observer has no mutation grants.

    No second worker, run launcher or boundary relay is started. The normal API
    reads the same restricted runtime database and promoted artifact payloads.
    """
    database = stack.database
    assert database is not None
    tenant = database.tenants["tenant-1"]
    application_id = database.application_id
    issuer = "https://overnight-evidence.invalid"
    binding = ApplicationBinding.seal(
        application_id=application_id,
        installation_id=database.installation_id,
        binding_version="1",
        supabase_project_ref=database.project_ref,
        database_secret_ref="APPLICATION_DATABASE_DIRECT",
        accepted_issuers={issuer},
        accepted_audiences={"mission-control"},
        required_component_version=COMPONENT_VERSION,
    )
    key = RSAKey.generate_key(2048, parameters={"kid": "overnight-observer"})
    key_file = stack.payload_root.parent / "overnight-observer-public.json"
    key_file.write_text(json.dumps({"keys": [key.as_dict(private=False)]}), encoding="utf-8")
    authentication = ApplicationAuthentication(
        binding=binding,
        issuer=issuer,
        audience="mission-control",
        public_jwks_file=key_file,
        grants=(
            ActorGrant(
                subject="evidence-observer",
                actor_id="overnight-evidence-observer",
                tenant_ids={tenant},
                permissions={"workflow_run.read", "workflow.result.read"},
            ),
        ),
    )
    payloads = artifact_payload_store(stack.settings)
    assert isinstance(payloads, FilesystemArtifactPayloadStore), "fixture requires local custody"
    application = create_application(
        MissionDeployment(
            storage_mode="production_common",
            max_request_bytes=1_000_000,
            applications=(ApplicationDeployment(authentication=authentication),),
        ),
        runtime_options={
            application_id: RuntimeOptions(
                technical_admission_policies(),
                ExtensionRegistry(),
                UnavailablePayloadStore(),
                artifact_payloads=payloads,
            )
        },
    )
    token = jwt.encode(
        {"alg": "RS256", "kid": "overnight-observer"},
        {
            "iss": issuer,
            "aud": "mission-control",
            "sub": "evidence-observer",
            "exp": int(time.time()) + 1800,
            "app_metadata": {"application_id": application_id, "tenant_id": str(tenant)},
        },
        key,
    )
    async with AsyncExitStack() as resources:
        # The public API normally owns subscription delivery. This read-only
        # observer must not start another relay beside the existing workflow stack.
        # Restore the process environment immediately after startup.
        with patch.dict(os.environ, {"MISSION_CONTROL_SUBSCRIPTION_RELAY": "0"}):
            await resources.enter_async_context(application.router.lifespan_context(application))
        client = await resources.enter_async_context(
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application),
                base_url=f"http://overnight-observer/v1/applications/{application_id}/",
                headers={"Authorization": f"Bearer {token}"},
                timeout=45,
            )
        )
        yield client
