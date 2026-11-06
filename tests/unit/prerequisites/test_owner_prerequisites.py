"""MO-20: `mc.owner_prerequisite.v1`, the stored record's state rules and the freshness
assessment a preflight applies before launch (SPEC-05 section 1)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from mission_control.domain.prerequisites import (
    BLOCKING_STANDINGS,
    EvidenceRefused,
    Freshness,
    GeneratedContent,
    GeneratedFrom,
    OwnerPrerequisite,
    OwnerPrerequisiteRecord,
    PrerequisiteEvidence,
    PrerequisiteStanding,
    PrerequisiteState,
    VerificationMethod,
    assess_prerequisite,
)

AT = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
KIT = "envkit.python-uv-node@1#sha256:" + "a" * 64
POLICY = "sha256:" + "b" * 64
SETUP = "generated/claude-cloud/envkit-python-uv-node-1/setup.sh"


def _prerequisite(**changes: Any) -> OwnerPrerequisite:
    fields: dict[str, Any] = {
        "id": "claude_cloud.environment.envkit-python-uv-node-1",
        "provider": "anthropic",
        "scope": "environment",
        "title": "Create the Claude Code cloud environment",
        "why": "Claude cloud environments are UI-only.",
        "blocks": [{"lane": "claude_cloud"}],
        "steps": ["Open claude.ai/code.", {"paste": "setup_script", "content_ref": SETUP}],
        "verify": {"method": "probe_mission", "probe": "missions/probes/claude-cloud-env@1"},
        "freshness": {
            "revalidate_after": timedelta(days=30),
            "on_change_of": ["kit_digest", "policy_digest"],
        },
        "generated_from": {"kit": KIT, "policy_digest": POLICY},
        "generated": [GeneratedContent.render(SETUP, "text/x-shellscript", "set -eu\n")],
        **changes,
    }
    return OwnerPrerequisite.model_validate(fields)


def _login(**freshness: Any) -> OwnerPrerequisite:
    return OwnerPrerequisite.model_validate(
        {
            "id": "claude_cloud.host.auth_login",
            "provider": "anthropic",
            "scope": "host",
            "title": "claude auth login",
            "why": "The refresh grant is capped at 30 days.",
            "blocks": [{"lane": "claude_cloud"}],
            "steps": ["Run claude auth login."],
            "verify": {"method": "file_check", "probe": "claude auth status"},
            "freshness": {"expires_after": timedelta(days=30), **freshness},
        }
    )


def _evidence(
    prerequisite: OwnerPrerequisite,
    method: VerificationMethod = VerificationMethod.PROBE_MISSION,
    **changes: Any,
) -> PrerequisiteEvidence:
    fields: dict[str, Any] = {
        "method": method,
        "definition_digest": prerequisite.digest,
        "recorded_at": AT,
        "evidence_ref": None if method is VerificationMethod.ATTESTATION else "signal:probe-1",
        **changes,
    }
    return PrerequisiteEvidence.model_validate(fields)


# --------------------------------------------------------------------------- definition


def test_a_definition_round_trips_with_its_content_digests() -> None:
    prerequisite = _prerequisite()
    again = OwnerPrerequisite.model_validate_json(prerequisite.model_dump_json())
    assert again == prerequisite and again.digest == prerequisite.digest
    assert prerequisite.content_digests == {SETUP: prerequisite.content(SETUP).digest}
    assert prerequisite.content(SETUP).digest.startswith("sha256:")


def test_generated_content_carries_the_digest_of_its_exact_text() -> None:
    item = GeneratedContent.render(SETUP, "text/x-shellscript", "set -eu\n")
    with pytest.raises(ValidationError, match="digest does not match"):
        GeneratedContent(ref=SETUP, media_type="text/plain", content="set -e\n", digest=item.digest)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"generated": []}, "steps paste content that is not generated"),
        (
            {"steps": ["Open claude.ai/code."]},
            "generated content no step pastes",
        ),
        ({"generated_from": None}, "generated_from"),
        ({"steps": ["  "]}, "not blank"),
        ({"verify": {"method": "api_probe"}}, "names its probe"),
        ({"id": "Claude.environment"}, "id"),
    ],
)
def test_a_definition_refuses_inconsistent_content(changes: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        _prerequisite(**changes)


def test_freshness_durations_are_positive() -> None:
    with pytest.raises(ValidationError, match="positive"):
        Freshness(expires_after=timedelta(0))
    with pytest.raises(ValidationError, match="repeat"):
        Freshness(on_change_of=("kit_digest", "kit_digest"))


# --------------------------------------------------------------------------- record


def test_state_follows_the_evidence_method() -> None:
    prerequisite = _prerequisite()
    record = OwnerPrerequisiteRecord.of(prerequisite)
    assert record.state is PrerequisiteState.UNMET and record.evidence is None
    attested = record.evidenced(_evidence(prerequisite, VerificationMethod.ATTESTATION))
    assert attested.state is PrerequisiteState.ATTESTED
    verified = attested.evidenced(_evidence(prerequisite))
    assert verified.state is PrerequisiteState.VERIFIED
    assert OwnerPrerequisiteRecord.model_validate_json(verified.model_dump_json()) == verified
    with pytest.raises(ValidationError, match="matching evidence"):
        OwnerPrerequisiteRecord.model_validate({**verified.model_dump(), "state": "attested"})
    with pytest.raises(ValidationError, match="definition_digest does not match"):
        OwnerPrerequisiteRecord(prerequisite=prerequisite, definition_digest=POLICY)


def test_verified_evidence_cites_its_proof_and_expires_after_it_is_recorded() -> None:
    prerequisite = _prerequisite()
    with pytest.raises(ValidationError, match="evidence_ref"):
        _evidence(prerequisite, evidence_ref=None)
    with pytest.raises(ValidationError, match="expires after"):
        _evidence(prerequisite, expires_at=AT)
    with pytest.raises(ValidationError, match="value"):
        _evidence(prerequisite, VerificationMethod.ATTESTATION, value="sk live value")


def test_evidence_for_another_definition_is_refused() -> None:
    record = OwnerPrerequisiteRecord.of(_prerequisite())
    other = _prerequisite(title="Another title")
    with pytest.raises(EvidenceRefused, match="stored definition"):
        record.evidenced(_evidence(other))


def test_re_registering_a_changed_definition_keeps_the_evidence_which_drifts() -> None:
    prerequisite = _prerequisite()
    verified = OwnerPrerequisiteRecord.of(prerequisite).evidenced(_evidence(prerequisite))
    assert verified.registered(prerequisite) is verified
    content = GeneratedContent.render(SETUP, "text/x-shellscript", "set -euo pipefail\n")
    changed = verified.registered(_prerequisite(generated=[content]))
    assert changed.evidence == verified.evidence
    assert changed.definition_digest != verified.definition_digest
    assessment = assess_prerequisite(changed, now=AT)
    assert assessment.standing is PrerequisiteStanding.DRIFTED and assessment.blocking
    with pytest.raises(ValueError, match="is not"):
        verified.registered(_prerequisite(id="claude_cloud.environment.other"))


# --------------------------------------------------------------------------- assessment


def test_an_unproven_prerequisite_is_unmet_and_blocks() -> None:
    assessment = assess_prerequisite(OwnerPrerequisiteRecord.of(_prerequisite()), now=AT)
    assert assessment.standing is PrerequisiteStanding.UNMET and assessment.blocking
    assert {
        PrerequisiteStanding.UNMET,
        PrerequisiteStanding.DRIFTED,
        PrerequisiteStanding.EXPIRED,
    } == BLOCKING_STANDINGS


def test_an_expiring_credential_is_flagged_before_it_expires_and_blocks_after() -> None:
    login = _login()
    expires = AT + timedelta(days=30)
    record = OwnerPrerequisiteRecord.of(login).evidenced(
        _evidence(login, VerificationMethod.FILE_CHECK, expires_at=expires)
    )
    fresh = assess_prerequisite(record, now=AT + timedelta(days=22, hours=23))
    assert fresh.standing is PrerequisiteStanding.MET and not fresh.blocking
    expiring = assess_prerequisite(record, now=AT + timedelta(days=23))
    assert expiring.standing is PrerequisiteStanding.EXPIRING and not expiring.blocking
    assert expiring.expires_at == expires and str(expires) in expiring.reasons[0]
    expired = assess_prerequisite(record, now=expires)
    assert expired.standing is PrerequisiteStanding.EXPIRED and expired.blocking
    # The warning window is the prerequisite's own.
    early = _login(warn_before=timedelta(days=10))
    warned = OwnerPrerequisiteRecord.of(early).evidenced(
        _evidence(early, VerificationMethod.FILE_CHECK, expires_at=expires)
    )
    assert assess_prerequisite(warned, now=AT + timedelta(days=21)).standing is (
        PrerequisiteStanding.EXPIRING
    )


def test_revalidation_makes_evidence_stale_without_blocking() -> None:
    prerequisite = _prerequisite()
    record = OwnerPrerequisiteRecord.of(prerequisite).evidenced(_evidence(prerequisite))
    assert assess_prerequisite(record, now=AT + timedelta(days=29)).standing is (
        PrerequisiteStanding.MET
    )
    stale = assess_prerequisite(record, now=AT + timedelta(days=30))
    assert stale.standing is PrerequisiteStanding.STALE and not stale.blocking


def test_a_binding_with_another_kit_or_policy_drifts_the_generated_content() -> None:
    prerequisite = _prerequisite()
    record = OwnerPrerequisiteRecord.of(prerequisite).evidenced(_evidence(prerequisite))
    same = GeneratedFrom(kit=KIT, policy_digest=POLICY)
    assert assess_prerequisite(record, now=AT, bound=same).standing is PrerequisiteStanding.MET
    other_kit = GeneratedFrom(kit=KIT.replace("a" * 64, "c" * 64), policy_digest=POLICY)
    drifted = assess_prerequisite(record, now=AT, bound=other_kit)
    assert drifted.standing is PrerequisiteStanding.DRIFTED and drifted.blocking
    assert drifted.reasons == (f"rendered from kit {KIT}; the binding pins {other_kit.kit}",)
    other_policy = GeneratedFrom(kit=KIT, policy_digest="sha256:" + "d" * 64)
    assert "network policy" in assess_prerequisite(record, now=AT, bound=other_policy).reasons[0]
    # Only the inputs the prerequisite names make it drift.
    kit_only = _prerequisite(freshness={"on_change_of": ["kit_digest"]})
    kit_record = OwnerPrerequisiteRecord.of(kit_only).evidenced(_evidence(kit_only))
    assert assess_prerequisite(kit_record, now=AT, bound=other_policy).standing is (
        PrerequisiteStanding.MET
    )
