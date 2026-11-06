"""Opening a provider event stream and naming positions in it (ADR-0052; SPEC-06 section 3).

`open_event_stream` is the one HTTP read every Remote Session Lane shares: `GET` with
`Accept: text/event-stream` (plus `Last-Event-ID` when the provider resumes natively), the
provider's error table on failure, then a `StreamOpened` marker (the connection is established
and the retention window, when the provider states one, is known) followed by the parsed
events. A provider without native resume reads its history after the marker: events that arrive
meanwhile wait in the connection, so nothing between history and stream is lost.

A stream cursor names the last event a lane stored for one turn. Each provider supplies a
`StreamCursorCodec`; `TurnEventCursors` is the codec for providers whose event ids are scoped
to one turn (Cursor runs): the cursor is `<turn>@<event id>`, the frame key
`<prefix>:<turn>:<event id>`, and a cursor from another turn resumes nothing, because such an
id is meaningless (or refused) on this turn's stream.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Protocol

import httpx

from mission_control.adapters.remote_session.errors import (
    ErrorRule,
    RemoteSessionError,
    raise_for_response,
)
from mission_control.adapters.remote_session.sse import SseEvent, parse_sse
from mission_control.application.frames.kinds import bounded_key

STREAM_START: Final = "^start"


@dataclass(frozen=True)
class StreamOpened:
    """The stream is connected; `retention_seconds` is the provider-stated replay window."""

    retention_seconds: int | None
    last_event_id: str | None


async def open_event_stream(
    client: httpx.AsyncClient,
    path: str,
    *,
    operation: str,
    rules: Sequence[ErrorRule],
    fallback: type[Exception] = RemoteSessionError,
    last_event_id: str | None = None,
    retention_header: str | None = None,
    params: Mapping[str, str] | None = None,
    headers: Mapping[str, str] | None = None,
) -> AsyncIterator[SseEvent | StreamOpened]:
    """The stream's events; the first item is the `StreamOpened` marker. `headers` are the
    provider's own request headers (a beta flag), beside `Accept` and `Last-Event-ID`."""

    sent = {**(headers or {}), "Accept": "text/event-stream"}
    if last_event_id:
        sent["Last-Event-ID"] = last_event_id
    async with client.stream("GET", path, headers=sent, params=params) as response:
        if not response.is_success:
            await response.aread()
            raise_for_response(response, operation, rules, fallback=fallback)
        retention = response.headers.get(retention_header) if retention_header else None
        yield StreamOpened(
            retention_seconds=int(retention) if retention and retention.isdigit() else None,
            last_event_id=last_event_id,
        )
        async for event in parse_sse(response.aiter_lines()):
            yield event


async def replay_then_stream(
    stream: AsyncIterator[SseEvent | StreamOpened],
    history: Callable[[], AsyncIterator[SseEvent]],
    event_key: Callable[[SseEvent], str | None],
) -> AsyncIterator[SseEvent | StreamOpened]:
    """Resume for a provider without `Last-Event-ID` (Managed Agents, the Agents API): the
    stream is opened first, so events arriving meanwhile wait in the connection; the history
    from the cursor is replayed after the `StreamOpened` marker; live events the history
    already carried are dropped by key."""

    replayed: set[str] = set()
    async for item in stream:
        if isinstance(item, StreamOpened):
            yield item
            async for event in history():
                key = event_key(event)
                if key is not None:
                    replayed.add(key)
                yield event
            continue
        key = event_key(item)
        if key is not None and key in replayed:
            continue
        yield item


async def poll_while_idle[T](
    stream: AsyncIterator[T], poll: Callable[[], Awaitable[None]], *, interval_s: float = 1
) -> AsyncIterator[T]:
    """Retry durable pending actions while SSE is quiet, without cancelling its next read."""
    pending: asyncio.Future[T] | None = None
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(anext(stream))
            done, _ = await asyncio.wait({pending}, timeout=interval_s)
            if not done:
                await poll()
                continue
            try:
                value = pending.result()
            except StopAsyncIteration:
                return
            pending = None
            yield value
    finally:
        if pending is not None:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        close = getattr(stream, "aclose", None)
        if close is not None:
            await close()


class StreamCursorCodec(Protocol):
    """How one provider names stream positions for a turn."""

    def cursor(self, turn_ref: str, event_id: str) -> str:
        """The persisted cursor after `event_id` of `turn_ref`."""
        ...

    def resume_point(self, cursor: str | None, turn_ref: str) -> str | None:
        """The native resume position a cursor names for `turn_ref` (None: from the start)."""
        ...

    def provider_key(self, turn_ref: str | None, event_id: str) -> str:
        """The frame dedupe key of one identified event."""
        ...

    def resume_cursor(self, provider_key: str) -> str | None:
        """The cursor a stored frame key resumes from (None: the key is not a stream event)."""
        ...


@dataclass(frozen=True)
class TurnEventCursors:
    """`<turn>@<event id>` cursors and `<prefix>:<turn>:<event id>` keys."""

    key_prefix: str = "sse"

    def cursor(self, turn_ref: str, event_id: str) -> str:
        return f"{turn_ref}@{event_id}"

    def resume_point(self, cursor: str | None, turn_ref: str) -> str | None:
        if cursor is None or cursor == STREAM_START:
            return None
        turn, separator, event_id = cursor.rpartition("@")
        if not separator:
            return cursor
        if turn != turn_ref or not event_id or event_id == STREAM_START:
            return None
        return event_id

    def provider_key(self, turn_ref: str | None, event_id: str) -> str:
        if turn_ref:
            return bounded_key(self.key_prefix, turn_ref, event_id)
        return bounded_key(self.key_prefix, event_id)

    def resume_cursor(self, provider_key: str) -> str | None:
        prefix = f"{self.key_prefix}:"
        if not provider_key.startswith(prefix):
            return None
        turn, separator, event_id = provider_key.removeprefix(prefix).rpartition(":")
        return self.cursor(turn, event_id) if separator and turn else event_id


__all__ = [
    "STREAM_START",
    "StreamCursorCodec",
    "StreamOpened",
    "TurnEventCursors",
    "open_event_stream",
    "replay_then_stream",
]
