"""The actual PG append adapter checks ownership while holding its insertion lock."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from tests.fixtures.provider_frames import SCOPE, in_memory_store, observation, opened_writer

from mission_control.adapters.postgres.frames import repository
from mission_control.application.execution.harness.dispatch import SessionOwner, StaleSessionOwner
from mission_control.domain.frames.contracts import FrameKind


class Connection:
    def __init__(self, frame, owner):
        self.frame, self.owner = frame, owner
        self.queries, self.prior = [], []
        self.in_transaction = False

    @asynccontextmanager
    async def transaction(self):
        self.in_transaction = True
        try:
            yield
        finally:
            self.in_transaction = False

    async def fetchrow(self, query, *args):
        assert self.in_transaction
        self.queries.append(query)
        if "FOR UPDATE" in query:
            return {
                "harness_execution_id": self.frame.harness_execution_id,
                "run_id": self.frame.run_id,
                "attempt_id": None,
                "generation": 1,
                "native_identity": {"mc_session_owner": self.owner.model_dump(mode="json")},
            }
        return None  # No existing arrival cursor.

    async def fetch(self, query, *args):
        assert self.in_transaction
        self.queries.append(query)
        if "SELECT provider_key" in query:
            return self.prior
        assert "INSERT INTO mission_control.provider_frame" in query
        return [{"frame_id": self.frame.frame_id}]

    async def execute(self, query, *args):
        assert self.in_transaction
        self.queries.append(query)


class Pool:
    def __init__(self, connection):
        self.connection = connection

    @asynccontextmanager
    async def acquire(self):
        yield self.connection


async def fixture(monkeypatch):
    store, _ = in_memory_store()
    writer, handle = await opened_writer(store)
    await writer.write([observation("recovered", FrameKind.STATUS, {"capture": "sha256:fixture"})])
    frame = (await store.frames_for_execution(SCOPE, handle.harness_execution_id, 1))[0]
    owner = SessionOwner(
        owner_ref="recovery",
        epoch=2,
        generation=1,
        lease_expires_at=datetime.now(UTC) + timedelta(minutes=2),
        claimed_at=datetime.now(UTC),
    )
    connection = Connection(frame, owner)
    monkeypatch.setattr(repository, "begin", AsyncMock(return_value=(1, "biotech", 2)))
    return repository.PostgresFrameRepository(Pool(connection)), connection, frame, owner


async def test_same_row_lock_protects_fenced_frame_insert(monkeypatch):
    store, connection, frame, owner = await fixture(monkeypatch)
    receipt = await store.append_fenced([frame], owner=owner)
    assert receipt.new == 1
    assert "FOR UPDATE" in connection.queries[0]
    assert any(
        "INSERT INTO mission_control.provider_frame" in query for query in connection.queries
    )


@pytest.mark.parametrize("changed", ["epoch", "generation", "expired", "body_conflict"])
async def test_stale_owner_or_changed_evidence_never_reaches_insert(monkeypatch, changed):
    store, connection, frame, owner = await fixture(monkeypatch)
    if changed == "epoch":
        owner = owner.model_copy(update={"epoch": 1})
    if changed == "generation":
        owner = owner.model_copy(update={"generation": 2})
    if changed == "expired":
        owner = owner.model_copy(
            update={"lease_expires_at": datetime.now(UTC) - timedelta(seconds=1)}
        )
        connection.owner = owner
    if changed == "body_conflict":
        connection.prior = [
            {
                "provider_key": frame.provider_key,
                "body_digest": "foreign",
                "native_session_ref": frame.native_session_ref,
                "native_turn_ref": frame.native_turn_ref,
                "kind": frame.kind.value,
            }
        ]
    with pytest.raises((StaleSessionOwner, ValueError)):
        await store.append_fenced([frame], owner=owner)
    assert not any(
        "INSERT INTO mission_control.provider_frame" in query for query in connection.queries
    )
