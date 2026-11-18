"""Migration 0033 guards on a real disposable PostgreSQL 17 (newest built release).

Runs against MISSION_CONTROL_TEST_ADMIN_DSN (loopback disposable server only). The guards refuse
what they should: a closed MP-11 correlation and a settled intent never move (including a
settled intent's receipt digest), bound columns never change, nothing is deleted, and MP-15
causation is immutable and must name an existing inbox.

The catalog shape of the 0033 tables (scope, forced RLS, grants) and the lane profile registry's
immutability are proved by `packages/mission-control-db-contract/tests/test_schema_guards.py`;
the live lane describes by `tests/integration/postgres/test_lane_bindings.py`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import asyncpg
import pytest
import pytest_asyncio

from mission_control.adapters.postgres.run_control.run_control_repository import (
    PostgresRunControlRepository,
)
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.support.db_builders import owner_rows, scoped_count
from tests.support.run_control import request, service

pytestmark = pytest.mark.common_db

DIGEST = "sha256:" + "d" * 64
ACTOR = "test:release-0033"


# --------------------------------------------------------------------------- guards


async def _admitted_run(db: CommonDatabase) -> tuple[str, UUID, UUID]:
    pool = await db.pool(max_size=2)
    try:
        authority, _ = service(PostgresRunControlRepository(pool))  # type: ignore[arg-type]
        admission = await authority.admit(
            request(request_scope=db.scope(), request_id=str(uuid4()))
        )
        assert admission.run_id is not None
    finally:
        await pool.close()
    (row,) = await owner_rows(
        db,
        "SELECT run_id, mission_id FROM mission_control.mission_run WHERE run_key = $1",
        admission.run_id,
    )
    return admission.run_id, row["run_id"], row["mission_id"]


@pytest_asyncio.fixture
async def owner(common_db: CommonDatabase) -> AsyncIterator[asyncpg.Connection]:
    connection = await asyncpg.connect(common_db.owner_dsn)
    try:
        yield connection
    finally:
        await connection.close()


def _scope(db: CommonDatabase) -> tuple[UUID, str, UUID]:
    return db.installation_id, db.application_id, db.tenants["tenant-1"]


async def test_mp11_guards_refuse_moving_closed_or_settled_rows(
    common_db: CommonDatabase,
    owner: asyncpg.Connection,
) -> None:
    scope = _scope(common_db)
    run_key, run_id, _mission_id = await _admitted_run(common_db)
    now = datetime.now(UTC)
    task_id, correlation_id, intent_id = uuid4(), uuid4(), uuid4()
    await owner.execute(
        "INSERT INTO mission_control.human_task (installation_id, application_id, tenant_id, "
        "human_task_id, task_key, target_ref, kind, request_packet_ref, assignee_scope, "
        "lifecycle, version, updated_at, created_at, created_by_actor_ref) VALUES "
        "($1, $2, $3, $4, $5, $6, 'approval:provider_permission', 'inline:test', 'tenant', "
        "'open', 1, $7, $7, $8)",
        *scope,
        task_id,
        f"task:{task_id}",
        f"run:{run_key}",
        now,
        ACTOR,
    )
    await owner.execute(
        "INSERT INTO mission_control.approval_correlation (installation_id, application_id, "
        "tenant_id, approval_correlation_id, human_task_id, run_key, harness_execution_id, "
        "generation, connection_ref, native, input_digest, state, opened_at, version, "
        "created_by_actor_ref) VALUES ($1, $2, $3, $4, $5, $6, 'hx-1', 1, 'conn-1', "
        "'{\"request_id\": \"r-1\"}', $7, 'live', $8, 1, $9)",
        *scope,
        correlation_id,
        task_id,
        run_key,
        DIGEST,
        now,
        ACTOR,
    )
    where = f"WHERE approval_correlation_id = '{correlation_id}'"
    with pytest.raises(asyncpg.RestrictViolationError, match="bound to its native request"):
        await owner.execute(
            f"UPDATE mission_control.approval_correlation SET native = '{{}}' {where}"
        )
    await owner.execute(
        "UPDATE mission_control.approval_correlation SET state = 'answered', "
        f"reply = '{{\"allow\": true}}', reply_digest = '{DIGEST}', closed_at = now(), "
        f"version = 2 {where}"
    )
    with pytest.raises(asyncpg.RestrictViolationError, match="closed approval correlation"):
        await owner.execute(
            f"UPDATE mission_control.approval_correlation SET close_reason = 'x' {where}"
        )
    with pytest.raises(asyncpg.RestrictViolationError, match="never deleted"):
        await owner.execute(f"DELETE FROM mission_control.approval_correlation {where}")

    await owner.execute(
        "INSERT INTO mission_control.governed_effect_intent (installation_id, application_id, "
        "tenant_id, governed_effect_intent_id, intent_key, run_id, run_key, "
        "harness_execution_id, generation, lane_profile, tool_name, effect_kind, arguments, "
        "input_digest, policy_digest, state, version, created_at, updated_at, "
        "created_by_actor_ref) VALUES ($1, $2, $3, $4, $5, $6, $7, 'hx-1', 1, "
        "'claude_agent_sdk', 'shell.exec', 'shell', '{\"cmd\": \"true\"}', $8, $8, 'ready', 1, "
        "$9, $9, $10)",
        *scope,
        intent_id,
        f"intent:{intent_id}",
        run_id,
        run_key,
        DIGEST,
        now,
        ACTOR,
    )
    where = f"WHERE governed_effect_intent_id = '{intent_id}'"
    with pytest.raises(asyncpg.RestrictViolationError, match="bound to its arguments"):
        await owner.execute(
            f"UPDATE mission_control.governed_effect_intent SET arguments = '{{}}' {where}"
        )
    await owner.execute(
        "UPDATE mission_control.governed_effect_intent SET state = 'executing', "
        f"claimant_ref = 'worker-1', claimed_at = now(), version = 2 {where}"
    )
    await owner.execute(
        "UPDATE mission_control.governed_effect_intent SET state = 'executed', "
        f"receipt = '{{\"exit\": 0}}', receipt_digest = '{DIGEST}', version = 3 {where}"
    )
    other = "sha256:" + "e" * 64
    for change in (
        f"receipt_digest = '{other}'",  # the receipt digest of a settled intent never moves
        "receipt = '{\"exit\": 1}'",
        "reason = 'late'",
        "state = 'in_doubt'",
    ):
        with pytest.raises(asyncpg.RestrictViolationError):
            await owner.execute(
                f"UPDATE mission_control.governed_effect_intent SET {change} {where}"
            )
    with pytest.raises(asyncpg.RestrictViolationError, match="never deleted"):
        await owner.execute(f"DELETE FROM mission_control.governed_effect_intent {where}")
    # Forced RLS: another tenant's runtime scope sees none of it.
    pool = await common_db.pool(max_size=2)
    try:
        for table in ("approval_correlation", "governed_effect_intent"):
            assert await scoped_count(pool, common_db.scope(), table) == 1, table
            assert await scoped_count(pool, common_db.scope("tenant-2"), table) == 0, table
            assert await scoped_count(pool, None, table) == 0, table
    finally:
        await pool.close()


async def test_mp15_guards_keep_causation_immutable_and_nothing_deleted(
    common_db: CommonDatabase,
    owner: asyncpg.Connection,
) -> None:
    scope = _scope(common_db)
    _run_key, _run_id, mission_id = await _admitted_run(common_db)
    (event,) = await owner_rows(
        common_db,
        "SELECT event_id FROM mission_control.mission_event WHERE mission_id = $1 "
        "ORDER BY seq LIMIT 1",
        mission_id,
    )
    now = datetime.now(UTC)
    subscription_id, notification_id, request_id = uuid4(), uuid4(), uuid4()
    await owner.execute(
        "INSERT INTO mission_control.mission_subscription (installation_id, application_id, "
        "tenant_id, subscription_id, target_kind, mission_id, event_types, channel_kind, "
        "channel, cursor_seq, state, failure_count, next_attempt_at, version, created_at, "
        "updated_at, created_by_actor_ref) VALUES ($1, $2, $3, $4, 'mission', $5, "
        "ARRAY['human_task.created'], 'stream_ticket', "
        '\'{"kind": "stream_ticket", "ticket": "coordinator-inbox:t"}\', 0, \'active\', 0, '
        "$6, 1, $6, $6, $7)",
        *scope,
        subscription_id,
        mission_id,
        now,
        ACTOR,
    )
    await owner.execute(
        "INSERT INTO mission_control.coordinator_inbox (installation_id, application_id, "
        "tenant_id, subscription_id, coordinator_ref, profile, delivery_kind, delivery, "
        "prompting, next_inbox_seq, acked_inbox_seq, version, created_at, updated_at, "
        "created_by_actor_ref) VALUES ($1, $2, $3, $4, 'coordinator-1', '{}', 'poll', "
        '\'{"kind": "poll"}\', false, 1, 0, 1, $5, $5, $6)',
        *scope,
        subscription_id,
        now,
        ACTOR,
    )
    await owner.execute(
        "INSERT INTO mission_control.coordinator_notification (installation_id, "
        "application_id, tenant_id, notification_id, subscription_id, state, kind, "
        "actionable, mission_id, seq_from, seq_to, event_count, anchor_event_id, depth, body, "
        "opened_at, version, created_at, updated_at, created_by_actor_ref) VALUES ($1, $2, $3, "
        "$4, $5, 'open', 'progress', false, $6, 1, 1, 1, $7, 0, "
        '\'{"schema_version": "mc.coordinator_notification.v1"}\', $8, 1, $8, $8, $9)',
        *scope,
        notification_id,
        subscription_id,
        mission_id,
        event["event_id"],
        now,
        ACTOR,
    )
    causation = (
        "INSERT INTO mission_control.coordinator_causation (installation_id, application_id, "
        "tenant_id, command_request_id, subscription_id, notification_id, origin, "
        "target_run_ref, depth, recorded_at, created_at, created_by_actor_ref) VALUES ($1, $2, "
        "$3, $4, $5, $6, 'prompt', 'run:coordinator', 1, $7, $7, $8)"
    )
    # Causation must name an existing inbox (FK added in review), not just a notification.
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await owner.execute(causation, *scope, uuid4(), uuid4(), notification_id, now, ACTOR)
    await owner.execute(causation, *scope, request_id, subscription_id, notification_id, now, ACTOR)
    with pytest.raises(asyncpg.RestrictViolationError, match="immutable"):
        await owner.execute(
            "UPDATE mission_control.coordinator_causation SET depth = 2 "
            f"WHERE command_request_id = '{request_id}'"
        )
    for table, key, value in (
        ("coordinator_causation", "command_request_id", request_id),
        ("coordinator_notification", "notification_id", notification_id),
        ("coordinator_inbox", "subscription_id", subscription_id),
    ):
        with pytest.raises(asyncpg.RestrictViolationError, match="immutable"):
            await owner.execute(f"DELETE FROM mission_control.{table} WHERE {key} = '{value}'")
    pool = await common_db.pool(max_size=2)
    try:
        for table in ("coordinator_inbox", "coordinator_notification", "coordinator_causation"):
            assert await scoped_count(pool, common_db.scope(), table) == 1, table
            assert await scoped_count(pool, common_db.scope("tenant-2"), table) == 0, table
    finally:
        await pool.close()
