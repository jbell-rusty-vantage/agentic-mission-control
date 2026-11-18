"""FT-D1: migration 0028 (mission_chain, chain_link, authoring_provenance, relationship kinds)
on a disposable PostgreSQL 17: forced RLS, grants, forward-only guards and the chain contract
round trip through real restricted roles."""

from __future__ import annotations

import json
from uuid import uuid4

import asyncpg
import pytest

from mission_control.adapters.postgres.scope import apply_scope
from mission_control.contracts.identities import parse_request_scope
from mission_control.domain.authoring.manifest import load_manifest_yaml, parse_manifest
from mission_control.domain.composition.chain import (
    ChainScope,
    MissionChain,
    build_mission_chain,
    compile_chain,
)
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.support.integration.postgres.mission_chain_tables import (
    FIXTURE,
    NOW,
    insert_chain,
    insert_mission,
)

pytestmark = pytest.mark.common_db

TABLES = ("mission_chain", "chain_link", "authoring_provenance")


async def seed_chain(pool: asyncpg.Pool, db: CommonDatabase) -> MissionChain:
    request_scope = parse_request_scope(db.scope())
    scope = ChainScope(
        installation_id=request_scope.installation_id,
        application_id=request_scope.application_id,
        tenant_id=request_scope.tenant_id,
    )
    compilation = compile_chain(
        parse_manifest(load_manifest_yaml(FIXTURE.read_text(encoding="utf-8")))
    )
    assert compilation.resolution is not None
    async with pool.acquire() as connection, connection.transaction():
        await apply_scope(connection, db.scope())
        members = {
            key: (await insert_mission(connection, scope, f"{key}-{uuid4().hex[:6]}"), uuid4())
            for key in compilation.resolution.order
        }
        chain = build_mission_chain(
            resolution=compilation.resolution,
            chain_id=uuid4(),
            scope=scope,
            chain_key="two-mission-chain",
            title="Research then ingestion",
            manifest_digest="sha256:" + "c" * 64,
            members=members,
            created_at=NOW,
            created_by_actor_ref="actor:owner",
        )
        await insert_chain(connection, chain)
    return chain


async def scoped(pool: asyncpg.Pool, scope: str | None, query: str, *args: object) -> object:
    async with pool.acquire() as connection, connection.transaction():
        if scope is not None:
            await apply_scope(connection, scope)
        return await connection.fetchval(query, *args)


async def test_tables_force_rls_and_grant_least_privilege(common_db: CommonDatabase):
    owner = await asyncpg.connect(common_db.owner_dsn)
    try:
        rows = await owner.fetch(
            "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE relnamespace = 'mission_control'::regnamespace AND relname = ANY($1)",
            list(TABLES),
        )
        flags = {row["relname"]: (row[1], row[2]) for row in rows}
        assert flags == dict.fromkeys(TABLES, (True, True))
        privileges = {
            (role, table): await owner.fetchval(
                "SELECT array_agg(p ORDER BY p) FROM unnest(ARRAY['SELECT','INSERT','UPDATE',"
                "'DELETE']) p WHERE has_table_privilege($1, 'mission_control.' || $2, p)",
                role,
                table,
            )
            for role in ("mission_control_runtime", "mission_control_readonly")
            for table in TABLES
        }
        assert privileges[("mission_control_readonly", "mission_chain")] == ["SELECT"]
        assert privileges[("mission_control_runtime", "authoring_provenance")] == [
            "INSERT",
            "SELECT",
        ]
        # Column-limited UPDATE: identity columns are not updatable by the runtime.
        assert await owner.fetchval(
            "SELECT has_column_privilege('mission_control_runtime', "
            "'mission_control.chain_link', 'state', 'UPDATE')"
        )
        assert not await owner.fetchval(
            "SELECT has_column_privilege('mission_control_runtime', "
            "'mission_control.chain_link', 'bindings', 'UPDATE')"
        )
        kinds = await owner.fetchval(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'mission_relationship_kind_check'"
        )
        for kind in (
            "composition",
            "fork",
            "dependency",
            "supplies",
            "depends_on",
            "parent_of",
            "adopted_from",
            "successor_of",
            "forked_from",
        ):
            assert f"'{kind}'" in kinds
    finally:
        await owner.close()


async def test_chain_round_trip_is_scoped(common_db: CommonDatabase):
    pool = await common_db.pool("mission_control_runtime")
    try:
        chain = await seed_chain(pool, common_db)
        assert (
            await scoped(pool, common_db.scope(), "SELECT count(*) FROM mission_control.chain_link")
            == 2
        )
        assert await scoped(pool, None, "SELECT count(*) FROM mission_control.chain_link") == 0
        assert (
            await scoped(
                pool,
                common_db.scope("tenant-2"),
                "SELECT count(*) FROM mission_control.mission_chain",
            )
            == 0
        )
        members = await scoped(
            pool,
            common_db.scope(),
            "SELECT members::text FROM mission_control.mission_chain WHERE chain_id = $1",
            chain.chain_id,
        )
        assert [item["mission_key"] for item in json.loads(str(members))] == [
            "research",
            "ingestion",
        ]
        condition = await scoped(
            pool,
            common_db.scope(),
            "SELECT release_condition::text FROM mission_control.chain_link WHERE link_key = $1",
            "research->ingestion:supplies",
        )
        assert json.loads(str(condition)) == {"kind": "goal_accepted", "goal_key": "evidence_map"}
    finally:
        await pool.close()


async def expect_rejected(pool: asyncpg.Pool, db: CommonDatabase, query: str, *args: object) -> str:
    with pytest.raises(asyncpg.PostgresError) as caught:
        await scoped(pool, db.scope(), query, *args)
    return str(caught.value)


async def test_links_move_forward_only(common_db: CommonDatabase):
    pool = await common_db.pool("mission_control_runtime")
    try:
        chain = await seed_chain(pool, common_db)
        supplies, depends = chain.links
        # armed -> released with release facts.
        await scoped(
            pool,
            common_db.scope(),
            "UPDATE mission_control.chain_link SET state = 'released', released_at = $2, "
            "packet_digest = $3, version = version + 1, updated_at = $2 WHERE link_id = $1",
            supplies.link_id,
            NOW,
            "sha256:" + "d" * 64,
        )
        # released -> armed, a stale version, and rewriting release facts are refused.
        for query in (
            "UPDATE mission_control.chain_link SET state = 'armed', version = version + 1 "
            "WHERE link_id = $1",
            "UPDATE mission_control.chain_link SET state = 'detached', version = version + 2 "
            "WHERE link_id = $1",
            "UPDATE mission_control.chain_link SET state = 'detached', packet_digest = NULL, "
            "version = version + 1 WHERE link_id = $1",
        ):
            assert "forward" in await expect_rejected(pool, common_db, query, supplies.link_id)
        # blocked needs a reason (CHECK) and is final.
        await expect_rejected(
            pool,
            common_db,
            "UPDATE mission_control.chain_link SET state = 'blocked', version = version + 1 "
            "WHERE link_id = $1",
            depends.link_id,
        )
        await scoped(
            pool,
            common_db.scope(),
            "UPDATE mission_control.chain_link SET state = 'blocked', "
            "blocked_reason = 'upstream_not_accepted', version = version + 1 WHERE link_id = $1",
            depends.link_id,
        )
        assert "forward" in await expect_rejected(
            pool,
            common_db,
            "UPDATE mission_control.chain_link SET state = 'cancelled', blocked_reason = NULL, "
            "version = version + 1 WHERE link_id = $1",
            depends.link_id,
        )
        # Rows are never deleted (and the runtime has no DELETE grant at all).
        await expect_rejected(
            pool,
            common_db,
            "DELETE FROM mission_control.chain_link WHERE link_id = $1",
            depends.link_id,
        )
    finally:
        await pool.close()


async def test_chain_lifecycle_is_forward_only_and_completion_is_final(common_db: CommonDatabase):
    pool = await common_db.pool("mission_control_runtime")
    try:
        chain = await seed_chain(pool, common_db)
        update = (
            "UPDATE mission_control.mission_chain SET lifecycle = $2, terminal_outcome = $3, "
            "version = version + 1, updated_at = now() WHERE chain_id = $1"
        )
        # completed requires a terminal outcome (CHECK).
        await expect_rejected(pool, common_db, update, chain.chain_id, "completed", None)
        await scoped(pool, common_db.scope(), update, chain.chain_id, "running", None)
        await expect_rejected(pool, common_db, update, chain.chain_id, "pending", None)
        await scoped(pool, common_db.scope(), update, chain.chain_id, "completed", "accepted")
        assert "forward" in await expect_rejected(
            pool, common_db, update, chain.chain_id, "completed", "not_accepted"
        )
    finally:
        await pool.close()
