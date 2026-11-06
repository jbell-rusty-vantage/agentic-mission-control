"""Concrete per-installation PostgreSQL composition over the common component.

This factory never migrates, seeds identity rows, selects secrets, or connects to a
fallback database. The operator supplies app-bound restricted pools; readiness
requires the attested common mission_control release for this exact binding.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import asyncpg

from mission_control.adapters.postgres.approvals.tasks import PostgresApprovalTaskRepository
from mission_control.adapters.postgres.async_subagents.async_subagents import (
    PostgresAsyncSubagentAuthority,
)
from mission_control.adapters.postgres.chains.store import install_chain_release_hook
from mission_control.adapters.postgres.closed_workflow import PostgresClosedWorkflowAuthority
from mission_control.adapters.postgres.context.continuation_repository import (
    PostgresContinuationRepository,
    PostgresRunIds,
)
from mission_control.adapters.postgres.control_plane.definition_repository import (
    PostgresDefinitionRepository,
)
from mission_control.adapters.postgres.control_plane.manifest_submission import (
    PostgresManifestSubmissionRepository,
)
from mission_control.adapters.postgres.frames.repository import PostgresFrameRepository
from mission_control.adapters.postgres.frames.transcript_projection import PostgresRunMissionIds
from mission_control.adapters.postgres.frames.transcript_reads import (
    PostgresFamilyFactsReader,
    PostgresMissionEventReader,
)
from mission_control.adapters.postgres.human_tasks.repository import PostgresHumanTaskRepository
from mission_control.adapters.postgres.lanes.workspace_leases import PostgresWorkspaceLeaseStore
from mission_control.adapters.postgres.operations.checkpoint_lineage import (
    PostgresCheckpointLineageRepository,
)
from mission_control.adapters.postgres.operations.cognition_points import (
    PostgresCognitionPointRepository,
)
from mission_control.adapters.postgres.orchestration.stagegraph_repository import (
    PostgresStageGraphOperationTemplateRepository,
)
from mission_control.adapters.postgres.run_control.cluster_bindings import (
    PostgresRunClusterBindings,
)
from mission_control.adapters.postgres.run_control.inspection_repository import (
    PostgresBudgetViewReader,
    PostgresInspectionReadRepository,
    PostgresPointsStatusReader,
    PostgresUnitFailureReader,
)
from mission_control.adapters.postgres.run_control.inspection_sections import (
    PostgresInspectionSections,
)
from mission_control.adapters.postgres.run_control.mailbox import PostgresCommandMailbox
from mission_control.adapters.postgres.run_control.run_control_repository import (
    PostgresRunControlRepository,
)
from mission_control.adapters.postgres.run_control.stop_fence import PostgresStopFenceRepository
from mission_control.adapters.postgres.runtime.run_forks import (
    PostgresForkMaterializationStore,
    PostgresForkSourceReader,
    PostgresRunSnapshotRepository,
)
from mission_control.adapters.postgres.runtime.stage3_kernel_repository import (
    RETENTION_DAYS,
    PostgresForkRepository,
)
from mission_control.application.authoring.manifest_fork_admission import (
    ManifestForkAdmissionProvenance,
)
from mission_control.application.authoring.service import ControlPlaneService
from mission_control.application.context.continuation import (
    ContinuationCommands,
    ContinuationTriggers,
    FrameSessionLocator,
)
from mission_control.application.execution.boundary_interventions import (
    BoundaryCommandDeliveryService,
    BoundaryCommandTransport,
    BoundaryInterventionService,
)
from mission_control.application.execution.harness.time_travel import TimeTravelRegistry
from mission_control.application.execution.mailbox import MailboxDeliveryService
from mission_control.application.execution.operations.unit_reconciliation import (
    AcceptedCheckpointVerifier,
    UnitReconciliationNudge,
)
from mission_control.application.execution.run_launch import (
    RunLaunchService,
    RunWorkflowSubmitter,
    TemporalClusterIdentity,
)
from mission_control.application.execution.service import (
    AdmissionPolicyRegistry,
    F1RunConfigurationVerifier,
    FamilyAdmissionRegistry,
    RunControlService,
)
from mission_control.application.frames.artifact_bodies import ArtifactPayloadReader
from mission_control.application.frames.transcript import TranscriptService
from mission_control.application.human_tasks.service import HumanTaskService
from mission_control.application.installations.registry import (
    ApplicationBinding,
    ApplicationRegistry,
    InstallationObservation,
    InstallationUnavailable,
    VerifiedApplicationIdentity,
    request_scope,
)
from mission_control.application.missions.admission import MissionAdmissionService
from mission_control.application.missions.inspection import InspectionSources
from mission_control.application.missions.runtime import MissionControlRuntimeService
from mission_control.application.missions.service import MissionControlService
from mission_control.application.ports.payloads import ContentAddressedPayloadStore
from mission_control.application.prerequisites.preflight import (
    StoredPrerequisiteLaunchGuard,
)
from mission_control.application.programs.fork_templates import StageGraphForkTemplateDerivation
from mission_control.application.recovery.closed_workflow import (
    ClosedWorkflowObserver,
    ClosedWorkflowRecovery,
)
from mission_control.application.recovery.cognitive_seed import (
    CognitiveSeedService,
    ForkSeedRunner,
)
from mission_control.application.recovery.fork_seed import ForkSeedService
from mission_control.application.recovery.run_forks import (
    EffectiveConfigurationBlueprintReader,
    ForkPatchPolicyRegistry,
    LedgerPendingCommands,
    LineageAsyncChildForkClassifier,
    RecordingForkMaterializer,
    RunControlForkAuthority,
    RunSnapshotService,
    SemanticForkService,
)
from mission_control.application.recovery.runtime_recovery import RuntimeForkService
from mission_control.bootstrap.application_profiles import (
    ApplicationProfileError,
    load_application_profile,
)
from mission_control.bootstrap.common_installation import (
    CommonReadiness,
    inspect_common_installation,
    verify_pool_role,
)
from mission_control.bootstrap.launch_promises import compose_launch_promises
from mission_control.bootstrap.operation_recovery_composition import (
    compose_postgres_operation_recovery,
)
from mission_control.bootstrap.prerequisites import compose_prerequisite_preflight
from mission_control.bootstrap.settings import Settings, get_settings
from mission_control.domain.authoring.extensions import ExtensionRegistry
from mission_control.domain.resolution.resolved import KnowledgePortBinding


@dataclass(frozen=True)
class MissionApplicationServices:
    binding: ApplicationBinding
    readiness: CommonReadiness
    catalog_scope: str
    control_plane: ControlPlaneService
    run_control: RunControlService
    lifecycle: MissionControlService
    runtime: MissionControlRuntimeService
    admission: MissionAdmissionService
    launch: RunLaunchService | None
    delivery: BoundaryCommandDeliveryService | None
    snapshots: RunSnapshotService
    forks: SemanticForkService
    fork_receipts: PostgresForkRepository
    materializations: PostgresForkMaterializationStore
    # MP-15: the tenant's mailbox delivery service (lane semantics for coordinator prompts).
    mailbox: MailboxDeliveryService | None = None


# WI-05 (OVE-167): the oldest Knowledge Services verification component Mission Control accepts.
# 2.5.0 (migration 0008) journals every dispatch before native dispatch and stamps native commits,
# so a commit whose protocol receipt was lost is reconstructed instead of staying unresolved.
MIN_KNOWLEDGE_COMPONENT: tuple[int, int, int] = (2, 5, 0)


def knowledge_component_supported(pinned_schema_name: str) -> bool:
    """``knowledge-verification-<major.minor.patch>`` at or above ``MIN_KNOWLEDGE_COMPONENT``.

    Anything else (an unversioned or in-memory store, an older component) is refused at startup.
    """

    match = re.fullmatch(r"knowledge-verification-(\d+)\.(\d+)\.(\d+)", pinned_schema_name)
    if match is None:
        return False
    major, minor, patch = (int(part) for part in match.groups())
    return (major, minor, patch) >= MIN_KNOWLEDGE_COMPONENT


def temporal_cluster_identity(
    *, target: str, address: str, namespace: str, task_queue: str
) -> TemporalClusterIdentity:
    """The cluster this process submits to (MP-22): `TEMPORAL_TARGET` plus the bound address
    and namespace; the label is `<target>:<address>/<namespace>`."""

    return TemporalClusterIdentity(
        cluster_id=f"{target}:{address}/{namespace}",
        target=target,
        address=address,
        namespace=namespace,
        task_queue=task_queue,
    )


async def compose_application_services(
    binding: ApplicationBinding,
    identity: VerifiedApplicationIdentity,
    *,
    runtime_pool: asyncpg.Pool,
    admission_policies: AdmissionPolicyRegistry,
    extensions: ExtensionRegistry,
    payload_store: ContentAddressedPayloadStore,
    storage_mode: Literal["production_common"] = "production_common",
    registry: ApplicationRegistry | None = None,
    boundary_transport: BoundaryCommandTransport | None = None,
    submitter: RunWorkflowSubmitter | None = None,
    family_writer_pool: asyncpg.Pool | None = None,
    family_admissions: FamilyAdmissionRegistry | None = None,
    fork_policies: ForkPatchPolicyRegistry | None = None,
    nudge: UnitReconciliationNudge | None = None,
    closed_workflow_observer: ClosedWorkflowObserver | None = None,
    artifact_payloads: ArtifactPayloadReader | None = None,
    checkpoint_verifier: AcceptedCheckpointVerifier | None = None,
    externalize_above_bytes: int = 256_000,
    cluster: TemporalClusterIdentity | None = None,
    time_travel: Callable[[], TimeTravelRegistry | None] | None = None,
    fork_seed_runner: ForkSeedRunner | None = None,
) -> MissionApplicationServices:
    if registry is not None:
        registry.disable(binding.application_id)
    try:
        binding = ApplicationBinding.model_validate(binding.model_dump(mode="python"))
    except ValueError as error:
        raise InstallationUnavailable("application binding digest or identity mismatch") from error
    if storage_mode != "production_common":
        raise InstallationUnavailable("only the common mission_control component is supported")
    if (
        identity.application_id != binding.application_id
        or identity.installation_id != binding.installation_id
        or identity.issuer not in binding.accepted_issuers
        or not identity.audiences & binding.accepted_audiences
    ):
        raise InstallationUnavailable("identity is not bound to this installation")
    readiness = await inspect_common_installation(runtime_pool, binding)
    if family_writer_pool is not None:
        await inspect_family_writer_installation(
            family_writer_pool, readiness.database_name, binding
        )
    scope = request_scope(identity)
    catalog_scope = f"mc/{binding.installation_id}/{binding.application_id}/catalog"
    catalog = ControlPlaneService(
        PostgresDefinitionRepository(runtime_pool, catalog_scope=catalog_scope),
        extensions,
        payload_store,
        externalize_above_bytes=externalize_above_bytes,
    )
    # FT-D2: chain links release inside the ledger commit that satisfies them.
    install_chain_release_hook()
    repository = PostgresRunControlRepository(runtime_pool, family_writer_pool=family_writer_pool)
    run_control = RunControlService(
        repository, F1RunConfigurationVerifier(catalog), admission_policies, family_admissions
    )
    delivery = (
        BoundaryCommandDeliveryService(run_control, boundary_transport)
        if boundary_transport is not None
        else None
    )
    interventions = BoundaryInterventionService(run_control, delivery)
    snapshot_repository = PostgresRunSnapshotRepository(runtime_pool)
    materializations = PostgresForkMaterializationStore(runtime_pool)
    fork_receipts = PostgresForkRepository(runtime_pool)
    saga = RuntimeForkService(
        repository=fork_receipts,
        authority=RunControlForkAuthority(run_control, repository),
        materializer=RecordingForkMaterializer(
            materializations, retention=lambda at: at + timedelta(days=RETENTION_DAYS)
        ),
    )
    snapshots = RunSnapshotService(
        reads=PostgresInspectionReadRepository(runtime_pool),
        sources=PostgresForkSourceReader(runtime_pool),
        snapshots=snapshot_repository,
        async_children=LineageAsyncChildForkClassifier(
            PostgresAsyncSubagentAuthority(runtime_pool)
        ),
        commands=LedgerPendingCommands(run_control),
        # FT-G4: a fork of a Cursor Local run restores the workspace its last session froze.
        lane_snapshots=PostgresWorkspaceLeaseStore(runtime_pool),
    )
    forks = SemanticForkService(
        snapshots=snapshot_repository,
        saga=saga,
        policies=fork_policies,
        # 1.4.4 (P5.2): the frontier closure reads the source blueprint from its ERC.
        blueprints=EffectiveConfigurationBlueprintReader(catalog),
        admission_provenance=ManifestForkAdmissionProvenance(
            PostgresManifestSubmissionRepository(runtime_pool),
            run_control,
            catalog,
        ),
        # P1 turn 4 (WP-2): `cognitive_seed` forks for lanes forking at R3.
        seeds=CognitiveSeedService(
            points=PostgresCognitionPointRepository(runtime_pool),
            lineage=PostgresCheckpointLineageRepository(runtime_pool),
            time_travel=time_travel or (lambda: None),
            # 1.4.4 (P6.1): the copy runs on the maintenance worker when a runner is given.
            seed_runner=fork_seed_runner,
        ),
    )
    recovery = compose_postgres_operation_recovery(
        runtime_pool, run_control=run_control, nudge=nudge, verifier=checkpoint_verifier
    )
    launch = (
        RunLaunchService(
            prerequisites=StoredPrerequisiteLaunchGuard(
                PostgresManifestSubmissionRepository(runtime_pool).run_subscriptions,
                compose_prerequisite_preflight(runtime_pool, binding=binding),
                runtime_templates=PostgresManifestSubmissionRepository(
                    runtime_pool
                ).runtime_templates,
            ),
            run_control=run_control,
            submitter=submitter,
            forks=fork_receipts,
            materializations=materializations,
            fork_templates=StageGraphForkTemplateDerivation(
                PostgresStageGraphOperationTemplateRepository(runtime_pool)
            ),
            # FT-C4: the root starts with the ledger mission as `mc_mission_id`.
            mission_ids=PostgresRunMissionIds(runtime_pool),
            # OVE-166 / WI-02: the admitted named promises are registered before the submit.
            promises=compose_launch_promises(runtime_pool),
            # MP-22: the run is bound to this cluster before its first submit.
            cluster_bindings=(
                PostgresRunClusterBindings(runtime_pool) if cluster is not None else None
            ),
            cluster=cluster,
        )
        if submitter is not None
        else None
    )
    # FT-F1 / MP-15: one mailbox service per tenant; the coordinator inbox prompts through it.
    mailbox = MailboxDeliveryService(PostgresCommandMailbox(runtime_pool), run_control)
    result = MissionApplicationServices(
        binding=binding,
        mailbox=mailbox,
        readiness=readiness,
        catalog_scope=catalog_scope,
        control_plane=catalog,
        run_control=run_control,
        lifecycle=MissionControlService(
            run_control,
            interventions,
            request_scope=scope,
            stop_fences=PostgresStopFenceRepository(runtime_pool),
            # FT-B4: request_continuation records a trigger for the live session.
            continuations=ContinuationCommands(
                ContinuationTriggers(PostgresContinuationRepository(runtime_pool)),
                FrameSessionLocator(
                    PostgresFrameRepository(runtime_pool), PostgresRunIds(runtime_pool)
                ),
                request_scope=scope,
            ),
            # FT-F1: queue_instruction / add_context admit into the Run's command mailbox.
            mailbox=mailbox,
            forks=materializations,
            # Sprint V SV-16: an accepted cancel cancels the run's open knowledge handles.
            knowledge_stop=await compose_knowledge_stop(
                get_settings(), runtime_pool, application_id=binding.application_id
            ),
            # FT-F6: inspection sections from frames, the ledger, chains and subscriptions.
            inspection=InspectionSources(
                transcripts=TranscriptService(
                    PostgresMissionEventReader(runtime_pool),
                    PostgresFrameRepository(runtime_pool),
                    request_scope=scope,
                    points=PostgresCognitionPointRepository(runtime_pool),
                    family_facts=PostgresFamilyFactsReader(runtime_pool),
                ),
                sections=PostgresInspectionSections(runtime_pool),
                # 1.4.4 (P6.1): the typed `points_incomplete` outcome on `run inspect`.
                points=PostgresPointsStatusReader(runtime_pool),
                # Tracing Stage 2 (F-T3-1): typed unit failures on `run inspect`.
                failures=PostgresUnitFailureReader(runtime_pool),
                # Tracing Stage 2 (FX-TR-BUDGET): the budget account on `run inspect`.
                budget=PostgresBudgetViewReader(runtime_pool),
            ),
            # MP-11: an admitted cancel closes the run's open approval tasks.
            approvals=HumanTaskService(
                PostgresHumanTaskRepository(runtime_pool),
                request_scope=scope,
                approvals=PostgresApprovalTaskRepository(runtime_pool),
            ),
        ),
        runtime=MissionControlRuntimeService(
            snapshots,
            forks,
            request_scope=scope,
            reconciliation_service=recovery.reconciliation,
            # FT-F4: the forked Run's mailbox gets the Snapshot restore and the instruction.
            seeds=ForkSeedService(run_control),
            closed_workflow_recovery=(
                ClosedWorkflowRecovery(
                    run_control,
                    PostgresClosedWorkflowAuthority(runtime_pool, results=artifact_payloads),
                    closed_workflow_observer,
                )
                if closed_workflow_observer is not None
                else None
            ),
        ),
        admission=MissionAdmissionService(run_control, request_scope=scope, launch_service=launch),
        launch=launch,
        delivery=delivery,
        snapshots=snapshots,
        forks=forks,
        fork_receipts=fork_receipts,
        materializations=materializations,
    )
    if registry is not None:
        if registry.bindings.get(binding.application_id) != binding:
            raise InstallationUnavailable("composition binding differs from deployment registry")
        registry.observe(
            binding.application_id,
            InstallationObservation(
                binding.installation_id,
                binding.application_id,
                binding.supabase_project_ref,
                frozenset({readiness.component_version}),
            ),
        )
    return result


async def inspect_family_writer_installation(
    pool: asyncpg.Pool, database_name: str, binding: ApplicationBinding
) -> None:
    """The family writer is a distinct restricted login on the same installation."""
    async with pool.acquire() as connection, connection.transaction(readonly=True):
        role = await verify_pool_role(connection, "mission_control_family_writer")
        actual = await connection.fetch(
            """
            SELECT installation_id, application_id, supabase_project_ref,
                   schema_component_version
            FROM mission_control.application_installation WHERE state = 'active'
            """
        )
    if (
        role["database_name"] != database_name
        or len(actual) != 1
        or actual[0]["installation_id"] != binding.installation_id
        or actual[0]["application_id"] != binding.application_id
        or actual[0]["supabase_project_ref"] != binding.supabase_project_ref
        or actual[0]["schema_component_version"] != binding.required_component_version
    ):
        raise InstallationUnavailable("family writer points to another installation")


# --------------------------------------------------------------------------------------
# Sprint V SV-16: the application knowledge binding (gateway, journal, handles, minter,
# HTTP client, submissions, tools) composed from settings, with a `describe` preflight.
# --------------------------------------------------------------------------------------

KNOWLEDGE_REQUIRED_ENV = (
    "KNOWLEDGE_BINDING_URL",
    "KNOWLEDGE_BINDING_AUDIENCE",
    "KNOWLEDGE_ISSUER",
    "KNOWLEDGE_ISSUER_KEY_FILE",
)


class KnowledgeConfigurationError(ValueError):
    """The knowledge binding is required or partially configured but incomplete (fail closed)."""


@dataclass(frozen=True)
class KnowledgeConfiguration:
    application_id: str
    # The application's knowledge port (its Application Profile `[knowledge]`, OC-R4).
    knowledge: KnowledgePortBinding
    url: str
    audience: str
    issuer: str
    key_file: Path
    key_id: str | None
    retiring_key_file: Path | None
    retiring_key_id: str | None
    lifetime_seconds: int
    subject: str
    max_polls: int
    timeout_seconds: float
    describe_tenant: str | None
    # W1 D6: the KS component installation (unset: the MC installation id, one shared id).
    component_installation_id: str | None = None

    @property
    def binding_id(self) -> str:
        return self.knowledge.binding_id

    def knowledge_installation(self, installation_id: str) -> str:
        """The installation every K01 origin names: the component's when configured."""

        return self.component_installation_id or installation_id


def knowledge_configuration(
    settings: Settings, *, application_id: str
) -> KnowledgeConfiguration | None:
    """``None`` when nothing is configured and nothing is required; otherwise complete or fail.

    Names the missing environment variables, never any value.
    """

    values = {
        "KNOWLEDGE_BINDING_URL": settings.knowledge_binding_url,
        "KNOWLEDGE_BINDING_AUDIENCE": settings.knowledge_binding_audience,
        "KNOWLEDGE_ISSUER": settings.knowledge_issuer,
        "KNOWLEDGE_ISSUER_KEY_FILE": settings.knowledge_issuer_key_file,
    }
    configured = [name for name, value in values.items() if value]
    if not configured and not settings.knowledge_gateway_required:
        return None
    missing = [name for name in KNOWLEDGE_REQUIRED_ENV if not values[name]]
    if settings.knowledge_gateway_required and not settings.knowledge_component_installation_id:
        # W1 D6: a required binding names the component installation explicitly; MC never
        # assumes its own installation id is the one the executor serves.
        missing.append("KNOWLEDGE_COMPONENT_INSTALLATION_ID")
    if missing:
        raise KnowledgeConfigurationError(
            "knowledge binding is required or partially configured; missing " + ", ".join(missing)
        )
    # W1 D5: the issuer and audience travel as K01 `Name`s (Origin.issuer, CredentialClaims
    # iss/aud; KS NameSchema); a value the protocol refuses fails here, naming the variable.
    from pydantic import TypeAdapter, ValidationError

    from mission_control.contracts.knowledge_protocol import Name

    invalid = []
    for name in ("KNOWLEDGE_ISSUER", "KNOWLEDGE_BINDING_AUDIENCE"):
        try:
            TypeAdapter(Name).validate_python(values[name])
        except ValidationError:
            invalid.append(name)
    component = settings.knowledge_component_installation_id
    if component is not None:
        # The KS component database pins `installation_id uuid`: a canonical lowercase UUID.
        from uuid import UUID

        try:
            canonical = str(UUID(component)) == component
        except ValueError:
            canonical = False
        if not canonical:
            invalid.append("KNOWLEDGE_COMPONENT_INSTALLATION_ID")
    if "KNOWLEDGE_COMPONENT_INSTALLATION_ID" in invalid:
        raise KnowledgeConfigurationError(
            "KNOWLEDGE_COMPONENT_INSTALLATION_ID must be the component's canonical lowercase UUID"
        )
    if invalid:
        raise KnowledgeConfigurationError(
            ", ".join(invalid) + " must be a K01 Name (^[a-z][a-z0-9_.-]{0,119}$; e.g. "
            "mission-control.<application>), the value the executor pins too"
        )
    # OC-R4: the binding, apply contract and payload layout are the application's profile.
    try:
        knowledge = load_application_profile(
            settings.deployments_root, application_id
        ).profile.knowledge
    except ApplicationProfileError as error:
        raise KnowledgeConfigurationError(
            f"no knowledge binding for application {application_id}: {error}"
        ) from None
    assert settings.knowledge_binding_url and settings.knowledge_binding_audience
    assert settings.knowledge_issuer and settings.knowledge_issuer_key_file
    return KnowledgeConfiguration(
        application_id=application_id,
        knowledge=knowledge,
        url=settings.knowledge_binding_url,
        audience=settings.knowledge_binding_audience,
        issuer=settings.knowledge_issuer,
        key_file=settings.knowledge_issuer_key_file,
        key_id=settings.knowledge_issuer_key_id,
        retiring_key_file=settings.knowledge_issuer_retiring_key_file,
        retiring_key_id=settings.knowledge_issuer_retiring_key_id,
        lifetime_seconds=settings.knowledge_credential_lifetime_seconds,
        subject=settings.knowledge_subject,
        max_polls=settings.knowledge_gateway_max_polls,
        timeout_seconds=settings.knowledge_binding_timeout_seconds,
        describe_tenant=settings.knowledge_describe_tenant,
        component_installation_id=settings.knowledge_component_installation_id,
    )


def knowledge_served_tools(settings: Settings, *, application_id: str) -> dict[str, Any]:
    """W1 D9: the knowledge tool components this installation serves (digest -> tool), the same
    set for the API launch author, the worker registry and the chain-relay author.

    Served exactly when the worker composes the knowledge lane: the binding is configured (any
    KNOWLEDGE_* set, or KNOWLEDGE_GATEWAY_REQUIRED). A required or partial configuration that is
    incomplete refuses here, naming the variables, as the worker does; nothing configured serves
    none, so a manifest selecting a knowledge tool is refused truthfully.
    """

    if knowledge_configuration(settings, application_id=application_id) is None:
        return {}
    from mission_control.adapters.deep_agents.knowledge_tools import served_knowledge_tools

    return served_knowledge_tools()


@dataclass(frozen=True)
class KnowledgeLaneComposition:
    """What the worker mounts: the Deep Agents lane support, its exact tool components and
    registry entries, and the sanitized startup receipt of the describe preflight."""

    configuration: KnowledgeConfiguration
    gateway: Any
    submissions: Any
    toolset: Any
    support: Any
    components: tuple[Any, ...]
    registry_tools: dict[str, Any]
    startup_receipt: dict[str, Any]
    # Host-recorded use decisions `knowledge_apply` resolves (durable, release 1.7.0 0059).
    decisions: Any = None
    # OVE-169: the trusted settlement with real independent evaluators (None: not configured).
    trusted: Any = None


def read_intent_bound(settings: Settings) -> bool:
    """Whether the deployment's manifest launch bindings bind the ``knowledge_read_intent``
    tool (catalog capability ``tool.knowledge-read-intent``). An absent or unreadable file
    binds nothing here; the launch-bindings preflight refuses an unreadable one."""

    from mission_control.adapters.deep_agents.knowledge_tools import knowledge_capability_id
    from mission_control.application.authoring.manifest_launch_inputs import (
        ManifestLaunchBindings,
    )

    path = settings.manifest_launch_bindings_path
    if path is None:
        return False
    try:
        bindings = ManifestLaunchBindings.load(path)
    except ValueError:
        return False
    return knowledge_capability_id("knowledge_read_intent") in bindings.capabilities


def _knowledge_gateway(
    configuration: KnowledgeConfiguration,
    runtime_pool: asyncpg.Pool,
    client: Any | None,
    now: Callable[[], datetime],
) -> tuple[Any, Any, Any]:
    """The gateway over the journal (1.5.0), durable handles (1.6.0), the issuer-backed
    minter and the K01 client; exact bytes through the executor's `artifacts` route."""

    from mission_control.adapters.knowledge.credentials import (
        Ed25519CredentialMinter,
        load_signing_key,
    )
    from mission_control.adapters.knowledge.http_client import (
        HttpExactContentReader,
        HttpKnowledgeBindingClient,
    )
    from mission_control.adapters.postgres.knowledge.handles import PostgresKnowledgeHandleStore
    from mission_control.adapters.postgres.knowledge.operations import PostgresKnowledgeJournal
    from mission_control.adapters.postgres.knowledge.use_decisions import PostgresUseDecisionStore
    from mission_control.application.knowledge.gateway import KnowledgeGateway

    active = load_signing_key(configuration.key_file, kid=configuration.key_id)
    retiring = (
        None
        if configuration.retiring_key_file is None
        else load_signing_key(configuration.retiring_key_file, kid=configuration.retiring_key_id)
    )
    minter = Ed25519CredentialMinter(
        issuer=configuration.issuer,
        active=active,
        retiring=retiring,
        lifetime_seconds=configuration.lifetime_seconds,
        clock=now,
    )
    binding_client = client or HttpKnowledgeBindingClient(
        configuration.url, timeout_seconds=configuration.timeout_seconds
    )
    content = (
        binding_client
        if hasattr(binding_client, "fetch")
        else HttpExactContentReader(binding_client)
    )
    gateway = KnowledgeGateway(
        client=binding_client,
        journal=PostgresKnowledgeJournal(runtime_pool),
        handles=PostgresKnowledgeHandleStore(runtime_pool),
        minter=minter,
        content=content,
        # WI-03: the durable decisions the trusted bridge records (1.7.0, 0059); no process memory.
        decisions=PostgresUseDecisionStore(runtime_pool),
        knowledge=configuration.knowledge,
        audience=configuration.audience,
        max_polls=configuration.max_polls,
        clock=now,
    )
    return gateway, active, retiring


async def compose_knowledge_stop(
    settings: Settings,
    runtime_pool: asyncpg.Pool,
    *,
    application_id: str,
    client: Any | None = None,
) -> Any | None:
    """The API side of a run-level stop: the gateway whose `cancel_run` cancels a stopped
    run's open knowledge handles. `None` when the knowledge binding is not configured."""

    configuration = knowledge_configuration(settings, application_id=application_id)
    if configuration is None:
        return None
    gateway, _active, _retiring = _knowledge_gateway(
        configuration, runtime_pool, client, lambda: datetime.now(UTC)
    )
    return gateway


async def compose_knowledge_review(
    settings: Settings,
    runtime_pool: asyncpg.Pool,
    *,
    application_id: str,
    installation_id: str,
    request_scope: str,
    client: Any | None = None,
) -> Any | None:
    """The API side of the operator review route (W1 D2): one tenant's
    ``KnowledgeReviewService`` over the KS review path (``ReviewRelay``) of this application's
    knowledge binding. `None` when the knowledge binding is not configured."""

    from mission_control.adapters.postgres.knowledge.output_contracts import (
        PostgresOutputContractStore,
    )
    from mission_control.adapters.postgres.knowledge.run_actors import PostgresRunActors
    from mission_control.application.knowledge.judgment import (
        EvaluatorAttemptReset,
        ReviewRelay,
    )
    from mission_control.application.knowledge.review import KnowledgeReviewService
    from mission_control.application.outputs.fulfillment import OutputFulfillmentService
    from mission_control.application.outputs.submission_service import SubmissionService

    configuration = knowledge_configuration(settings, application_id=application_id)
    if configuration is None:
        return None

    def now() -> datetime:
        return datetime.now(UTC)

    gateway, _active, _retiring = _knowledge_gateway(configuration, runtime_pool, client, now)
    outputs = PostgresOutputContractStore(runtime_pool)
    return KnowledgeReviewService(
        ReviewRelay(gateway, clock=now),
        runs=PostgresRunActors(runtime_pool),
        assessments=outputs,
        # W1 fix G S2: the audited operator reset of exhausted evaluator attempts. This service
        # only records the reset assessment (no refresh, no frontier evaluation), so it composes
        # no reference-use, effect or member-decision evidence ports; fulfillment is decided by
        # `compose_output_fulfillment` and the trusted settlement's service.
        resets=EvaluatorAttemptReset(
            OutputFulfillmentService(
                outputs, SubmissionService(outputs, contracts=outputs, clock=now), clock=now
            ),
            outputs,
            clock=now,
        ),
        request_scope=request_scope,
        issuer=configuration.issuer,
        producer_subject=configuration.subject,
        knowledge_installation_id=configuration.knowledge_installation(installation_id),
        clock=now,
    )


async def compose_knowledge_lane(
    settings: Settings,
    runtime_pool: asyncpg.Pool,
    *,
    application_id: str,
    installation_id: str,
    client: Any | None = None,
    clock: Callable[[], datetime] | None = None,
) -> KnowledgeLaneComposition | None:
    """Compose the knowledge binding from settings; ``None`` when it is not configured.

    The ``describe`` preflight runs under a standalone service credential before anything is
    mounted: the descriptor must name this binding, application and signing issuer and speak
    ``ks.knowledge_operation.v2``; its canonical digest is recorded in the startup receipt.
    """

    from urllib.parse import urlsplit

    from mission_control.adapters.deep_agents.knowledge_tools import (
        KnowledgeLaneSupport,
        knowledge_registry_tools,
        knowledge_tool_components,
    )
    from mission_control.adapters.postgres.knowledge.invocation_locator import (
        PostgresInvocationLocator,
    )
    from mission_control.adapters.postgres.knowledge.lineage import PostgresContentLineageStore
    from mission_control.adapters.postgres.knowledge.output_contracts import (
        PostgresOutputContractStore,
    )
    from mission_control.adapters.postgres.knowledge.retained_reads import (
        PostgresRetainedReadStore,
    )
    from mission_control.application.knowledge.access import instant
    from mission_control.application.knowledge.operations import KnowledgeRefused
    from mission_control.application.knowledge.toolset import KnowledgeToolset
    from mission_control.application.outputs.submission_service import SubmissionService
    from mission_control.contracts.knowledge_protocol import Origin, digest_canonical

    configuration = knowledge_configuration(settings, application_id=application_id)
    if configuration is None:
        return None
    now = clock or (lambda: datetime.now(UTC))
    gateway, active, retiring = _knowledge_gateway(configuration, runtime_pool, client, now)
    # W1 D6: the executor authorizes the origin against the component installation it serves.
    knowledge_installation = configuration.knowledge_installation(installation_id)
    service_origin = Origin(
        kind="standalone",
        installationId=knowledge_installation,
        applicationId=application_id,
        tenantId=configuration.describe_tenant or installation_id,
        issuer=configuration.issuer,
        subject=configuration.subject,
        mission=None,
        recoveryAuthorityRef=None,
        invocationId=f"startup-{installation_id}",
        authenticatedAt=instant(now()),
    )
    try:
        descriptor = await gateway.describe(service_origin)
    except KnowledgeRefused as refused:
        hint = (
            " (the executor installs another binding, tenant or component installation than "
            "KNOWLEDGE_COMPONENT_INSTALLATION_ID / KNOWLEDGE_DESCRIBE_TENANT name)"
            if refused.code == "SCOPE_DENIED"
            else ""
        )
        raise KnowledgeConfigurationError(
            f"knowledge.describe preflight refused: {refused.code}{hint}"
        ) from None
    problems = [
        name
        for name, ok in (
            ("protocol", "ks.knowledge_operation.v2" in descriptor.protocolVersions),
            ("binding", descriptor.binding == configuration.binding_id),
            ("application", descriptor.application == application_id),
            # `signingIssuer` names the binding's own run-seal signer (KS default
            # `knowledge-services`), not the credential issuer: recorded, never compared with
            # KNOWLEDGE_ISSUER (the T1-MC parity run found the earlier equality check wrong).
            ("receiptLookup", descriptor.guarantees.receiptLookup == "by_effect_key"),
            # WI-05: native receipt reconstruction needs the KS component's dispatch journal.
            ("componentVersion", knowledge_component_supported(descriptor.pinnedSchema.name)),
        )
        if not ok
    ]
    if problems:
        raise KnowledgeConfigurationError(
            "knowledge binding descriptor does not match this deployment: " + ", ".join(problems)
        )
    # OVE-204 slice 4: a deployment whose launch bindings bind `knowledge_read_intent` needs a
    # binding that serves `knowledge.read_intent` (a KS backend with the host-injected read
    # intent port); refused here rather than at the first agent read.
    read_intent_served = "knowledge.read_intent" in descriptor.operations
    if not read_intent_served and read_intent_bound(settings):
        raise KnowledgeConfigurationError(
            "the manifest launch bindings bind knowledge_read_intent "
            "(tool.knowledge-read-intent) but the knowledge binding descriptor does not serve "
            "knowledge.read_intent"
        )
    # WI-03 S7: a scripted (deterministic double) census auditor is disposable-only; the
    # producer-started `report.assess` path refuses it on any other installation.
    if descriptor.auditorKind == "scripted" and not settings.knowledge_disposable_installation:
        raise KnowledgeConfigurationError(
            "the knowledge binding runs a scripted census auditor; report.assess is refused "
            "outside a disposable installation (KNOWLEDGE_DISPOSABLE_INSTALLATION)"
        )
    # K01 descriptors carry lists only (no sets); the canonical digest of the model itself.
    descriptor_digest = digest_canonical(descriptor)
    # Release 1.7.0: one store serves the submission rows and the output-contract records.
    output_store = PostgresOutputContractStore(runtime_pool)
    submissions = SubmissionService(
        output_store, assessor=gateway, contracts=output_store, clock=now
    )
    toolset = KnowledgeToolset(
        gateway=gateway,
        submissions=submissions,
        issuer=configuration.issuer,
        subject=configuration.subject,
        clock=now,
        lineage=PostgresContentLineageStore(runtime_pool),
        knowledge_installation_id=knowledge_installation,
        # Provenance slice 1 (OVE-204): origins name the ledger mission and activation.
        locator=PostgresInvocationLocator(runtime_pool),
        # Provenance slice 4 (OVE-204): every knowledge_read_intent read is recorded.
        retained_reads=PostgresRetainedReadStore(runtime_pool),
    )
    from mission_control.bootstrap.trusted_judgment import (
        TrustedCompositionError,
        compose_trusted_settlement,
        trusted_receipt,
    )

    try:
        toolset.trusted = compose_trusted_settlement(
            settings,
            runtime_pool,
            application_id=application_id,
            gateway=gateway,
            output_store=output_store,
            submissions=submissions,
            auditor_kind=descriptor.auditorKind,
            clock=now,
        )
    except TrustedCompositionError as error:
        raise KnowledgeConfigurationError(str(error)) from None
    if toolset.trusted is None:
        from mission_control.application.knowledge.trusted_settlement import (
            UncomposedTrustedSettlement,
        )
        from mission_control.bootstrap.application_profiles import trusted_assessment_validators

        # W1 D30: a revision the trusted pin must judge waits here instead of finalizing.
        assessment_pins = trusted_assessment_validators(settings.deployments_root, application_id)
        toolset.uncomposed_trusted = UncomposedTrustedSettlement(
            store=output_store,
            assessment_pin=next(iter(assessment_pins))
            if assessment_pins
            else "knowledge.report.assess@1",
        )
    from mission_control.bootstrap.trusted_judgment import compose_native_write

    toolset.native = compose_native_write(
        toolset.trusted,
        gateway,
        output_store,
        capability_pin=toolset.capability_pins.get(
            "knowledge_apply", "knowledge.knowledge_apply@1"
        ),
    )
    support = KnowledgeLaneSupport(toolset)
    registry_tools = knowledge_registry_tools(support.tools)
    from mission_control.adapters.deep_agents.knowledge_tools import served_knowledge_tools

    if set(registry_tools) != set(served_knowledge_tools()):
        # W1 D9: the launch authors serve the shared definition; the live tools must match it.
        raise KnowledgeConfigurationError(
            "the worker's knowledge tools differ from the served knowledge tool definitions"
        )
    location = urlsplit(configuration.url)
    receipt = {
        "schema": "mc.knowledge_binding_startup.v1",
        "application_id": application_id,
        "binding": configuration.binding_id,
        "protocol_version": "ks.knowledge_operation.v2",
        "endpoint": f"{location.scheme}://{location.hostname}:{location.port or ''}",
        "audience": configuration.audience,
        "issuer": configuration.issuer,
        "component_installation_id": knowledge_installation,
        "active_kid": active.kid,
        "retiring_kid": None if retiring is None else retiring.kid,
        "credential_lifetime_seconds": configuration.lifetime_seconds,
        "descriptor_digest": descriptor_digest,
        "signing_issuer": descriptor.signingIssuer,
        "operations": sorted(descriptor.operations),
        "read_intent_served": read_intent_served,
        "auditor_kind": descriptor.auditorKind,
        "guarantees": descriptor.guarantees.model_dump(mode="json"),
        "trusted_evaluators": trusted_receipt(toolset.trusted),
    }
    return KnowledgeLaneComposition(
        configuration=configuration,
        gateway=gateway,
        submissions=submissions,
        toolset=toolset,
        support=support,
        components=knowledge_tool_components(support.tools),
        registry_tools=registry_tools,
        startup_receipt=receipt,
        decisions=gateway.decisions,
        trusted=toolset.trusted,
    )
