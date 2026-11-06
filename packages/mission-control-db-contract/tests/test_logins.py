"""Restricted LOGIN roles (``mission-db login-plan`` / ``login-apply``) on a Supabase-like target.

Container B installs as a NON-superuser CREATEROLE migration principal, like Supabase's
``postgres``: the logins, their memberships and password rotation must all work without
superuser. Every DSN goes only to the owner-only env file; nothing returned carries a password.
"""

from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from conftest import VERSIONS, admin_dsn, run, write_target
from test_install import install

from mission_control_db_contract.cli import build_parser
from mission_control_db_contract.deployment import verify_release
from mission_control_db_contract.errors import ContractError
from mission_control_db_contract.logins import (
    LOGINS,
    _validate_tls,
    assert_ignored,
    build_dsn,
    login_apply,
    login_plan,
    login_user,
    read_env_file,
    scram_verifier,
)
from mission_control_db_contract.runtime import load_descriptor, runtime_apply
from mission_control_db_contract.target import load_target


def _confirm(target: dict[str, str]) -> str:
    return f"{target['project_ref']}:{target['installation_id']}"


@pytest.fixture
def prefix() -> Any:
    value = "t" + secrets.token_hex(4)
    yield value
    dsn = admin_dsn("B")

    async def drop() -> None:
        connection = await asyncpg.connect(dsn)
        try:
            for spec in LOGINS:
                await connection.execute(f"DROP ROLE IF EXISTS {spec.role(value)}")
        finally:
            await connection.close()

    run(drop())


@pytest.fixture
def installed(make_db, release, tmp_path, monkeypatch):
    descriptor = load_descriptor(release.release_root.parent / "runtime" / "descriptor.json")
    db = make_db("B")
    target = load_target(write_target(tmp_path, db, monkeypatch=monkeypatch))
    install(target, release)
    return db, target, descriptor


def _runtime(target, release, descriptor, tmp_path: Path) -> None:
    run(
        runtime_apply(
            target,
            release,
            descriptor,
            confirmation=_confirm(target),
            receipt_path=tmp_path / "runtime.json",
            **VERSIONS,
        )
    )


def _apply(target, release, descriptor, out_env: Path, prefix: str, **overrides):
    return run(
        login_apply(
            target,
            release,
            descriptor,
            confirmation=overrides.pop("confirmation", _confirm(target)),
            out_env=out_env,
            sslmode="disable",
            prefix=prefix,
            require_ignored=False,
            **{**VERSIONS, **overrides},
        )
    )


async def _as_login(dsn: str, query: str, *args: Any) -> Any:
    connection = await asyncpg.connect(dsn)
    try:
        return await connection.fetchval(query, *args)
    finally:
        await connection.close()


def test_fresh_apply_repeat_and_rotate(installed, release, tmp_path, prefix):
    db, target, descriptor = installed
    _runtime(target, release, descriptor, tmp_path)
    plan = run(login_plan(target, release, descriptor, prefix=prefix, **VERSIONS))
    assert plan["status"] == "pending" and plan["holds"] == []
    assert [e["status"] for e in plan["logins"]] == ["absent"] * 3

    out_env = tmp_path / "secrets" / "logins.env"
    first = _apply(target, release, descriptor, out_env, prefix, probe=True)
    assert [e["action"] for e in first["logins"]] == ["created"] * 3 and first["changed"]
    values = read_env_file(out_env)
    assert set(values) == {"MC_RUNTIME_DSN", "MC_FAMILY_WRITER_DSN", "MC_CHECKPOINTER_DSN"}
    passwords = {name: dsn.split("@", 1)[0].rsplit(":", 1)[1] for name, dsn in values.items()}
    rendered = json.dumps(first)
    assert not any(password in rendered for password in passwords.values())
    assert all(p["member"] and not p["can_set_role"] for p in first["probes"])

    # Each login holds exactly its capability, INHERIT TRUE / SET FALSE / no ADMIN, no privilege.
    for spec in LOGINS:
        role = spec.role(prefix)
        row = run(
            db.fetchval(
                "SELECT row_to_json(x)::text FROM (SELECT r.rolcanlogin, r.rolsuper, "
                "r.rolbypassrls, r.rolcreatedb, r.rolcreaterole, r.rolreplication, ARRAY("
                "SELECT g.rolname || ':' || m.admin_option || ':' || m.inherit_option || ':' "
                "|| m.set_option FROM pg_auth_members m JOIN pg_roles g ON g.oid = m.roleid "
                "WHERE m.member = r.oid) AS m FROM pg_roles r WHERE r.rolname = $1) x",
                role,
            )
        )
        assert json.loads(row) == {
            "rolcanlogin": True,
            "rolsuper": False,
            "rolbypassrls": False,
            "rolcreatedb": False,
            "rolcreaterole": False,
            "rolreplication": False,
            "m": [f"{spec.capability}:false:true:false"],
        }
        assert run(
            db.fetchval(
                "SELECT rolpassword LIKE 'SCRAM-SHA-256$%' FROM pg_authid WHERE rolname = $1", role
            )
        )
    # The pools' own identity rule holds through the generated DSNs (no SET ROLE needed).
    capabilities = [spec.capability for spec in LOGINS]
    for spec in LOGINS:
        held = run(
            _as_login(
                values[spec.dsn_name],
                "SELECT array_agg(rolname ORDER BY rolname) FROM pg_roles "
                "WHERE rolname = ANY($1::text[]) AND pg_has_role(current_user, oid, 'MEMBER')",
                capabilities + ["mission_control_outbox_worker", "mission_control_readonly"],
            )
        )
        assert held == [spec.capability]
    assert run(
        _as_login(
            values["MC_RUNTIME_DSN"],
            "SELECT has_table_privilege('mission_control.mission', 'SELECT')",
        )
    )

    # The common release still verifies: logins are not capability roles and change no grant.
    assert run(verify_release(target, release, **VERSIONS))["status"] == "verified"

    # Repeat: verified, unchanged bytes; the plan reports complete.
    before = out_env.read_bytes()
    again = _apply(target, release, descriptor, out_env, prefix)
    assert [e["action"] for e in again["logins"]] == ["verified"] * 3 and not again["changed"]
    assert out_env.read_bytes() == before
    complete = run(login_plan(target, release, descriptor, prefix=prefix, **VERSIONS))
    assert complete["status"] == "complete" and complete["mutations"] == []

    # Rotate: new passwords that authenticate; the old ones no longer do.
    rotated = _apply(target, release, descriptor, out_env, prefix, rotate=True, probe=True)
    assert [e["action"] for e in rotated["logins"]] == ["rotated"] * 3
    new_values = read_env_file(out_env)
    assert all(new_values[n] != values[n] for n in values)
    with pytest.raises(asyncpg.InvalidPasswordError):
        run(_as_login(values["MC_RUNTIME_DSN"], "SELECT 1"))


def test_other_env_names_are_preserved_and_lost_secret_refuses(
    installed, release, tmp_path, prefix
):
    _db, target, descriptor = installed
    _runtime(target, release, descriptor, tmp_path)
    out_env = tmp_path / "logins.env"
    out_env.write_text("BKS_VERIFICATION_DSN='postgresql://kept'\n", encoding="utf-8")
    _apply(target, release, descriptor, out_env, prefix)
    assert read_env_file(out_env)["BKS_VERIFICATION_DSN"] == "postgresql://kept"
    with pytest.raises(ContractError) as refused:
        _apply(target, release, descriptor, tmp_path / "other.env", prefix)
    assert refused.value.code == "LOGIN_SECRET_UNKNOWN"


def test_checkpointer_needs_runtime_apply_and_drift_holds(installed, release, tmp_path, prefix):
    db, target, descriptor = installed
    plan = run(login_plan(target, release, descriptor, prefix=prefix, **VERSIONS))
    assert plan["status"] == "hold"
    assert any("runtime-apply" in hold for hold in plan["holds"])
    with pytest.raises(ContractError) as refused:
        _apply(target, release, descriptor, tmp_path / "a.env", prefix)
    assert refused.value.code == "LOGIN_HOLD"
    assert not (tmp_path / "a.env").exists()

    _runtime(target, release, descriptor, tmp_path)
    runtime_login = LOGINS[0].role(prefix)
    run(db.execute(f"CREATE ROLE {runtime_login} LOGIN"))
    run(db.execute(f"GRANT mission_control_runtime, mission_control_readonly TO {runtime_login}"))
    drifted = run(login_plan(target, release, descriptor, prefix=prefix, **VERSIONS))
    assert drifted["status"] == "hold"
    assert drifted["logins"][0]["status"] == "drift"
    with pytest.raises(ContractError) as refused:
        _apply(target, release, descriptor, tmp_path / "b.env", prefix, rotate=True)
    assert refused.value.code == "LOGIN_HOLD"


def test_confirmation_mismatch_refuses(installed, release, tmp_path, prefix):
    _db, target, descriptor = installed
    with pytest.raises(ContractError):
        _apply(target, release, descriptor, tmp_path / "c.env", prefix, confirmation="x:y")


# ---------------------------------------------------------------------------------- pure


POOLER = {
    "project_ref": "wkythqbofmckbuoothhn",
    "database_host": "aws-1-us-east-1.pooler.supabase.com",
    "database_port": "5432",
    "database_name": "postgres",
    "database_user": "postgres.wkythqbofmckbuoothhn",
    "database_session_user": "postgres",
}
DIRECT = {
    "project_ref": "bxnetwiimwhtlrjlbtab",
    "database_host": "db.bxnetwiimwhtlrjlbtab.supabase.co",
    "database_port": "5432",
    "database_name": "postgres",
    "database_user": "postgres",
    "database_session_user": "postgres",
}


def test_dsn_user_follows_the_route(tmp_path):
    ca = tmp_path / "ca.crt"
    ca.write_text("-----BEGIN CERTIFICATE-----\nx\n-----END CERTIFICATE-----\n", encoding="utf-8")
    assert login_user(POOLER, "mcl_runtime") == "mcl_runtime.wkythqbofmckbuoothhn"
    assert login_user(DIRECT, "mcl_runtime") == "mcl_runtime"
    user = "mcl_runtime.wkythqbofmckbuoothhn"
    dsn = build_dsn(POOLER, user, "pw", sslmode="verify-full", ca_file=ca)
    assert dsn.startswith(
        "postgresql://mcl_runtime.wkythqbofmckbuoothhn:pw@aws-1-us-east-1.pooler.supabase.com:5432/"
        "postgres?sslmode=verify-full&sslrootcert="
    )
    assert dsn.endswith(ca.resolve().as_posix())
    with pytest.raises(ContractError) as refused:
        _validate_tls(DIRECT, "disable", None)
    assert refused.value.code == "TLS_REQUIRED"
    with pytest.raises(ContractError) as refused:
        _validate_tls(DIRECT, "verify-full", tmp_path / "missing.crt")
    assert refused.value.code == "CA_FILE_MISSING"
    _validate_tls(DIRECT, "verify-full", ca)


def test_scram_verifier_shape_and_out_env_guard(tmp_path):
    verifier = scram_verifier("secret", salt=b"0" * 16)
    assert verifier.startswith("SCRAM-SHA-256$4096:") and "secret" not in verifier
    assert verifier == scram_verifier("secret", salt=b"0" * 16)
    with pytest.raises(ContractError) as refused:
        assert_ignored(tmp_path / "x.env")
    assert refused.value.code == "OUTPUT_NOT_IN_REPOSITORY"
    tracked = Path(__file__).resolve().parent / "conftest.py"
    with pytest.raises(ContractError) as refused:
        assert_ignored(tracked)
    assert refused.value.code == "OUTPUT_TRACKED"


def test_cli_parses_login_commands():
    args = build_parser().parse_args(
        [
            "login-apply",
            "--deployment-dir",
            "deployments/biotech",
            "--reader-version",
            "r",
            "--writer-version",
            "w",
            "--descriptor",
            "d.json",
            "--confirm-target",
            "a:b",
            "--out-env",
            ".scratch/x.env",
            "--ca-file",
            "ca.crt",
            "--probe",
        ]
    )
    assert args.command == "login-apply" and args.probe and not args.rotate
    assert args.sslmode == "verify-full" and args.login_prefix == "mcl"


def test_a_failed_rotation_keeps_the_working_file_and_capability_drift_holds(
    installed, release, tmp_path, prefix, monkeypatch
):
    """Review S1/S4: the out-env is replaced only after the DDL commits; a capability role that
    is itself a member of another role holds the plan."""

    from mission_control_db_contract import logins

    db, target, descriptor = installed
    _runtime(target, release, descriptor, tmp_path)
    out_env = tmp_path / "logins.env"
    _apply(target, release, descriptor, out_env, prefix)
    before = out_env.read_bytes()

    def broken(_password: str, **_kwargs: object) -> str:
        raise RuntimeError("crash inside the DDL transaction")

    original = logins.scram_verifier
    monkeypatch.setattr(logins, "scram_verifier", broken)
    with pytest.raises(ContractError):
        _apply(target, release, descriptor, out_env, prefix, rotate=True)
    assert out_env.read_bytes() == before
    assert not logins._pending(out_env).exists()
    monkeypatch.setattr(logins, "scram_verifier", original)
    # The kept credentials still authenticate (a verify-only rerun probes them).
    again = _apply(target, release, descriptor, out_env, prefix)
    assert again["changed"] is False and len(again["probes"]) == 3

    run(db.execute(f"CREATE ROLE {prefix}_extra NOLOGIN"))
    run(db.execute(f"GRANT {prefix}_extra TO mission_control_runtime"))
    plan = run(login_plan(target, release, descriptor, prefix=prefix, **VERSIONS))
    assert plan["status"] == "hold"
    assert any("itself a member" in hold for hold in plan["holds"])
    run(db.execute(f"DROP ROLE {prefix}_extra"))


def test_the_transaction_pooler_port_is_refused(installed, release, tmp_path, prefix):
    _db, target, descriptor = installed
    with pytest.raises(ContractError) as refused:
        _apply(target | {"database_port": "6543"}, release, descriptor, tmp_path / "x.env", prefix)
    assert refused.value.code == "SESSION_CONNECTION_REQUIRED"


def test_a_crash_after_the_commit_keeps_the_pending_credentials(
    installed, release, tmp_path, prefix, monkeypatch
):
    """Review N1: after the DDL commits, the pending file holds the only new credentials; it
    is never removed, and the next run adopts it once its credentials authenticate."""

    from mission_control_db_contract import logins

    _db, target, descriptor = installed
    _runtime(target, release, descriptor, tmp_path)
    out_env = tmp_path / "logins.env"
    _apply(target, release, descriptor, out_env, prefix)
    original = logins._replace

    def crash(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("crash after the commit, before the replace")

    monkeypatch.setattr(logins, "_replace", crash)
    with pytest.raises(ContractError):
        _apply(target, release, descriptor, out_env, prefix, rotate=True)
    pending = logins._pending(out_env)
    assert pending.exists()
    monkeypatch.setattr(logins, "_replace", original)
    adopted = _apply(target, release, descriptor, out_env, prefix)
    assert adopted["changed"] is False and len(adopted["probes"]) == 3
    assert not pending.exists()
