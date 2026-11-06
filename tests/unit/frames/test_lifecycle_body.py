"""Bounded status evidence must not become a second store for arbitrary provider text."""

import pytest
from pydantic import ValidationError

from mission_control.application.frames.writer import FrameWriter
from mission_control.domain.authoring.canonical import canonical_json
from mission_control.domain.frames.body import frame_body_object
from mission_control.domain.frames.contracts import FrameKind, ProviderFrame
from mission_control.domain.frames.lifecycle import lifecycle_body
from tests.fixtures.provider_frames import (
    SCOPE,
    harness_start,
    in_memory_store,
    observation,
    provider_frame,
)


def test_lifecycle_summary_excludes_text_and_nested_secrets() -> None:
    assert lifecycle_body(
        {
            "status": "failed",
            "error": {"code": 429, "message": "secret"},
            "result": "secret output",
            "url": "https://secret.invalid",
            "unknown": "secret",
        }
    ) == {"status": "failed", "error": {"code": 429}}


def test_empty_summary_preserves_canonical_frame_digest_input() -> None:
    frame = provider_frame(1, FrameKind.RUN_RESULT, {"status": "finished"})
    assert "lifecycle_body" not in frame.model_dump(mode="json")
    assert b"lifecycle_body" not in canonical_json(frame.model_dump(mode="json"))


@pytest.mark.parametrize(
    "summary",
    [
        {"status": "finished", "is_error": True},
        {"status": "failed", "is_error": False},
        {"status": "finished", "message": "secret"},
        {"status": "error"},  # Contradicts the complete body.
    ],
)
def test_inconsistent_or_unbounded_summary_is_rejected(summary: dict[str, object]) -> None:
    payload = provider_frame(1, FrameKind.RUN_RESULT, {"status": "finished"}).model_dump()
    payload["lifecycle_body"] = summary
    with pytest.raises(ValidationError):
        ProviderFrame.model_validate(payload)


@pytest.mark.asyncio
async def test_writer_extracts_known_lifecycle_without_inventing_full_body() -> None:
    store, _ = in_memory_store()
    handle = await store.open_execution(harness_start())
    await FrameWriter(store, handle).write(
        [
            observation(
                "large",
                FrameKind.RUN_RESULT,
                {"message": "padding" * 2000, "status": "finished", "result": "private prose"},
            )
        ]
    )
    frame = (await store.frames_for_execution(SCOPE, handle.harness_execution_id, 1))[0]
    assert frame.lifecycle_body == {"status": "finished"}
    assert frame_body_object(frame.body_excerpt, frame.body_bytes, frame.lifecycle_body) == {
        "status": "finished"
    }
    assert frame_body_object(frame.body_excerpt, frame.body_bytes) == {}
