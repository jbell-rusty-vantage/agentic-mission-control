"""Builders, constants and fakes that other test files import.

Moved from tests/integration/postgres/test_sprint_v_release_150.py.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import uuid4

import asyncpg
import pytest

from tests.support.integration.postgres.run2_release_141 import context


async def create_tenant(connection, target):
    tenant = uuid4()
    await connection.execute(
        "INSERT INTO mission_control.tenant "
        "(installation_id,application_id,tenant_id,external_tenant_ref,state,"
        "qualification_fixture,created_at,created_by_actor_ref) "
        "VALUES ($1::uuid,$2,$3,$4,'active',true,now(),'fixture:sprint-v')",
        target["installation_id"],
        target["application_id"],
        tenant,
        f"sprint-v-{tenant}",
    )
    return tenant


@asynccontextmanager
async def as_role(connection, target, tenant, role="mission_control_runtime"):
    async with connection.transaction():
        await connection.execute(f"SET LOCAL ROLE {role}")
        await context(connection, target, tenant)
        yield


async def raises_sqlstate(connection, sqlstate, query, *args):
    with pytest.raises(asyncpg.PostgresError) as caught:
        async with connection.transaction():
            await connection.execute(query, *args)
    assert caught.value.sqlstate == sqlstate, caught.value
    return caught.value
