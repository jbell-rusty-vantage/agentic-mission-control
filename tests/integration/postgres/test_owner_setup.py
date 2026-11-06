"""Owner setup persists attestations and server-generated evidence under forced RLS."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import asyncpg
import pytest

from mission_control.adapters.postgres.prerequisites import PostgresOwnerPrerequisiteRepository
from mission_control.application.prerequisites.setup import (
    AttestRequest,
    OwnerSetupService,
    ProbeResult,
)
from mission_control.domain.prerequisites import VerificationMethod
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.integration.postgres.test_owner_prerequisites import common_db, pool  # noqa: F401

pytestmark = pytest.mark.common_db


async def test_owner_attestation_and_trusted_probe_roundtrip(
    common_db: CommonDatabase,  # noqa: F811
    pool: asyncpg.Pool,  # noqa: F811
) -> None:
    scope = common_db.scope()
    repository = PostgresOwnerPrerequisiteRepository(pool)
    service = OwnerSetupService(repository)
    plan = await service.plan(scope, "claude_managed")
    prerequisite = plan.items[0].prerequisite
    await service.attest(
        scope,
        prerequisite.id,
        AttestRequest(definition_digest=prerequisite.digest, value="env_test"),
        actor_id="fixture-owner",
    )
    record = await repository.get(scope, prerequisite.id)
    assert record.state == "attested" and record.evidence.value == "env_test"
    service.probes = SimpleNamespace(
        verify=AsyncMock(
            return_value=ProbeResult(
                method=VerificationMethod.API_PROBE,
                evidence_ref="artifact:fixture-proof",
            )
        )
    )
    await service.verify(scope, prerequisite.id, prerequisite.digest)
    durable = await PostgresOwnerPrerequisiteRepository(pool).get(scope, prerequisite.id)
    assert durable.state == "verified" and durable.evidence.evidence_ref == "artifact:fixture-proof"
    assert await repository.get(common_db.scope("tenant-2"), prerequisite.id) is None
