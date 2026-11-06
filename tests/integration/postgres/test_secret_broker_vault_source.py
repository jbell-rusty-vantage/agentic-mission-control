"""MO-11 on a disposable PostgreSQL 17: the composed Secret Broker reads Supabase Vault.

`compose_secret_broker` with `MISSION_CONTROL_SECRET_STORE=supabase_vault` opens its own pool on
the configured DSN and reads `vault.decrypted_secrets` by secret name. The disposable database
stands in for Supabase with a `vault.decrypted_secrets` view of the documented shape (`name`,
`decrypted_secret`; FIXTURE: real Vault decrypts through its extension, which local PostgreSQL
lacks). A role the view is not granted to is refused without its value, and a provider-held
path is never read. No live Supabase project is touched.
"""

from __future__ import annotations

from contextlib import AsyncExitStack

import asyncpg
import pytest
from pydantic import SecretStr

from mission_control.adapters.temporal.deployment_composition import compose_secret_broker
from mission_control.application.secrets.broker import SecretUnavailable
from mission_control.application.secrets.references import declarations
from mission_control.domain.authoring.contracts import SecretRef
from tests.fixtures.isolated_settings import isolated_settings
from tests.qualification.two_project.disposable import (
    create_database,
    database_dsn,
    drop_database,
    new_suffix,
    require_admin_dsn,
)

pytestmark = pytest.mark.common_db

VAULT_VALUE = "mo11-vault-sentinel-6b0e"
HELD_VALUE = "mo11-held-never-read-1a7c"


async def _vault_database(server: str, suffix: str) -> tuple[str, str, str]:
    """A database with the Vault view, its reader role and a role without the grant."""

    name = await create_database(server, suffix)
    reader, outsider = f"mcqd_{suffix}_reader", f"mcqd_{suffix}_outsider"
    owner = await asyncpg.connect(database_dsn(server, name))
    try:
        await owner.execute(
            f"""
            CREATE SCHEMA vault;
            CREATE TABLE vault.secrets (name text PRIMARY KEY, secret text NOT NULL);
            CREATE VIEW vault.decrypted_secrets AS
                SELECT name, secret AS decrypted_secret FROM vault.secrets;
            INSERT INTO vault.secrets VALUES
                ('firecrawl/api_key', '{VAULT_VALUE}'), ('cursor/team_key', '{HELD_VALUE}');
            CREATE ROLE "{reader}" LOGIN PASSWORD 'reader-pass';
            CREATE ROLE "{outsider}" LOGIN PASSWORD 'outsider-pass';
            GRANT USAGE ON SCHEMA vault TO "{reader}", "{outsider}";
            GRANT SELECT ON vault.decrypted_secrets TO "{reader}";
            """
        )
    finally:
        await owner.close()
    return name, reader, outsider


def _login(server: str, database: str, role: str, password: str) -> str:
    dsn = database_dsn(server, database)
    scheme, rest = dsn.split("://", 1)
    return f"{scheme}://{role}:{password}@{rest.rsplit('@', 1)[-1]}"


async def test_the_composed_broker_reads_supabase_vault_by_secret_name() -> None:
    server = require_admin_dsn()
    suffix = new_suffix()
    name, reader, outsider = await _vault_database(server, suffix)
    try:
        async with AsyncExitStack() as resources:
            broker = await compose_secret_broker(
                isolated_settings(
                    mission_control_secret_store="supabase_vault",
                    mission_control_secret_vault_dsn=SecretStr(
                        _login(server, name, reader, "reader-pass")
                    ),
                    mission_control_provider_held_secrets=("cursor/team_key",),
                ),
                resources,
            )
            assert await broker.resolve(
                (SecretRef(provider="vault", key="firecrawl/api_key"),)
            ) == {"vault:firecrawl/api_key": VAULT_VALUE}
            resolved = await broker.resolve_declarations(
                declarations(
                    (
                        "FIRECRAWL_API_KEY=secret:firecrawl/api_key",
                        "CURSOR_TEAM_KEY=secret:cursor/team_key",
                    )
                )
            )
            assert dict(resolved.values) == {"FIRECRAWL_API_KEY": VAULT_VALUE}
            assert resolved.held == ("CURSOR_TEAM_KEY",)
            assert HELD_VALUE not in broker.registry.values()
            with pytest.raises(SecretUnavailable, match="no value"):
                await broker.resolve((SecretRef(provider="vault", key="absent/key"),))

        async with AsyncExitStack() as resources:
            refused = await compose_secret_broker(
                isolated_settings(
                    mission_control_secret_store="supabase_vault",
                    mission_control_secret_vault_dsn=SecretStr(
                        _login(server, name, outsider, "outsider-pass")
                    ),
                ),
                resources,
            )
            with pytest.raises(SecretUnavailable, match="refused the read") as denied:
                await refused.resolve((SecretRef(provider="vault", key="firecrawl/api_key"),))
            assert VAULT_VALUE not in str(denied.value)
    finally:
        await drop_database(server, name, (reader, outsider))
