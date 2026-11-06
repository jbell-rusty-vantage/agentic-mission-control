"""Migration 0035 under a NON-superuser migration principal (cluster B, Supabase-like).

The ingress tables keep FORCE ROW LEVEL SECURITY, which binds their owner too. The SECURITY
DEFINER functions run as that owner: they must resolve a credential before they know its
tenant and then write under the tenant's scope, while a login that is only a member of
`mission_control_ingress` reaches nothing but the functions.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import uuid

import asyncpg
import pytest
from conftest import run, with_db, write_target
from test_install import install

from mission_control_db_contract.target import load_target

TOKEN = "mct_" + "q" * 43
DIGEST = "sha256:" + hashlib.sha256(TOKEN.encode()).hexdigest()
BODY = "sha256:" + "0" * 64


async def _seed(installer: str, installation: str, tenant: uuid.UUID) -> None:
    connection = await asyncpg.connect(installer)
    try:
        async with connection.transaction():
            await connection.execute(
                "SELECT set_config('mc.installation_id', $1, true), "
                "set_config('mc.application_id', 'biotech', true), "
                "set_config('mc.tenant_id', $2, true)",
                installation,
                str(tenant),
            )
            await connection.execute(
                "INSERT INTO mission_control.tenant (installation_id, application_id, tenant_id, "
                "external_tenant_ref, state, qualification_fixture, created_at, "
                "created_by_actor_ref) VALUES ($1, 'biotech', $2, 'test:ingress', 'active', true, "
                "now(), 'fixture:ingress')",
                uuid.UUID(installation),
                tenant,
            )
            await connection.execute(
                "INSERT INTO mission_control.ingress_credential (installation_id, "
                "application_id, tenant_id, credential_id, purpose, credential_hash, scopes, "
                "context, rate_limit, rate_window_started_at, rate_window_count, issued_at, "
                "expires_at, created_by_actor_ref) VALUES ($1, 'biotech', $2, $3, "
                "'mission_request', $4, ARRAY['mission:request'], '{}'::jsonb, 10, now(), 0, "
                "now(), now() + interval '1 hour', 'fixture:ingress')",
                uuid.UUID(installation),
                tenant,
                uuid.uuid4(),
                DIGEST,
            )
    finally:
        await connection.close()


async def _calls(dsn: str, installation: str) -> dict[str, object]:
    connection = await asyncpg.connect(dsn, statement_cache_size=0)
    try:
        identity = uuid.UUID(installation)
        request = await connection.fetchrow(
            "SELECT * FROM mission_control.ingress_mission_request($1, 'biotech', $2, $3, "
            "'launch-1', 'mission:report@1', $4, $5::jsonb)",
            identity,
            DIGEST,
            uuid.uuid4(),
            BODY,
            json.dumps({"manifest_ref": "mission:report@1"}),
        )
        status = await connection.fetchrow(
            "SELECT * FROM mission_control.ingress_mission_request_status($1, 'biotech', $2, $3)",
            identity,
            DIGEST,
            request["request_id"],
        )
        webhook = await connection.fetchval(
            "SELECT mission_control.ingress_webhook($1, 'biotech', 'github', NULL, $2, 'gh-1', "
            "$3, '{}'::jsonb)",
            identity,
            uuid.uuid4(),
            BODY,
        )
        unknown = await connection.fetchval(
            "SELECT outcome FROM mission_control.ingress_accept($1, 'biotech', 'run_token', $2, "
            "NULL, NULL, NULL, $3::jsonb)",
            identity,
            "sha256:" + "1" * 64,
            json.dumps(
                [
                    {
                        "ingress_id": str(uuid.uuid4()),
                        "kind": "signal.milestone",
                        "dedupe_key": "s-1",
                        "body_sha256": BODY,
                        "payload": {},
                    }
                ]
            ),
        )
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await connection.fetch("SELECT * FROM mission_control.ingress_inbox")
        return {
            "request": request["outcome"],
            "status": (status["outcome"], status["state"]),
            "webhook": webhook,
            "unknown": unknown,
        }
    finally:
        await connection.close()


async def _visible_without_scope(installer: str) -> int:
    connection = await asyncpg.connect(installer)
    try:
        return int(await connection.fetchval("SELECT count(*) FROM mission_control.ingress_inbox"))
    finally:
        await connection.close()


def test_definer_functions_work_under_forced_rls_for_a_non_superuser_owner(
    make_db, release, tmp_path, monkeypatch
):
    db = make_db("B")
    target = load_target(write_target(tmp_path, db, monkeypatch=monkeypatch))
    install(target, release)
    installation = target["installation_id"]
    run(_seed(db.installer, installation, uuid.uuid4()))

    login, password = f"mcdb_t_ingress_{secrets.token_hex(4)}", secrets.token_hex(12)
    run(
        db.execute(
            f"CREATE ROLE {login} LOGIN NOSUPERUSER NOBYPASSRLS INHERIT PASSWORD '{password}' "
            "IN ROLE mission_control_ingress"
        )
    )
    try:
        run(db.execute(f"GRANT CONNECT ON DATABASE {db.name} TO {login}"))
        outcomes = run(_calls(with_db(db.admin, db.name, login, password), installation))
        assert outcomes == {
            "request": "accepted",
            "status": ("found", "queued"),
            "webhook": "accepted",
            "unknown": "unknown",
        }
        # The owner itself still sees nothing without a scope: RLS stays forced.
        assert run(_visible_without_scope(db.installer)) == 0
        assert run(db.fetchval("SELECT count(*) FROM mission_control.ingress_inbox")) == 2
    finally:
        run(db.execute(f"REVOKE CONNECT ON DATABASE {db.name} FROM {login}"))
        run(db.execute(f"DROP ROLE {login}"))
