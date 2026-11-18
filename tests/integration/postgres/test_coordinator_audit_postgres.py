"""`PostgresCoordinatorAuditSink` on the disposable database (restricted runtime role).

A coordinator audit event is stored as digest-only metadata (the table has no request or
response payload column), an emitted event is read back once (a repeated event id is not
duplicated), another tenant's scope reads nothing under forced row-level security, and a
non-canonical scope is refused. Moved from
tests/unit/coordinator/test_coordinator_security_audit.py, which asserted SQL text on a fake
asyncpg pool (OVE-238).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import asyncpg
import pytest

from mission_control.adapters.postgres.coordinator.coordinator_audit_repository import (
    PostgresCoordinatorAuditSink,
)
from mission_control.application.coordinator.coordinator_facade import CoordinatorAuditEvent
from tests.support.db import CommonDatabase
from tests.support.db_builders import owner_rows

pytestmark = pytest.mark.common_db

SENTINEL = "sk-proj-SENTINEL_OPENAI_KEY_1234567890"


def _event(scope: str, occurred_at: datetime) -> CoordinatorAuditEvent:
    return CoordinatorAuditEvent(
        event_id=str(uuid4()),
        occurred_at=occurred_at,
        operation="search_capabilities",
        actor_id="operator-1",
        tenant_scope=scope,
        outcome="succeeded",
        correlation_id=str(uuid4()),
        request_digest="sha256:" + "a" * 64,
        response_digest="sha256:" + "b" * 64,
    )


async def test_the_audit_sink_persists_only_digest_metadata(
    common_db: CommonDatabase, runtime_pool: asyncpg.Pool
) -> None:
    now = datetime.now(UTC)
    event = _event(common_db.scope(), now)
    sink = PostgresCoordinatorAuditSink(runtime_pool)
    await sink.emit(event)
    await sink.emit(event)  # a redelivered event is stored once

    rows = await owner_rows(common_db, "SELECT * FROM mission_control.coordinator_audit_event")
    assert len(rows) == 1
    columns = set(rows[0].keys())
    assert not {column for column in columns if "payload" in column}
    assert rows[0]["request_digest"] == event.request_digest
    assert rows[0]["response_digest"] == event.response_digest
    assert SENTINEL not in repr(dict(rows[0]))

    events = await sink.list_events(
        tenant_scope=common_db.scope(), actor_id="operator-1", occurred_since=now
    )
    assert events == (event,)


async def test_the_audit_sink_reads_back_only_its_own_scope(
    common_db: CommonDatabase, runtime_pool: asyncpg.Pool
) -> None:
    now = datetime.now(UTC)
    sink = PostgresCoordinatorAuditSink(runtime_pool)
    await sink.emit(_event(common_db.scope(), now))

    other = await sink.list_events(
        tenant_scope=common_db.scope("tenant-2"),
        actor_id="operator-1",
        occurred_since=now - timedelta(minutes=1),
    )
    assert other == ()
    later = await sink.list_events(
        tenant_scope=common_db.scope(),
        actor_id="operator-1",
        occurred_since=now + timedelta(minutes=1),
    )
    assert later == ()
    with pytest.raises(ValueError, match="canonical"):
        await sink.list_events(tenant_scope="tenant-a", actor_id="operator-1", occurred_since=now)
