"""Owner setup and trusted verification; public requests cannot supply probe success."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from mission_control.application.prerequisites.catalog import account_prerequisites
from mission_control.application.prerequisites.preflight import PreflightItem
from mission_control.application.prerequisites.service import (
    OwnerPrerequisiteRepository,
    OwnerPrerequisiteService,
    UnknownPrerequisite,
)
from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.prerequisites import (
    EvidenceRefused,
    OwnerPrerequisiteRecord,
    VerificationMethod,
    assess_prerequisite,
)
from mission_control.domain.prerequisites.owner_prerequisites import ATTESTED_VALUE_PATTERN


class SetupContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AttestRequest(SetupContract):
    definition_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    value: str | None = Field(default=None, pattern=ATTESTED_VALUE_PATTERN)
    expires_at: AwareDatetime | None = None


class VerifyRequest(SetupContract):
    definition_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class ProbeResult(SetupContract):
    method: VerificationMethod
    evidence_ref: str = Field(min_length=1, max_length=1024)
    expires_at: AwareDatetime | None = None


class PrerequisiteProbePort(Protocol):
    async def verify(self, request_scope: str, record: OwnerPrerequisiteRecord) -> ProbeResult: ...


class ProbeUnavailable(RuntimeError):
    code = "probe_unavailable"


class SetupPlan(SetupContract):
    schema_version: Literal["mc.owner_setup.v1"] = "mc.owner_setup.v1"
    target: str
    items: tuple[PreflightItem, ...]
    ready: bool
    blockers: tuple[str, ...] = ()


def selected_profiles(target: str) -> tuple[LaneProfile, ...]:
    providers = {
        "cursor": (LaneProfile.CURSOR_CLOUD, LaneProfile.CURSOR_LOCAL),
        "anthropic": (
            LaneProfile.CLAUDE_MANAGED,
            LaneProfile.CLAUDE_CLOUD,
            LaneProfile.CLAUDE_AGENT_SDK,
        ),
        "openai": (LaneProfile.CODEX_AGENTS, LaneProfile.CODEX_CLOUD, LaneProfile.CODEX),
    }
    if target in providers:
        return providers[target]
    profile = LaneProfile(target)
    if profile is LaneProfile.DEEP_AGENTS:
        raise ValueError("deep_agents has no provider owner setup")
    return (profile,)


class OwnerSetupService:
    def __init__(
        self,
        repository: OwnerPrerequisiteRepository,
        *,
        probes: PrerequisiteProbePort | None = None,
    ) -> None:
        self.repository = repository
        self.probes = probes
        self._service = OwnerPrerequisiteService(repository)

    async def plan(self, request_scope: str, target: str) -> SetupPlan:
        items = []
        for profile in selected_profiles(target):
            for prerequisite in account_prerequisites(profile):
                record = await self.repository.register(request_scope, prerequisite)
                items.append(
                    PreflightItem(
                        prerequisite=prerequisite,
                        assessment=assess_prerequisite(record, now=datetime.now(UTC)),
                    )
                )
        return SetupPlan(
            target=target,
            items=tuple(items),
            ready=not any(item.assessment.blocking for item in items),
        )

    async def attest(
        self, scope: str, prerequisite_id: str, request: AttestRequest, *, actor_id: str
    ) -> OwnerPrerequisiteRecord:
        # Only public environment identifiers are accepted, never credentials or arbitrary text.
        if request.value and request.value.lower().startswith(
            ("sk-", "sk_", "ghp_", "github_pat_", "bearer", "eyj", "mcsig_")
        ):
            raise ValueError(
                "use an environment identifier; store credentials in the Secret Broker"
            )
        return await self._service.attest(
            scope,
            prerequisite_id,
            value=request.value,
            evidence_ref=f"owner:{actor_id}",
            expires_at=request.expires_at,
            definition_digest=request.definition_digest,
        )

    async def verify(
        self, scope: str, prerequisite_id: str, definition_digest: str
    ) -> OwnerPrerequisiteRecord:
        record = await self.repository.get(scope, prerequisite_id)
        if record is None:
            raise UnknownPrerequisite(prerequisite_id)
        if record.definition_digest != definition_digest:
            raise EvidenceRefused("setup changed; refresh the plan before verifying")
        if self.probes is None:
            raise ProbeUnavailable(
                "no trusted verification probe is configured for this installation"
            )
        proof = await self.probes.verify(scope, record)
        if not proof.method.verifies:
            raise EvidenceRefused("a probe cannot return an attestation")
        return await self._service.verify(
            scope,
            prerequisite_id,
            method=proof.method,
            evidence_ref=proof.evidence_ref,
            expires_at=proof.expires_at,
            definition_digest=definition_digest,
        )
