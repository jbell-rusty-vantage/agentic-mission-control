"""Tracing Stage 3: how a read states and resolves bodies (R4-F1, R4-F4, R4-F5).

- R4-F4: a kind outside `FULL_BODY_KINDS` is cut at the list cap, so its entry is `excerpt`
  unless that cut excerpt still holds the whole body (a 5 KB `tool_call_started` used to
  read `inline` with truncated JSON).
- R4-F5: a `full=true` page reads each referenced body once (a conversation repeats its
  earlier messages in every request) and inlines at most the page budget; past it the bare
  reference stays and `body.truncated` is set.
- R4-F1: an `expired` entry is never resolved by a full read, and its placeholder keeps no
  artifact reference.
"""

from __future__ import annotations

import json
from collections import Counter
from hashlib import sha256

import pytest

from mission_control.application.frames import transcript as transcript_module
from mission_control.application.frames.body_refs import frame_body_ref
from mission_control.application.frames.transcript import (
    EXCERPT_CHARS,
    TranscriptService,
    keep_expired,
    merge,
)
from mission_control.domain.frames.contracts import FrameKind
from mission_control.domain.policies.contracts import ActorContext
from tests.fixtures.provider_frames import SCOPE, provider_frame
from tests.fixtures.transcripts import RUN_KEY, InMemoryMissionEvents, StaticFrames

FULL = ActorContext(actor_id="reader", permissions=frozenset({"workflow_run.read"}))


def ref(name: str) -> str:
    digest = "sha256:" + sha256(name.encode()).hexdigest()
    return frame_body_ref(digest=digest, size_bytes=10, media_type="application/json")


SYSTEM, FIRST, SECOND = ref("system"), ref("first"), ref("second")


class CountingBodies:
    def __init__(self) -> None:
        self.reads: Counter[str] = Counter()

    async def read(self, request_scope: str, actor: ActorContext, artifact_ref: str) -> str:
        assert request_scope == SCOPE and actor is FULL
        self.reads[artifact_ref] += 1
        return json.dumps({"text": "m" * 100, "ref": artifact_ref[-8:]})


def request_frame(ordinal: int, messages: list[str]) -> object:
    return provider_frame(
        ordinal,
        FrameKind.MODEL_REQUEST,
        {"system": {"ref": SYSTEM}, "messages": [{"ref": item} for item in messages]},
    )


def service(frames: list[object]) -> TranscriptService:
    return TranscriptService(
        InMemoryMissionEvents([]),
        StaticFrames(frames),  # type: ignore[arg-type]
        request_scope=SCOPE,
    )


def test_a_capped_kind_reads_excerpt_not_inline() -> None:
    started = provider_frame(1, FrameKind.TOOL_CALL_STARTED, {"args": "a" * 5_000})
    small = provider_frame(2, FrameKind.TOOL_CALL_STARTED, {"args": "b"})
    request = provider_frame(3, FrameKind.MODEL_REQUEST, {"messages": ["c" * 5_000]})
    entries = {
        item.entry.execution.arrival_ordinal: item.entry
        for item in merge(RUN_KEY, [], [started, small, request])
    }  # type: ignore[union-attr]
    assert started.body_bytes > EXCERPT_CHARS
    assert entries[1].body.state == "excerpt"
    assert len(entries[1].body_excerpt or "") == EXCERPT_CHARS
    assert entries[2].body.state == "inline"
    # A full-body kind keeps the whole stored body, so it is still `inline`.
    assert entries[3].body.state == "inline"
    assert json.loads(entries[3].body_excerpt or "")


@pytest.mark.asyncio
async def test_a_full_page_reads_each_reference_once() -> None:
    bodies = CountingBodies()
    frames = [request_frame(1, [FIRST]), request_frame(2, [FIRST, SECOND])]
    page = await service(frames).with_artifacts(bodies).materialize(RUN_KEY, actor=FULL, full=True)
    assert bodies.reads == Counter({SYSTEM: 1, FIRST: 1, SECOND: 1})
    second = json.loads(page.entries[1].body_excerpt or "")
    assert [part["body"]["ref"] for part in second["messages"]] == [FIRST[-8:], SECOND[-8:]]
    assert all(entry.body.truncated is None for entry in page.entries)


@pytest.mark.asyncio
async def test_past_the_page_budget_the_bare_reference_stays_and_is_marked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = len(json.dumps({"text": "m" * 100, "ref": "xxxxxxxx"}).encode())
    # Room for the first request's two bodies only.
    monkeypatch.setattr(transcript_module, "FULL_PAGE_BODY_BUDGET_BYTES", 2 * body)
    frames = [request_frame(1, [FIRST]), request_frame(2, [FIRST, SECOND])]
    page = await (
        service(frames).with_artifacts(CountingBodies()).materialize(RUN_KEY, actor=FULL, full=True)
    )
    first, second = page.entries
    assert first.body.truncated is None
    assert all("body" in part for part in json.loads(first.body_excerpt or "")["messages"])
    assert second.body.truncated is True
    later = json.loads(second.body_excerpt or "")
    assert later["system"] == {"ref": SYSTEM}
    assert all(part == {"ref": part["ref"]} for part in later["messages"])


@pytest.mark.asyncio
async def test_expired_entries_are_never_resolved_and_keep_no_reference() -> None:
    promoted = provider_frame(1, FrameKind.MESSAGE, {"text": "x"}).model_copy(
        update={"body_bytes": 90_000, "body_artifact_ref": FIRST}
    )
    (projected,) = (item.entry for item in merge(RUN_KEY, [], [promoted]))
    assert projected.body.state == "artifact" and projected.refs.artifact_ref == FIRST
    (placeholder,) = keep_expired((projected,), ())
    assert placeholder.body.state == "expired"
    assert placeholder.body.artifact_ref is None and placeholder.refs.artifact_ref is None

    class Refusing:
        async def read(self, request_scope: str, actor: ActorContext, artifact_ref: str) -> str:
            raise AssertionError(f"an expired body was read: {artifact_ref}")

    stale = placeholder.model_copy(
        update={
            "refs": projected.refs,
            "body": placeholder.body.model_copy(update={"artifact_ref": FIRST}),
        }
    )
    reader = service([]).with_artifacts(Refusing())
    reads = transcript_module._FullReads()
    assert await reader._with_full_body(stale, FULL, reads) == stale
