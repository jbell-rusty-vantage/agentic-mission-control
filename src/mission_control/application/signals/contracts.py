"""Signal Ingress wire contracts and trust tiers (SPEC-04 section 3, SPEC-10 section 2).

Every body the ingress accepts is one of these strict documents. The tier a request was
accepted at is recorded on every inbox row; watchers can require a minimum tier, and only
`run_token` and `provider_oidc` may gate an effect or upload an artifact. A typed rejection
carries its code and HTTP status; it never echoes a credential.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Final, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from mission_control.domain.capabilities.hooks import HookEvent
from mission_control.domain.policies.stop_fence import EffectKind

SIGNAL_SCHEMA: Final = "mc.signal.v1"
SIGNAL_BATCH_SCHEMA: Final = "mc.signal_batch.v1"
SIGNAL_GATE_SCHEMA: Final = "mc.signal_gate.v1"
MISSION_REQUEST_SCHEMA: Final = "mc.mission_request.v1"
PROVIDER_WAKE_SCHEMA: Final = "mc.provider_wake.v1"

MAX_BATCH_SIGNALS: Final = 100
_IDENTIFIER = r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,255}$"
_SIGNAL_TYPE = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$"


class TrustTier(StrEnum):
    RUN_TOKEN = "run_token"  # noqa: S105 - a trust tier name, not a credential
    PROVIDER_OIDC = "provider_oidc"
    ENVIRONMENT_KEY = "environment_key"
    PROVIDER_SIGNED = "provider_signed"
    LAUNCH_TOKEN = "launch_token"  # noqa: S105 - a trust tier name, not a credential


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Signal(_Strict):
    """`mc.signal.v1`: one observation from inside an environment (evidence, never authority).

    `signal_id` is the sender's dedupe key; `seq` its monotonic per-session sequence, so a
    gap is detectable. `data` is untrusted and stored redacted."""

    schema_version: Literal["mc.signal.v1"] = SIGNAL_SCHEMA
    signal_id: str = Field(pattern=_IDENTIFIER)
    type: str = Field(pattern=_SIGNAL_TYPE, max_length=128)
    seq: int | None = Field(default=None, ge=0, le=10**18)
    occurred_at: AwareDatetime | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class SignalBatch(_Strict):
    schema_version: Literal["mc.signal_batch.v1"] = SIGNAL_BATCH_SCHEMA
    signals: tuple[Signal, ...] = Field(min_length=1, max_length=MAX_BATCH_SIGNALS)


class GateRequest(_Strict):
    """`mc.signal_gate.v1`: a hook asks whether one effect may proceed."""

    schema_version: Literal["mc.signal_gate.v1"] = SIGNAL_GATE_SCHEMA
    signal_id: str = Field(pattern=_IDENTIFIER)
    hook_event: HookEvent
    effect_ref: str = Field(min_length=1, max_length=512)
    effect_kind: EffectKind
    tool: str | None = Field(default=None, min_length=1, max_length=256)
    tool_input: dict[str, Any] = Field(default_factory=dict)


class ArtifactPrepareRequest(_Strict):
    artifact_ref: str = Field(pattern=r"^[A-Za-z0-9._/-]{1,256}$")
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    size_bytes: int = Field(ge=1, le=5 * 1024**3)
    media_type: str = Field(pattern=r"^[a-z]+/[A-Za-z0-9.+-]+$", max_length=255)


class ArtifactCommitRequest(_Strict):
    artifact_upload_id: UUID


class MissionRequest(_Strict):
    """`mc.mission_request.v1`: a remote launch request (R29). Admission happens on the
    worker, through the same application handler as the API."""

    schema_version: Literal["mc.mission_request.v1"] = MISSION_REQUEST_SCHEMA
    idempotency_key: str = Field(pattern=_IDENTIFIER)
    manifest_ref: str = Field(min_length=1, max_length=512)
    inputs: dict[str, Any] = Field(default_factory=dict)


class ProviderWake(_Strict):
    """`mc.provider_wake.v1`: a verified provider webhook reduced to the identity it names.

    It is the whole stored payload of a `webhook.anthropic` or `webhook.openai` inbox row (the
    delivery id is the row's `dedupe_key`). It carries no state: the worker resolves
    `resource_ref` to its run and re-reads that resource from the provider."""

    schema_version: Literal["mc.provider_wake.v1"] = PROVIDER_WAKE_SCHEMA
    event_type: str = Field(pattern=_SIGNAL_TYPE, max_length=128)
    resource_ref: str = Field(pattern=_IDENTIFIER)
    event_id: str | None = Field(default=None, pattern=_IDENTIFIER)


class SignalReceipt(_Strict):
    accepted: int = Field(ge=0)
    duplicates: int = Field(ge=0)


class GateAnswer(_Strict):
    decision: Literal["allow", "deny", "stop"]
    reason: str | None = None


class ArtifactUploadSlot(_Strict):
    artifact_upload_id: UUID
    upload_url: str
    upload_token: str | None = None
    expires_at: datetime


class MissionRequestStatus(_Strict):
    state: Literal["queued", "admitted", "refused"]
    mission_id: UUID | None = None
    reason: str | None = None
    lifecycle: str | None = None


class IngressRejected(Exception):
    """A typed refusal: `code` is stable, `status_code` the HTTP answer."""

    def __init__(self, status_code: int, code: str) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code


__all__ = [
    "MAX_BATCH_SIGNALS",
    "MISSION_REQUEST_SCHEMA",
    "PROVIDER_WAKE_SCHEMA",
    "SIGNAL_BATCH_SCHEMA",
    "SIGNAL_GATE_SCHEMA",
    "SIGNAL_SCHEMA",
    "ArtifactCommitRequest",
    "ArtifactPrepareRequest",
    "ArtifactUploadSlot",
    "GateAnswer",
    "GateRequest",
    "IngressRejected",
    "MissionRequest",
    "MissionRequestStatus",
    "ProviderWake",
    "Signal",
    "SignalBatch",
    "SignalReceipt",
    "TrustTier",
]
