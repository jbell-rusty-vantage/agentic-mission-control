"""Quarantine verification and custody. Uploads never grant publication or review."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Protocol
from uuid import UUID

from mission_control.application.artifacts.artifact_promotion import (
    ArtifactPayloadAddress,
    ArtifactPayloadPort,
)
from mission_control.application.signals.contracts import IngressRejected
from mission_control.application.signals.drainer import DrainRejected


@dataclass(frozen=True)
class CommittedUpload:
    upload_id: UUID
    request_scope: str
    run_key: str
    generation: int
    artifact_ref: str
    storage_key: str
    digest: str
    size_bytes: int
    media_type: str
    expires_at: datetime


class QuarantineReader(Protocol):
    async def read(self, key: str, *, max_bytes: int) -> bytes: ...
    async def delete(self, key: str) -> None: ...


class UploadAuthority(Protocol):
    async def rejected(self, upload: CommittedUpload, reason: str) -> None:
        """Persist rejected slot; quarantine cleanup remains retryable until inbox settlement."""
        ...

    async def require_current(self, upload: CommittedUpload) -> None:
        """Re-read scoped committed slot and current run generation; reject stale scope."""
        ...

    async def existing(self, upload: CommittedUpload) -> ArtifactPayloadAddress | None:
        """Read a previously registered immutable custody version for replay."""
        ...

    async def verified(self, upload: CommittedUpload, address: ArtifactPayloadAddress) -> None:
        """Idempotently register verified byte custody only; never fabricate review authority."""
        ...


class ArtifactCustodyService:
    def __init__(
        self,
        quarantine: QuarantineReader,
        payloads: ArtifactPayloadPort,
        authority: UploadAuthority,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        max_bytes: int = 64 * 1024 * 1024,
    ) -> None:
        self._quarantine, self._payloads, self._authority = quarantine, payloads, authority
        self._clock, self._max_bytes = clock, max_bytes

    async def verify(
        self, upload: CommittedUpload, *, request_scope: str, generation: int
    ) -> ArtifactPayloadAddress:
        if upload.request_scope != request_scope or upload.generation != generation:
            raise DrainRejected("artifact_cross_scope_or_stale")
        try:
            return await self._verify(upload, request_scope=request_scope, generation=generation)
        except DrainRejected as rejected:
            await self._authority.rejected(upload, rejected.code)
            await self._quarantine.delete(upload.storage_key)
            raise

    async def _verify(
        self, upload: CommittedUpload, *, request_scope: str, generation: int
    ) -> ArtifactPayloadAddress:
        await self._authority.require_current(upload)
        prior = await self._authority.existing(upload)
        if prior is not None:
            if prior.content_digest != upload.digest or prior.size_bytes != upload.size_bytes:
                raise DrainRejected("custody_address_mismatch")
            await self._quarantine.delete(upload.storage_key)
            return prior
        if upload.expires_at <= self._clock():
            raise DrainRejected("artifact_expired")
        if not 0 <= upload.size_bytes <= self._max_bytes:
            raise DrainRejected("artifact_size_limit")
        try:
            content = await self._quarantine.read(upload.storage_key, max_bytes=upload.size_bytes)
        except IngressRejected as rejected:
            if rejected.code == "artifact_size_mismatch":
                raise DrainRejected("artifact_size_mismatch") from None
            raise
        if len(content) != upload.size_bytes:
            raise DrainRejected("artifact_size_mismatch")
        if "sha256:" + sha256(content).hexdigest() != upload.digest:
            raise DrainRejected("artifact_digest_mismatch")
        # Recheck after network I/O before any custody write.
        await self._authority.require_current(upload)
        if upload.expires_at <= self._clock():
            raise DrainRejected("artifact_expired")
        address = await self._payloads.stage(
            artifact_id=f"ingress-{upload.upload_id}",
            content=content,
            content_digest=upload.digest,
            media_type=upload.media_type,
        )
        if address.content_digest != upload.digest or address.size_bytes != upload.size_bytes:
            raise DrainRejected("custody_address_mismatch")
        await self._authority.verified(upload, address)
        await self._quarantine.delete(upload.storage_key)
        return address
