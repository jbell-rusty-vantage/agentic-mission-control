"""OVE-171 / WI-08 on real PostgreSQL: the result decision attributes a route fact from the exact
validated bytes and commits it in the family journal; a governed revisit of a declared Revisit
Region commits through the atomic family seam with its decision as evidence, re-derived from the
authoritative head (a forged or stale revisit is refused); the restricted roles and the family
mutation bound accept both records."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from mission_control.adapters.postgres.run_control.run_control_repository import (
    PostgresRunControlRepository,
)
from mission_control.domain.authoring.contracts import StageGraphBlueprint
from mission_control.domain.programs.contracts import StageGraphCycleActivityRequest
from mission_control.domain.programs.interpreter import StageGraphInterpreter
from mission_control.domain.programs.routing import ROUTE_FACTS_KEY
from tests.integration.postgres.runtime_common import common_db as common_db
from tests.unit.orchestration.test_completion_validation_service import OUTPUT, prepared

pytestmark = pytest.mark.common_db


def _cycle(fixture, projection, evaluation_ref: str) -> StageGraphCycleActivityRequest:  # type: ignore[no-untyped-def]
    return StageGraphCycleActivityRequest(
        run_id=fixture.result.run_id,
        request_scope=fixture.scope,
        projection=projection,
        invalidation_frontier=("final",),
        next_objective="Revisit 2 of region refine",
        evaluation_ref=evaluation_ref,
        evaluation_contract_ref="revisit:refine",
        objective_contract_ref="revisit:refine",
        blueprint=fixture.result.blueprint,
        effective_max_concurrency=1,
        occurred_at=datetime.now(UTC),
        idempotency_issuer="operator",
        correlation_id="wi08-revisit-test",
        cycle_scope="revisit",
    )


@pytest.mark.asyncio
async def test_facts_and_a_governed_revisit_commit_through_the_real_family_seam(common_db):
    pool = await common_db.pool()
    writer = await common_db.pool("mission_control_family_writer")
    try:
        fixture = await prepared(
            PostgresRunControlRepository(pool, family_writer_pool=writer),
            common_db.scope(),
            revisit=True,
        )
        decided = await fixture.service.decide_result(fixture.result)
        assert decided.accepted and decided.proposal.decision.value == "admit"
        (accepted,) = decided.projection.accepted_results
        fact = accepted.operation_result[ROUTE_FACTS_KEY]["count"]
        assert fact["status"] == "known" and fact["value"] == 1
        assert fact["evidence_ref"].startswith(f"{OUTPUT}#/count@sha256:")
        head = await fixture.journal()
        recorded = head.decision_payload["projection"]["accepted_results"][0]["operation_result"]
        assert recorded[ROUTE_FACTS_KEY]["count"]["value"] == 1

        interpreter = StageGraphInterpreter(
            StageGraphBlueprint.model_validate(fixture.result.blueprint),
            effective_max_concurrency=1,
        )
        due = interpreter.revisit_due(decided.projection)
        assert due is not None and (due.visit, due.disposition) == (1, "revisit")
        with pytest.raises(ValueError, match="no revisit"):
            await fixture.service.apply_cycle(
                _cycle(fixture, decided.projection, "revisit:refine:9")
            )
        cycled = await fixture.service.apply_cycle(
            _cycle(fixture, decided.projection, "revisit:refine:1")
        )
        assert cycled.accepted, cycled.reason_code
        assert cycled.projection.workflow_cycle_ordinal == 1
        assert cycled.proposal.invalidated_stage_ids == ("final",)
        head = await fixture.journal()
        assert head.decision_kind == "cycle_decided"
        assert head.decision_payload["revisit"]["visit"] == 1
        assert head.decision_payload["evaluation_ref"] == "revisit:refine:1"
        run = await fixture.run_control.get_run(fixture.scope, fixture.result.run_id)
        assert run.version == cycled.projection.run_version
        # The next visit is admissible at the new workflow cycle.
        (proposal,) = interpreter.frontier(cycled.projection, available_concurrency=1)
        assert proposal.identity.candidate.workflow_cycle_ordinal == 1
        assert proposal.continues_from is not None
    finally:
        await pool.close()
        await writer.close()
