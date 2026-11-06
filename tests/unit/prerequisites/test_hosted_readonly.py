"""Exact source/binding evidence and sanitized installation configuration errors."""

from types import SimpleNamespace

import pytest

from mission_control.adapters.prerequisites.probes import ProviderOwnerProbeExecutor
from mission_control.application.prerequisites.catalog import account_prerequisites
from mission_control.application.prerequisites.probes import (
    OwnerProbeBinding,
    OwnerProbeConfiguration,
)
from mission_control.application.prerequisites.service import (
    InMemoryOwnerPrerequisiteRepository,
    OwnerPrerequisiteService,
)
from mission_control.application.prerequisites.setup import ProbeUnavailable
from mission_control.application.secrets.references import BrokerRef
from mission_control.bootstrap.hosted_readonly import HostedReadonlyVerifier
from mission_control.bootstrap.prerequisites import InstallationOwnerProbes
from mission_control.bootstrap.settings import Settings
from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.prerequisites import VerificationMethod
from tests.fixtures.lane_bindings import lane_fields
from tests.unit.prerequisites.test_owner_bootstrap import probe_template


def readonly_template():
    _, operation = probe_template()
    binding = ProviderExecutionBinding.sealed(
        **{
            **ProviderExecutionBinding.carried_by(operation).model_dump(exclude={"binding_digest"}),
            "repo_url": "https://github.com/acme/repo",
            "repo_ref": "main",
            "repo_commit": "a" * 40,
        }
    )
    return operation.model_copy(update={**lane_fields(binding)})


def readonly_binding(operation, prerequisite):
    provider = ProviderExecutionBinding.carried_by(operation)
    return OwnerProbeBinding(
        request_scope=operation.request_scope,
        prerequisite_id=prerequisite.id,
        definition_digest=prerequisite.digest,
        operation="github_readonly_repository",
        credentials=({"provider": "environment", "key": "READONLY_REPO_KEY"},),
        repository="acme/repo",
        binding_digest=operation.effective_configuration_digest,
        provider_binding_digest=provider.binding_digest,
        auth=provider.auth,
        repo_url=provider.repo_url,
        repo_ref=provider.repo_ref,
        repo_commit=provider.repo_commit,
    )


async def test_changed_source_or_sealed_context_never_reuses_verified_readonly_proof(tmp_path):
    operation = readonly_template()
    prerequisite = next(
        item
        for item in account_prerequisites(LaneProfile.CLAUDE_MANAGED)
        if item.id.endswith(".ma4")
    )
    binding = readonly_binding(operation, prerequisite)
    path = tmp_path / "bindings.json"
    path.write_text(
        OwnerProbeConfiguration(bindings=(binding,)).model_dump_json(), encoding="utf-8"
    )
    repository = InMemoryOwnerPrerequisiteRepository()
    await repository.register(operation.request_scope, prerequisite)
    proof = ProviderOwnerProbeExecutor._evidence(binding)
    await OwnerPrerequisiteService(repository).verify(
        operation.request_scope,
        prerequisite.id,
        method=VerificationMethod.API_PROBE,
        evidence_ref=proof.evidence_ref,
    )
    verifier = HostedReadonlyVerifier(
        Settings(_env_file=None, mission_control_owner_probes_path=path), None
    )
    verifier._repository = repository
    await verifier.verify_hosted_readonly(
        operation, (BrokerRef.parse("environment:READONLY_REPO_KEY"),)
    )
    for changed in (
        operation.model_copy(update={"effective_configuration_digest": "sha256:" + "0" * 64}),
        operation.model_copy(update={"request_scope": operation.request_scope + "other"}),
    ):
        with pytest.raises(ProbeUnavailable):
            await verifier.verify_hosted_readonly(
                changed, (BrokerRef.parse("environment:READONLY_REPO_KEY"),)
            )
    with pytest.raises(ProbeUnavailable):
        await verifier.verify_hosted_readonly(
            operation, (BrokerRef.parse("environment:OPENAI_API_KEY"),)
        )
    updated = binding.model_copy(
        update={"credentials": ({"provider": "environment", "key": "OTHER_KEY"},)}
    )
    # A properly parsed new configuration still cannot reuse evidence for the old one.
    updated = OwnerProbeBinding.model_validate(updated.model_dump())
    path.write_text(
        OwnerProbeConfiguration(bindings=(updated,)).model_dump_json(), encoding="utf-8"
    )
    with pytest.raises(ProbeUnavailable):
        await verifier.verify_hosted_readonly(
            operation, (BrokerRef.parse("environment:OTHER_KEY"),)
        )


@pytest.mark.parametrize("exists", [True, False])
async def test_missing_or_malformed_probe_configuration_is_sanitized(tmp_path, exists):
    path = tmp_path / "private.json"
    if exists:
        path.write_text("private-unparseable-value", encoding="utf-8")
    verifier = InstallationOwnerProbes(
        Settings(_env_file=None, mission_control_owner_probes_path=path), None
    )
    with pytest.raises(ProbeUnavailable) as error:
        await verifier.verify("scope", SimpleNamespace())
    assert "private-unparseable-value" not in str(error.value)
    assert str(path) not in str(error.value)
