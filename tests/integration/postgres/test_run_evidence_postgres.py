"""Persisted input retrieval survives recomposition and preserves forced-RLS scope."""

import pytest

from mission_control.adapters.postgres.coordinator.workflow_result_repository import (
    PostgresWorkflowResultRepository,
)
from mission_control.adapters.postgres.frames.transcript_projection import PostgresRunMissionIds
from mission_control.adapters.postgres.orchestration.orchestration_binding_repository import (
    PostgresRunSemanticInputBindingRepository,
)
from mission_control.adapters.postgres.run_control.run_control_repository import (
    PostgresRunControlRepository,
)
from mission_control.application.execution.boundary_interventions import BoundaryInterventionService
from mission_control.application.missions.retrieval import RunEvidenceService
from mission_control.application.missions.service import MissionControlService
from mission_control.domain.policies.errors import RunControlNotFound
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.integration.postgres.runtime_common import common_db as common_db
from tests.unit.mission_control.test_run_evidence import ACTOR, binding
from tests.unit.run_control.test_run_control import request, service

pytestmark = pytest.mark.common_db


@pytest.mark.asyncio
async def test_inputs_survive_recomposition_and_cross_tenant_read_is_denied(
    common_db: CommonDatabase,
) -> None:
    pool = await common_db.pool()
    scope = common_db.scope()
    try:
        runs, _ = service(PostgresRunControlRepository(pool))
        admitted = await runs.admit(request(request_scope=scope))
        assert admitted.run_id
        run_id = admitted.run_id
        frozen = binding(run_id, scope=scope)
        repository = PostgresRunSemanticInputBindingRepository(pool)
        await repository.create(frozen)
        await repository.create(frozen)  # replay preserves one immutable binding
    finally:
        await pool.close()

    # Fresh pool/repositories prove the response does not rely on process-local state.
    pool = await common_db.pool()
    try:
        runs, _ = service(PostgresRunControlRepository(pool))
        lifecycle = MissionControlService(
            runs, BoundaryInterventionService(runs), request_scope=scope
        )
        evidence = RunEvidenceService(
            lifecycle,
            bindings=PostgresRunSemanticInputBindingRepository(pool),
            results=PostgresWorkflowResultRepository(pool),
            mission_ids=PostgresRunMissionIds(pool),
        )
        assert (await evidence.inputs(run_id, actor=ACTOR)).binding == frozen
        view = await evidence.get(run_id, actor=ACTOR)
        assert view.mission_id
        assert view.inputs.status == "recorded"
        assert view.result.status == "pending"
        other_scope = common_db.scope("tenant-2")
        other = RunEvidenceService(
            MissionControlService(
                runs, BoundaryInterventionService(runs), request_scope=other_scope
            ),
            bindings=PostgresRunSemanticInputBindingRepository(pool),
        )
        with pytest.raises(RunControlNotFound):
            await other.inputs(run_id, actor=ACTOR)
    finally:
        await pool.close()
