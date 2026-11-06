"""The Owner Prerequisite store and its use cases (materialization-observation SPEC-05; ADR-0047).

Per installation scope the store keeps each prerequisite's current definition, its state and
the evidence that set it. :class:`OwnerPrerequisiteService`

* **registers** what a lane's binding needs: it generates the prerequisites and their
  paste-ready content (``generators``), writes each definition (a changed definition replaces
  the stored one and keeps its evidence, which then drifts) and assesses them against the
  binding;
* records **attestations** (the weakest evidence, state ``attested``) and **verifications**
  (``api_probe``, ``probe_mission`` or ``file_check``, state ``verified``), each citing the
  definition it proved and, for a credential, when it expires;
* **assesses** the stored records at the current time, so an expiring credential is flagged
  before launch and an expired one blocks it (SPEC-05 section 1 "Freshness").

Preflight, the launch refusal and the setup wizard (MO-21, MO-22) consume this service.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Protocol

from mission_control.application.prerequisites.generators import (
    GenerationInputs,
    generate_owner_prerequisites,
)
from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.prerequisites import (
    GeneratedFrom,
    OwnerPrerequisite,
    OwnerPrerequisiteRecord,
    PrerequisiteAssessment,
    PrerequisiteEvidence,
    VerificationMethod,
    assess_prerequisite,
)


class UnknownPrerequisite(LookupError):
    def __init__(self, prerequisite_id: str) -> None:
        super().__init__(f"no owner prerequisite {prerequisite_id} is registered")
        self.prerequisite_id = prerequisite_id


class OwnerPrerequisiteRepository(Protocol):
    async def register(
        self, request_scope: str, prerequisite: OwnerPrerequisite
    ) -> OwnerPrerequisiteRecord:
        """Insert an unmet record, or make ``prerequisite`` the stored record's definition
        (``OwnerPrerequisiteRecord.registered``); returns what is stored."""
        ...

    async def record_evidence(
        self, request_scope: str, prerequisite_id: str, evidence: PrerequisiteEvidence
    ) -> OwnerPrerequisiteRecord:
        """Set the stored record's evidence (``OwnerPrerequisiteRecord.evidenced``); raises
        :class:`UnknownPrerequisite` or ``EvidenceRefused``."""
        ...

    async def get(
        self, request_scope: str, prerequisite_id: str
    ) -> OwnerPrerequisiteRecord | None: ...

    async def list(self, request_scope: str) -> tuple[OwnerPrerequisiteRecord, ...]: ...


class InMemoryOwnerPrerequisiteRepository:
    """The repository port over a dict (unit tests and local composition)."""

    def __init__(self) -> None:
        self.records: dict[tuple[str, str], OwnerPrerequisiteRecord] = {}

    async def register(
        self, request_scope: str, prerequisite: OwnerPrerequisite
    ) -> OwnerPrerequisiteRecord:
        key = (request_scope, prerequisite.id)
        stored = self.records.get(key)
        record = (
            OwnerPrerequisiteRecord.of(prerequisite)
            if stored is None
            else stored.registered(prerequisite)
        )
        self.records[key] = record
        return record

    async def record_evidence(
        self, request_scope: str, prerequisite_id: str, evidence: PrerequisiteEvidence
    ) -> OwnerPrerequisiteRecord:
        key = (request_scope, prerequisite_id)
        stored = self.records.get(key)
        if stored is None:
            raise UnknownPrerequisite(prerequisite_id)
        record = stored.evidenced(evidence)
        self.records[key] = record
        return record

    async def get(self, request_scope: str, prerequisite_id: str) -> OwnerPrerequisiteRecord | None:
        return self.records.get((request_scope, prerequisite_id))

    async def list(self, request_scope: str) -> tuple[OwnerPrerequisiteRecord, ...]:
        return tuple(
            record
            for (scope, _id), record in sorted(self.records.items())
            if scope == request_scope
        )


def _utc_now() -> datetime:
    return datetime.now(UTC)


class OwnerPrerequisiteService:
    def __init__(
        self,
        repository: OwnerPrerequisiteRepository,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._repository = repository
        self._clock = clock

    async def register_for_binding(
        self,
        request_scope: str,
        profile: LaneProfile | str,
        inputs: GenerationInputs,
        *,
        secret_values: Iterable[str] = (),
    ) -> tuple[PrerequisiteAssessment, ...]:
        """Generate and store what ``profile`` needs for this binding; assess each record
        against it. ``secret_values`` are values the caller knows to be secret, which no
        generated item may contain."""

        prerequisites = generate_owner_prerequisites(profile, inputs, secret_values=secret_values)
        records = [
            await self._repository.register(request_scope, prerequisite)
            for prerequisite in prerequisites
        ]
        now = self._clock()
        return tuple(
            assess_prerequisite(record, now=now, bound=inputs.generated_from) for record in records
        )

    async def attest(
        self,
        request_scope: str,
        prerequisite_id: str,
        *,
        value: str | None = None,
        evidence_ref: str | None = None,
        expires_at: datetime | None = None,
        definition_digest: str | None = None,
    ) -> OwnerPrerequisiteRecord:
        """The owner says it is done (``attested``); ``value`` is the identifier they copied,
        such as an ``env_...`` id. ``definition_digest`` names the steps they followed; it is
        refused when the stored definition has changed since."""

        return await self._record(
            request_scope,
            prerequisite_id,
            VerificationMethod.ATTESTATION,
            evidence_ref=evidence_ref,
            value=value,
            expires_at=expires_at,
            definition_digest=definition_digest,
        )

    async def verify(
        self,
        request_scope: str,
        prerequisite_id: str,
        *,
        method: VerificationMethod,
        evidence_ref: str,
        expires_at: datetime | None = None,
        definition_digest: str | None = None,
    ) -> OwnerPrerequisiteRecord:
        """A probe proved it (``verified``). ``expires_at`` is a credential's own expiry when
        the probe read one; the prerequisite's ``expires_after`` bounds it either way."""

        if not method.verifies:
            raise ValueError("an attestation does not verify a prerequisite; use attest")
        return await self._record(
            request_scope,
            prerequisite_id,
            method,
            evidence_ref=evidence_ref,
            expires_at=expires_at,
            definition_digest=definition_digest,
        )

    async def assess(
        self,
        request_scope: str,
        *,
        prerequisite_ids: Iterable[str] | None = None,
        bound: GeneratedFrom | None = None,
    ) -> tuple[PrerequisiteAssessment, ...]:
        """The stored records' standings now; an id that was never registered is unmet."""

        now = self._clock()
        records = {record.id: record for record in await self._repository.list(request_scope)}
        wanted = sorted(records) if prerequisite_ids is None else list(prerequisite_ids)
        missing = [item for item in wanted if item not in records]
        if missing:
            raise UnknownPrerequisite(", ".join(missing))
        return tuple(assess_prerequisite(records[item], now=now, bound=bound) for item in wanted)

    async def _record(
        self,
        request_scope: str,
        prerequisite_id: str,
        method: VerificationMethod,
        *,
        evidence_ref: str | None,
        value: str | None = None,
        expires_at: datetime | None,
        definition_digest: str | None,
    ) -> OwnerPrerequisiteRecord:
        stored = await self._repository.get(request_scope, prerequisite_id)
        if stored is None:
            raise UnknownPrerequisite(prerequisite_id)
        now = self._clock()
        lifetime = stored.prerequisite.freshness.expires_after
        bounds = [
            item for item in (expires_at, None if lifetime is None else now + lifetime) if item
        ]
        evidence = PrerequisiteEvidence(
            method=method,
            definition_digest=definition_digest or stored.definition_digest,
            recorded_at=now,
            evidence_ref=evidence_ref,
            value=value,
            expires_at=min(bounds) if bounds else None,
        )
        return await self._repository.record_evidence(request_scope, prerequisite_id, evidence)


__all__ = [
    "InMemoryOwnerPrerequisiteRepository",
    "OwnerPrerequisiteRepository",
    "OwnerPrerequisiteService",
    "UnknownPrerequisite",
]
