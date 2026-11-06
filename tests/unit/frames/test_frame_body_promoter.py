"""1.4.4 (TR-D3): the payload-store promoter and the `frame-body://` scheme."""

from __future__ import annotations

from hashlib import sha256

import pytest

from mission_control.adapters.storage.artifact_payloads import InMemoryArtifactPayloadStore
from mission_control.adapters.storage.frame_body_promoter import PayloadStoreFrameBodyPromoter
from mission_control.application.frames.body_refs import parse_frame_body_ref
from mission_control.domain.execution.errors import WorkspaceDigestMismatch
from mission_control.domain.frames.contracts import FrameKind
from tests.fixtures.provider_frames import harness_start, in_memory_store

BODY = b'{"content": "a tool result", "status": "success"}'
DIGEST = "sha256:" + sha256(BODY).hexdigest()


@pytest.mark.asyncio
async def test_promotion_stages_once_and_references_by_content() -> None:
    store, _run_id = in_memory_store()
    handle = await store.open_execution(harness_start())
    payloads = InMemoryArtifactPayloadStore()
    promoter = PayloadStoreFrameBodyPromoter(payloads)
    first = await promoter.promote_frame_body(
        handle,
        promotion_key="exec:1:tool-1",
        kind=FrameKind.TOOL_CALL_COMPLETED,
        digest=DIGEST,
        media_type="application/json",
        payload=BODY,
    )
    second = await promoter.promote_frame_body(
        handle,
        promotion_key="exec:1:tool-2",  # another frame, another key, the same bytes
        kind=FrameKind.MESSAGE,
        digest=DIGEST,
        media_type="application/json",
        payload=BODY,
    )
    assert first == second
    assert len(payloads.payloads) == 1
    parsed = parse_frame_body_ref(first)
    assert parsed.digest == DIGEST and parsed.bytes == len(BODY)
    assert parsed.media_type == "application/json"
    # The owner's bare scheme: the body is named by digest alone; the store that staged it
    # derives the address (R4-F6: the reference carries no locator at all).
    assert first == f"frame-body://{DIGEST}?bytes={len(BODY)}&type=application%2Fjson"
    address = payloads.address_for(content_digest=parsed.digest, size_bytes=parsed.bytes)
    assert address.object_ref == "memory://artifacts/" + DIGEST.removeprefix("sha256:")
    assert await payloads.retrieve(address) == BODY


@pytest.mark.asyncio
async def test_a_wrong_digest_is_refused_before_staging() -> None:
    store, _run_id = in_memory_store()
    handle = await store.open_execution(harness_start())
    payloads = InMemoryArtifactPayloadStore()
    promoter = PayloadStoreFrameBodyPromoter(payloads)
    with pytest.raises(WorkspaceDigestMismatch):
        await promoter.promote_frame_body(
            handle,
            promotion_key="exec:1:tool-1",
            kind=FrameKind.TOOL_CALL_COMPLETED,
            digest="sha256:" + "0" * 64,
            media_type="application/json",
            payload=BODY,
        )
    assert payloads.payloads == {}
