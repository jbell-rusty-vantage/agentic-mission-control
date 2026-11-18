"""The run alias a caller holds resolves on the disposable database, inside its own scope.

Routes return a run's public run key (a UUID string); the journal and inboxes use the
internal `mission_run.run_id`. `PostgresSubscriptionStore.resolve_target` maps either to the
same target on the restricted runtime role, and another tenant's scope sees nothing (forced
row-level security, not a WHERE clause). Replaces the SQL-text-matching pool of
tests/unit/subscriptions/test_subscription_caller_identity.py (OVE-238).
"""

from __future__ import annotations

from uuid import UUID, uuid4

import asyncpg
import pytest

from mission_control.adapters.postgres.subscriptions.store import PostgresSubscriptionStore
from mission_control.application.subscriptions.ports import SubscriptionNotFound
from mission_control.domain.subscriptions.contracts import SubscriptionTarget
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.support.db_builders import insert_fixture_run

pytestmark = pytest.mark.common_db

PUBLIC_RUN = UUID("10000000-0000-7000-8000-000000000002")


async def _seeded(common_db: CommonDatabase) -> SubscriptionTarget:
    internal = await insert_fixture_run(common_db, common_db.scope(), str(PUBLIC_RUN))
    connection = await asyncpg.connect(common_db.owner_dsn)
    try:
        mission = await connection.fetchval(
            "SELECT mission_id FROM mission_control.mission_run WHERE run_id=$1", internal
        )
    finally:
        await connection.close()
    return SubscriptionTarget(kind="run", mission_id=mission, run_id=internal)


async def test_the_public_run_key_and_the_internal_run_id_resolve_to_one_target(
    common_db: CommonDatabase, runtime_pool: asyncpg.Pool
) -> None:
    expected = await _seeded(common_db)
    assert expected.run_id != PUBLIC_RUN
    resolver = PostgresSubscriptionStore(runtime_pool, common_db.scope())
    assert await resolver.resolve_target("run", PUBLIC_RUN) == expected
    assert expected.run_id is not None
    assert await resolver.resolve_target("run", expected.run_id) == expected
    assert await resolver.resolve_target("mission", expected.mission_id) == SubscriptionTarget(
        kind="mission", mission_id=expected.mission_id
    )
    with pytest.raises(SubscriptionNotFound):
        await resolver.resolve_target("run", uuid4())


async def test_another_scope_never_resolves_the_alias(
    common_db: CommonDatabase, runtime_pool: asyncpg.Pool
) -> None:
    expected = await _seeded(common_db)
    other = PostgresSubscriptionStore(runtime_pool, common_db.scope("tenant-2"))
    assert expected.run_id is not None
    for target in (PUBLIC_RUN, expected.run_id):
        with pytest.raises(SubscriptionNotFound):
            await other.resolve_target("run", target)
    with pytest.raises(SubscriptionNotFound):
        await other.resolve_target("mission", expected.mission_id)
