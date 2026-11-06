"""W1 D20 on real PostgreSQL: a KS refusal of an evaluator's documents is legible in inspection.

The bridge records an ``unavailable`` assessment whose findings name KS's refusal and its bounded
issues (release 1.7.0 ``output_assessment.findings``); the inspection reader returns the first
findings themselves (``finding_details``), not only their count.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import asyncpg
import pytest
import pytest_asyncio

from mission_control.adapters.postgres.knowledge.output_contracts import (
    PostgresOutputContractStore,
)
from mission_control.adapters.postgres.knowledge.output_inspection import (
    PostgresOutputInspectionReader,
)
from mission_control.application.knowledge.gateway import TrustedAnswer
from mission_control.application.knowledge.judgment import TrustedJudgmentRefused
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.integration.postgres.runtime_common import common_db  # noqa: F401
from tests.integration.postgres.test_trusted_judgment_postgres import access_for
from tests.unit.knowledge.test_trusted_judgment import ScriptedRunner, evaluators, world
from tests.unit.knowledge.test_w1_d19_d20 import census_refusal

pytestmark = [pytest.mark.asyncio, pytest.mark.common_db]


@pytest_asyncio.fixture
async def pool(common_db: CommonDatabase) -> AsyncIterator[asyncpg.Pool]:  # noqa: F811
    created = await common_db.pool()
    try:
        yield created
    finally:
        await created.close()


async def test_a_refused_census_shows_its_issues_in_inspection(
    common_db: CommonDatabase,  # noqa: F811
    pool: asyncpg.Pool,
) -> None:
    w, subject = await world(
        common_db.application_id,
        store=PostgresOutputContractStore(pool),
        access=access_for(common_db),
    )
    bridge = w.bridge(ScriptedRunner({"judge": "full_support"}))
    real = bridge._gateway.trusted  # type: ignore[attr-defined]

    async def trusted(operation: str, *args: Any, **kwargs: Any) -> TrustedAnswer:
        if operation == "report.observe":
            return TrustedAnswer(operation=operation, refusal=census_refusal())
        return await real(operation, *args, **kwargs)

    bridge._gateway.trusted = trusted  # type: ignore[attr-defined,method-assign]
    with pytest.raises(TrustedJudgmentRefused):
        await bridge.assess(subject, evaluators(w), w.stack.access, w.use())
    views = await PostgresOutputInspectionReader(pool).assessments(
        w.stack.access.scope, subject.run_id
    )
    # The refusal record supersedes the observe dispatch marker; it is the newest row.
    view = views[-1]
    assert view.result == "unavailable" and view.findings == 9
    assert len(view.finding_details) == 8
    first, issue = view.finding_details[0], view.finding_details[1]
    assert first.code == "ks_invalid_envelope" and first.pointer == "observation_invalid"
    assert "the census is not a valid discovery" in first.message
    assert issue.code == "ks_issue" and issue.pointer == "occurrences.0.span.basis"
