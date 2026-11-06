"""W1 D30 on real PostgreSQL: a worker without a trusted settlement keeps a trusted-pinned report
revision waiting with the actionable cause (the restricted runtime role, the real output-contract
tables), and never for a promise whose requirements name another validator."""

from __future__ import annotations

from collections.abc import AsyncIterator

import asyncpg
import pytest
import pytest_asyncio

from mission_control.adapters.postgres.knowledge.output_contracts import (
    PostgresOutputContractStore,
)
from mission_control.application.knowledge.judgment import EvaluatorUnavailable
from mission_control.application.knowledge.trusted_settlement import (
    UncomposedTrustedSettlement,
    pending_or_raise,
)
from mission_control.domain.execution.invocation_settlement import SettlementOutcome
from mission_control.domain.outputs.contracts import OutputForm, Requirement
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.integration.postgres.runtime_common import common_db  # noqa: F401
from tests.integration.postgres.test_wi07_collections_postgres import access_for
from tests.unit.knowledge.test_wi07_report_collections import PIN, handle
from tests.unit.outputs.scenario import build_stack, obligation

pytestmark = [pytest.mark.asyncio, pytest.mark.common_db]


@pytest_asyncio.fixture
async def pool(common_db: CommonDatabase) -> AsyncIterator[asyncpg.Pool]:  # noqa: F811
    created = await common_db.pool()
    try:
        yield created
    finally:
        await created.close()


async def test_a_trusted_pinned_report_waits_with_the_cause_on_postgres(
    common_db: CommonDatabase,  # noqa: F811
    pool: asyncpg.Pool,
) -> None:
    store = PostgresOutputContractStore(pool)
    access = access_for(common_db, "goal-iteration/1/executor")
    report = obligation(
        "root.report",
        OutputForm.REFERENCE,
        requirements=(Requirement(key="assessed", validator=PIN),),
    )
    stack = await build_stack(store, store, access, report)
    worker = await stack.start(access)
    ack = await worker.submit("s1", "root.report", handle("r1"))
    assert ack.status == "accepted", ack.error
    finalized = await stack.submissions.finalize(access.identity(("root.report",)))
    assert finalized.finalization_id is not None

    passed = await UncomposedTrustedSettlement(store=store, assessment_pin=PIN).settle(
        access, attempt=0
    )
    assert passed.unavailable == (ack.revisions[0].revision_id,)
    with pytest.raises(EvaluatorUnavailable) as waiting:
        pending_or_raise(passed)
    detail = SettlementOutcome.unavailable(waiting.value).detail
    assert detail["code"] == "EVALUATOR_UNAVAILABLE" and detail["reason"] == "evaluator_unavailable"
    assert "MC_AUDITOR_ANTHROPIC_API_KEY" in detail["issues"][0]
    # A promise judged by another validator never waits on the evaluators.
    other = UncomposedTrustedSettlement(store=store, assessment_pin="mc.schema@1")
    assert pending_or_raise(await other.settle(access, attempt=0)) == ()
