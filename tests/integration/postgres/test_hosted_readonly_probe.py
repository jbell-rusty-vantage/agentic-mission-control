"""Restricted-role persistence of exact source proof and refusal after config drift."""

import pytest

from mission_control.adapters.postgres.prerequisites import PostgresOwnerPrerequisiteRepository
from mission_control.adapters.prerequisites.probes import ProviderOwnerProbeExecutor
from mission_control.application.prerequisites.catalog import account_prerequisites
from mission_control.application.prerequisites.probes import OwnerProbeConfiguration
from mission_control.application.prerequisites.service import OwnerPrerequisiteService
from mission_control.application.prerequisites.setup import ProbeUnavailable
from mission_control.application.secrets.references import BrokerRef
from mission_control.bootstrap.hosted_readonly import HostedReadonlyVerifier
from mission_control.bootstrap.settings import Settings
from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.prerequisites import VerificationMethod
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.integration.postgres.runtime_common import common_db  # noqa: F401
from tests.unit.prerequisites.test_hosted_readonly import readonly_binding, readonly_template

pytestmark = pytest.mark.common_db


async def test_exact_readonly_source_proof_persists_and_config_change_refuses(
    common_db: CommonDatabase,  # noqa: F811
    tmp_path,
):
    pool = await common_db.pool("mission_control_runtime")
    try:
        operation = readonly_template().model_copy(update={"request_scope": common_db.scope()})
        prerequisite = next(
            item
            for item in account_prerequisites(LaneProfile.CLAUDE_MANAGED)
            if item.id.endswith(".ma4")
        )
        binding = readonly_binding(operation, prerequisite)
        repository = PostgresOwnerPrerequisiteRepository(pool)
        await repository.register(operation.request_scope, prerequisite)
        proof = ProviderOwnerProbeExecutor._evidence(binding)
        await OwnerPrerequisiteService(repository).verify(
            operation.request_scope,
            prerequisite.id,
            method=VerificationMethod.API_PROBE,
            evidence_ref=proof.evidence_ref,
            definition_digest=prerequisite.digest,
        )
        path = tmp_path / "probe-config.json"
        path.write_text(
            OwnerProbeConfiguration(bindings=(binding,)).model_dump_json(), encoding="utf-8"
        )
        verifier = HostedReadonlyVerifier(
            Settings(_env_file=None, mission_control_owner_probes_path=path), pool
        )
        await verifier.verify_hosted_readonly(
            operation, (BrokerRef.parse("environment:READONLY_REPO_KEY"),)
        )
        changed = binding.model_copy(update={"repo_ref": "different"})
        path.write_text(
            OwnerProbeConfiguration(bindings=(changed,)).model_dump_json(), encoding="utf-8"
        )
        with pytest.raises(ProbeUnavailable):
            await verifier.verify_hosted_readonly(
                operation, (BrokerRef.parse("environment:READONLY_REPO_KEY"),)
            )
        with pytest.raises(ProbeUnavailable):
            await verifier.verify_hosted_readonly(
                operation.model_copy(update={"request_scope": common_db.scope("tenant-2")}),
                (BrokerRef.parse("environment:READONLY_REPO_KEY"),),
            )
    finally:
        await pool.close()
