"""Signed scoped API stack: the configured API on real PostgreSQL and a local Temporal server.

The application runs in ``production_common`` storage mode on a fresh database with the common
``mission_control`` component installed, every pool is a restricted login, tokens are signed by
a generated key whose public JWKS the deployment pins, and the production workers run
deterministic DeepAgents cognition (no provider network call). Shared by
`tests/acceptance/mission_control/test_authenticated_scoped_runtime.py`, the MO-43 wake-channel
acceptance and the offline operator stack drill (`scripts/offline_operator_stack.py`).
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import asyncpg
import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from joserfc import jwt
from joserfc.jwk import RSAKey
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from temporalio.client import Client
from temporalio.worker import Worker
from tests.fixtures import rrm009_production_stack as technical
from tests.fixtures.db_env import db_env_name
from tests.fixtures.mission_control_common_db import (
    COMPONENT_VERSION,
    CommonDatabase,
    drop_common_database,
)
from tests.fixtures.mission_control_production_stack import _fresh_database, start_local
from tests.fixtures.tcp_proxy import SaverProxy

from mission_control.adapters.auth.jwt import ActorGrant, ApplicationAuthentication
from mission_control.adapters.postgres.frames.retention import PostgresFrameRetention
from mission_control.adapters.postgres.orchestration.goal_directed_repository import (
    PostgresGoalDirectedDocumentRepository,
)
from mission_control.adapters.postgres.orchestration.stagegraph_repository import (
    PostgresStageGraphOperationTemplateRepository,
)
from mission_control.adapters.storage.control_plane_payloads import UnavailablePayloadStore
from mission_control.adapters.temporal.activities.fork_seed import ForkSeedActivities
from mission_control.adapters.temporal.activities.frames_expire import FramesExpireActivities
from mission_control.adapters.temporal.activities.transcript_projection import (
    TranscriptProjectionActivities,
    start_transcript_projection_relay,
)
from mission_control.adapters.temporal.coordinator_runtime import coordinator_task_queues
from mission_control.adapters.temporal.deployment_composition import (
    ProductionWorkerActivityCompositionFactory,
    artifact_payload_store,
)
from mission_control.adapters.temporal.registration.task_queues import maintenance_task_queue
from mission_control.adapters.temporal.search_attributes import register_belllabs_search_attributes
from mission_control.adapters.temporal.worker import ProductionWorkerSet, create_production_workers
from mission_control.adapters.temporal.workflow_sandbox import coordinator_workflow_runner
from mission_control.adapters.temporal.workflows.fork_seed import ForkSeedWorkflow
from mission_control.adapters.temporal.workflows.frames_expire import FramesExpireWorkflow
from mission_control.adapters.temporal.workflows.transcript_projection import (
    TranscriptProjectionWorkflow,
)
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
from mission_control.bootstrap.composition import MissionApplicationServices
from mission_control.bootstrap.settings import get_settings
from mission_control.bootstrap.worker import transcript_projectors
from mission_control.contracts.identities import mission_root_id
from mission_control.domain.authoring.extensions import ExtensionRegistry
from mission_control.interfaces.http.run_control import ROLE_PERMISSIONS

PORT = 17233


@dataclass
class ScopedStack:
    application: FastAPI
    token: str
    http: httpx.AsyncClient
    client: Client
    services: MissionApplicationServices
    pool: asyncpg.Pool
    binding: technical.TechnicalBinding
    model_log: list[dict[str, Any]]
    scope: str
    owner_pool: asyncpg.Pool
    catalogs: dict[str, technical.TechnicalCatalog] = field(default_factory=dict)
    # WP-TR-3: the maintenance queue (`mc.frames_expire.v1`, the transcript projection) and
    # who serves it in this stack: `production` (the worker set) or `fixture` (see
    # `maintenance_worker`).
    maintenance_queue: str = ""
    maintenance_served_by: str = ""
    # Sprint V SV-16: the worker's composed knowledge lane (None unless one was requested).
    knowledge: Any = None
    # The application the stack serves (`biotech` unless a test selects `ai-engineer`).
    application_id: str = "biotech"


@asynccontextmanager
async def scoped_stack(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    saver_proxy: SaverProxy | None = None,
    knowledge_lane: Callable[..., Awaitable[Any]] | None = None,
    knowledge_tools: tuple[Any, ...] = (),
    application_id: str = "biotech",
) -> AsyncIterator[ScopedStack]:
    """The stack on a fresh common database.

    FX-TR-REMOTE (WP-TR-5): with ``saver_proxy`` the LangGraph saver DSN (the
    checkpointer-only login of the fresh database) is pointed at the proxy, which is started
    toward the database's host and port, so both the workers and the API open the saver
    through it; the common Mission Control database stays direct. The proxy is stopped on
    teardown. Without it, the stack is unchanged.
    """

    node = shutil.which("node")
    if node is None:
        pytest.fail("the pinned deterministic MCP/browser component requires local Node")
    common, checkpoint_dsn = await _fresh_database(application_id=application_id)
    try:
        if saver_proxy is not None:
            checkpoint_dsn = await proxied_conninfo(saver_proxy, checkpoint_dsn)
        try:
            async with _scoped_stack(
                root,
                monkeypatch,
                common,
                checkpoint_dsn,
                node,
                knowledge_lane=knowledge_lane,
                knowledge_tools=knowledge_tools,
                application_id=application_id,
            ) as stack:
                yield stack
        finally:
            if saver_proxy is not None:
                await saver_proxy.stop()
    finally:
        await drop_common_database(common)


async def proxied_conninfo(proxy: SaverProxy, dsn: str) -> str:
    """Start ``proxy`` toward ``dsn``'s host and port; return ``dsn`` rebuilt through it.

    ``dsn`` may be a URI or a keyword conninfo; every key other than ``host`` and ``port``
    (user, password, dbname, ...) is kept. The result is a keyword conninfo, which the
    runtime binding (`runtime_checkpoint_conninfo`) accepts like a URI.
    """

    parts = conninfo_to_dict(dsn)
    host = str(parts.get("host") or "127.0.0.1")
    port = int(parts.get("port") or 5432)
    await proxy.start(host, port)
    return make_conninfo("", **{**parts, "host": "127.0.0.1", "port": proxy.port})


@asynccontextmanager
async def _scoped_stack(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    common: CommonDatabase,
    checkpoint_dsn: str,
    node: str,
    *,
    knowledge_lane: Callable[..., Awaitable[Any]] | None = None,
    knowledge_tools: tuple[Any, ...] = (),
    application_id: str = "biotech",
) -> AsyncIterator[ScopedStack]:
    app = application_id
    owner_dsn = common.owner_dsn
    runtime_dsn = common.dsn("mission_control_runtime")
    writer_dsn = common.dsn("mission_control_family_writer")
    installation, tenant = common.installation_id, common.tenants["tenant-1"]
    binding = ApplicationBinding.seal(
        application_id=common.application_id,
        installation_id=installation,
        binding_version="1",
        supabase_project_ref=common.project_ref,
        database_secret_ref="MC_SCOPED_RUNTIME_DSN",
        accepted_issuers={"https://local-qualification.invalid"},
        accepted_audiences={"mission-control"},
        required_component_version=COMPONENT_VERSION,
    )
    scope = common.scope("tenant-1")
    monkeypatch.setattr(technical, "SCOPE", scope)
    environment = {
        "MC_SCOPED_RUNTIME_DSN": runtime_dsn,
        "MC_SCOPED_WRITER_DSN": writer_dsn,
        db_env_name(app, "RUNTIME_DSN"): runtime_dsn,
        db_env_name(app, "ADMIN_DSN"): owner_dsn,
        db_env_name(app, "FAMILY_WRITER_DSN"): writer_dsn,
        "MISSION_CONTROL_CATALOG_SCOPE": f"mc/{installation}/{app}/catalog",
        # OC-R4: the installation's application selects its profile (capability owner).
        "MISSION_CONTROL_APPLICATION": app,
        db_env_name(app, "CHECKPOINT_DSN"): checkpoint_dsn,
        "LANGGRAPH_CHECKPOINT_SCHEMA": technical.LANGGRAPH_SCHEMA,
        "TEMPORAL_ADDRESS": f"127.0.0.1:{PORT}",
        "TEMPORAL_NAMESPACE": "default",
        "TEMPORAL_TASK_QUEUE": technical.TASK_QUEUE,
        "RUN_CONTROL_TEMPORAL_ENABLED": "1",
        "COORDINATOR_LAUNCH_ENABLED": "1",
        "BOUNDARY_RELAY_REQUEST_SCOPES": json.dumps([scope]),
        "ARTIFACT_PAYLOAD_ROOT": str(root / "payloads"),
        "CAPABILITY_BUNDLE_BACKEND": "local",
        "DEEP_AGENT_SANDBOX_WORKSPACE_ROOT": str(root / "workspaces"),
        "WEB_RESEARCH_AGENT_BROWSER_NODE": node,
        "OPERATION_JOURNAL_CLAIMED_BY": "operation-runtime:scoped-proof",
        "ASYNC_SUBAGENT_SUBMITTER_IDENTITY": "scoped-proof",
        "LANGSMITH_TRACING": "false",
        "LANGCHAIN_TRACING_V2": "false",
        "OPENAI_API_KEY": "deterministic-local-no-provider-access",
        "S3_BUCKET": "",
    }
    monkeypatch.delenv("LANGGRAPH_CHECKPOINT_SETUP", raising=False)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    settings = get_settings()
    key = RSAKey.generate_key(2048, parameters={"kid": "scoped-proof"})
    public_key_file = root / "public-jwks.json"
    public_key_file.write_text(json.dumps({"keys": [key.as_dict(private=False)]}))
    authentication = ApplicationAuthentication(
        binding=binding,
        issuer="https://local-qualification.invalid",
        audience="mission-control",
        public_jwks_file=public_key_file,
        grants=(
            ActorGrant(
                subject="qualified-operator",
                actor_id=technical.OPERATOR,
                tenant_ids={tenant},
                permissions=(
                    ROLE_PERMISSIONS["operator"]
                    | ROLE_PERMISSIONS["fork_operator"]
                    # P1 turn 4: `state-as-of` (checkpoint summary) and a fork with an
                    # instruction (`workflow_run.control`, P1-A6) are part of the drills.
                    | ROLE_PERMISSIONS["state_inspector"]
                    | {"workflow.result.read", "workflow_run.control"}
                    # 1.4.4 (FX-TR-RECONCILE): `points:reconcile` is the existing reconcile
                    # grant.
                    | {"workflow_run.reconcile_unit"}
                    # WP-TR-2 (FX-TR-HOOK): `cancel` with `urgency: immediate` of active work
                    # (the stop fence) is an admin command.
                    | {"workflow_run.admin"}
                ),
                authority_refs={"authority:lifecycle"},
                sponsorship_refs={"sponsorship:test"},
                approval_refs={"approval:test"},
            ),
        ),
    )
    queues = coordinator_task_queues(settings.temporal_task_queue)
    deployment = MissionDeployment(
        storage_mode="production_common",
        max_request_bytes=1_000_000,
        applications=(
            ApplicationDeployment(
                authentication=authentication,
                family_writer_secret_ref="MC_SCOPED_WRITER_DSN",
                temporal=TemporalDeployment(
                    address=settings.temporal_address,
                    namespace=settings.temporal_namespace,
                    root_task_queue=queues.stagegraph,
                    stagegraph_task_queue=queues.stagegraph,
                    goal_directed_task_queue=queues.goal_directed,
                ),
            ),
        ),
    )
    family_admissions = FamilyAdmissionRegistry()
    configure_goal_directed_family_admissions(family_admissions)
    register_stagegraph_family_mutations(family_admissions)
    application = create_application(
        deployment,
        runtime_options={
            app: RuntimeOptions(
                technical.technical_admission_policies(),
                ExtensionRegistry(),
                UnavailablePayloadStore(),
                family_admissions=family_admissions,
                # WP-TR-2 (FX-TR-STEP): `GET transcript?full=true` reads promoted frame bodies
                # through the tenant's `GrantedArtifactBodyReader`, which the API composes only
                # over a payload store (`bootstrap/api.py`, MP-13). The same filesystem store
                # the in-process workers promote into (`ARTIFACT_PAYLOAD_ROOT`).
                artifact_payloads=artifact_payload_store(settings),
            )
        },
    )
    env = await start_local(root / "temporal.sqlite", port=PORT)
    print("SCOPED E2E: disposable PostgreSQL and cached Temporal ready", flush=True)
    try:
        await register_belllabs_search_attributes(env.client, settings.temporal_namespace)
        async with AsyncExitStack() as resources:
            await resources.enter_async_context(application.router.lifespan_context(application))
            services = application.state.mission_control_compositions[(installation, app, tenant)]
            pool = await asyncpg.create_pool(runtime_dsn, min_size=1, max_size=5)
            resources.push_async_callback(pool.close)
            owner_pool = await asyncpg.create_pool(owner_dsn, min_size=1, max_size=2)
            resources.push_async_callback(owner_pool.close)
            model_log: list[dict[str, Any]] = []
            binding_assets = technical.technical_binding()
            if knowledge_tools:
                binding_assets = replace(binding_assets, knowledge_tools=knowledge_tools)
            factory = ProductionWorkerActivityCompositionFactory(
                env.client,
                additional_components=binding_assets.components(model_log),
                worker_identity=f"mission-control-scoped-proof:{os.getpid()}",
                claim_lease=timedelta(seconds=90),
                knowledge_lane=knowledge_lane,
            )
            composition = await factory.build(
                settings=settings,
                control_plane=services.control_plane,
                run_control=services.run_control,
                postgres_pool=pool,
            )
            assert composition.resources is not None
            resources.push_async_callback(composition.resources.aclose)
            workers = create_production_workers(env.client, settings, composition)
            for worker in workers.workers:
                await resources.enter_async_context(worker)
            maintenance_queue = maintenance_task_queue(settings.temporal_task_queue)
            maintenance = maintenance_worker(
                env.client, maintenance_queue, workers, pool, composition
            )
            if maintenance is not None:
                await resources.enter_async_context(maintenance)
                start_transcript_projection_relay(
                    resources,
                    pool=pool,
                    client=env.client,
                    task_queue=maintenance_queue,
                    request_scopes=[scope],
                    lease_owner="scoped-proof-transcript-projection",
                    graceful_shutdown_seconds=5.0,
                )
            token = jwt.encode(
                {"alg": "RS256", "kid": "scoped-proof"},
                {
                    "iss": authentication.issuer,
                    "aud": authentication.audience,
                    "sub": "qualified-operator",
                    # Tracing Stage 2: live runs and their reads outlast 30 minutes.
                    "exp": int(time.time())
                    + int(os.environ.get("SCOPED_PROOF_TOKEN_SECONDS", "1800")),
                    "app_metadata": {"application_id": app, "tenant_id": str(tenant)},
                },
                key,
            )
            http = await resources.enter_async_context(
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=application),
                    base_url="http://scoped-proof",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=45,
                )
            )
            print("SCOPED E2E: signed API and actual production workers started", flush=True)
            yield ScopedStack(
                application,
                token,
                http,
                env.client,
                services,
                pool,
                binding_assets,
                model_log,
                scope,
                owner_pool,
                maintenance_queue=maintenance_queue,
                maintenance_served_by="production" if maintenance is None else "fixture",
                knowledge=factory.knowledge,
                application_id=app,
            )
    finally:
        await env.shutdown()
        get_settings.cache_clear()


def maintenance_worker(
    client: Client,
    queue: str,
    workers: ProductionWorkerSet,
    pool: asyncpg.Pool,
    composition: Any | None = None,
) -> Worker | None:
    """WP-TR-3 (FX-TR-RETAIN; FX-TR-STEP on the projection): the maintenance-queue worker.

    The `missionctl worker` entrypoint starts one (`bootstrap/worker.py:542-560`:
    `mc.frames_expire.v1` with `FramesExpireActivities` over the runtime pool) but
    `create_production_workers` does not, so the scoped stack had no worker on the queue and a
    retention run or a projection trigger would wait forever. This serves the retention
    workflow over the stack's runtime pool. It returns None when the production worker set
    already serves the queue (the source stream then registered the retention and the
    projection workflows there, and a second worker on the queue would poll projection tasks
    it cannot run). The transcript projection workflow itself is the source stream's: when it
    is not registered on this worker, FX-TR-STEP's "projected without a refresh" line fails
    and says so.
    """

    if any(worker.task_queue == queue for worker in workers.workers):
        return None
    return Worker(
        client,
        task_queue=queue,
        workflows=[FramesExpireWorkflow, TranscriptProjectionWorkflow, ForkSeedWorkflow],
        activities=[
            FramesExpireActivities(
                PostgresFrameRetention(
                    pool,
                    actor_ref="scoped-proof-frames-expire",
                    projectors=transcript_projectors(pool),
                )
            ).expire,
            # WP-TR-5 (P6.1): the cognitive seed's copy over the workers' own savers.
            ForkSeedActivities(
                lambda: getattr(composition, "time_travel", None) if composition else None
            ).copy,
            # WP-TR-3 (TR-D10): the persisted Transcript projection, released per
            # settlement by the outbox relay the stack starts beside this worker.
            TranscriptProjectionActivities(transcript_projectors(pool)).project,
        ],
        workflow_runner=coordinator_workflow_runner(),
    )


async def close_saver(stack: ScopedStack) -> list[str]:
    """FX-TR-STEP ("all read with the saver pool closed"): close the API process's pinned
    LangGraph saver and return what was closed.

    `bootstrap/api.py::compose_time_travel` opens one `StandalonePersistenceLifespan` over the
    runtime DSN and hands its `AsyncPostgresSaver` to `DeepAgentsTimeTravel` (behind
    `app.state.time_travel_registry`) and to `LangGraphCheckpointHistoryReader`
    (`app.state.inspection_checkpoint_reader`); neither exposes the saver publicly, so this
    reads their `_checkpointers` maps and closes each distinct saver's `conn` (psycopg
    `AsyncConnection`). The workers' own saver (`composition.resources`) stays open, so the
    run itself is unaffected; `state-as-of` and `points:reconcile` lose their saver, while the
    transcript and points routes read the common database only. The lifespan exit closes the
    connection again at teardown, which psycopg accepts.
    """

    state = stack.application.state
    holders: list[Any] = []
    registry = getattr(state, "time_travel_registry", None)
    if registry is not None and registry.supports("deep_agents"):
        holders.append(registry.lane("deep_agents"))
    reader = getattr(state, "inspection_checkpoint_reader", None)
    if reader is not None:
        holders.append(reader)
    savers: dict[int, Any] = {}
    for holder in holders:
        for saver in (getattr(holder, "_checkpointers", None) or {}).values():
            savers.setdefault(id(saver), saver)
    closed: list[str] = []
    for saver in savers.values():
        connection = getattr(saver, "conn", None)
        close = getattr(connection, "close", None)
        if close is None:
            continue
        await close()
        closed.append(f"{type(saver).__name__}.conn:{type(connection).__name__}")
    return closed


async def until(predicate: Callable[[], Awaitable[bool]], seconds: float = 180) -> None:
    async with asyncio.timeout(seconds):
        for _ in range(int(seconds * 4)):
            if await predicate():
                return
            await asyncio.sleep(0.25)
    raise AssertionError("runtime condition did not become true")


async def inspect(stack: ScopedStack, run_id: str) -> dict[str, Any]:
    response = await stack.http.get(
        f"/v1/applications/{stack.application_id}/runs/{run_id}/inspection"
    )
    assert response.status_code == 200, response.text
    return response.json()


async def prepare_run(stack: ScopedStack, family: str) -> tuple[str, dict[str, Any]]:
    """Admit a run over HTTP and persist its native templates: (run id, launch body).

    ``family`` is `StageGraph`, `GoalDirected` or the FX-TR tag `StageGraphTracing`
    (`technical.TRACING_FAMILY`): the four-stage cycling blueprint, launched as a Stage Graph.
    """

    catalog = stack.catalogs.get(family)
    if catalog is None:
        catalog = await technical.publish_technical_catalog(
            stack.services.control_plane,
            family=family,
            now=datetime.now(UTC),
        )
        stack.catalogs[family] = catalog
    request = technical.admission_request(catalog, str(uuid4())).model_dump(mode="json")
    for input_field in (
        "schema_version",
        "request_scope",
        "idempotency_issuer",
        "actor",
        "requested_at",
        "correlation_id",
        "causation_id",
    ):
        request.pop(input_field, None)
    admission = await stack.http.post(
        f"/v1/applications/{stack.application_id}/run-requests", json=request
    )
    assert admission.status_code == 201, admission.text
    run_id = admission.json()["admission"]["run_id"]
    binding_ref = f"semantic-input:scoped-proof:{run_id}"
    if family in technical.STAGE_FAMILIES:
        await PostgresStageGraphOperationTemplateRepository(stack.pool).persist_templates(
            request_scope=stack.scope,
            semantic_input_binding_ref=binding_ref,
            templates={
                name: value.model_copy(update={"request_scope": stack.scope})
                for name, value in technical.stage_templates(stack.binding, catalog).items()
            },
            recorded_at=datetime.now(UTC),
        )
        family_input = {
            "stagegraph": asdict(technical.stage_input(catalog, run_id, binding_ref, 1))
        }
    else:
        templates = {
            name: value.model_copy(update={"request_scope": stack.scope})
            for name, value in technical.goal_templates(stack.binding, catalog).items()
        }
        await PostgresGoalDirectedDocumentRepository(stack.pool).persist_templates(
            request_scope=stack.scope,
            semantic_input_binding_ref=binding_ref,
            executor=templates["executor"],
            verifier=templates["verifier"],
            recorded_at=datetime.now(UTC),
        )
        family_input = {
            "goal_directed": asdict(
                technical.goal_input(
                    catalog,
                    run_id,
                    binding_ref,
                    1,
                    "Produce one independently verified technical record.",
                )
            )
        }
    # The launch body's family is the workflow family; the FX-TR tag is a fixture selector.
    launch_family = "StageGraph" if family in technical.STAGE_FAMILIES else family
    return run_id, {"family": launch_family, **family_input}


async def admit_and_launch(stack: ScopedStack, family: str) -> tuple[str, str]:
    run_id, body = await prepare_run(stack, family)
    launched = await stack.http.post(
        f"/v1/applications/{stack.application_id}/runs/{run_id}/launch", json=body
    )
    assert launched.status_code == 202, launched.text
    workflow_id = launched.json()["workflow_id"]
    assert workflow_id == mission_root_id(stack.scope, run_id)
    print(f"SCOPED E2E: admitted and launched {family}", flush=True)
    return run_id, workflow_id


@asynccontextmanager
async def serve_loopback(application: FastAPI) -> AsyncIterator[str]:
    """Serve the started application over real HTTP on a free loopback port; yields its URL.

    The stack already entered the application lifespan, so uvicorn serves with ``lifespan="off"``.
    """

    server = uvicorn.Server(
        uvicorn.Config(application, host="127.0.0.1", port=0, lifespan="off", log_level="warning")
    )
    task = asyncio.create_task(server.serve())
    try:
        await until(lambda: _started(server, task), seconds=30)
        port = server.servers[0].sockets[0].getsockname()[1]
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task


async def _started(server: uvicorn.Server, task: asyncio.Task[None]) -> bool:
    if task.done():
        task.result()  # surface a failed bind instead of waiting out the timeout
    return server.started
