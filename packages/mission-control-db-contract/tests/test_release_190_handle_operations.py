"""Release 1.9.0 on a Supabase-like cluster B (Sprint OC W1 defect D22, upgrade path from 1.8.0).

Cluster B installs as the NON-superuser CREATEROLE migration principal, as on Supabase. On 1.8.0
the `knowledge_operation_handle` operation check refuses the trusted assessment operations (W1
session 6: the KS-accepted auditor `report.observe` handle). The additive 1.9.0 upgrade applies
exactly 0066 and 0067 under that principal (the table, its check and the guard function are the
component's own, so no platform grant is needed), after which the check names exactly the eleven
handle operations, verify passes and a repeat changes nothing. The committed 1.9.0 inputs are the
built 1.8.0 prefix plus the two authored migrations, byte for byte.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from conftest import PACKAGE, VERSIONS, build_and_lock, copy_component, run, write_target
from test_install import install

from mission_control_db_contract.deployment import apply_release, plan_release, verify_release
from mission_control_db_contract.integrity import Release
from mission_control_db_contract.target import load_target

NEW = ["0066_collection_member_assessments", "0067_knowledge_handle_trusted_operations"]
HANDLE_OPERATIONS = (
    "decision.resolve",
    "knowledge.apply",
    "knowledge.read",
    "report.assess",
    "report.decide",
    "report.derive",
    "report.observe",
    "report.register",
    "report.review",
    "report.seal",
    "verify.claims",
)
CHECK = (
    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
    "WHERE conname = 'knowledge_operation_handle_operation_check'"
)


@pytest.fixture(scope="module")
def releases(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Release]:
    """1.8.0 and 1.9.0 rebuilt from their committed inputs on disposable cluster A."""

    built = {}
    for version in ("1.8.0", "1.9.0"):
        work = tmp_path_factory.mktemp("release-" + version.replace(".", ""))
        root = copy_component(work, source=PACKAGE / "releases" / version / "component")
        built[version] = build_and_lock(work, root, "ai-engineer")
    return built


async def _admin(db, query: str):  # type: ignore[no-untyped-def]
    connection = await db.connect()
    try:
        return await connection.fetchval(query)
    finally:
        await connection.close()


def test_upgrade_from_180_widens_the_handle_check_on_a_supabase_like_cluster(
    make_db, releases, tmp_path, monkeypatch
):
    db = make_db("B")
    # 1.8.0's 0064 needs the installing login to pass USAGE on `extensions` on.
    run(_admin(db, "GRANT USAGE ON SCHEMA extensions TO mcdb_migrator WITH GRANT OPTION"))
    target = load_target(write_target(tmp_path, db, app="ai-engineer", monkeypatch=monkeypatch))
    install(target, releases["1.8.0"])
    before = run(_admin(db, CHECK))
    assert "'report.observe'" not in before and "'verify.claims'" in before

    plan = run(plan_release(target, releases["1.9.0"], **VERSIONS))
    assert plan["plan"]["holds"] == []
    assert plan["plan"]["pending_migrations"] == NEW
    result = run(
        apply_release(
            target,
            releases["1.9.0"],
            confirmation=f"{target['project_ref']}:{target['installation_id']}",
            expected_plan_digest=plan["plan_digest"],
            **VERSIONS,
        )
    )
    assert result["applied_migrations"] == NEW
    assert result["component_version"] == "1.9.0"
    after = run(_admin(db, CHECK))
    assert sorted(set(re.findall(r"'([a-z]+\.[a-z]+)'", after))) == list(HANDLE_OPERATIONS)
    assert run(verify_release(target, releases["1.9.0"], **VERSIONS))["status"] == "verified"
    again = run(plan_release(target, releases["1.9.0"], **VERSIONS))
    assert again["plan"]["pending_migrations"] == []
    repeat, _ = install(target, releases["1.9.0"])
    assert repeat["applied_migrations"] == []


def test_the_committed_190_inputs_are_the_180_prefix_plus_two_migrations() -> None:
    previous = sorted(p.name for p in (PACKAGE / "releases/1.8.0/component/migrations").iterdir())
    current = sorted(p.name for p in (PACKAGE / "releases/1.9.0/component/migrations").iterdir())
    assert current == previous + [key + ".sql" for key in NEW]
    for name in previous:
        assert (PACKAGE / "releases/1.9.0/component/migrations" / name).read_bytes() == (
            PACKAGE / "releases/1.8.0/component/migrations" / name
        ).read_bytes()
    root = Path(__file__).resolve().parents[3]
    for key in NEW:
        assert (PACKAGE / "releases/1.9.0/component/migrations" / f"{key}.sql").read_bytes() == (
            root / "scripts/release_190" / f"{key}.sql"
        ).read_bytes()
