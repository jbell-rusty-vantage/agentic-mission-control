"""Trusted probe reads correlate real restricted PostgreSQL rows, never public attestations."""

from datetime import UTC, datetime
from uuid import uuid4

import asyncpg
import pytest

from mission_control.adapters.postgres.environments import PostgresEnvironmentPreparationRepository
from mission_control.adapters.postgres.frames.repository import PostgresFrameRepository
from mission_control.adapters.prerequisites.probes import ProviderOwnerProbeExecutor
from mission_control.adapters.secrets.sources import WorkerEnvironmentSource
from mission_control.application.prerequisites.probes import OwnerProbeBinding
from mission_control.application.prerequisites.setup import ProbeUnavailable
from mission_control.application.secrets.broker import SecretBroker
from mission_control.domain.execution.environment_preparation import (
    EnvironmentDeclaration,
    EnvironmentPreparation,
    ReadinessLevel,
    ReadinessMark,
    preparation_id,
)
from mission_control.domain.frames.contracts import LaneProfile
from tests.fixtures.mission_control_common_db import CommonDatabase, tenant_id
from tests.integration.postgres.frames_common import admit_unit_attempt
from tests.integration.postgres.runtime_common import common_db  # noqa: F401
from tests.unit.prerequisites.test_trusted_probes import record_for

pytestmark = pytest.mark.common_db


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "code"), [("signed_webhook", "ma2"), ("signal_receipt", "m1")]
)
async def test_receipt_requires_exact_scoped_binding_and_current_generation(
    common_db: CommonDatabase,  # noqa: F811
    operation: str,
    code: str,
) -> None:
    pool = await common_db.pool("mission_control_runtime")
    owner = await asyncpg.connect(common_db.owner_dsn)
    try:
        admitted = await admit_unit_attempt(pool, common_db)
        start = admitted.start(lane=LaneProfile.CLAUDE_MANAGED, native_session_ref="sess-probe")
        frames = PostgresFrameRepository(pool)
        await frames.open_execution(start)
        now = datetime.now(UTC)
        declaration = EnvironmentDeclaration(lane_profile="claude_managed")
        preparation = EnvironmentPreparation(
            preparation_id=preparation_id(common_db.scope(), start.harness_execution_id, 1),
            run_key=admitted.run_key,
            harness_execution_id=start.harness_execution_id,
            generation=1,
            lane_profile="claude_managed",
            binding_digest=start.intended_binding_digest,
            declaration=declaration,
            declaration_digest=declaration.digest,
            receipt_digest="sha256:" + "1" * 64,
            readiness=ReadinessLevel.DISCOVERED,
            marks=tuple(
                ReadinessMark(level=level, reached_at=now, evidence_ref="fixture:discovery")
                for level in tuple(ReadinessLevel)[:5]
            ),
        )
        await PostgresEnvironmentPreparationRepository(pool).record(common_db.scope(), preparation)
        record = record_for("claude_managed", code)
        binding = OwnerProbeBinding(
            request_scope=common_db.scope(),
            prerequisite_id=record.prerequisite.id,
            definition_digest=record.definition_digest,
            operation=operation,
            run_key=admitted.run_key,
            binding_digest=start.intended_binding_digest,
        )
        executor = ProviderOwnerProbeExecutor(
            SecretBroker(environment=WorkerEnvironmentSource({})), pool
        )
        with pytest.raises(ProbeUnavailable, match="no matching verified"):
            await executor.check(binding, record)
        # Trusted test writer supplies an inbox fixture. Signature verification itself is
        # exercised by test_signal_ingress_postgres through the restricted edge functions.
        receipt = uuid4()
        webhook = operation == "signed_webhook"
        await owner.execute(
            "INSERT INTO mission_control.ingress_inbox "
            "(installation_id,application_id,tenant_id,ingress_id,received_at,trust_tier,kind,"
            "credential_ref,dedupe_key,body_sha256,payload,run_key,unit_key,"
            "generation,state,attempts) "
            "VALUES ($1,'biotech',$2,$3,clock_timestamp(),$4,$5,'fixture-probe','delivery-1',"
            "$6,$7::jsonb,$8,$9,$10,'pending',0)",
            common_db.installation_id,
            None if webhook else tenant_id("tenant-1"),
            receipt,
            "provider_signed" if webhook else "run_token",
            "webhook.anthropic" if webhook else "signal.materialization.observed",
            "sha256:" + "2" * 64,
            '{"resource_ref":"sess-probe"}',
            None if webhook else admitted.run_key,
            None if webhook else admitted.unit.unit_key,
            None if webhook else 1,
        )
        observed = await executor.check(binding, record)
        assert str(receipt) in observed.evidence_ref
        assert observed.observed_at <= datetime.now(UTC)
        for change in (
            {"request_scope": common_db.scope("tenant-2")},
            {"binding_digest": "sha256:" + "3" * 64},
            {"run_key": "another-run"},
        ):
            with pytest.raises(ProbeUnavailable, match="no fresh scoped"):
                await executor.check(binding.model_copy(update=change), record)
        await frames.open_execution(start.model_copy(update={"generation": 2}))
        with pytest.raises(ProbeUnavailable, match="no fresh scoped"):
            await executor.check(binding, record)
        next_preparation = preparation.model_copy(
            update={
                "generation": 2,
                "preparation_id": preparation_id(common_db.scope(), start.harness_execution_id, 2),
            }
        )
        await PostgresEnvironmentPreparationRepository(pool).record(
            common_db.scope(), next_preparation
        )
        with pytest.raises(ProbeUnavailable, match="no matching verified"):
            await executor.check(binding, record)
    finally:
        await owner.close()
        await pool.close()
