import json
import os
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import ValidationError

from mission_control.adapters.prerequisites.cursor_native import (
    NativeCursorObservation,
    verify_native_cursor,
)
from mission_control.application.prerequisites.catalog import account_prerequisites
from mission_control.application.prerequisites.preflight import scope_prerequisite
from mission_control.application.prerequisites.probes import (
    NativeCursorEvidenceBinding,
    NativeCursorHostIdentity,
    OwnerProbeBinding,
)
from mission_control.application.prerequisites.setup import ProbeUnavailable
from mission_control.domain.authoring.manifest import Environment
from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.prerequisites import OwnerPrerequisiteRecord


def prepared(tmp_path):
    root = tmp_path / "protected-repository"
    root.mkdir()
    marker = root / "AGENTS.md"
    marker.write_text("retained repository instructions")
    git = Path(shutil.which("git")).resolve()
    git_env = {key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR") if key in os.environ}
    git_env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0")
    for argv in (
        ("init", "-b", "main"),
        ("add", "AGENTS.md"),
        (
            "-c",
            "user.name=C9 fixture",
            "-c",
            "user.email=c9@example.invalid",
            "commit",
            "-m",
            "fixture",
        ),
    ):
        subprocess.run(
            [str(git), "-c", "core.hooksPath=" + os.devnull, "-C", str(root), *argv],
            env=git_env,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    commit = subprocess.check_output(
        [str(git), "-C", str(root), "rev-parse", "HEAD"], env=git_env, text=True
    ).strip()
    lease_root = tmp_path / "leases"
    lease_root.mkdir()
    retired = lease_root / "retired"
    retired.mkdir()
    prior_worktree_identity = (retired.stat().st_dev, retired.stat().st_ino)
    (retired / "fixture.txt").write_text("disposable cleanup fixture")
    prior_file_digest = "sha256:" + sha256((retired / "fixture.txt").read_bytes()).hexdigest()
    (retired / "fixture.txt").unlink()
    retired.rmdir()
    identity = NativeCursorHostIdentity.model_validate(
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
            "host_configuration_digest": "sha256:" + "e" * 64,
            "auth": {"profile": "cursor-api", "billing_mode": "api"},
            "auth_route": "api_key",
            "agent_profile_ref": {
                "kind": "agent_profile",
                "logical_id": "cursor",
                "revision": 1,
                "digest": "sha256:" + "c" * 64,
            },
            "cursor_configuration": {
                "pins": {
                    "cursor_sdk": "1.0.37",
                    "bridge": "1.0.37",
                    "protocol": "sdk.v1",
                    "cloud_api": "v1",
                },
                "model_id": "Auto",
                "workspace": {
                    "repo_url": str(root),
                    "base_ref": "main",
                    "lease_root": str(lease_root),
                },
                "mode": "agent",
                "sandbox_enabled": False,
                "disallowed_tools": [],
                "hook_callback_digest": "sha256:" + "b" * 64,
            },
            "observed_repository_commit": commit,
            "git_executable": git,
            "git_sha256": "sha256:" + sha256(git.read_bytes()).hexdigest(),
            "attestor": "reviewed-host-observer",
            "node_version": "v24.5.0",
            "bridge_archive_version": "1.0.0",
            **dict.fromkeys(
                (
                    "node_sha256",
                    "bridge_archive_sha256",
                    "sdk_closure_sha256",
                    "loader_closure_sha256",
                ),
                "sha256:" + "d" * 64,
            ),
        }
    )
    native = identity.model_dump(
        mode="json",
        exclude={
            "build_commit",
            "attestor",
            "node_version",
            "node_sha256",
            "bridge_archive_version",
            "bridge_archive_sha256",
            "sdk_closure_sha256",
            "loader_closure_sha256",
            "observed_repository_commit",
            "git_executable",
            "git_sha256",
        },
    )
    native["auth"] = identity.auth.model_dump(mode="json", exclude_none=True)
    native["workspace"] = identity.workspace.model_dump(mode="json", exclude_none=True)
    prerequisite = next(
        p for p in account_prerequisites(LaneProfile.CURSOR_LOCAL) if p.id.endswith(".c9")
    )
    record = OwnerPrerequisiteRecord.of(
        scope_prerequisite(prerequisite, Environment(), None, native_identity=native)
    )
    observation = NativeCursorObservation(
        schema_version="mc.cursor_native_host_observation.v1",
        identity=identity,
        observed_repository_commit=commit,
        observed_at=datetime.now(UTC),
        sdk_version_observed="1.0.37",
        bridge_archive_version_observed="1.0.0",
        protocol_observed="sdk.v1",
        node_version_observed="v24.5.0",
        node_sha256_observed=identity.node_sha256,
        bridge_archive_sha256_observed=identity.bridge_archive_sha256,
        sdk_closure_sha256_observed=identity.sdk_closure_sha256,
        loader_closure_sha256_observed=identity.loader_closure_sha256,
        cleanup_fixture={
            "protected_root": root,
            "retired_worktree": lease_root / "retired",
            "root_identity_before": (root.stat().st_dev, root.stat().st_ino),
            "root_identity_after": (root.stat().st_dev, root.stat().st_ino),
            "retired_worktree_identity_before": prior_worktree_identity,
            "retired_worktree_files_before": [{"path": "fixture.txt", "sha256": prior_file_digest}],
            "files_before": [
                {"path": "AGENTS.md", "sha256": "sha256:" + sha256(marker.read_bytes()).hexdigest()}
            ],
            "files_after": [
                {"path": "AGENTS.md", "sha256": "sha256:" + sha256(marker.read_bytes()).hexdigest()}
            ],
        },
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
        operation="cursor_native_host",
        native_cursor=NativeCursorEvidenceBinding(
            **identity.model_dump(),
            path=path,
            content_sha256="sha256:" + sha256(path.read_bytes()).hexdigest(),
        ),
    )
    return binding, record, observation


def test_exact_host_proof_no_authentication_claim(tmp_path):
    binding, record, observed = prepared(tmp_path)
    result = verify_native_cursor(binding, record)
    assert result.observed_at == observed.observed_at
    assert binding.native_cursor.content_sha256 in result.evidence_ref
    assert not observed.authentication_validated and not observed.provider_calls


@pytest.mark.parametrize(
    "change",
    ["corrupt", "missing", "oversized", "identity", "stale", "future", "cli_hash", "sdk", "method"],
)
def test_host_proof_refuses_mismatch(tmp_path, change):
    binding, record, observed = prepared(tmp_path)
    pin = binding.native_cursor
    if change == "corrupt":
        pin.path.write_bytes(b"{}")
    elif change == "missing":
        pin.path.unlink()
    elif change == "oversized":
        pin.path.write_bytes(b"x" * 65537)
    elif change == "identity":
        binding = binding.model_copy(
            update={"native_cursor": pin.model_copy(update={"host_profile": "another"})}
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
            else {"node_sha256_observed": "sha256:" + "f" * 64}
            if change == "cli_hash"
            else {"sdk_version_observed": "wrong"}
        )
        raw = observed.model_copy(update=updates).model_dump_json().encode()
        pin.path.write_bytes(raw)
        binding = binding.model_copy(
            update={
                "native_cursor": pin.model_copy(
                    update={"content_sha256": "sha256:" + sha256(raw).hexdigest()}
                )
            }
        )
    with pytest.raises(ProbeUnavailable):
        verify_native_cursor(binding, record)


@pytest.mark.parametrize(
    "field",
    [
        "workspace",
        "host_profile",
        "auth",
        "cursor_configuration",
        "agent_profile_ref",
        "host_configuration_digest",
    ],
)
def test_selected_configuration_changes_prerequisite_identity(tmp_path, field):
    binding, _record, _ = prepared(tmp_path)
    identity = binding.native_cursor.model_dump(
        mode="json",
        exclude={
            "path",
            "content_sha256",
            "build_commit",
            "attestor",
            "node_version",
            "node_sha256",
            "bridge_archive_version",
            "bridge_archive_sha256",
            "sdk_closure_sha256",
            "loader_closure_sha256",
            "observed_repository_commit",
            "git_executable",
            "git_sha256",
        },
    )
    original = next(
        p for p in account_prerequisites(LaneProfile.CURSOR_LOCAL) if p.id.endswith(".c9")
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
        NativeCursorObservation.model_validate({**observed.model_dump(), field: value})


def test_old_probe_dump_bytes_unchanged_without_optional_native_fields():
    probe = OwnerProbeBinding(
        request_scope="scope",
        prerequisite_id="m4",
        definition_digest="sha256:" + "a" * 64,
        operation="broker_names",
        credentials=({"provider": "environment", "key": "CURSOR_API_KEY"},),
    )
    assert "native_cursor" not in probe.model_dump() and "native_codex" not in probe.model_dump()


def test_native_evidence_cannot_be_assigned_to_broker_names(tmp_path):
    binding, _, _ = prepared(tmp_path)
    with pytest.raises(ValidationError):
        OwnerProbeBinding.model_validate({**binding.model_dump(), "operation": "broker_names"})


def test_symlink_observation_refused(tmp_path):
    binding, record, _ = prepared(tmp_path)
    pin = binding.native_cursor
    link = tmp_path / "link.json"
    try:
        link.symlink_to(pin.path)
    except OSError:
        pytest.skip("host does not permit creating symbolic links")
    with pytest.raises(ProbeUnavailable):
        verify_native_cursor(
            binding.model_copy(update={"native_cursor": pin.model_copy(update={"path": link})}),
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


async def test_broker_names_cannot_satisfy_c9(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from mission_control.adapters.prerequisites.probes import ProviderOwnerProbeExecutor

    _binding, record, _ = prepared(tmp_path)
    wrong = OwnerProbeBinding(
        request_scope="scope",
        prerequisite_id=record.prerequisite.id,
        definition_digest=record.definition_digest,
        operation="broker_names",
        credentials=({"provider": "environment", "key": "CURSOR_API_KEY"},),
    )
    broker = SimpleNamespace(resolve=AsyncMock(side_effect=AssertionError("not an C9 probe")))
    with pytest.raises(ProbeUnavailable):
        await ProviderOwnerProbeExecutor(broker, None).check(wrong, record)
    broker.resolve.assert_not_called()


@pytest.mark.parametrize(
    "change",
    [
        "root_file",
        "root_removed",
        "retired_survives",
        "root_identity",
        "snapshot_changed",
        "outside_lease",
    ],
)
def test_cleanup_fixture_must_match_actual_surviving_filesystem(tmp_path, change):
    binding, record, observed = prepared(tmp_path)
    fixture = observed.cleanup_fixture
    if change == "root_file":
        (fixture.protected_root / "AGENTS.md").write_text("changed")
    elif change == "root_removed":
        fixture.protected_root.rename(tmp_path / "moved-protected-root")
    elif change == "retired_survives":
        fixture.retired_worktree.mkdir()
    else:
        update = (
            {"root_identity_after": (0, 0)}
            if change == "root_identity"
            else {"files_after": ({"path": "other", "sha256": "sha256:" + "f" * 64},)}
            if change == "snapshot_changed"
            else {"retired_worktree": str(tmp_path / "outside")}
        )
        raw = {
            **observed.model_dump(mode="json"),
            "cleanup_fixture": {**fixture.model_dump(mode="json"), **update},
        }
        payload = json.dumps(raw).encode()
        binding.native_cursor.path.write_bytes(payload)
        binding = binding.model_copy(
            update={
                "native_cursor": binding.native_cursor.model_copy(
                    update={"content_sha256": "sha256:" + sha256(payload).hexdigest()}
                )
            }
        )
    with pytest.raises(ProbeUnavailable):
        verify_native_cursor(binding, record)


@pytest.mark.parametrize(
    "field", ["bridge_archive_version_observed", "protocol_observed", "node_version_observed"]
)
def test_archive_protocol_node_are_distinct_exact_observations(tmp_path, field):
    _, _, observed = prepared(tmp_path)
    with pytest.raises(ValidationError):
        NativeCursorObservation.model_validate({**observed.model_dump(), field: "1.0.37"})


@pytest.mark.parametrize("field", ["auth", "host_profile", "host_configuration_digest"])
def test_old_proof_cannot_satisfy_changed_admission_identity(tmp_path, field):
    binding, record, _ = prepared(tmp_path)
    original = next(
        p for p in account_prerequisites(LaneProfile.CURSOR_LOCAL) if p.id.endswith(".c9")
    )
    selected = binding.native_cursor.model_dump(
        mode="json",
        exclude={
            "path",
            "content_sha256",
            "build_commit",
            "attestor",
            "node_version",
            "node_sha256",
            "bridge_archive_version",
            "bridge_archive_sha256",
            "sdk_closure_sha256",
            "loader_closure_sha256",
            "observed_repository_commit",
            "git_executable",
            "git_sha256",
        },
    )
    selected["auth"] = binding.native_cursor.auth.model_dump(mode="json", exclude_none=True)
    selected["workspace"] = binding.native_cursor.workspace.model_dump(
        mode="json", exclude_none=True
    )
    selected[field] = "changed"
    changed = OwnerPrerequisiteRecord.of(
        scope_prerequisite(original, Environment(), None, native_identity=selected)
    )
    assert record.definition_digest != changed.definition_digest
    with pytest.raises(ProbeUnavailable):
        verify_native_cursor(binding, changed)


@pytest.mark.parametrize("change", ["head", "pinned_commit", "git_binary"])
def test_actual_repository_head_and_vetted_git_are_required(tmp_path, change):
    binding, record, observed = prepared(tmp_path)
    if change == "head":
        root = observed.cleanup_fixture.protected_root
        subprocess.run(
            [
                str(observed.identity.git_executable),
                "-c",
                "core.hooksPath=" + os.devnull,
                "-c",
                "user.name=C9 fixture",
                "-c",
                "user.email=c9@example.invalid",
                "-C",
                str(root),
                "commit",
                "--allow-empty",
                "-m",
                "second",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        identity = observed.identity
        if change == "pinned_commit":
            config = identity.cursor_configuration.model_copy(
                update={
                    "workspace": identity.cursor_configuration.workspace.model_copy(
                        update={"base_ref": "f" * 40}
                    )
                }
            )
            identity = identity.model_copy(update={"cursor_configuration": config})
        else:
            identity = identity.model_copy(update={"git_sha256": "sha256:" + "f" * 64})
        observed = observed.model_copy(update={"identity": identity})
        payload = observed.model_dump_json().encode()
        binding.native_cursor.path.write_bytes(payload)
        pin = NativeCursorEvidenceBinding(
            **identity.model_dump(),
            path=binding.native_cursor.path,
            content_sha256="sha256:" + sha256(payload).hexdigest(),
        )
        binding = binding.model_copy(update={"native_cursor": pin})
        selected = identity.model_dump(
            mode="json",
            exclude={
                "build_commit",
                "attestor",
                "node_version",
                "node_sha256",
                "bridge_archive_version",
                "bridge_archive_sha256",
                "sdk_closure_sha256",
                "loader_closure_sha256",
                "observed_repository_commit",
                "git_executable",
                "git_sha256",
            },
        )
        selected["auth"] = identity.auth.model_dump(mode="json", exclude_none=True)
        selected["workspace"] = identity.workspace.model_dump(mode="json", exclude_none=True)
        prerequisite = next(
            p for p in account_prerequisites(LaneProfile.CURSOR_LOCAL) if p.id.endswith(".c9")
        )
        record = OwnerPrerequisiteRecord.of(
            scope_prerequisite(prerequisite, Environment(), None, native_identity=selected)
        )
        binding = binding.model_copy(
            update={
                "prerequisite_id": record.prerequisite.id,
                "definition_digest": record.definition_digest,
            }
        )
    with pytest.raises(ProbeUnavailable):
        verify_native_cursor(binding, record)
