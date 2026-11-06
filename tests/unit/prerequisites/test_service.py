"""MO-20: the Owner Prerequisite store's use cases over the in-memory repository: register
what a binding needs, attest and verify, and flag expiring credentials before launch (SPEC-05
sections 1 and 4). The PostgreSQL repository runs the same flows in
`tests/integration/postgres/test_owner_prerequisites.py`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from mission_control.application.prerequisites import (
    InMemoryOwnerPrerequisiteRepository,
    OwnerPrerequisiteService,
    UnknownPrerequisite,
)
from mission_control.application.prerequisites.generators import CLAUDE_LOGIN_LIFETIME
from mission_control.domain.prerequisites import (
    EvidenceRefused,
    PrerequisiteStanding,
    PrerequisiteState,
    VerificationMethod,
)
from tests.fixtures.owner_prerequisites import inputs

SCOPE = "installation:fixture"
AT = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
ENVIRONMENT = "claude_cloud.environment.envkit-python-uv-node-1"
LOGIN = "claude_cloud.host.auth_login"


class Clock:
    def __init__(self) -> None:
        self.now = AT

    def __call__(self) -> datetime:
        return self.now


def _service() -> tuple[OwnerPrerequisiteService, Clock, InMemoryOwnerPrerequisiteRepository]:
    clock = Clock()
    repository = InMemoryOwnerPrerequisiteRepository()
    return OwnerPrerequisiteService(repository, clock=clock), clock, repository


async def test_a_fresh_installation_has_every_generated_prerequisite_unmet() -> None:
    service, _clock, repository = _service()
    assessments = await service.register_for_binding(SCOPE, "claude_cloud", inputs())
    assert {item.prerequisite_id: item.standing for item in assessments} == {
        ENVIRONMENT: PrerequisiteStanding.UNMET,
        LOGIN: PrerequisiteStanding.UNMET,
    }
    assert all(item.blocking for item in assessments)
    stored = await repository.get(SCOPE, ENVIRONMENT)
    assert stored is not None and stored.state is PrerequisiteState.UNMET
    # Registering the same binding again stores nothing new.
    assert await service.register_for_binding(SCOPE, "claude_cloud", inputs()) == assessments
    assert await repository.get(SCOPE, ENVIRONMENT) == stored
    assert await repository.list("installation:other") == ()


async def test_attestation_and_verification_meet_the_prerequisites() -> None:
    service, _clock, _repository = _service()
    await service.register_for_binding(SCOPE, "claude_cloud", inputs())
    attested = await service.attest(SCOPE, ENVIRONMENT, value="env_01ABCdef")
    assert attested.state is PrerequisiteState.ATTESTED
    assert attested.evidence is not None and attested.evidence.value == "env_01ABCdef"
    verified = await service.verify(
        SCOPE,
        ENVIRONMENT,
        method=VerificationMethod.PROBE_MISSION,
        evidence_ref="signal:env.prepared/probe-1",
    )
    assert verified.state is PrerequisiteState.VERIFIED
    (assessment,) = await service.assess(SCOPE, prerequisite_ids=[ENVIRONMENT])
    assert assessment.standing is PrerequisiteStanding.MET and not assessment.blocking
    assert assessment.method is VerificationMethod.PROBE_MISSION


async def test_the_30_day_login_is_flagged_before_it_expires_and_blocks_after() -> None:
    service, clock, _repository = _service()
    await service.register_for_binding(SCOPE, "claude_cloud", inputs())
    verified = await service.verify(
        SCOPE, LOGIN, method=VerificationMethod.FILE_CHECK, evidence_ref="file:~/.claude"
    )
    assert verified.evidence is not None
    assert verified.evidence.expires_at == AT + CLAUDE_LOGIN_LIFETIME

    clock.now = AT + timedelta(days=22)
    (fresh,) = await service.assess(SCOPE, prerequisite_ids=[LOGIN])
    assert fresh.standing is PrerequisiteStanding.MET
    clock.now = AT + timedelta(days=24)
    (expiring,) = await service.assess(SCOPE, prerequisite_ids=[LOGIN])
    assert expiring.standing is PrerequisiteStanding.EXPIRING and not expiring.blocking
    clock.now = AT + timedelta(days=30)
    (expired,) = await service.assess(SCOPE, prerequisite_ids=[LOGIN])
    assert expired.standing is PrerequisiteStanding.EXPIRED and expired.blocking

    # Signing in again restarts the lifetime; a credential's own earlier expiry wins.
    renewed = await service.verify(
        SCOPE,
        LOGIN,
        method=VerificationMethod.FILE_CHECK,
        evidence_ref="file:~/.claude",
        expires_at=clock.now + timedelta(days=3),
    )
    assert renewed.evidence is not None
    assert renewed.evidence.expires_at == clock.now + timedelta(days=3)
    (soon,) = await service.assess(SCOPE, prerequisite_ids=[LOGIN])
    assert soon.standing is PrerequisiteStanding.EXPIRING


async def test_a_changed_binding_drifts_what_the_owner_already_did() -> None:
    service, _clock, _repository = _service()
    await service.register_for_binding(SCOPE, "claude_cloud", inputs())
    await service.verify(
        SCOPE, ENVIRONMENT, method=VerificationMethod.PROBE_MISSION, evidence_ref="signal:p-1"
    )
    # Preflight for a mission bound to a republished kit, before anything is regenerated.
    republished = inputs(system_packages=["git"])
    (stale,) = await service.assess(
        SCOPE, prerequisite_ids=[ENVIRONMENT], bound=republished.generated_from
    )
    assert stale.standing is PrerequisiteStanding.DRIFTED and stale.blocking
    # Registering that binding replaces the generated content and keeps the evidence, which
    # now proves an older definition: the owner must repeat the steps.
    by_id = {
        item.prerequisite_id: item
        for item in await service.register_for_binding(SCOPE, "claude_cloud", republished)
    }
    assert by_id[ENVIRONMENT].standing is PrerequisiteStanding.DRIFTED
    assert by_id[LOGIN].standing is PrerequisiteStanding.UNMET
    await service.verify(
        SCOPE, ENVIRONMENT, method=VerificationMethod.PROBE_MISSION, evidence_ref="signal:p-2"
    )
    (met,) = await service.assess(
        SCOPE, prerequisite_ids=[ENVIRONMENT], bound=republished.generated_from
    )
    assert met.standing is PrerequisiteStanding.MET


async def test_evidence_for_steps_the_owner_did_not_see_is_refused() -> None:
    service, _clock, repository = _service()
    await service.register_for_binding(SCOPE, "claude_cloud", inputs())
    before = await repository.get(SCOPE, ENVIRONMENT)
    assert before is not None
    await service.register_for_binding(SCOPE, "claude_cloud", inputs(system_packages=["git"]))
    with pytest.raises(EvidenceRefused):
        await service.attest(
            SCOPE, ENVIRONMENT, value="env_01", definition_digest=before.definition_digest
        )
    after = await repository.get(SCOPE, ENVIRONMENT)
    assert after is not None and after.state is PrerequisiteState.UNMET


async def test_unknown_prerequisites_and_attestation_as_verification_are_refused() -> None:
    service, _clock, _repository = _service()
    with pytest.raises(UnknownPrerequisite):
        await service.attest(SCOPE, ENVIRONMENT)
    with pytest.raises(UnknownPrerequisite):
        await service.assess(SCOPE, prerequisite_ids=[ENVIRONMENT])
    await service.register_for_binding(SCOPE, "claude_cloud", inputs())
    with pytest.raises(ValueError, match="use attest"):
        await service.verify(
            SCOPE, ENVIRONMENT, method=VerificationMethod.ATTESTATION, evidence_ref="owner"
        )
    assert [item.prerequisite_id for item in await service.assess(SCOPE)] == [ENVIRONMENT, LOGIN]
