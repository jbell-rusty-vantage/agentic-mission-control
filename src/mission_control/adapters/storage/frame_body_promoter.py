"""`FrameBodyPromoter` over the content-addressed artifact payload store (1.4.4, TR-D3).

A promoted frame body goes where settlement outputs go (`ArtifactPayloadPort.stage`, the
same `sha256` address space) and is referenced as `frame-body://sha256:<hex>?bytes=<n>&type=
<media>` (`application/frames/body_refs.py`). No `artifact_metadata_revision`
row and no durable-reference admit: the frame row already registers the body's digest, size
and media type. Staging is idempotent, so the same bytes promoted twice (two frames, two runs,
a retried activity) return the same reference and occupy one object.
"""

from __future__ import annotations

from hashlib import sha256

from mission_control.application.artifacts.artifact_promotion import ArtifactPayloadPort
from mission_control.application.frames.body_refs import frame_body_ref
from mission_control.domain.execution.errors import WorkspaceDigestMismatch
from mission_control.domain.frames.contracts import FrameKind, HarnessExecutionHandle


class PayloadStoreFrameBodyPromoter:
    """Stages frame bodies in the artifact payload store; see the module docstring."""

    def __init__(self, payloads: ArtifactPayloadPort) -> None:
        self._payloads = payloads

    async def promote_frame_body(
        self,
        handle: HarnessExecutionHandle,
        *,
        promotion_key: str,
        kind: FrameKind,
        digest: str,
        media_type: str,
        payload: bytes,
    ) -> str:
        del handle, kind  # content-addressed: the body belongs to no run and no kind
        actual = f"sha256:{sha256(payload).hexdigest()}"
        if digest != actual:
            raise WorkspaceDigestMismatch(
                f"frame body digest mismatch: declared {digest}, payload is {actual}"
            )
        address = await self._payloads.stage(
            artifact_id=f"frame-body:{promotion_key}",
            content=payload,
            content_digest=digest,
            media_type=media_type,
        )
        # The owner's scheme names the body by digest alone (TR-D3); the reader asks the
        # same content-addressed store for the address (`address_for`).
        return frame_body_ref(
            digest=address.content_digest, size_bytes=address.size_bytes, media_type=media_type
        )


__all__ = ["PayloadStoreFrameBodyPromoter"]
