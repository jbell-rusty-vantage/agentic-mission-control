"""Builders, constants and fakes that other test files import.

Moved from tests/integration/postgres/test_mo44_watchers_postgres.py.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable

import asyncpg
import pytest
from temporalio.client import Client

from mission_control.adapters.postgres.watchers import PostgresWatcherStore
from mission_control.domain.programs.watchers import WatcherDescriptor

TEMPORAL_ADDRESS = os.environ.get("MC_TEMPORAL_TEST_ADDRESS", "127.0.0.1:7233")
TEMPORAL_NAMESPACE = os.environ.get("MC_TEMPORAL_TEST_NAMESPACE", "default")


class FixedProgram(PostgresWatcherStore):
    """The PostgreSQL store with the descriptors given here instead of a definition snapshot."""

    def __init__(
        self, pool: asyncpg.Pool, scope: str, descriptors: tuple[WatcherDescriptor, ...]
    ) -> None:
        super().__init__(pool, scope)
        self.fixed = descriptors

    async def descriptors(self, run_id: str) -> tuple[WatcherDescriptor, ...]:
        del run_id
        return self.fixed


async def eventually[T](
    probe: Callable[[], Awaitable[T]], done: Callable[[T], bool], *, seconds: float = 60
) -> T:
    """The probe's first value that is done, read every half second for at most ``seconds``."""

    for _ in range(int(seconds * 2)):
        value = await probe()
        if done(value):
            return value
        await asyncio.sleep(0.5)
    pytest.fail(f"not done within {seconds} s")


async def local_temporal() -> Client:
    try:
        return await Client.connect(TEMPORAL_ADDRESS, namespace=TEMPORAL_NAMESPACE)
    except RuntimeError as error:
        pytest.fail(f"the real local Temporal server at {TEMPORAL_ADDRESS} is required: {error}")
