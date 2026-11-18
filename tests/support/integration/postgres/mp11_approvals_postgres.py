"""Builders, constants and fakes that other test files import.

Moved from tests/integration/postgres/test_approval_bindings_postgres.py.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import asyncpg
import pytest_asyncio

from mission_control.adapters.postgres.run_control.run_control_repository import (
    PostgresRunControlRepository,
)
from tests.fixtures.mission_control_common_db import (
    CommonDatabase,
    create_common_database,
    drop_common_database,
)
from tests.support.run_control import request, service


@pytest_asyncio.fixture
async def mp11_db() -> AsyncIterator[CommonDatabase]:
    """Scratch database with the released chain 0001..0033 (MP-11 tables from 0033)."""

    database = await create_common_database()
    try:
        yield database
    finally:
        await drop_common_database(database)


async def admitted_run(pool: asyncpg.Pool, scope: str) -> str:
    authority, _ = service(PostgresRunControlRepository(pool))  # type: ignore[arg-type]
    admission = await authority.admit(request(request_scope=scope, request_id=str(uuid4())))
    assert admission.run_id is not None
    return admission.run_id
