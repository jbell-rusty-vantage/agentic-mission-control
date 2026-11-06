"""Composition of the Mission Manifest service (FT-E2 compile, FT-E3 submit and start)."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import asyncpg

from mission_control.adapters.capabilities.capability_pins import CapabilityPins
from mission_control.adapters.deep_agents.compile import deep_agents_lane
from mission_control.adapters.postgres.chains.exports import PostgresChainStartGate
from mission_control.adapters.postgres.chains.store import PostgresChainIntentStore
from mission_control.adapters.postgres.control_plane.definition_repository import (
    PostgresDefinitionRepository,
)
from mission_control.adapters.postgres.control_plane.manifest_submission import (
    PostgresManifestSubmissionRepository,
)
from mission_control.adapters.postgres.frames.transcript_projection import PostgresRunMissionIds
from mission_control.adapters.postgres.orchestration.goal_directed_repository import (
    PostgresGoalDirectedDocumentRepository,
)
from mission_control.adapters.postgres.orchestration.stagegraph_repository import (
    PostgresStageGraphOperationTemplateRepository,
)
from mission_control.adapters.postgres.run_control.cluster_bindings import (
    PostgresRunClusterBindings,
)
from mission_control.adapters.postgres.runtime.run_forks import PostgresForkMaterializationStore
from mission_control.adapters.postgres.runtime.stage3_kernel_repository import (
    PostgresForkRepository,
)
from mission_control.adapters.remote_session.projection import digest as hosted_digest
from mission_control.application.authoring.manifest_launch_inputs import (
    TRUSTED_ASSESSMENT_PIN,
    CapabilityComponentBinding,
    ManifestChainLaunchInputs,
    ManifestLaunchBindings,
    ManifestLaunchInputAuthor,
    ManifestRunDefinitions,
    ServedComponents,
    ServedModel,
)
from mission_control.application.authoring.manifest_service import (
    ManifestCompileService,
    ManifestProgramCompiler,
    MissionManifestService,
)
from mission_control.application.authoring.manifest_submit import (
    LaunchInputPort,
    ManifestSubmitService,
    StoredForkSources,
    SubscriptionPort,
    register_manifest_admission_policies,
)
from mission_control.application.authoring.provider_launch import CatalogProjectionRows
from mission_control.application.authoring.service import ControlPlaneService
from mission_control.application.capabilities.catalog import CatalogService
from mission_control.application.chains.cancellation import RunControlChainCanceller
from mission_control.application.chains.relay import (
    ChainIntentRelay,
    ChainRelayPump,
    LaunchServiceChainStarter,
)
from mission_control.application.environments.kits import (
    CatalogEnvironmentInputs,
    EnvironmentKitCatalog,
)
from mission_control.application.execution.boundary_interventions import (
    BoundaryCommandDeliveryService,
    BoundaryCommandTransport,
    BoundaryInterventionService,
)
from mission_control.application.execution.run_launch import (
    RunLaunchService,
    RunWorkflowSubmitter,
    TemporalClusterIdentity,
)
from mission_control.application.execution.service import (
    AdmissionPolicyRegistry,
    RunControlService,
)
from mission_control.application.execution.unstarted_cancellation import UnstartedRunCancellation
from mission_control.application.installations.registry import ApplicationBinding
from mission_control.application.ports.payloads import ContentAddressedPayloadStore
from mission_control.application.prerequisites.preflight import (
    StoredPrerequisiteLaunchGuard,
)
from mission_control.application.programs.service import orchestration_lifecycle_actor
from mission_control.application.resolution.lane_options import LaneOptionsChecks
from mission_control.application.resolution.registries import LaneRegistry, ModelCatalog
from mission_control.application.subordinates.parent_completion import ASYNC_RESULT_POLICIES
from mission_control.application.watchers.ports import WatcherStartPort
from mission_control.application.workspaces.preferences import FreshPlacementEligibility
from mission_control.bootstrap.application_profiles import (
    compose_application_registry,
    require_hosted_widening_within_ceiling,
)
from mission_control.bootstrap.bundle_custody import compose_bundle_materializer
from mission_control.bootstrap.installation_config import (
    InstallationConfigError,
    load_installation_config,
)
from mission_control.bootstrap.lanes import describe_only_registry, settings_bound_lanes
from mission_control.bootstrap.launch_promises import compose_launch_promises
from mission_control.bootstrap.model_profiles import compose_model_catalog
from mission_control.bootstrap.prerequisites import (
    InstallationOwnerProbes,
    compose_prerequisite_preflight,
)
from mission_control.bootstrap.resolution import compose_manifest_launch_resolver
from mission_control.bootstrap.settings import Settings
from mission_control.bootstrap.signals import configured_network_hosts
from mission_control.contracts.identities import parse_request_scope
from mission_control.domain.authoring.extensions import ExtensionRegistry
from mission_control.domain.execution.data_class import DEFAULT_DATA_CLASS_POLICY, DataClassPolicy

if TYPE_CHECKING:
    from mission_control.adapters.temporal.deployment_composition import (
        DeploymentCapabilityComponents,
    )


def installation_config_values(
    settings: Settings | None,
    *,
    request_scope: str,
    application_binding: ApplicationBinding | None = None,
) -> Mapping[str, str]:
    """The composing Application's non-secret values a manifest ``config:<key>`` resolves to
    (P1); none when no installation configuration file is set or the file does not list the
    Application. A configured file that is missing or invalid, or holds a secret-like key,
    raises ``InstallationConfigError``, as does one no Application can be selected from:
    composition fails, nothing falls back."""

    path = settings.mission_control_installation_config_path if settings is not None else None
    if path is None:
        return {}
    application_id = application_binding.application_id if application_binding else None
    if application_id is None:
        try:
            application_id = parse_request_scope(request_scope).application_id
        except ValueError:
            raise InstallationConfigError(
                "installation configuration is set but no Application is known to select from "
                "it (no application binding and no canonical request scope)"
            ) from None
    return load_installation_config(path).values_for(application_id)


def _scope_application_id(
    request_scope: str, application_binding: ApplicationBinding | None
) -> str:
    """The composing Application: its binding's id, else the canonical request scope's."""

    if application_binding is not None:
        return application_binding.application_id
    return parse_request_scope(request_scope).application_id


def compose_manifest_service(
    pool: asyncpg.Pool,
    *,
    request_scope: str,
    catalog: CatalogService,
    extensions: ExtensionRegistry,
    payload_store: ContentAddressedPayloadStore,
    run_control: RunControlService | None = None,
    admission_policies: AdmissionPolicyRegistry | None = None,
    launches: RunLaunchService | None = None,
    subscriptions: SubscriptionPort | None = None,
    launch_inputs: LaunchInputPort | None = None,
    data_class_policy: DataClassPolicy = DEFAULT_DATA_CLASS_POLICY,
    watchers: WatcherStartPort | None = None,
    settings: Settings | None = None,
    placement_lanes: LaneRegistry | None = None,
    application_binding: ApplicationBinding | None = None,
) -> MissionManifestService:
    """Compile resolves through the tenant's catalog search and lowers onto the compiler of the
    installation catalog (dry-run overlay: compile persists nothing). With run control composed,
    submit publishes the lowered definitions, commits the revision and admits the run; start
    launches through the governed launch service (no launcher: start is unavailable). Data
    Classes are admitted under the Application Binding's ``data_class_policy`` (HL-18)."""

    definitions = PostgresDefinitionRepository(pool, catalog_scope=catalog.catalog_scope)
    programs = ManifestProgramCompiler(definitions, extensions, payload_store)
    # First: an unknown Application refuses the installation configuration file typed (P1).
    config_values = installation_config_values(
        settings, request_scope=request_scope, application_binding=application_binding
    )
    applications: tuple[str, ...] | None = None
    charter_skills: dict[str, str] = {}
    if settings is not None:
        # OC-R4: the manifest's application validates against the installation's profile, and
        # the binding's hosted Data Class widening may not exceed that profile's ceiling (S1).
        application_id = _scope_application_id(request_scope, application_binding)
        profiles = compose_application_registry(settings.deployments_root, (application_id,))
        require_hosted_widening_within_ceiling(profiles.get(application_id), data_class_policy)
        applications = profiles.applications()
        # OVE-204 slice 6: compile mounts each application's knowledge charter skill on its
        # knowledge missions (`[knowledge] charter_skill`, checked at profile load).
        charter_skills = {
            app: charter
            for app in applications
            if (charter := profiles.get(app).knowledge.charter_skill) is not None
        }
    compiler = ManifestCompileService(
        definitions=catalog.definitions,
        search=catalog.search,
        programs=programs,
        # The production projection is partitioned by the installation catalog scope.
        catalog_scope=catalog.catalog_scope,
        # MO-12: Environment Kit pins resolve in the catalog; P1: a `value_ref: config:<key>`
        # resolves in the Application's installation configuration file when one is set
        # (`MISSION_CONTROL_INSTALLATION_CONFIG_PATH`); unset, every such key stays a blocker.
        environment_inputs=CatalogEnvironmentInputs(
            EnvironmentKitCatalog(catalog.definitions),
            config=config_values,
        ),
        data_class_policy=data_class_policy,
        applications=applications,
        # OC-R6: the registered lanes' own options checks (Deep Agents: its model tools).
        lane_options=LaneOptionsChecks((deep_agents_lane(None),)),
        charter_skills=charter_skills,
    )
    prerequisites = compose_prerequisite_preflight(
        pool, binding=application_binding, settings=settings
    )
    registry = placement_lanes
    if registry is None and settings is not None:
        registry = describe_only_registry(
            bound=settings_bound_lanes(settings), allow_unqualified=False
        )

    compiler.configure_placement_eligibility(FreshPlacementEligibility(registry, prerequisites))
    if launches is not None:
        launches.configure_prerequisites(
            StoredPrerequisiteLaunchGuard(
                PostgresManifestSubmissionRepository(pool).run_subscriptions,
                prerequisites,
                runtime_templates=PostgresManifestSubmissionRepository(pool).runtime_templates,
            )
        )
    lifecycle = None
    if run_control is not None:
        if admission_policies is not None:
            register_manifest_admission_policies(admission_policies)
        lifecycle = ManifestSubmitService(
            compiler=compiler,
            programs=programs,
            run_control=run_control,
            submissions=PostgresManifestSubmissionRepository(pool),
            request_scope=request_scope,
            launches=launches,
            launch_inputs=launch_inputs,
            subscriptions=subscriptions,
            watchers=watchers,
            prerequisites=prerequisites,
            # F1-G2: a fork-derived run of a manifest run starts from its source's submission.
            fork_sources=StoredForkSources(
                PostgresForkMaterializationStore(pool), PostgresForkRepository(pool)
            ),
        )
    service = MissionManifestService(
        compiler=compiler,
        request_scope=request_scope,
        lifecycle=lifecycle,
        prerequisites=prerequisites,
    )
    if settings is not None and service.owner_setup is not None:
        service.owner_setup.probes = InstallationOwnerProbes(settings, pool)
    return service


# --- MP-02: the production launch input author and the chain relay -----------------------


def served_components(
    pins: CapabilityPins,
    settings: Settings,
    additional: DeploymentCapabilityComponents | None = None,
) -> ServedComponents:
    """The digests the workers' exact component registry serves (pins plus registrations),
    with what each served model definition serves (OC-R6)."""

    if additional is not None:
        additional.check_models(pins)

    return ServedComponents(
        models=frozenset(item.ref.digest for item in pins.models)
        | frozenset(additional.model_factories if additional is not None else ()),
        model_identities={
            **{item.ref.digest: ServedModel(item.provider, item.model_id) for item in pins.models},
            **(dict(additional.model_identities) if additional is not None else {}),
        },
        qualification=additional.qualification if additional is not None else False,
        sandboxes=frozenset(item.ref.digest for item in pins.sandboxes)
        | frozenset(additional.sandbox_factories if additional is not None else ()),
        checkpointers=frozenset(item.ref.digest for item in pins.checkpointers)
        | frozenset(settings.deep_agent_checkpointer_digests),
        stores=frozenset(item.ref.digest for item in pins.stores)
        | frozenset(settings.deep_agent_store_digests),
        mcp_servers=frozenset(item.ref.digest for item in pins.mcp_servers)
        | frozenset(additional.mcp_servers if additional is not None else ()),
        skills=frozenset(item.bundle_digest for item in pins.skills)
        | frozenset(additional.skill_bundles if additional is not None else ()),
        tools=frozenset(item.ref.digest for item in pins.tools)
        | frozenset(additional.tools if additional is not None else ()),
    )


def resolve_pinned_capabilities(
    bindings: ManifestLaunchBindings, pins: CapabilityPins, *, node_executable: Path | None
) -> ManifestLaunchBindings:
    """Expand ``pinned`` capability bindings into the exact components the pin file states."""

    resolved: dict[str, CapabilityComponentBinding] = {}
    for capability_id, binding in bindings.capabilities.items():
        if binding.pinned is None or binding.resolved:
            resolved[capability_id] = binding
            continue
        update: dict[str, object]
        if binding.kind == "mcp_server":
            if node_executable is None:
                raise ValueError(
                    f"{capability_id}: pinned MCP servers need WEB_RESEARCH_AGENT_BROWSER_NODE"
                )
            update = {
                "mcp_server": pins.mcp_server(binding.pinned).component(
                    node_executable=node_executable
                )
            }
        elif binding.kind == "skill":
            update = {"skill": pins.skill(binding.pinned).component()}
        else:
            update = {"tool": pins.tool(binding.pinned).component()}
        resolved[capability_id] = CapabilityComponentBinding.model_validate(
            {**binding.model_dump(mode="python"), **update}
        )
    return bindings.model_copy(update={"capabilities": resolved})


def compose_projection_rows(pool: asyncpg.Pool, *, settings: Settings) -> CatalogProjectionRows:
    """The launch author's catalog rows, their bundle bytes through the deployment's custody
    (MO-01): without custody a selected skill bundle or hook script refuses the launch."""

    return CatalogProjectionRows(
        PostgresDefinitionRepository(
            pool, catalog_scope=settings.mission_control_catalog_scope or ""
        ),
        bundles=compose_bundle_materializer(settings),
    )


def compose_manifest_launch_inputs(
    pool: asyncpg.Pool,
    *,
    settings: Settings,
    application_id: str,
    run_control: RunControlService,
    control_plane: ControlPlaneService,
    pins: CapabilityPins | None = None,
    additional: DeploymentCapabilityComponents | None = None,
    models: ModelCatalog | None = None,
    definitions: ManifestRunDefinitions | None = None,
    trusted_settlement_ready: Callable[[], bool] | None = None,
) -> ManifestLaunchInputAuthor | None:
    """The production manifest launch author, or ``None`` when no bindings file is set.

    ``application_id`` is the installation's application: it selects the one Application
    Profile (`deployments/<app>/application.toml`) the launch resolves against (OC-R4) and its
    Model Catalog (`deployments/<app>/models.toml`, OC-R6); ``models`` replaces the catalog
    file for a test deployment, as ``pins`` and ``additional`` do for the pin file.
    ``trusted_settlement_ready`` is a trusted composition hook for an explicitly injected
    settlement; it is never populated from a manifest or request. Absent, deployment
    credential/model readiness retains the normal bootstrap check.
    """

    path = settings.manifest_launch_bindings_path
    if path is None:
        return None
    pins = pins if pins is not None else CapabilityPins.from_settings(settings)
    # W1 D9: the knowledge tool components the worker registers are served here too (the one
    # shared definition), so a manifest selecting a knowledge tool is admitted exactly where the
    # worker can run it; absent when the knowledge binding is not configured.
    from dataclasses import replace

    from mission_control.adapters.temporal.deployment_composition import (
        DeploymentCapabilityComponents,
    )
    from mission_control.bootstrap.composition import knowledge_served_tools

    knowledge = knowledge_served_tools(settings, application_id=application_id)
    if knowledge:
        base = additional or DeploymentCapabilityComponents()
        additional = replace(base, tools={**base.tools, **knowledge})
    bindings = resolve_pinned_capabilities(
        ManifestLaunchBindings.load(path),
        pins,
        node_executable=settings.web_research_agent_browser_node,
    )
    # The Deep Agents node roles resolve through the seam (ADR-0063): the lane package owns
    # the deployment's Deep Agents facts; the application is the installation's profile file
    # (OC-R4); models are the installation's Model Catalog (OC-R6).
    resolver = compose_manifest_launch_resolver(
        bindings,
        served_components(pins, settings, additional),
        applications=compose_application_registry(settings.deployments_root, (application_id,)),
        models=(
            models
            if models is not None
            else compose_model_catalog(settings.deployments_root, application_id)
        ),
        provider_secret_env=settings.manifest_provider_secret_env,
        hosted_digest=lambda profile, config, rows, environment: hosted_digest(
            profile, config, rows, installation_id="digest-only", environment=environment
        ),
        network_hosts=configured_network_hosts(settings),
        async_result_policy_refs=frozenset(ASYNC_RESULT_POLICIES),
        allow_unqualified_lanes=settings.allow_unqualified_lanes,
    )
    from mission_control.bootstrap.application_profiles import trusted_assessment_validators
    from mission_control.bootstrap.trusted_judgment import trusted_settlement_composable

    # W1 D30: a promise requiring the application's trusted assessment pin is refused at launch
    # where no trusted settlement composes (the checked-in pin when the profile cannot load).
    assessment_pins = trusted_assessment_validators(settings.deployments_root, application_id)
    return ManifestLaunchInputAuthor(
        # OVE-169: dependent inputs are admitted only where the trusted settlement composes.
        dependent_inputs_admitted=(
            trusted_settlement_ready()
            if trusted_settlement_ready is not None
            else trusted_settlement_composable(settings, application_id)
        ),
        trusted_assessment_pin=next(iter(assessment_pins))
        if assessment_pins
        else TRUSTED_ASSESSMENT_PIN,
        resolver=resolver,
        run_control=run_control,
        control_plane=control_plane,
        # OVE-176: the nested-body launch passes a view that reads a child run as its body.
        definitions=definitions or PostgresManifestSubmissionRepository(pool),
        stage_templates=PostgresStageGraphOperationTemplateRepository(pool),
        goal_templates=PostgresGoalDirectedDocumentRepository(pool),
        # mission/v2: the catalog rows a claude/codex binding's materialization digest renders.
        projection_rows=compose_projection_rows(pool, settings=settings),
    )


def compose_chain_relay_pump(
    pool: asyncpg.Pool,
    *,
    settings: Settings,
    author: LaunchInputPort,
    run_control: RunControlService,
    submitter: RunWorkflowSubmitter,
    request_scopes: Sequence[str],
    lease_owner: str,
    cluster: TemporalClusterIdentity | None = None,
    watchers: WatcherStartPort | None = None,
    application_binding: ApplicationBinding | None = None,
    boundary_transport: BoundaryCommandTransport | None = None,
) -> ChainRelayPump:
    """The chain relay over the governed launch: duplicate deliveries start a run once."""

    launches = RunLaunchService(
        run_control=run_control,
        submitter=submitter,
        # OVE-166 / WI-02: every launch route registers the admitted promises.
        promises=compose_launch_promises(pool),
        mission_ids=PostgresRunMissionIds(pool),
        # MP-22: a released consumer run is bound to the relaying worker's cluster.
        cluster_bindings=PostgresRunClusterBindings(pool) if cluster is not None else None,
        cluster=cluster,
    )
    launches.configure_prerequisites(
        StoredPrerequisiteLaunchGuard(
            PostgresManifestSubmissionRepository(pool).run_subscriptions,
            compose_prerequisite_preflight(pool, binding=application_binding, settings=settings),
            runtime_templates=PostgresManifestSubmissionRepository(pool).runtime_templates,
        )
    )
    relay = ChainIntentRelay(
        store=PostgresChainIntentStore(pool),
        starter=LaunchServiceChainStarter(
            inputs=ManifestChainLaunchInputs(author),
            launches=launches,
            watchers=watchers,
            start_gate=PostgresChainStartGate(pool),
        ),
        canceller=RunControlChainCanceller(
            run_control,
            BoundaryInterventionService(
                run_control,
                BoundaryCommandDeliveryService(run_control, boundary_transport),
            ),
            unstarted=UnstartedRunCancellation(run_control, orchestration_lifecycle_actor()),
        )
        if boundary_transport is not None
        else None,
        lease_owner=settings.chain_relay_lease_owner or lease_owner,
    )
    return ChainRelayPump(
        relay,
        request_scopes,
        interval_seconds=settings.chain_relay_interval_seconds,
        limit=settings.chain_relay_batch_limit,
    )
