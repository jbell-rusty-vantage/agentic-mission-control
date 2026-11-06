"""Verify operator-pinned public observations of the exact native Codex host."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict

from mission_control.application.prerequisites.probes import (
    NativeCodexHostIdentity,
    OwnerProbeBinding,
    ProbeObservation,
)
from mission_control.application.prerequisites.setup import ProbeUnavailable
from mission_control.domain.prerequisites import OwnerPrerequisiteRecord


class NativeCodexObservation(BaseModel):
    """Public receipt issued by an installation's reviewed host observer.

    The file hash and attestor are installation configuration, not request input.
    Remote metadata access proves neither inference permission nor account balance.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["mc.codex_native_observation.v1"]
    identity: NativeCodexHostIdentity
    observed_at: AwareDatetime
    cli_version_observed: str
    cli_sha256_observed: str
    api_login: Literal["apiKey"]
    account_read: Literal["apiKey"]
    credential_store: Literal["ephemeral"]
    auth_json_created: Literal[False]
    thread_started: Literal[False]
    turn_started: Literal[False]
    remote_model_id: str
    remote_metadata_access: Literal[True]


def verify_native_codex(
    binding: OwnerProbeBinding, record: OwnerPrerequisiteRecord
) -> ProbeObservation:
    pinned = binding.native_codex
    if pinned is None:
        raise ProbeUnavailable("native Codex evidence is not configured")
    identity = {
        "workspace": pinned.workspace.model_dump(mode="json", exclude_none=True),
        "host_profile": pinned.host_profile,
        "auth": pinned.auth.model_dump(mode="json", exclude_none=True),
        "cli_version": pinned.cli_version,
        "model_id": pinned.model_id,
    }
    digest = (
        "sha256:"
        + sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    )
    if not record.prerequisite.why.endswith(" Native Codex identity: " + digest):
        raise ProbeUnavailable("native Codex proof does not match the scoped prerequisite")
    # Bounded public evidence only. Never execute a command or resolve credentials here.
    with pinned.path.open("rb") as source:
        raw = source.read(65537)
    if len(raw) > 65536 or "sha256:" + sha256(raw).hexdigest() != pinned.content_sha256:
        raise ProbeUnavailable("native Codex evidence content does not match its pin")
    observed = NativeCodexObservation.model_validate_json(raw)
    if observed.identity.model_dump() != pinned.model_dump(exclude={"content_sha256", "path"}):
        raise ProbeUnavailable("native Codex evidence names a different host identity")
    if (
        observed.cli_version_observed != pinned.cli_version
        or observed.cli_sha256_observed != pinned.cli_sha256
        or observed.remote_model_id != pinned.model_id
        or pinned.auth.billing_mode != "api"
    ):
        raise ProbeUnavailable("native Codex observation does not prove the selected API route")
    now = datetime.now(UTC)
    if not now - timedelta(seconds=binding.max_age_seconds) < observed.observed_at <= now:
        raise ProbeUnavailable("native Codex observation is stale or in the future")
    return ProbeObservation(
        f"native-codex:{binding.operation}:evidence:{pinned.content_sha256}",
        observed.observed_at,
    )
