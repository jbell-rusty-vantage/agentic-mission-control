"""The operation journal contract over the src `InMemoryAtomicOperationJournalRepository`.

OVE-238 G3. The same scenarios run on PostgreSQL in
`tests/integration/postgres/test_operation_journal_contract_postgres.py`.
"""

from __future__ import annotations

import pytest

from mission_control.application.execution.operations.operation_journal import (
    InMemoryAtomicOperationJournalRepository,
)
from mission_control.application.execution.run_control_repository import (
    InMemoryRunControlRepository,
)
from tests.support.contracts.operation_journal import (
    SCENARIOS,
    OperationJournalSubject,
    Scenario,
)
from tests.support.ids import OTHER_SCOPE, SCOPE


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda item: item.__name__)
async def test_in_memory_operation_journal_satisfies_the_contract(scenario: Scenario) -> None:
    journal = InMemoryAtomicOperationJournalRepository(require_seeded_runs=True)
    await scenario(
        OperationJournalSubject(
            journal, InMemoryRunControlRepository(), SCOPE, OTHER_SCOPE, seed=journal.seed_run
        )
    )
