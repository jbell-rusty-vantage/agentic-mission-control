"""Builders, constants and fakes that other test files import.

Moved from tests/integration/postgres/test_knowledge_gateway_postgres.py.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import asyncpg
import pytest_asyncio

from mission_control.adapters.postgres.knowledge.handles import PostgresKnowledgeHandleStore
from mission_control.adapters.postgres.knowledge.operations import PostgresKnowledgeJournal
from mission_control.application.knowledge.gateway import KnowledgeGateway
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.support.clock import Clock
from tests.support.knowledge.binding import FakeKnowledgeBinding
from tests.support.knowledge.credentials import (
    AUDIENCE,
    BINDING,
    KNOWLEDGE_NOW,
    Issuer,
    RecordingMinter,
    knowledge_port,
)


@pytest_asyncio.fixture
async def pool(common_db: CommonDatabase) -> AsyncIterator[asyncpg.Pool]:
    created = await common_db.pool()
    try:
        yield created
    finally:
        await created.close()


def stack(pool: asyncpg.Pool, clock: Clock | None = None):
    clock = clock or Clock(KNOWLEDGE_NOW)
    issuer = Issuer(clock=clock)
    minter = RecordingMinter(issuer.minter())
    client = FakeKnowledgeBinding(verifier=issuer.verifier(), clock=clock)
    journal = PostgresKnowledgeJournal(pool)
    handles = PostgresKnowledgeHandleStore(pool)

    async def sleep(_seconds: float) -> None:
        return None

    def gateway(max_polls: int = 10) -> KnowledgeGateway:
        return KnowledgeGateway(
            client=client,
            journal=journal,
            handles=handles,
            minter=minter,
            content=client,
            knowledge=knowledge_port(BINDING),
            audience=AUDIENCE,
            max_polls=max_polls,
            clock=clock,
            sleep=sleep,
        )

    return clock, minter, client, journal, gateway
