"""The output contract store contract over `PostgresOutputContractStore` (OVE-238 G3).

Each scenario runs on a fresh disposable database under the restricted runtime login (release
1.7.0 output-contract tables, forced row-level security). The in-memory runner is
`tests/unit/outputs/test_output_contract_store_contract.py`.
"""

from __future__ import annotations

import pytest

from mission_control.adapters.postgres.knowledge.output_contracts import (
    PostgresOutputContractStore,
)
from tests.support.contracts.output_contracts import SCENARIOS, OutputContractSubject, Scenario
from tests.support.db import CommonDatabase

pytestmark = pytest.mark.common_db


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda item: item.__name__)
async def test_postgres_output_contract_store_satisfies_the_contract(
    common_db: CommonDatabase, scenario: Scenario
) -> None:
    pool = await common_db.pool("mission_control_runtime")
    try:
        store = PostgresOutputContractStore(pool)
        await scenario(
            OutputContractSubject(
                store, store, common_db.scope("tenant-1"), common_db.scope("tenant-2")
            )
        )
    finally:
        await pool.close()
