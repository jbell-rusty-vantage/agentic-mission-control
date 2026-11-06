from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import ValidationError

from mission_control.adapters.prerequisites.codex_native import (
    NativeCodexObservation,
    verify_native_codex,
)
from mission_control.application.prerequisites.catalog import account_prerequisites
from mission_control.application.prerequisites.preflight import scope_prerequisite
from mission_control.application.prerequisites.probes import (
    NativeCodexEvidenceBinding,
    NativeCodexHostIdentity,
    OwnerProbeBinding,
)
from mission_control.application.prerequisites.setup import ProbeUnavailable
from mission_control.domain.authoring.manifest import Environment
from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.prerequisites import (
    OwnerPrerequisiteRecord,
    PrerequisiteEvidence,
    VerificationMethod,
    assess_prerequisite,
)


def prepared(tmp_path: Path):
    identity = NativeCodexHostIdentity.model_validate(
        {
            "workspace": {
                "provider": "local-filesystem-wsl",
                **dict.fromkeys(
                    ("runtime_digest", "image_digest", "package_digest", "environment_digest"),
                    "sha256:" + "a" * 64,
                ),
            },
            "build_commit": "a" * 40,
            "host_profile": "wsl",
            "auth": {"profile": "api", "billing_mode": "api"},
            "cli_version": "0.162.1",
            "cli_sha256": "sha256:" + "b" * 64,
            "attestor": "installation-host-observer",
            "model_id": "gpt-6-luna",
        }
    )
    scoped = {
        "workspace": identity.workspace.model_dump(mode="json"),
        "host_profile": identity.host_profile,
        "auth": identity.auth.model_dump(mode="json", exclude_none=True),
        "cli_version": identity.cli_version,
        "model_id": identity.model_id,
    }
    prerequisite = next(p for p in account_prerequisites(LaneProfile.CODEX) if p.id.endswith(".x4"))
    record = OwnerPrerequisiteRecord.of(
        scope_prerequisite(prerequisite, Environment(), None, native_identity=scoped)
    )
    observation = NativeCodexObservation(
        schema_version="mc.codex_native_observation.v1",
        identity=identity,
        observed_at=datetime.now(UTC),
        cli_version_observed="0.162.1",
        cli_sha256_observed=identity.cli_sha256,
        api_login="apiKey",
        account_read="apiKey",
        credential_store="ephemeral",
        auth_json_created=False,
        thread_started=False,
        turn_started=False,
        remote_model_id="gpt-6-luna",
        remote_metadata_access=True,
    )
    path = tmp_path / "observation.json"
    raw = observation.model_dump_json().encode()
    path.write_bytes(raw)
    binding = OwnerProbeBinding(
        request_scope="scope",
        prerequisite_id=record.prerequisite.id,
        definition_digest=record.definition_digest,
        operation="codex_native_auth",
        native_codex=NativeCodexEvidenceBinding(
            **identity.model_dump(),
            path=path,
            content_sha256="sha256:" + sha256(raw).hexdigest(),
        ),
    )
    return binding, record, observation


def test_pinned_native_observation_proves_exact_host_without_secrets(tmp_path):
    binding, record, observation = prepared(tmp_path)
    result = verify_native_codex(binding, record)
    assert result.observed_at == observation.observed_at
    assert binding.native_codex.content_sha256 in result.evidence_ref


@pytest.mark.parametrize("change", ["content", "host", "future", "stale", "model"])
def test_native_observation_refuses_mismatches(tmp_path, change):
    binding, record, observation = prepared(tmp_path)
    pinned = binding.native_codex
    assert pinned is not None
    if change == "content":
        pinned.path.write_bytes(b"{}")
    elif change == "host":
        binding = binding.model_copy(
            update={"native_codex": pinned.model_copy(update={"host_profile": "other"})}
        )
    else:
        updates = (
            {"remote_model_id": "other"}
            if change == "model"
            else {
                "observed_at": datetime.now(UTC) + timedelta(days=1 if change == "future" else -2)
            }
        )
        raw = observation.model_copy(update=updates).model_dump_json().encode()
        pinned.path.write_bytes(raw)
        binding = binding.model_copy(
            update={
                "native_codex": pinned.model_copy(
                    update={"content_sha256": "sha256:" + sha256(raw).hexdigest()}
                )
            }
        )
    with pytest.raises(ProbeUnavailable):
        verify_native_codex(binding, record)


def test_old_binding_serialization_omits_native_field():
    binding = OwnerProbeBinding(
        request_scope="s",
        prerequisite_id="codex.owner.m4",
        definition_digest="sha256:" + "a" * 64,
        operation="broker_names",
        credentials=({"provider": "environment", "key": "OPENAI_API_KEY"},),
    )
    assert "native_codex" not in binding.model_dump()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("auth_json_created", True),
        ("thread_started", True),
        ("turn_started", True),
        ("credential_store", "file"),
        ("account_read", "chatgpt"),
        ("remote_metadata_access", False),
        ("unexpected_proof", "caller supplied"),
    ],
)
def test_native_receipt_refuses_unsafe_or_untyped_claims(tmp_path, field, value):
    _, _, observation = prepared(tmp_path)
    with pytest.raises(ValidationError):
        NativeCodexObservation.model_validate({**observation.model_dump(), field: value})


@pytest.mark.parametrize("field", ["host_profile", "workspace", "auth", "cli_version", "model_id"])
def test_native_scope_changes_identity_and_definition(field):
    prerequisite = next(p for p in account_prerequisites(LaneProfile.CODEX) if p.id.endswith(".x6"))
    identity = {
        "host_profile": "wsl",
        "workspace": "build-a",
        "auth": "api-a",
        "cli_version": "0.162.1",
    }
    original = scope_prerequisite(prerequisite, Environment(), None, native_identity=identity)
    repeated = scope_prerequisite(prerequisite, Environment(), None, native_identity=identity)
    changed = scope_prerequisite(
        prerequisite, Environment(), None, native_identity={**identity, field: "changed"}
    )
    assert original == repeated
    assert original.id != changed.id
    assert original.digest != changed.digest
    now = datetime.now(UTC)
    verified = OwnerPrerequisiteRecord.of(original).evidenced(
        PrerequisiteEvidence(
            method=VerificationMethod.FILE_CHECK,
            definition_digest=original.digest,
            recorded_at=now,
            evidence_ref="native-codex:trusted",
            expires_at=now + timedelta(hours=1),
        )
    )
    assert not assess_prerequisite(verified, now=now).blocking
    assert assess_prerequisite(OwnerPrerequisiteRecord.of(changed), now=now).blocking
    assert scope_prerequisite(prerequisite, Environment(), None) == prerequisite
