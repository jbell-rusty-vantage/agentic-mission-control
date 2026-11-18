"""1.16.0: the capability search source-set digest sorts in byte order (0075, MC-F 2026-11-16).

`activate_generation` (0022) sorted the text keys of its digest under the database's default
collation; the application's expected digest is in codepoint order. On an `en_US.utf8` database
(the compose server, CI and Supabase) the seeded ids `mcp.github.tool.list-issue-fields`,
`...list-issues` and `...list-issue-types` sort differently and no generation could activate.

The release proof installs 1.16.0 fresh and upgrades 1.15.0 with the real installer (exactly 0075
pending, earlier receipts kept, verify, replay). The activation proof runs on databases created
with `LC_COLLATE 'en_US.utf8'`: 1.16.0 activates a generation holding those three ids with the
application's digest, and the same rows on 1.15.0 are refused, so the test would have caught it.
"""

from __future__ import annotations

from pathlib import Path

import asyncpg
import pytest

from mission_control.adapters.postgres.capability.capability_search_generation_repository import (
    PostgresProjectionGenerationRepository,
)
from mission_control.adapters.postgres.capability.capability_search_repository import (
    PostgresCatalogSearchRepository,
)
from mission_control.adapters.postgres.control_plane.definition_repository import (
    PostgresDefinitionRepository,
)
from mission_control_db_contract.deployment import plan_release, verify_release
from tests.fixtures.mission_control_common_db import (
    COMPONENT_ROOT,
    catalog_scope,
    common_database,
)
from tests.support.integration.postgres.capability_search_projection_postgres import (
    NOW,
    document,
    spec,
    tool,
)
from tests.support.integration.postgres.run2_release_141 import (
    PACKAGE,
    VERSIONS,
    disposable,
    install,
    release_at,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.common_db]
NEW = ["0075_capability_search_byte_order_digest"]
RELEASE_1150 = PACKAGE / "releases/1.15.0/component"
RELEASE_1160 = PACKAGE / "releases/1.16.0/component"
LOCALE = "en_US.utf8"
GITHUB_IDS = (
    "mcp.github.tool.list-issue-fields",
    "mcp.github.tool.list-issues",
    "mcp.github.tool.list-issue-types",
)
CATALOG = catalog_scope("biotech")


@pytest.mark.parametrize("upgrade", [False, True], ids=["fresh", "upgrade-from-1150"])
async def test_release_1160_replaces_the_activation_digest_additively(
    tmp_path: Path, upgrade: bool
) -> None:
    successor = release_at(RELEASE_1160, tmp_path / "new", "ai-engineer")
    async with disposable(tmp_path, "ai-engineer") as (target, connection):
        receipts = []
        if upgrade:
            await install(target, release_at(RELEASE_1150, tmp_path / "old", "ai-engineer"))
            receipts = await connection.fetch("SELECT * FROM mission_control.component_release")
            plan = await plan_release(target, successor, **VERSIONS)
            assert plan["plan"]["pending_migrations"] == NEW
        await install(target, successor)
        for row in receipts:
            assert (
                await connection.fetchrow(
                    "SELECT * FROM mission_control.component_release WHERE migration_key=$1",
                    row["migration_key"],
                )
                == row
            )
        definition = await connection.fetchval(
            "SELECT pg_get_functiondef('mission_control_search.activate_generation"
            "(text,text,integer,text)'::regprocedure)"
        )
        assert 'd.logical_id COLLATE "C"' in definition
        signature = "mission_control_search.activate_generation(text,text,integer,text)"
        for role, allowed in (
            ("mission_control_runtime", True),
            ("mission_control_catalog_writer", True),
            ("mission_control_outbox_worker", True),
            ("mission_control_readonly", False),
        ):
            assert (
                await connection.fetchval(
                    "SELECT has_function_privilege($1, $2, 'EXECUTE')", role, signature
                )
                is allowed
            ), role
        assert (await verify_release(target, successor, **VERSIONS))["status"] == "verified"
        assert (await install(target, successor))["applied_migrations"] == []


@pytest.mark.parametrize("release", ["newest", "1.15.0"])
async def test_a_locale_database_activates_ids_whose_locale_and_byte_order_differ(
    release: str,
) -> None:
    if release == "newest":
        assert (COMPONENT_ROOT / "migrations" / f"{NEW[0]}.sql").is_file()
        options: dict[str, object] = {}
    else:
        options = {
            "paths": sorted((RELEASE_1150 / "migrations").glob("[0-9][0-9][0-9][0-9]_*.sql")),
            "component_version": "1.15.0",
        }
    async with common_database(locale=LOCALE, **options) as database:
        owner = await asyncpg.connect(database.owner_dsn)
        try:
            collation = await owner.fetchval(
                "SELECT datcollate FROM pg_database WHERE datname = current_database()"
            )
            locale_order = await owner.fetchval(
                "SELECT array_agg(x ORDER BY x) FROM unnest($1::text[]) AS x", list(GITHUB_IDS)
            )
            byte_order = await owner.fetchval(
                'SELECT array_agg(x ORDER BY x COLLATE "C") FROM unnest($1::text[]) AS x',
                list(GITHUB_IDS),
            )
        finally:
            await owner.close()
        assert collation == LOCALE
        assert list(byte_order) == sorted(GITHUB_IDS)  # Python codepoint order
        assert list(locale_order) != list(byte_order)  # the ordering the old function used

        runtime = await database.pool("mission_control_runtime")
        writer_pool = await database.pool("mission_control_catalog_writer")
        try:
            catalog = PostgresDefinitionRepository(runtime, catalog_scope=CATALOG)
            published = tuple(
                [
                    await catalog.publish(tool(item, f"GitHub {item}"), "p", NOW, 0)
                    for item in GITHUB_IDS
                ]
            )
            generations = PostgresProjectionGenerationRepository(writer_pool, catalog_scope=CATALOG)
            writer = PostgresCatalogSearchRepository(writer_pool, catalog_scope=CATALOG)
            expected = spec("global", "generation-locale", published)
            await generations.begin(expected, created_at=NOW)
            for axis, item in enumerate(published):
                assert await writer.upsert(document(item, "global", "generation-locale", axis))
            rows = await writer.list_generation("global", "generation-locale")
            assert [row.logical_id for row in rows] == sorted(GITHUB_IDS)
            if release == "1.15.0":
                with pytest.raises(asyncpg.RaiseError, match="source digest verification failed"):
                    await generations.activate(expected, activated_at=NOW)
                return
            activation = await generations.activate(expected, activated_at=NOW)
            assert activation.activated_count == len(GITHUB_IDS)
            assert activation.activated_source_set_digest == expected.expected_source_set_digest
            record = await generations.get("global", "generation-locale")
            assert record is not None and record.state == "active"
        finally:
            await writer_pool.close()
            await runtime.close()
