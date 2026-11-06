"""A cancellation in progress cannot be acknowledged as an already-started chain consumer."""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from mission_control.adapters.postgres.chains.exports import PostgresChainStartGate
from mission_control.adapters.postgres.run_control import canonical as mc


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "projection",
    [
        {"phase": "cancelling", "terminal_outcome": None},
        {"phase": "terminal", "terminal_outcome": "cancelled"},
    ],
)
async def test_cancelled_receiver_refuses_before_family_input_or_launch(monkeypatch, projection):
    monkeypatch.setattr(mc, "begin", AsyncMock(return_value=("installation", "app", "tenant")))

    class Connection:
        @asynccontextmanager
        async def transaction(self):
            yield

        async def fetchval(self, *args):
            return json.dumps(projection)

    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield Connection()

    intent = SimpleNamespace(request_scope="scope", run_id="run", mission_id="mission")
    with pytest.raises(ValueError, match="cancelled before relay delivery"):
        await PostgresChainStartGate(Pool()).ensure_startable(intent)
