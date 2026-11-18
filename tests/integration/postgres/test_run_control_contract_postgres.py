"""The run-control contract over `PostgresRunControlRepository` (OVE-238 G3).

Each scenario runs on a fresh disposable database under the restricted runtime login (real
grants, forced row-level security). The in-memory runner is
`tests/unit/run_control/test_run_control_contract.py`.
"""

from __future__ import annotations

import pytest

from mission_control.adapters.postgres.run_control.run_control_repository import (
    PostgresRunControlRepository,
)
from tests.support.contracts.run_control import SCENARIOS, RunControlSubject, Scenario
from tests.support.db import CommonDatabase

pytestmark = pytest.mark.common_db


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda item: item.__name__)
async def test_postgres_run_control_repository_satisfies_the_contract(
    common_db: CommonDatabase, scenario: Scenario
) -> None:
    pool = await common_db.pool("mission_control_runtime")
    try:
        await scenario(
            RunControlSubject(
                PostgresRunControlRepository(pool),
                common_db.scope("tenant-1"),
                common_db.scope("tenant-2"),
            )
        )
    finally:
        await pool.close()
