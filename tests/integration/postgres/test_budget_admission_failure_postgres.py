"""Persist real reserve denial and concluded failure through restricted common roles."""

from functools import partial

import pytest

from mission_control.adapters.postgres.run_control.run_control_repository import (
    PostgresRunControlRepository,
)
from mission_control.application.programs.service import StageGraphDecisionService
from mission_control.domain.programs.contracts import (
    StageGraphCompletionActivityRequest,
    StageGraphDecisionMutation,
)
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.integration.postgres.runtime_common import common_db as common_db
from tests.integration.postgres.runtime_common import scoped_command, scoped_request
from tests.unit.orchestration.test_budget_admission_failure import prepared

pytestmark = pytest.mark.common_db


@pytest.mark.asyncio
async def test_postgres_budget_rejection_and_failed_terminalization_survive_restart(
    common_db: CommonDatabase,
):
    runtime = await common_db.pool("mission_control_runtime", max_size=4)
    writer = await common_db.pool("mission_control_family_writer", max_size=4)
    try:
        repository = PostgresRunControlRepository(runtime, family_writer_pool=writer)
        control, _, candidate, interpreter = await prepared(
            repository=repository,
            run_request=scoped_request(common_db),
            make_command=partial(scoped_command, common_db),
        )
        budget = await control.get_budget(candidate.request_scope, candidate.run_id)
        service = StageGraphDecisionService(control, repository)
        refused = await service.admit_operation(candidate)
        assert refused.reason_code == "budget_hard_cap_exceeded"
        assert refused.projection.family_version == 1
        assert not refused.projection.producer_liabilities
        restarted = PostgresRunControlRepository(runtime, family_writer_pool=writer)
        head = await restarted.get_family_head(
            candidate.request_scope, candidate.run_id, "stagegraph", StageGraphDecisionMutation
        )
        assert head and head.decision_kind == "admission_rejected"
        assert head.next_projection_digest == refused.projection.digest
        assert (
            await StageGraphDecisionService(control, restarted).admit_operation(candidate)
            == refused
        )
        run = await control.get_run(candidate.request_scope, candidate.run_id)
        completion = interpreter.failure_completion(refused.projection)
        assert completion and completion.can_terminalize
        terminal = await StageGraphDecisionService(control, restarted).complete(
            StageGraphCompletionActivityRequest(
                run_id=candidate.run_id,
                request_scope=candidate.request_scope,
                projection=refused.projection,
                proposal=completion,
                workflow_type_digest=run.workflow_type_ref.digest,
                occurred_at=candidate.occurred_at,
                idempotency_issuer=candidate.idempotency_issuer,
                correlation_id=candidate.correlation_id,
            )
        )
        assert terminal.accepted and terminal.terminal_outcome.value == "failed"
        assert (
            await control.get_run(candidate.request_scope, candidate.run_id)
        ).phase.value == "terminal"
        assert await control.get_budget(candidate.request_scope, candidate.run_id) == budget
        assert (
            await StageGraphDecisionService(control, restarted).admit_operation(candidate)
            == refused
        )
    finally:
        await writer.close()
        await runtime.close()
