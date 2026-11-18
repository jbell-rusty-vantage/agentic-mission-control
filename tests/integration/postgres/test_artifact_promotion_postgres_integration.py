from __future__ import annotations

import asyncio

import asyncpg
import pytest

from mission_control.adapters.postgres.scope import apply_scope
from mission_control.adapters.postgres.workspaces.artifact_repository import (
    PostgresArtifactDurableReferenceRepository,
)
from mission_control.domain.policies.errors import IdempotencyConflict, RunControlNotFound
from tests.fixtures.mission_control_common_db import CommonDatabase, canonical_scope
from tests.support.db_builders import insert_fixture_run
from tests.support.integration.postgres.artifact_promotion_postgres_integration import (
    admitted_revision,
)
from tests.support.unit.workspaces.artifact_promotion import CONTENT_DIGEST

pytestmark = pytest.mark.common_db

RUN_KEY = "run:postgres-artifact-integration"


async def _counts(pool: asyncpg.Pool, scope: str) -> tuple[int, int]:
    async with pool.acquire() as connection, connection.transaction():
        await apply_scope(connection, scope)
        artifacts = await connection.fetchval("SELECT count(*) FROM mission_control.artifact")
        outbox = await connection.fetchval("SELECT count(*) FROM mission_control.outbox")
    return int(artifacts), int(outbox)


async def test_postgres_artifact_reference_and_event_commit_atomically(
    catalog_db: CommonDatabase, catalog_runtime_pool: asyncpg.Pool
) -> None:
    scope = catalog_db.scope("tenant-1")
    await insert_fixture_run(catalog_db, scope, RUN_KEY)
    artifact = admitted_revision(RUN_KEY, scope)

    async def fail_before_commit(boundary: str) -> None:
        if boundary == "artifact_admission":
            raise RuntimeError("injected artifact transaction failure")

    failing = PostgresArtifactDurableReferenceRepository(
        catalog_runtime_pool, before_commit=fail_before_commit
    )
    with pytest.raises(RuntimeError, match="injected"):
        await failing.admit(request_scope=scope, run_id=RUN_KEY, artifact=artifact)
    assert await failing.get(scope, artifact.artifact_id) is None
    assert await failing.pending_events(scope) == ()
    assert await _counts(catalog_runtime_pool, scope) == (0, 0)

    repository = PostgresArtifactDurableReferenceRepository(catalog_runtime_pool)
    first = await repository.admit(request_scope=scope, run_id=RUN_KEY, artifact=artifact)
    replayed = await repository.admit(request_scope=scope, run_id=RUN_KEY, artifact=artifact)
    events = await repository.pending_events(scope)

    assert first == replayed
    assert await repository.get(scope, artifact.artifact_id) == first
    assert len(events) == 1
    assert events[0]["event_type"] == "artifact.admitted"
    assert events[0]["payload"]["metadata_revision"] == artifact.revision


async def test_promotion_replay_is_idempotent_and_conflicts_fail_closed(
    catalog_db: CommonDatabase, catalog_runtime_pool: asyncpg.Pool
) -> None:
    scope = catalog_db.scope("tenant-1")
    await insert_fixture_run(catalog_db, scope, RUN_KEY)
    artifact = admitted_revision(RUN_KEY, scope)
    repository = PostgresArtifactDurableReferenceRepository(catalog_runtime_pool)
    results = await asyncio.gather(
        *(
            repository.admit(request_scope=scope, run_id=RUN_KEY, artifact=artifact)
            for _ in range(6)
        )
    )
    assert len(set(results)) == 1
    # Registered once: one canonical artifact row and one outbox row, no duplicates.
    assert await _counts(catalog_runtime_pool, scope) == (1, 1)
    async with catalog_runtime_pool.acquire() as connection, connection.transaction():
        await apply_scope(connection, scope)
        row = await connection.fetchrow(
            "SELECT a.custody_state, a.content_digest, a.byte_size, a.storage_kind, "
            "o.delivery_key, o.destination_kind, o.delivery_state, o.aggregate_key "
            "FROM mission_control.artifact a JOIN mission_control.outbox o "
            "ON o.tenant_id = a.tenant_id"
        )
        assert (row["custody_state"], row["content_digest"], row["byte_size"]) == (
            "registered",
            CONTENT_DIGEST,
            57,
        )
        assert (row["destination_kind"], row["delivery_state"]) == ("artifact_reference", "pending")
    # A changed digest under the same artifact identity conflicts; nothing new is written.
    with pytest.raises(IdempotencyConflict):
        await repository.admit(
            request_scope=scope,
            run_id=RUN_KEY,
            artifact=artifact.model_copy(update={"content_digest": "sha256:" + "e" * 64}),
        )
    assert await _counts(catalog_runtime_pool, scope) == (1, 1)
    # Scoped read denial: another tenant and the other installation see nothing.
    other_tenant = catalog_db.scope("tenant-2")
    assert await repository.get(other_tenant, artifact.artifact_id) is None
    assert await repository.pending_events(other_tenant) == ()
    with pytest.raises(RunControlNotFound):
        await repository.admit(
            request_scope=other_tenant,
            run_id=RUN_KEY,
            artifact=admitted_revision(RUN_KEY, other_tenant),
        )
    foreign = canonical_scope("tenant-1", "ai-engineer")
    assert await repository.get(foreign, artifact.artifact_id) is None
    # Artifact custody rows are not mutable/deletable by the runtime role.
    async with catalog_runtime_pool.acquire() as connection, connection.transaction():
        await apply_scope(connection, scope)
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await connection.execute("DELETE FROM mission_control.artifact")
