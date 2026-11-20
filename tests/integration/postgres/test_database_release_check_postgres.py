"""The restricted runtime login reads the release of its bound database (VER-S1).

The disposable database holds the Mission Control component alone, as the local stack does; the
`api` schema and `api.database_release()` are added here the way the database contract ships
them (the function is not PUBLIC's, the schema is not the runtime role's until granted).
"""

from __future__ import annotations

import json

import asyncpg
import pytest

from mission_control.application.installations.registry import (
    ApplicationBinding,
    InstallationUnavailable,
)
from mission_control.bootstrap.common_installation import (
    DatabaseReleaseCheck,
    inspect_common_installation,
)
from mission_control.contracts.database_release import DatabaseReleaseDeclaration
from tests.support.db import COMPONENT_VERSION, CommonDatabase, common_database

pytestmark = pytest.mark.common_db

FORMAT = "ai-engineer-database-release/1"
DECLARED = DatabaseReleaseDeclaration(format=FORMAT, range="0.12.0")
ENFORCE = DatabaseReleaseCheck(DECLARED, "enforce")
WARN = DatabaseReleaseCheck(DECLARED, "warn")


def _binding(database: CommonDatabase) -> ApplicationBinding:
    return ApplicationBinding.seal(
        application_id=database.application_id,
        installation_id=database.installation_id,
        binding_version="1",
        supabase_project_ref=database.project_ref,
        database_secret_ref="MC_BOOTSTRAP_TEST_DSN",
        accepted_issuers={"https://issuer.invalid"},
        accepted_audiences={"authenticated"},
        required_component_version=COMPONENT_VERSION,
    )


async def _state_release(owner: asyncpg.Pool, release: str | None, state: str) -> None:
    answer = json.dumps({"format": FORMAT, "release": release, "state": state})
    async with owner.acquire() as connection:
        await connection.execute(
            "CREATE OR REPLACE FUNCTION api.database_release() RETURNS jsonb "
            f"LANGUAGE sql STABLE AS $release$ SELECT '{answer}'::jsonb $release$"
        )
        await connection.execute("REVOKE ALL ON FUNCTION api.database_release() FROM PUBLIC")


@pytest.mark.asyncio
async def test_the_runtime_login_checks_the_release_of_its_bound_database() -> None:
    async with common_database() as database:
        binding = _binding(database)
        runtime = await database.pool("mission_control_runtime")
        owner = await database.owner_pool()
        try:
            # No declaration: the component check alone, as before.
            undeclared = await inspect_common_installation(runtime, binding)
            assert undeclared.database_release.verdict == "not_declared"

            # The Mission Control component alone in its database: nothing to check.
            alone = await inspect_common_installation(runtime, binding, database_release=ENFORCE)
            assert alone.database_release.verdict == "not_applicable"
            assert alone.database_release.declared_range == "0.12.0"

            # The contract's schema without the function: no answer.
            async with owner.acquire() as connection:
                await connection.execute("CREATE SCHEMA api")
            with pytest.raises(InstallationUnavailable, match="no api.database_release"):
                await inspect_common_installation(runtime, binding, database_release=ENFORCE)
            warned = await inspect_common_installation(runtime, binding, database_release=WARN)
            assert warned.database_release.verdict == "unknown"

            # The function exists, and the runtime role may not reach it yet.
            await _state_release(owner, "0.12.0", "current")
            with pytest.raises(InstallationUnavailable, match="may not call api.database_release"):
                await inspect_common_installation(runtime, binding, database_release=ENFORCE)
            async with owner.acquire() as connection:
                await connection.execute("GRANT USAGE ON SCHEMA api TO mission_control_runtime")
            with pytest.raises(InstallationUnavailable, match="may not call api.database_release"):
                await inspect_common_installation(runtime, binding, database_release=ENFORCE)
            async with owner.acquire() as connection:
                await connection.execute(
                    "GRANT EXECUTE ON FUNCTION api.database_release() TO mission_control_runtime"
                )

            # The declared release, as stamped.
            current = await inspect_common_installation(runtime, binding, database_release=ENFORCE)
            assert current.database_release.report() == {
                "declared_range": "0.12.0",
                "release": "0.12.0",
                "state": "current",
                "verdict": "ok",
                "mode": "enforce",
            }

            # Unreleased migrations on top: starts, with a warning. (Replacing a function keeps
            # its grants.)
            await _state_release(owner, "0.12.0", "ahead")
            ahead = await inspect_common_installation(runtime, binding, database_release=ENFORCE)
            assert (ahead.database_release.verdict, ahead.database_release.warning) == ("ok", True)

            # Another release: refused in enforce mode, reported in warn mode.
            await _state_release(owner, "0.11.0", "current")
            with pytest.raises(InstallationUnavailable, match="database release is incompatible"):
                await inspect_common_installation(runtime, binding, database_release=ENFORCE)
            other = await inspect_common_installation(runtime, binding, database_release=WARN)
            assert other.database_release.report() == {
                "declared_range": "0.12.0",
                "release": "0.11.0",
                "state": "current",
                "verdict": "incompatible",
                "mode": "warn",
            }
        finally:
            await runtime.close()
            await owner.close()
