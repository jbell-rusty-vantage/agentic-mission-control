"""MO-16: migration 0037 and the environment preparation repository on a real disposable
PostgreSQL 17 (MISSION_CONTROL_TEST_ADMIN_DSN, loopback only).

- `environment_readiness_level` is seeded reference data: the six levels with their ranks,
  readable without tenant scope, immutable, never writable by the runtime role.
- `environment_preparation` is tenant scoped under forced RLS with one three-column policy, a
  tenant FK, REVOKE PUBLIC, runtime SELECT/INSERT plus column-limited UPDATE, readonly SELECT.
- The repository inserts, merges later levels under the row lock (versions advance by one) and
  never regresses; a generation prepared again with another receipt keeps the recorded one
  (nothing is written); the guard refuses a regressed level, a changed receipt or identity, a
  skipped version and a delete even from the owner.
- The launch gate over the repository: `lane.turn` refuses to start a session below the
  minimum readiness and settles `failed(environment_not_ready)`; a prepared environment starts
  and a hook frame records `exercised`, all persisted in PostgreSQL.
- MO-34: readiness reaches `discovered` on every lane with a discovery mechanism (the three
  local lanes, cursor_cloud and both hosted API lanes), each from its own mechanism's report,
  and the stored record keeps the expectation the report was compared with.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import pytest
import pytest_asyncio

from mission_control.adapters.postgres.environments import (
    PostgresEnvironmentPreparationRepository,
)
from mission_control.application.environments import (
    EnvironmentPreparationService,
    preparation_of,
)
from mission_control.application.execution.harness.lane_turns import LaneExecutionIdentity
from mission_control.domain.execution.contracts import (
    OperationExecutionRequest,
    OperationExecutionResult,
)
from mission_control.domain.execution.environment_preparation import (
    ENVIRONMENT_NOT_READY,
    READINESS_LADDER,
    EnvironmentPreparation,
    ReadinessLevel,
)
from mission_control.domain.execution.lane_turns import LaneTurnRequest
from mission_control.domain.execution.lanes import CursorExecutionBinding, PreparedSession
from tests.fixtures.discovery_lanes import DISCOVERING_LANES, Attempt, scenario
from tests.fixtures.lane_turns import (
    ACTIVATION_UUID,
    RUN_UUID,
    PreparingLane,
    RecordingSignals,
    ScriptedSessionLane,
    cursor_operation,
    lane_stack,
    scripted_frames,
)
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.integration.postgres.runtime_common import (  # noqa: F401
    common_db,
    owner_rows,
    scoped_count,
)

pytestmark = pytest.mark.common_db

AT = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
DIGEST = "sha256:" + "f" * 64
TABLE = "environment_preparation"
RUNTIME_UPDATE_COLUMNS = {"readiness", "receipt_digest", "record", "version", "updated_at"}
OTHER_ROLES = (
    "mission_control_family_writer",
    "mission_control_catalog_writer",
    "mission_control_outbox_worker",
    "public",
)
PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")


def _operation(db: CommonDatabase) -> OperationExecutionRequest:
    return cursor_operation(request_scope=db.scope())


def _identity(db: CommonDatabase) -> LaneExecutionIdentity:
    return LaneExecutionIdentity.of(_operation(db), "cursor_local", 1)


def _prepared(**changes: Any) -> PreparedSession:
    fields: dict[str, Any] = {
        "lane_profile": "cursor_local",
        "harness_execution_id": "hx",
        "generation": 1,
        "workspace_ref": "workspace_lease:lease-1",
        "projection_digests": {"rules_digest": DIGEST},
        "materialization_ref": DIGEST,
        **changes,
    }
    return PreparedSession.model_validate(fields)


def _record(db: CommonDatabase, prepared: PreparedSession) -> EnvironmentPreparation:
    binding = CursorExecutionBinding.carried_by(_operation(db))
    assert binding is not None
    return preparation_of(_identity(db), binding, prepared, at=AT)


@pytest_asyncio.fixture
async def pool(common_db: CommonDatabase) -> AsyncIterator[asyncpg.Pool]:  # noqa: F811
    created = await common_db.pool("mission_control_runtime")
    try:
        yield created
    finally:
        await created.close()


@pytest_asyncio.fixture
async def owner(common_db: CommonDatabase) -> AsyncIterator[asyncpg.Connection]:  # noqa: F811
    connection = await asyncpg.connect(common_db.owner_dsn)
    try:
        yield connection
    finally:
        await connection.close()


async def _privileges(db: CommonDatabase, role: str, table: str) -> set[str]:
    rows = await owner_rows(
        db,
        "SELECT privilege FROM unnest($3::text[]) AS privilege "
        "WHERE has_table_privilege($1, 'mission_control.' || $2, privilege)",
        role,
        table,
        list(PRIVILEGES),
    )
    return {row["privilege"] for row in rows}


async def _update_columns(db: CommonDatabase, role: str, table: str) -> set[str]:
    rows = await owner_rows(
        db,
        "SELECT a.attname FROM pg_attribute a "
        "WHERE a.attrelid = ('mission_control.' || $2)::regclass AND a.attnum > 0 "
        "AND NOT a.attisdropped AND has_column_privilege($1, a.attrelid, a.attnum, 'UPDATE')",
        role,
        table,
    )
    return {row["attname"] for row in rows}


# --------------------------------------------------------------------------- catalog shape


async def test_the_readiness_ladder_is_seeded_immutable_reference_data(
    common_db: CommonDatabase,  # noqa: F811
    owner: asyncpg.Connection,
) -> None:
    rows = await owner.fetch(
        "SELECT readiness, rank FROM mission_control.environment_readiness_level ORDER BY rank"
    )
    assert [(row["readiness"], row["rank"]) for row in rows] == [
        (level.value, rank) for rank, level in enumerate(READINESS_LADDER)
    ]
    with pytest.raises(asyncpg.RestrictViolationError, match="immutable"):
        await owner.execute(
            "UPDATE mission_control.environment_readiness_level SET rank = 9 "
            "WHERE readiness = 'prepared'"
        )
    runtime = await asyncpg.connect(common_db.dsn())
    try:
        count = "SELECT count(*) FROM mission_control.environment_readiness_level"
        assert await runtime.fetchval(count) == len(READINESS_LADDER)
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await runtime.execute(
                "INSERT INTO mission_control.environment_readiness_level VALUES ('ready', 9)"
            )
    finally:
        await runtime.close()


async def test_preparations_are_scoped_forced_rls_with_declared_grants(
    common_db: CommonDatabase,  # noqa: F811
) -> None:
    (row,) = await owner_rows(
        common_db,
        """
        SELECT c.relrowsecurity, c.relforcerowsecurity,
               (SELECT array_agg(pg_get_expr(p.polqual, p.polrelid) || ' / '
                                 || pg_get_expr(p.polwithcheck, p.polrelid))
                FROM pg_policy p WHERE p.polrelid = c.oid) AS policies,
               EXISTS (SELECT 1 FROM pg_constraint k WHERE k.conrelid = c.oid
                       AND k.contype = 'f'
                       AND k.confrelid = 'mission_control.tenant'::regclass) AS tenant_fk,
               (SELECT count(*) FROM aclexplode(c.relacl) x WHERE x.grantee = 0) AS public_acl
        FROM pg_class c WHERE c.oid = 'mission_control.environment_preparation'::regclass
        """,
    )
    assert (row["relrowsecurity"], row["relforcerowsecurity"]) == (True, True)
    assert row["tenant_fk"] and row["public_acl"] == 0
    (policy,) = row["policies"]
    for function in ("ctx_installation_id", "ctx_application_id", "ctx_tenant_id"):
        assert policy.count(function) == 2, policy
    assert await _privileges(common_db, "mission_control_runtime", TABLE) == {"SELECT", "INSERT"}
    assert await _update_columns(common_db, "mission_control_runtime", TABLE) == (
        RUNTIME_UPDATE_COLUMNS
    )
    assert await _privileges(common_db, "mission_control_readonly", TABLE) == {"SELECT"}
    for role in OTHER_ROLES:
        assert await _privileges(common_db, role, TABLE) == set(), role
    assert not (
        await owner_rows(
            common_db,
            "SELECT has_function_privilege('public', "
            "'mission_control.environment_preparation_guard()', 'EXECUTE') AS allowed",
        )
    )[0]["allowed"]


# --------------------------------------------------------------------------- repository


async def test_the_repository_inserts_merges_and_never_regresses(
    common_db: CommonDatabase,  # noqa: F811
    pool: asyncpg.Pool,
) -> None:
    repository = PostgresEnvironmentPreparationRepository(pool, clock=lambda: AT)
    scope = common_db.scope()
    delivered = _record(common_db, _prepared(materialization_ref=None))
    assert delivered.readiness is ReadinessLevel.DELIVERED
    assert await repository.record(scope, delivered) == delivered

    prepared = _record(common_db, _prepared())
    stored = await repository.record(scope, prepared)
    assert stored.readiness is ReadinessLevel.PREPARED and stored.receipt_digest == DIGEST
    # The earlier delivered-only observation arriving again changes nothing, nor does the
    # generation prepared again into its reused lease with another receipt.
    assert await repository.record(scope, delivered) == stored
    other_receipt = _record(common_db, _prepared(materialization_ref="sha256:" + "9" * 64))
    assert await repository.record(scope, other_receipt) == stored
    exercised = stored.advanced(
        ReadinessLevel.EXERCISED, at=AT + timedelta(seconds=5), evidence_ref="frame:hook"
    )
    # A worker whose clock is behind merges too; the row is never updated back in time.
    behind = PostgresEnvironmentPreparationRepository(pool, clock=lambda: AT - timedelta(hours=1))
    assert await behind.record(scope, exercised) == exercised
    assert await repository.get(scope, stored.preparation_id) == exercised
    assert await repository.for_run(scope, stored.run_key) == (exercised,)

    (row,) = await owner_rows(
        common_db,
        "SELECT readiness, receipt_digest, version, declaration_digest, lane_profile, "
        "updated_at FROM mission_control.environment_preparation WHERE preparation_id = $1",
        stored.preparation_id,
    )
    assert dict(row) == {
        "readiness": "exercised",
        "receipt_digest": DIGEST,
        "version": 3,
        "declaration_digest": stored.declaration_digest,
        "lane_profile": "cursor_local",
        "updated_at": AT,
    }
    # Forced RLS: another tenant and an unscoped session see nothing.
    assert await scoped_count(pool, scope, TABLE) == 1
    assert await scoped_count(pool, common_db.scope("tenant-2"), TABLE) == 0
    assert await scoped_count(pool, None, TABLE) == 0
    assert await repository.get(common_db.scope("tenant-2"), stored.preparation_id) is None
    with pytest.raises(LookupError, match="another scope"):
        await repository.record(common_db.scope("tenant-2"), stored)


async def test_the_guard_refuses_what_the_merge_never_does(
    common_db: CommonDatabase,  # noqa: F811
    pool: asyncpg.Pool,
    owner: asyncpg.Connection,
) -> None:
    repository = PostgresEnvironmentPreparationRepository(pool, clock=lambda: AT)
    stored = await repository.record(common_db.scope(), _record(common_db, _prepared()))
    update = "UPDATE mission_control.environment_preparation SET"
    where = f"WHERE preparation_id = '{stored.preparation_id}'"
    other = "sha256:" + "0" * 64
    for change, message in (
        ("readiness = 'delivered', version = version + 1", "never regresses"),
        (f"receipt_digest = '{other}', version = version + 1", "receipt is immutable"),
        (f"binding_digest = '{other}', version = version + 1", "bound to its attempt"),
        ("generation = 2, version = version + 1", "bound to its attempt"),
        ("version = version + 2", "advances by one"),
        (f"preparation_id = '{uuid4()}', version = version + 1", "bound to its attempt"),
        (
            "updated_at = updated_at - interval '1 second', version = version + 1",
            "back in time",
        ),
    ):
        with pytest.raises(asyncpg.RestrictViolationError, match=message):
            await owner.execute(f"{update} {change} {where}")
    with pytest.raises(asyncpg.RestrictViolationError, match="never deleted"):
        await owner.execute(f"DELETE FROM mission_control.environment_preparation {where}")
    # The typed columns must agree with the record they mirror.
    with pytest.raises(asyncpg.CheckViolationError):
        await owner.execute(f"{update} readiness = 'discovered', version = version + 1 {where}")


# --------------------------------------------------------------------------- launch gate


def _gate_stack(db: CommonDatabase, pool: asyncpg.Pool, lane: Any) -> Any:
    operation = _operation(db)
    service = EnvironmentPreparationService(PostgresEnvironmentPreparationRepository(pool))
    stack = lane_stack(lane, operation=operation, preparations=service)
    stack.frames.register_run(
        db.scope(),
        operation.identity.run_id,
        RUN_UUID,
        {operation.identity.operation_id: ACTIVATION_UUID},
    )
    return stack, LaneTurnRequest(operation=operation, lane_profile="cursor_local", generation=1)


async def _stored_readiness(db: CommonDatabase, harness_execution_id: UUID) -> list[Any]:
    return await owner_rows(
        db,
        "SELECT readiness, receipt_digest, record FROM mission_control.environment_preparation "
        "WHERE harness_execution_id = $1",
        harness_execution_id,
    )


async def test_the_launch_policy_refuses_a_session_below_the_minimum(
    common_db: CommonDatabase,  # noqa: F811
    pool: asyncpg.Pool,
) -> None:
    lane = ScriptedSessionLane(frames=scripted_frames())
    stack, request = _gate_stack(common_db, pool, lane)
    result = await stack.service.turn(request, RecordingSignals(stack.frames))

    settled = OperationExecutionResult.model_validate(result.operation_result)
    assert settled.status == "failed" and settled.failure_code == ENVIRONMENT_NOT_READY
    assert lane.calls == ["prepare"], "the session never started"
    (row,) = await _stored_readiness(common_db, _identity(common_db).harness_execution_id)
    assert (row["readiness"], row["receipt_digest"]) == ("declared", None)


async def test_a_prepared_environment_starts_and_is_exercised(
    common_db: CommonDatabase,  # noqa: F811
    pool: asyncpg.Pool,
) -> None:
    frames = scripted_frames()
    frames.insert(1, ("hook.invoked", {"hook": "mc.stop_fence", "event": "before_tool"}))
    lane = PreparingLane(frames=frames)
    stack, request = _gate_stack(common_db, pool, lane)
    result = await stack.service.turn(request, RecordingSignals(stack.frames))

    settled = OperationExecutionResult.model_validate(result.operation_result)
    assert settled.status == "completed"
    (row,) = await _stored_readiness(common_db, _identity(common_db).harness_execution_id)
    assert row["readiness"] == "exercised" and row["receipt_digest"] is not None
    record = EnvironmentPreparation.model_validate_json(row["record"])
    assert [mark.level.value for mark in record.marks] == [
        "declared",
        "rendered",
        "delivered",
        "prepared",
        "exercised",
    ]


@pytest.mark.parametrize("lane", DISCOVERING_LANES)
async def test_readiness_reaches_discovered_on_every_lane_with_a_mechanism(
    common_db: CommonDatabase,  # noqa: F811
    pool: asyncpg.Pool,
    tmp_path: Path,
    lane: str,
) -> None:
    case = await scenario(lane, tmp_path)
    attempt = Attempt(request_scope=common_db.scope(), lane_profile=lane)
    repository = PostgresEnvironmentPreparationRepository(pool, clock=lambda: AT)
    service = EnvironmentPreparationService(repository, clock=lambda: AT)
    started = await service.admit_start(attempt, case.binding, case.prepared)
    local = lane in {"claude_agent_sdk", "codex", "cursor_local"}
    assert started.readiness is (ReadinessLevel.PREPARED if local else ReadinessLevel.DELIVERED)

    outcome = await service.discovered(attempt, case.report, evidence_ref=f"proof:{lane}")

    assert outcome.gaps == ()
    (row,) = await _stored_readiness(common_db, attempt.harness_execution_id)
    assert row["readiness"] == "discovered"
    record = EnvironmentPreparation.model_validate_json(row["record"])
    assert record.discovery == case.prepared.discovery
    levels = [mark.level.value for mark in record.marks]
    assert levels == ["declared", "rendered", "delivered", "prepared", "discovered"]
    if not local:
        # A provider-side proof is the cloud environment's preparation receipt.
        assert row["receipt_digest"] == case.report.digest
