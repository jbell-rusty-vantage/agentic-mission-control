"""Provenance slice 4 (OVE-204) on a disposable PostgreSQL 17: every read intent is recorded.

``gateway.read_intent`` over the K01 semantic fake writes one ``retained_read_observation`` per
answered operation through ``PostgresRetainedReadStore`` on the restricted runtime login (real
grants, forced RLS): the rows carry the mapping of ``application/knowledge/read_intent.py``, a
replayed request writes nothing new, another tenant sees nothing, the runtime role cannot
mutate a row and the table's readable-needs-digest CHECK holds.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime

import asyncpg
import pytest
import pytest_asyncio

from mission_control.adapters.postgres.knowledge.retained_reads import PostgresRetainedReadStore
from mission_control.application.knowledge.access import InvocationAccess
from mission_control.contracts.knowledge_protocol import canonical_json, digest_canonical
from tests.fixtures.knowledge_binding import BINDING, read_intent_answer
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.integration.postgres.runtime_common import (  # noqa: F401
    common_db,
    owner_rows,
    runtime_pool,
)
from tests.unit.knowledge.test_gateway import harness, origin
from tests.unit.knowledge.test_read_intent import GOVERNORS, request

pytestmark = [pytest.mark.asyncio, pytest.mark.common_db]


@pytest_asyncio.fixture
async def store(runtime_pool: asyncpg.Pool) -> AsyncIterator[PostgresRetainedReadStore]:  # noqa: F811
    yield PostgresRetainedReadStore(runtime_pool)


def access_in(db: CommonDatabase, h: object, tenant: str = "tenant-1") -> InvocationAccess:
    scope = db.scope(tenant)
    _, installation, application, tenant_id = scope.split("/")
    return InvocationAccess(
        origin=origin(
            installation_id=installation, application_id=application, tenant_id=tenant_id
        ),
        subject="mission-control-runtime",
        invocation_id="inv-0001",
        authenticated_at=h.clock.now,  # type: ignore[attr-defined]
    )


async def test_a_read_intent_records_one_observation_per_operation(
    common_db: CommonDatabase,  # noqa: F811
    store: PostgresRetainedReadStore,
) -> None:
    h = harness()
    h.client.reader = lambda envelope: read_intent_answer(
        envelope,
        rows={"head": [{"knowledge_seq": 12}], "where": []},
        errors={"page": "PAGE_NOT_FOUND"},
        withheld=frozenset({"find"}),
    )
    access = access_in(common_db, h)
    result = await h.gateway.read_intent(
        request(),
        access,
        observations=store,
        capability_pin="knowledge.knowledge_read_intent@1",
        governors=GOVERNORS,
        request_key="read-intent-pg-1",
    )
    rows = await store.observations(access.scope, access.invocation_ref)
    assert [row.read_observation_ref for row in rows] == sorted(
        f"{result.operationId}#{op}" for op in ("head", "find", "where", "page")
    )
    by_op = {row.read_observation_ref.split("#")[1]: row for row in rows}
    head = by_op["head"]
    assert head.run_id == access.origin.run_id and head.source_binding_id is None
    assert head.handle.startswith(f"kri:{BINDING}/knowledge.head?sha256:")
    assert head.observed_digest == digest_canonical([{"knowledge_seq": 12}])
    assert head.byte_count == len(canonical_json([{"knowledge_seq": 12}]).encode())
    assert head.observed_at == datetime(2026, 10, 31, 10, tzinfo=UTC)
    assert head.consistency["ksOperationId"] == result.operationId
    assert head.consistency["snapshotDigest"] == result.snapshotDigest
    assert (by_op["find"].readable, by_op["find"].byte_count) == (True, None)
    assert (by_op["where"].readable, by_op["where"].byte_count) == (True, 2)
    assert (by_op["page"].readable, by_op["page"].byte_count) == (False, None)
    assert by_op["page"].consistency["errorCode"] == "PAGE_NOT_FOUND"

    (generated,) = await owner_rows(
        common_db,
        "SELECT count(*) FILTER (WHERE digest_verified) AS verified, "
        "count(*) FILTER (WHERE expected_digest IS NULL) AS unexpected, "
        "min(created_by_actor_ref) AS actor FROM mission_control.retained_read_observation",
    )
    assert (generated["verified"], generated["unexpected"]) == (0, 4)
    assert generated["actor"] == "mission-control:knowledge-gateway"

    # A replay of the same request is the same KS operation: no new rows.
    again = await h.gateway.read_intent(
        request(),
        access,
        observations=store,
        capability_pin="knowledge.knowledge_read_intent@1",
        governors=GOVERNORS,
        request_key="read-intent-pg-1",
    )
    assert again.operationId == result.operationId
    assert len(await store.observations(access.scope, access.invocation_ref)) == 4
    assert await store.record(access.scope, (), actor_ref="x", at=h.clock.now) == 0

    # Forced RLS: another tenant of the same installation sees none of them.
    other = access_in(common_db, h, "tenant-2")
    assert await store.observations(other.scope, access.invocation_ref) == []


async def test_rows_are_immutable_and_readable_rows_need_their_digest(
    common_db: CommonDatabase,  # noqa: F811
    runtime_pool: asyncpg.Pool,  # noqa: F811
    store: PostgresRetainedReadStore,
) -> None:
    h = harness()
    h.client.reader = read_intent_answer
    access = access_in(common_db, h)
    await h.gateway.read_intent(
        request(),
        access,
        observations=store,
        capability_pin="knowledge.knowledge_read_intent@1",
        governors=GOVERNORS,
        request_key="read-intent-pg-2",
    )
    (row, *_) = await store.observations(access.scope, access.invocation_ref)

    from mission_control.adapters.postgres.run_control import canonical as mc

    async with runtime_pool.acquire() as connection, connection.transaction():
        await mc.begin(connection, access.scope)
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await connection.execute(
                "UPDATE mission_control.retained_read_observation SET readable = false"
            )

    # The table CHECK refuses a readable row without its observed digest (the dataclass
    # refuses it first, so the row is forged past it).
    forged = replace(row, read_observation_ref="forged#x")
    object.__setattr__(forged, "observed_digest", None)
    object.__setattr__(forged, "observation_id", "00000000-0000-4000-8000-0000000000ff")
    with pytest.raises(asyncpg.CheckViolationError):
        await store.record(access.scope, (forged,), actor_ref="test", at=h.clock.now)
