"""Production composition of the local provider lanes and their native approvals (MP-07,
MP-08, MP-11).

One worker process holds one `ApprovalBroker` whose `connection_ref` is the worker's session
owner ref (the identity MP-06 fences native sessions with), so a native permission request is
bound to a durable Human Task before any wait and a restarted worker never answers an old
handle. The Claude and Codex lanes are composed only when the deployment opts in, an MP-05
auth profile document is configured and the host can spawn their subprocesses (Linux/WSL);
otherwise they stay unregistered and the registry refuses the profile. Nothing here is
qualified: the registry admits these lanes only under the local-proof policy.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import asyncpg

from mission_control.adapters.claude.compose import broker_permissions, compose_claude_local
from mission_control.adapters.claude.continuation import claude_continuation_registration
from mission_control.adapters.claude.harness import ClaudeAgentSdkHarness, ClaudeLaneSettings
from mission_control.adapters.claude.host import host_gate as claude_host_gate
from mission_control.adapters.claude.time_travel import ClaudeTimeTravel
from mission_control.adapters.claude.workspace import AllocatedWorkspace
from mission_control.adapters.codex.compose import AdmissionServiceSource, compose_codex_local
from mission_control.adapters.codex.continuation import codex_continuation_registration
from mission_control.adapters.codex.harness import CodexLocalHarness
from mission_control.adapters.codex.time_travel import CodexTimeTravel
from mission_control.adapters.cursor.workspace import GitWorktreeLeaser
from mission_control.adapters.postgres.approvals.context import PostgresApprovalContextProbe
from mission_control.adapters.postgres.approvals.correlations import (
    PostgresApprovalCorrelationRepository,
)
from mission_control.adapters.postgres.approvals.tasks import PostgresApprovalTaskRepository
from mission_control.adapters.postgres.control_plane.definition_repository import (
    PostgresDefinitionRepository,
)
from mission_control.adapters.postgres.lanes.hook_tokens import PostgresHookIntentLedger
from mission_control.adapters.postgres.lanes.workspace_leases import PostgresWorkspaceLeaseStore
from mission_control.adapters.postgres.run_control.stop_fence import PostgresStopFenceRepository
from mission_control.adapters.storage.context_files import PayloadContextFiles
from mission_control.adapters.workspaces.git_workspaces import GitWorkspaceBackend
from mission_control.adapters.workspaces.mission_setup import BashMissionSetupRunner
from mission_control.application.agentic_components.placement import RenderedProjectionSource
from mission_control.application.artifacts.artifact_promotion import ArtifactPayloadPort
from mission_control.application.authoring.provider_launch import (
    CatalogProjectionRows,
    ProviderBindingRows,
)
from mission_control.application.capabilities.bundle_custody import BundleMaterializer
from mission_control.application.context.hydrators import LaneContinuationRegistration
from mission_control.application.environments.kits import EnvironmentKitCatalog
from mission_control.application.environments.mission_layer import MissionLayerService
from mission_control.application.execution.approvals_broker import ApprovalBroker
from mission_control.application.execution.child_environment import provider_child_environment
from mission_control.application.execution.harness.hook_callbacks import HookCallbackService
from mission_control.application.execution.harness.time_travel import TimeTravelLane
from mission_control.application.execution.operations.lane_outputs import LaneOutputCustody
from mission_control.application.frames.sink import FrameReader
from mission_control.application.secrets.delivery import ProcessSecretDelivery
from mission_control.application.workspaces.service import WorkspaceAllocator
from mission_control.bootstrap.host_projection import HOST_PROJECTORS
from mission_control.bootstrap.provider_auth import compose_auth_admission
from mission_control.bootstrap.settings import PROJECT_ROOT, Settings

DEFAULT_LANE_WORKSPACE_ROOT = PROJECT_ROOT / ".workspaces"


def compose_approval_broker(pool: asyncpg.Pool, *, connection_ref: str) -> ApprovalBroker:
    """MP-11: the worker's one broker over the release 1.2.0 approval tables."""

    return ApprovalBroker(
        PostgresApprovalTaskRepository(pool),
        PostgresApprovalCorrelationRepository(pool),
        probe=PostgresApprovalContextProbe(pool),
        connection_ref=connection_ref,
        fences=PostgresStopFenceRepository(pool),
    )


def _lease_root(settings: Settings, configured: Path | None, name: str) -> Path:
    return configured or (
        (settings.deep_agent_sandbox_workspace_root or DEFAULT_LANE_WORKSPACE_ROOT) / name
    )


def execution_binding_rows(
    settings: Settings, pool: asyncpg.Pool, bundles: BundleMaterializer | None
) -> ProviderBindingRows:
    """The rows of the capability pins a `mc.execution_binding.v2` carries, as the launch author
    rendered them (so `prepare` recomputes the bound materialization digest), their bundle
    bytes through the deployment's custody (MO-01)."""

    scope = settings.mission_control_catalog_scope or ""
    return ProviderBindingRows(
        CatalogProjectionRows(
            PostgresDefinitionRepository(pool, catalog_scope=scope), bundles=bundles
        )
    )


def compose_mission_layer(settings: Settings, pool: asyncpg.Pool) -> MissionLayerService:
    """MO-12: the local lanes' bootstrap entrypoint, reading Environment Kits from the
    installation catalog and running their mission layer with the worker's bash."""

    scope = settings.mission_control_catalog_scope or ""
    return MissionLayerService(
        EnvironmentKitCatalog(PostgresDefinitionRepository(pool, catalog_scope=scope)),
        BashMissionSetupRunner(),
    )


def claude_lease_root(settings: Settings) -> Path:
    """The Claude lane's Workspace Lease root (also checked by the worker-host preflight)."""

    return _lease_root(settings, settings.mission_control_claude_lease_root, "claude-leases")


def codex_lease_root(settings: Settings) -> Path:
    """The Codex lane's Workspace Lease root (also checked by the worker-host preflight)."""

    return _lease_root(settings, settings.mission_control_codex_lease_root, "codex-leases")


def compose_claude_local_lane(
    settings: Settings,
    pool: asyncpg.Pool,
    payloads: ArtifactPayloadPort,
    *,
    broker: ApprovalBroker | None,
    bundles: BundleMaterializer | None,
    outputs: LaneOutputCustody | None = None,
    secrets: ProcessSecretDelivery | None = None,
) -> ClaudeAgentSdkHarness | None:
    """The `claude_agent_sdk` lane (MP-07) when opted in, authenticated and spawnable here."""

    if not settings.mission_control_claude_lane:
        return None
    auth = compose_auth_admission(settings)
    gate = claude_host_gate()
    if auth is None or not gate.supported:
        return None
    root = claude_lease_root(settings)
    backend = GitWorkspaceBackend(root)
    leases = PostgresWorkspaceLeaseStore(pool)
    files = PayloadContextFiles(payloads)
    rows = execution_binding_rows(settings, pool, bundles)
    return compose_claude_local(
        workspaces=AllocatedWorkspace(
            WorkspaceAllocator(
                ledger=leases, backend=backend, root=root, allocator_ref=backend.owner_ref
            ),
            leases,
            files,
        ),
        projections=RenderedProjectionSource(rows, projectors=HOST_PROJECTORS),
        rows=rows,
        auth=auth,
        child_environment=provider_child_environment,
        environ=os.environ,
        fences=PostgresStopFenceRepository(pool),
        intents=PostgresHookIntentLedger(pool),
        inputs=files,
        settings=ClaudeLaneSettings(
            init_timeout_s=settings.mission_control_claude_init_timeout_s,
            drain_timeout_s=settings.mission_control_claude_drain_timeout_s,
        ),
        permissions=(
            broker_permissions(
                broker,
                wait_seconds=settings.mission_control_approval_wait_s,
                reviewers=settings.mission_control_approval_reviewers,
            )
            if broker is not None
            else None
        ),
        host=gate,
        outputs=outputs,
        secrets=secrets,
        mission_layer=compose_mission_layer(settings, pool),
    )


def compose_codex_local_lane(
    settings: Settings,
    pool: asyncpg.Pool,
    payloads: ArtifactPayloadPort,
    *,
    broker: ApprovalBroker | None,
    bundles: BundleMaterializer | None,
    hooks: HookCallbackService,
    outputs: LaneOutputCustody | None = None,
    secrets: ProcessSecretDelivery | None = None,
) -> CodexLocalHarness | None:
    """The `codex` lane (MP-08) when opted in, authenticated and spawnable here (the
    app-server is a stdio subprocess; a Windows worker cannot spawn it). Its Kernel Hooks
    answer through the worker's `hooks` service on the loopback listener (G11)."""

    if not settings.mission_control_codex_lane or sys.platform == "win32":
        return None
    auth = compose_auth_admission(settings)
    if auth is None:
        return None
    root = codex_lease_root(settings)
    rows = execution_binding_rows(settings, pool, bundles)
    files = PayloadContextFiles(payloads)
    return compose_codex_local(
        leaser=GitWorktreeLeaser(
            PostgresWorkspaceLeaseStore(pool), lease_root=root, artifacts=files
        ),
        projections=RenderedProjectionSource(rows, projectors=HOST_PROJECTORS),
        rows=rows,
        artifacts=files,
        inputs=files,
        auth=AdmissionServiceSource(auth),
        lease_root=root,
        codex_binary=settings.mission_control_codex_binary,
        codex_home_mode=settings.mission_control_codex_home_mode,
        owner_codex_home=settings.mission_control_codex_owner_home,
        default_repository=settings.mission_control_codex_repository,
        child_environment=provider_child_environment,
        environ=os.environ,
        broker=broker,
        approval_wait_seconds=settings.mission_control_approval_wait_s,
        allow_version_mismatch=settings.mission_control_codex_allow_version_mismatch,
        approval_reviewers=settings.mission_control_approval_reviewers,
        outputs=outputs,
        hooks=hooks,
        hook_callback_base_url=f"http://127.0.0.1:{settings.mission_control_hook_callback_port}",
        secrets=secrets,
        mission_layer=compose_mission_layer(settings, pool),
    )


def provider_time_travel_lanes(
    frames: FrameReader,
    store: object | None,
    *,
    claude: ClaudeAgentSdkHarness | None = None,
    codex: CodexLocalHarness | None = None,
    request_scope: str | None = None,
) -> tuple[TimeTravelLane, ...]:
    """Cross-provider control (K3, 2026-11-05): the `TimeTravelLane`s of the local provider
    lanes, for `TimeTravelRegistry.register_all`. Both are `ScopedTimeTravelLane`s: a
    composition without a request scope (the worker, the API lifespan) registers them
    unbound and the registry binds the caller's scope on `lane(profile, request_scope=...)`.
    `store` is the content custody of the staged seeds (`PayloadContextFiles` in production,
    stage + retrieve); the harnesses, when this process composed them, are the provider-side
    ports for R3 reads and seeds (`thread/read`, `thread/fork`; the transcript mirror).
    Always registered: an R1 read over the persisted frames needs no harness."""

    return (
        ClaudeTimeTravel(
            frames,
            store,  # type: ignore[arg-type]
            transcripts=claude,
            request_scope=request_scope,
        ),
        CodexTimeTravel(
            frames,
            store,  # type: ignore[arg-type]
            provider=codex,
            request_scope=request_scope,
        ),
    )


def provider_registrations(
    claude: ClaudeAgentSdkHarness | None,
    codex: CodexLocalHarness | None,
    snapshot_store: object,
) -> tuple[LaneContinuationRegistration, ...]:
    """MP-12: the local provider lanes' continuation registrations (never qualified)."""

    registrations: list[LaneContinuationRegistration] = []
    if claude is not None:
        registrations.append(claude_continuation_registration(claude, snapshot_store))  # type: ignore[arg-type]
    if codex is not None:
        registrations.append(codex_continuation_registration(codex, snapshot_store))  # type: ignore[arg-type]
    return tuple(registrations)


__all__ = [
    "claude_lease_root",
    "codex_lease_root",
    "compose_approval_broker",
    "compose_claude_local_lane",
    "compose_codex_local_lane",
    "execution_binding_rows",
    "provider_registrations",
    "provider_time_travel_lanes",
]
