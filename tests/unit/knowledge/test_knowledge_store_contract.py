"""The knowledge store contracts over `mission_control.adapters.knowledge.memory` (OVE-238 G3).

The same scenarios run on PostgreSQL in
`tests/integration/postgres/test_knowledge_store_contract_postgres.py`.
"""

from __future__ import annotations

import pytest

from mission_control.adapters.knowledge.memory import (
    InMemoryKnowledgeHandleStore,
    InMemoryKnowledgeJournal,
    InMemoryLineageStore,
    InMemoryRetainedReadStore,
    InMemorySubmissionStore,
    InMemoryTransferPlanStore,
)
from tests.support.contracts.knowledge import SCENARIOS, KnowledgeSubject, Scenario
from tests.support.ids import OTHER_SCOPE, SCOPE


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda item: item.__name__)
async def test_in_memory_knowledge_stores_satisfy_the_contract(scenario: Scenario) -> None:
    await scenario(
        KnowledgeSubject(
            journal=InMemoryKnowledgeJournal(),
            handles=InMemoryKnowledgeHandleStore(),
            submissions=InMemorySubmissionStore(),
            transfer_plans=InMemoryTransferPlanStore(),
            lineage=InMemoryLineageStore(),
            retained_reads=InMemoryRetainedReadStore(),
            scope=SCOPE,
            other_scope=OTHER_SCOPE,
        )
    )
