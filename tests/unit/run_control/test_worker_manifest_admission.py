"""Loop iter-1 L1-01: the worker composition admits manifest-lowered nested bodies.

The worker's run control admits nested Goal Loop and Stage Graph bodies (and released chain
consumers) whose Workflow Types carry the manifest admission contract. Before the fix the
worker composed an empty registry and every nested activation was refused.
"""

from __future__ import annotations

import pytest

from mission_control.adapters.temporal.worker import compose_worker_run_control_service
from mission_control.application.execution.run_control_repository import (
    InMemoryRunControlRepository,
)
from mission_control.application.execution.service import AdmissionPolicyRegistry
from mission_control.domain.authoring.manifest_lowering import (
    MANIFEST_INPUT_CONTRACT,
    MANIFEST_INVARIANT,
)
from mission_control.domain.policies.contracts import RunRequest, VerifiedRunConfiguration
from mission_control.domain.policies.errors import AdmissionRejected
from tests.unit.run_control.test_run_control import ConfigurationVerifier, request


class ManifestConfigurationVerifier(ConfigurationVerifier):
    async def verify(self, run_request: RunRequest) -> VerifiedRunConfiguration:
        verified = await super().verify(run_request)
        return verified.model_copy(
            update={
                "input_admission_contract": MANIFEST_INPUT_CONTRACT,
                "invariant_refs": frozenset({MANIFEST_INVARIANT}),
            }
        )


def nested_body_request(*evidence: str) -> RunRequest:
    return request(request_id="nested-body").model_copy(
        update={"admission_evidence_refs": evidence}
    )


@pytest.mark.asyncio
async def test_worker_composition_admits_a_manifest_nested_body() -> None:
    worker = compose_worker_run_control_service(
        InMemoryRunControlRepository(),
        ManifestConfigurationVerifier(),
        AdmissionPolicyRegistry(),
    )
    nested = nested_body_request("manifest:sha256:" + "a" * 64, "nested-body:sha256:" + "b" * 64)

    verified = await worker.verify_admission(nested)
    assert verified.input_admission_contract == MANIFEST_INPUT_CONTRACT
    decision = await worker.admit(nested)
    assert decision.run_id is not None


@pytest.mark.asyncio
async def test_worker_composition_keeps_the_manifest_contract_closed() -> None:
    worker = compose_worker_run_control_service(
        InMemoryRunControlRepository(),
        ManifestConfigurationVerifier(),
        AdmissionPolicyRegistry(),
    )
    with pytest.raises(AdmissionRejected, match="Mission Manifest submit"):
        await worker.verify_admission(nested_body_request("nested-body:sha256:" + "b" * 64))


def test_worker_composition_accepts_a_registry_that_already_has_the_contract() -> None:
    from mission_control.application.authoring.manifest_submit import (
        register_manifest_admission_policies,
    )

    policies = AdmissionPolicyRegistry()
    register_manifest_admission_policies(policies)
    compose_worker_run_control_service(
        InMemoryRunControlRepository(), ManifestConfigurationVerifier(), policies
    )
