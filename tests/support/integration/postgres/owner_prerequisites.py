"""Builders, constants and fakes that other test files import.

Moved from tests/integration/postgres/test_owner_prerequisites.py.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import asyncpg
import pytest_asyncio

from tests.support.db import CommonDatabase


@pytest_asyncio.fixture
async def pool(common_db: CommonDatabase) -> AsyncIterator[asyncpg.Pool]:
    created = await common_db.pool("mission_control_runtime")
    try:
        yield created
    finally:
        await created.close()
