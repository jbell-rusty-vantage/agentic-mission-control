"""Server-owned readonly source proof before any hosted vault publication."""

from datetime import UTC, datetime
from urllib.parse import urlparse

import asyncpg

from mission_control.adapters.postgres.prerequisites import PostgresOwnerPrerequisiteRepository
from mission_control.application.prerequisites.probes import OwnerProbeConfiguration
from mission_control.application.prerequisites.setup import ProbeUnavailable
from mission_control.application.secrets.references import BrokerRef
from mission_control.bootstrap.settings import Settings
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.execution.contracts import OperationExecutionRequest
from mission_control.domain.prerequisites import (
    PrerequisiteStanding,
    VerificationMethod,
    assess_prerequisite,
)


class HostedReadonlyVerifier:
    def __init__(self, settings: Settings, pool: asyncpg.Pool):
        self._settings, self._repository = settings, PostgresOwnerPrerequisiteRepository(pool)

    async def verify_hosted_readonly(
        self, operation: OperationExecutionRequest, refs: tuple[BrokerRef, ...]
    ) -> None:
        if not refs:
            return
        try:
            await self._verify(operation, refs)
        except ProbeUnavailable:
            raise
        except Exception as error:
            raise ProbeUnavailable(
                f"readonly source proof unavailable ({type(error).__name__})"
            ) from None

    async def _verify(
        self, operation: OperationExecutionRequest, refs: tuple[BrokerRef, ...]
    ) -> None:
        provider = ProviderExecutionBinding.carried_by(operation)
        path = self._settings.mission_control_owner_probes_path
        if provider is None or path is None or provider.repo_url is None:
            raise ProbeUnavailable(
                "hosted repository credentials need exact reviewed repository and source evidence"
            )
        url = provider.repo_url
        if url.startswith("git@github.com:"):
            repository = url.removeprefix("git@github.com:").removesuffix(".git")
        else:
            parsed = urlparse(url)
            if (
                parsed.hostname != "github.com"
                or parsed.scheme != "https"
                or parsed.username
                or parsed.query
                or parsed.fragment
            ):
                raise ProbeUnavailable(
                    "readonly repository proof requires an exact GitHub repository"
                )
            repository = parsed.path.strip("/").removesuffix(".git")
        configuration = OwnerProbeConfiguration.load(path)
        for ref in refs:
            if ref.scheme == "mint" or ref.key in {"ANTHROPIC_API_KEY", "OPENAI_API_KEY"}:
                raise ProbeUnavailable(
                    "provider organization credentials cannot enter a hosted repository vault"
                )
            matched = False
            for binding in configuration.bindings:
                source_refs = tuple(
                    BrokerRef(
                        scheme="environment" if item.provider == "environment" else "store",
                        key=item.key,
                    )
                    for item in binding.credentials
                )
                if binding.operation != "github_readonly_repository" or source_refs != (ref,):
                    continue
                if (
                    binding.request_scope != operation.request_scope
                    or binding.binding_digest != operation.effective_configuration_digest
                    or binding.provider_binding_digest != provider.binding_digest
                ):
                    continue
                if (
                    binding.auth != provider.auth
                    or binding.repo_url != url
                    or binding.repo_ref != provider.repo_ref
                    or binding.repo_commit != provider.repo_commit
                    or (binding.repository or "").lower() != repository.lower()
                ):
                    continue
                record = await self._repository.get(
                    operation.request_scope, binding.prerequisite_id
                )
                if (
                    record is None
                    or record.definition_digest != binding.definition_digest
                    or record.evidence is None
                ):
                    continue
                expected = f"api-probe:github_readonly_repository:binding:{sha256_digest(binding)}:"
                if record.evidence.method != VerificationMethod.API_PROBE or not (
                    record.evidence.evidence_ref or ""
                ).startswith(expected):
                    continue
                if assess_prerequisite(record, now=datetime.now(UTC)).standing not in {
                    PrerequisiteStanding.MET,
                    PrerequisiteStanding.EXPIRING,
                }:
                    continue
                matched = True
                break
            if not matched:
                raise ProbeUnavailable(
                    "no fresh verified read-only repository proof matches this exact "
                    "source and sealed binding"
                )
