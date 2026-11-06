"""Tracing Stage 2 (F-S2-5): frames retention deleted still read `expired`.

An entry an earlier projection held whose frame the Native Event Store no longer has becomes
a `frame_expired` placeholder at its own cursor (`body.state == "expired"`); entries whose
frame is still stored, events and earlier placeholders are kept as they are.
"""

from __future__ import annotations

from datetime import UTC, datetime

from mission_control.application.frames.transcript import keep_expired
from mission_control.domain.frames.transcript import (
    TranscriptBody,
    TranscriptEntry,
    TranscriptRefs,
)


def frame_entry(ordinal: int, kind: str, frame_id: str) -> TranscriptEntry:
    return TranscriptEntry(
        cursor=f"tc1:000000000002:{ordinal:017d}:{ordinal:012d}:abcdef01",
        run_id="run-1",
        at=datetime(2026, 10, 22, 21, 0, ordinal, tzinfo=UTC),
        source="provider_frame",
        kind=kind,
        role="agent",
        title=kind,
        body_excerpt='{"text": "chunk"}',
        body=TranscriptBody(state="inline", bytes=17),
        refs=TranscriptRefs(frame_id=frame_id),
        canonical=False,
    )


def test_a_deleted_frame_becomes_an_expired_placeholder_in_place() -> None:
    first = frame_entry(1, "model_request", "f1")
    delta = frame_entry(2, "message_delta", "f2")
    message = frame_entry(3, "message", "f3")
    projected = (first, delta, message)

    merged = keep_expired(projected, (first, message))

    assert [entry.cursor for entry in merged] == [item.cursor for item in projected]
    assert [entry.entry_seq for entry in merged] == [1, 2, 3]
    placeholder = merged[1]
    assert placeholder.kind == "frame_expired"
    assert placeholder.title == "(frame expired: message_delta)"
    assert placeholder.body.state == "expired" and placeholder.body_excerpt is None
    assert placeholder.refs.frame_id == "f2"
    # A second pass over the placeholder keeps it unchanged.
    assert keep_expired(merged, (first, message)) == merged


def test_nothing_changes_when_every_frame_is_stored() -> None:
    entries = (frame_entry(1, "model_request", "f1"), frame_entry(2, "message", "f2"))
    assert keep_expired(entries, entries) == entries
