"""Replay, dry run (1.4.4, tracing Stage 1, P4.3 / TR-D11): the model input of one step,
reconstructed from the Transcript alone and checked against the recorded digests.

The `model_request` frame of a point's range (`adapters/deep_agents/frames.py::
model_request_capture`; ledger 5.10) lists the exact batch `[system, *messages]` by message
id, type and body digest, plus the digest of the whole batch. Every entry resolves to bytes
the Transcript already holds:

- an AI or tool message is a frame (`message`, `tool_call_completed`, `tool_call_failed`)
  whose body is exactly `frame_message_body(m)`: the frame with the entry's digest, else the
  frame of the same kind whose body `id` is the entry's id; the body is the excerpt when the
  frame is inline, else the promoted body through the granted reader;
- a human or system message is a promoted object: the entry's `ref`
  (`frame-body://sha256:<hex>?bytes=<n>&type=<media>`) through the granted reader.

The batch is then serialized the way the observer did (`domain/frames/body.py::
batch_frame_body`, the one rule) and its digest compared with the frame's `batch_digest`.
`exact` is true only when every message resolved and the two digests agree. Nothing is sent
to any model: a paid replay (`--model NAME`) is a later decision.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, Final, Literal

from pydantic import Field

from mission_control.application.execution.cognition_point_reads import (
    LIST_PERMISSION,
    CognitionPointReadService,
)
from mission_control.application.frames.artifact_bodies import (
    ARTIFACT_READ_PERMISSION,
    ArtifactBodyMissing,
)
from mission_control.application.frames.transcript import ArtifactBodyReader, _int
from mission_control.domain.frames.body import batch_frame_body, frame_body
from mission_control.domain.frames.contracts import FrameContract, FrameKind, ProviderFrame
from mission_control.domain.policies.contracts import ActorContext

REPLAY_REPORT_SCHEMA: Final = "mc.replay_report.v1"
REPLAY_PERMISSION = ARTIFACT_READ_PERMISSION

_AI_KINDS: frozenset[FrameKind] = frozenset({FrameKind.MESSAGE})
_TOOL_KINDS: frozenset[FrameKind] = frozenset(
    {FrameKind.TOOL_CALL_COMPLETED, FrameKind.TOOL_CALL_FAILED}
)
_FRAME_MESSAGE_TYPES: Mapping[str, frozenset[FrameKind]] = {
    "ai": _AI_KINDS,
    "tool": _TOOL_KINDS,
    "function": _TOOL_KINDS,
}

MessageSource = Literal["frame", "object", "missing"]


class ReplayDenied(PermissionError):
    code = "unauthorized"


class ReplayUnavailable(RuntimeError):
    """No body reader or frame reader is composed, or a request body cannot be read."""

    code = "replay_unavailable"


class ModelRequestNotFound(LookupError):
    """The point's range holds no `model_request` frame (or none with the call index)."""

    code = "model_request_not_found"


class ReplayMessage(FrameContract):
    """One position of the reconstructed batch (the system message first, when present)."""

    index: int = Field(ge=0)
    id: str | None = None
    type: str
    digest: str | None = None
    """The digest the `model_request` frame recorded for this message."""
    reconstructed_digest: str | None = None
    source: MessageSource
    frame_id: str | None = None
    ref: str | None = None
    reason: str | None = None


class ReplayDifference(FrameContract):
    index: int = Field(ge=0)
    id: str | None = None
    recorded_digest: str | None = None
    reconstructed_digest: str | None = None


class ReplayReport(FrameContract):
    """`mc.replay_report.v1`: the dry-run comparison for one model call of one point."""

    schema_version: Literal["mc.replay_report.v1"] = REPLAY_REPORT_SCHEMA
    run_id: str
    point_id: str
    frame_id: str
    arrival_ordinal: int = Field(ge=1)
    call_index: int | None = None
    model: str | None = None
    batch_digest_recorded: str | None = None
    batch_digest_reconstructed: str | None = None
    exact: bool
    first_difference: ReplayDifference | None = None
    messages: tuple[ReplayMessage, ...] = ()
    batch: list[dict[str, Any]] | None = None
    """The reconstructed message bodies, when `exact` or asked for (`include_batch`)."""


class _Resolved:
    __slots__ = ("body", "message")

    def __init__(self, message: ReplayMessage, body: dict[str, Any] | None) -> None:
        self.message = message
        self.body = body


class ReplayService:
    """Dry-run replay over the point read service and the granted body reader."""

    def __init__(
        self,
        points: CognitionPointReadService,
        *,
        artifacts: ArtifactBodyReader | None = None,
    ) -> None:
        self._points = points
        self._artifacts = artifacts if artifacts is not None else points.artifacts

    @property
    def request_scope(self) -> str:
        return self._points.request_scope

    async def dry_run(
        self,
        request_scope: str,
        actor: ActorContext,
        run_id: str,
        point_id: str,
        *,
        call_index: int | None = None,
        include_batch: bool = False,
    ) -> ReplayReport:
        if request_scope != self._points.request_scope:
            raise ReplayDenied("replay service serves another tenant scope")
        for permission in (LIST_PERMISSION, REPLAY_PERMISSION):
            if permission not in actor.permissions:
                raise ReplayDenied(f"actor lacks {permission}")
        if self._artifacts is None:
            raise ReplayUnavailable("no artifact body reader is composed for replay")
        frames = await self._points.frames_for_point(run_id, point_id)
        request = await self._select_request(frames, actor, call_index)
        if request is None:
            raise ModelRequestNotFound(point_id)
        frame, body = request
        run_frames = await self._points.frames_for_run(frame.run_id)
        resolved = await self._reconstruct(body, run_frames, actor)
        bodies = [item.body for item in resolved]
        complete = all(item is not None for item in bodies)
        reconstructed = (
            batch_frame_body([item for item in bodies if item is not None]).digest
            if complete and bodies
            else None
        )
        recorded = _string(body.get("batch_digest"))
        exact = reconstructed is not None and reconstructed == recorded
        difference = next(
            (
                ReplayDifference(
                    index=item.message.index,
                    id=item.message.id,
                    recorded_digest=item.message.digest,
                    reconstructed_digest=item.message.reconstructed_digest,
                )
                for item in resolved
                if item.message.reconstructed_digest != item.message.digest
            ),
            None,
        )
        model = body.get("model")
        return ReplayReport(
            run_id=run_id,
            point_id=point_id,
            frame_id=str(frame.frame_id),
            arrival_ordinal=frame.arrival_ordinal,
            call_index=_int(body.get("call_index")),
            model=_string(model.get("name")) if isinstance(model, Mapping) else _string(model),
            batch_digest_recorded=recorded,
            batch_digest_reconstructed=reconstructed,
            exact=exact,
            first_difference=difference,
            messages=tuple(item.message for item in resolved),
            batch=(
                [item for item in bodies if item is not None]
                if complete and (exact or include_batch)
                else None
            ),
        )

    async def _select_request(
        self, frames: Sequence[ProviderFrame], actor: ActorContext, call_index: int | None
    ) -> tuple[ProviderFrame, dict[str, Any]] | None:
        requests = sorted(
            (frame for frame in frames if frame.kind is FrameKind.MODEL_REQUEST),
            key=lambda frame: frame.arrival_ordinal,
        )
        if not requests:
            return None
        if call_index is None:
            frame = requests[-1]
            body = await self._whole_body(frame, actor)
            if body is None:
                raise ReplayUnavailable("the model_request body is not readable")
            return frame, body
        for frame in requests:
            body = await self._whole_body(frame, actor)
            if body is not None and _int(body.get("call_index")) == call_index:
                return frame, body
        return None

    async def _reconstruct(
        self, request: Mapping[str, Any], frames: Sequence[ProviderFrame], actor: ActorContext
    ) -> list[_Resolved]:
        by_digest: dict[str, ProviderFrame] = {}
        for frame in frames:
            if frame.kind in _AI_KINDS or frame.kind in _TOOL_KINDS:
                by_digest.setdefault(frame.body_digest, frame)
        resolved: list[_Resolved] = []
        system = request.get("system")
        if isinstance(system, Mapping):
            resolved.append(await self._object(0, {"type": "system", **system}, actor))
        entries = request.get("messages")
        for entry in entries if isinstance(entries, list) else ():
            if not isinstance(entry, Mapping):
                continue
            index = len(resolved)
            kind = _string(entry.get("type")) or "unknown"
            if entry.get("ref"):
                resolved.append(await self._object(index, entry, actor))
            elif kind in _FRAME_MESSAGE_TYPES:
                resolved.append(await self._frame(index, entry, by_digest, frames, actor))
            else:
                resolved.append(_missing(index, entry, "no_reference"))
        return resolved

    async def _object(self, index: int, entry: Mapping[str, Any], actor: ActorContext) -> _Resolved:
        ref = _string(entry.get("ref"))
        recorded = _string(entry.get("digest"))
        kind = _string(entry.get("type")) or "unknown"
        identity = _string(entry.get("id"))
        if ref is None or self._artifacts is None:
            return _missing(index, entry, "no_reference")
        try:
            text = await self._artifacts.read(self._points.request_scope, actor, ref)
            body = json.loads(text)
        except ArtifactBodyMissing as error:
            return _missing(index, entry, f"object_unavailable: {error}", ref=ref)
        except ValueError:
            return _missing(index, entry, "object_not_json", ref=ref)
        if not isinstance(body, dict):
            return _missing(index, entry, "object_not_a_message", ref=ref)
        return _Resolved(
            ReplayMessage(
                index=index,
                id=identity,
                type=kind,
                digest=recorded,
                reconstructed_digest=frame_body(body).digest,
                source="object",
                ref=ref,
            ),
            body,
        )

    async def _frame(
        self,
        index: int,
        entry: Mapping[str, Any],
        by_digest: Mapping[str, ProviderFrame],
        frames: Sequence[ProviderFrame],
        actor: ActorContext,
    ) -> _Resolved:
        recorded = _string(entry.get("digest"))
        kind = _string(entry.get("type")) or "unknown"
        identity = _string(entry.get("id"))
        kinds = _FRAME_MESSAGE_TYPES[kind]
        frame = by_digest.get(recorded) if recorded is not None else None
        if frame is not None and frame.kind not in kinds:
            frame = None
        body: dict[str, Any] | None = None
        if frame is not None:
            body = await self._whole_body(frame, actor)
        if body is None and identity is not None:
            frame, body = await self._frame_by_id(identity, kinds, frames, actor)
        if frame is None or body is None:
            return _missing(
                index,
                entry,
                "body_unavailable" if frame is not None else "no_frame_for_message",
                frame_id=str(frame.frame_id) if frame is not None else None,
            )
        return _Resolved(
            ReplayMessage(
                index=index,
                id=identity,
                type=kind,
                digest=recorded,
                reconstructed_digest=frame_body(body).digest,
                source="frame",
                frame_id=str(frame.frame_id),
            ),
            body,
        )

    async def _frame_by_id(
        self,
        identity: str,
        kinds: frozenset[FrameKind],
        frames: Sequence[ProviderFrame],
        actor: ActorContext,
    ) -> tuple[ProviderFrame | None, dict[str, Any] | None]:
        """The latest frame of the kinds whose whole body carries `id == identity`."""

        marker = json.dumps(identity, ensure_ascii=False)
        candidates = sorted(
            (frame for frame in frames if frame.kind in kinds),
            key=lambda frame: frame.arrival_ordinal,
            reverse=True,
        )
        for frame in candidates:
            inline = _inline(frame)
            if inline is not None:
                if inline.get("id") == identity:
                    return frame, inline
                continue
            # Truncated: the canonical excerpt sorts `content` before `id`, so a long
            # content hides the id; only a frame whose excerpt does not already name
            # another id is worth the promoted read.
            if f'"id":{marker}' not in frame.body_excerpt and '"id":"' in frame.body_excerpt:
                continue
            body = await self._whole_body(frame, actor)
            if body is not None and body.get("id") == identity:
                return frame, body
        return None, None

    async def _whole_body(self, frame: ProviderFrame, actor: ActorContext) -> dict[str, Any] | None:
        inline = _inline(frame)
        if inline is not None:
            return inline
        if frame.body_artifact_ref is None or self._artifacts is None:
            return None
        try:
            text = await self._artifacts.read(
                self._points.request_scope, actor, frame.body_artifact_ref
            )
            value = json.loads(text)
        except (ArtifactBodyMissing, ValueError):
            return None
        return value if isinstance(value, dict) else None


def _inline(frame: ProviderFrame) -> dict[str, Any] | None:
    """The whole body when the excerpt holds all of it (`body.state: inline`)."""

    if len(frame.body_excerpt.encode("utf-8")) < frame.body_bytes:
        return None
    try:
        value = json.loads(frame.body_excerpt)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _missing(
    index: int,
    entry: Mapping[str, Any],
    reason: str,
    *,
    ref: str | None = None,
    frame_id: str | None = None,
) -> _Resolved:
    """A message the replay could not reconstruct, and why (Tracing Stage 3, clean code)."""

    return _Resolved(
        ReplayMessage(
            index=index,
            id=_string(entry.get("id")),
            type=_string(entry.get("type")) or "unknown",
            digest=_string(entry.get("digest")),
            source="missing",
            ref=ref,
            frame_id=frame_id,
            reason=reason,
        ),
        None,
    )


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


__all__ = [
    "REPLAY_PERMISSION",
    "REPLAY_REPORT_SCHEMA",
    "ModelRequestNotFound",
    "ReplayDenied",
    "ReplayDifference",
    "ReplayMessage",
    "ReplayReport",
    "ReplayService",
    "ReplayUnavailable",
]
