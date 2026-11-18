"""Builders, constants and fakes that other test files import.

Moved from tests/integration/postgres/test_checkpoint_lineage_postgres.py.
"""

from __future__ import annotations

from uuid import uuid4

import asyncpg

from mission_control.adapters.postgres.run_control.run_control_repository import (
    PostgresRunControlRepository,
)
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.support.db_builders import scoped_request
from tests.support.run_control import service as run_control_service

RUNTIME_ROLE = "mission_control_runtime"


async def admit_run(pool: asyncpg.Pool, db: CommonDatabase) -> str:
    run_service, _ = run_control_service(PostgresRunControlRepository(pool))  # type: ignore[arg-type]
    decision = await run_service.admit(scoped_request(db, request_id=f"lineage-{uuid4()}"))
    assert decision.run_id is not None
    return decision.run_id
