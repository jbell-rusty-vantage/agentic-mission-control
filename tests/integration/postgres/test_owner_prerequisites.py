"""MO-20: migration 0038 and the Owner Prerequisite store on a real disposable PostgreSQL 17
(MISSION_CONTROL_TEST_ADMIN_DSN, loopback only).

- `owner_prerequisite` is tenant scoped under forced RLS with one three-column policy, a tenant
  FK, REVOKE PUBLIC, runtime SELECT/INSERT plus column-limited UPDATE, readonly SELECT.
- The repository inserts unmet records, writes nothing for an unchanged definition, replaces a
  changed definition keeping its evidence, and records attestations and verifications with the
  next version; another scope sees none of it.
- The table refuses what the record never does: a state the evidence method cannot set,
  inconsistent typed columns, a changed identity, a skipped version, an update back in time
  and a delete, even from the owner.
- The service over the repository registers what a claude_cloud binding needs with its
  generated content, verifies the 30-day login and flags it expiring before launch, expired
  after, and drifts the environment when the binding's kit changes.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
import pytest_asyncio

from mission_control.adapters.postgres.prerequisites import PostgresOwnerPrerequisiteRepository
from mission_control.application.prerequisites import (
    OwnerPrerequisiteService,
    UnknownPrerequisite,
    generate_owner_prerequisites,
)
from mission_control.domain.prerequisites import (
    EvidenceRefused,
    OwnerPrerequisiteRecord,
    PrerequisiteEvidence,
    PrerequisiteStanding,
    PrerequisiteState,
    VerificationMethod,
)
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.fixtures.owner_prerequisites import inputs
from tests.integration.postgres.runtime_common import (  # noqa: F401
    common_db,
    owner_rows,
    scoped_count,
)

pytestmark = pytest.mark.common_db

AT = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
TABLE = "owner_prerequisite"
ENVIRONMENT = "claude_cloud.environment.envkit-python-uv-node-1"
LOGIN = "claude_cloud.host.auth_login"
RUNTIME_UPDATE_COLUMNS = {
    "definition_digest",
    "state",
    "verification_method",
    "expires_at",
    "record",
    "version",
    "updated_at",
}
OTHER_ROLES = (
    "mission_control_family_writer",
    "mission_control_catalog_writer",
    "mission_control_outbox_worker",
    "public",
)
PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")


class Clock:
    def __init__(self) -> None:
        self.now = AT

    def __call__(self) -> datetime:
        return self.now


@pytest_asyncio.fixture
async def pool(common_db: CommonDatabase) -> AsyncIterator[asyncpg.Pool]:  # noqa: F811
    created = await common_db.pool("mission_control_runtime")
    try:
        yield created
    finally:
        await created.close()


@pytest_asyncio.fixture
async def owner(common_db: CommonDatabase) -> AsyncIterator[asyncpg.Connection]:  # noqa: F811
    connection = await asyncpg.connect(common_db.owner_dsn)
    try:
        yield connection
    finally:
        await connection.close()


async def _privileges(db: CommonDatabase, role: str) -> set[str]:
    rows = await owner_rows(
        db,
        "SELECT privilege FROM unnest($2::text[]) AS privilege "
        "WHERE has_table_privilege($1, 'mission_control.owner_prerequisite', privilege)",
        role,
        list(PRIVILEGES),
    )
    return {row["privilege"] for row in rows}


async def _update_columns(db: CommonDatabase, role: str) -> set[str]:
    rows = await owner_rows(
        db,
        "SELECT a.attname FROM pg_attribute a "
        "WHERE a.attrelid = 'mission_control.owner_prerequisite'::regclass AND a.attnum > 0 "
        "AND NOT a.attisdropped AND has_column_privilege($1, a.attrelid, a.attnum, 'UPDATE')",
        role,
    )
    return {row["attname"] for row in rows}


async def _row(db: CommonDatabase, prerequisite_id: str) -> dict[str, object]:
    (row,) = await owner_rows(
        db,
        "SELECT provider, prerequisite_scope, definition_digest, state, verification_method, "
        "expires_at, version, updated_at FROM mission_control.owner_prerequisite "
        "WHERE prerequisite_id = $1",
        prerequisite_id,
    )
    return dict(row)


# --------------------------------------------------------------------------- catalog shape


async def test_prerequisites_are_scoped_forced_rls_with_declared_grants(
    common_db: CommonDatabase,  # noqa: F811
) -> None:
    (row,) = await owner_rows(
        common_db,
        """
        SELECT c.relrowsecurity, c.relforcerowsecurity,
               (SELECT array_agg(pg_get_expr(p.polqual, p.polrelid) || ' / '
                                 || pg_get_expr(p.polwithcheck, p.polrelid))
                FROM pg_policy p WHERE p.polrelid = c.oid) AS policies,
               EXISTS (SELECT 1 FROM pg_constraint k WHERE k.conrelid = c.oid
                       AND k.contype = 'f'
                       AND k.confrelid = 'mission_control.tenant'::regclass) AS tenant_fk,
               (SELECT count(*) FROM aclexplode(c.relacl) x WHERE x.grantee = 0) AS public_acl
        FROM pg_class c WHERE c.oid = 'mission_control.owner_prerequisite'::regclass
        """,
    )
    assert (row["relrowsecurity"], row["relforcerowsecurity"]) == (True, True)
    assert row["tenant_fk"] and row["public_acl"] == 0
    (policy,) = row["policies"]
    for function in ("ctx_installation_id", "ctx_application_id", "ctx_tenant_id"):
        assert policy.count(function) == 2, policy
    assert await _privileges(common_db, "mission_control_runtime") == {"SELECT", "INSERT"}
    assert await _update_columns(common_db, "mission_control_runtime") == RUNTIME_UPDATE_COLUMNS
    assert await _privileges(common_db, "mission_control_readonly") == {"SELECT"}
    for role in OTHER_ROLES:
        assert await _privileges(common_db, role) == set(), role
    assert not (
        await owner_rows(
            common_db,
            "SELECT has_function_privilege('public', "
            "'mission_control.owner_prerequisite_guard()', 'EXECUTE') AS allowed",
        )
    )[0]["allowed"]


# --------------------------------------------------------------------------- repository


async def test_the_repository_registers_records_evidence_and_keeps_scopes_apart(
    common_db: CommonDatabase,  # noqa: F811
    pool: asyncpg.Pool,
) -> None:
    clock = Clock()
    repository = PostgresOwnerPrerequisiteRepository(pool, clock=clock)
    scope = common_db.scope()
    environment, login = generate_owner_prerequisites("claude_cloud", inputs())
    assert environment.id == ENVIRONMENT and login.id == LOGIN

    unmet = await repository.register(scope, environment)
    assert unmet == OwnerPrerequisiteRecord.of(environment)
    assert await repository.register(scope, environment) == unmet  # nothing written
    await repository.register(scope, login)
    assert [record.id for record in await repository.list(scope)] == [ENVIRONMENT, LOGIN]
    assert await repository.get(scope, ENVIRONMENT) == unmet
    # Generated content round-trips byte for byte with its digests.
    stored = await repository.get(scope, ENVIRONMENT)
    assert stored is not None
    assert stored.prerequisite.content_digests == environment.content_digests
    assert [item.content for item in stored.prerequisite.generated] == [
        item.content for item in environment.generated
    ]
    assert await _row(common_db, ENVIRONMENT) == {
        "provider": "anthropic",
        "prerequisite_scope": "environment",
        "definition_digest": environment.digest,
        "state": "unmet",
        "verification_method": None,
        "expires_at": None,
        "version": 1,
        "updated_at": AT,
    }

    clock.now = AT + timedelta(minutes=5)
    attested = await repository.record_evidence(
        scope,
        ENVIRONMENT,
        PrerequisiteEvidence(
            method=VerificationMethod.ATTESTATION,
            definition_digest=environment.digest,
            recorded_at=clock.now,
            value="env_01ABCdef",
        ),
    )
    assert attested.state is PrerequisiteState.ATTESTED
    expires = AT + timedelta(days=30)
    verified = await repository.record_evidence(
        scope,
        LOGIN,
        PrerequisiteEvidence(
            method=VerificationMethod.FILE_CHECK,
            definition_digest=login.digest,
            recorded_at=AT,
            evidence_ref="file:claude-auth",
            expires_at=expires,
        ),
    )
    assert verified.state is PrerequisiteState.VERIFIED
    assert await repository.get(scope, LOGIN) == verified
    login_row = await _row(common_db, LOGIN)
    assert (login_row["state"], login_row["verification_method"]) == ("verified", "file_check")
    assert (login_row["expires_at"], login_row["version"]) == (expires, 2)

    # A changed definition replaces the stored one and keeps the evidence it no longer matches.
    changed = generate_owner_prerequisites("claude_cloud", inputs(system_packages=["git"]))[0]
    replaced = await repository.register(scope, changed)
    assert replaced.prerequisite == changed and replaced.evidence == attested.evidence
    environment_row = await _row(common_db, ENVIRONMENT)
    assert environment_row["definition_digest"] == changed.digest
    assert (environment_row["state"], environment_row["version"]) == ("attested", 3)
    with pytest.raises(EvidenceRefused):
        await repository.record_evidence(
            scope,
            ENVIRONMENT,
            PrerequisiteEvidence(
                method=VerificationMethod.ATTESTATION,
                definition_digest=environment.digest,
                recorded_at=clock.now,
            ),
        )
    assert attested.evidence is not None
    with pytest.raises(UnknownPrerequisite):
        await repository.record_evidence(
            scope, "claude_cloud.environment.absent", attested.evidence
        )

    other = common_db.scope("tenant-2")
    assert await repository.list(other) == ()
    assert await repository.get(other, ENVIRONMENT) is None
    assert await scoped_count(pool, scope, TABLE) == 2
    assert await scoped_count(pool, None, TABLE) == 0


async def test_the_table_refuses_what_the_record_never_does(
    common_db: CommonDatabase,  # noqa: F811
    pool: asyncpg.Pool,
    owner: asyncpg.Connection,
) -> None:
    repository = PostgresOwnerPrerequisiteRepository(pool, clock=lambda: AT)
    scope = common_db.scope()
    _environment, login = generate_owner_prerequisites("claude_cloud", inputs())
    await repository.register(scope, login)
    where = "WHERE prerequisite_id = 'claude_cloud.host.auth_login'"
    update = f"UPDATE mission_control.owner_prerequisite SET {{}}, version = version + 1 {where}"

    # A verified state needs a verifying method; an attestation only attests.
    with pytest.raises(asyncpg.CheckViolationError):
        await owner.execute(
            update.format("state = 'verified', verification_method = 'attestation'")
        )
    with pytest.raises(asyncpg.CheckViolationError):
        await owner.execute(update.format("state = 'attested', verification_method = 'api_probe'"))
    with pytest.raises(asyncpg.CheckViolationError):
        await owner.execute(update.format("verification_method = 'file_check'"))
    # Typed columns mirror the record.
    with pytest.raises(asyncpg.CheckViolationError):
        await owner.execute(update.format(f"definition_digest = 'sha256:{'0' * 64}'"))
    record = json.loads(OwnerPrerequisiteRecord.of(login).model_dump_json())
    record["prerequisite"]["provider"] = "openai"
    with pytest.raises(asyncpg.CheckViolationError):
        await owner.execute(
            f"UPDATE mission_control.owner_prerequisite SET record = $1::jsonb, "
            f"version = version + 1 {where}",
            json.dumps(record),
        )
    # The guard: identity, version, time and deletes.
    with pytest.raises(asyncpg.RestrictViolationError, match="identity"):
        await owner.execute(update.format("provider = 'openai'"))
    with pytest.raises(asyncpg.RestrictViolationError, match="advances by one"):
        await owner.execute(
            f"UPDATE mission_control.owner_prerequisite SET version = version + 2 {where}"
        )
    with pytest.raises(asyncpg.RestrictViolationError, match="back in time"):
        await owner.execute(update.format("updated_at = updated_at - interval '1 hour'"))
    with pytest.raises(asyncpg.RestrictViolationError, match="never deleted"):
        await owner.execute(f"DELETE FROM mission_control.owner_prerequisite {where}")
    assert (await _row(common_db, LOGIN))["version"] == 1


# --------------------------------------------------------------------------- service


async def test_the_service_flags_an_expiring_login_before_launch_on_postgres(
    common_db: CommonDatabase,  # noqa: F811
    pool: asyncpg.Pool,
) -> None:
    clock = Clock()
    service = OwnerPrerequisiteService(
        PostgresOwnerPrerequisiteRepository(pool, clock=clock), clock=clock
    )
    scope = common_db.scope()
    fresh = await service.register_for_binding(scope, "claude_cloud", inputs())
    assert {item.prerequisite_id: item.standing for item in fresh} == {
        ENVIRONMENT: PrerequisiteStanding.UNMET,
        LOGIN: PrerequisiteStanding.UNMET,
    }
    await service.attest(scope, ENVIRONMENT, value="env_01ABCdef")
    # Owner identifiers do not substitute for the declared environment probe mission.
    attested = await service.assess(scope, prerequisite_ids=[ENVIRONMENT])
    assert attested[0].standing is PrerequisiteStanding.UNMET
    await service.verify(
        scope,
        ENVIRONMENT,
        method=VerificationMethod.PROBE_MISSION,
        evidence_ref="fixture-probe:environment-preparation",
    )
    await service.verify(
        scope, LOGIN, method=VerificationMethod.FILE_CHECK, evidence_ref="file:claude-auth"
    )

    clock.now = AT + timedelta(days=24)
    standings = {item.prerequisite_id: item for item in await service.assess(scope)}
    assert standings[ENVIRONMENT].standing is PrerequisiteStanding.MET
    assert standings[LOGIN].standing is PrerequisiteStanding.EXPIRING
    assert standings[LOGIN].expires_at == AT + timedelta(days=30)
    assert not any(item.blocking for item in standings.values())

    clock.now = AT + timedelta(days=30)
    (expired,) = await service.assess(scope, prerequisite_ids=[LOGIN])
    assert expired.standing is PrerequisiteStanding.EXPIRED and expired.blocking

    republished = inputs(system_packages=["git"])
    by_id = {
        item.prerequisite_id: item
        for item in await service.register_for_binding(scope, "claude_cloud", republished)
    }
    assert by_id[ENVIRONMENT].standing is PrerequisiteStanding.DRIFTED
    assert by_id[LOGIN].standing is PrerequisiteStanding.EXPIRED
