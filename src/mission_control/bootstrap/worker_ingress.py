"""Opt-in production ingress worker assembly; no provider/network work on import."""

from __future__ import annotations

import asyncio
import os
from contextlib import AsyncExitStack, suppress
from pathlib import Path
from typing import Any

import asyncpg
import httpx

from mission_control.adapters.postgres.frames.transcript_projection import PostgresRunMissionIds
from mission_control.adapters.postgres.ingress_drainer import listen_ingress
from mission_control.adapters.postgres.run_control.cluster_bindings import (
    PostgresRunClusterBindings,
)
from mission_control.adapters.supabase_storage.ingress import (
    SupabaseArtifactPayloadStore,
    SupabaseQuarantineStore,
)
from mission_control.adapters.temporal.registration.task_queues import watchers_task_queue
from mission_control.adapters.temporal.submission import TemporalWorkflowSubmitter
from mission_control.adapters.temporal.watcher_starter import TemporalWatcherStarter
from mission_control.application.execution.run_launch import RunLaunchService
from mission_control.application.signals.artifacts import ArtifactCustodyService
from mission_control.bootstrap.api import application_pool
from mission_control.bootstrap.catalog import compose_catalog_service
from mission_control.bootstrap.ingress_drainer import compose_ingress_drainer
from mission_control.bootstrap.launch_promises import compose_launch_promises
from mission_control.bootstrap.manifests import (
    compose_manifest_launch_inputs,
    compose_manifest_service,
)
from mission_control.bootstrap.subscriptions import compose_subscription_service
from mission_control.domain.authoring.extensions import ExtensionRegistry


async def start_worker_ingress(
    stack: AsyncExitStack,
    *,
    prepared: Any,
    settings: Any,
    client: Any,
    control_plane: Any,
    run_control: Any,
    options: Any,
    payload_store: Any,
    cluster: Any = None,
) -> tuple[asyncio.Task[Any], ...]:
    if not getattr(settings, "ingress_drainer_enabled", False):
        return ()
    authentication = prepared.application.authentication
    binding = authentication.binding
    temporal = prepared.application.temporal
    if temporal is None or settings.manifest_launch_bindings_path is None:
        raise RuntimeError("ingress drainer requires Temporal and manifest launch bindings")
    manifests = {}
    for ref, path in getattr(settings, "ingress_manifest_paths", {}).items():
        manifests[ref] = await asyncio.to_thread(Path(path).read_text, encoding="utf-8")
    claim_pool = await application_pool(binding.database_secret_ref)
    stack.push_async_callback(claim_pool.close)
    author = compose_manifest_launch_inputs(
        prepared.runtime_pool,
        settings=settings,
        application_id=binding.application_id,
        run_control=run_control,
        control_plane=control_plane,
    )
    if author is None:
        raise RuntimeError("ingress manifest launch input author is unavailable")
    submitter = TemporalWorkflowSubmitter.for_production(
        client,
        root_task_queue=temporal.root_task_queue,
        stagegraph_task_queue=temporal.stagegraph_task_queue,
        goal_directed_task_queue=temporal.goal_directed_task_queue,
        search_attribute_policy="required",
        mission_installation_id=binding.installation_id,
        mission_application_id=binding.application_id,
    )
    launches = RunLaunchService(
        run_control=run_control,
        submitter=submitter,
        # OVE-166 / WI-02: every launch route registers the admitted promises.
        promises=compose_launch_promises(prepared.runtime_pool),
        mission_ids=PostgresRunMissionIds(prepared.runtime_pool),
        cluster_bindings=PostgresRunClusterBindings(prepared.runtime_pool) if cluster else None,
        cluster=cluster,
    )
    watchers = TemporalWatcherStarter(
        client, task_queue=watchers_task_queue(temporal.root_task_queue)
    )
    scopes = [
        f"mc/{binding.installation_id}/{binding.application_id}/{tenant}"
        for tenant in sorted({t for g in authentication.grants for t in g.tenant_ids}, key=str)
    ]
    services = {}
    for scope in scopes:
        catalog_factory = options.catalog_factory if options else None
        catalog = (catalog_factory or compose_catalog_service)(
            prepared.runtime_pool,
            request_scope=scope,
            catalog_scope=f"mc/{binding.installation_id}/{binding.application_id}/catalog",
        )
        services[scope] = compose_manifest_service(
            prepared.runtime_pool,
            request_scope=scope,
            catalog=catalog,
            extensions=options.extensions if options else ExtensionRegistry(),
            payload_store=payload_store,
            run_control=run_control,
            admission_policies=options.admission_policies if options else None,
            launches=launches,
            subscriptions=compose_subscription_service(prepared.runtime_pool, scope),
            launch_inputs=author,
            watchers=watchers,
            settings=settings,
            application_binding=binding,
            data_class_policy=binding.data_class_policy,
        )
    custody = None
    quarantine_bucket = getattr(settings, "ingress_quarantine_bucket", None)
    custody_bucket = getattr(settings, "ingress_custody_bucket", None)
    credential = getattr(settings, "ingress_storage_credential", None)
    if any((quarantine_bucket, custody_bucket, credential)):
        if (
            not all((quarantine_bucket, custody_bucket, credential, settings.db.url))
            or quarantine_bucket == custody_bucket
        ):
            raise RuntimeError(
                "ingress custody needs separate buckets and an application storage credential"
            )
        assert quarantine_bucket is not None and custody_bucket is not None
        assert credential is not None
        project_url = settings.db.url
        assert project_url is not None
        http = await stack.enter_async_context(httpx.AsyncClient(timeout=30))
        quarantine = SupabaseQuarantineStore(
            http,
            project_url=project_url,
            bucket=quarantine_bucket,
            credential=credential.get_secret_value(),
        )
        payloads = SupabaseArtifactPayloadStore(
            SupabaseQuarantineStore(
                http,
                project_url=project_url,
                bucket=custody_bucket,
                credential=credential.get_secret_value(),
            ),
            namespace=f"{binding.application_id}/{binding.installation_id}",
        )

        def custody(authority: Any) -> ArtifactCustodyService:
            return ArtifactCustodyService(quarantine, payloads, authority)

    notified = asyncio.Event()
    listen_ref = getattr(settings, "ingress_listen_secret_ref", None)
    if listen_ref:
        dsn = os.environ.get(listen_ref)
        if not dsn:
            raise RuntimeError("configured ingress LISTEN credential is unavailable")
        connection = await asyncpg.connect(dsn, statement_cache_size=0)
        stack.push_async_callback(connection.close)
        notified = await stack.enter_async_context(listen_ingress(connection))
    stop = asyncio.Event()
    tasks = tuple(
        asyncio.create_task(
            compose_ingress_drainer(
                claim_pool=claim_pool,
                runtime_pool=prepared.runtime_pool,
                request_scope=scope,
                authentication=authentication,
                manifest_services=services,
                manifests=manifests,
                temporal_client=client,
                artifact_custody=custody,
            ).run(stop, notified),
            name=f"ingress-drainer:{scope}",
        )
        for scope in scopes
    )

    async def shutdown() -> None:
        stop.set()
        notified.set()
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks), timeout=max(settings.worker_graceful_shutdown_seconds, 1)
            )
        finally:
            for task in tasks:
                task.cancel()
            with suppress(asyncio.CancelledError):
                await asyncio.gather(*tasks, return_exceptions=True)

    stack.push_async_callback(shutdown)
    return tasks
