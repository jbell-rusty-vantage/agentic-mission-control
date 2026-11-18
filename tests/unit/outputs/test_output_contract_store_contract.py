"""The output contract store contract over the src `InMemoryOutputContractStore` (OVE-238 G3).

The same scenarios run on PostgreSQL in
`tests/integration/postgres/test_output_contract_store_contract_postgres.py`.
"""

from __future__ import annotations

import pytest

from mission_control.adapters.outputs.memory import InMemoryOutputContractStore
from tests.support.contracts.output_contracts import SCENARIOS, OutputContractSubject, Scenario
from tests.support.ids import OTHER_SCOPE, SCOPE


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda item: item.__name__)
async def test_in_memory_output_contract_store_satisfies_the_contract(
    scenario: Scenario,
) -> None:
    store = InMemoryOutputContractStore()
    await scenario(OutputContractSubject(store, store.submissions, SCOPE, OTHER_SCOPE))
