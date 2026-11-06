"""Preflight reads persisted evidence and never reuses another tenant's attestations."""

from datetime import UTC, datetime, timedelta

import asyncpg
import pytest

from mission_control.adapters.postgres.prerequisites import PostgresOwnerPrerequisiteRepository
from mission_control.application.prerequisites.preflight import PrerequisitePreflight
from mission_control.application.prerequisites.service import OwnerPrerequisiteService
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.integration.postgres.test_owner_prerequisites import common_db, pool  # noqa: F401
from tests.unit.prerequisites.test_preflight import definition

pytestmark = pytest.mark.common_db


async def test_preflight_persists_owner_steps_and_refuses_expired_evidence(
    common_db: CommonDatabase,  # noqa: F811
    pool: asyncpg.Pool,  # noqa: F811
) -> None:
    repository = PostgresOwnerPrerequisiteRepository(pool)
    preflight = PrerequisitePreflight(repository)
    scope = common_db.scope()
    first = await preflight.assess(scope, (definition(),))
    assert not first.ready and len(first.items) == 8
    stored = await repository.list(scope)
    assert {item.id for item in stored} == {item.prerequisite.id for item in first.items}
    assert not await repository.list(common_db.scope("tenant-2"))
    old = datetime.now(UTC) - timedelta(days=2)
    service = OwnerPrerequisiteService(repository, clock=lambda: old)
    for item in first.items:
        await service.attest(scope, item.prerequisite.id, expires_at=old + timedelta(days=1))
    # A fresh facade/repository must read the same durable expiry; no cached success.
    fresh = PrerequisitePreflight(PostgresOwnerPrerequisiteRepository(pool))
    report = await fresh.assess(scope, (definition(),))
    assert not report.ready
    assert all(item.assessment.standing == "expired" for item in report.items)
