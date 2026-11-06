"""Pinned local Claude SDK host proof; never authenticates or starts a provider session."""

from __future__ import annotations

import json
import os
import stat
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict

from mission_control.application.prerequisites.probes import (
    NativeClaudeHostIdentity,
    OwnerProbeBinding,
    ProbeObservation,
)
from mission_control.application.prerequisites.setup import ProbeUnavailable
from mission_control.domain.prerequisites import OwnerPrerequisiteRecord, VerificationMethod


class NativeClaudeObservation(BaseModel):
    """Operator-pinned offline host receipt. M4/key validity remain separate."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["mc.claude_native_host_observation.v1"]
    identity: NativeClaudeHostIdentity
    observed_at: AwareDatetime
    sdk_version_observed: Literal["0.2.165"]
    cli_version_observed: Literal["2.1.294"]
    cli_sha256_observed: str
    sdk_imported: Literal[True]
    worker_imported: Literal[True]
    api_key_delivery_configured: Literal[True]
    authentication_validated: Literal[False]
    provider_calls: Literal[0]
    session_started: Literal[False]
    turn_started: Literal[False]


def verify_native_claude(
    binding: OwnerProbeBinding, record: OwnerPrerequisiteRecord
) -> ProbeObservation:
    pinned = binding.native_claude
    if pinned is None or binding.operation != "claude_native_host":
        raise ProbeUnavailable("native Claude host evidence is not configured")
    if (
        binding.prerequisite_id != record.prerequisite.id
        or binding.definition_digest != record.definition_digest
        or record.prerequisite.verify.method is not VerificationMethod.FILE_CHECK
        or record.prerequisite.verify.probe != "prerequisite:a8"
    ):
        raise ProbeUnavailable("native Claude host proof does not match A8")
    identity = pinned.model_dump(
        mode="json", exclude={"build_commit", "cli_sha256", "attestor", "path", "content_sha256"}
    )
    # Match deployment serialization: AuthPin omits absent optional account identity.
    identity["auth"] = pinned.auth.model_dump(mode="json", exclude_none=True)
    identity["workspace"] = pinned.workspace.model_dump(mode="json", exclude_none=True)
    digest = (
        "sha256:"
        + sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    )
    if not record.prerequisite.why.endswith(" Native Claude host identity: " + digest):
        raise ProbeUnavailable("native Claude proof does not match the selected host configuration")
    try:
        path = pinned.path
        if path.resolve() != path.absolute() or path.is_symlink():
            raise ProbeUnavailable("native Claude evidence path is not a regular pinned file")
        before = path.stat()
        if not stat.S_ISREG(before.st_mode) or before.st_size > 65536:
            raise ProbeUnavailable("native Claude evidence is not a bounded regular file")
        fd = os.open(
            path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        )
        with os.fdopen(fd, "rb") as source:
            opened = os.fstat(source.fileno())
            if not stat.S_ISREG(opened.st_mode) or (before.st_dev, before.st_ino) != (
                opened.st_dev,
                opened.st_ino,
            ):
                raise ProbeUnavailable("native Claude evidence identity changed")
            raw = source.read(65537)
        if len(raw) > 65536 or "sha256:" + sha256(raw).hexdigest() != pinned.content_sha256:
            raise ProbeUnavailable("native Claude evidence content differs from its pin")
        observed = NativeClaudeObservation.model_validate_json(raw)
    except (OSError, ValueError):
        raise ProbeUnavailable(
            "native Claude public observation is unavailable or invalid"
        ) from None
    if observed.identity.model_dump() != pinned.model_dump(exclude={"path", "content_sha256"}):
        raise ProbeUnavailable("native Claude evidence names another host identity")
    if (
        pinned.sdk_version != observed.sdk_version_observed
        or pinned.cli_version != observed.cli_version_observed
        or pinned.cli_sha256 != observed.cli_sha256_observed
        or pinned.auth.billing_mode != "api"
        or pinned.auth_route != "api_key"
    ):
        raise ProbeUnavailable(
            "native Claude host observation does not prove the selected API configuration"
        )
    now = datetime.now(UTC)
    if not now - timedelta(seconds=binding.max_age_seconds) < observed.observed_at <= now:
        raise ProbeUnavailable("native Claude host observation is stale or in the future")
    return ProbeObservation(
        f"native-claude:host:evidence:{pinned.content_sha256}", observed.observed_at
    )
