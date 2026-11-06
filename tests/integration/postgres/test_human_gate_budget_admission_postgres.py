"""Real restricted-role persistence of noncognitive admission and review settlement."""

from functools import partial

import pytest

from mission_control.adapters.postgres.run_control.run_control_repository import (
    PostgresRunControlRepository,
)
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.programs.contracts import StageGraphDecisionMutation
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.integration.postgres.runtime_common import common_db as common_db
from tests.integration.postgres.runtime_common import scoped_command, scoped_request
from tests.unit.orchestration.test_human_gate_budget_admission import accept_gate_result, fixture

pytestmark = pytest.mark.common_db


@pytest.mark.asyncio
async def test_postgres_non_cognitive_gate_head_and_completed_review_survive_restart(
    common_db: CommonDatabase,
):
    runtime = await common_db.pool("mission_control_runtime", max_size=4)
    writer = await common_db.pool("mission_control_family_writer", max_size=4)
    try:
        repository = PostgresRunControlRepository(runtime, family_writer_pool=writer)
        control, _, candidate = await fixture(
            repository,
            run_request=scoped_request(common_db),
            make_command=partial(scoped_command, common_db),
        )
        result = await accept_gate_result(control, repository, candidate)
        restarted = PostgresRunControlRepository(runtime, family_writer_pool=writer)
        head = await restarted.get_family_head(
            candidate.request_scope, candidate.run_id, "stagegraph", StageGraphDecisionMutation
        )
        assert head is not None
        assert head.decision_kind == "result_decided"
        assert head.next_projection_digest == result.projection.digest
        gate = await restarted.get_family_mutation(
            candidate.request_scope,
            candidate.run_id,
            "stagegraph",
            "admit-" + sha256_digest(candidate.proposal.identity.semantic_key)[7:],
            StageGraphDecisionMutation,
        )
        assert gate is not None and gate.decision_kind == "control_admitted"
    finally:
        await writer.close()
        await runtime.close()
