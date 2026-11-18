"""Builders, constants and fakes that other test files import.

Moved from tests/unit/mission_control/test_run_evidence.py.
"""

from datetime import UTC, datetime

from mission_control.application.coordinator.coordinator_results import (
    InMemoryWorkflowResultRepository,
)
from mission_control.application.execution.boundary_interventions import BoundaryInterventionService
from mission_control.application.missions.retrieval import RunEvidenceService
from mission_control.application.missions.service import MissionControlService
from mission_control.application.programs.orchestration_binding_repository import (
    InMemoryRunSemanticInputBindingRepository,
)
from mission_control.domain.policies.contracts import ActorContext
from mission_control.domain.programs.bindings import (
    RunSemanticInputBinding,
    SemanticHandlerBinding,
    SemanticInputPayload,
    StageHandlerBinding,
)
from tests.support.run_control import DIGEST, request, service

ACTOR = ActorContext(actor_id="reader", permissions={"workflow_run.read", "workflow.result.read"})
NOW = datetime(2026, 10, 11, tzinfo=UTC)


async def setup():
    runs, _ = service()
    admitted = await runs.admit(request())
    assert admitted.run_id
    lifecycle = MissionControlService(
        runs, BoundaryInterventionService(runs), request_scope="tenant-1"
    )
    bindings = InMemoryRunSemanticInputBindingRepository()
    results = InMemoryWorkflowResultRepository()
    evidence = RunEvidenceService(lifecycle, bindings=bindings, results=results)
    return evidence, lifecycle, bindings, results, admitted.run_id


def binding(run_id, scope="tenant-1", digest=DIGEST):
    return RunSemanticInputBinding.create(
        request_scope=scope,
        run_id=run_id,
        blueprint_family="StageGraph",
        effective_configuration_digest=digest,
        blueprint_digest=DIGEST,
        created_at=NOW,
        stage_handlers=(
            StageHandlerBinding(
                stage_id="report",
                handler=SemanticHandlerBinding(
                    handler_id="report",
                    handler_revision=1,
                    input=SemanticInputPayload.from_value(
                        schema_ref="report.input/1", value={"topic": "persistent missions"}
                    ),
                    output_contract_ref="report.output/1",
                ),
            ),
        ),
    )
