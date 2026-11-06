from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest
from pydantic import ValidationError

from mission_control.adapters.prerequisites.claude_native import (
    NativeClaudeObservation,
    verify_native_claude,
)
from mission_control.application.prerequisites.catalog import account_prerequisites
from mission_control.application.prerequisites.preflight import scope_prerequisite
from mission_control.application.prerequisites.probes import (
    NativeClaudeEvidenceBinding,
    NativeClaudeHostIdentity,
    OwnerProbeBinding,
)
from mission_control.application.prerequisites.setup import ProbeUnavailable
from mission_control.domain.authoring.manifest import Environment
from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.prerequisites import OwnerPrerequisiteRecord


def prepared(tmp_path):
    identity = NativeClaudeHostIdentity.model_validate(
        {
            "workspace": {
                "provider": "local-filesystem-wsl",
                **dict.fromkeys(
                    ("runtime_digest", "image_digest", "package_digest", "environment_digest"),
                    "sha256:" + "a" * 64,
                ),
            },
            "build_commit": "a" * 40,
            "host_profile": "worker.linux.wsl",
            "auth": {"profile": "claude-api", "billing_mode": "api"},
            "auth_route": "api_key",
            "cli_version": "2.1.294",
            "cli_sha256": "sha256:" + "b" * 64,
            "sdk_version": "0.2.165",
            "host_configuration_digest": "sha256:" + "e" * 64,
            "attestor": "reviewed-host-observer",
            "model_id": "claude-sonnet-5-5",
            "provider_options": {"provider": "claude_agent_sdk"},
            "agent_profile_ref": {
                "kind": "agent_profile",
                "logical_id": "claude",
                "revision": 1,
                "digest": "sha256:" + "c" * 64,
            },
        }
    )
    native = identity.model_dump(mode="json", exclude={"build_commit", "cli_sha256", "attestor"})
    native["auth"] = identity.auth.model_dump(mode="json", exclude_none=True)
    native["workspace"] = identity.workspace.model_dump(mode="json", exclude_none=True)
    prerequisite = next(
        p for p in account_prerequisites(LaneProfile.CLAUDE_AGENT_SDK) if p.id.endswith(".a8")
    )
    record = OwnerPrerequisiteRecord.of(
        scope_prerequisite(prerequisite, Environment(), None, native_identity=native)
    )
    observation = NativeClaudeObservation(
        schema_version="mc.claude_native_host_observation.v1",
        identity=identity,
        observed_at=datetime.now(UTC),
        sdk_version_observed="0.2.165",
        cli_version_observed="2.1.294",
        cli_sha256_observed=identity.cli_sha256,
        sdk_imported=True,
        worker_imported=True,
        api_key_delivery_configured=True,
        authentication_validated=False,
        provider_calls=0,
        session_started=False,
        turn_started=False,
    )
    path = tmp_path / "observation.json"
    path.write_text(observation.model_dump_json())
    binding = OwnerProbeBinding(
        request_scope="scope",
        prerequisite_id=record.prerequisite.id,
        definition_digest=record.definition_digest,
        operation="claude_native_host",
        native_claude=NativeClaudeEvidenceBinding(
            **identity.model_dump(),
            path=path,
            content_sha256="sha256:" + sha256(path.read_bytes()).hexdigest(),
        ),
    )
    return binding, record, observation


def test_exact_host_proof_no_authentication_claim(tmp_path):
    binding, record, observed = prepared(tmp_path)
    result = verify_native_claude(binding, record)
    assert result.observed_at == observed.observed_at
    assert binding.native_claude.content_sha256 in result.evidence_ref
    assert not observed.authentication_validated and not observed.provider_calls


@pytest.mark.parametrize(
    "change",
    ["corrupt", "missing", "oversized", "identity", "stale", "future", "cli_hash", "sdk", "method"],
)
def test_host_proof_refuses_mismatch(tmp_path, change):
    binding, record, observed = prepared(tmp_path)
    pin = binding.native_claude
    if change == "corrupt":
        pin.path.write_bytes(b"{}")
    elif change == "missing":
        pin.path.unlink()
    elif change == "oversized":
        pin.path.write_bytes(b"x" * 65537)
    elif change == "identity":
        binding = binding.model_copy(
            update={"native_claude": pin.model_copy(update={"host_profile": "another"})}
        )
    elif change == "method":
        record = OwnerPrerequisiteRecord.of(
            record.prerequisite.model_copy(
                update={
                    "verify": record.prerequisite.verify.model_copy(
                        update={"probe": "prerequisite:m4"}
                    )
                }
            )
        )
    else:
        updates = (
            {"observed_at": datetime.now(UTC) + timedelta(days=-2 if change == "stale" else 2)}
            if change in {"stale", "future"}
            else {"cli_sha256_observed": "sha256:" + "d" * 64}
            if change == "cli_hash"
            else {"sdk_version_observed": "wrong"}
        )
        raw = observed.model_copy(update=updates).model_dump_json().encode()
        pin.path.write_bytes(raw)
        binding = binding.model_copy(
            update={
                "native_claude": pin.model_copy(
                    update={"content_sha256": "sha256:" + sha256(raw).hexdigest()}
                )
            }
        )
    with pytest.raises(ProbeUnavailable):
        verify_native_claude(binding, record)


@pytest.mark.parametrize(
    "field",
    [
        "workspace",
        "host_profile",
        "auth",
        "cli_version",
        "sdk_version",
        "model_id",
        "provider_options",
        "agent_profile_ref",
        "host_configuration_digest",
    ],
)
def test_selected_configuration_changes_prerequisite_identity(tmp_path, field):
    binding, _record, _ = prepared(tmp_path)
    identity = binding.native_claude.model_dump(
        mode="json", exclude={"path", "content_sha256", "build_commit", "cli_sha256", "attestor"}
    )
    original = next(
        p for p in account_prerequisites(LaneProfile.CLAUDE_AGENT_SDK) if p.id.endswith(".a8")
    )
    before = scope_prerequisite(original, Environment(), None, native_identity=identity)
    changed = scope_prerequisite(
        original, Environment(), None, native_identity={**identity, field: "changed"}
    )
    assert changed.id != before.id and changed.digest != before.digest


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("authentication_validated", True),
        ("provider_calls", 1),
        ("session_started", True),
        ("sdk_imported", False),
        ("api_key_delivery_configured", False),
    ],
)
def test_unadmitted_proof_claims_rejected(tmp_path, field, value):
    _, _, observed = prepared(tmp_path)
    with pytest.raises(ValidationError):
        NativeClaudeObservation.model_validate({**observed.model_dump(), field: value})


def test_old_probe_dump_bytes_unchanged_without_optional_native_fields():
    probe = OwnerProbeBinding(
        request_scope="scope",
        prerequisite_id="m4",
        definition_digest="sha256:" + "a" * 64,
        operation="broker_names",
        credentials=({"provider": "environment", "key": "ANTHROPIC_API_KEY"},),
    )
    assert "native_claude" not in probe.model_dump() and "native_codex" not in probe.model_dump()


def test_native_evidence_cannot_be_assigned_to_broker_names(tmp_path):
    binding, _, _ = prepared(tmp_path)
    with pytest.raises(ValidationError):
        OwnerProbeBinding.model_validate({**binding.model_dump(), "operation": "broker_names"})


def test_symlink_observation_refused(tmp_path):
    binding, record, _ = prepared(tmp_path)
    pin = binding.native_claude
    link = tmp_path / "link.json"
    try:
        link.symlink_to(pin.path)
    except OSError:
        pytest.skip("host does not permit creating symbolic links")
    with pytest.raises(ProbeUnavailable):
        verify_native_claude(
            binding.model_copy(update={"native_claude": pin.model_copy(update={"path": link})}),
            record,
        )


async def test_production_executor_host_check_never_resolves_credentials(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from mission_control.adapters.prerequisites.probes import ProviderOwnerProbeExecutor
    from mission_control.application.prerequisites.probes import (
        ConfiguredOwnerProbes,
        OwnerProbeConfiguration,
    )

    binding, record, observed = prepared(tmp_path)
    broker = SimpleNamespace(resolve=AsyncMock(side_effect=AssertionError("no credential reads")))
    executor = ProviderOwnerProbeExecutor(broker, None)
    probes = ConfiguredOwnerProbes(OwnerProbeConfiguration(bindings=(binding,)), executor)
    first = await probes.verify("scope", record)
    second = await probes.verify("scope", record)
    assert (
        first.expires_at
        == second.expires_at
        == observed.observed_at + timedelta(seconds=binding.max_age_seconds)
    )
    with pytest.raises(ProbeUnavailable):
        await probes.verify("another-scope", record)
    broker.resolve.assert_not_called()


async def test_broker_names_cannot_satisfy_a8(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from mission_control.adapters.prerequisites.probes import ProviderOwnerProbeExecutor

    _binding, record, _ = prepared(tmp_path)
    wrong = OwnerProbeBinding(
        request_scope="scope",
        prerequisite_id=record.prerequisite.id,
        definition_digest=record.definition_digest,
        operation="broker_names",
        credentials=({"provider": "environment", "key": "ANTHROPIC_API_KEY"},),
    )
    broker = SimpleNamespace(resolve=AsyncMock(side_effect=AssertionError("not an A8 probe")))
    with pytest.raises(ProbeUnavailable):
        await ProviderOwnerProbeExecutor(broker, None).check(wrong, record)
    broker.resolve.assert_not_called()
