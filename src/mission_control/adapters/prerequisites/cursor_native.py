"""Pinned Cursor host and cleanup-fixture evidence; no provider/authentication calls."""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from mission_control.application.prerequisites.probes import (
    NativeCursorHostIdentity,
    OwnerProbeBinding,
    ProbeObservation,
)
from mission_control.application.prerequisites.setup import ProbeUnavailable
from mission_control.domain.prerequisites import OwnerPrerequisiteRecord, VerificationMethod


class CursorRootFileSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    path: str = Field(min_length=1, max_length=512)
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def relative_path(self) -> CursorRootFileSnapshot:
        path = PurePosixPath(self.path)
        if path.is_absolute() or ".." in path.parts or "\\" in self.path or ":" in self.path:
            raise ValueError("cleanup snapshots require safe relative root paths")
        return self


class CursorCleanupFixture(BaseModel):
    """Actual before/after root snapshots, checked against the surviving filesystem."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    protected_root: Path
    retired_worktree: Path
    root_identity_before: tuple[int, int]
    root_identity_after: tuple[int, int]
    retired_worktree_identity_before: tuple[int, int]
    retired_worktree_files_before: tuple[CursorRootFileSnapshot, ...] = Field(
        min_length=1, max_length=100
    )
    files_before: tuple[CursorRootFileSnapshot, ...] = Field(min_length=1, max_length=100)
    files_after: tuple[CursorRootFileSnapshot, ...] = Field(min_length=1, max_length=100)


class NativeCursorObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["mc.cursor_native_host_observation.v1"]
    identity: NativeCursorHostIdentity
    observed_repository_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    observed_at: AwareDatetime
    sdk_version_observed: Literal["1.0.37"]
    bridge_archive_version_observed: Literal["1.0.0"]
    protocol_observed: Literal["sdk.v1"]
    node_version_observed: Literal["v24.5.0"]
    node_sha256_observed: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    bridge_archive_sha256_observed: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    sdk_closure_sha256_observed: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    loader_closure_sha256_observed: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    sdk_imported: Literal[True]
    worker_imported: Literal[True]
    api_key_delivery_configured: Literal[True]
    authentication_validated: Literal[False]
    provider_calls: Literal[0]
    session_started: Literal[False]
    turn_started: Literal[False]
    cleanup_fixture: CursorCleanupFixture


def _regular_bytes(path: Path, limit: int) -> bytes:
    if not path.is_absolute() or path.resolve() != path.absolute() or path.is_symlink():
        raise ProbeUnavailable("Cursor evidence path is not an exact regular file")
    before = path.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
        raise ProbeUnavailable("Cursor evidence file is not bounded and regular")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(fd, "rb") as source:
        opened = os.fstat(source.fileno())
        if not stat.S_ISREG(opened.st_mode) or (before.st_dev, before.st_ino) != (
            opened.st_dev,
            opened.st_ino,
        ):
            raise ProbeUnavailable("Cursor evidence file changed identity")
        raw = source.read(limit + 1)
        after = os.fstat(source.fileno())
    if (
        len(raw) > limit
        or (opened.st_size, opened.st_mtime_ns) != (after.st_size, after.st_mtime_ns)
        or path.stat().st_ino != opened.st_ino
    ):
        raise ProbeUnavailable("Cursor evidence file changed during read")
    return raw


def _verify_cleanup(observed: NativeCursorObservation) -> None:
    fixture = observed.cleanup_fixture
    config = observed.identity.cursor_configuration
    root, retired = fixture.protected_root, fixture.retired_worktree
    if (
        not root.is_absolute()
        or root.resolve() != root.absolute()
        or not root.is_dir()
        or str(root) != config.workspace.repo_url
        or not retired.is_absolute()
        or config.workspace.lease_root is None
    ):
        raise ProbeUnavailable("Cursor cleanup fixture names another protected root")
    lease_root = Path(config.workspace.lease_root)
    if (
        not lease_root.is_absolute()
        or lease_root.resolve() != lease_root.absolute()
        or retired.resolve() != retired.absolute()
        or not retired.is_relative_to(lease_root)
        or retired == lease_root
        or root.is_relative_to(retired)
        or retired.is_relative_to(root)
        or os.path.lexists(retired)
    ):
        raise ProbeUnavailable("Cursor cleanup fixture does not prove isolated worktree removal")
    # The operator-pinned capture must retain the original fixture identity/files,
    # not merely an absent path that may never have been a worktree. Their bytes
    # cannot be reread after cleanup; the reviewed attestor owns that prior capture.
    old_device, old_inode = fixture.retired_worktree_identity_before
    if (
        old_device < 0
        or old_inode <= 0
        or fixture.retired_worktree_identity_before == fixture.root_identity_before
    ):
        raise ProbeUnavailable("Cursor cleanup fixture lacks a distinct prior worktree identity")
    old_names = [item.path for item in fixture.retired_worktree_files_before]
    if len(set(old_names)) != len(old_names):
        raise ProbeUnavailable("Cursor cleanup fixture repeats prior worktree files")
    git = observed.identity.git_executable
    if (
        "sha256:" + sha256(_regular_bytes(git, 16777216)).hexdigest()
        != observed.identity.git_sha256
    ):
        raise ProbeUnavailable("Cursor cleanup verifier git executable differs from its pin")
    child = {key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR") if key in os.environ}
    child.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_SYSTEM=os.devnull,
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_TERMINAL_PROMPT="0",
        GIT_OPTIONAL_LOCKS="0",
    )
    # Fixed builtin command, vetted executable, no shell/network/provider/auth route.
    # Temporary outputs bound memory; oversized output is refused and never exposed.
    with tempfile.TemporaryFile() as output:
        result = subprocess.run(
            [
                str(git),
                "--no-optional-locks",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "core.hooksPath=" + os.devnull,
                "-C",
                str(root),
                "rev-parse",
                "--show-toplevel",
                "--verify",
                "HEAD^{commit}",
            ],
            env=child,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
        if result.returncode != 0 or output.tell() > 4096:
            raise ProbeUnavailable("Cursor protected repository HEAD is unavailable")
        output.seek(0)
        lines = output.read(4097).decode("utf-8").splitlines()
        if len(lines) != 2 or Path(lines[0]).resolve() != root.resolve():
            raise ProbeUnavailable("Cursor git verification resolved another protected root")
        head = lines[1].strip()
    if (
        head != observed.observed_repository_commit
        or head != observed.identity.observed_repository_commit
    ):
        raise ProbeUnavailable("Cursor protected repository HEAD drifted from native observation")
    if (
        re.fullmatch(r"[0-9a-f]{40}", config.workspace.base_ref)
        and head != config.workspace.base_ref
    ):
        raise ProbeUnavailable(
            "Cursor observed repository HEAD differs from the pinned base commit"
        )
    # A symbolic base_ref is retained as the admitted name, not claimed resolved
    # by that spelling. The actual separately captured/current commit is explicit.
    current = root.stat()
    if (
        fixture.root_identity_before != fixture.root_identity_after
        or (current.st_dev, current.st_ino) != fixture.root_identity_after
    ):
        raise ProbeUnavailable("Cursor protected root identity changed during cleanup")
    before = {item.path: item.sha256 for item in fixture.files_before}
    after = {item.path: item.sha256 for item in fixture.files_after}
    if (
        len(before) != len(fixture.files_before)
        or len(after) != len(fixture.files_after)
        or before != after
    ):
        raise ProbeUnavailable("Cursor cleanup changed the protected file snapshot")
    for name, expected in after.items():
        if "sha256:" + sha256(_regular_bytes(root / name, 1048576)).hexdigest() != expected:
            raise ProbeUnavailable("Cursor protected root file no longer matches cleanup evidence")


def verify_native_cursor(
    binding: OwnerProbeBinding, record: OwnerPrerequisiteRecord
) -> ProbeObservation:
    pinned = binding.native_cursor
    if pinned is None or binding.operation != "cursor_native_host":
        raise ProbeUnavailable("native Cursor host evidence is not configured")
    if (
        binding.prerequisite_id != record.prerequisite.id
        or binding.definition_digest != record.definition_digest
        or record.prerequisite.verify.method is not VerificationMethod.FILE_CHECK
        or record.prerequisite.verify.probe != "prerequisite:c9"
    ):
        raise ProbeUnavailable("native Cursor host evidence does not match C9")
    # Selected auth/host scope admission; neither is claimed as a Cursor binding field.
    selected = pinned.model_dump(
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
            "path",
            "content_sha256",
        },
    )
    selected["auth"] = pinned.auth.model_dump(mode="json", exclude_none=True)
    selected["workspace"] = pinned.workspace.model_dump(mode="json", exclude_none=True)
    digest = (
        "sha256:"
        + sha256(json.dumps(selected, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    )
    if not record.prerequisite.why.endswith(" Native Cursor host identity: " + digest):
        raise ProbeUnavailable("native Cursor host proof names another selected configuration")
    try:
        raw = _regular_bytes(pinned.path, 65536)
        if "sha256:" + sha256(raw).hexdigest() != pinned.content_sha256:
            raise ProbeUnavailable("native Cursor evidence content differs from its pin")
        observed = NativeCursorObservation.model_validate_json(raw)
        if observed.identity.model_dump() != pinned.model_dump(exclude={"path", "content_sha256"}):
            raise ProbeUnavailable("native Cursor evidence names another host identity")
        if (
            pinned.auth.billing_mode != "api"
            or pinned.cursor_configuration.pins.cursor_sdk != observed.sdk_version_observed
            or pinned.cursor_configuration.pins.bridge != "1.0.37"
            or pinned.cursor_configuration.pins.protocol != observed.protocol_observed
            or pinned.cursor_configuration.pins.cloud_api != "v1"
            or pinned.node_version != observed.node_version_observed
            or pinned.bridge_archive_version != observed.bridge_archive_version_observed
            or pinned.node_sha256 != observed.node_sha256_observed
            or pinned.bridge_archive_sha256 != observed.bridge_archive_sha256_observed
            or pinned.sdk_closure_sha256 != observed.sdk_closure_sha256_observed
            or pinned.loader_closure_sha256 != observed.loader_closure_sha256_observed
        ):
            raise ProbeUnavailable("native Cursor observed tool closure differs from selected pins")
        _verify_cleanup(observed)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise ProbeUnavailable("native Cursor public observation unavailable or invalid") from None
    now = datetime.now(UTC)
    if not now - timedelta(seconds=binding.max_age_seconds) < observed.observed_at <= now:
        raise ProbeUnavailable("native Cursor host observation is stale or in the future")
    return ProbeObservation(
        f"native-cursor:host:evidence:{pinned.content_sha256}", observed.observed_at
    )
