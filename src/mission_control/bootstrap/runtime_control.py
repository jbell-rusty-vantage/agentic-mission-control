"""Production runtime composition of the BellLabs API (RRM-009, CP-050 prerequisite).

`compose_runtime_control` attaches, on `app.state` and before the first request, everything
the governed facade needs to drive and observe the macro runtime through Temporal:

* the production root submitter (`TemporalWorkflowSubmitter.for_production`, Search
  Attribute policy `required`, REQ-CP-EXEC-015) and the `RunLaunchService` behind
  `POST /run-control/v1/runs/{run_id}/launch`;
* inspection sources (REQ-CP-RUN-011/012): the Temporal Visibility reader, the registered
  persistent saver's checkpoint history reader, the PostgreSQL async-child detail repository and
  one shared cursor key;
* boundary intervention delivery (RRM-007, review F6): the Temporal transport for inline
  delivery, the reconciliation nudge and verifier, and the delivery relay that re-drives
  accepted commands whose inline delivery failed;
* fork patch policies (RRM-006) and the generic artifact submitter.

Readiness verifies the namespace's Search Attributes and never mutates it; registration is
the separate administrative step (`scripts/register_belllabs_search_attributes.py`).
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import AsyncExitStack, suppress
from dataclasses import dataclass

from fastapi import FastAPI
from starlette.requests import Request
from temporalio.client import Client

from mission_control.adapters.capabilities.capability_pins import CapabilityPins
from mission_control.adapters.deep_agents.checkpoint_history import (
    LangGraphCheckpointHistoryReader,
)
from mission_control.adapters.deep_agents.checkpoint_verifier import (
    LangGraphCheckpointDescendantVerifier,
)
from mission_control.adapters.deep_agents.persistence import StandalonePersistenceLifespan
from mission_control.adapters.deep_agents.runtime_persistence_verifier import (
    verify_runtime_persistence,
)
from mission_control.adapters.deep_agents.time_travel import DeepAgentsTimeTravel
from mission_control.adapters.postgres.async_subagents.async_subagent_detail_repository import (
    PostgresAsyncSubagentDetailRepository,
)
from mission_control.adapters.postgres.async_subagents.async_subagents import (
    PostgresAsyncSubagentAuthority,
)
from mission_control.adapters.postgres.control_plane.manifest_submission import (
    PostgresManifestSubmissionRepository,
)
from mission_control.adapters.postgres.frames.repository import PostgresFrameRepository
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
from mission_control.adapters.temporal.artifact_submission import TemporalGenericArtifactSubmitter
from mission_control.adapters.temporal.boundary_commands import TemporalBoundaryCommandTransport
from mission_control.adapters.temporal.coordinator_runtime import coordinator_task_queues
from mission_control.adapters.temporal.registration.task_queues import generic_artifact_task_queue
from mission_control.adapters.temporal.search_attributes import (
    SearchAttributeRegistrationError,
    verify_belllabs_search_attributes,
)
from mission_control.adapters.temporal.submission import TemporalWorkflowSubmitter
from mission_control.adapters.temporal.unit_reconciliation import (
    TemporalFamilyLiabilityHint,
    TemporalUnitReconciliationNudge,
)
from mission_control.adapters.temporal.visibility import TemporalVisibilityInspectionReader
from mission_control.application.execution.boundary_relay import BoundaryCommandRelay
from mission_control.application.execution.harness.time_travel import TimeTravelRegistry
from mission_control.application.execution.liability_hints import FamilyLiabilityHints
from mission_control.application.execution.run_launch import RunLaunchService
from mission_control.application.installations.registry import ApplicationBinding
from mission_control.application.prerequisites.preflight import (
    StoredPrerequisiteLaunchGuard,
)
from mission_control.application.programs.fork_templates import StageGraphForkTemplateDerivation
from mission_control.application.programs.service import orchestration_lifecycle_actor
from mission_control.application.recovery.run_forks import ForkPatchPolicyRegistry
from mission_control.application.subordinates.parent_effects import RunControlAsyncChildEffects
from mission_control.application.subordinates.service import AsyncSubagentService
from mission_control.application.subordinates.usage_reconciliation import (
    AsyncChildUsageReconciliation,
    ProviderNotComposed,
)
from mission_control.bootstrap.composition import temporal_cluster_identity
from mission_control.bootstrap.launch_promises import compose_launch_promises
from mission_control.bootstrap.prerequisites import compose_prerequisite_preflight
from mission_control.bootstrap.session_time_travel import session_lane_time_travel
from mission_control.bootstrap.settings import Settings
from mission_control.interfaces.http.run_control import (
    get_boundary_intervention_service,
    get_run_control_service,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RuntimeControlComposition:
    """What the API composed. `readiness` stays in process and in the log; `/health/ready`
    reports status and mode only (RRM-009 review)."""

    submitter: TemporalWorkflowSubmitter
    launch: RunLaunchService
    relay: BoundaryCommandRelay
    checkpointer_digests: tuple[str, ...]
    readiness: dict[str, object]


def startup_request(app: FastAPI) -> Request:
    """A Starlette request bound to the application, for the lazily composed dependencies."""

    return Request({"type": "http", "app": app, "headers": [], "method": "GET", "path": "/"})


async def compose_runtime_control(
    app: FastAPI,
    settings: Settings,
    *,
    client: Client,
    stack: AsyncExitStack,
    fork_patch_policies: ForkPatchPolicyRegistry | None = None,
    start_relay: bool = True,
    application_binding: ApplicationBinding | None = None,
) -> RuntimeControlComposition:
    state = app.state
    pool = getattr(state, "run_control_postgres_pool", None)
    if pool is None:
        raise RuntimeError("RUN_CONTROL_TEMPORAL_ENABLED requires application PostgreSQL")
    readiness: dict[str, object] = {"temporal_namespace": settings.temporal_namespace}
    try:
        await verify_belllabs_search_attributes(
            client,
            settings.temporal_namespace,
            **(
                {"cloud_api_key": settings.temporal_cloud_api_key.get_secret_value()}
                if settings.temporal_target == "cloud"
                and settings.temporal_cloud_api_key is not None
                else {}
            ),
        )
        readiness["search_attributes"] = "verified"
    except SearchAttributeRegistrationError as error:
        readiness["search_attributes"] = f"missing: {error}"
        raise
    async with pool.acquire() as connection:
        database_name = await connection.fetchval("SELECT current_database()")
    # Same read-only proof as the worker: no fallback schema, no setup at startup.
    evidence = await verify_runtime_persistence(
        settings.langgraph_checkpoint_dsn,
        expected_database=database_name,
        schema=settings.langgraph_checkpoint_schema,
    )
    readiness["runtime_persistence"] = evidence.schema
    persistence = await stack.enter_async_context(
        StandalonePersistenceLifespan(settings.langgraph_checkpoint_dsn)
    )
    pins = CapabilityPins.from_settings(settings)
    checkpointers = {item.ref.digest: persistence.saver for item in pins.checkpointers}
    # OC-R4 review B2: the technical API is the local technical surface: no installation
    # `temporal` section exists here, so the queue is TEMPORAL_TASK_QUEUE or the profile
    # MISSION_CONTROL_APPLICATION selects; unset is a typed startup failure.
    queues = coordinator_task_queues(settings.task_queue_base)
    submitter = TemporalWorkflowSubmitter.for_production(
        client,
        stagegraph_task_queue=queues.stagegraph,
        goal_directed_task_queue=queues.goal_directed,
        search_attribute_policy="required",
        mission_installation_id=(
            application_binding.installation_id if application_binding is not None else None
        ),
        mission_application_id=(
            application_binding.application_id if application_binding is not None else None
        ),
    )
    # Inspection sources (RRM-005).
    state.temporal_client = client
    state.temporal_visibility_reader = TemporalVisibilityInspectionReader(client)
    state.inspection_checkpoint_reader = LangGraphCheckpointHistoryReader(checkpointers)
    # P1 turn 4: the time-travel router (`read_as_of`, `seed_fork`) over the same savers.
    state.time_travel_registry = TimeTravelRegistry(
        {
            "deep_agents": DeepAgentsTimeTravel(
                checkpointers,
                locators={
                    digest: persistence.locator_digest
                    for digest in checkpointers
                    if persistence.locator_digest
                },
            )
        }
    ).register_all(
        # K3 (2026-11-05): the session lanes read the common database's frames under the
        # caller's scope; no payload store is composed here, so Cursor reads stay at R1.
        session_lane_time_travel(PostgresFrameRepository(pool))
    )
    state.inspection_async_child_details = PostgresAsyncSubagentDetailRepository(pool)
    state.inspection_cursor_key = settings.inspection_cursor_secret
    # Boundary interventions (RRM-007) and unit reconciliation (RRM-004).
    state.boundary_command_transport = TemporalBoundaryCommandTransport(client)
    state.unit_reconciliation_nudge = TemporalUnitReconciliationNudge(client)
    state.unit_reconciliation_verifier = LangGraphCheckpointDescendantVerifier(checkpointers)
    # Forks (RRM-006) and the governed launch (RRM-009).
    state.fork_patch_policies = fork_patch_policies or ForkPatchPolicyRegistry()
    state.workflow_submitter = submitter
    request = startup_request(app)
    run_control = await get_run_control_service(request)
    launch = RunLaunchService(
        prerequisites=StoredPrerequisiteLaunchGuard(
            PostgresManifestSubmissionRepository(pool).run_subscriptions,
            compose_prerequisite_preflight(pool, binding=application_binding, settings=settings),
            runtime_templates=PostgresManifestSubmissionRepository(pool).runtime_templates,
        ),
        run_control=run_control,
        submitter=submitter,
        # OVE-166 / WI-02: every launch route registers the admitted promises.
        promises=compose_launch_promises(pool),
        forks=PostgresForkRepository(pool),
        materializations=PostgresForkMaterializationStore(pool),
        fork_templates=StageGraphForkTemplateDerivation(
            PostgresStageGraphOperationTemplateRepository(pool)
        ),
        # MP-22: the technical API binds runs to its configured cluster too.
        cluster_bindings=PostgresRunClusterBindings(pool),
        cluster=temporal_cluster_identity(
            target=settings.temporal_target,
            address=settings.temporal_address,
            namespace=settings.temporal_namespace,
            task_queue=settings.task_queue_base,
        ),
    )
    state.run_launch_service = launch
    state.generic_artifact_submitter = TemporalGenericArtifactSubmitter(
        client, task_queue=generic_artifact_task_queue(settings.task_queue_base)
    )
    interventions = await get_boundary_intervention_service(request)
    # RRM-008 composed: the `liability_reconciled` hint after operator decisions, and the
    # privileged usage reconciliation of cancelled async children (no provider access).
    hints = FamilyLiabilityHints(run_control, TemporalFamilyLiabilityHint(client))
    state.family_liability_hints = hints
    state.async_child_usage_reconciliation = AsyncChildUsageReconciliation(
        AsyncSubagentService(
            PostgresAsyncSubagentDetailRepository(pool),
            PostgresAsyncSubagentAuthority(pool),
            ProviderNotComposed(),
            parent_effects=RunControlAsyncChildEffects(
                run_control, actor=orchestration_lifecycle_actor()
            ),
        ),
        hints,
    )
    relay = BoundaryCommandRelay(
        run_control=run_control,
        interventions=interventions,
        request_scopes=settings.boundary_relay_request_scopes,
        interval_seconds=settings.boundary_relay_interval_seconds,
    )
    state.boundary_command_relay = relay
    if start_relay and relay.request_scopes:
        task = asyncio.create_task(relay.run_forever(), name="belllabs-boundary-relay")

        async def stop_relay() -> None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

        stack.push_async_callback(stop_relay)
    readiness.update(
        {
            "launch": "composed",
            "boundary_relay_scopes": list(relay.request_scopes),
            "checkpointer_digests": sorted(checkpointers),
        }
    )
    composition = RuntimeControlComposition(
        submitter=submitter,
        launch=launch,
        relay=relay,
        checkpointer_digests=tuple(sorted(checkpointers)),
        readiness=readiness,
    )
    state.runtime_control = composition
    logger.info("runtime control composed", extra={"readiness": readiness})
    return composition


__all__ = ["RuntimeControlComposition", "compose_runtime_control", "startup_request"]
