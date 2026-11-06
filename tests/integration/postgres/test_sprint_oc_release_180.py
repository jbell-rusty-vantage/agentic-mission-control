"""Actual 1.8.0 installer proof (Sprint OC W1 / OVE-169).

1.8.0 is the built 1.7.0 prefix plus 0061 (WI-22 durable transition reactions), 0063 (WI-19
coordinator delivery observations) and 0064 (W1 D7: USAGE on schema ``extensions`` for the roles
that rank capability search). Fresh install and upgrade from 1.7.0 with preserved receipts,
verify and an idempotent re-apply, forced row security, comments and runtime grants without
DELETE on every new table, the extension privileges of exactly the three search roles, and the
runtime security baseline. The behaviour of 0061 and 0063 is proven through their stores in
``test_wi22_reactions_postgres.py`` and ``test_wi19_attention_postgres.py``; the Supabase-like
(non-superuser installer) upgrade and the refusal without GRANT OPTION are proven in the
db-contract package (``test_release_180_search_privileges.py``). Prior releases stay immutable.
"""

from __future__ import annotations

import pytest

from mission_control_db_contract.deployment import verify_release
from tests.integration.postgres.test_run2_release_141 import (
    PACKAGE,
    VERSIONS,
    assert_runtime_security,
    disposable,
    install,
    release_at,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.common_db]
SUCCESSOR = PACKAGE / "releases/1.8.0/component"
PREVIOUS = PACKAGE / "releases/1.7.0/component"
NEW = [
    "0061_durable_transition_reactions",
    "0063_coordinator_delivery_observations",
    "0064_search_extension_privileges",
]
TABLES = (
    "reaction_binding",
    "reaction_transition",
    "reaction_activation",
    "reaction_capture_anomaly",
    "coordinator_delivery_observation",
)
SEARCH_ROLES = (
    "mission_control_runtime",
    "mission_control_catalog_writer",
    "mission_control_outbox_worker",
)


@pytest.mark.parametrize("upgrade", [None, "1.7.0"], ids=["fresh", "upgrade-from-170"])
async def test_release_180_installs_reactions_observations_and_search_privileges(tmp_path, upgrade):
    successor = release_at(SUCCESSOR, tmp_path / "successor-lock", "ai-engineer")
    async with disposable(tmp_path, "ai-engineer") as (target, connection):
        before = []
        if upgrade:
            await install(target, release_at(PREVIOUS, tmp_path / "previous-lock", "ai-engineer"))
            before = await connection.fetch(
                "SELECT * FROM mission_control.component_release ORDER BY migration_key"
            )
            assert not await connection.fetchval(
                "SELECT has_schema_privilege('mission_control_runtime', 'extensions', 'USAGE')"
            )
        result = await install(target, successor)
        assert result["component_version"] == "1.8.0"
        if upgrade:
            assert result["applied_migrations"] == NEW
        else:
            assert result["applied_migrations"][-3:] == NEW
            assert "0062" not in " ".join(result["applied_migrations"])
        for row in before:
            assert (
                await connection.fetchrow(
                    "SELECT * FROM mission_control.component_release WHERE migration_key=$1",
                    row["migration_key"],
                )
                == row
            )
        for name in TABLES:
            table = f"mission_control.{name}"
            assert await connection.fetchval(
                "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class "
                "WHERE oid=$1::regclass",
                table,
            ), table
            assert await connection.fetchval(
                "SELECT obj_description($1::regclass, 'pg_class') IS NOT NULL", table
            ), table
            assert not await connection.fetchval(
                "SELECT has_table_privilege('mission_control_runtime', $1, 'DELETE')", table
            ), table
        for role in SEARCH_ROLES:
            assert await connection.fetchval(
                "SELECT has_schema_privilege($1, 'extensions', 'USAGE')", role
            ), role
            assert not await connection.fetchval(
                "SELECT has_schema_privilege($1, 'extensions', 'CREATE')", role
            ), role
        assert not await connection.fetchval(
            "SELECT has_schema_privilege('mission_control_readonly', 'extensions', 'USAGE')"
        )
        async with connection.transaction():
            await connection.execute("SET LOCAL ROLE mission_control_runtime")
            assert (
                await connection.fetchval(
                    "SELECT extensions.word_similarity('agent browser', 'agent-browser skill')"
                )
                > 0.3
            )
            assert await connection.fetchval(
                "SELECT '[1,0,0]'::extensions.vector OPERATOR(extensions.<=>) "
                "'[0,1,0]'::extensions.vector"
            ) == pytest.approx(1.0)
        assert (await verify_release(target, successor, **VERSIONS))["status"] == "verified"
        assert (await install(target, successor))["applied_migrations"] == []
        await assert_runtime_security(connection, target)
