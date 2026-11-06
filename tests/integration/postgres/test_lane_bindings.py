"""FT-G1 migration 0030 (+ MP-01 migration 0031, HL-06 migration 0036) on a disposable
PostgreSQL 17: the lane profile registry and the execution binding lane columns, through real
grants and forced RLS."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio

from mission_control.application.execution.harness.describe import DECLARED_LANE_MATRICES
from tests.fixtures.mission_control_common_db import (
    CommonDatabase,
    create_common_database,
    drop_common_database,
)
from tests.integration.postgres.runtime_common import common_db  # noqa: F401

pytestmark = pytest.mark.common_db

DIGEST = "sha256:" + "d" * 64
# The nine Lane Profiles the registry seeds (0030 three, 0031 four and 0036 two v2 stubs).
SEEDED_PROFILES = sorted(DECLARED_LANE_MATRICES)
SUCCESSOR_COMPONENT = (
    Path(__file__).resolve().parents[3]
    / "packages/mission-control-db-contract/releases/1.4.1/component"
)


@pytest_asyncio.fixture
async def successor_db() -> AsyncIterator[CommonDatabase]:
    """Current describes use explicit 1.4.1 SQL; other historical tests retain 1.4.0."""
    database = await create_common_database(
        paths=sorted((SUCCESSOR_COMPONENT / "migrations").glob("*.sql")),
        component_version="1.4.1",
    )
    try:
        yield database
    finally:
        await drop_common_database(database)


async def test_lane_profiles_are_seeded_with_their_declared_describes(
    successor_db: CommonDatabase,
) -> None:
    owner = await asyncpg.connect(successor_db.owner_dsn)
    try:
        rows = await owner.fetch(
            "SELECT lane_profile, lane, placement, describe, qualified, qualification_ref "
            "FROM mission_control.lane_profile ORDER BY lane_profile"
        )
    finally:
        await owner.close()
    assert [row["lane_profile"] for row in rows] == SEEDED_PROFILES
    assert len(rows) == 9
    for row in rows:
        declared = DECLARED_LANE_MATRICES[row["lane_profile"]]
        assert json.loads(row["describe"]) == declared.model_dump(mode="json")
        assert row["lane"] == declared.lane and row["placement"] == declared.placement
        assert row["qualified"] is declared.qualified
        assert (row["qualification_ref"] is not None) is declared.qualified


async def test_runtime_reads_but_never_writes_lane_profiles(
    common_db: CommonDatabase,  # noqa: F811
) -> None:
    pool = await common_db.pool("mission_control_runtime")
    try:
        async with pool.acquire() as connection:
            count = await connection.fetchval("SELECT count(*) FROM mission_control.lane_profile")
            assert count == len(SEEDED_PROFILES)
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await connection.execute(
                    "UPDATE mission_control.lane_profile SET qualified = true "
                    "WHERE lane_profile = 'cursor_local'"
                )
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await connection.execute(
                    "INSERT INTO mission_control.lane_profile (lane_profile, lane, placement, "
                    "describe) VALUES ('gemini_local', 'cursor', 'cloud', '{}'::jsonb)"
                )
    finally:
        await pool.close()


async def _insert_binding(
    connection: asyncpg.Connection,
    db: CommonDatabase,
    lane_profile: str | None,
    lane_binding: object,
) -> None:
    tenant = db.tenants["tenant-1"]
    columns = (
        "installation_id, application_id, tenant_id, execution_binding_id, binding_key, "
        "binding_contract, manifest, manifest_digest, admission_decision, admitted_at, "
        "created_at, created_by_actor_ref"
    )
    values = (
        "$1, $2, $3, $4, $5, 'operation-binding/1', '{}'::jsonb, $6, 'admitted', $7, $7, 'ft-g1'"
    )
    args: list[object] = [
        db.installation_id,
        db.application_id,
        tenant,
        uuid.uuid4(),
        f"binding:{uuid.uuid4()}",
        DIGEST,
        datetime.now(UTC),
    ]
    if lane_profile is not None:
        columns += ", lane_profile, lane_binding"
        values += ", $8, $9::jsonb"
        args.extend([lane_profile, json.dumps(lane_binding) if lane_binding is not None else None])
    await connection.execute(
        f"INSERT INTO mission_control.execution_binding ({columns}) VALUES ({values})", *args
    )


async def test_execution_bindings_default_to_deep_agents_and_cursor_requires_its_binding(
    common_db: CommonDatabase,  # noqa: F811
) -> None:
    owner = await asyncpg.connect(common_db.owner_dsn)
    try:
        await _insert_binding(owner, common_db, None, None)
        assert await owner.fetchval(
            "SELECT array_agg(DISTINCT lane_profile) FROM mission_control.execution_binding"
        ) == ["deep_agents"]
        with pytest.raises(asyncpg.CheckViolationError):
            await _insert_binding(owner, common_db, "cursor_local", None)
        with pytest.raises(asyncpg.CheckViolationError):
            await _insert_binding(
                owner,
                common_db,
                "cursor_local",
                {"schema_version": "mc.cursor_binding.v1", "lane_profile": "cursor_cloud"},
            )
        # MP-01: an unknown profile is still the FK violation; the seeded `codex` profile needs
        # its typed `mc.execution_binding.v2` document (a cursor binding or none is refused).
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await _insert_binding(owner, common_db, "gemini_local", None)
        for profile in (
            "claude_agent_sdk",
            "codex",
            "claude_cloud",
            "codex_cloud",
            "claude_managed",
            "codex_agents",
        ):
            with pytest.raises(asyncpg.CheckViolationError):
                await _insert_binding(owner, common_db, profile, None)
        with pytest.raises(asyncpg.CheckViolationError):
            await _insert_binding(
                owner,
                common_db,
                "codex",
                {"schema_version": "mc.cursor_binding.v1", "lane_profile": "codex"},
            )
        with pytest.raises(asyncpg.CheckViolationError):
            await _insert_binding(
                owner,
                common_db,
                "codex",
                {
                    "schema_version": "mc.execution_binding.v2",
                    "lane_profile": "claude_agent_sdk",
                    "binding_digest": DIGEST,
                },
            )
        await _insert_binding(
            owner,
            common_db,
            "cursor_local",
            {"schema_version": "mc.cursor_binding.v1", "lane_profile": "cursor_local"},
        )
        for profile in ("codex", "claude_managed", "codex_agents"):
            await _insert_binding(
                owner,
                common_db,
                profile,
                {
                    "schema_version": "mc.execution_binding.v2",
                    "lane_profile": profile,
                    "binding_digest": DIGEST,
                },
            )
        for profile in ("cursor_local", "codex", "claude_managed", "codex_agents"):
            assert (
                await owner.fetchval(
                    "SELECT count(*) FROM mission_control.execution_binding "
                    "WHERE lane_profile = $1",
                    profile,
                )
                == 1
            )
    finally:
        await owner.close()


async def test_0036_admits_the_hosted_agent_api_profiles_on_every_lane_profile_check(
    common_db: CommonDatabase,  # noqa: F811
) -> None:
    """HL-06: frames, native identity, continuation records, search documents and capability
    host support admit `claude_managed` and `codex_agents` (and still refuse an unknown one)."""

    owner = await asyncpg.connect(common_db.owner_dsn)
    try:
        checks = await owner.fetch(
            "SELECT conname, pg_get_constraintdef(oid) AS definition FROM pg_constraint "
            "WHERE conname = ANY($1::text[])",
            [
                "harness_execution_lane_profile_check",
                "provider_frame_lane_profile_check",
                "continuation_transfer_lane_profile_check",
                "search_document_host_profiles_known",
            ],
        )
        assert len(checks) == 4
        for check in checks:
            for profile in ("claude_managed", "codex_agents"):
                assert f"'{profile}'" in check["definition"], check["conname"]
        valid = "SELECT mission_control.capability_host_support_valid($1::jsonb)"
        for profile in ("claude_managed", "codex_agents"):
            document = {
                "schema_version": "mc.capability_host_support.v1",
                "profiles": {profile: {"status": "unqualified"}},
            }
            assert await owner.fetchval(valid, json.dumps(document)) is True
        unknown = {
            "schema_version": "mc.capability_host_support.v1",
            "profiles": {"gemini_local": {"status": "supported"}},
        }
        assert await owner.fetchval(valid, json.dumps(unknown)) is False
    finally:
        await owner.close()
