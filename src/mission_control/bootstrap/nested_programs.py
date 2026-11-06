"""Trusted composition of recursive composition (OVE-176): the nested-program activities.

Always composed on both family workers, durable: the PostgreSQL activation lineage
(``mission_control.nested_activation``, unregistered ``scripts/release_1130/0071``), the child
output reader over the output-contract store and governed child controls through run control and
the boundary command delivery. The launcher additionally needs the manifest launch author
(``MISSION_CONTROL_MANIFEST_LAUNCH_BINDINGS_PATH``) and the installation's application; adoption
needs the knowledge toolset. Missing either, that part is not composed and a nested body refuses
typed (``nested_execution_unavailable``) or settles without adoption; nothing is ever flattened.
"""

from __future__ import annotations

import logging
from typing import Any

import asyncpg
from temporalio.client import Client

from mission_control.adapters.postgres.control_plane.definition_repository import (
    PostgresDefinitionRepository,
)
from mission_control.adapters.postgres.control_plane.manifest_submission import (
    PostgresManifestSubmissionRepository,
)
from mission_control.adapters.postgres.control_plane.nested_runs import PostgresNestedRunAdmissions
from mission_control.adapters.postgres.knowledge.output_contracts import (
    PostgresOutputContractStore,
)
from mission_control.adapters.postgres.orchestration.nested_activations import (
    PostgresNestedActivationStore,
)
from mission_control.adapters.temporal.boundary_commands import TemporalBoundaryCommandTransport
from mission_control.adapters.temporal.coordinator_runtime import coordinator_task_queues
from mission_control.adapters.temporal.nested_program_activities import NestedProgramActivities
from mission_control.application.authoring.manifest_service import (
    ManifestProgramCompiler,
    catalog_output_schemas,
)
from mission_control.application.authoring.service import ControlPlaneService
from mission_control.application.execution.boundary_interventions import (
    BoundaryCommandDeliveryService,
    BoundaryInterventionService,
)
from mission_control.application.execution.service import RunControlService
from mission_control.application.outputs.adoption import OutputAdoptionService
from mission_control.application.programs.nested_bodies import (
    NestedExportAdoption,
    NestedProgramService,
    NestedRunLauncher,
)
from mission_control.application.programs.nested_launch import (
    ManifestNestedRunLauncher,
    NestedRunDefinitions,
    RunControlNestedControls,
    StoreNestedOutputs,
    ToolsetNestedAdoption,
)
from mission_control.bootstrap.settings import Settings

_LOG = logging.getLogger(__name__)


def compose_nested_program_activities(
    pool: asyncpg.Pool,
    *,
    client: Client,
    settings: Settings,
    run_control: RunControlService,
    control_plane: ControlPlaneService,
    application_id: str | None,
    knowledge_toolset: Any | None = None,
) -> NestedProgramActivities:
    activations = PostgresNestedActivationStore(pool)
    outputs = PostgresOutputContractStore(pool)
    controls = RunControlNestedControls(
        BoundaryInterventionService(
            run_control,
            BoundaryCommandDeliveryService(run_control, TemporalBoundaryCommandTransport(client)),
        ),
        run_control,
    )
    launcher: NestedRunLauncher | None = None
    if application_id is None:
        _LOG.warning(
            "nested bodies will refuse (nested_execution_unavailable): the worker names no "
            "installation application, so no nested-body launcher is composed"
        )
    if application_id is not None:
        from mission_control.bootstrap.launch_promises import compose_launch_promises
        from mission_control.bootstrap.manifests import compose_manifest_launch_inputs

        submissions = PostgresManifestSubmissionRepository(pool)
        author = compose_manifest_launch_inputs(
            pool,
            settings=settings,
            application_id=application_id,
            run_control=run_control,
            control_plane=control_plane,
            definitions=NestedRunDefinitions(submissions, activations),
        )
        if author is None:
            _LOG.warning(
                "nested bodies will refuse (nested_execution_unavailable): no manifest launch "
                "bindings file (MISSION_CONTROL_MANIFEST_LAUNCH_BINDINGS_PATH) is configured"
            )
        else:
            definitions = PostgresDefinitionRepository(
                pool, catalog_scope=settings.mission_control_catalog_scope or ""
            )
            queues = coordinator_task_queues(settings.task_queue_base)
            registrar = compose_launch_promises(pool)

            async def register(scope: str, run_id: str, digest: str, promises: Any) -> None:
                await registrar(scope, run_id, digest, promises)

            async def schemas(definition: Any) -> Any:
                return await catalog_output_schemas(definitions, definition)

            launcher = ManifestNestedRunLauncher(
                run_control=run_control,
                definitions=submissions,
                configurations=control_plane,
                output_schemas=schemas,
                programs=ManifestProgramCompiler(
                    definitions, control_plane.extensions, control_plane.payload_store
                ),
                admissions=PostgresNestedRunAdmissions(pool),
                activations=activations,
                launch_inputs=author,
                promises=register,
                family_task_queues={
                    "StageGraph": queues.stagegraph,
                    "GoalDirected": queues.goal_directed,
                },
            )
    adoption: NestedExportAdoption | None = None
    if knowledge_toolset is not None:
        adoption = ToolsetNestedAdoption(
            knowledge_toolset,
            OutputAdoptionService(
                outputs=outputs,
                submissions=knowledge_toolset.submissions,
                lineage=knowledge_toolset.lineage,
            ),
        )
    return NestedProgramActivities(
        NestedProgramService(
            run_control=run_control,
            launcher=launcher,
            outputs=StoreNestedOutputs(outputs),
            controls=controls,
            activations=activations,
            adoption=adoption,
        )
    )


__all__ = ["compose_nested_program_activities"]
