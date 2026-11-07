"""Configured scoped API: ``uvicorn mission_control.bootstrap.api:create_app --factory
--loop mission_control.bootstrap.api:api_loop_factory``.

This composition reads deployed identity and migrations; it never creates or upgrades
schemas. The transitional local mode is explicit and does not attest production parity.
On Windows the API runs a ``SelectorEventLoop`` (:func:`api_loop_factory`), as the worker does
(``bootstrap/worker.run_cli``): psycopg's async adapter (the LangGraph saver behind time travel)
cannot open on uvicorn's default ``ProactorEventLoop`` (W1 D3).
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import os
import re
import sys
from collections.abc import AsyncIterator, Mapping
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal, Protocol
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID

import asyncpg
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from mission_control.adapters.auth.jwt import (
    ApplicationAuthentication,
    MissionAuthenticationRejected,
    MissionTokenVerifier,
)
from mission_control.adapters.capabilities.capability_pins import CapabilityPins
from mission_control.adapters.deep_agents.checkpoint_history import LangGraphCheckpointHistoryReader
from mission_control.adapters.deep_agents.compile import deep_agents_lane
from mission_control.adapters.deep_agents.persistence import StandalonePersistenceLifespan
from mission_control.adapters.deep_agents.time_travel import DeepAgentsTimeTravel
from mission_control.adapters.postgres.approvals.context import PostgresApprovalContextProbe
from mission_control.adapters.postgres.approvals.intents import PostgresGovernedIntentRepository
from mission_control.adapters.postgres.approvals.tasks import PostgresApprovalTaskRepository
from mission_control.adapters.postgres.chains.store import PostgresChainReader
from mission_control.adapters.postgres.context.continuation_repository import (
    PostgresCheckpointRepository,
    PostgresContinuationRepository,
)
from mission_control.adapters.postgres.coordinator.workflow_result_repository import (
    PostgresWorkflowResultRepository,
)
from mission_control.adapters.postgres.frames.repository import PostgresFrameRepository
from mission_control.adapters.postgres.frames.transcript_entries import PostgresTranscriptEntries
from mission_control.adapters.postgres.frames.transcript_projection import (
    PostgresRunMissionIds,
    PostgresTranscriptDocuments,
)
from mission_control.adapters.postgres.frames.transcript_reads import (
    PostgresFamilyFactsReader,
    PostgresFrameBodyIndex,
    PostgresMissionEventReader,
)
from mission_control.adapters.postgres.human_tasks.repository import PostgresHumanTaskRepository
from mission_control.adapters.postgres.operations.checkpoint_lineage import (
    PostgresCheckpointLineageRepository,
)
from mission_control.adapters.postgres.operations.cognition_points import (
    PostgresCognitionPointRepository,
)
from mission_control.adapters.postgres.orchestration.completion_evidence import (
    PostgresCompletionEvidenceReader,
)
from mission_control.adapters.postgres.orchestration.goal_completion_evidence import (
    PostgresGoalCompletionEvidenceReader,
)
from mission_control.adapters.postgres.orchestration.native_inputs import PostgresNativeInputReader
from mission_control.adapters.postgres.orchestration.orchestration_binding_repository import (
    PostgresRunSemanticInputBindingRepository,
)
from mission_control.adapters.postgres.run_control.stop_fence import PostgresStopFenceRepository
from mission_control.adapters.postgres.subscriptions.store import PostgresSubscriptionStore
from mission_control.adapters.postgres.workspace_closures import PostgresWorkspaceClosures
from mission_control.adapters.postgres.workspaces.artifact_metadata_repository import (
    PostgresArtifactMetadataRepository,
)
from mission_control.adapters.realtime.stream_source import PostgresStreamSource
from mission_control.adapters.storage.control_plane_payloads import UnavailablePayloadStore
from mission_control.adapters.temporal.activities.fork_seed import TemporalForkSeedRunner
from mission_control.adapters.temporal.boundary_commands import TemporalBoundaryCommandTransport
from mission_control.adapters.temporal.client import connect_temporal, resolve_temporal_connection
from mission_control.adapters.temporal.closed_workflow import TemporalClosedWorkflowObserver
from mission_control.adapters.temporal.coordinator_runtime import coordinator_task_queues
from mission_control.adapters.temporal.human_gate_wake import TemporalHumanGateWake
from mission_control.adapters.temporal.native_inputs import TemporalNativeInputBinding
from mission_control.adapters.temporal.registration.task_queues import (
    maintenance_task_queue,
    watchers_task_queue,
)
from mission_control.adapters.temporal.search_attributes import verify_belllabs_search_attributes
from mission_control.adapters.temporal.submission import TemporalWorkflowSubmitter
from mission_control.adapters.temporal.unit_reconciliation import TemporalUnitReconciliationNudge
from mission_control.adapters.temporal.visibility import TemporalRunVisibility
from mission_control.adapters.temporal.watcher_starter import TemporalWatcherStarter
from mission_control.application.artifacts.artifact_promotion import ArtifactPayloadAddress
from mission_control.application.capabilities.catalog import CatalogService
from mission_control.application.chains.service import ChainInspectionService
from mission_control.application.context.continuation import CheckpointReadService
from mission_control.application.execution.approvals_governed import (
    GovernedEffectService,
    GovernedToolRegistry,
)
from mission_control.application.execution.cognition_point_reads import CognitionPointReadService
from mission_control.application.execution.harness.time_travel import TimeTravelRegistry
from mission_control.application.execution.operations.point_reconciliation import (
    PointReconciler,
)
from mission_control.application.execution.service import (
    AdmissionPolicyRegistry,
    FamilyAdmissionRegistry,
)
from mission_control.application.frames.artifact_bodies import (
    ArtifactPayloadReader,
    ContentAddressedPayloadReader,
    GrantedArtifactBodyReader,
)
from mission_control.application.frames.replay import ReplayService
from mission_control.application.frames.search import RunListService, TranscriptSearchService
from mission_control.application.frames.sink import FrameReader
from mission_control.application.frames.transcript import TranscriptService
from mission_control.application.human_tasks.service import HumanTaskService
from mission_control.application.installations.registry import (
    ApplicationRegistry,
    VerifiedApplicationIdentity,
    request_scope,
)
from mission_control.application.missions.retrieval import RunEvidenceService
from mission_control.application.ports.payloads import ContentAddressedPayloadStore
from mission_control.application.recovery.run_forks import ForkPatchPolicyRegistry
from mission_control.application.streams.service import MissionStreamService
from mission_control.bootstrap.application_profiles import (
    compose_application_registry,
    require_selected_application,
)
from mission_control.bootstrap.catalog import (
    compose_catalog_service,
    configured_catalog_embeddings,
)
from mission_control.bootstrap.composition import (
    MissionApplicationServices,
    compose_application_services,
    compose_knowledge_review,
    temporal_cluster_identity,
)
from mission_control.bootstrap.lanes import (
    SESSION_LANES,
    describe_only_registry,
    settings_bound_lanes,
)
from mission_control.bootstrap.manifests import (
    compose_manifest_launch_inputs,
    compose_manifest_service,
)
from mission_control.bootstrap.model_profiles import compose_model_catalog
from mission_control.bootstrap.selection import compose_selection_workspace
from mission_control.bootstrap.session_time_travel import session_lane_time_travel
from mission_control.bootstrap.settings import get_settings
from mission_control.bootstrap.signals import compose_signal_ingress, verify_signal_ingress_pool
from mission_control.bootstrap.subscriptions import (
    InboxComposition,
    compose_coordinator_inbox_service,
    compose_output_inspection_service,
    compose_subscription_service,
    relay_enabled,
    run_subscription_relays,
)
from mission_control.contracts.identities import parse_request_scope
from mission_control.contracts.json import parse_json_object
from mission_control.domain.authoring.extensions import ExtensionRegistry
from mission_control.domain.context.refs import parse_durable_input_locator
from mission_control.domain.frames.contracts import ProviderFrame
from mission_control.interfaces.http.artifacts import router as artifacts_router
from mission_control.interfaces.http.catalog import router as catalog_router
from mission_control.interfaces.http.chains import router as chains_router
from mission_control.interfaces.http.cognition_points import router as cognition_points_router
from mission_control.interfaces.http.continuation import router as continuation_router
from mission_control.interfaces.http.coordinator_inbox import router as coordinator_inbox_router
from mission_control.interfaces.http.human_tasks import router as human_tasks_router
from mission_control.interfaces.http.ingress import router as ingress_router
from mission_control.interfaces.http.knowledge_reviews import router as knowledge_reviews_router
from mission_control.interfaces.http.lanes import router as lanes_router
from mission_control.interfaces.http.middleware.body_limit import BodySizeLimitMiddleware
from mission_control.interfaces.http.mission_control import (
    MissionPrincipal,
    get_mission_principal,
    router,
)
from mission_control.interfaces.http.missions import router as missions_router
from mission_control.interfaces.http.models import router as models_router
from mission_control.interfaces.http.output_inspection import router as output_inspection_router
from mission_control.interfaces.http.run_evidence import router as run_evidence_router
from mission_control.interfaces.http.selection import router as selection_router
from mission_control.interfaces.http.stop_fence import router as stop_fence_router
from mission_control.interfaces.http.subscriptions import router as subscriptions_router
from mission_control.interfaces.http.transcript import router as transcript_router
from mission_control.interfaces.mcp.operator_server import (
    OPERATOR_MCP_PATH,
    BearerAuthenticator,
    BearerPrincipalGate,
    create_operator_server,
)
from mission_control.interfaces.mcp.signal_tools import mount_signal_tools

STAGEGRAPH_QUEUE_SUFFIX = "-coordinator-family-stagegraph"


class TaskQueueConventionError(ValueError):
    """A deployment's family queues do not share one qualified base (fail closed)."""


class TemporalDeployment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    address: str = Field(min_length=1)
    namespace: str = Field(min_length=1)
    root_task_queue: str = Field(min_length=1)
    stagegraph_task_queue: str = Field(min_length=1)
    goal_directed_task_queue: str = Field(min_length=1)

    @property
    def queue_base(self) -> str:
        """The installation's Temporal queue base, the one source the API and the worker derive
        the coordinator, maintenance and artifact queues from (OC-R4 review B2)."""

        if not self.stagegraph_task_queue.endswith(STAGEGRAPH_QUEUE_SUFFIX):
            raise TaskQueueConventionError(
                "stagegraph queue must use the qualified family queue convention"
            )
        base = self.stagegraph_task_queue.removesuffix(STAGEGRAPH_QUEUE_SUFFIX)
        if self.goal_directed_task_queue != coordinator_task_queues(base).goal_directed:
            raise TaskQueueConventionError(
                "worker family task queues do not share the configured application base"
            )
        return base


class ApplicationDeployment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    authentication: ApplicationAuthentication
    family_writer_secret_ref: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]*$")
    signal_ingress_secret_ref: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]*$")
    temporal: TemporalDeployment | None = None


class MissionDeployment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    storage_mode: Literal["production_common"]
    applications: tuple[ApplicationDeployment, ...] = Field(min_length=1)
    max_request_bytes: int = Field(ge=1, le=16_000_000)

    @model_validator(mode="after")
    def unique_applications(self) -> MissionDeployment:
        ids = [item.authentication.binding.application_id for item in self.applications]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate application deployment")
        return self


def require_queue_agreement(installation_base: str, settings_queue: str | None) -> None:
    """OC-R4 re-review 3: where a process has both the installation's queue base and a
    settings queue (`TEMPORAL_TASK_QUEUE` or the selected profile's), they must agree; the
    installation is the source, a different settings value is a typed startup error."""

    if settings_queue is not None and settings_queue != installation_base:
        raise TaskQueueConventionError(
            f"TEMPORAL_TASK_QUEUE (or the selected profile) names {settings_queue}, but the "
            f"installation's queue base is {installation_base}; unset it or make them agree"
        )


def verify_deployment_selection(
    deployment: MissionDeployment, selected: str | None, settings_queue: str | None = None
) -> None:
    """OC-R4 review B2, before the API starts anything: a selected application profile
    (`MISSION_CONTROL_APPLICATION`) is a composed binding's own, every installation's queue
    base follows the worker's convention (the API derives its queues from it), and a settings
    queue in the same process agrees with it."""

    for item in deployment.applications:
        require_selected_application(selected, item.authentication.binding.application_id)
        if item.temporal is not None:
            require_queue_agreement(item.temporal.queue_base, settings_queue)


class CatalogFactory(Protocol):
    def __call__(
        self,
        pool: asyncpg.Pool,
        *,
        request_scope: str,
        catalog_scope: str,
    ) -> CatalogService: ...


@dataclass(frozen=True)
class RuntimeOptions:
    """Trusted Python composition extensions; never populated from request bodies."""

    admission_policies: AdmissionPolicyRegistry
    extensions: ExtensionRegistry
    payload_store: ContentAddressedPayloadStore
    family_admissions: FamilyAdmissionRegistry | None = None
    fork_policies: ForkPatchPolicyRegistry | None = None
    catalog_factory: CatalogFactory | None = None
    # MP-13: the artifact payload store the transcript's `full=true` reads bodies from. The API
    # has no payload store composed by default; unset keeps `501 full_body_unavailable`.
    artifact_payloads: ContentAddressedPayloadReader | None = None
    # MP-11: the Mission-Control-owned effect tools the governed gateway may run (trusted
    # Python composition; none by default, so the gateway governs nothing).
    governed_tools: GovernedToolRegistry | None = None


def bearer_authenticator(verifier: MissionTokenVerifier) -> BearerAuthenticator:
    """The one bearer verification behind the HTTP routes and the operator MCP mount."""

    def authenticate(
        application_id: str,
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    ) -> MissionPrincipal:
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise HTTPException(status_code=401, detail={"code": "bearer_token_required"})
        try:
            authenticated = verifier.authenticate(application_id, token)
        except MissionAuthenticationRejected as error:
            raise HTTPException(
                status_code=error.status_code, detail={"code": error.code}
            ) from None
        identity = authenticated.identity
        return MissionPrincipal(
            installation_id=identity.installation_id,
            application_id=identity.application_id,
            tenant_id=identity.tenant_id,
            issuer=identity.issuer,
            audiences=identity.audiences,
            actor=authenticated.actor,
            sponsorship_refs=authenticated.sponsorship_refs,
            approval_refs=authenticated.approval_refs,
        )

    return authenticate


def install_authentication(application: FastAPI, verifier: MissionTokenVerifier) -> None:
    application.dependency_overrides[get_mission_principal] = bearer_authenticator(verifier)


LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
TLS_MODES = frozenset({"require", "verify-ca", "verify-full"})


async def application_pool(secret_ref: str) -> asyncpg.Pool:
    """Open an app-bound restricted pool; remote endpoints must require TLS."""
    dsn = os.environ.get(secret_ref)
    if not dsn:
        raise RuntimeError("configured database credential reference is unavailable")
    parsed = urlsplit(dsn)
    query = dict(parse_qsl(parsed.query))
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname:
        raise RuntimeError("configured database credential is not a PostgreSQL endpoint")
    if parsed.hostname not in LOOPBACK_HOSTS and query.get("sslmode") not in TLS_MODES:
        raise RuntimeError("remote PostgreSQL endpoints must require TLS")
    if "options" in query:
        raise RuntimeError("application pools cannot override server options")
    try:
        return await asyncpg.create_pool(
            dsn=dsn,
            min_size=1,
            max_size=8,
            command_timeout=30,
            server_settings={"statement_timeout": "30000", "lock_timeout": "10000"},
            # Loop iter-3 F1-G7: the Supabase pooler drops idle client connections sooner than
            # asyncpg's 300 s default; a reused one was reset mid-write. Recycle idle ones.
            max_inactive_connection_lifetime=60,
        )
    except Exception:
        raise RuntimeError("configured PostgreSQL connection is unavailable") from None


async def coordinator_inbox_installed(pool: asyncpg.Pool) -> bool:
    """Whether the application database has the MP-15 inbox tables (release 1.2.0, 0033)."""

    async with pool.acquire() as connection:
        return bool(
            await connection.fetchval(
                "SELECT to_regclass('mission_control.coordinator_inbox') IS NOT NULL"
            )
        )


async def _stop_relay(stop: asyncio.Event, task: asyncio.Task[None]) -> None:
    stop.set()
    await task


logger = logging.getLogger(__name__)


def api_loop_factory() -> asyncio.AbstractEventLoop:
    """The API process's event loop (uvicorn ``--loop`` with this callable's import path).

    Psycopg's asynchronous adapter requires a selector loop on Windows (the worker's rule,
    ``bootstrap/worker.run_cli``); elsewhere uvicorn's own ``auto`` choice stands.
    """

    if sys.platform == "win32":
        return asyncio.SelectorEventLoop()
    from uvicorn.loops.auto import auto_loop_factory

    return auto_loop_factory(use_subprocess=False)()


def _proactor_loop() -> bool:
    """Whether this process runs on a Windows ``ProactorEventLoop`` (psycopg async refuses)."""

    proactor = getattr(asyncio, "ProactorEventLoop", None)
    return proactor is not None and isinstance(asyncio.get_running_loop(), proactor)


class PayloadSnapshotReader:
    """K3: the API's read-only view of an application's artifact payloads as a snapshot
    byte source (`retrieve` by durable locator, as `PayloadContextFiles` does; no `stage`:
    seeds are staged on the maintenance worker, never on the API request thread)."""

    def __init__(self, payloads: ArtifactPayloadReader) -> None:
        self._payloads = payloads

    async def retrieve(self, durable_ref: str) -> bytes:
        object_ref, digest, size = parse_durable_input_locator(durable_ref)
        return await self._payloads.retrieve(
            ArtifactPayloadAddress(object_ref=object_ref, content_digest=digest, size_bytes=size)
        )


class ApplicationFrameReaders:
    """K3 (2026-11-05): one `FrameReader` over every configured application's pool, routed
    by the request scope's application id (the time-travel registry is process-wide, the
    frame store per application). `snapshots_for` is the same route to the application's
    snapshot byte store (its artifact payloads), for the Cursor R2 reads."""

    def __init__(self) -> None:
        self._frames: dict[str, FrameReader] = {}
        self._snapshots: dict[str, Any] = {}

    def register(self, application_id: str, frames: FrameReader, *, snapshots: Any = None) -> None:
        self._frames[application_id] = frames
        if snapshots is not None:
            self._snapshots[application_id] = snapshots

    @staticmethod
    def _application(request_scope: str) -> str | None:
        try:
            return parse_request_scope(request_scope).application_id
        except ValueError:
            return None

    def _reader(self, request_scope: str) -> FrameReader | None:
        application_id = self._application(request_scope)
        return self._frames.get(application_id) if application_id is not None else None

    def snapshots_for(self, request_scope: str) -> Any:
        application_id = self._application(request_scope)
        return self._snapshots.get(application_id) if application_id is not None else None

    async def frames_for_execution(
        self,
        request_scope: str,
        harness_execution_id: UUID,
        generation: int,
        *,
        after_ordinal: int = 0,
        closing_only: bool = False,
        limit: int = 1_000,
    ) -> tuple[ProviderFrame, ...]:
        reader = self._reader(request_scope)
        if reader is None:
            return ()
        return await reader.frames_for_execution(
            request_scope,
            harness_execution_id,
            generation,
            after_ordinal=after_ordinal,
            closing_only=closing_only,
            limit=limit,
        )

    async def frames_for_run(
        self,
        request_scope: str,
        run_id: UUID,
        *,
        closing_only: bool = False,
        limit: int = 10_000,
    ) -> tuple[ProviderFrame, ...]:
        reader = self._reader(request_scope)
        if reader is None:
            return ()
        return await reader.frames_for_run(
            request_scope, run_id, closing_only=closing_only, limit=limit
        )

    async def current_generation(
        self, request_scope: str, harness_execution_id: UUID
    ) -> int | None:
        reader = self._reader(request_scope)
        if reader is None:
            return None
        return await reader.current_generation(request_scope, harness_execution_id)


async def compose_time_travel(application: FastAPI, settings: Any, stack: AsyncExitStack) -> None:
    """Attach `app.state.time_travel_registry` (and the inspection checkpoint reader when
    absent) over the pinned savers; a missing or unreachable runtime DSN leaves the Deep
    Agents lane out (its `state-as-of` answers 501). K3 (2026-11-05): every Session Lane's
    time travel registers beside it over `app.state.mission_control_frame_readers`, which
    the per-application lifespan fills with each application's frame repository and
    snapshot store (`ApplicationFrameReaders.register`)."""

    dsn = getattr(settings, "langgraph_checkpoint_dsn", None)
    if dsn and _proactor_loop():
        logger.error(
            "time travel is unavailable: the API runs a ProactorEventLoop; start uvicorn with "
            "--loop mission_control.bootstrap.api:api_loop_factory"
        )
        return
    registry = TimeTravelRegistry()
    if dsn:
        try:
            persistence = await stack.enter_async_context(StandalonePersistenceLifespan(dsn))
            pins = CapabilityPins.from_settings(settings)
            checkpointers = {item.ref.digest: persistence.saver for item in pins.checkpointers}
        except Exception:
            logger.exception("time travel is unavailable: the runtime persistence did not open")
        else:
            registry.register(
                DeepAgentsTimeTravel(
                    checkpointers,
                    locators={
                        digest: persistence.locator_digest
                        for digest in checkpointers
                        if persistence.locator_digest
                    },
                )
            )
            if getattr(application.state, "inspection_checkpoint_reader", None) is None:
                application.state.inspection_checkpoint_reader = LangGraphCheckpointHistoryReader(
                    checkpointers
                )
    readers = ApplicationFrameReaders()
    application.state.mission_control_frame_readers = readers
    registry.register_all(session_lane_time_travel(readers, snapshots=readers.snapshots_for))
    application.state.time_travel_registry = registry


def create_application(
    deployment: MissionDeployment,
    *,
    runtime_options: Mapping[str, RuntimeOptions] | None = None,
) -> FastAPI:
    deployment = MissionDeployment.model_validate(deployment.model_dump(mode="python"))
    if deployment.storage_mode != "production_common":
        raise RuntimeError("only the common Mission Control component is supported")
    configs = tuple(item.authentication for item in deployment.applications)
    verifier = MissionTokenVerifier(configs)
    registry = ApplicationRegistry(tuple(config.binding for config in configs))
    options_by_app = dict(runtime_options or {})
    allowed_applications = {item.binding.application_id for item in configs}
    if set(options_by_app) - allowed_applications or any(
        not isinstance(value, RuntimeOptions) for value in options_by_app.values()
    ):
        raise ValueError(
            "runtime options must name configured applications and typed RuntimeOptions"
        )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        verify_deployment_selection(
            deployment,
            get_settings().mission_control_application,
            get_settings().temporal_task_queue,
        )
        catalog_embeddings = configured_catalog_embeddings(get_settings())
        async with AsyncExitStack() as stack:
            # P1 turn 4: `state-as-of` reads a point's graph state from the registered saver,
            # so the operator API opens the runtime persistence the worker uses when its DSN
            # is configured; without it the time-travel registry stays empty (501).
            await compose_time_travel(application, get_settings(), stack)
            subscription_stores: list[PostgresSubscriptionStore] = []
            inbox_compositions: list[InboxComposition] = []
            try:
                for item in deployment.applications:
                    config = item.authentication
                    binding = config.binding
                    # OC-R6: the application's Model Catalog for the model listing (fails
                    # closed on a missing or invalid `deployments/<app>/models.toml`).
                    application.state.mission_control_model_catalogs[binding.application_id] = (
                        compose_model_catalog(
                            get_settings().deployments_root, binding.application_id
                        )
                    )
                    pool = await application_pool(binding.database_secret_ref)
                    stack.push_async_callback(pool.close)
                    if item.signal_ingress_secret_ref is not None:
                        ingress_pool = await application_pool(item.signal_ingress_secret_ref)
                        stack.push_async_callback(ingress_pool.close)
                        await verify_signal_ingress_pool(ingress_pool)
                        application.state.mission_control_ingress[binding.application_id] = (
                            compose_signal_ingress(
                                ingress_pool,
                                installation_id=binding.installation_id,
                                application_id=binding.application_id,
                            )
                        )
                    # MP-15: the coordinator inbox needs release 1.2.0 (migration 0033); an
                    # application database on an older release keeps every other service.
                    inbox_installed = await coordinator_inbox_installed(pool)
                    family_pool = None
                    if item.family_writer_secret_ref is not None:
                        family_pool = await application_pool(item.family_writer_secret_ref)
                        stack.push_async_callback(family_pool.close)
                    options = options_by_app.get(binding.application_id) or RuntimeOptions(
                        AdmissionPolicyRegistry(),
                        ExtensionRegistry(),
                        UnavailablePayloadStore(),
                    )
                    # K3: the session lanes' time travel reads this application's frames
                    # (and, for Cursor R2, its snapshot bytes) under the caller's scope.
                    frame_readers = getattr(
                        application.state, "mission_control_frame_readers", None
                    )
                    if isinstance(frame_readers, ApplicationFrameReaders):
                        frame_readers.register(
                            binding.application_id,
                            PostgresFrameRepository(pool),
                            snapshots=(
                                PayloadSnapshotReader(options.artifact_payloads)
                                if options.artifact_payloads is not None
                                else None
                            ),
                        )
                    transport = submitter = nudge = None
                    closed_workflow_observer = None
                    run_visibility: TemporalRunVisibility | None = None
                    gate_wake: TemporalHumanGateWake | None = None
                    watcher_starter: TemporalWatcherStarter | None = None
                    cluster = None
                    if item.temporal is not None:
                        temporal = item.temporal
                        # FT-G7: local server by default; Temporal Cloud only when
                        # TEMPORAL_TARGET=cloud (api key + TLS).
                        connection = resolve_temporal_connection(
                            get_settings(), address=temporal.address, namespace=temporal.namespace
                        )
                        client = await connect_temporal(connection)
                        await verify_belllabs_search_attributes(
                            client,
                            connection.namespace,
                            **(
                                {"cloud_api_key": connection.api_key}
                                if connection.target == "cloud"
                                else {}
                            ),
                        )
                        transport = TemporalBoundaryCommandTransport(client)
                        # FT-C4: run list over the typed Search Attributes.
                        run_visibility = TemporalRunVisibility(client)
                        nudge = TemporalUnitReconciliationNudge(client)
                        closed_workflow_observer = TemporalClosedWorkflowObserver(client)
                        # MP-10: a committed resolution nudges its waiting Human Gate.
                        gate_wake = TemporalHumanGateWake(client)
                        # MO-44: manifest start launches the run's Watcher Evaluator.
                        watcher_starter = TemporalWatcherStarter(
                            client, task_queue=watchers_task_queue(temporal.root_task_queue)
                        )
                        submitter = TemporalWorkflowSubmitter.for_production(
                            client,
                            root_task_queue=temporal.root_task_queue,
                            stagegraph_task_queue=temporal.stagegraph_task_queue,
                            goal_directed_task_queue=temporal.goal_directed_task_queue,
                            search_attribute_policy="required",
                            mission_installation_id=binding.installation_id,
                            mission_application_id=binding.application_id,
                        )
                        # MP-22: every launch binds the run to this cluster first.
                        cluster = temporal_cluster_identity(
                            target=connection.target,
                            address=temporal.address,
                            namespace=connection.namespace,
                            task_queue=temporal.root_task_queue,
                        )
                    tenants = {tenant for grant in config.grants for tenant in grant.tenant_ids}
                    if not tenants:
                        raise RuntimeError("deployment must grant at least one application tenant")
                    for tenant in tenants:
                        identity = VerifiedApplicationIdentity(
                            issuer=config.issuer,
                            audiences=frozenset({config.audience}),
                            application_id=binding.application_id,
                            installation_id=binding.installation_id,
                            tenant_id=tenant,
                        )
                        services = await compose_application_services(
                            binding,
                            identity,
                            runtime_pool=pool,
                            admission_policies=options.admission_policies,
                            extensions=options.extensions,
                            payload_store=options.payload_store,
                            storage_mode="production_common",
                            registry=registry,
                            family_writer_pool=family_pool,
                            family_admissions=options.family_admissions,
                            fork_policies=options.fork_policies,
                            boundary_transport=transport,
                            submitter=submitter,
                            nudge=nudge,
                            closed_workflow_observer=closed_workflow_observer,
                            artifact_payloads=options.artifact_payloads,
                            externalize_above_bytes=15_000_000,
                            cluster=cluster,
                            time_travel=lambda: getattr(
                                application.state, "time_travel_registry", None
                            ),
                            # 1.4.4 (P6.1): the seed copy on the worker's maintenance queue.
                            # OC-R4 review B2: the installation's queue base (the worker's
                            # source), never a settings default.
                            fork_seed_runner=None
                            if item.temporal is None
                            else TemporalForkSeedRunner(
                                client,
                                task_queue=maintenance_task_queue(item.temporal.queue_base),
                            ),
                        )
                        key = (binding.installation_id, binding.application_id, tenant)
                        application.state.mission_control_services[key] = services.lifecycle
                        application.state.mission_control_runtime_services[key] = services.runtime
                        application.state.mission_control_admission_services[key] = (
                            services.admission
                        )
                        application.state.mission_control_compositions[key] = services
                        catalog_scope = (
                            f"mc/{binding.installation_id}/{binding.application_id}/catalog"
                        )
                        if options.catalog_factory is not None:
                            catalog = options.catalog_factory(
                                pool,
                                request_scope=request_scope(identity),
                                catalog_scope=catalog_scope,
                            )
                        else:
                            # FT-A3: lexical search always; hybrid when the embedding
                            # Model Profile and its credential are configured.
                            catalog = compose_catalog_service(
                                pool,
                                request_scope=request_scope(identity),
                                catalog_scope=catalog_scope,
                                embeddings=catalog_embeddings,
                            )
                        if (
                            catalog.request_scope != request_scope(identity)
                            or catalog.catalog_scope
                            != f"mc/{binding.installation_id}/{binding.application_id}/catalog"
                        ):
                            raise RuntimeError(
                                "catalog composition differs from authenticated scope"
                            )
                        application.state.mission_control_catalog_services[key] = catalog
                        # The Selection Workspace: one search and one read-only draft check
                        # over this catalog, the describe-only lanes and the application's
                        # Model Catalog and Application Profile (admission is the seam's own).
                        application.state.mission_control_selection_workspaces[key] = (
                            compose_selection_workspace(
                                application_id=binding.application_id,
                                lanes=application.state.mission_control_lanes,
                                models=application.state.mission_control_model_catalogs[
                                    binding.application_id
                                ],
                                applications=compose_application_registry(
                                    get_settings().deployments_root, (binding.application_id,)
                                ),
                                catalog=catalog,
                            )
                        )
                        # SPEC-03 (C3): the run transcript, read under the tenant scope.
                        transcripts = TranscriptService(
                            PostgresMissionEventReader(pool),
                            PostgresFrameRepository(pool),
                            request_scope=request_scope(identity),
                            # 1.4.4: entries are placed by unit and point (P3.2); the
                            # persisted projection answers when current (TR-D10).
                            points=PostgresCognitionPointRepository(pool),
                            entry_store=PostgresTranscriptEntries(pool),
                            family_facts=PostgresFamilyFactsReader(pool),
                        )
                        application.state.mission_control_transcript_services[key] = transcripts
                        # MP-13: full artifact bodies, read under the same scope and the
                        # `workflow.result.read` grant; only when a payload store is composed.
                        body_reader = (
                            GrantedArtifactBodyReader(
                                PostgresArtifactMetadataRepository(
                                    pool, request_scope=request_scope(identity)
                                ),
                                options.artifact_payloads,
                                request_scope=request_scope(identity),
                                # Tracing Stage 3 (R4-F6): a `frame-body://` download is
                                # served only for a digest a frame of the path's run holds.
                                frames=PostgresFrameBodyIndex(pool),
                                # OVE-204 slice 5: a `closure-body://` download is served
                                # only for a promoted body of the path run's closures.
                                closures=PostgresWorkspaceClosures(pool),
                            )
                            if options.artifact_payloads is not None
                            else None
                        )
                        # P1 turn 4: the cognition point index, read under the tenant scope;
                        # 1.4.4 (WP-TR-3): with the frame reader (frames by point) and the
                        # granted body reader (replay) composed beside it.
                        point_reads = CognitionPointReadService(
                            PostgresCognitionPointRepository(pool),
                            request_scope=request_scope(identity),
                            frames=PostgresFrameRepository(pool),
                            artifacts=body_reader,
                            # OVE-204 slice 5: the run's Workspace Closures.
                            closures=PostgresWorkspaceClosures(pool),
                        )
                        application.state.mission_control_cognition_point_services[key] = (
                            point_reads
                        )
                        application.state.mission_control_replay_services[key] = ReplayService(
                            point_reads, artifacts=body_reader
                        )
                        # 1.4.4 (TR-D6): the point reconciler lives where the saver is
                        # (`compose_time_travel` above); without a registry every unit
                        # it checks is reported `saver_unreachable`, never raised.
                        application.state.mission_control_point_reconcilers[key] = PointReconciler(
                            lineage=PostgresCheckpointLineageRepository(pool),
                            points=PostgresCognitionPointRepository(pool),
                            time_travel=lambda: getattr(
                                application.state, "time_travel_registry", None
                            ),
                            frames=PostgresFrameRepository(pool),
                            runs=PostgresMissionEventReader(pool),
                        )
                        application.state.mission_control_evidence_services[key] = (
                            RunEvidenceService(
                                services.lifecycle,
                                bindings=PostgresRunSemanticInputBindingRepository(pool),
                                native_inputs=(
                                    PostgresNativeInputReader(
                                        pool, TemporalNativeInputBinding(client)
                                    )
                                    if item.temporal is not None
                                    else None
                                ),
                                goal_completion=PostgresGoalCompletionEvidenceReader(pool),
                                results=PostgresWorkflowResultRepository(pool),
                                checkpoints=CheckpointReadService(
                                    PostgresCheckpointRepository(pool),
                                    PostgresContinuationRepository(pool),
                                    request_scope=request_scope(identity),
                                ),
                                mission_ids=PostgresRunMissionIds(pool),
                                completion=PostgresCompletionEvidenceReader(pool),
                                closures=PostgresWorkspaceClosures(pool),
                            )
                        )
                        if body_reader is not None:
                            application.state.mission_control_artifact_body_readers[key] = (
                                body_reader
                            )
                        # SPEC-03 (C4): run list (Temporal Visibility + ledger) and search.
                        application.state.mission_control_run_list_services[key] = RunListService(
                            run_visibility,
                            services.run_control,
                            request_scope=request_scope(identity),
                        )
                        application.state.mission_control_transcript_search_services[key] = (
                            TranscriptSearchService(
                                transcripts,
                                PostgresTranscriptDocuments(pool),
                                entries=PostgresTranscriptEntries(pool),
                            )
                        )
                        # SPEC-02 (B4): sealed continuation checkpoints, read under scope.
                        application.state.mission_control_checkpoint_services[key] = (
                            CheckpointReadService(
                                PostgresCheckpointRepository(pool),
                                PostgresContinuationRepository(pool),
                                request_scope=request_scope(identity),
                            )
                        )
                        # WI-19: exact output, fulfillment and transfer inspection (read-only).
                        application.state.mission_control_output_inspection_services[key] = (
                            compose_output_inspection_service(pool, request_scope(identity))
                        )
                        # W1 D2: the operator review route over the KS review path (only
                        # with a configured knowledge binding).
                        knowledge_review = await compose_knowledge_review(
                            get_settings(),
                            pool,
                            application_id=binding.application_id,
                            installation_id=str(binding.installation_id),
                            request_scope=request_scope(identity),
                        )
                        if knowledge_review is not None:
                            application.state.mission_control_knowledge_review_services[key] = (
                                knowledge_review
                            )
                        subscriptions = compose_subscription_service(pool, request_scope(identity))
                        application.state.mission_control_subscription_services[key] = subscriptions
                        mailbox_semantics = (
                            services.mailbox.semantics if services.mailbox is not None else None
                        )
                        if inbox_installed:
                            # MP-15 (SPEC-04): the durable coordinator inbox; prompts go through
                            # this tenant's MissionControlService and its mailbox semantics.
                            application.state.mission_control_coordinator_inbox_services[key] = (
                                compose_coordinator_inbox_service(
                                    pool,
                                    request_scope(identity),
                                    commands=services.lifecycle,
                                    mailbox_semantics=mailbox_semantics,
                                )
                            )
                            inbox_compositions.append(
                                (
                                    pool,
                                    request_scope(identity),
                                    services.lifecycle,
                                    mailbox_semantics,
                                )
                            )
                        # MP-10 (SPEC-03): Human Gate tasks under the tenant scope; HTTP, MCP
                        # and the socket resolve through this one service. MP-11: approval-
                        # origin tasks (provider permission/question, MCP elicitation,
                        # governed effect) share it and its one resolution path; their waiters
                        # live in the worker's broker, which re-reads the task (no wake here).
                        approval_tasks = PostgresApprovalTaskRepository(pool)
                        application.state.mission_control_human_task_services[key] = (
                            HumanTaskService(
                                PostgresHumanTaskRepository(pool),
                                request_scope=request_scope(identity),
                                wake=gate_wake,
                                approvals=approval_tasks,
                            )
                        )
                        # MP-11: prepare/review/execute for Mission-Control-owned tools.
                        application.state.mission_control_governed_effect_services[key] = (
                            GovernedEffectService(
                                PostgresGovernedIntentRepository(pool),
                                approval_tasks,
                                options.governed_tools or GovernedToolRegistry(),
                                request_scope=request_scope(identity),
                                probe=PostgresApprovalContextProbe(pool),
                                fences=PostgresStopFenceRepository(pool),
                            )
                        )
                        # MP-14 (SPEC-04): scoped mission/frame streams for the /missions
                        # socket; replay reads PostgreSQL only (`bootstrap/realtime.py`).
                        application.state.mission_control_stream_services[key] = (
                            MissionStreamService(
                                PostgresStreamSource(pool, request_scope(identity)),
                                request_scope=request_scope(identity),
                            )
                        )
                        # FT-E2/E3: Mission Manifest compile, submit and start for the tenant;
                        # MP-02: start authors the launch inputs from the deployment bindings.
                        launch_inputs = (
                            compose_manifest_launch_inputs(
                                pool,
                                settings=get_settings(),
                                application_id=binding.application_id,
                                run_control=services.run_control,
                                control_plane=services.control_plane,
                            )
                            if services.launch is not None
                            else None
                        )
                        application.state.mission_control_manifest_services[key] = (
                            compose_manifest_service(
                                pool,
                                application_binding=binding,
                                settings=get_settings(),
                                request_scope=request_scope(identity),
                                catalog=catalog,
                                extensions=options.extensions,
                                payload_store=options.payload_store,
                                run_control=services.run_control,
                                admission_policies=options.admission_policies,
                                launches=services.launch,
                                subscriptions=subscriptions,
                                launch_inputs=launch_inputs,
                                data_class_policy=binding.data_class_policy,
                                watchers=watcher_starter,
                                placement_lanes=application.state.mission_control_lanes,
                            )
                        )
                        # FT-D2: the Mission Chain projection, read under the tenant scope.
                        application.state.mission_control_chain_services[key] = (
                            ChainInspectionService(
                                PostgresChainReader(pool), request_scope=request_scope(identity)
                            )
                        )
                        subscription_stores.append(
                            PostgresSubscriptionStore(pool, request_scope(identity))
                        )
                if subscription_stores and relay_enabled():
                    relay_stop = asyncio.Event()
                    relay_task = asyncio.create_task(
                        run_subscription_relays(
                            subscription_stores, relay_stop, inboxes=inbox_compositions
                        )
                    )
                    stack.push_async_callback(_stop_relay, relay_stop, relay_task)
                # SPEC-04 §6 (MO-43): the authenticated operator MCP over these services.
                signal_mcp = mount_signal_tools(
                    application, application.state.mission_control_ingress.values()
                )
                await stack.enter_async_context(signal_mcp.router.lifespan_context(signal_mcp))
                stack.callback(application.router.routes.remove, application.router.routes[-1])
                operator_mcp = create_operator_server(application.state).http_app(
                    path="/", transport="streamable-http", stateless_http=True, json_response=True
                )
                await stack.enter_async_context(operator_mcp.router.lifespan_context(operator_mcp))
                application.mount(
                    OPERATOR_MCP_PATH,
                    BearerPrincipalGate(operator_mcp, bearer_authenticator(verifier)),
                )
                stack.callback(application.router.routes.remove, application.router.routes[-1])
                application.state.mission_control_ready = True
                yield
            finally:
                application.state.mission_control_ready = False
                for config in configs:
                    registry.disable(config.binding.application_id)

    application = FastAPI(title="Mission Control", lifespan=lifespan)
    application.add_middleware(BodySizeLimitMiddleware, max_bytes=deployment.max_request_bytes)
    application.state.mission_control_registry = registry
    application.state.mission_control_services = {}
    application.state.mission_control_ingress = {}
    application.state.mission_control_runtime_services = {}
    application.state.mission_control_admission_services = {}
    application.state.mission_control_catalog_services = {}
    application.state.mission_control_transcript_services = {}
    application.state.mission_control_cognition_point_services = {}
    application.state.mission_control_point_reconcilers = {}
    application.state.mission_control_replay_services = {}
    application.state.mission_control_evidence_services = {}
    application.state.mission_control_artifact_body_readers = {}
    application.state.mission_control_checkpoint_services = {}
    application.state.mission_control_run_list_services = {}
    application.state.mission_control_transcript_search_services = {}
    application.state.mission_control_subscription_services = {}
    application.state.mission_control_coordinator_inbox_services = {}
    application.state.mission_control_output_inspection_services = {}
    application.state.mission_control_knowledge_review_services = {}
    application.state.mission_control_human_task_services = {}
    application.state.mission_control_governed_effect_services = {}
    application.state.mission_control_stream_services = {}
    application.state.mission_control_chain_services = {}
    application.state.mission_control_manifest_services = {}
    application.state.mission_control_model_catalogs = {}
    application.state.mission_control_selection_workspaces = {}
    application.state.mission_control_compositions = {}
    application.state.mission_control_ready = False
    # FT-G1: the API lists and describes lanes; workers execute them.
    lane_settings = get_settings()
    application.state.mission_control_lanes = describe_only_registry(
        bound=settings_bound_lanes(lane_settings),
        allow_unqualified=lane_settings.allow_unqualified_lanes,
        # OC-R6: the package registrations whose declared model routes the listing reads; this
        # process compiles nothing, so the Deep Agents lane carries no deployment facts. OC-R3:
        # every other lane package too (`bootstrap/lanes.SESSION_LANES`); the registry keeps
        # only the lanes this installation binds (unbound ones are absent and `unbound`).
        registrations=(deep_agents_lane(None), *SESSION_LANES.values()),
    )
    install_authentication(application, verifier)
    application.include_router(router)
    application.include_router(ingress_router)
    application.include_router(catalog_router)
    application.include_router(lanes_router)
    application.include_router(models_router)
    application.include_router(selection_router)
    application.include_router(stop_fence_router)
    application.include_router(transcript_router)
    application.include_router(cognition_points_router)
    application.include_router(artifacts_router)
    application.include_router(run_evidence_router)
    application.include_router(continuation_router)
    application.include_router(subscriptions_router)
    application.include_router(chains_router)
    application.include_router(missions_router)
    application.include_router(human_tasks_router)
    application.include_router(coordinator_inbox_router)
    application.include_router(output_inspection_router)
    application.include_router(knowledge_reviews_router)

    @application.get("/health/live")
    def live() -> dict[str, bool]:
        return {"live": True}

    @application.get("/health/ready")
    def ready() -> dict[str, object]:
        if not application.state.mission_control_ready:
            raise HTTPException(status_code=503, detail={"code": "installation_unavailable"})
        services: list[MissionApplicationServices] = list(
            application.state.mission_control_compositions.values()
        )
        return {
            "ready": True,
            "storage_mode": "production_common",
            "production_ready": all(item.readiness.production_ready for item in services),
            "component_versions": sorted({item.readiness.component_version for item in services}),
            "launch_configured": all(item.launch is not None for item in services),
        }

    return application


def load_deployment(filename: str | Path | None = None) -> MissionDeployment:
    filename = filename or os.environ.get("MISSION_CONTROL_DEPLOYMENT_FILE")
    if not filename:
        raise RuntimeError("MISSION_CONTROL_DEPLOYMENT_FILE must name an operator deployment file")
    config_path = Path(filename).resolve()
    document = parse_json_object(config_path.read_bytes())
    deployment = MissionDeployment.model_validate(document)
    # Relative public-key paths are relative to the operator configuration, not cwd.
    resolved = []
    for item in deployment.applications:
        auth = item.authentication
        path = auth.public_jwks_file
        if not path.is_absolute():
            auth = auth.model_copy(update={"public_jwks_file": config_path.parent / path})
        resolved.append(item.model_copy(update={"authentication": auth}))
    return deployment.model_copy(update={"applications": tuple(resolved)})


def create_app() -> FastAPI:
    deployment = load_deployment()
    return create_application(deployment, runtime_options=load_runtime_options(deployment))


def load_runtime_options(
    deployment: MissionDeployment,
    specification: str | None = None,
) -> Mapping[str, RuntimeOptions] | None:
    """Load an explicitly installed, operator-reviewed Python composition factory.

    Only process configuration selects this callable. No request, token, catalog
    document, downloaded skill, or model output can select code to import.
    """
    specification = specification or os.environ.get("MISSION_CONTROL_RUNTIME_OPTIONS_FACTORY")
    if not specification:
        return None
    if not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*", specification):
        raise ValueError("runtime options factory must be an installed module:callable")
    module_name, function_name = specification.split(":")
    factory = getattr(importlib.import_module(module_name), function_name)
    if not callable(factory):
        raise ValueError("runtime options factory is not callable")
    result = factory(deployment)
    expected = {item.authentication.binding.application_id for item in deployment.applications}
    if (
        not isinstance(result, Mapping)
        or set(result) != expected
        or any(not isinstance(value, RuntimeOptions) for value in result.values())
    ):
        raise ValueError(
            "runtime options factory must return exactly the configured typed app mapping"
        )
    return dict(result)
