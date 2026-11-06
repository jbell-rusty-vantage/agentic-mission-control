"""Read real immutable validation journal rows with restricted pools and forced RLS."""

import pytest

from mission_control.adapters.postgres.orchestration.completion_evidence import (
    PostgresCompletionEvidenceReader,
)
from mission_control.adapters.postgres.run_control import canonical as mc
from mission_control.adapters.postgres.run_control.run_control_repository import (
    PostgresRunControlRepository,
)
from mission_control.contracts.identities import uuid7
from mission_control.domain.authoring.canonical import sha256_digest
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.integration.postgres.runtime_common import common_db as common_db
from tests.unit.mission_control.test_completion_evidence import receipt_row
from tests.unit.run_control.test_run_control import request, service

pytestmark = pytest.mark.common_db


@pytest.mark.asyncio
async def test_journal_pagination_survives_restart_and_is_scoped(common_db: CommonDatabase):
    scope = common_db.scope()
    pool = await common_db.pool()
    try:
        runs, _ = service(PostgresRunControlRepository(pool))
        admitted = await runs.admit(request(request_scope=scope))
        run_id = admitted.run_id
        assert run_id
    finally:
        await pool.close()
    writer = await common_db.pool("mission_control_family_writer")
    try:
        # Reader fixture receipts use the real immutable journal, real grants and exact
        # fingerprints. Runtime validation/settlement itself has separate service tests.
        async with writer.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            for version in (1, 2):
                row = receipt_row(run_id=run_id, scope=scope, version=version)
                if version == 2:
                    validation = row["mutation"]["decision_payload"]["completion_validation"]
                    validation["status"] = "satisfied"
                    validation["reason_codes"] = []
                    row["mutation_fingerprint"] = sha256_digest(
                        {
                            key: value
                            for key, value in row["mutation"].items()
                            if key != "decided_at"
                        }
                    )
                await connection.execute(
                    """
                    INSERT INTO mission_control.family_admission_journal (
                        installation_id, application_id, tenant_id, family_admission_journal_id,
                        run_key, family_kind, family_version, mutation_kind, mutation_key,
                        mutation_fingerprint, mutation_contract, mutation, decided_at, created_at,
                        created_by_actor_ref
                    ) VALUES ($1,$2,$3,$4,$5,'stagegraph',$6,'decision_committed',$7,$8,
                              'mc.family-mutation/1',$9::jsonb,$10,$10,'test-reader-fixture')
                    """,
                    *args,
                    uuid7(),
                    run_id,
                    version,
                    row["mutation_key"],
                    row["mutation_fingerprint"],
                    mc.dump(row["mutation"]),
                    row["decided_at"],
                )
    finally:
        await writer.close()
    pool = await common_db.pool()
    try:
        reader = PostgresCompletionEvidenceReader(pool)
        first = await reader.list(scope, run_id, limit=1)
        assert first.status == "recorded"
        assert first.decisions[0].validation.status == "pending"
        assert first.next_after_family_version == 1
        second = await reader.list(scope, run_id, after_family_version=1, limit=1)
        assert second.decisions[0].validation.status == "satisfied"
        assert second.next_after_family_version is None
        assert (await reader.list(scope, run_id, after_family_version=2)).status == "not_recorded"
        assert (await reader.list(common_db.scope("tenant-2"), run_id)).decisions == ()
        with pytest.raises(ValueError, match="bounds"):
            await reader.list(scope, run_id, limit=101)
    finally:
        await pool.close()
