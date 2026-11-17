"""Disposable common-database fixtures, registered as a pytest plugin in tests/conftest.py.

Each test gets a fresh disposable database from ``tests.fixtures.mission_control_common_db``
with restricted LOGIN roles (real grants, forced RLS) and canonical scopes. ``catalog_db``
also holds a *disabled* ``ai-engineer`` installation row, so cross-application denial is
proven by row-level security; its runtime pool is ``catalog_runtime_pool``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import asyncpg
import pytest_asyncio

from tests.fixtures.mission_control_common_db import (
    CommonDatabase,
    create_common_database,
    drop_common_database,
)
from tests.support.db_builders import add_disabled_installation


@pytest_asyncio.fixture
async def common_db() -> AsyncIterator[CommonDatabase]:
    database = await create_common_database()
    try:
        yield database
    finally:
        await drop_common_database(database)


@pytest_asyncio.fixture
async def poisoned_db() -> AsyncIterator[CommonDatabase]:
    database = await create_common_database(legacy_poison=True)
    try:
        yield database
    finally:
        await drop_common_database(database)


@pytest_asyncio.fixture
async def runtime_pool(common_db: CommonDatabase) -> AsyncIterator[asyncpg.Pool]:
    pool = await common_db.pool("mission_control_runtime")
    try:
        yield pool
    finally:
        await pool.close()


@pytest_asyncio.fixture
async def family_pool(common_db: CommonDatabase) -> AsyncIterator[asyncpg.Pool]:
    pool = await common_db.pool("mission_control_family_writer")
    try:
        yield pool
    finally:
        await pool.close()


@pytest_asyncio.fixture
async def catalog_db() -> AsyncIterator[CommonDatabase]:
    database = await create_common_database()
    try:
        await add_disabled_installation(database)
        yield database
    finally:
        await drop_common_database(database)


@pytest_asyncio.fixture
async def catalog_runtime_pool(catalog_db: CommonDatabase) -> AsyncIterator[asyncpg.Pool]:
    pool = await catalog_db.pool("mission_control_runtime")
    try:
        yield pool
    finally:
        await pool.close()


@pytest_asyncio.fixture
async def catalog_writer_pool(catalog_db: CommonDatabase) -> AsyncIterator[asyncpg.Pool]:
    pool = await catalog_db.pool("mission_control_catalog_writer")
    try:
        yield pool
    finally:
        await pool.close()
