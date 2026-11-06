"""Ports of the Signal Ingress service (SPEC-10 sections 2 and 3).

`IngressStore` is one application's ingress database surface: one SECURITY DEFINER function call
per method (`adapters/postgres/ingress.py`). Every method answers a typed outcome string; the
service maps a rejection to its HTTP status. `ProviderOidcVerifier` verifies a provider-minted
JWT (Cursor). `QuarantineUploads` signs an upload URL for a quarantine storage key.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from mission_control.application.capabilities.bundle_custody import SignedUpload
from mission_control.application.signals.contracts import TrustTier
from mission_control.domain.policies.stop_fence import EffectKind


@dataclass(frozen=True)
class Principal:
    """Who presented a request: the tier and its credential reference. `credential` is a
    token digest (`run_token`, `launch_token`) or a provider session id (`provider_oidc`,
    `environment_key`); a token value never reaches the store."""

    tier: TrustTier
    credential: str
    provider: str | None = None
    environment_ref: str | None = None
    nonce_hash: str | None = None


@dataclass(frozen=True)
class InboxItem:
    """One redacted, size-checked message for the inbox."""

    ingress_id: UUID
    kind: str
    dedupe_key: str
    body_sha256: str
    payload: Mapping[str, Any]
    seq: int | None = None


@dataclass(frozen=True)
class AcceptOutcome:
    outcome: str
    accepted: int = 0
    duplicates: int = 0


@dataclass(frozen=True)
class GateCall:
    ingress_id: UUID
    dedupe_key: str
    hook_event: str
    effect_ref: str
    effect_kind: EffectKind
    tool: str | None
    input_digest: str
    body_sha256: str


@dataclass(frozen=True)
class GateOutcome:
    outcome: str
    decision: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class ArtifactSlotOutcome:
    outcome: str
    artifact_upload_id: UUID | None = None
    storage_key: str | None = None
    expires_at: datetime | None = None


@dataclass(frozen=True)
class RequestOutcome:
    outcome: str
    request_id: UUID | None = None


@dataclass(frozen=True)
class RequestStatusOutcome:
    outcome: str
    state: str | None = None
    mission_id: UUID | None = None
    reason: str | None = None
    lifecycle: str | None = None


class IngressStore(Protocol):
    @property
    def application_id(self) -> str: ...

    async def accept(self, principal: Principal, items: Sequence[InboxItem]) -> AcceptOutcome: ...

    async def gate(self, principal: Principal, call: GateCall) -> GateOutcome: ...

    async def webhook(self, provider: str, route_ref: str | None, item: InboxItem) -> str: ...

    async def prepare_artifact(
        self,
        principal: Principal,
        artifact_upload_id: UUID,
        *,
        artifact_ref: str,
        sha256: str,
        size_bytes: int,
        media_type: str,
        ttl_seconds: int,
    ) -> ArtifactSlotOutcome: ...

    async def commit_artifact(
        self, principal: Principal, ingress_id: UUID, artifact_upload_id: UUID
    ) -> RequestOutcome: ...

    async def request_mission(
        self, principal: Principal, item: InboxItem, *, manifest_ref: str
    ) -> RequestOutcome: ...

    async def mission_request_status(
        self, principal: Principal, request_id: UUID
    ) -> RequestStatusOutcome: ...


@dataclass(frozen=True)
class SessionBinding:
    """A provider session the worker binds to one run generation. `provider_oidc` names the
    session (Cursor `cloud_agent_id`) at launch; `environment_key` registers the digest of the
    run nonce written to `.mission/run.json`, and the first `session.started` signal that
    presents the nonce names the session."""

    request_scope: str
    tier: TrustTier
    provider: str
    run_key: str
    unit_key: str
    generation: int
    expires_at: datetime
    session_id: str | None = None
    nonce_hash: str | None = None
    environment_ref: str | None = None
    context: Mapping[str, Any] = field(default_factory=dict, hash=False)
    rate_limit_per_minute: int = 600


@dataclass(frozen=True)
class OidcIdentity:
    """A verified provider JWT reduced to the session it names."""

    provider: str
    session_id: str
    environment_ref: str | None = None


class ProviderOidcVerifier(Protocol):
    async def verify(self, token: str) -> OidcIdentity:
        """The identity of a valid token; `IngressRejected` otherwise."""
        ...


class QuarantineUploads(Protocol):
    async def signed_upload(self, storage_key: str) -> SignedUpload: ...


__all__ = [
    "AcceptOutcome",
    "ArtifactSlotOutcome",
    "GateCall",
    "GateOutcome",
    "InboxItem",
    "IngressStore",
    "OidcIdentity",
    "Principal",
    "ProviderOidcVerifier",
    "QuarantineUploads",
    "RequestOutcome",
    "RequestStatusOutcome",
    "SessionBinding",
]
