"""The knowledge store contracts over the PostgreSQL knowledge stores (OVE-238 G3).

Each scenario runs on a fresh disposable database under the restricted runtime login (forced
row-level security). The in-memory runner is
`tests/unit/knowledge/test_knowledge_store_contract.py`.
"""

from __future__ import annotations

import pytest

from mission_control.adapters.postgres.context.transfer_plans import PostgresTransferPlanStore
from mission_control.adapters.postgres.knowledge.handles import PostgresKnowledgeHandleStore
from mission_control.adapters.postgres.knowledge.lineage import PostgresContentLineageStore
from mission_control.adapters.postgres.knowledge.operations import PostgresKnowledgeJournal
from mission_control.adapters.postgres.knowledge.retained_reads import PostgresRetainedReadStore
from mission_control.adapters.postgres.knowledge.submissions import PostgresOutputSubmissionStore
from tests.support.contracts.knowledge import SCENARIOS, KnowledgeSubject, Scenario
from tests.support.db import CommonDatabase

pytestmark = pytest.mark.common_db

# PostgreSQL defects the contract keeps asserting (OVE-238 G3): name -> file:line and cause.
KNOWN_DEFECTS = {
    "strict_lineage_refuses_a_second_producer": (
        "src/mission_control/adapters/postgres/knowledge/lineage.py:123 leaks "
        "asyncpg.UniqueViolationError (content_lineage_one_producer_idx) across the port "
        "instead of the ValueError the in-memory store and the registration path raise"
    ),
}


def _cases() -> list[object]:
    return [
        pytest.param(
            scenario,
            id=scenario.__name__,
            marks=pytest.mark.xfail(strict=True, reason=KNOWN_DEFECTS[scenario.__name__])
            if scenario.__name__ in KNOWN_DEFECTS
            else (),
        )
        for scenario in SCENARIOS
    ]


@pytest.mark.parametrize("scenario", _cases())
async def test_postgres_knowledge_stores_satisfy_the_contract(
    common_db: CommonDatabase, scenario: Scenario
) -> None:
    pool = await common_db.pool("mission_control_runtime")
    try:
        await scenario(
            KnowledgeSubject(
                journal=PostgresKnowledgeJournal(pool),
                handles=PostgresKnowledgeHandleStore(pool),
                submissions=PostgresOutputSubmissionStore(pool),
                transfer_plans=PostgresTransferPlanStore(pool),
                lineage=PostgresContentLineageStore(pool),
                retained_reads=PostgresRetainedReadStore(pool),
                scope=common_db.scope("tenant-1"),
                other_scope=common_db.scope("tenant-2"),
            )
        )
    finally:
        await pool.close()
