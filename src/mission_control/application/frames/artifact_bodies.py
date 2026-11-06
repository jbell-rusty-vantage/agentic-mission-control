"""Full transcript bodies through the artifact read path (SPEC-03 `--full`).

`GrantedArtifactBodyReader` resolves a transcript entry's `artifact_ref` to bytes under the
caller's grant. Two reference families are served:

- a durable `artifact://<request_scope>/<run_id>/<artifact_id>` reference (or
  `artifact:<id>`): the actor needs the artifact read grant on top of `workflow_run.read`,
  the artifact must belong to the service's tenant scope (and to the reference's run when it
  names one), and only admitted, non-prohibited revisions are read;
- a `frame-body://sha256:<hex>?bytes=<n>&type=<media>` reference (1.4.4, TR-D3;
  `application/frames/body_refs.py`): a promoted frame body in the content-addressed
  payload store, with no metadata row. The same grant (`workflow.result.read`) and tenant
  scope check apply; the body is located by its digest alone (`address_for`) and verified
  against the digest and byte count. Frame bodies are content-addressed and shared, not per
  run: the reference proves nothing about which run produced it.

Tracing Stage 3 (R4-F6): a read for a named run (`read_bytes(..., run_id=...)`, what the
download route does) is bound to that run. A `frame-body://` digest must be referenced by a
frame of the run in the reader's tenant scope (`FrameBodyIndex`), and the byte count and
media type are the frame row's, never the caller's; a durable artifact must be the run's.
Without a composed index a run-bound frame-body read is refused. The in-process callers (the
transcript's `--full`, replay) read references their own scoped frame rows hold.

OVE-204 slice 5: a `closure-body://sha256:<hex>?bytes=<n>&type=<media>` reference names a
promoted Workspace Closure body (`domain/execution/workspace_closure.py`). It is served only
run-bound: the digest must be a promoted body of one of the run's closures
(`ClosureBodyIndex`), whose entry row gives the byte count and media type. A body larger than
the cap is recorded in the closure but refused here (`payload_too_large`).

The payload store verifies the content digest and size on retrieval; the 4 000 000-byte cap
applies to every family.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Final, Protocol

from mission_control.application.artifacts.artifact_promotion import ArtifactPayloadAddress
from mission_control.application.frames.body_refs import (
    MalformedFrameBodyRef,
    is_frame_body_ref,
    parse_frame_body_ref,
)
from mission_control.domain.execution.contracts import (
    ArtifactMetadataRevision,
    ArtifactPromotionState,
)
from mission_control.domain.execution.errors import WorkspaceDigestMismatch
from mission_control.domain.execution.workspace_closure import (
    MalformedClosureRef,
    is_closure_body_ref,
    parse_closure_body_ref,
)
from mission_control.domain.policies.contracts import ActorContext

ARTIFACT_READ_PERMISSION: Final = "workflow.result.read"
MAX_FULL_BODY_BYTES: Final = 4_000_000
_DURABLE_PREFIX: Final = "artifact://"
_SHORT_PREFIX: Final = "artifact:"


class ArtifactBodyDenied(PermissionError):
    code = "unauthorized"


class ArtifactBodyMissing(LookupError):
    code = "artifact_unavailable"


class ArtifactBodyTooLarge(ArtifactBodyMissing):
    """The body exists but exceeds the full-body cap (HTTP 413 on the download route)."""

    code = "payload_too_large"


class ArtifactMetadataReader(Protocol):
    async def get_by_artifact(self, artifact_id: str) -> ArtifactMetadataRevision | None: ...


class ArtifactPayloadReader(Protocol):
    async def retrieve(self, address: ArtifactPayloadAddress) -> bytes: ...


class ContentAddressedPayloadReader(ArtifactPayloadReader, Protocol):
    """A payload store that derives the address of a digest the way its `stage` did
    (1.4.4): what a bare `frame-body://` reference needs to be read."""

    def address_for(self, *, content_digest: str, size_bytes: int) -> ArtifactPayloadAddress: ...


@dataclass(frozen=True, slots=True)
class FrameBodyRecord:
    """What a frame row of the run says about a promoted body it references (R4-F6)."""

    size_bytes: int
    media_type: str


class FrameBodyIndex(Protocol):
    """Tracing Stage 3 (R4-F6): binds a `frame-body://` digest to a run. `None` unless a
    frame of the run (by run key, in the scope) references the digest as its promoted body,
    or a `model_request` frame of the run names it as one of its message bodies."""

    async def run_frame_body(
        self, request_scope: str, run_key: str, digest: str
    ) -> FrameBodyRecord | None: ...


class ClosureBodyIndex(Protocol):
    """OVE-204 slice 5: binds a `closure-body://` digest to a run. `None` unless a Workspace
    Closure of the run (by run key, in the scope) holds the digest as a promoted body."""

    async def run_closure_body(
        self, request_scope: str, run_key: str, digest: str
    ) -> FrameBodyRecord | None: ...


def parse_artifact_ref(artifact_ref: str) -> tuple[str | None, str | None, str]:
    """(request scope, run id, artifact id) of a durable or short artifact reference."""

    if artifact_ref.startswith(_DURABLE_PREFIX):
        rest = artifact_ref.removeprefix(_DURABLE_PREFIX)
        scope, _sep, tail = rest.rpartition("/")
        scope, _sep, run_id = scope.rpartition("/")
        if not scope or not run_id or not tail:
            raise ArtifactBodyMissing("malformed artifact reference")
        return scope, run_id, tail
    if artifact_ref.startswith(_SHORT_PREFIX) and len(artifact_ref) > len(_SHORT_PREFIX):
        return None, None, artifact_ref.removeprefix(_SHORT_PREFIX)
    raise ArtifactBodyMissing("not an artifact reference")


class GrantedArtifactBodyReader:
    """`ArtifactBodyReader` over artifact metadata and the artifact payload store."""

    def __init__(
        self,
        metadata: ArtifactMetadataReader,
        payloads: ContentAddressedPayloadReader,
        *,
        request_scope: str,
        max_bytes: int = MAX_FULL_BODY_BYTES,
        frames: FrameBodyIndex | None = None,
        closures: ClosureBodyIndex | None = None,
    ) -> None:
        self._metadata = metadata
        self._payloads = payloads
        self.request_scope = request_scope
        self._max_bytes = max_bytes
        self._frames = frames
        self._closures = closures

    async def read(self, request_scope: str, actor: ActorContext, artifact_ref: str) -> str:
        content, _media_type = await self.read_bytes(request_scope, actor, artifact_ref)
        return content.decode("utf-8", errors="replace")

    async def read_bytes(
        self,
        request_scope: str,
        actor: ActorContext,
        artifact_ref: str,
        *,
        run_id: str | None = None,
    ) -> tuple[bytes, str]:
        """The verified bytes of a reference and their media type (TR-D3, the download route).

        The same grant, tenant scope, digest verification and byte cap as `read`. With
        `run_id` (the route's path run) the read is bound to that run (R4-F6): a frame body's
        byte count and media type are the run's frame row's; without it they are the
        reference's (in-process callers pass references their own frame rows hold).
        """

        if ARTIFACT_READ_PERMISSION not in actor.permissions:
            raise ArtifactBodyDenied(f"actor lacks {ARTIFACT_READ_PERMISSION}")
        if request_scope != self.request_scope:
            raise ArtifactBodyDenied("artifact reader serves another tenant scope")
        if is_frame_body_ref(artifact_ref):
            return await self._read_frame_body(artifact_ref, run_id=run_id)
        if is_closure_body_ref(artifact_ref):
            return await self._read_closure_body(artifact_ref, run_id=run_id)
        ref_scope, ref_run, artifact_id = parse_artifact_ref(artifact_ref)
        if ref_scope is not None and ref_scope != request_scope:
            raise ArtifactBodyDenied("artifact reference names another tenant scope")
        revision = await self._metadata.get_by_artifact(artifact_id)
        if revision is None or revision.request_scope != request_scope:
            raise ArtifactBodyMissing("artifact not found")
        # Tracing Stage 3 (R4-F6): the artifact is the reference's run's and, for a run-bound
        # read, the path run's (the short `artifact:<id>` form names no run of its own).
        if ref_run is not None and revision.run_id != ref_run:
            raise ArtifactBodyMissing("artifact not found")
        if run_id is not None and revision.run_id != run_id:
            raise ArtifactBodyMissing("artifact not found")
        if revision.permission_outcome == "prohibited":
            raise ArtifactBodyDenied("artifact read is prohibited by its permission outcome")
        if revision.state != ArtifactPromotionState.ADMITTED or revision.object_ref is None:
            raise ArtifactBodyMissing("artifact is not admitted")
        if revision.size_bytes > self._max_bytes:
            raise ArtifactBodyTooLarge("artifact body exceeds the transcript full-body cap")
        content = await self._payloads.retrieve(
            ArtifactPayloadAddress(
                object_ref=revision.object_ref,
                content_digest=revision.content_digest,
                size_bytes=revision.size_bytes,
            )
        )
        return content, revision.media_type

    async def _read_frame_body(self, artifact_ref: str, *, run_id: str | None) -> tuple[bytes, str]:
        """A promoted frame body: located by digest, verified by digest and byte count."""

        try:
            ref = parse_frame_body_ref(artifact_ref)
        except MalformedFrameBodyRef as error:
            raise ArtifactBodyMissing(f"malformed frame body reference: {error}") from None
        size_bytes, media_type = ref.bytes, ref.media_type
        if run_id is not None:
            # Tracing Stage 3 (R4-F6): a digest the run's frames do not reference is absent
            # (a tenant cannot read another's body by digest); size and type are the row's.
            if self._frames is None:
                raise ArtifactBodyMissing("frame bodies cannot be bound to a run here")
            record = await self._frames.run_frame_body(self.request_scope, run_id, ref.digest)
            if record is None:
                raise ArtifactBodyMissing("the run references no such frame body")
            size_bytes, media_type = record.size_bytes, record.media_type
        if size_bytes > self._max_bytes:
            raise ArtifactBodyTooLarge("frame body exceeds the transcript full-body cap")
        try:
            content = await self._payloads.retrieve(
                self._payloads.address_for(content_digest=ref.digest, size_bytes=size_bytes)
            )
        except (WorkspaceDigestMismatch, LookupError, OSError) as error:
            raise ArtifactBodyMissing(f"frame body unavailable: {error}") from None
        actual = f"sha256:{sha256(content).hexdigest()}"
        if actual != ref.digest or len(content) != size_bytes:
            raise ArtifactBodyMissing("frame body does not match its reference")
        return content, media_type

    async def _read_closure_body(
        self, artifact_ref: str, *, run_id: str | None
    ) -> tuple[bytes, str]:
        """A promoted Workspace Closure body: always run-bound, verified like a frame body."""

        try:
            ref = parse_closure_body_ref(artifact_ref)
        except MalformedClosureRef as error:
            raise ArtifactBodyMissing(f"malformed closure body reference: {error}") from None
        if run_id is None or self._closures is None:
            raise ArtifactBodyMissing("closure bodies are read only for a named run")
        record = await self._closures.run_closure_body(self.request_scope, run_id, ref.digest)
        if record is None:
            raise ArtifactBodyMissing("the run's closures hold no such body")
        if record.size_bytes > self._max_bytes:
            raise ArtifactBodyTooLarge("closure body exceeds the full-body download cap")
        try:
            content = await self._payloads.retrieve(
                self._payloads.address_for(content_digest=ref.digest, size_bytes=record.size_bytes)
            )
        except (WorkspaceDigestMismatch, LookupError, OSError) as error:
            raise ArtifactBodyMissing(f"closure body unavailable: {error}") from None
        actual = f"sha256:{sha256(content).hexdigest()}"
        if actual != ref.digest or len(content) != record.size_bytes:
            raise ArtifactBodyMissing("closure body does not match its reference")
        return content, record.media_type


__all__ = [
    "ARTIFACT_READ_PERMISSION",
    "MAX_FULL_BODY_BYTES",
    "ArtifactBodyDenied",
    "ArtifactBodyMissing",
    "ArtifactBodyTooLarge",
    "ClosureBodyIndex",
    "ContentAddressedPayloadReader",
    "FrameBodyIndex",
    "FrameBodyRecord",
    "GrantedArtifactBodyReader",
    "parse_artifact_ref",
]
