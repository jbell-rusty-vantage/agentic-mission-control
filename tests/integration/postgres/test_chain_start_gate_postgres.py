"""`PostgresChainStartGate` on the disposable common database (restricted runtime role).

A chain consumer whose run is cancelling, or already terminal `cancelled`, is refused before
any family input is built or a launch is attempted; a pending consumer without its release set
is refused; a consumer that is already running keeps its sealed inputs. Replaces
tests/unit/chains/test_chain_start_gate.py, which faked the asyncpg pool and patched
`run_control.canonical.begin` (OVE-238).
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import pytest

from mission_control.adapters.postgres.chains.exports import PostgresChainStartGate
from mission_control.application.chains.relay import ChainIntent
from tests.support.db import CommonDatabase
from tests.support.db_builders import insert_fixture_run

pytestmark = pytest.mark.common_db


async def _consumer(common_db: CommonDatabase, projection: dict[str, Any]) -> ChainIntent:
    scope = common_db.scope()
    run_key = f"chain-consumer-{uuid4()}"
    run_id = await insert_fixture_run(common_db, scope, run_key)
    connection = await asyncpg.connect(common_db.owner_dsn)
    try:
        mission_id = await connection.fetchval(
            "UPDATE mission_control.mission_run SET projection=$2::jsonb "
            "WHERE run_id=$1 RETURNING mission_id",
            run_id,
            json.dumps(projection),
        )
    finally:
        await connection.close()
    assert isinstance(mission_id, UUID)
    return ChainIntent(
        intent_kind="start_run",
        delivery_key=f"chain-start:{run_key}",
        request_scope=scope,
        chain_id=uuid4(),
        mission_id=mission_id,
        run_id=run_id,
        run_key=run_key,
        family="GoalDirected",
        initial_goal="Ingest the supplied evidence map",
        actor_ref="chain:test",
    )


@pytest.mark.parametrize(
    "projection",
    [
        {"phase": "cancelling", "terminal_outcome": None},
        {"phase": "terminal", "terminal_outcome": "cancelled"},
    ],
)
async def test_cancelled_receiver_refuses_before_family_input_or_launch(
    common_db: CommonDatabase, runtime_pool: asyncpg.Pool, projection: dict[str, Any]
) -> None:
    intent = await _consumer(common_db, projection)
    with pytest.raises(ValueError, match="cancelled before relay delivery"):
        await PostgresChainStartGate(runtime_pool).ensure_startable(intent)


async def test_a_pending_receiver_without_its_release_set_is_refused(
    common_db: CommonDatabase, runtime_pool: asyncpg.Pool
) -> None:
    intent = await _consumer(common_db, {"phase": "pending", "terminal_outcome": None})
    with pytest.raises(ValueError, match="release set is unavailable"):
        await PostgresChainStartGate(runtime_pool).ensure_startable(intent)


async def test_a_running_receiver_keeps_its_sealed_inputs(
    common_db: CommonDatabase, runtime_pool: asyncpg.Pool
) -> None:
    intent = await _consumer(common_db, {"phase": "active", "terminal_outcome": None})
    assert await PostgresChainStartGate(runtime_pool).ensure_startable(intent) is None


async def test_an_unknown_receiver_is_unavailable(
    common_db: CommonDatabase, runtime_pool: asyncpg.Pool
) -> None:
    intent = await _consumer(common_db, {"phase": "active", "terminal_outcome": None})
    other = intent.model_copy(update={"run_id": uuid4()})
    with pytest.raises(ValueError, match="admission is unavailable"):
        await PostgresChainStartGate(runtime_pool).ensure_startable(other)
