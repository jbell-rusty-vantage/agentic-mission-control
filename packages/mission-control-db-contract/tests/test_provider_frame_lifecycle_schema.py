"""Additive lifecycle facts upgrade and SQL bounds on disposable PostgreSQL 17."""

from __future__ import annotations

import json
from uuid import uuid4

import asyncpg
import pytest
from mission_control.adapters.postgres.frames.repository import PostgresFrameRepository
from mission_control.adapters.postgres.scope import apply_scope
from tests.fixtures.mission_control_common_db import common_database, migration_paths
from tests.integration.postgres.frames_common import admit_unit_attempt

pytestmark = [pytest.mark.common_db, pytest.mark.asyncio]


async def test_lifecycle_body_upgrade_preserves_old_frames_and_enforces_bounds() -> None:
    paths = [path for path in migration_paths() if path.name[:4] <= "0034"]
    migration = paths[-1]
    assert migration.stem == "0034_provider_frame_lifecycle_body"
    async with common_database(paths=paths[:-1]) as database:
        pool = await database.pool(max_size=2)
        owner = await asyncpg.connect(database.owner_dsn)
        try:
            admitted = await admit_unit_attempt(pool, database)
            handle = await PostgresFrameRepository(pool).open_execution(admitted.start())
            # Pre-upgrade row uses precisely the existing columns. The immutable-row
            # trigger remains installed throughout the additive ALTER TABLE.
            insert = """
                INSERT INTO mission_control.provider_frame (
                    installation_id, application_id, tenant_id, frame_id, run_id,
                    activation_id, attempt_no, harness_execution_id, generation,
                    lane_profile, native_session_ref, provider_key, arrival_ordinal,
                    observed_at, kind, closing, raw_kind, body_digest, body_bytes,
                    body_media_type, body_excerpt, created_at, created_by_actor_ref
                    {column}
                ) SELECT installation_id, application_id, tenant_id, $1, run_id,
                    $5, 1, harness_execution_id, 1, lane_profile,
                    'schema-test-session', $2, $3, clock_timestamp(), 'status', false,
                    'schema-test', 'sha256:' || repeat('0', 64), 2, 'application/json',
                    '{{}}'::bytea, clock_timestamp(), 'test:release-0034' {value}
                  FROM mission_control.harness_execution WHERE harness_execution_id = $4
            """
            old_id = uuid4()
            await owner.execute(
                insert.format(column="", value=""),
                old_id,
                "old",
                1,
                handle.harness_execution_id,
                handle.activation_id,
            )
            await owner.execute(migration.read_text(encoding="utf-8"))
            assert (
                await owner.fetchval(
                    "SELECT lifecycle_body::text FROM mission_control.provider_frame "
                    "WHERE frame_id=$1",
                    old_id,
                )
                == "{}"
            )
            with pytest.raises(asyncpg.PostgresError, match="immutable"):
                await owner.execute(
                    "UPDATE mission_control.provider_frame SET lifecycle_body='{}' "
                    "WHERE frame_id=$1",
                    old_id,
                )

            statement = insert.format(column=", lifecycle_body", value=", $6::jsonb")
            async with pool.acquire() as connection:
                for ordinal, (body, expected_error) in enumerate(
                    [
                        ('{"status":"completed","is_error":false}', None),
                        (json.dumps({"status": "a" * 4082}), None),  # 4096 JSONB text bytes
                        (json.dumps({"status": "a" * 4083}), asyncpg.CheckViolationError),
                        (json.dumps({"status": "é" * 2042}), asyncpg.CheckViolationError),
                        ("[]", asyncpg.CheckViolationError),
                        ('"completed"', asyncpg.CheckViolationError),
                        ("null", asyncpg.CheckViolationError),
                        (None, asyncpg.NotNullViolationError),
                    ],
                    start=2,
                ):
                    async with connection.transaction():
                        await apply_scope(connection, database.scope())
                        args = (
                            uuid4(),
                            str(ordinal),
                            ordinal,
                            handle.harness_execution_id,
                            handle.activation_id,
                            body,
                        )
                        if expected_error:
                            with pytest.raises(expected_error):
                                async with connection.transaction():
                                    await connection.execute(statement, *args)
                        else:
                            assert await connection.execute(statement, *args) == "INSERT 0 1"
        finally:
            await owner.close()
            await pool.close()
