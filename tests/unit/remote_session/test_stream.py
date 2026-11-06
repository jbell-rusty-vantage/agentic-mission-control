"""HL-04: the event-stream parser, `open_event_stream`, the per-turn cursor codec and the
history-then-stream merge of the Remote Session Lane base (FIXTURE transport)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest

from mission_control.adapters.remote_session.errors import (
    STANDARD_ERROR_RULES,
    ErrorRule,
    InvalidStreamCursor,
    StreamExpired,
)
from mission_control.adapters.remote_session.sse import (
    SseEvent,
    parse_sse,
    parse_sse_text,
    render_sse,
)
from mission_control.adapters.remote_session.stream import (
    STREAM_START,
    StreamOpened,
    TurnEventCursors,
    open_event_stream,
    replay_then_stream,
)

RULES = (
    ErrorRule(400, InvalidStreamCursor, "foreign cursor", code="invalid_cursor"),
    *STANDARD_ERROR_RULES,
)


# --- wire parsing ------------------------------------------------------------------------------


def test_the_parser_follows_the_event_stream_rules() -> None:
    text = (
        ": a comment\n"
        "event: status\n"
        'data: {"a":\n'
        "data: 1}\n"
        "\n"
        "id: 7\n"
        "data: plain\n"
        "\n"
        "id: bad\x00id\n"
        "event: tail\n"
        "data: x"
    )
    status, plain, tail = parse_sse_text(text)
    assert status == SseEvent(event="status", data='{"a":\n1}')
    assert status.json() == {"a": 1}
    assert plain == SseEvent(event="message", data="plain", id="7"), "unnamed is `message`"
    assert plain.json() == {"text": "plain"}
    assert tail.id is None, "an id with NUL is ignored"
    assert SseEvent(event="x", data="[1]").json() == {"value": [1]}
    assert SseEvent(event="x", data=" ").json() == {}


async def test_async_parsing_and_rendering_round_trip() -> None:
    events = [SseEvent("status", '{"s": 1}'), SseEvent("message", "two\nlines", id="2")]

    async def lines() -> AsyncIterator[str]:
        for line in render_sse(events).split("\n"):
            yield line + "\r"

    assert [item async for item in parse_sse(lines())] == events


# --- open_event_stream -------------------------------------------------------------------------


def _client(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url="https://provider.invalid", transport=handler)


async def test_the_stream_opens_with_its_marker_then_yields_parsed_events() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            headers={"X-Retention": "3600", "Content-Type": "text/event-stream"},
            text=render_sse([SseEvent("message", "{}", id="5")]),
        )

    async with _client(httpx.MockTransport(handler)) as client:
        items = [
            item
            async for item in open_event_stream(
                client,
                "/v1/sessions/s/stream",
                operation="stream session",
                rules=RULES,
                last_event_id="4",
                retention_header="X-Retention",
                params={"deltas": "false"},
            )
        ]
    assert items == [
        StreamOpened(retention_seconds=3600, last_event_id="4"),
        SseEvent("message", "{}", id="5"),
    ]
    (request,) = seen
    assert request.headers["Accept"] == "text/event-stream"
    assert request.headers["Last-Event-ID"] == "4"
    assert request.url.params["deltas"] == "false"


async def test_without_resume_or_retention_the_request_names_neither() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, headers={"X-Retention": "soon"}, text="")

    async with _client(httpx.MockTransport(handler)) as client:
        items = [
            item
            async for item in open_event_stream(
                client, "/s", operation="stream", rules=RULES, retention_header="X-Retention"
            )
        ]
    assert items == [StreamOpened(retention_seconds=None, last_event_id=None)]
    assert "Last-Event-ID" not in seen[0].headers


@pytest.mark.parametrize(
    ("status", "body", "error"),
    [(400, {"code": "invalid_cursor"}, InvalidStreamCursor), (410, {}, StreamExpired)],
)
async def test_a_refused_stream_raises_the_providers_typed_error_before_any_marker(
    status: int, body: dict[str, str], error: type[Exception]
) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(status, json=body))
    async with _client(transport) as client:
        items: list[object] = []
        with pytest.raises(error):
            async for item in open_event_stream(client, "/s", operation="stream", rules=RULES):
                items.append(item)
    assert items == []


# --- cursors -----------------------------------------------------------------------------------


def test_turn_event_cursors_are_scoped_to_one_turn() -> None:
    codec = TurnEventCursors()
    assert codec.cursor("run-1", "9") == "run-1@9"
    assert codec.resume_point("run-1@9", "run-1") == "9"
    assert codec.resume_point("run-0@9", "run-1") is None, "another turn's id resumes nothing"
    assert codec.resume_point(None, "run-1") is None
    assert codec.resume_point(STREAM_START, "run-1") is None
    assert codec.resume_point(f"run-1@{STREAM_START}", "run-1") is None
    assert codec.resume_point("run-1@", "run-1") is None
    assert codec.resume_point("7", "run-1") == "7", "a bare id is a legacy cursor"
    assert codec.provider_key("run-1", "9") == "sse:run-1:9"
    assert codec.provider_key(None, "9") == "sse:9"


def test_a_stored_key_resumes_at_its_cursor() -> None:
    codec = TurnEventCursors(key_prefix="ev")
    assert codec.resume_cursor(codec.provider_key("run-1", "9")) == "run-1@9"
    assert codec.resume_cursor("ev:9") == "9"
    assert codec.resume_cursor("sse:run-1:9") is None, "another prefix is not this stream"


# --- history, then stream ----------------------------------------------------------------------


async def test_history_follows_the_marker_and_live_duplicates_are_dropped_by_key() -> None:
    async def stream() -> AsyncIterator[SseEvent | StreamOpened]:
        yield StreamOpened(retention_seconds=None, last_event_id=None)
        yield SseEvent("message", "live", id="b")
        yield SseEvent("status", "id-less")
        yield SseEvent("message", "live", id="c")

    replays = 0

    async def history() -> AsyncIterator[SseEvent]:
        nonlocal replays
        replays += 1
        yield SseEvent("message", "old", id="a")
        yield SseEvent("message", "old", id="b")
        yield SseEvent("status", "id-less")

    merged = [item async for item in replay_then_stream(stream(), history, lambda e: e.id)]
    assert replays == 1
    assert [
        (item.id, item.data) if isinstance(item, SseEvent) else "opened" for item in merged
    ] == ["opened", ("a", "old"), ("b", "old"), (None, "id-less"), (None, "id-less"), ("c", "live")]
