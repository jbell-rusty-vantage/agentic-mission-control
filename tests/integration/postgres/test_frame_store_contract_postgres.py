"""The frame store contract over `PostgresFrameRepository` (OVE-238 G3).

Each scenario runs on a fresh disposable database under the restricted runtime login, against
an admitted run with one recorded runtime-unit attempt. The in-memory runner is
`tests/unit/frames/test_frame_store_contract.py`.
"""

from __future__ import annotations

import pytest

from mission_control.adapters.postgres.frames.repository import PostgresFrameRepository
from tests.support.contracts.frames import SCENARIOS, FrameStoreSubject, Scenario
from tests.support.db import CommonDatabase
from tests.support.db_builders import admit_unit_attempt

pytestmark = pytest.mark.common_db


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda item: item.__name__)
async def test_postgres_frame_store_satisfies_the_contract(
    common_db: CommonDatabase, scenario: Scenario
) -> None:
    pool = await common_db.pool("mission_control_runtime")
    try:
        admitted = await admit_unit_attempt(pool, common_db)
        await scenario(
            FrameStoreSubject(
                PostgresFrameRepository(pool), admitted.start(), common_db.scope("tenant-2")
            )
        )
    finally:
        await pool.close()
