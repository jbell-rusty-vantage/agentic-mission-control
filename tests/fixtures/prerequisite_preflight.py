"""Prerequisite inputs for disposable stacks with deterministic provider doubles.

Installer readiness still reads the real restricted PostgreSQL installation. Synthetic
owner evidence is opt-in, persisted in that disposable database, and explicitly labelled
as fixture evidence; it cannot qualify a live provider or escape this test composition.
"""

from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
from tests.fixtures.db_env import db_env_name
from tests.fixtures.mission_control_common_db import COMPONENT_VERSION, CommonDatabase

from mission_control.application.installations.registry import ApplicationBinding
from mission_control.application.prerequisites.preflight import PrerequisitePreflight
from mission_control.application.prerequisites.service import OwnerPrerequisiteRepository
from mission_control.bootstrap import manifests, runtime_control
from mission_control.bootstrap.prerequisites import compose_prerequisite_preflight
from mission_control.bootstrap.settings import Settings
from mission_control.domain.prerequisites import (
    OwnerPrerequisite,
    OwnerPrerequisiteRecord,
    PrerequisiteEvidence,
)


class DeterministicProviderEvidence:
    def __init__(self, repository: OwnerPrerequisiteRepository) -> None:
        self.repository = repository

    async def register(
        self, request_scope: str, prerequisite: OwnerPrerequisite
    ) -> OwnerPrerequisiteRecord:
        supported = {"claude_agent_sdk", "codex", "cursor_local", "cursor_cloud"}
        if not any(block.lane.value in supported for block in prerequisite.blocks):
            raise AssertionError(f"no deterministic owner fixture for {prerequisite.id}")
        record = await self.repository.register(request_scope, prerequisite)
        now = datetime.now(UTC)
        return await self.repository.record_evidence(
            request_scope,
            prerequisite.id,
            PrerequisiteEvidence(
                method=prerequisite.verify.method,
                definition_digest=record.definition_digest,
                recorded_at=now,
                expires_at=now + timedelta(days=30),
                evidence_ref=f"fixture:deterministic-provider/{prerequisite.id}",
            ),
        )

    async def record_evidence(
        self, request_scope: str, prerequisite_id: str, evidence: PrerequisiteEvidence
    ) -> OwnerPrerequisiteRecord:
        return await self.repository.record_evidence(request_scope, prerequisite_id, evidence)

    async def get(self, request_scope: str, prerequisite_id: str) -> OwnerPrerequisiteRecord | None:
        return await self.repository.get(request_scope, prerequisite_id)

    async def list(self, request_scope: str) -> tuple[OwnerPrerequisiteRecord, ...]:
        return await self.repository.list(request_scope)


def bind_disposable_prerequisites(
    monkeypatch: pytest.MonkeyPatch,
    database: CommonDatabase,
    *,
    deterministic_owner_evidence: bool,
    component_version: str = COMPONENT_VERSION,
) -> None:
    installed = ApplicationBinding.seal(
        application_id=database.application_id,
        installation_id=database.installation_id,
        binding_version="1",
        supabase_project_ref=database.project_ref,
        database_secret_ref=db_env_name(database.application_id, "RUNTIME_DSN"),
        accepted_issuers={"https://local-qualification.invalid"},
        accepted_audiences={"mission-control"},
        required_component_version=component_version,
    )

    def compose(
        pool: asyncpg.Pool,
        *,
        binding: ApplicationBinding | None,
        settings: Settings | None = None,
    ) -> PrerequisitePreflight:
        preflight = compose_prerequisite_preflight(
            pool, binding=binding or installed, settings=settings
        )
        if deterministic_owner_evidence:
            preflight.repository = DeterministicProviderEvidence(preflight.repository)
        return preflight

    # API launch and worker chain continuations use the same installed identity and
    # owner-fixture policy. Every remaining production preflight check stays active.
    monkeypatch.setattr(runtime_control, "compose_prerequisite_preflight", compose)
    monkeypatch.setattr(manifests, "compose_prerequisite_preflight", compose)
