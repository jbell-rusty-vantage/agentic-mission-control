"""The deployment `WorkerActivityCompositionFactory` (RRM-009, CP-050 prerequisite).

`python -m mission_control.adapters.temporal.worker` composes this factory when
`COORDINATOR_LAUNCH_ENABLED` is
set. It wires, through the existing application ports and nothing else:

* the application PostgreSQL authority (run control, operation journal, checkpoint lineage
  and recovery, fork materialization, typed results) on the worker's runtime pool;
* PostgreSQL operation bindings, family documents and templates, scoped workspace
  manifests, artifact metadata and async-child detail;
* the object artifact store (S3 when a bucket is configured, otherwise the shared
  content-addressed directory) for result payloads, artifact promotion and candidates;
* the persistent, registered LangGraph saver and store (REQ-CP-DA-004, DA-016), opened once
  per worker process and registered under the deployment's exact checkpointer and store
  digests;
* the exact capability registry from the deployment pins (models, Skills, MCP servers,
  host tools, sandboxes), the governed async-subagent middleware (RRM-013), the recovery
  composition (RRM-004), the fork reuse resolver (RRM-006), the boundary application
  services (RRM-007) and the journaled GoalDirected settlement (RRM-016);
* the canonical workflow and activity registries and task queues.

Nothing here is company- or fixture-specific. Deterministic qualification models are
registered through `additional_components`, exactly like any other exact model revision.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from functools import partial
from hashlib import sha256
from typing import Any, assert_never

import asyncpg
import httpx
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.store.base import BaseStore
from temporalio.client import Client

from mission_control.adapters.capabilities.capability_bundles import (
    BundleReader,
    DirectoryBundleStore,
)
from mission_control.adapters.capabilities.capability_pins import CapabilityPins
from mission_control.adapters.codex.hooks_callback import CodexHookMapper
from mission_control.adapters.cursor import cursor_lane_stubs
from mission_control.adapters.cursor.bridge import SdkBridgeLauncher
from mission_control.adapters.cursor.cloud import CursorCloudHarness
from mission_control.adapters.cursor.cloud_api import CloudAgentsClient
from mission_control.adapters.cursor.controls import (
    CursorCloudSessionHydrator,
    CursorCloudWorkspaceSnapshots,
    CursorSessionHydrator,
    CursorWorkspaceSnapshots,
)
from mission_control.adapters.cursor.cost import HttpCostReader, LocalHttpBillingReader
from mission_control.adapters.cursor.costs import (
    CursorCostReconciler,
)
from mission_control.adapters.cursor.environments import (
    CursorEnvironmentProvisioner,
    CursorEnvironments,
    CursorEnvironmentsClient,
)
from mission_control.adapters.cursor.hooks_callback import CursorHookMapper
from mission_control.adapters.cursor.local import CursorLocalHarness, CursorLocalSettings
from mission_control.adapters.cursor.projection import CatalogRows
from mission_control.adapters.cursor.scm import GitBranchPublisher
from mission_control.adapters.cursor.secrets import CursorSecretsClient
from mission_control.adapters.cursor.workspace import GitWorktreeLeaser
from mission_control.adapters.deep_agents import (
    DeepAgentRuntimeAdapter,
    DeepAgentsAsyncSubagentAdapter,
    DockerSandboxFactory,
    ExactComponentRegistry,
    ExactDeepAgentMaterializer,
    ExactModelFactory,
    LangSmithSandboxFactory,
    StateSandboxFactory,
)
from mission_control.adapters.deep_agents.async_subagents import BellLabsAsyncSubagentMiddleware
from mission_control.adapters.deep_agents.binding import DEEP_AGENTS_LANE_BINDINGS
from mission_control.adapters.deep_agents.browser_tool import (
    AgentBrowserPageTool,
    granted_network_hosts,
)
from mission_control.adapters.deep_agents.checkpoint_verifier import (
    LangGraphCheckpointDescendantVerifier,
)
from mission_control.adapters.deep_agents.child_adoption import LiveInvocationChildAdopter
from mission_control.adapters.deep_agents.compile import deep_agents_lane
from mission_control.adapters.deep_agents.harness import DeepAgentsHarness
from mission_control.adapters.deep_agents.hooks import (
    HookIntentLedgerShim,
    KernelHookPorts,
    StopFenceShim,
    StreamFrameSink,
    StreamUsageRecorder,
)
from mission_control.adapters.deep_agents.hooks_callback import DeepAgentsHookMapper
from mission_control.adapters.deep_agents.materializer import (
    IdentityCheckedModelFactory,
    ModelFactory,
    ResolvedHookScriptBundle,
    ResolvedSkillBundle,
    SandboxFactory,
)
from mission_control.adapters.deep_agents.persistence import (
    StandalonePersistence,
    StandalonePersistenceLifespan,
)
from mission_control.adapters.deep_agents.time_travel import DeepAgentsTimeTravel
from mission_control.adapters.operations.runtime_ports import (
    FilesystemArtifactPayloadStore,
    PinnedCapabilityAssetVerifier,
    RecordedOperationEventSink,
    SecretEnvVarsResolver,
)
from mission_control.adapters.postgres.approvals.context import PostgresApprovalContextProbe
from mission_control.adapters.postgres.async_subagents.async_subagent_detail_repository import (
    PostgresAsyncSubagentDetailRepository,
)
from mission_control.adapters.postgres.async_subagents.async_subagents import (
    PostgresAsyncSubagentAuthority,
)
from mission_control.adapters.postgres.capability_bundles import PostgresCapabilityBundleAdmissions
from mission_control.adapters.postgres.chains.exports import PostgresLinkedExports
from mission_control.adapters.postgres.chains.store import PostgresChainSupplies
from mission_control.adapters.postgres.context.artifact_bytes import PostgresArtifactBytes
from mission_control.adapters.postgres.context.continuation_repository import (
    PostgresContinuationRepository,
)
from mission_control.adapters.postgres.context.selection_repository import (
    PostgresContextSelectionRepository,
)
from mission_control.adapters.postgres.control_plane.definition_repository import (
    PostgresDefinitionRepository,
)
from mission_control.adapters.postgres.control_plane.manifest_submission import (
    PostgresManifestSubmissionRepository,
)
from mission_control.adapters.postgres.coordinator.workflow_result_repository import (
    PostgresWorkflowResultRepository,
)
from mission_control.adapters.postgres.cursor_costs import PostgresCursorCosts
from mission_control.adapters.postgres.environments import (
    PostgresEnvironmentPreparationRepository,
)
from mission_control.adapters.postgres.frames.repository import PostgresFrameRepository
from mission_control.adapters.postgres.human_tasks.repository import PostgresHumanTaskRepository
from mission_control.adapters.postgres.knowledge.output_fulfillment import (
    compose_output_fulfillment,
)
from mission_control.adapters.postgres.lanes.execution_state import (
    PostgresLaneExecutionStateStore,
)
from mission_control.adapters.postgres.lanes.hook_tokens import (
    PostgresHookIntentLedger,
    PostgresHookTokenStore,
)
from mission_control.adapters.postgres.lanes.placement import PostgresPlacementStore
from mission_control.adapters.postgres.lanes.workspace_leases import PostgresWorkspaceLeaseStore
from mission_control.adapters.postgres.operations.invocation_settlement import (
    PostgresInvocationSettlementStore,
)
from mission_control.adapters.postgres.operations.operation_binding_repository import (
    PostgresOperationBindingRepository,
)
from mission_control.adapters.postgres.operations.operation_journal import (
    PostgresAtomicOperationJournalRepository,
)
from mission_control.adapters.postgres.orchestration.completion_repository import (
    PostgresCompletionRepository,
)
from mission_control.adapters.postgres.orchestration.goal_directed_repository import (
    PostgresGoalDirectedDocumentRepository,
)
from mission_control.adapters.postgres.orchestration.nested_activations import (
    PostgresNestedActivationStore,
)
from mission_control.adapters.postgres.orchestration.orchestration_binding_repository import (
    PostgresRunSemanticInputBindingRepository,
)
from mission_control.adapters.postgres.orchestration.stagegraph_repository import (
    PostgresStageGraphOperationTemplateRepository,
)
from mission_control.adapters.postgres.run_control.mailbox import PostgresCommandMailbox
from mission_control.adapters.postgres.run_control.run_control_repository import (
    PostgresRunControlRepository,
)
from mission_control.adapters.postgres.run_control.stop_fence import PostgresStopFenceRepository
from mission_control.adapters.postgres.runtime.run_forks import (
    PostgresForkMaterializationStore,
    PostgresRunSnapshotRepository,
)
from mission_control.adapters.postgres.workspace_candidate_contents import (
    PostgresWorkspaceCandidateContents,
)
from mission_control.adapters.postgres.workspace_closures import PostgresWorkspaceClosures
from mission_control.adapters.postgres.workspaces.artifact_metadata_repository import (
    PostgresArtifactMetadataRepository,
)
from mission_control.adapters.postgres.workspaces.artifact_repository import (
    PostgresArtifactDurableReferenceRepository,
)
from mission_control.adapters.postgres.workspaces.workspace_manifest_repository import (
    PostgresWorkspaceManifestRepository,
)
from mission_control.adapters.secrets.sources import (
    KeyringSecretSource,
    SecretStoreFile,
    SupabaseVaultSource,
    WorkerEnvironmentSource,
)
from mission_control.adapters.storage.artifact_payloads import S3ArtifactPayloadStore
from mission_control.adapters.storage.context_files import PayloadContextFiles
from mission_control.adapters.storage.filesystem_workspace import FilesystemWorkspaceProvisioner
from mission_control.adapters.supabase_storage.bundles import (
    SupabaseCapabilityBundleStore,
    configured_supabase_bundle_store,
)
from mission_control.adapters.temporal.activities.cursor_costs import CursorCostActivities
from mission_control.adapters.temporal.activities.human_gate import HumanGateActivities
from mission_control.adapters.temporal.artifact_activities import ArtifactPromotionActivities
from mission_control.adapters.temporal.continuation_composition import (
    ContinuationSettings,
    compose_lane_continuation,
)
from mission_control.adapters.temporal.coordinator_runtime import (
    GoalDirectedCoordinatorDependencies,
    StageGraphCoordinatorDependencies,
    create_routed_coordinator_activities,
)
from mission_control.adapters.temporal.hosted_lane_composition import compose_hosted_lanes
from mission_control.adapters.temporal.local_signals import (
    LocalSignalDelivery,
    RemoteSignalDelivery,
    ScopedSecretMinter,
)
from mission_control.adapters.temporal.operation_activities import OperationExecutionActivities
from mission_control.adapters.temporal.provider_lane_composition import (
    compose_approval_broker,
    compose_claude_local_lane,
    compose_codex_local_lane,
    compose_mission_layer,
    provider_registrations,
)
from mission_control.adapters.temporal.unit_reconciliation import TemporalUnitReconciliationNudge
from mission_control.adapters.temporal.worker import (
    WorkerActivityComposition,
    operation_heartbeat_policy,
)
from mission_control.adapters.workspaces.git_workspaces import GitWorkspaceBackend
from mission_control.application.agentic_components.placement import (
    RenderedProjectionSource,
    hook_context_index,
)
from mission_control.application.artifacts.artifact_promotion import (
    ArtifactPayloadAddress,
    ArtifactPayloadPort,
    ArtifactPromotionService,
    ArtifactValidationAuthorityPort,
    ScopedArtifactPromotionService,
    StaticArtifactValidationAuthority,
)
from mission_control.application.artifacts.workspace_candidates import (
    WorkspaceCandidateCaptureService,
)
from mission_control.application.artifacts.workspace_materialization import (
    BindingWorkspaceMaterializer,
    WorkspaceMaterializationService,
)
from mission_control.application.authoring.manifest_launch_inputs import ServedModel
from mission_control.application.authoring.service import ControlPlaneService
from mission_control.application.capabilities.bundle_custody import BundleMaterializer
from mission_control.application.context.fork_context import ForkContextReader
from mission_control.application.context.hydrators import LaneContinuationRegistration
from mission_control.application.context.lane_continuation import ContinuationHoldOracle
from mission_control.application.context.pack_service import ContextPackService
from mission_control.application.coordinator.coordinator_results import (
    TerminalWorkflowCompletionService,
)
from mission_control.application.environments.kits import EnvironmentKitCatalog
from mission_control.application.environments.preparation import EnvironmentPreparationService
from mission_control.application.environments.provider_environments import (
    ProviderEnvironmentService,
)
from mission_control.application.execution.harness.budget_controls import BudgetControlService
from mission_control.application.execution.harness.hook_callbacks import HookCallbackService
from mission_control.application.execution.harness.inject import InterruptAndInjectService
from mission_control.application.execution.harness.lane_turns import LaneTurnService
from mission_control.application.execution.harness.protocol import AgentHarness
from mission_control.application.execution.harness.sessions import (
    WorkerSessionManager,
    default_owner_ref,
)
from mission_control.application.execution.harness.time_travel import (
    TimeTravelLane,
    TimeTravelRegistry,
)
from mission_control.application.execution.mailbox import MailboxDeliveryService
from mission_control.application.execution.operations.checkpoint_lineage import DEFAULT_CLAIM_LEASE
from mission_control.application.execution.operations.journaled_operation_execution import (
    JournaledOperationExecutionCoordinator,
)
from mission_control.application.execution.operations.lane_outputs import (
    LaneOutputCustody,
    WorkspaceCandidateLaneOutputs,
)
from mission_control.application.execution.operations.operation_execution import (
    OperationExecutionService,
    RunControlOperationAuthority,
    RunControlOperationBudgetAuthority,
    SecretResolutionPort,
)
from mission_control.application.execution.operations.operation_journal import (
    OperationJournalService,
)
from mission_control.application.execution.service import RunControlService
from mission_control.application.execution.stop_fence import KernelHookFenceGate
from mission_control.application.frames.reducer import FrameFactProjector
from mission_control.application.frames.sink import FrameReader
from mission_control.application.knowledge.toolset import KnowledgeToolset
from mission_control.application.programs.control_admission import (
    ManifestStageGraphHumanGateProvider,
)
from mission_control.application.programs.human_gates import GateReservationSettlement
from mission_control.application.programs.named_outputs import NamedStageOutputs
from mission_control.application.programs.orchestration_routing import SemanticHandlerRegistry
from mission_control.application.programs.service import (
    F1OrchestrationBindingVerifier,
    RunControlLifecycleGateway,
    orchestration_lifecycle_actor,
)
from mission_control.application.recovery.run_forks import ForkReuseOracle, ForkReuseResolver
from mission_control.application.resolution.lane_bindings import LaneRebinders
from mission_control.application.resolution.registries import LaneRegistry
from mission_control.application.secrets.broker import SecretBroker, SecretSource
from mission_control.application.secrets.delivery import ProcessSecretDelivery
from mission_control.application.secrets.redaction import install_log_redaction
from mission_control.application.signals.service import SignalIngressService
from mission_control.application.subordinates.admission import CheckTimeAdmission
from mission_control.application.subordinates.adoption import AsyncChildOutputAdoption
from mission_control.application.subordinates.parent_completion import (
    ASYNC_RESULT_POLICIES,
    AdmissionRule,
    AsyncChildCompletion,
)
from mission_control.application.subordinates.parent_effects import RunControlAsyncChildEffects
from mission_control.application.subordinates.service import AsyncSubagentService
from mission_control.application.workspaces.placement import PlacementAdmission
from mission_control.application.workspaces.service import WorkspaceAllocator
from mission_control.bootstrap.application_profiles import trusted_assessment_validators
from mission_control.bootstrap.bundle_custody import compose_bundle_materializer
from mission_control.bootstrap.frame_capture import compose_frame_capture
from mission_control.bootstrap.host_projection import HOST_PROJECTORS
from mission_control.bootstrap.lanes import SESSION_LANES
from mission_control.bootstrap.operation_recovery_composition import (
    OperationRecoveryComposition,
    compose_postgres_operation_recovery,
)
from mission_control.bootstrap.settings import (
    PROJECT_ROOT,
    IntegrationConfigurationError,
    Settings,
    configured,
)
from mission_control.bootstrap.workspace_closures import workspace_closure_profile
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.execution.contracts import (
    AsyncChildCancellationRecord,
    AsyncSubagentContract,
    AsyncSubagentDependencyClass,
    DeepAgentMCPServerComponent,
    OperationExecutionBinding,
    RuntimeInvocation,
    RuntimeResult,
)
from mission_control.domain.policies.contracts import ActorContext
from mission_control.domain.programs.goal_directed_runtime import (
    GoalExecutorObservation,
    GoalNamedExecutorObservation,
    GoalVerifierObservation,
)

DEFAULT_ARTIFACT_PAYLOAD_ROOT = PROJECT_ROOT / ".artifact-payloads"
ASYNC_CHILD_COMPLETION_KIND = "async_child_completion.v1"
# The result admission policies this deployment decides at the parent boundary, by the
# contract's `result_admission_policy_ref`; a child of any other policy is left undecided.
DEFAULT_ASYNC_RESULT_POLICIES: Mapping[str, AdmissionRule] = ASYNC_RESULT_POLICIES
DEFAULT_WORKSPACE_ROOT = PROJECT_ROOT / ".workspaces"
GOAL_DIRECTED_WORKER_ACTOR = "goal-directed-worker"


@dataclass(frozen=True)
class DeploymentCapabilityComponents:
    """Exact components a deployment registers beside the pinned catalog.

    Keys are immutable definition digests (`ExactComponentRegistry` semantics). A
    qualification registers its deterministic model under the model digest it binds; a
    deployment registers nothing here unless it serves a component the pin file cannot
    describe (a structured output schema, a middleware instance).
    """

    model_factories: Mapping[str, ModelFactory] = field(default_factory=dict)
    # OC-R6: what each registered model factory serves, by digest; required for every one
    # unless `qualification` is set.
    model_identities: Mapping[str, ServedModel] = field(default_factory=dict)
    # Explicit test or qualification composition: its deterministic models may declare no
    # identity and may stand in for a pinned definition's factory. Never inferred.
    qualification: bool = False
    prompts: Mapping[str, str] = field(default_factory=dict)
    tools: Mapping[str, BaseTool] = field(default_factory=dict)
    skill_bundles: Mapping[str, ResolvedSkillBundle] = field(default_factory=dict)
    sandbox_factories: Mapping[str, SandboxFactory] = field(default_factory=dict)
    # 1.4.4 (FX-TR-HOOK): catalog hook script bundles by manifest digest, the way the
    # materializer resolves them (`ExactComponentRegistry.hook_scripts`).
    hook_scripts: Mapping[str, ResolvedHookScriptBundle] = field(default_factory=dict)
    structured_output_schemas: Mapping[str, type[Any] | dict[str, Any]] = field(
        default_factory=dict
    )
    # Exact MCP server components (by ref digest) the worker may launch besides the pinned
    # ones; compared by full equality before every launch (qualification harnesses only).
    mcp_servers: Mapping[str, DeepAgentMCPServerComponent] = field(default_factory=dict)

    def check_models(self, pins: CapabilityPins) -> None:
        """Fail closed on registered model factories (OC-R6): each declares what it serves, and
        none replaces a pinned definition's factory, unless this is a qualification composition."""

        if self.qualification:
            return
        pinned = {item.ref.digest for item in pins.models}
        collisions = sorted(set(self.model_factories) & pinned)
        if collisions:
            raise ValueError(
                f"MODEL_FACTORY_COLLISION: registered model factories replace pinned model "
                f"definitions {collisions}; only a qualification composition may"
            )
        undeclared = sorted(set(self.model_factories) - set(self.model_identities))
        if undeclared:
            raise ValueError(
                f"MODEL_PIN_UNDECLARED: registered model factories {undeclared} declare no "
                "vendor and model id (DeploymentCapabilityComponents.model_identities)"
            )


@dataclass(frozen=True)
class DeploymentCapabilityRegistry:
    registry: ExactComponentRegistry
    pins: CapabilityPins
    checkpointers: Mapping[str, BaseCheckpointSaver[Any]]

    def disclosure(self) -> dict[str, object]:
        return {
            **self.pins.disclosure(),
            "checkpointer_digests": sorted(self.checkpointers),
            "store_digests": sorted(self.registry.stores),
            "model_digests": sorted(self.registry.model_factories),
            "sandbox_digests": sorted(self.registry.sandbox_factories),
        }


def supabase_skill_bundle_reader(
    settings: Settings, *, http_client: httpx.Client
) -> SupabaseCapabilityBundleStore:
    """The worker's skill-pin reader: the reader credential (SELECT on the application prefix),
    never the service key. Refuses without a trusted namespace, catalog scope or reader token."""

    if not settings.capability_bundle_namespace or not settings.mission_control_catalog_scope:
        raise ValueError("Supabase skills require trusted storage namespace and catalog scope")
    return configured_supabase_bundle_store(settings, http_client=http_client, credential="reader")


def build_deployment_capability_registry(
    settings: Settings,
    pins: CapabilityPins,
    *,
    saver: BaseCheckpointSaver[Any],
    store: BaseStore,
    additional: DeploymentCapabilityComponents | None = None,
    bundle_reader: BundleReader | None = None,
    kernel_hooks: KernelHookPorts | None = None,
    hook_callbacks: HookCallbackService | None = None,
    hook_callback_base_url: str | None = None,
) -> DeploymentCapabilityRegistry:
    """The exact component registry: pinned catalog plus the persistent saver and store.

    `kernel_hooks` are the Deep Agents lane's four kernel hook ports (P3.5; the production
    set comes from `compose_kernel_hook_ports`, the default is the no-op set); `hook_callbacks`
    and `hook_callback_base_url` let the materializer mint a callback endpoint for catalog
    hook scripts that declare `callback: service`."""

    if settings.capability_bundle_backend == "supabase" and bundle_reader is None:
        raise ValueError("Supabase skill pins require a PostgreSQL-admitted bundle reader")
    if bundle_reader is None and settings.capability_bundle_local_root is not None:
        bundle_reader = DirectoryBundleStore(settings.capability_bundle_local_root)
    extra = additional or DeploymentCapabilityComponents()
    # One exact factory per served model definition; it builds the client for the vendor the
    # sealed binding pins (the Model Catalog's, OC-R6) and refuses a binding for another vendor
    # or model id than the pin file declares for that definition.
    extra.check_models(pins)
    model_factories: dict[str, ModelFactory] = {
        model.ref.digest: ExactModelFactory(
            served_vendor=model.provider, served_model_id=model.model_id
        )
        for model in pins.models
    }
    for digest, factory in extra.model_factories.items():
        identity = extra.model_identities.get(digest)
        model_factories[digest] = (
            IdentityCheckedModelFactory(factory, vendor=identity.vendor, model_id=identity.model_id)
            if identity is not None
            else factory
        )
    sandbox_factories: dict[str, SandboxFactory] = {}
    for sandbox in pins.sandboxes:
        if sandbox.backend == "state":
            sandbox_factories[sandbox.ref.digest] = StateSandboxFactory()
        elif sandbox.backend == "docker":
            sandbox_factories[sandbox.ref.digest] = DockerSandboxFactory(
                workspace_root=settings.deep_agent_sandbox_workspace_root
                or DEFAULT_WORKSPACE_ROOT / "sandboxes"
            )
        elif sandbox.backend == "langsmith":
            sandbox_factories[sandbox.ref.digest] = LangSmithSandboxFactory()
        else:
            # OVE-216: every pinned backend names its own factory; a new backend (Daytona)
            # fails at composition until its factory exists, never at run time.
            assert_never(sandbox.backend)
    sandbox_factories.update(extra.sandbox_factories)
    tools: dict[str, BaseTool] = {}
    for tool in pins.tools:
        if settings.web_research_agent_browser_node is None:
            raise ValueError("pinned agent-browser tool requires WEB_RESEARCH_AGENT_BROWSER_NODE")
        tools[tool.ref.digest] = AgentBrowserPageTool(
            node_executable=settings.web_research_agent_browser_node,
            entrypoint=tool.verify_entrypoint(),
            command_timeout_seconds=settings.web_research_browser_command_timeout_seconds,
            max_output_bytes=settings.web_research_max_browser_output_bytes,
        )
    tools.update(extra.tools)
    skill_bundles: dict[str, ResolvedSkillBundle] = {
        skill.bundle_digest: skill.bundle(store=bundle_reader) for skill in pins.skills
    }
    skill_bundles.update(extra.skill_bundles)
    checkpointers = {item.ref.digest: saver for item in pins.checkpointers}
    stores = {item.ref.digest: store for item in pins.stores}
    registry = ExactComponentRegistry(
        model_factories=model_factories,
        prompts=dict(extra.prompts),
        tools=tools,
        skill_bundles=skill_bundles,
        sandbox_factories=sandbox_factories,
        checkpointers=checkpointers,
        stores=stores,
        structured_output_schemas=dict(extra.structured_output_schemas),
        hook_scripts=dict(extra.hook_scripts),
        kernel_hooks=kernel_hooks or KernelHookPorts(),
        hook_callbacks=hook_callbacks,
        hook_callback_base_url=hook_callback_base_url,
        shell_workspace_root=(settings.deep_agent_sandbox_workspace_root or DEFAULT_WORKSPACE_ROOT)
        / "shell-sessions",
    )
    return DeploymentCapabilityRegistry(registry=registry, pins=pins, checkpointers=checkpointers)


def compose_kernel_hook_ports(pool: asyncpg.Pool) -> KernelHookPorts:
    """The Deep Agents lane's production kernel hook ports (tracing proposal P3.5, TR-D4).

    The stop fence and the Operation Intent go to the same repositories the Kernel Hook
    callback service uses (one fence, one ledger per deployment); hook frames and
    hook-observed usage go through the graph's stream writer as `mc.hook_invoked`,
    `mc.hook_result` and `mc.usage` custom events, which the Deep Agents frame recorder
    persists like every other native event. No side-effect class allow-list is declared by
    the binding today, so the Operation Intent hook refuses nothing on that ground."""

    return KernelHookPorts(
        # Tracing Stage 3 (R1-F1): the model-call fence check reads the run, so an orphaned
        # fence (its cancel rejected) no longer ends turns.
        stop_fence=StopFenceShim(
            KernelHookFenceGate(
                PostgresStopFenceRepository(pool), runs=PostgresRunControlRepository(pool)
            )
        ),
        intents=HookIntentLedgerShim(PostgresHookIntentLedger(pool)),
        frames=StreamFrameSink(),
        usage=StreamUsageRecorder(),
        allowed_side_effect_classes=None,
    )


def artifact_payload_store(settings: Settings) -> ArtifactPayloadPort:
    from mission_control.bootstrap.payload_custody import verify_payload_custody

    root = settings.artifact_payload_root or DEFAULT_ARTIFACT_PAYLOAD_ROOT
    verify_payload_custody(settings, root)
    if settings.s3_bucket:
        return S3ArtifactPayloadStore(settings, settings.s3_bucket)
    return FilesystemArtifactPayloadStore(root)


class ProductionAsyncSubagentMiddlewareFactory:
    """RRM-013 in production: one governed `AsyncSubagentService` per parent operation.

    The provider adapter is built from the operation's resolved secrets (the deployment
    credential reference the parent binding declares) and its request scope; reservations,
    links and the parent's effect claim go through the worker's run control before any
    provider call. New spawns are allowed only when the deployment opts in.

    OVE-184: every middleware admits a completed child at check time through the deployment's
    registered result admission policies (`CheckTimeAdmission`), and, where the worker
    composes the knowledge toolset, offers `adopt_async_task_output` (the explicit exact
    adoption into one of the parent's own promises, through its ordinary submission act).
    """

    def __init__(
        self,
        *,
        pool: asyncpg.Pool,
        run_control: RunControlService,
        actor: ActorContext,
        allow_new_spawns: bool,
        submitter_identity: str,
        dependency_class: AsyncSubagentDependencyClass = (
            AsyncSubagentDependencyClass.REQUIRED_BLOCKING
        ),
        policies: Mapping[str, AdmissionRule] | None = None,
        knowledge_toolset: KnowledgeToolset | None = None,
    ) -> None:
        self._pool = pool
        self._run_control = run_control
        self._actor = actor
        self._allow_new_spawns = allow_new_spawns
        self._submitter_identity = submitter_identity
        self._dependency_class = dependency_class
        self._policies = dict(policies if policies is not None else ASYNC_RESULT_POLICIES)
        self._knowledge_toolset = knowledge_toolset

    def service(
        self, binding: OperationExecutionBinding, resolved_secrets: Mapping[str, str]
    ) -> tuple[AsyncSubagentService, DeepAgentsAsyncSubagentAdapter]:
        """The governed service of one parent operation, over its scope-bound credential."""

        adapter = DeepAgentsAsyncSubagentAdapter(
            secrets=resolved_secrets, request_scope=binding.request_scope
        )
        service = AsyncSubagentService(
            PostgresAsyncSubagentDetailRepository(self._pool),
            PostgresAsyncSubagentAuthority(self._pool),
            adapter,
            parent_effects=RunControlAsyncChildEffects(self._run_control, actor=self._actor),
            allow_new_spawns=self._allow_new_spawns,
            submitter_identity=self._submitter_identity,
        )
        return service, adapter

    def middleware(
        self,
        binding: OperationExecutionBinding,
        contracts: tuple[AsyncSubagentContract, ...],
        resolved_secrets: Mapping[str, str],
    ) -> BellLabsAsyncSubagentMiddleware:
        service, adapter = self.service(binding, resolved_secrets)
        toolset = self._knowledge_toolset
        return BellLabsAsyncSubagentMiddleware(
            service=service,
            adapter=adapter,
            binding=binding,
            contracts=contracts,
            dependency_class=self._dependency_class,
            admission=CheckTimeAdmission(service, policies=self._policies),
            adopter=(
                LiveInvocationChildAdopter(
                    toolset, AsyncChildOutputAdoption(service, toolset.submissions), binding
                )
                if toolset is not None
                else None
            ),
        )


class ProductionAsyncChildCancellation:
    """RRM-008 step 4 in production: the operation boundary's `AsyncChildCancellationPort`.

    `OperationExecutionService.cancel_children` names only the parent binding. The provider
    adapter of that parent's children needs the operation's own scope-bound credential, so
    this port resolves the binding's `secret_refs` (the same resolver cognition uses), builds
    the parent's governed `AsyncSubagentService` exactly as the middleware does, and cancels
    every active child under its link policy. A parent that spawned no child resolves no
    secret and calls no provider.
    """

    def __init__(
        self,
        children: ProductionAsyncSubagentMiddlewareFactory,
        authority: PostgresAsyncSubagentAuthority,
        secrets: SecretResolutionPort,
    ) -> None:
        self._children = children
        self._authority = authority
        self._secrets = secrets

    async def cancel_children(
        self,
        binding: OperationExecutionBinding,
        *,
        reason: str,
        requested_at: datetime,
    ) -> tuple[AsyncChildCancellationRecord, ...]:
        if not await self._authority.list_child_ids(binding.request_scope, binding.binding_id):
            return ()
        resolved = await self._secrets.resolve(binding.secret_refs)
        service, _adapter = self._children.service(binding, resolved)
        return await service.cancel_children(binding, reason=reason, requested_at=requested_at)


def compose_transfer_materializer(
    pool: asyncpg.Pool,
    payloads: ArtifactPayloadPort,
    context_files: PayloadContextFiles,
    *,
    gateway: Any = None,
    lineage: Any = None,
    recheck: Any = None,
    linked_recheck: Any = None,
    trusted_validators: frozenset[str] | None,
) -> Any:
    """WI-02 (ADR-0061): the one transfer materializer over the 1.7.0 plan tables.

    Produced outputs resolve through the run's named promises (exact accepted revisions); a KS
    report is read exactly with the receiver's purpose through ``gateway`` when composed, and
    its current access is re-read at every attempt. The only host selector registered by
    default is the goal-wide current-set index (``mc.current-set@1``, WI-07); any other
    application source refuses until an application binding supplies one.
    """

    from mission_control.adapters.postgres.context.transfer_plans import (
        PostgresTransferPlanStore,
    )
    from mission_control.adapters.postgres.knowledge.output_contracts import (
        PostgresOutputContractStore,
    )
    from mission_control.adapters.postgres.knowledge.use_decisions import (
        PostgresMemberDecisions,
    )
    from mission_control.application.context.linked_transfer import (
        LinkedExportAccess,
        LinkedExportResolver,
    )
    from mission_control.application.context.materialization import (
        ApplicationSelectorResolver,
        ArtifactResolver,
        CurrentAccessPort,
        KnowledgeReadAccess,
        LiteralResolver,
        ProducedOutputResolver,
        TransferMaterializer,
    )
    from mission_control.application.context.resolution import ContentResolutionService
    from mission_control.application.outputs.current_set import CurrentSetIndexResolver
    from mission_control.domain.knowledge.judgment import TRUSTED_BRIDGE_ACTOR
    from mission_control.domain.outputs.current_set import CURRENT_SET_BINDING

    outputs = PostgresOutputContractStore(pool)
    artifacts = ArtifactResolver(PostgresArtifactBytes(pool, payloads), context_files)
    reports = None if gateway is None else ContentResolutionService(gateway)
    renderer = ProducedOutputResolver(
        outputs, reports=reports, artifacts=artifacts, recheck=recheck
    )
    linked = LinkedExportResolver(
        PostgresLinkedExports(pool), outputs, renderer, recheck=linked_recheck
    )
    access: dict[str, CurrentAccessPort] = {}
    if reports is not None:
        access["produced_output"] = KnowledgeReadAccess(reports)
        access["linked_export"] = LinkedExportAccess(linked, KnowledgeReadAccess(reports))
    return TransferMaterializer(
        store=PostgresTransferPlanStore(pool),
        staging=context_files,
        custody=context_files,
        resolvers={
            # OVE-169: `recheck` (the composed trusted settlement) re-resolves each accepted
            # head's KS decision before use; a demoted head is never admitted.
            "produced_output": renderer,
            "linked_export": linked,
            "exact_artifact": artifacts,
            "typed_literal": LiteralResolver(),
            "application_selector": ApplicationSelectorResolver(
                {
                    CURRENT_SET_BINDING: CurrentSetIndexResolver(
                        outputs,
                        trusted_validators=trusted_validators,
                        member_decisions=PostgresMemberDecisions(
                            pool, bridge_actor=TRUSTED_BRIDGE_ACTOR
                        ),
                    )
                }
            ),
        },
        access=access,
        lineage=lineage,
    )


def registered_lane_profiles(settings: Settings) -> tuple[str, ...]:
    """The profiles `compose_lane_registry` registers for these settings (MP-22 host gate)."""

    profiles = ["deep_agents"]
    if settings.cursor_api_key is not None:
        profiles += ["cursor_local", "cursor_cloud"]
    # Mirrors the opt-ins of `provider_lane_composition` (the host gate itself is what
    # MP-22 preflight checks for these profiles).
    if settings.mission_control_auth_profiles_path is not None:
        if settings.mission_control_claude_lane:
            profiles.append("claude_agent_sdk")
        if settings.mission_control_codex_lane:
            profiles.append("codex")
    if settings.mission_control_claude_managed_lane:
        profiles.append("claude_managed")
    if settings.mission_control_codex_agents_lane:
        profiles.append("codex_agents")
    return tuple(profiles)


def continuation_settings(settings: Settings) -> ContinuationSettings:
    """MP-12: the worker's context-pressure policy and governors from `Settings`."""

    return ContinuationSettings(
        soft_context_ratio=settings.mission_control_context_soft_ratio,
        hard_context_ratio=settings.mission_control_context_hard_ratio,
        reserve_ratio=settings.mission_control_context_reserve_ratio,
        max_session_turns=settings.mission_control_context_max_session_turns,
        max_transfers=settings.mission_control_continuation_max_transfers,
        max_compaction_failures=settings.mission_control_continuation_max_compaction_failures,
        native_compaction=settings.mission_control_native_compaction,
    )


def lane_continuation_registrations(
    *,
    cursor_local: CursorLocalHarness | None,
    cursor_cloud: CursorCloudHarness | None,
    durable_bytes: Any,
    snapshot_store: Any,
    extra: Sequence[LaneContinuationRegistration] = (),
) -> tuple[LaneContinuationRegistration, ...]:
    """MP-12: the composed Session Lanes' continuation registrations (never `qualified`)."""

    registrations: list[LaneContinuationRegistration] = []
    if cursor_local is not None:
        local = cursor_local
        registrations.append(
            LaneContinuationRegistration(
                "cursor_local",
                lambda _scope: CursorSessionHydrator(local, durable_bytes),
                snapshots=lambda _scope: CursorWorkspaceSnapshots(local, snapshot_store),
            )
        )
    if cursor_cloud is not None:
        cloud = cursor_cloud
        registrations.append(
            LaneContinuationRegistration(
                "cursor_cloud",
                lambda _scope: CursorCloudSessionHydrator(cloud, durable_bytes),
                snapshots=lambda _scope: CursorCloudWorkspaceSnapshots(cloud, snapshot_store),
            )
        )
    registrations.extend(extra)
    return tuple(registrations)


def goal_output_schemas() -> dict[str, type[Any]]:
    """MP-22 delta 4: the strict GoalDirected executor/verifier observation schemas under the
    digests the manifest launch bindings carry (`sha256_digest(Model.model_json_schema())`),
    so a bound `goal_output_schemas` entry materializes with a `response_format`."""

    return {
        sha256_digest(model.model_json_schema()): model
        for model in (
            GoalExecutorObservation,
            GoalNamedExecutorObservation,
            GoalVerifierObservation,
        )
    }


def with_goal_output_schemas(
    additional: DeploymentCapabilityComponents | None,
) -> DeploymentCapabilityComponents:
    extra = additional or DeploymentCapabilityComponents()
    return replace(
        extra,
        structured_output_schemas={**goal_output_schemas(), **extra.structured_output_schemas},
    )


def compose_lane_registry(
    settings: Settings,
    deep_agents: DeepAgentsHarness | None,
    *,
    cursor_local: AgentHarness | None = None,
    cursor_cloud: AgentHarness | None = None,
    claude_local: AgentHarness | None = None,
    codex_local: AgentHarness | None = None,
    claude_managed: AgentHarness | None = None,
    codex_agents: AgentHarness | None = None,
) -> LaneRegistry:
    """`deep_agents` always; the Cursor profiles when a Cursor credential is bound: the real
    `cursor_local` (FT-G3) and `cursor_cloud` (FT-G5) harnesses when composed, otherwise
    unqualified stubs. Unqualified lanes are admitted only under the application's local-proof
    policy (`MISSION_CONTROL_ALLOW_UNQUALIFIED_LANES`).

    Every composed lane registers its package (ADR-0063; OC-R3) with the harness this worker
    composed: Deep Agents through `adapters/deep_agents.deep_agents_lane` (the worker executes
    sealed bindings and compiles none, so its registration carries no deployment facts), every
    other lane through its package's `LANES` (`bootstrap/lanes.SESSION_LANES`). An uncomposed
    Cursor profile publishes an unqualified stub, a runtime-only entry the resolver refuses."""

    composed: list[AgentHarness] = []
    stubs: list[AgentHarness] = []
    if settings.cursor_api_key is not None:
        local_stub, cloud_stub = cursor_lane_stubs()
        for harness, stub in ((cursor_local, local_stub), (cursor_cloud, cloud_stub)):
            if harness is None:
                stubs.append(stub)
            else:
                composed.append(harness)
    # MP-07/MP-08: the local Claude and Codex lanes, when composed for this worker.
    composed.extend(
        lane
        for lane in (claude_local, codex_local, claude_managed, codex_agents)
        if lane is not None
    )
    registry = LaneRegistry(allow_unqualified=settings.allow_unqualified_lanes)
    if deep_agents is not None:
        registry.register(deep_agents_lane(None), deep_agents)
    for harness in composed:
        registry.register(SESSION_LANES[harness.describe().lane_profile], harness)
    for unqualified in stubs:
        registry.register_harness(unqualified)
    return registry


def cursor_catalog_rows(
    settings: Settings, pool: asyncpg.Pool, bundles: BundleMaterializer | None
) -> CatalogRows:
    """The Cursor lanes' rows of a binding's exact catalog pins, their bundle bytes through the
    deployment's custody (MO-01)."""

    return CatalogRows(
        PostgresDefinitionRepository(
            pool, catalog_scope=settings.mission_control_catalog_scope or ""
        ),
        bundles=bundles,
    )


async def compose_secret_broker(
    settings: Settings, resources: AsyncExitStack, pool: asyncpg.Pool | None = None
) -> SecretBroker:
    """MO-11: the deployment's Secret Broker (ADR-0043). `environment:` references read the
    worker environment; `secret:`/`vault:` references read the installation's store (none, a
    secret-store file, the owner's keyring or Supabase Vault), except the paths listed as
    provider-held, which are only verified at delivery. With a runtime pool, `mint:` issues
    run-bound credentials in the scoped common table the ingress reads (MO-40); standalone
    callers without that pool cannot mint."""

    store: SecretSource | None = None
    match settings.mission_control_secret_store:
        case "file":
            if settings.mission_control_secret_store_path is None:
                raise IntegrationConfigurationError(
                    "the file secret store requires MISSION_CONTROL_SECRET_STORE_PATH"
                )
            store = SecretStoreFile(settings.mission_control_secret_store_path)
        case "keyring":
            store = KeyringSecretSource(settings.mission_control_secret_keyring_service)
        case "supabase_vault":
            dsn = configured(settings.mission_control_secret_vault_dsn)
            if dsn is None:
                raise IntegrationConfigurationError(
                    "the Supabase Vault store requires MISSION_CONTROL_SECRET_VAULT_DSN"
                )
            pool = await asyncpg.create_pool(dsn.get_secret_value(), min_size=0, max_size=2)
            resources.push_async_callback(pool.close)
            store = SupabaseVaultSource(pool)
    return SecretBroker(
        environment=WorkerEnvironmentSource(),
        store=store,
        provider_held=settings.mission_control_provider_held_secrets,
        minter=ScopedSecretMinter(pool) if pool is not None else None,
    )


def _ingress_session_registrar(pool: asyncpg.Pool) -> Any:
    # Registration is worker-side and uses the normal tenant-scoped runtime role.
    from mission_control.bootstrap.ingress_drainer import ProductionSessionRegistrar

    return ProductionSessionRegistrar(pool)


def compose_cursor_cloud(
    settings: Settings,
    pool: asyncpg.Pool,
    payloads: ArtifactPayloadPort,
    *,
    bundles: BundleMaterializer | None,
    secrets: SecretBroker,
    outputs: LaneOutputCustody | None = None,
) -> tuple[CursorCloudHarness, CloudAgentsClient, CursorEnvironments] | None:
    """The `cursor_cloud` lane (FT-G5) over the Cloud Agents API v1 when a Cursor credential
    is bound. Branches are published through the worker's git configuration; the cloud
    projection carries catalog command hooks only (the VM cannot reach the worker).

    MO-06: each run branch is recorded as a fenced `provider_workspace` lease in the common
    component, and a binding's `env_vars_ref` resolves through the deployment's Secret Broker
    (`secrets`, the same one every lane resolves credential references with). MO-11: every
    commit to the run branch is scanned for the values that broker resolved for the run.
    MO-13: a binding's provider environment is applied through the environments API (the
    kit read from the catalog and its base layer from bundle custody, secrets through the
    same broker). The caller closes both returned API clients."""

    if settings.cursor_api_key is None:
        return None
    files = PayloadContextFiles(payloads)
    root = settings.cursor_lease_root or (
        (settings.deep_agent_sandbox_workspace_root or DEFAULT_WORKSPACE_ROOT) / "cursor-leases"
    )
    workspaces_root = root / "cloud-workspaces"
    client = CloudAgentsClient(settings.cursor_api_key)
    environments = CursorEnvironments(
        CursorEnvironmentsClient(settings.cursor_api_key),
        CursorSecretsClient(settings.cursor_api_key),
    )
    kits = EnvironmentKitCatalog(
        PostgresDefinitionRepository(
            pool, catalog_scope=settings.mission_control_catalog_scope or ""
        ),
        bundles=bundles,
    )
    harness = CursorCloudHarness(
        client=client,
        cost_reader=HttpCostReader(client) if settings.cursor_cost_settlement else None,
        publisher=GitBranchPublisher(root / "cloud-mirrors"),
        projections=RenderedProjectionSource(
            cursor_catalog_rows(settings, pool, bundles),
            kernel_hooks=(),
            projectors=HOST_PROJECTORS,
        ),
        artifacts=files,
        inputs=files,
        env_resolver=SecretEnvVarsResolver(secrets),
        signal_environment=RemoteSignalDelivery(
            secrets, pool, origin=settings.mission_control_signal_ingress_origin
        )
        if settings.mission_control_signal_ingress_origin is not None
        else None,
        # The provider isolates the workspace, so no worker holds it: any worker that
        # reattaches re-acquires the same lease, and the backend never materializes a tree.
        workspaces=WorkspaceAllocator(
            ledger=PostgresWorkspaceLeaseStore(pool),
            backend=GitWorkspaceBackend(workspaces_root),
            root=workspaces_root,
            allocator_ref="deployment:cursor_cloud",
        ),
        outputs=outputs,
        environments=CursorEnvironmentProvisioner(
            ProviderEnvironmentService(environments, broker=secrets), kits
        ),
        missing_output_follow_up=settings.cursor_missing_output_followup,
    )
    return harness, client, environments


def compose_hook_callbacks(pool: asyncpg.Pool) -> HookCallbackService:
    """The worker's one Kernel Hook callback service (FT-G3; G11; P3.5): every command-hook
    lane (`cursor_local`, `codex`) answers its `.mission/hooks/kernel.py` through it on the
    loopback listener, and a Deep Agents catalog hook script that declares `callback: service`
    posts its `mc.hook_input.v1` to it; each payload is read by its lane's mapper. Tokens,
    intents and frames persist in the common component."""

    return HookCallbackService(
        tokens=PostgresHookTokenStore(pool),
        intents=PostgresHookIntentLedger(pool),
        mapper=CursorHookMapper(),
        lane_mappers={"codex": CodexHookMapper(), "deep_agents": DeepAgentsHookMapper()},
        fences=KernelHookFenceGate(PostgresStopFenceRepository(pool)),
        frames=PostgresFrameRepository(pool),
        context_reader=hook_context_index,
    )


def compose_cursor_local(
    settings: Settings,
    pool: asyncpg.Pool,
    payloads: ArtifactPayloadPort,
    *,
    bundles: BundleMaterializer | None,
    hooks: HookCallbackService,
    outputs: LaneOutputCustody | None = None,
    secrets: ProcessSecretDelivery | None = None,
) -> CursorLocalHarness | None:
    """The `cursor_local` lane (FT-G3) over the worker's Kernel Hook callback service, when
    a Cursor credential is bound. Leases persist in the common component; the packet and the
    patch artifacts go through the content-addressed payload store; the projection resolves
    the binding's exact catalog pins."""

    if settings.cursor_api_key is None:
        return None
    files = PayloadContextFiles(payloads)
    lease_root = settings.cursor_lease_root or (
        (settings.deep_agent_sandbox_workspace_root or DEFAULT_WORKSPACE_ROOT) / "cursor-leases"
    )
    harness = CursorLocalHarness(
        launcher=SdkBridgeLauncher(
            settings.cursor_api_key, windows_enabled=settings.mission_control_cursor_windows
        ),
        leaser=GitWorktreeLeaser(
            PostgresWorkspaceLeaseStore(pool), lease_root=lease_root, artifacts=files
        ),
        projections=RenderedProjectionSource(
            cursor_catalog_rows(settings, pool, bundles), projectors=HOST_PROJECTORS
        ),
        hooks=hooks,
        artifacts=files,
        inputs=files,
        outputs=outputs,
        mission_layer=compose_mission_layer(settings, pool),
        secrets=secrets,
        settings=CursorLocalSettings(
            lease_root=lease_root,
            callback_base_url=f"http://127.0.0.1:{settings.mission_control_hook_callback_port}",
            default_repository=settings.cursor_local_repository,
        ),
    )
    # FT-G4: the `stop` hook's one `missing_output_policy` follow-up knows the declared outputs.
    hooks.set_stop_policy(harness)
    return harness


class DeploymentOperationRuntime:
    """The deployment's operation runtime around the canonical Deep Agent adapter.

    * Constrained egress: the operation's granted `network_hosts` bound every governed
      browser page its cognition opens (`granted_network_hosts`).
    * After cognition, the parent-boundary completion of the async children it spawned
      (`AsyncChildCompletion`); the records travel with the runtime's event payloads into the
      settlement's digest-bound output payload.

    Every other runtime capability is the wrapped adapter's. RRM-008: a requested cancel
    reaches `execute` as `asyncio.CancelledError` (during cognition or during the children's
    completion wait) and is never caught here; the operation boundary decides whether it is a
    journaled cancel of the unit (`observe_latest` then reports the latest durable
    checkpoint, still inside the granted egress) or anything else (re-raised).
    """

    def __init__(
        self,
        runtime: DeepAgentRuntimeAdapter,
        children: ProductionAsyncSubagentMiddlewareFactory,
        *,
        pool: asyncpg.Pool,
        policies: Mapping[str, AdmissionRule],
        wait_seconds: float,
        launch_verifier: PinnedCapabilityAssetVerifier | None = None,
    ) -> None:
        self._runtime = runtime
        self._children = children
        self._pool = pool
        self._policies = dict(policies)
        self._wait_seconds = wait_seconds
        self._launch_verifier = launch_verifier

    def _verify_launch(self, invocation: RuntimeInvocation) -> None:
        # RRM-009 review: every path that materializes the agent (and so starts its stdio
        # MCP servers) verifies the launch against the pins first, including the
        # cancellation path's `observe_latest`.
        if self._launch_verifier is not None:
            self._launch_verifier.verify_launch(invocation.binding)

    async def execute(
        self, invocation: RuntimeInvocation, resolved_secrets: Mapping[str, str]
    ) -> RuntimeResult:
        self._verify_launch(invocation)
        with granted_network_hosts(invocation.binding.capability_grant.network_hosts):
            result = await self._runtime.execute(invocation, resolved_secrets)
        # The lane stated at sealing whether this attempt binds async children (its
        # heartbeat class); the bytes themselves stay the Deep Agents adapter's.
        dispatch = invocation.binding.lane_dispatch
        if dispatch is None or dispatch.heartbeat_class != "deep_agent_async_children":
            return result
        service, _adapter = self._children.service(invocation.binding, resolved_secrets)
        records = await AsyncChildCompletion(
            service,
            PostgresAsyncSubagentAuthority(self._pool),
            policies=self._policies,
            wait_seconds=self._wait_seconds,
        ).complete(invocation.binding, execution_generation=dispatch.execution_generation)
        return result.model_copy(
            update={
                "event_payloads": (
                    *result.event_payloads,
                    {
                        "kind": ASYNC_CHILD_COMPLETION_KIND,
                        "binding_id": invocation.binding.binding_id,
                        "children": [record.as_payload() for record in records],
                    },
                )
            }
        )

    async def observe_latest(
        self, invocation: RuntimeInvocation, resolved_secrets: Mapping[str, str]
    ) -> RuntimeResult:
        self._verify_launch(invocation)
        with granted_network_hosts(invocation.binding.capability_grant.network_hosts):
            return await self._runtime.observe_latest(invocation, resolved_secrets)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._runtime, name)


@dataclass(frozen=True)
class ProductionOperationComposition:
    """What the factory built for the operation boundary, kept for the worker's readiness."""

    service: OperationExecutionService
    recovery: OperationRecoveryComposition
    capabilities: DeploymentCapabilityRegistry | None
    saver: BaseCheckpointSaver[Any] | None
    payloads: ArtifactPayloadPort
    promotion: ScopedArtifactPromotionService
    candidates: WorkspaceCandidateCaptureService
    lane_turns: LaneTurnService


KnowledgeLaneFactory = Callable[[Settings, asyncpg.Pool], Awaitable[Any]]


class ProductionWorkerActivityCompositionFactory:
    def __init__(
        self,
        client: Client,
        *,
        pins: CapabilityPins | None = None,
        additional_components: DeploymentCapabilityComponents | None = None,
        artifact_validation: ArtifactValidationAuthorityPort | None = None,
        worker_identity: str | None = None,
        claim_lease: timedelta | None = None,
        async_result_policies: Mapping[str, AdmissionRule] | None = None,
        knowledge_lane: KnowledgeLaneFactory | None = None,
    ) -> None:
        self._client = client
        self.hosted_signal_ingress: SignalIngressService | None = None
        self.installation_id: str | None = None
        # Sprint V SV-16: the application this worker serves (set by bootstrap like the
        # installation id) and the composed knowledge lane with its startup receipt.
        self.application_id: str | None = None
        self.knowledge: Any = None
        self._knowledge_lane = knowledge_lane
        self.session_deleters: dict = {}
        self._async_result_policies = dict(
            async_result_policies
            if async_result_policies is not None
            else DEFAULT_ASYNC_RESULT_POLICIES
        )
        self._pins = pins
        self._additional = additional_components
        self._artifact_validation = artifact_validation
        self._worker_identity = worker_identity
        self._claim_lease = claim_lease
        self.operation: ProductionOperationComposition | None = None

    async def build(
        self,
        *,
        settings: Settings,
        control_plane: ControlPlaneService,
        run_control: RunControlService,
        postgres_pool: asyncpg.Pool,
    ) -> WorkerActivityComposition:
        resources = AsyncExitStack()
        try:
            return await self._build(
                resources,
                settings=settings,
                control_plane=control_plane,
                run_control=run_control,
                postgres_pool=postgres_pool,
            )
        except BaseException:
            # RRM-009 review: a composition that fails partway closes what it opened.
            await resources.aclose()
            raise

    async def _compose_knowledge(self, settings: Settings, pool: asyncpg.Pool) -> Any:
        if self._knowledge_lane is not None:
            return await self._knowledge_lane(settings, pool)
        if self.application_id is None or self.installation_id is None:
            return None
        from mission_control.bootstrap.composition import compose_knowledge_lane

        return await compose_knowledge_lane(
            settings,
            pool,
            application_id=self.application_id,
            installation_id=self.installation_id,
        )

    async def _build(
        self,
        resources: AsyncExitStack,
        *,
        settings: Settings,
        control_plane: ControlPlaneService,
        run_control: RunControlService,
        postgres_pool: asyncpg.Pool,
    ) -> WorkerActivityComposition:
        from mission_control.adapters.postgres.knowledge.output_contracts import (
            PostgresOutputContractStore,
        )
        from mission_control.application.human_tasks.packets import NamedOutputReviewPackets

        lane_only = settings.mission_control_worker_role == "lane"
        persistence = None
        if not lane_only:
            persistence = await resources.enter_async_context(
                StandalonePersistenceLifespan(
                    settings.langgraph_checkpoint_dsn,
                    run_setup=settings.langgraph_checkpoint_setup,
                )
            )
        pins = self._pins if self._pins is not None else CapabilityPins.from_settings(settings)
        bundle_reader = None
        if settings.capability_bundle_backend == "supabase":
            # Deployment-owned origin/credential only; never provided by a mission or skill.
            # Redirects are disabled so bearer credentials cannot leave the configured origin.
            storage_http = resources.enter_context(httpx.Client(timeout=30, follow_redirects=False))
            storage_reader = supabase_skill_bundle_reader(settings, http_client=storage_http)
            catalog_scope = settings.mission_control_catalog_scope
            storage_namespace = settings.capability_bundle_namespace
            if not catalog_scope or not storage_namespace:
                raise ValueError(
                    "Supabase skills require trusted storage namespace and catalog scope"
                )
            bundle_reader = await PostgresCapabilityBundleAdmissions(
                postgres_pool,
                catalog_scope=catalog_scope,
                storage_namespace=storage_namespace,
            ).resolve_pins(pins, reader=storage_reader)
        # FT-G3/G11/P3.5: one Kernel Hook callback service for the command-hook lanes and the
        # Deep Agents catalog hook scripts; the worker serves it on loopback when any of
        # those lanes is composed.
        hooks = compose_hook_callbacks(postgres_pool)
        # Sprint V SV-16: the knowledge tools (K01 binding over HTTP, issuer-backed
        # credentials) join the exact registry as ordinary tool components; `describe` ran
        # as a preflight inside the composition, which fails closed when misconfigured.
        knowledge = await self._compose_knowledge(settings, postgres_pool)
        self.knowledge = knowledge
        additional = self._additional
        if knowledge is not None:
            base = additional or DeploymentCapabilityComponents()
            additional = replace(base, tools={**base.tools, **knowledge.registry_tools})
        capabilities = None
        if persistence is not None:
            capabilities = build_deployment_capability_registry(
                settings,
                pins,
                saver=persistence.saver,
                store=persistence.store,
                additional=with_goal_output_schemas(additional),
                bundle_reader=bundle_reader,
                # P3.5 (TR-D4): the real kernel hook ports and the callback the materializer
                # mints for catalog hook scripts of this lane.
                kernel_hooks=compose_kernel_hook_ports(postgres_pool),
                hook_callbacks=hooks,
                hook_callback_base_url=(
                    f"http://127.0.0.1:{settings.mission_control_hook_callback_port}"
                ),
            )
        actor = orchestration_lifecycle_actor()
        payloads = artifact_payload_store(settings)
        bindings = PostgresOperationBindingRepository(postgres_pool)

        def workspaces_for_scope(request_scope: str) -> WorkspaceMaterializationService:
            if not request_scope.strip():
                raise ValueError("workspace materialization requires request scope")
            # Scope is authority from the exact binding, never a caller-controlled path.
            scope_directory = sha256(request_scope.encode("utf-8")).hexdigest()
            return WorkspaceMaterializationService(
                manifests=PostgresWorkspaceManifestRepository(
                    postgres_pool, request_scope=request_scope
                ),
                provisioner=FilesystemWorkspaceProvisioner(
                    (settings.deep_agent_sandbox_workspace_root or DEFAULT_WORKSPACE_ROOT)
                    / scope_directory
                ),
                durable_inputs=_DurableInputsFromPayloads(payloads),
            )

        candidates = WorkspaceCandidateCaptureService(
            materializer_for_scope=workspaces_for_scope,
            contents_for_scope=lambda scope: PostgresWorkspaceCandidateContents(
                postgres_pool, payloads, request_scope=scope
            ),
        )

        def promotion_for_scope(request_scope: str) -> ArtifactPromotionService:
            return ArtifactPromotionService(
                bindings=bindings,
                metadata=PostgresArtifactMetadataRepository(
                    postgres_pool, request_scope=request_scope
                ),
                payloads=payloads,
                workspaces=workspaces_for_scope(request_scope),
                durable_references=PostgresArtifactDurableReferenceRepository(postgres_pool),
                validation_authority=self._artifact_validation
                or StaticArtifactValidationAuthority(
                    permission_outcomes={}, check_outcomes={}, required_check_ids={}
                ),
            )

        promotion = ScopedArtifactPromotionService(promotion_for_scope)
        recovery = compose_postgres_operation_recovery(
            postgres_pool,
            run_control=run_control,
            nudge=TemporalUnitReconciliationNudge(self._client),
            verifier=LangGraphCheckpointDescendantVerifier(
                capabilities.checkpointers if capabilities else {}
            ),
            default_lease=self._claim_lease or DEFAULT_CLAIM_LEASE,
        )
        children = ProductionAsyncSubagentMiddlewareFactory(
            pool=postgres_pool,
            run_control=run_control,
            actor=actor,
            allow_new_spawns=settings.async_subagent_spawning_enabled,
            submitter_identity=settings.async_subagent_submitter_identity,
            policies=self._async_result_policies,
            knowledge_toolset=None if knowledge is None else knowledge.toolset,
        )
        verifier = PinnedCapabilityAssetVerifier(
            pins,
            node_executable=settings.web_research_agent_browser_node,
            registered_mcp_servers=(
                self._additional.mcp_servers if self._additional is not None else None
            ),
        )
        # FT-B2 (ADR-0027): Context Packet files are content-addressed in the payload store;
        # the packer captures producer outputs from custody records and seals into PostgreSQL.
        context_files = PayloadContextFiles(payloads)
        # WI-07 review N1: the Application Profile's trusted-judgment pin (no default pin).
        trusted_validators = trusted_assessment_validators(
            settings.deployments_root, self.application_id
        )
        # OVE-204 slice 5: the Application Profile's `[workspace]` closure caps and retention.
        closure_policy = workspace_closure_profile(settings.deployments_root, self.application_id)
        # WI-02 (ADR-0061): the one transfer materializer. Exact members are staged in the
        # same content-addressed context-file custody the packer uses; sealed plans and attempt
        # receipts persist in the 1.7.0 transfer tables.
        transfer = compose_transfer_materializer(
            postgres_pool,
            payloads,
            context_files,
            gateway=None if knowledge is None else knowledge.toolset.gateway,
            lineage=None if knowledge is None else knowledge.toolset.lineage,
            recheck=None
            if knowledge is None or knowledge.trusted is None
            else knowledge.trusted.recheck,
            linked_recheck=None
            if knowledge is None or knowledge.trusted is None
            else partial(knowledge.trusted.recheck, strict=True),
            trusted_validators=trusted_validators,
        )
        context_packs = ContextPackService(
            artifacts=PostgresArtifactBytes(postgres_pool, payloads),
            selections=PostgresContextSelectionRepository(postgres_pool),
            staging=context_files,
            fork_contexts=ForkContextReader(
                PostgresRunSnapshotRepository(postgres_pool), context_files
            ),
            # FT-D2: a released chain consumer's first packet carries its supplies.
            chain_supplies=PostgresChainSupplies(postgres_pool),
        )
        adapter: DeploymentOperationRuntime | LaneOnlyRuntime = LaneOnlyRuntime()
        if capabilities is not None:
            adapter = DeploymentOperationRuntime(
                DeepAgentRuntimeAdapter(
                    ExactDeepAgentMaterializer(capabilities.registry),
                    async_subagents=children,
                    workspace_outputs=candidates,
                    # SPEC-03 (C1): provider frames persist before any derivation; (C2) their
                    # closing facts become mission events through run control.
                    frames=PostgresFrameRepository(postgres_pool),
                    frame_facts=FrameFactProjector(
                        PostgresFrameRepository(postgres_pool), run_control, actor=actor
                    ),
                    context_inputs=context_files,
                    # WP-TR-2: the capture profile and the `frame-body://` promoter over the
                    # content-addressed payload store (model-input records, full bodies).
                    frame_capture=compose_frame_capture(settings, payloads),
                    # WP-TR-5: where the pinned savers live and the points walk budget.
                    saver_locators=(
                        {
                            item.ref.digest: persistence.locator_digest
                            for item in pins.checkpointers
                            if persistence is not None and persistence.locator_digest
                        }
                    ),
                    points_walk_budget_ms=settings.mission_control_points_walk_budget_ms,
                    knowledge=None if knowledge is None else knowledge.support,
                    transfer=transfer,
                    # OVE-204 slice 5: every attempt's Workspace Closure at its settled
                    # boundary, bodies in the content-addressed payload store.
                    closures=PostgresWorkspaceClosures(postgres_pool, payloads),
                    closure_policy=closure_policy,
                ),
                children,
                pool=postgres_pool,
                policies=self._async_result_policies,
                wait_seconds=settings.async_subagent_completion_wait_seconds,
                launch_verifier=verifier,
            )
        # MO-11: one Secret Broker serves every lane's credential references and deliveries;
        # whatever it resolves is redacted from this process's frames and logs.
        secrets = await compose_secret_broker(settings, resources, postgres_pool)
        install_log_redaction(secrets.registry)
        local_secrets = (
            LocalSignalDelivery(
                secrets, postgres_pool, port=settings.mission_control_hook_callback_port
            )
            if settings.mission_control_local_signal_ingress
            else ProcessSecretDelivery(secrets)
        )
        # MP-20: a Session Lane's `outputs/` files become digest-checked workspace candidates
        # of the exact binding (the families' typed obligations resolve them).
        lane_outputs = WorkspaceCandidateLaneOutputs(
            workspaces=BindingWorkspaceMaterializer(service_for_scope=workspaces_for_scope),
            candidates=candidates,
        )
        # MO-01: every lane's rows resolver materializes skill bundles and hook scripts through
        # the deployment's one bundle custody (signed URLs, verified, cached by digest).
        bundles = compose_bundle_materializer(settings)
        # FT-G3: the real `cursor_local` lane when Cursor is bound (`hooks` was composed
        # above, before the capability registry that hands it to the Deep Agents lane).
        cursor = compose_cursor_local(
            settings,
            postgres_pool,
            payloads,
            bundles=bundles,
            hooks=hooks,
            outputs=lane_outputs,
            secrets=local_secrets,
        )
        if cursor is not None:
            from mission_control.bootstrap.cursor_bridges import recover_released_cursor_bridges

            await recover_released_cursor_bridges(
                settings,
                postgres_pool,
                default_root=DEFAULT_WORKSPACE_ROOT,
                temporal_client=self._client,
            )
        # FT-G5: the real `cursor_cloud` lane over the Cloud Agents API v1.
        cloud = compose_cursor_cloud(
            settings,
            postgres_pool,
            payloads,
            bundles=bundles,
            secrets=secrets,
            outputs=lane_outputs,
        )
        if cloud is not None:
            resources.push_async_callback(cloud[1].aclose)
            resources.push_async_callback(cloud[2].aclose)
        # MP-06/MP-11: one owner ref per worker process fences its native sessions and holds
        # its native approval handles (the broker binds every request to a durable task).
        owner_ref = default_owner_ref(self._worker_identity)
        broker = compose_approval_broker(postgres_pool, connection_ref=owner_ref)
        # MP-07: the local Claude lane when opted in, authenticated and spawnable here.
        claude = compose_claude_local_lane(
            settings,
            postgres_pool,
            payloads,
            broker=broker,
            bundles=bundles,
            outputs=lane_outputs,
            secrets=ProcessSecretDelivery(secrets),
        )
        # MP-08: the local Codex app-server lane under the same conditions.
        codex = compose_codex_local_lane(
            settings,
            postgres_pool,
            payloads,
            broker=broker,
            bundles=bundles,
            hooks=hooks,
            outputs=lane_outputs,
            secrets=local_secrets,
        )
        if (
            settings.mission_control_claude_managed_lane
            or settings.mission_control_codex_agents_lane
        ) and self.installation_id is None:
            raise ValueError("hosted lanes require the trusted application installation id")
        managed, agents, self.session_deleters = compose_hosted_lanes(
            settings=settings,
            pool=postgres_pool,
            payloads=payloads,
            bundles=bundles,
            secrets=secrets,
            broker=broker,
            resources=resources,
            client=self._client,
            installation_id=self.installation_id or "unused",
            signal_ingress=self.hosted_signal_ingress,
        )
        # FT-G1: the lane registry is built once per worker (SPEC-07 section 3).
        lanes = compose_lane_registry(
            settings,
            None if lane_only else DeepAgentsHarness(adapter, secrets),
            cursor_local=cursor,
            cursor_cloud=cloud[0] if cloud is not None else None,
            claude_local=claude,
            codex_local=codex,
            claude_managed=managed,
            codex_agents=agents,
        )
        # FT-F1: the command mailbox; Delivery Reports name what the registered lane declares.
        mailbox = MailboxDeliveryService(
            PostgresCommandMailbox(postgres_pool),
            run_control,
            describe=lambda profile: (
                lanes.describe(profile) if profile in lanes.profiles() else None
            ),
            # FT-F4: a unit a fork reuses runs no turn and takes no queued content.
            reuse=ForkReuseOracle(PostgresForkMaterializationStore(postgres_pool)),
            # MP-12: while a continuation fences the run, held entries stay queued.
            holds=ContinuationHoldOracle(PostgresContinuationRepository(postgres_pool)),
        )
        injections = InterruptAndInjectService(mailbox, packs=context_packs)
        journal_coordinator = JournaledOperationExecutionCoordinator(
            journal=OperationJournalService(
                PostgresAtomicOperationJournalRepository(postgres_pool)
            ),
            run_control=run_control,
            results=payloads,
            actor=actor,
        )
        cost_activities = None
        if settings.cursor_cost_settlement:
            cloud_cost = HttpCostReader(cloud[1]) if cloud is not None else None
            local_cost = (
                LocalHttpBillingReader(settings.cursor_api_key)
                if cursor is not None and settings.cursor_api_key is not None
                else None
            )
            if local_cost is not None:
                resources.push_async_callback(local_cost.aclose)

            async def read_cursor_cost(profile: str, agent_id: str, run_id: str) -> int | None:
                if profile == "cursor_cloud" and cloud_cost is not None:
                    return await cloud_cost(agent_id, run_id)
                if profile == "cursor_local" and local_cost is not None:
                    return await local_cost(agent_id, run_id)
                return None

            cost_activities = CursorCostActivities(
                CursorCostReconciler(
                    PostgresCursorCosts(postgres_pool, journal_coordinator.get_settlement),
                    read_cursor_cost,
                    journal_coordinator,
                    clock=lambda: datetime.now(UTC),
                )
            )
        service = OperationExecutionService(
            cursor_cost_settlement=settings.cursor_cost_settlement,
            lanes=lanes,
            # FT-F3: immediate-cancel Delivery Report milestones on the run's Stop Fence.
            stop_fences=PostgresStopFenceRepository(postgres_pool),
            # FT-F1: delivered mailbox entries are consumed when their turn starts.
            mailbox=mailbox,
            # FT-F2: interrupt_and_inject by the lane's declared semantics.
            injections=injections,
            authority=RunControlOperationAuthority(run_control, control_plane),
            bindings=bindings,
            sandbox=BindingWorkspaceMaterializer(service_for_scope=workspaces_for_scope),
            assets=verifier,
            mcp=verifier,
            secrets=secrets,
            events=RecordedOperationEventSink(),
            budget=RunControlOperationBudgetAuthority(run_control, actor=actor),
            journal=journal_coordinator,
            journal_claimed_by=settings.operation_journal_claimed_by,
            lineage=recovery.lineage,
            # Sprint OC WI-04: completed results are saved before their settlement waits.
            saved_results=PostgresInvocationSettlementStore(postgres_pool),
            settlement_wait_cap=timedelta(seconds=settings.settlement_wait_cap_seconds),
            effect_wait_deadline=timedelta(seconds=settings.settlement_effect_deadline_seconds),
            review_alarm_interval=timedelta(seconds=settings.settlement_review_alarm_seconds),
            fork_reuse=ForkReuseResolver(
                PostgresForkMaterializationStore(postgres_pool), results=payloads, bindings=bindings
            ),
            # RRM-008 step 4: the cancellation saga cancels the unit's active async children
            # with the operation's own scope-bound credential.
            children=ProductionAsyncChildCancellation(
                children, PostgresAsyncSubagentAuthority(postgres_pool), secrets
            ),
        )
        # FT-G2: `lane.turn`, `lane.status`, `lane.cancel` on the cognitive queues. Session
        # Lanes persist frames through the FrameSink and lane state on harness_execution;
        # the Deep Agents lane runs its governed body through `lane.turn` unchanged.
        frame_store = PostgresFrameRepository(postgres_pool)
        lane_states = PostgresLaneExecutionStateStore(postgres_pool)
        # MP-12: continuation of Session Lanes. Each lane registers its hydrator and snapshot
        # port; the operation workflow drives the persisted phase machine on this queue.
        durable_bytes = _DurableInputsFromPayloads(payloads)
        registrations = lane_continuation_registrations(
            cursor_local=cursor,
            cursor_cloud=cloud[0] if cloud is not None else None,
            durable_bytes=durable_bytes,
            snapshot_store=context_files,
            extra=provider_registrations(claude, codex, context_files),
        )
        continuation = compose_lane_continuation(
            postgres_pool,
            run_control,
            packets=context_packs,
            states=lane_states,
            frames=frame_store,
            registrations=registrations,
            settings=continuation_settings(settings),
        )
        lane_turns = LaneTurnService(
            budget_controls=BudgetControlService(
                states=lane_states,
                authority=RunControlOperationAuthority(run_control, control_plane),
                approvals=PostgresApprovalContextProbe(postgres_pool),
                fences=PostgresStopFenceRepository(postgres_pool),
            ),
            lanes=lanes,
            placement=PlacementAdmission(
                PostgresPlacementStore(postgres_pool), settings.mission_control_placement_limits
            ),
            boundary=service,
            frames=frame_store,
            session_registration=(
                _ingress_session_registrar(postgres_pool)
                if settings.mission_control_signal_ingress_origin is not None
                else None
            ),
            states=lane_states,
            secrets=secrets,
            redaction=secrets.registry,
            frame_facts=FrameFactProjector(frame_store, run_control, actor=actor),
            # FT-G4: queued content rides the next send (`wait_then_send`), an injected
            # command replaces the running turn (`cancel_and_replace`), and the frames name
            # a cancelled turn's usage and its Uncertain Effects.
            mailbox=mailbox,
            injections=injections,
            frame_reader=frame_store,
            # MP-06: fenced session ownership held by this worker process (restart = new
            # owner), and the Stop Fence every new native dispatch (create/send) is admitted
            # against before it is issued.
            sessions=WorkerSessionManager(
                owner_ref=owner_ref,
                min_lease=timedelta(seconds=settings.mission_control_session_lease_min_s),
                lease_heartbeats=settings.mission_control_session_lease_heartbeats,
            ),
            fences=PostgresStopFenceRepository(postgres_pool),
            receipt_grace_s=settings.mission_control_dispatch_receipt_grace_s,
            # MP-12: context pressure at a turn's terminal frame and pending transfers.
            continuations=continuation.coordinator,
            # MO-16: every prepared attempt's readiness is recorded, and a session starts only
            # at the launch policy's minimum readiness.
            preparations=EnvironmentPreparationService(
                PostgresEnvironmentPreparationRepository(postgres_pool)
            ),
        )
        self.operation = ProductionOperationComposition(
            service=service,
            recovery=recovery,
            capabilities=capabilities,
            saver=persistence.saver if persistence else None,
            payloads=payloads,
            promotion=promotion,
            candidates=candidates,
            lane_turns=lane_turns,
        )
        if lane_only:
            return WorkerActivityComposition(
                coordinator=None,
                operation=OperationExecutionActivities(
                    service,
                    worker_identity=self._worker_identity,
                    lane_turns=lane_turns,
                    continuation=continuation.activities,
                    cursor_costs=cost_activities,
                ),
                resources=resources,
                hook_callbacks=_served_hook_callbacks(hooks, cursor, codex, capabilities),
            )
        semantic_bindings = PostgresRunSemanticInputBindingRepository(postgres_pool)
        completion = TerminalWorkflowCompletionService(
            runs=run_control,
            results=PostgresWorkflowResultRepository(postgres_pool),
        )
        goal_documents = PostgresGoalDirectedDocumentRepository(postgres_pool)
        # RRM-008 composed: heartbeat timeout per operation class, and a worker drain shorter
        # than every one of them (refused before any worker is created).
        heartbeats = operation_heartbeat_policy(settings)
        heartbeats.verify_graceful_shutdown(settings.worker_graceful_shutdown_seconds)
        # OC-R2: the families rebind a template's sealed binding through the lane that sealed it.
        lane_bindings = LaneRebinders({"deep_agents": DEEP_AGENTS_LANE_BINDINGS})
        coordinator = create_routed_coordinator_activities(
            bindings=semantic_bindings,
            handlers=SemanticHandlerRegistry(),
            # MP-10: Human Gate tasks on the common `human_task` rows; a gate stage's
            # reservation is released through run control before its result is decided.
            human_gates=HumanGateActivities(
                PostgresHumanTaskRepository(postgres_pool),
                settlement=GateReservationSettlement(run_control),
                packets=NamedOutputReviewPackets(PostgresOutputContractStore(postgres_pool)),
            ),
            lifecycle=RunControlLifecycleGateway(
                run_control, F1OrchestrationBindingVerifier(control_plane), actor
            ),
            goal_directed=GoalDirectedCoordinatorDependencies(
                artifacts=PostgresArtifactBytes(postgres_pool, payloads),
                run_control=run_control,
                operation_bindings=bindings,
                templates=goal_documents,
                documents=goal_documents,
                actor=ActorContext(
                    actor_id=GOAL_DIRECTED_WORKER_ACTOR,
                    permissions=frozenset(
                        {"workflow_run.goal_directed", "workflow_run.reserve_budget"}
                    ),
                    authority_refs=frozenset({f"authority:{GOAL_DIRECTED_WORKER_ACTOR}"}),
                ),
                operation_heartbeats=heartbeats,
                context_packs=context_packs,
                linked_exports=PostgresLinkedExports(postgres_pool),
                mailbox=mailbox,
                completions=PostgresCompletionRepository(postgres_pool),
                lane_bindings=lane_bindings,
                # W1 (OVE-169): explicit fulfillment at the convergence boundary.
                fulfillment=compose_output_fulfillment(
                    postgres_pool, trusted_validators=trusted_validators
                ),
            ),
            stagegraph=StageGraphCoordinatorDependencies(
                human_tasks=PostgresHumanTaskRepository(postgres_pool),
                nested_activations=PostgresNestedActivationStore(postgres_pool),
                run_control=run_control,
                repository=PostgresRunControlRepository(postgres_pool),
                operation_bindings=bindings,
                templates=PostgresStageGraphOperationTemplateRepository(postgres_pool),
                human_gate_provider=ManifestStageGraphHumanGateProvider(
                    PostgresManifestSubmissionRepository(postgres_pool),
                    control_plane,
                    run_control,
                    PostgresStageGraphOperationTemplateRepository(postgres_pool),
                ),
                operation_heartbeats=heartbeats,
                context_packs=context_packs,
                linked_exports=PostgresLinkedExports(postgres_pool),
                mailbox=mailbox,
                artifacts=PostgresArtifactBytes(postgres_pool, payloads),
                named_outputs=NamedStageOutputs(
                    PostgresOutputContractStore(postgres_pool),
                    compose_output_fulfillment(
                        postgres_pool, trusted_validators=trusted_validators
                    ),
                ),
                lane_bindings=lane_bindings,
            ),
            completion=completion,
            # OVE-176: nested-body activate/settle/propagate on both family workers.
            nested=_nested_program_activities(
                postgres_pool,
                client=self._client,
                settings=settings,
                run_control=run_control,
                control_plane=control_plane,
                application_id=self.application_id,
                knowledge_toolset=None if knowledge is None else knowledge.toolset,
            ),
        )
        return WorkerActivityComposition(
            coordinator=coordinator,
            operation=OperationExecutionActivities(
                service,
                worker_identity=self._worker_identity,
                lane_turns=lane_turns,
                continuation=continuation.activities,
                cursor_costs=cost_activities,
            ),
            artifacts=ArtifactPromotionActivities(service=promotion, candidates=candidates),
            resources=resources,
            hook_callbacks=_served_hook_callbacks(hooks, cursor, codex, capabilities),
            time_travel=_worker_time_travel(
                capabilities,
                persistence,
                lanes=_session_time_travel(
                    frame_store,
                    context_files,
                    cloud[0] if cloud is not None else None,
                    claude,
                    codex,
                ),
            ),
        )


def _nested_program_activities(pool: asyncpg.Pool, **kwargs: Any) -> Any:
    from mission_control.bootstrap.nested_programs import compose_nested_program_activities

    return compose_nested_program_activities(pool, **kwargs)


def _worker_time_travel(
    capabilities: DeploymentCapabilityRegistry | None,
    persistence: StandalonePersistence | None,
    *,
    lanes: Iterable[TimeTravelLane] = (),
) -> TimeTravelRegistry | None:
    """1.4.4 (P6.1): the Deep Agents time-travel lane over the worker's pinned savers (the
    fork seed copy runs here, on the maintenance queue), naming each saver's location.
    K3 (2026-11-05): every composed Session Lane's `TimeTravelLane` registers beside it
    (`lanes`, see `bootstrap/session_time_travel.py`); a worker without the pinned savers
    still serves the session lanes' reads and seeds."""

    registry = TimeTravelRegistry()
    if capabilities is not None and persistence is not None:
        locators = {
            digest: persistence.locator_digest
            for digest in capabilities.checkpointers
            if persistence.locator_digest
        }
        registry.register(DeepAgentsTimeTravel(capabilities.checkpointers, locators=locators))
    registry.register_all(lanes)
    return registry if registry.lane_profiles else None


def _session_time_travel(
    frames: FrameReader,
    snapshots: PayloadContextFiles,
    cloud: CursorCloudHarness | None,
    claude: object | None,
    codex: object | None,
) -> tuple[TimeTravelLane, ...]:
    from mission_control.bootstrap.session_time_travel import session_lane_time_travel

    return session_lane_time_travel(
        frames,
        snapshots=snapshots,
        branches=cloud.branches if cloud is not None else None,
        claude=claude,
        codex=codex,
    )


def _served_hook_callbacks(
    hooks: HookCallbackService,
    cursor: object | None,
    codex: object | None,
    capabilities: DeploymentCapabilityRegistry | None,
) -> HookCallbackService | None:
    """The worker serves the loopback callback when a lane that calls it is composed: the
    command-hook lanes (`cursor_local`, `codex`) and the Deep Agents lane, whose catalog
    hook scripts post through the endpoint the materializer mints (P3.5)."""

    if cursor is None and codex is None and capabilities is None:
        return None
    return hooks


class _DurableInputsFromPayloads:
    """Governed read-only workspace inputs come from the content-addressed payload store."""

    def __init__(self, payloads: ArtifactPayloadPort) -> None:
        self._payloads = payloads

    async def retrieve(self, durable_ref: str) -> bytes:
        object_ref, _, rest = durable_ref.partition("#")
        # FT-B2: the digest itself contains ':' (`sha256:<hex>`); the size is the last field.
        digest, _, size = rest.rpartition(":")
        if not digest or not size.isdigit():
            raise ValueError(
                "durable workspace input must be addressed as <object_ref>#<sha256>:<size>"
            )
        return await self._payloads.retrieve(
            ArtifactPayloadAddress(
                object_ref=object_ref, content_digest=digest, size_bytes=int(size)
            )
        )


__all__ = [
    "ASYNC_CHILD_COMPLETION_KIND",
    "DEFAULT_ASYNC_RESULT_POLICIES",
    "DeploymentCapabilityComponents",
    "DeploymentCapabilityRegistry",
    "DeploymentOperationRuntime",
    "ProductionAsyncChildCancellation",
    "ProductionAsyncSubagentMiddlewareFactory",
    "ProductionOperationComposition",
    "ProductionWorkerActivityCompositionFactory",
    "artifact_payload_store",
    "build_deployment_capability_registry",
]


class LaneOnlyRuntime:
    """A lane host never executes the legacy Deep Agents operation runtime."""

    async def execute(
        self, invocation: RuntimeInvocation, resolved_secrets: Mapping[str, str]
    ) -> RuntimeResult:
        raise ValueError("Deep Agents operations cannot execute on a lane-only worker")
