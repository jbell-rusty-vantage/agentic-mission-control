"""Signed ordinary API controls over the already-running disposable Qualia stack.

This starts no second Temporal server or cognition workers. The primary manifest lifecycle
owns preparation; this companion serves scoped inspection/commands/snapshots/forks/launch.
Only an absent maintenance queue gets a fork-seed worker over the active worker's saver.
"""

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
from temporalio.worker import Worker
from tests.fixtures.db_env import db_env_name
from tests.fixtures.manifest_runtime import AUTHOR
from tests.fixtures.mission_control_common_db import COMPONENT_VERSION
from tests.fixtures.rrm009_production_stack import technical_admission_policies

from mission_control.adapters.auth.jwt import ActorGrant, ApplicationAuthentication
from mission_control.adapters.operations.runtime_ports import FilesystemArtifactPayloadStore
from mission_control.adapters.storage.control_plane_payloads import UnavailablePayloadStore
from mission_control.adapters.temporal.activities.fork_seed import ForkSeedActivities
from mission_control.adapters.temporal.coordinator_runtime import coordinator_task_queues
from mission_control.adapters.temporal.deployment_composition import artifact_payload_store
from mission_control.adapters.temporal.registration.task_queues import maintenance_task_queue
from mission_control.adapters.temporal.workflow_sandbox import coordinator_workflow_runner
from mission_control.adapters.temporal.workflows.fork_seed import ForkSeedWorkflow
from mission_control.application.execution.service import FamilyAdmissionRegistry
from mission_control.application.installations.registry import ApplicationBinding
from mission_control.application.programs.goal_directed import (
    configure_goal_directed_family_admissions,
)
from mission_control.application.programs.service import register_stagegraph_family_mutations
from mission_control.bootstrap.api import (
    ApplicationDeployment,
    MissionDeployment,
    RuntimeOptions,
    TemporalDeployment,
    create_application,
)
from mission_control.bootstrap.settings import get_settings
from mission_control.domain.authoring.extensions import ExtensionRegistry
from mission_control.interfaces.http.run_control import ROLE_PERMISSIONS


@asynccontextmanager
async def qualia_control_api(stack: Any) -> AsyncIterator[httpx.AsyncClient]:
    database = stack.database
    assert database is not None
    application_id = database.application_id
    tenant = database.tenants["tenant-1"]
    issuer = "https://overnight-evidence.invalid"
    binding = ApplicationBinding.seal(
        application_id=application_id,
        installation_id=database.installation_id,
        binding_version="1",
        supabase_project_ref=database.project_ref,
        database_secret_ref=db_env_name(application_id, "RUNTIME_DSN"),
        accepted_issuers={issuer},
        accepted_audiences={"mission-control"},
        required_component_version=COMPONENT_VERSION,
    )
    key = RSAKey.generate_key(2048, parameters={"kid": "qualia-control"})
    key_file = stack.payload_root.parent / "qualia-control-public.json"
    key_file.write_text(json.dumps({"keys": [key.as_dict(private=False)]}), encoding="utf-8")
    authentication = ApplicationAuthentication(
        binding=binding,
        issuer=issuer,
        audience="mission-control",
        public_jwks_file=key_file,
        grants=(
            ActorGrant(
                subject="qualia-fixture-operator",
                # The target ERC is compiled by this same ordinary manifest author.
                # A fixture-specific JWT subject does not replace its authority identity.
                actor_id=AUTHOR.actor_id,
                tenant_ids={tenant},
                permissions=(
                    ROLE_PERMISSIONS["operator"]
                    | ROLE_PERMISSIONS["fork_operator"]
                    | ROLE_PERMISSIONS["state_inspector"]
                    | {"workflow.result.read", "workflow_run.control", "workflow_run.admin"}
                ),
                authority_refs={"authority:lifecycle"},
                sponsorship_refs={"sponsorship:test"},
                approval_refs={"approval:test"},
            ),
        ),
    )
    family_admissions = FamilyAdmissionRegistry()
    configure_goal_directed_family_admissions(family_admissions)
    register_stagegraph_family_mutations(family_admissions)
    queues = coordinator_task_queues(stack.settings.task_queue_base)
    payloads = artifact_payload_store(stack.settings)
    assert isinstance(payloads, FilesystemArtifactPayloadStore), "fixture requires local custody"
    application = create_application(
        MissionDeployment(
            storage_mode="production_common",
            max_request_bytes=1_000_000,
            applications=(
                ApplicationDeployment(
                    authentication=authentication,
                    family_writer_secret_ref=db_env_name(application_id, "FAMILY_WRITER_DSN"),
                    temporal=TemporalDeployment(
                        address=stack.settings.temporal_address,
                        namespace=stack.settings.temporal_namespace,
                        root_task_queue=queues.stagegraph,
                        stagegraph_task_queue=queues.stagegraph,
                        goal_directed_task_queue=queues.goal_directed,
                    ),
                ),
            ),
        ),
        runtime_options={
            application_id: RuntimeOptions(
                technical_admission_policies(),
                ExtensionRegistry(),
                UnavailablePayloadStore(),
                family_admissions=family_admissions,
                artifact_payloads=payloads,
            )
        },
    )
    token = jwt.encode(
        {"alg": "RS256", "kid": "qualia-control"},
        {
            "iss": issuer,
            "aud": "mission-control",
            "sub": "qualia-fixture-operator",
            "exp": int(time.time()) + 7200,
            "app_metadata": {"application_id": application_id, "tenant_id": str(tenant)},
        },
        key,
    )
    async with AsyncExitStack() as resources:
        # The already-composed lifecycle owns the custom fixture catalog/model author.
        # Commands and concrete family-input launch need none of a second launch author.
        try:
            with patch.dict(os.environ, {"MISSION_CONTROL_SUBSCRIPTION_RELAY": "0"}):
                os.environ.pop("MANIFEST_LAUNCH_BINDINGS_PATH", None)
                get_settings.cache_clear()
                await resources.enter_async_context(
                    application.router.lifespan_context(application)
                )
        finally:
            get_settings.cache_clear()
        queue = maintenance_task_queue(stack.settings.task_queue_base)
        if queue not in stack.worker_queues:
            assert stack.composition.time_travel is not None, "fork seed needs the active saver"
            await resources.enter_async_context(
                Worker(
                    stack.client,
                    task_queue=queue,
                    workflows=[ForkSeedWorkflow],
                    activities=[ForkSeedActivities(lambda: stack.composition.time_travel).copy],
                    workflow_runner=coordinator_workflow_runner(),
                )
            )
        http = await resources.enter_async_context(
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application),
                base_url="http://qualia-control",
                headers={"Authorization": f"Bearer {token}"},
                timeout=120,
            )
        )
        yield http
