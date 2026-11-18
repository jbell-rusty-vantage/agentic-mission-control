"""The frame store contract over the src `InMemoryFrameStore` (OVE-238 G3).

The same scenarios run on PostgreSQL in
`tests/integration/postgres/test_frame_store_contract_postgres.py`.
"""

from __future__ import annotations

import pytest

from tests.fixtures.provider_frames import harness_start, in_memory_store
from tests.support.contracts.frames import SCENARIOS, FrameStoreSubject, Scenario
from tests.support.ids import OTHER_SCOPE, SCOPE


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda item: item.__name__)
async def test_in_memory_frame_store_satisfies_the_contract(scenario: Scenario) -> None:
    store, _run_id = in_memory_store(request_scope=SCOPE)
    await scenario(FrameStoreSubject(store, harness_start(request_scope=SCOPE), OTHER_SCOPE))
