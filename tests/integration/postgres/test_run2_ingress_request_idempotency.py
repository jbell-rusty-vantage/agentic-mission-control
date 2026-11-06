# ruff: noqa: F811
"""MO-79 additive 0044 over real 1.4.1 rows, using only restricted ingress functions.

Disposable SQL behavior/upgrade proof, not a release-attestation qualification. The owner
connection installs the new migration and creates a deterministic row-lock barrier; request
and status operations run through the existing mission_control_ingress-only fixture login.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import pytest
import pytest_asyncio

from mission_control.adapters.postgres.ingress import (
    PostgresIngressStore,
    PostgresMintedCredentialStore,
)
from mission_control.application.secrets.minting import CredentialMinter, LaunchBinding
from mission_control.application.signals.contracts import IngressRejected
from tests.fixtures.mission_control_common_db import create_common_database, drop_common_database
from tests.integration.postgres.test_signal_ingress_postgres import (
    Ingress,
    bearer,
    ingress,  # noqa: F401
)

pytestmark = pytest.mark.common_db
ROOT = Path(__file__).resolve().parents[3]
RELEASES = ROOT / "packages/mission-control-db-contract/releases"
MIGRATION = RELEASES / "1.4.2/component/migrations/0044_ingress_mission_request_idempotency.sql"
SIGNATURE = "mission_control.ingress_mission_request(uuid,text,text,uuid,text,text,text,jsonb)"


@pytest_asyncio.fixture
async def common_db():
    database = await create_common_database(
        paths=sorted((RELEASES / "1.4.1/component/migrations").glob("*.sql")),
        component_version="1.4.1",
    )
    try:
        yield database
    finally:
        await drop_common_database(database)


def body(key, *, manifest="fixture:first", value="original"):
    return json.dumps(
        {"idempotency_key": key, "manifest_ref": manifest, "inputs": {"topic": value}}
    ).encode()


async def credential(value, *, scope=None):
    scope = scope or value.scope
    return await CredentialMinter(PostgresMintedCredentialStore(value.runtime, scope)).mint(
        "mission_request",
        LaunchBinding(scope),
        context={"manifest_refs": ["fixture:first", "fixture:second"]},
    )


async def upgrade(value):
    sql = await asyncio.to_thread(MIGRATION.read_text, encoding="utf-8")
    await value.owner(sql)


async def function_metadata(value):
    rows = await value.owner(
        "SELECT proowner,proacl,prosecdef,proconfig FROM pg_proc WHERE oid=$1::regprocedure",
        SIGNATURE,
    )
    return dict(rows[0])


async def test_upgrade_preserves_original_receipt_and_refuses_conflicting_body(ingress: Ingress):
    token = await credential(ingress)
    headers = bearer(token.value)
    request = body("before-upgrade")
    original_id = await ingress.service.request_mission(request, headers)
    original = dict((await ingress.inbox("mission_request"))[0])
    metadata = await function_metadata(ingress)
    await upgrade(ingress)
    assert await function_metadata(ingress) == metadata
    assert metadata["prosecdef"] and "search_path=pg_catalog" in metadata["proconfig"]
    assert await ingress.service.request_mission(request, headers) == original_id
    for conflicting in (
        body("before-upgrade", manifest="fixture:second"),
        body("before-upgrade", value="changed"),
    ):
        with pytest.raises(IngressRejected) as failure:
            await ingress.service.request_mission(conflicting, headers)
        assert (failure.value.status_code, failure.value.code) == (409, "dedupe_conflict")
    # The definer surface also refuses a direct SQL caller supplying the old digest
    # alongside a different payload; the public ingress computes its own digest.
    changed_payload = json.loads(original["payload"])
    changed_payload["inputs"]["topic"] = "forged-digest"
    async with ingress.edge.acquire() as connection:
        forged = await connection.fetchrow(
            "SELECT * FROM mission_control.ingress_mission_request($1,$2,$3,$4,$5,$6,$7,$8::jsonb)",
            ingress.db.installation_id,
            ingress.db.application_id,
            token.record.digest,
            uuid4(),
            "before-upgrade",
            "fixture:first",
            original["body_sha256"],
            json.dumps(changed_payload),
        )
    assert dict(forged) == {"outcome": "dedupe_conflict", "request_id": None}
    assert dict((await ingress.inbox("mission_request"))[0]) == original
    assert (await ingress.service.mission_request_status(original_id, headers)).state == "queued"
    async with ingress.edge.acquire() as connection:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await connection.fetch("SELECT * FROM mission_control.ingress_inbox")
    # Credentials bind their own tenant: the same key cannot expose or mutate its sibling.
    other = await credential(ingress, scope=ingress.db.scope("tenant-2"))
    other_id = await ingress.service.request_mission(request, bearer(other.value))
    assert other_id != original_id
    with pytest.raises(IngressRejected) as cross_scope:
        await ingress.service.mission_request_status(original_id, bearer(other.value))
    assert cross_scope.value.code == "not_found"
    wrong_app = PostgresIngressStore(
        ingress.edge,
        installation_id=ingress.db.installation_id,
        application_id="ai-engineer",
    )
    from mission_control.application.signals.service import SignalIngressService

    with pytest.raises(IngressRejected) as wrong_scope:
        await SignalIngressService(wrong_app, keys=ingress.service._keys).request_mission(
            request, headers
        )
    assert wrong_scope.value.status_code == 401


@pytest.mark.parametrize("conflicting", [False, True])
async def test_concurrent_insert_conflict_checks_the_winning_digest(ingress: Ingress, conflicting):
    await upgrade(ingress)
    token = await credential(ingress)
    headers = bearer(token.value)
    first = body("simultaneous")
    second = body("simultaneous", value="changed") if conflicting else first
    owner = await asyncpg.connect(ingress.db.owner_dsn)
    tasks = []
    try:
        async with owner.transaction():
            # Both calls pass the initial absent-row lookup, then block in ingress_take_rate.
            # Releasing this existing credential lock forces the INSERT conflict branch.
            await owner.fetchval(
                "SELECT credential_id FROM mission_control.ingress_credential "
                "WHERE credential_id=$1::uuid FOR UPDATE",
                UUID(token.record.credential_id),
            )
            tasks = [
                asyncio.create_task(ingress.service.request_mission(payload, headers))
                for payload in (first, second)
            ]
            async with asyncio.timeout(5):
                while True:
                    # Statistics snapshots are cached for this barrier transaction.
                    await owner.execute("SELECT pg_stat_clear_snapshot()")
                    waiting = await owner.fetchval(
                        "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                        "AND wait_event_type='Lock' AND pid<>pg_backend_pid() "
                        "AND query LIKE '%ingress_mission_request(%'",
                    )
                    if waiting == 2:
                        break
                    await asyncio.sleep(0.02)
        results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 5)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await owner.close()
    rows = await ingress.inbox("mission_request")
    assert len(rows) == 1
    winner = rows[0]
    successes = [result for result in results if not isinstance(result, BaseException)]
    failures = [result for result in results if isinstance(result, BaseException)]
    if conflicting:
        assert successes == [winner["ingress_id"]]
        assert len(failures) == 1 and isinstance(failures[0], IngressRejected)
        assert (failures[0].status_code, failures[0].code) == (409, "dedupe_conflict")
    else:
        assert successes == [winner["ingress_id"], winner["ingress_id"]] and not failures
    winner_body = json.loads(winner["payload"])
    matching = body("simultaneous", value=winner_body["inputs"]["topic"])
    assert await ingress.service.request_mission(matching, headers) == winner["ingress_id"]
    assert dict((await ingress.inbox("mission_request"))[0]) == dict(winner)
