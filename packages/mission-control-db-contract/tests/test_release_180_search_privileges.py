"""Release 1.8.0 on a Supabase-like cluster B (Sprint OC W1 defect D7, upgrade path from 1.7.0).

Cluster B installs as the NON-superuser CREATEROLE migration principal and keeps `vector` and
`pg_trgm` in a schema `extensions` it does not own, as on Supabase. A restricted login that is a
member of `mission_control_runtime` only (the `mcl_*` shape of `login-apply`) cannot name the
extension objects capability search uses on 1.7.0; the additive 1.8.0 upgrade applies exactly
0061, 0063 and 0064, after which it can, and a repeat changes nothing. When the installing login
holds USAGE on `extensions` without GRANT OPTION, 0064's guard refuses the whole apply.
"""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from conftest import (
    PACKAGE,
    VERSIONS,
    admin_dsn,
    build_and_lock,
    copy_component,
    run,
    with_db,
    write_target,
)
from test_install import install

from mission_control_db_contract.deployment import apply_release, plan_release, verify_release
from mission_control_db_contract.errors import ContractError
from mission_control_db_contract.integrity import Release
from mission_control_db_contract.target import load_target

NEW = [
    "0061_durable_transition_reactions",
    "0063_coordinator_delivery_observations",
    "0064_search_extension_privileges",
]
SEARCH_ROLES = (
    "mission_control_runtime",
    "mission_control_catalog_writer",
    "mission_control_outbox_worker",
)
WORD_SIMILARITY = "SELECT extensions.word_similarity('agent browser', 'agent-browser skill')"
COSINE = "SELECT '[1,0,0]'::extensions.vector OPERATOR(extensions.<=>) '[0,1,0]'::extensions.vector"


@pytest.fixture(scope="module")
def releases(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Release]:
    """1.7.0 and 1.8.0 rebuilt from their committed inputs on disposable cluster A."""

    built = {}
    for version in ("1.7.0", "1.8.0"):
        work = tmp_path_factory.mktemp("release-" + version.replace(".", ""))
        root = copy_component(work, source=PACKAGE / "releases" / version / "component")
        built[version] = build_and_lock(work, root, "biotech")
    return built


@pytest.fixture
def login() -> Any:
    """A restricted login, member of mission_control_runtime only (INHERIT TRUE, SET FALSE)."""

    name = "t" + secrets.token_hex(4) + "_runtime"
    password = secrets.token_urlsafe(16)
    yield name, password

    async def drop() -> None:
        connection = await asyncpg.connect(admin_dsn("B"))
        try:
            await connection.execute(f"DROP ROLE IF EXISTS {name}")
        finally:
            await connection.close()

    run(drop())


async def _admin(db: Any, query: str) -> Any:
    connection = await db.connect()
    try:
        return await connection.fetchval(query)
    finally:
        await connection.close()


async def _create_login(db: Any, name: str, password: str) -> None:
    connection = await db.connect()
    try:
        await connection.execute(
            f"CREATE ROLE {name} LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE "
            f"PASSWORD '{password}'"
        )
        await connection.execute(
            f"GRANT mission_control_runtime TO {name} WITH INHERIT TRUE, SET FALSE"
        )
    finally:
        await connection.close()


async def _as_login(db: Any, name: str, password: str, query: str) -> Any:
    connection = await asyncpg.connect(with_db(db.admin, db.name, name, password))
    try:
        return await connection.fetchval(query)
    finally:
        await connection.close()


def _plan(target: dict[str, str], release: Release) -> dict[str, Any]:
    return run(plan_release(target, release, **VERSIONS))


def test_upgrade_from_170_grants_search_privileges_on_a_supabase_like_cluster(
    make_db, releases, login, tmp_path, monkeypatch
):
    db = make_db("B")
    # The schema owner (the platform) lets the installing login pass USAGE on.
    run(_admin(db, "GRANT USAGE ON SCHEMA extensions TO mcdb_migrator WITH GRANT OPTION"))
    target = load_target(write_target(tmp_path, db, monkeypatch=monkeypatch))
    install(target, releases["1.7.0"])
    name, password = login
    run(_create_login(db, name, password))
    for query in (WORD_SIMILARITY, COSINE):
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            run(_as_login(db, name, password, query))  # W1 D7 reproduced on 1.7.0

    plan = _plan(target, releases["1.8.0"])
    assert plan["plan"]["holds"] == []
    assert plan["plan"]["pending_migrations"] == NEW
    result = run(
        apply_release(
            target,
            releases["1.8.0"],
            confirmation=f"{target['project_ref']}:{target['installation_id']}",
            expected_plan_digest=plan["plan_digest"],
            **VERSIONS,
        )
    )
    assert result["applied_migrations"] == NEW
    assert result["component_version"] == "1.8.0"

    assert run(_as_login(db, name, password, WORD_SIMILARITY)) > 0.3
    assert run(_as_login(db, name, password, COSINE)) == pytest.approx(1.0)
    for role in SEARCH_ROLES:
        assert run(_admin(db, f"SELECT has_schema_privilege('{role}','extensions','USAGE')"))
        assert not run(_admin(db, f"SELECT has_schema_privilege('{role}','extensions','CREATE')"))
    assert not run(
        _admin(db, "SELECT has_schema_privilege('mission_control_readonly','extensions','USAGE')")
    )
    assert not run(
        _admin(
            db,
            "SELECT has_schema_privilege('mission_control_runtime','extensions',"
            "'USAGE WITH GRANT OPTION')",
        )
    )
    assert run(_admin(db, "SELECT to_regclass('mission_control.reaction_binding') IS NOT NULL"))
    assert run(
        _admin(
            db, "SELECT to_regclass('mission_control.coordinator_delivery_observation') IS NOT NULL"
        )
    )
    assert run(verify_release(target, releases["1.8.0"], **VERSIONS))["status"] == "verified"
    again = _plan(target, releases["1.8.0"])
    assert again["plan"]["pending_migrations"] == []
    repeat, _ = install(target, releases["1.8.0"])
    assert repeat["applied_migrations"] == []


def test_without_grant_option_the_whole_upgrade_is_refused(
    make_db, releases, tmp_path, monkeypatch
):
    db = make_db("B")  # the migrator holds USAGE on extensions, without GRANT OPTION
    target = load_target(write_target(tmp_path, db, monkeypatch=monkeypatch))
    install(target, releases["1.7.0"])
    acl_before = run(_admin(db, "SELECT nspacl::text FROM pg_namespace WHERE nspname='extensions'"))
    plan = _plan(target, releases["1.8.0"])
    assert plan["plan"]["pending_migrations"] == NEW
    with pytest.raises(ContractError) as refused:
        run(
            apply_release(
                target,
                releases["1.8.0"],
                confirmation=f"{target['project_ref']}:{target['installation_id']}",
                expected_plan_digest=plan["plan_digest"],
                **VERSIONS,
            )
        )
    assert refused.value.code == "APPLY_FAILED"
    assert "0064_search_extension_privileges" in str(refused.value)
    assert "42501" in str(refused.value)
    # Atomic: no 1.8.0 receipt, no 0061/0063 object, no grant.
    assert run(_admin(db, "SELECT max(migration_key) FROM mission_control.component_release")) == (
        "0060_hook_candidate_installs"
    )
    assert run(_admin(db, "SELECT to_regclass('mission_control.reaction_binding')")) is None
    assert (
        run(_admin(db, "SELECT nspacl::text FROM pg_namespace WHERE nspname='extensions'"))
        == acl_before
    )
    assert run(verify_release(target, releases["1.7.0"], **VERSIONS))["status"] == "verified"


def test_the_committed_180_inputs_are_the_170_prefix_plus_three_migrations() -> None:
    previous = sorted(p.name for p in (PACKAGE / "releases/1.7.0/component/migrations").iterdir())
    current = sorted(p.name for p in (PACKAGE / "releases/1.8.0/component/migrations").iterdir())
    assert current == previous + [key + ".sql" for key in NEW]
    for name in previous:
        assert (PACKAGE / "releases/1.8.0/component/migrations" / name).read_bytes() == (
            PACKAGE / "releases/1.7.0/component/migrations" / name
        ).read_bytes()
    root = Path(__file__).resolve().parents[3]
    for key, directory in zip(
        NEW, ("scripts/release_170", "scripts/release_180", "scripts/release_180"), strict=True
    ):
        assert (PACKAGE / "releases/1.8.0/component/migrations" / f"{key}.sql").read_bytes() == (
            root / directory / f"{key}.sql"
        ).read_bytes()
