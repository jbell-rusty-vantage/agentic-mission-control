"""Builders, constants and fakes that other test files import.

Moved from tests/unit/prerequisites/test_hosted_readonly.py.
"""

from mission_control.application.prerequisites.probes import OwnerProbeBinding
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from tests.support.lane_bindings import lane_fields
from tests.support.unit.prerequisites.owner_bootstrap import probe_template


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
