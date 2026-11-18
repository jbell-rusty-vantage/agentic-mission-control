"""The operation journal contract over `PostgresAtomicOperationJournalRepository` (OVE-238 G3).

Each scenario runs on a fresh disposable database under the restricted runtime login; runs are
admitted through `PostgresRunControlRepository` on the same pool. The in-memory runner is
`tests/unit/operations/test_operation_journal_contract.py`.
"""

from __future__ import annotations

import pytest

from mission_control.adapters.postgres.operations.operation_journal import (
    PostgresAtomicOperationJournalRepository,
)
from mission_control.adapters.postgres.run_control.run_control_repository import (
    PostgresRunControlRepository,
)
from tests.support.contracts.operation_journal import (
    SCENARIOS,
    OperationJournalSubject,
    Scenario,
)
from tests.support.db import CommonDatabase

pytestmark = pytest.mark.common_db


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda item: item.__name__)
async def test_postgres_operation_journal_satisfies_the_contract(
    common_db: CommonDatabase, scenario: Scenario
) -> None:
    pool = await common_db.pool("mission_control_runtime")
    try:
        await scenario(
            OperationJournalSubject(
                PostgresAtomicOperationJournalRepository(pool),
                PostgresRunControlRepository(pool),
                common_db.scope("tenant-1"),
                common_db.scope("tenant-2"),
            )
        )
    finally:
        await pool.close()
