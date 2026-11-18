"""Builders, constants and fakes that other test files import.

Moved from tests/integration/postgres/test_db_release_142_install_and_drift_refusal.py.
"""

from __future__ import annotations

from uuid import uuid4

from tests.support.integration.postgres.db_release_141_install_upgrade_and_drift import (
    insert_document,
)


async def preserve_document(connection, target):
    tenant = uuid4()
    await connection.execute(
        "INSERT INTO mission_control.tenant "
        "(installation_id,application_id,tenant_id,external_tenant_ref,state,"
        "qualification_fixture,created_at,created_by_actor_ref) "
        "VALUES ($1::uuid,$2,$3,'release-142-preserved','active',true,now(),'fixture:successor')",
        target["installation_id"],
        target["application_id"],
        tenant,
    )
    await insert_document(connection, target, tenant, "operation.binding/1", "before-upgrade")
    row = await connection.fetchrow(
        "SELECT * FROM mission_control.runtime_document WHERE tenant_id=$1", tenant
    )
    assert row is not None
    return tenant, row
