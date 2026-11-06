"""FrameWriter + FrameSink semantics on the in-memory store (SPEC-03 write path)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import pytest

from mission_control.adapters.storage.artifact_payloads import InMemoryArtifactPayloadStore
from mission_control.adapters.storage.frame_body_promoter import PayloadStoreFrameBodyPromoter
from mission_control.application.frames.artifact_bodies import (
    ArtifactBodyDenied,
    ArtifactBodyMissing,
    GrantedArtifactBodyReader,
)
from mission_control.application.frames.body_refs import parse_frame_body_ref
from mission_control.application.frames.capture_policy import (
    FULL_REQUESTS_PROFILE,
    STANDARD_PROFILE,
    FrameCapturePolicy,
)
from mission_control.application.frames.sink import (
    FrameOrdinalConflict,
    FrameSink,
    HarnessExecutionNotFound,
    InMemoryFrameStore,
)
from mission_control.application.frames.writer import FrameWriter
from mission_control.domain.frames.contracts import (
    AppendReceipt,
    FrameKind,
    HarnessExecutionHandle,
    ProviderCursor,
    ProviderFrame,
)
from mission_control.domain.policies.contracts import ActorContext
from tests.fixtures.provider_frames import (
    OTHER_SCOPE,
    SCOPE,
    StepClock,
    harness_start,
    in_memory_store,
    observation,
    opened_writer,
    turn_observations,
)


@pytest.mark.asyncio
async def test_append_is_idempotent_and_ordered_and_identity_records_follow() -> None:
    store, run_id = in_memory_store()
    writer, handle = await opened_writer(store)
    receipt = await writer.write(turn_observations())
    assert (receipt.new, receipt.duplicate, receipt.stale) == (9, 0, 0)
    frames = await store.frames_for_execution(SCOPE, handle.harness_execution_id, 1)
    assert [frame.arrival_ordinal for frame in frames] == list(range(1, 10))
    assert all(
        frame.run_id == run_id and frame.native_session_ref == "thread-1" for frame in frames
    )
    assert [frame.kind for frame in frames if frame.closing] == [
        FrameKind.USAGE,
        FrameKind.TOOL_CALL_COMPLETED,
        FrameKind.USAGE,
        FrameKind.TURN_ENDED,
        FrameKind.RUN_RESULT,
    ]
    # Re-running the writer over the same stream adds zero rows.
    replay = await writer.write(turn_observations())
    assert (replay.new, replay.duplicate) == (0, 9)
    assert len(await store.frames_for_run(SCOPE, run_id)) == 9
    turns = store.turns(handle.harness_execution_id)
    assert len(turns) == 1 and turns[0]["started_frame_id"] == frames[1].frame_id
    assert turns[0]["ended_frame_id"] == frames[7].frame_id
    assert store.sessions(handle.harness_execution_id)["thread-1"]["state"] == "closed"


@pytest.mark.asyncio
async def test_resumed_writer_continues_the_arrival_sequence() -> None:
    store, _run_id = in_memory_store()
    first, handle = await opened_writer(store)
    await first.write(turn_observations()[:4])
    reopened = await store.open_execution(harness_start())
    assert reopened.last_cursor is not None and reopened.last_cursor.arrival_ordinal == 4
    resumed = FrameWriter(store, reopened, clock=StepClock())
    receipt = await resumed.write(turn_observations())
    assert (receipt.new, receipt.duplicate) == (5, 4)
    frames = await store.frames_for_execution(SCOPE, handle.harness_execution_id, 1)
    assert [frame.arrival_ordinal for frame in frames] == [1, 2, 3, 4, 9, 10, 11, 12, 13]
    assert [frame.provider_key for frame in frames] == [
        item.provider_key for item in turn_observations()
    ]


@pytest.mark.asyncio
async def test_frames_of_an_older_generation_are_stale_and_never_stored() -> None:
    store, _run_id = in_memory_store()
    old, _handle = await opened_writer(store, harness_start(generation=1))
    newer = await store.open_execution(harness_start(generation=2))
    current = FrameWriter(store, newer, clock=StepClock())
    assert (await current.write(turn_observations()[:2])).new == 2
    stale = await old.write([observation("late", FrameKind.TOOL_CALL_COMPLETED)])
    assert (stale.new, stale.duplicate, stale.stale) == (0, 0, 1)
    assert await store.current_generation(SCOPE, newer.harness_execution_id) == 2
    assert await store.frames_for_execution(SCOPE, newer.harness_execution_id, 1) == ()


@pytest.mark.asyncio
async def test_unknown_run_or_activation_fails_closed() -> None:
    store, _run_id = in_memory_store()
    with pytest.raises(HarnessExecutionNotFound):
        await store.open_execution(harness_start(activation_key="missing"))


class _CollidingSink:
    """Rejects the first append with an ordinal collision, as a racing writer would."""

    def __init__(self, inner: InMemoryFrameStore, taken: int) -> None:
        self._inner = inner
        self._collide = True
        self._taken = taken

    async def append(self, frames: Sequence[ProviderFrame]) -> AppendReceipt:
        if self._collide:
            self._collide = False
            raise FrameOrdinalConflict("taken")
        return await self._inner.append(frames)

    async def last_cursor(
        self, harness_execution_id: Any, generation: int, *, request_scope: str
    ) -> ProviderCursor | None:
        return ProviderCursor(
            harness_execution_id=harness_execution_id,
            generation=generation,
            arrival_ordinal=self._taken,
            provider_key="someone-else",
        )


@pytest.mark.asyncio
async def test_ordinal_collision_reseeds_from_the_store_cursor() -> None:
    store, _run_id = in_memory_store()
    handle = await store.open_execution(harness_start())
    sink: FrameSink = _CollidingSink(store, taken=7)
    writer = FrameWriter(sink, handle, clock=StepClock())
    await writer.write([observation("k1", FrameKind.MESSAGE)])
    frames = await store.frames_for_execution(SCOPE, handle.harness_execution_id, 1)
    assert [frame.arrival_ordinal for frame in frames] == [8]


class _Promoter:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

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
        self.calls.append(
            {"key": promotion_key, "kind": kind, "digest": digest, "size": len(payload)}
        )
        return f"artifact://fixture/{digest}"


BIG = {"content": "x" * 5_000, "status": "success"}


@pytest.mark.asyncio
async def test_oversized_closing_bodies_are_promoted_per_the_capture_profile() -> None:
    store, _run_id = in_memory_store()
    promoter = _Promoter()
    writer, handle = await opened_writer(store, excerpt_cap_bytes=256, promoter=promoter)
    assert writer.capture is STANDARD_PROFILE and writer.promotes
    await writer.write(
        [
            observation("tool", FrameKind.TOOL_CALL_COMPLETED, BIG),
            observation("delta", FrameKind.MESSAGE_DELTA, BIG),
            observation("small", FrameKind.TOOL_CALL_COMPLETED, {"status": "success"}),
            observation("message", FrameKind.MESSAGE, BIG),
            observation("started", FrameKind.SUBAGENT_STARTED, BIG),
            observation("ended", FrameKind.SUBAGENT_ENDED, BIG),
            observation("tool-again", FrameKind.TOOL_CALL_COMPLETED, BIG),
        ]
    )
    frames = {
        frame.provider_key: frame
        for frame in await store.frames_for_execution(SCOPE, handle.harness_execution_id, 1)
    }
    # `standard` promotes messages and the closing subagent frame; one call per distinct body
    # of a kind (the second identical tool result reuses the first reference).
    assert [call["key"].rsplit(":", 1)[-1] for call in promoter.calls] == [
        "tool",
        "message",
        "ended",
    ]
    assert frames["tool"].body_artifact_ref == f"artifact://fixture/{frames['tool'].body_digest}"
    assert frames["tool-again"].body_artifact_ref == frames["tool"].body_artifact_ref
    assert len(frames["tool"].body_excerpt.encode()) <= 256 and frames["tool"].body_bytes > 5_000
    assert frames["delta"].body_artifact_ref is None
    assert frames["small"].body_artifact_ref is None
    assert frames["started"].body_artifact_ref is None  # not a full-body kind
    assert frames["ended"].body_artifact_ref is not None


@pytest.mark.asyncio
async def test_a_narrow_profile_keeps_other_kinds_as_excerpts() -> None:
    store, _run_id = in_memory_store()
    promoter = _Promoter()
    tools_only = FrameCapturePolicy(
        name="tools_only",
        excerpt_cap_bytes=256,
        promote_kinds=frozenset({FrameKind.TOOL_CALL_COMPLETED, FrameKind.MESSAGE_DELTA}),
        max_body_bytes=2 * 1024 * 1024,
        full_requests=False,
        message_objects=False,
    )
    writer, handle = await opened_writer(
        store, excerpt_cap_bytes=256, promoter=promoter, capture=tools_only
    )
    await writer.write(
        [
            observation("tool", FrameKind.TOOL_CALL_COMPLETED, BIG),
            observation("delta", FrameKind.MESSAGE_DELTA, BIG),
            observation("message", FrameKind.MESSAGE, BIG),
        ]
    )
    frames = {
        frame.provider_key: frame
        for frame in await store.frames_for_execution(SCOPE, handle.harness_execution_id, 1)
    }
    assert [call["key"].rsplit(":", 1)[-1] for call in promoter.calls] == ["tool"]
    assert frames["message"].body_artifact_ref is None
    assert frames["delta"].body_artifact_ref is None, "deltas never promote"
    assert not tools_only.eligible(FrameKind.TOOL_CALL_COMPLETED, 3 * 1024 * 1024, 256)


@pytest.mark.asyncio
async def test_no_promoter_means_excerpts_only_and_promote_object_declines() -> None:
    store, _run_id = in_memory_store()
    writer, handle = await opened_writer(store, excerpt_cap_bytes=256)
    assert not writer.promotes
    await writer.write([observation("tool", FrameKind.TOOL_CALL_COMPLETED, BIG)])
    (frame,) = await store.frames_for_execution(SCOPE, handle.harness_execution_id, 1)
    assert frame.body_artifact_ref is None and frame.body_bytes > 256
    assert (
        await writer.promote_object(
            kind=FrameKind.MODEL_REQUEST,
            payload=b"{}",
            media_type="application/json",
            promotion_key="m",
        )
        is None
    )


class _NoMetadata:
    async def get_by_artifact(self, artifact_id: str) -> None:
        return None


def _reader(
    payloads: InMemoryArtifactPayloadStore, scope: str = SCOPE
) -> GrantedArtifactBodyReader:
    return GrantedArtifactBodyReader(_NoMetadata(), payloads, request_scope=scope)


def _actor(*permissions: str) -> ActorContext:
    return ActorContext(actor_id="reader", permissions=frozenset(permissions))


@pytest.mark.asyncio
async def test_promoted_bodies_round_trip_through_the_payload_store_under_the_grant() -> None:
    store, _run_id = in_memory_store()
    payloads = InMemoryArtifactPayloadStore()
    promoter = PayloadStoreFrameBodyPromoter(payloads)
    writer, handle = await opened_writer(store, excerpt_cap_bytes=256, promoter=promoter)
    await writer.write([observation("tool", FrameKind.TOOL_CALL_COMPLETED, BIG)])
    (frame,) = await store.frames_for_execution(SCOPE, handle.harness_execution_id, 1)
    assert frame.body_artifact_ref is not None
    parsed = parse_frame_body_ref(frame.body_artifact_ref)
    assert (parsed.digest, parsed.bytes, parsed.media_type) == (
        frame.body_digest,
        frame.body_bytes,
        "application/json",
    )
    address = payloads.address_for(content_digest=parsed.digest, size_bytes=parsed.bytes)
    assert address.object_ref in payloads.payloads
    granted = _reader(payloads)
    body = await granted.read(SCOPE, _actor("workflow.result.read"), frame.body_artifact_ref)
    assert json.loads(body) == BIG and len(body.encode()) == frame.body_bytes
    with pytest.raises(ArtifactBodyDenied):
        await granted.read(SCOPE, _actor("workflow_run.read"), frame.body_artifact_ref)
    with pytest.raises(ArtifactBodyDenied):
        await _reader(payloads, OTHER_SCOPE).read(
            SCOPE, _actor("workflow.result.read"), frame.body_artifact_ref
        )
    # A reference whose bytes are not in this store, or do not match, keeps the excerpt
    # (LookupError), never a different body.
    with pytest.raises(ArtifactBodyMissing):
        await _reader(InMemoryArtifactPayloadStore()).read(
            SCOPE, _actor("workflow.result.read"), frame.body_artifact_ref
        )
    forged = frame.body_artifact_ref.replace(f"bytes={frame.body_bytes}", "bytes=7")
    with pytest.raises(ArtifactBodyMissing):
        await granted.read(SCOPE, _actor("workflow.result.read"), forged)
    with pytest.raises(ArtifactBodyMissing):
        await granted.read(SCOPE, _actor("workflow.result.read"), "frame-body://sha256:zz?x=1")


@pytest.mark.asyncio
async def test_promote_object_stores_each_message_once_and_honours_the_profile() -> None:
    store, _run_id = in_memory_store()
    promoter = _Promoter()
    writer, _handle = await opened_writer(store, promoter=promoter)
    system = json.dumps({"type": "system", "content": "You are careful."}).encode()
    human = json.dumps({"type": "human", "content": "Go."}).encode()
    first = await writer.promote_object(
        kind=FrameKind.MODEL_REQUEST,
        payload=system,
        media_type="application/json",
        promotion_key="call:1:system",
    )
    again = await writer.promote_object(
        kind=FrameKind.MODEL_REQUEST,
        payload=system,
        media_type="application/json",
        promotion_key="call:2:system",
    )
    other = await writer.promote_object(
        kind=FrameKind.MODEL_REQUEST,
        payload=human,
        media_type="application/json",
        promotion_key="call:1:human",
    )
    assert first is not None and first == again and other != first
    assert [call["key"].rsplit(":", 2)[-2:] for call in promoter.calls] == [
        ["1", "system"],
        ["1", "human"],
    ]
    assert not writer.capture.full_requests and FULL_REQUESTS_PROFILE.full_requests
    # Over the body ceiling: nothing stored, nothing referenced.
    assert (
        await writer.promote_object(
            kind=FrameKind.MODEL_REQUEST,
            payload=b"x" * (STANDARD_PROFILE.max_body_bytes + 1),
            media_type="text/plain",
            promotion_key="call:3:system",
        )
        is None
    )
    no_objects = FrameCapturePolicy(
        name="digests_only",
        excerpt_cap_bytes=8192,
        promote_kinds=STANDARD_PROFILE.promote_kinds,
        max_body_bytes=STANDARD_PROFILE.max_body_bytes,
        full_requests=False,
        message_objects=False,
    )
    silent, _handle = await opened_writer(store, promoter=promoter, capture=no_objects)
    assert (
        await silent.promote_object(
            kind=FrameKind.MODEL_REQUEST,
            payload=system,
            media_type="application/json",
            promotion_key="call:1:system",
        )
        is None
    )
    # Other kinds (an environment manifest) are unaffected by `message_objects`.
    assert (
        await silent.promote_object(
            kind=FrameKind.ENVIRONMENT_MATERIALIZED,
            payload=b"{}",
            media_type="application/json",
            promotion_key="manifest",
        )
        is not None
    )


class _FailingPromoter(_Promoter):
    async def promote_frame_body(self, handle: HarnessExecutionHandle, **kwargs: Any) -> str:
        if kwargs["promotion_key"].endswith(":tool"):
            raise OSError("payload store down")
        return await super().promote_frame_body(handle, **kwargs)


@pytest.mark.asyncio
async def test_a_failing_payload_store_keeps_the_frame_with_its_excerpt() -> None:
    """Tracing Stage 3 (R3-F14): the provider event already happened; a promotion error
    records the frame without a ref (its excerpt kept) and the batch goes on; a later frame
    with the same body tries the store again."""

    store, _run_id = in_memory_store()
    promoter = _FailingPromoter()
    writer, handle = await opened_writer(store, excerpt_cap_bytes=256, promoter=promoter)
    await writer.write(
        [
            observation("tool", FrameKind.TOOL_CALL_COMPLETED, BIG),
            observation("message", FrameKind.MESSAGE, BIG),
            observation("tool-again", FrameKind.TOOL_CALL_COMPLETED, BIG),
        ]
    )
    frames = {
        frame.provider_key: frame
        for frame in await store.frames_for_execution(SCOPE, handle.harness_execution_id, 1)
    }
    assert frames["tool"].body_artifact_ref is None and frames["tool"].body_bytes > 256
    assert frames["message"].body_artifact_ref is not None
    assert frames["tool-again"].body_artifact_ref is not None
    with pytest.raises(OSError):
        await writer.promote_object(
            kind=FrameKind.TOOL_CALL_COMPLETED,
            payload=b"{}",
            media_type="application/json",
            promotion_key="tool",
        )
