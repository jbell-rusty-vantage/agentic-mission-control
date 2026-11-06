"""Lane-neutral frame writer: identity, arrival ordinal and body handling (SPEC-03).

A lane writer turns provider events into `FrameObservation`s (provider key, raw kind,
classified kind, JSON body, native refs). `FrameWriter` stamps each with the harness
execution handle, a monotonic `arrival_ordinal` (seeded from the store's last cursor so a
resumed activity continues the sequence), redacts, digests and excerpts the body under
the application's cap, promotes an oversized closing body through the capture policy and
the promoter (`frame-body://`, 1.4.4 TR-D3), and appends in arrival order. It is shared by
the Deep Agents writer, the Cursor writers (G3/G5) and hook callbacks.

Capture behaviour (which kinds, which cap, where bodies go) is chosen in composition
(`application/frames/capture_policy.py`, `MISSION_CONTROL_FRAME_CAPTURE_PROFILE`), never by
a manifest. `promote_object` lets a recorder store an object that is not a frame body of its
own (a `model_request`'s per-message objects, or the whole batch under `full_requests`).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from hashlib import sha256

from mission_control.application.frames.capture_policy import (
    FULL_BODY_MAX_BYTES,
    STANDARD_PROFILE,
    FrameBodyPromoter,
    FrameCapturePolicy,
)
from mission_control.application.frames.sink import FrameOrdinalConflict, FrameSink
from mission_control.contracts.identities import uuid7
from mission_control.domain.frames.body import frame_body
from mission_control.domain.frames.contracts import (
    DEFAULT_EXCERPT_CAP_BYTES,
    AppendReceipt,
    FrameKind,
    FrameObservation,
    HarnessExecutionHandle,
    ProviderFrame,
    is_closing,
)
from mission_control.domain.frames.lifecycle import LIFECYCLE_BODY_KINDS, lifecycle_body

logger = logging.getLogger(__name__)

MAX_ORDINAL_RETRIES = 4


def _utc_now() -> datetime:
    return datetime.now(UTC)


class FrameWriter:
    """Writes one harness execution's frames in arrival order through a FrameSink."""

    def __init__(
        self,
        sink: FrameSink,
        handle: HarnessExecutionHandle,
        *,
        excerpt_cap_bytes: int = DEFAULT_EXCERPT_CAP_BYTES,
        secret_values: Iterable[str] = (),
        clock: Callable[[], datetime] = _utc_now,
        promoter: FrameBodyPromoter | None = None,
        capture: FrameCapturePolicy = STANDARD_PROFILE,
    ) -> None:
        self._sink = sink
        self._handle = handle
        self._cap = excerpt_cap_bytes
        self._secrets = tuple(secret_values)
        self._clock = clock
        self._promoter = promoter
        self._capture = capture
        self._promoted: dict[tuple[FrameKind, str], str] = {}
        self._next = (handle.last_cursor.arrival_ordinal if handle.last_cursor else 0) + 1
        self.receipt = AppendReceipt(new=0, duplicate=0, stale=0)

    @property
    def handle(self) -> HarnessExecutionHandle:
        return self._handle

    @property
    def capture(self) -> FrameCapturePolicy:
        return self._capture

    @property
    def promotes(self) -> bool:
        """Whether a body can be stored at all (a promoter was composed in)."""

        return self._promoter is not None

    async def write(self, observations: Sequence[FrameObservation]) -> AppendReceipt:
        if not observations:
            return AppendReceipt(new=0, duplicate=0, stale=0)
        prepared = [await self._prepare(item) for item in observations]
        for _attempt in range(MAX_ORDINAL_RETRIES):
            frames = [
                frame.model_copy(update={"arrival_ordinal": self._next + offset})
                for offset, frame in enumerate(prepared)
            ]
            try:
                receipt = await self._sink.append(frames)
            except FrameOrdinalConflict:
                cursor = await self._sink.last_cursor(
                    self._handle.harness_execution_id,
                    self._handle.generation,
                    request_scope=self._handle.request_scope,
                )
                self._next = (cursor.arrival_ordinal if cursor else 0) + 1
                continue
            self._next += len(frames)
            self.receipt = self.receipt + receipt
            return receipt
        raise FrameOrdinalConflict("arrival ordinals kept colliding with another writer")

    async def promote_object(
        self, *, kind: FrameKind, payload: bytes, media_type: str, promotion_key: str
    ) -> str | None:
        """Store an object the frame of `kind` refers to and return its `frame-body://`
        reference, or None when nothing is stored: no promoter was composed, the payload
        exceeds the profile's body ceiling, or `kind` is `model_request` and the profile keeps
        no per-message objects. A caller promotes a whole request batch only when
        `writer.capture.full_requests` says so. Identical bytes for the same kind are stored
        once per writer (and the store is content-addressed besides)."""

        if self._promoter is None or len(payload) > self._capture.max_body_bytes:
            return None
        if kind is FrameKind.MODEL_REQUEST and not self._capture.message_objects:
            return None
        return await self._promote(
            self._promoter,
            kind=kind,
            digest=f"sha256:{sha256(payload).hexdigest()}",
            media_type=media_type,
            payload=payload,
            promotion_key=promotion_key,
        )

    async def _promote(
        self,
        promoter: FrameBodyPromoter,
        *,
        kind: FrameKind,
        digest: str,
        media_type: str,
        payload: bytes,
        promotion_key: str,
    ) -> str:
        """The cached reference of `(kind, digest)`, or the promoter's for a first store."""

        cached = self._promoted.get((kind, digest))
        if cached is not None:
            return cached
        reference = await promoter.promote_frame_body(
            self._handle,
            promotion_key=self._promotion_key(promotion_key),
            kind=kind,
            digest=digest,
            media_type=media_type,
            payload=payload,
        )
        self._promoted[(kind, digest)] = reference
        return reference

    def _promotion_key(self, suffix: str) -> str:
        return f"{self._handle.harness_execution_id}:{self._handle.generation}:{suffix}"

    async def _prepare(self, observation: FrameObservation) -> ProviderFrame:
        body = frame_body(
            observation.body, excerpt_cap_bytes=self._cap, secret_values=self._secrets
        )
        artifact_ref: str | None = None
        if self._promoter is not None and self._capture.eligible(
            observation.kind, body.body_bytes, self._cap
        ):
            try:
                artifact_ref = await self._promote(
                    self._promoter,
                    kind=observation.kind,
                    digest=body.digest,
                    media_type=observation.body_media_type,
                    payload=body.canonical,
                    promotion_key=observation.provider_key,
                )
            except Exception:
                # Tracing Stage 3 (R3-F14): the frame is the record and the provider event
                # already happened; a payload store that fails keeps the excerpt (the body's
                # digest and size say it is partial) instead of aborting the turn.
                logger.warning(
                    "the body of frame %s was not promoted; the excerpt is kept",
                    observation.provider_key,
                    exc_info=True,
                )
        handle = self._handle
        return ProviderFrame(
            frame_id=uuid7(),
            scope=handle.scope,
            run_id=handle.run_id,
            activation_id=handle.activation_id,
            attempt_no=handle.attempt_no,
            harness_execution_id=handle.harness_execution_id,
            generation=handle.generation,
            lane_profile=handle.lane_profile,
            native_session_ref=observation.native_session_ref or handle.native_session_ref,
            native_turn_ref=observation.native_turn_ref,
            provider_key=observation.provider_key,
            arrival_ordinal=self._next,
            observed_at=observation.observed_at or self._clock(),
            provider_timestamp=observation.provider_timestamp,
            kind=observation.kind,
            closing=is_closing(observation.kind),
            subordinate_ref=observation.subordinate_ref,
            tool_call_ref=observation.tool_call_ref,
            body_digest=body.digest,
            body_bytes=body.body_bytes,
            body_media_type=observation.body_media_type,
            body_excerpt=body.excerpt,
            body_artifact_ref=artifact_ref,
            lifecycle_body=(
                lifecycle_body(json.loads(body.canonical))
                if observation.kind.value in LIFECYCLE_BODY_KINDS
                and body.body_bytes > len(body.excerpt.encode("utf-8"))
                else {}
            ),
            redactions=body.redactions,
            raw_kind=observation.raw_kind,
        )


__all__ = [
    "FULL_BODY_MAX_BYTES",
    "MAX_ORDINAL_RETRIES",
    "FrameBodyPromoter",
    "FrameWriter",
]
