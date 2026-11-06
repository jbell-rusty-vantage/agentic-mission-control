"""Additive 1.10.0 installer and restricted-role linked export schema proof."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import pytest

from mission_control.domain.authoring.manifest import load_manifest_yaml, parse_manifest
from mission_control.domain.composition.chain import (
    ChainScope,
    MissionChain,
    build_mission_chain,
    compile_chain,
)
from mission_control_db_contract.deployment import plan_release, verify_release
from tests.integration.postgres.test_mission_chain_tables import (
    FIXTURE,
    insert_chain,
    insert_mission,
)
from tests.integration.postgres.test_run2_release_141 import (
    CONTRACTS,
    PACKAGE,
    VERSIONS,
    assert_runtime_security,
    disposable,
    insert_document,
    install,
    release_at,
)
from tests.integration.postgres.test_sprint_v_release_150 import (
    as_role,
    create_tenant,
    raises_sqlstate,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.common_db]
SUCCESSOR = PACKAGE / "releases/1.10.0/component"
PREVIOUS = PACKAGE / "releases/1.9.0/component"
NEW = ["0068_exact_linked_exports"]


async def seed_links(
    connection: asyncpg.Connection, target: dict[str, str], tenant: UUID
) -> MissionChain:
    scope = ChainScope(
        installation_id=UUID(target["installation_id"]),
        application_id=target["application_id"],
        tenant_id=tenant,
    )
    doc = load_manifest_yaml(FIXTURE.read_text(encoding="utf-8"))
    doc["links"][0]["on_upstream_cancel"] = "cancel_downstream"
    doc["links"][1]["on_upstream_cancel"] = "detach"
    compiled = compile_chain(parse_manifest(doc))
    assert compiled.resolution is not None
    async with as_role(connection, target, tenant):
        members = {
            key: (await insert_mission(connection, scope, key), uuid4())
            for key in compiled.resolution.order
        }
        chain = build_mission_chain(
            resolution=compiled.resolution,
            chain_id=uuid4(),
            scope=scope,
            chain_key="schema-test",
            title="Schema test",
            manifest_digest="sha256:" + "a" * 64,
            members=members,
            created_at=datetime.now(UTC),
            created_by_actor_ref="fixture:1100",
        )
        await insert_chain(connection, chain)
    return chain


@pytest.mark.parametrize("upgrade", [False, True], ids=["fresh", "upgrade-from-190"])
async def test_release_1100_exact_exports_are_scoped_immutable_and_upgrade_safe(
    tmp_path: Path, upgrade: bool
) -> None:
    successor = release_at(SUCCESSOR, tmp_path / "successor-lock", "ai-engineer")
    async with disposable(tmp_path, "ai-engineer") as (target, connection):
        receipts, old_links = [], []
        tenant = None
        if upgrade:
            await install(target, release_at(PREVIOUS, tmp_path / "previous-lock", "ai-engineer"))
            receipts = await connection.fetch(
                "SELECT * FROM mission_control.component_release ORDER BY migration_key"
            )
            tenant = await create_tenant(connection, target)
            await seed_links(connection, target, tenant)
            old_links = await connection.fetch(
                "SELECT * FROM mission_control.chain_link ORDER BY link_id"
            )
            async with as_role(connection, target, tenant):
                await raises_sqlstate(
                    connection,
                    "23514",
                    "INSERT INTO mission_control.runtime_document "
                    "(installation_id,application_id,tenant_id,runtime_document_id,contract,"
                    "identity,payload,digest,recorded_at,created_at,created_by_actor_ref) "
                    "VALUES ($1::uuid,$2,$3,$4,'linked.export/1','pre-upgrade','{}',$5,now(),"
                    "now(),'fixture:1100')",
                    target["installation_id"],
                    target["application_id"],
                    tenant,
                    uuid4(),
                    "sha256:" + "a" * 64,
                )
        plan = await plan_release(target, successor, **VERSIONS)
        assert plan["plan"]["holds"] == []
        if upgrade:
            assert plan["plan"]["pending_migrations"] == NEW
        result = await install(target, successor)
        assert result["component_version"] == "1.10.0"
        assert (
            result["applied_migrations"] == NEW
            if upgrade
            else result["applied_migrations"][-1:] == NEW
        )
        for receipt in receipts:
            assert (
                await connection.fetchrow(
                    "SELECT * FROM mission_control.component_release WHERE migration_key=$1",
                    receipt["migration_key"],
                )
                == receipt
            )
        for old in old_links:
            current = dict(
                await connection.fetchrow(
                    "SELECT * FROM mission_control.chain_link WHERE link_id=$1", old["link_id"]
                )
            )
            assert json.loads(current.pop("transfer_policy")) == {}
            assert current == dict(old)
        tenant = tenant or await create_tenant(connection, target)
        if not upgrade:
            await seed_links(connection, target, tenant)
        async with as_role(connection, target, tenant):
            original = await connection.fetchrow("SELECT * FROM mission_control.chain_link LIMIT 1")
            assert original is not None
            clone = dict(original)
            for field in ("bindings", "release_condition", "transfer_policy"):
                clone[field] = json.loads(clone[field])
            clone.update(
                link_id=str(uuid4()),
                link_key="continued",
                on_upstream_cancel="continue",
                transfer_policy={
                    "receiving_purpose": "dependent_input",
                    "selector": "accepted_snapshot",
                    "placement": "file",
                },
            )
            await connection.execute(
                "INSERT INTO mission_control.chain_link SELECT * FROM jsonb_populate_record("
                "NULL::mission_control.chain_link,$1::jsonb)",
                json.dumps(clone, default=str),
            )
            await raises_sqlstate(
                connection,
                "42501",
                "UPDATE mission_control.chain_link SET transfer_policy='{}',state='cancelled',"
                "version=version+1 WHERE link_id=$1",
                UUID(clone["link_id"]),
            )
            for contract in (*CONTRACTS, "linked.export/1"):
                await insert_document(connection, target, tenant, contract, "schema:" + contract)
            assert (
                await connection.fetchval(
                    "SELECT count(*) FROM mission_control.runtime_document "
                    "WHERE contract='linked.export/1'"
                )
                == 1
            )
            await raises_sqlstate(
                connection,
                "42501",
                "UPDATE mission_control.runtime_document "
                "SET payload='{}' WHERE contract='linked.export/1'",
            )
            await raises_sqlstate(
                connection,
                "42501",
                "DELETE FROM mission_control.runtime_document WHERE contract='linked.export/1'",
            )
        await raises_sqlstate(
            connection,
            "23001",
            "UPDATE mission_control.chain_link SET transfer_policy='{}',state='cancelled',"
            "version=version+1 WHERE link_id=$1",
            UUID(clone["link_id"]),
        )
        for mutation in (
            "UPDATE mission_control.runtime_document SET payload='{}' "
            "WHERE contract='linked.export/1'",
            "DELETE FROM mission_control.runtime_document WHERE contract='linked.export/1'",
        ):
            await raises_sqlstate(connection, "23001", mutation)
        async with as_role(connection, target, tenant, role="mission_control_readonly"):
            assert (
                await connection.fetchval(
                    "SELECT count(*) FROM mission_control.runtime_document "
                    "WHERE contract='linked.export/1'"
                )
                == 1
            )
        other = await create_tenant(connection, target)
        async with as_role(connection, target, other):
            assert (
                await connection.fetchval(
                    "SELECT count(*) FROM mission_control.runtime_document "
                    "WHERE contract='linked.export/1'"
                )
                == 0
            )
            await raises_sqlstate(
                connection,
                "42501",
                "INSERT INTO mission_control.runtime_document "
                "SELECT installation_id,application_id,"
                "$1::uuid,$2::uuid,'linked.export/1','wrong-scope','{}',$3,"
                "now(),now(),'fixture:1100' "
                "FROM mission_control.tenant LIMIT 1",
                tenant,
                uuid4(),
                "sha256:" + "a" * 64,
            )
        index = await connection.fetchval(
            "SELECT pg_get_indexdef('mission_control."
            "runtime_document_linked_receiver_idx'::regclass)"
        )
        assert (
            "receiver_run_id" in index
            and "receiver_position" in index
            and "linked.export/1" in index
        )
        assert (await verify_release(target, successor, **VERSIONS))["status"] == "verified"
        assert (await install(target, successor))["applied_migrations"] == []
        await assert_runtime_security(connection, target)
