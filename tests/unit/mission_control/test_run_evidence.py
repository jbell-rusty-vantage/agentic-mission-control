from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests.unit.run_control.test_run_control import DIGEST, request, service

from mission_control.application.context.continuation import CheckpointReadService, CheckpointView
from mission_control.application.coordinator.coordinator_results import (
    InMemoryWorkflowResultRepository,
)
from mission_control.application.execution.boundary_interventions import BoundaryInterventionService
from mission_control.application.missions.retrieval import (
    RunEvidenceInconsistent,
    RunEvidenceService,
)
from mission_control.application.missions.service import MissionControlService
from mission_control.application.programs.orchestration_binding_repository import (
    InMemoryRunSemanticInputBindingRepository,
)
from mission_control.contracts.contracts import MissionControlRejected
from mission_control.domain.coordinator.launch import (
    BlueprintFamily,
    StageGraphResultDetails,
    WorkflowResultRecord,
)
from mission_control.domain.policies.contracts import ActorContext, RunOutcome
from mission_control.domain.policies.errors import RunControlNotFound
from mission_control.domain.programs.bindings import (
    RunSemanticInputBinding,
    SemanticHandlerBinding,
    SemanticInputPayload,
    StageHandlerBinding,
)
from mission_control.interfaces.http.mission_control import MissionPrincipal, get_mission_principal
from mission_control.interfaces.http.run_evidence import get_run_evidence_service, router

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


@pytest.mark.asyncio
async def test_retrieval_distinguishes_missing_evidence_and_returns_frozen_inputs():
    evidence, _, bindings, _, run_id = await setup()
    empty = await evidence.get(run_id, actor=ACTOR)
    assert empty.inputs.status == "not_recorded"
    assert empty.result.status == "pending"
    assert empty.checkpoints_status == "unavailable"
    assert empty.artifact_bytes_status == "not_verified"
    frozen = await bindings.create(binding(run_id))
    read = await evidence.get(run_id, actor=ACTOR)
    assert read.inputs.binding_digest == frozen.binding_digest
    assert read.inputs.handlers[0].schema_ref == "report.input/1"
    assert "persistent missions" not in read.model_dump_json()
    assert (await evidence.inputs(run_id, actor=ACTOR)).binding == frozen


@pytest.mark.asyncio
async def test_result_read_permission_and_unknown_run_fail_before_binding_read():
    evidence, _, bindings, _, _ = await setup()
    bindings.get_for_run = AsyncMock(side_effect=AssertionError("unauthorized store read"))
    with pytest.raises(MissionControlRejected, match="permissions"):
        await evidence.inputs(
            "missing", actor=ActorContext(actor_id="reader", permissions={"workflow_run.read"})
        )
    with pytest.raises(RunControlNotFound):
        await evidence.get("missing", actor=ACTOR)


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["scope", "configuration"])
async def test_mismatched_input_evidence_is_never_returned(mismatch):
    evidence, _, bindings, _, run_id = await setup()
    wrong = binding(
        run_id,
        scope="other" if mismatch == "scope" else "tenant-1",
        digest="sha256:" + "f" * 64 if mismatch == "configuration" else DIGEST,
    )
    bindings.get_for_run = AsyncMock(return_value=wrong)
    with pytest.raises(RunEvidenceInconsistent):
        await evidence.get(run_id, actor=ACTOR)


@pytest.mark.asyncio
async def test_terminal_result_missing_is_explicit_and_conflicting_result_rejected():
    evidence, lifecycle, _, results, run_id = await setup()
    inspection = await lifecycle.inspect(run_id, ACTOR)
    terminal = inspection.model_copy(
        update={
            "phase": "terminal",
            "execution_outcome": "failed",
            "projection": inspection.projection.model_copy(
                update={"terminal_outcome": RunOutcome.FAILED}
            ),
        }
    )
    lifecycle.inspect = AsyncMock(return_value=terminal)
    assert (await evidence.get(run_id, actor=ACTOR)).result.status == "missing_terminal_result"
    result = WorkflowResultRecord(
        run_id=run_id,
        request_scope="tenant-1",
        tenant_scope="tenant-1",
        blueprint_family=BlueprintFamily.STAGE_GRAPH,
        terminal_outcome=RunOutcome.COMPLETED,
        family_result=StageGraphResultDetails(execution_epoch=1, workflow_cycles=0),
        completed_at=NOW,
    )
    await results.save(result)
    with pytest.raises(RunEvidenceInconsistent):
        await evidence.get(run_id, actor=ACTOR)


@pytest.mark.asyncio
async def test_moving_ledger_requires_retry_instead_of_mixed_snapshot():
    evidence, lifecycle, _, _, run_id = await setup()
    inspection = await lifecycle.inspect(run_id, ACTOR)
    lifecycle.inspect = AsyncMock(
        side_effect=[inspection, inspection.model_copy(update={"version": inspection.version + 1})]
    )
    with pytest.raises(RunEvidenceInconsistent, match="retry"):
        await evidence.get(run_id, actor=ACTOR)


@pytest.mark.asyncio
async def test_checkpoint_manifest_does_not_claim_current_resumability():
    _, lifecycle, _, _, run_id = await setup()
    checkpoints = AsyncMock(spec=CheckpointReadService)
    checkpoints.request_scope = "tenant-1"
    checkpoints.list.return_value = (
        CheckpointView(
            run_id=run_id,
            checkpoint_id="checkpoint-1",
            checkpoint_digest=DIGEST,
            validator_result="valid",
            sealed_at=NOW,
            checkpoint={"workspace_snapshot_ref": "snapshot:1", "sandbox_snapshot_ref": None},
        ),
    )
    evidence = RunEvidenceService(lifecycle, checkpoints=checkpoints)
    view = await evidence.get(run_id, actor=ACTOR)
    assert view.checkpoints[0].current_resumability == "not_verified"
    assert view.checkpoints[0].workspace_snapshot_ref == "snapshot:1"
    assert view.checkpoints[0].sandbox_snapshot_ref is None
    assert view.result.status == "unavailable"


def test_cross_application_is_denied_before_service_lookup():
    class ForbiddenRegistry:
        def get(self, key):
            pytest.fail("cross-application read selected a service")

    app = FastAPI()
    app.include_router(router)
    app.state.mission_control_evidence_services = ForbiddenRegistry()
    app.dependency_overrides[get_mission_principal] = lambda: MissionPrincipal(
        installation_id=uuid4(),
        tenant_id=uuid4(),
        application_id="a",
        issuer="https://issuer.invalid",
        audiences={"authenticated"},
        actor=ACTOR,
    )
    response = TestClient(app).get("/v1/applications/b/runs/r/evidence")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_http_evidence_and_inputs_use_the_application_service():
    evidence, _, bindings, _, run_id = await setup()
    await bindings.create(binding(run_id))
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_run_evidence_service] = lambda: evidence
    app.dependency_overrides[get_mission_principal] = lambda: MissionPrincipal(
        installation_id=uuid4(),
        tenant_id=uuid4(),
        application_id="a",
        issuer="https://issuer.invalid",
        audiences={"authenticated"},
        actor=ACTOR,
    )
    with TestClient(app) as client:
        response = client.get(f"/v1/applications/a/runs/{run_id}/evidence")
        assert response.status_code == 200
        assert response.json()["result"]["status"] == "pending"
        response = client.get(f"/v1/applications/a/runs/{run_id}/inputs")
        assert response.status_code == 200
        assert response.json()["binding"]["run_id"] == run_id
        response = client.get(f"/v1/applications/a/runs/{run_id}/completion-evidence")
        assert response.status_code == 200
        assert response.json()["status"] == "unavailable"
        assert response.json()["decisions"] == []
        for query in ("limit=101", "limit=0", "after_family_version=-1"):
            response = client.get(f"/v1/applications/a/runs/{run_id}/completion-evidence?{query}")
            assert response.status_code == 422
