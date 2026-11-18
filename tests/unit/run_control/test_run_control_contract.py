"""The run-control contract over the src `InMemoryRunControlRepository` (OVE-238 G3).

The same scenarios run on PostgreSQL in
`tests/integration/postgres/test_run_control_contract_postgres.py`.
"""

from __future__ import annotations

import pytest

from mission_control.application.execution.run_control_repository import (
    InMemoryRunControlRepository,
)
from tests.support.contracts.run_control import SCENARIOS, RunControlSubject, Scenario
from tests.support.ids import OTHER_SCOPE, SCOPE


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda item: item.__name__)
async def test_in_memory_run_control_repository_satisfies_the_contract(
    scenario: Scenario,
) -> None:
    await scenario(RunControlSubject(InMemoryRunControlRepository(), SCOPE, OTHER_SCOPE))
