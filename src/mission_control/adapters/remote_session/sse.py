"""Server-Sent Events wire parsing for provider session streams (ADR-0052; SPEC-06 section 3).

Every Remote Session Lane reads its provider's event stream as `text/event-stream`: the Cursor
Cloud Agents run stream, the Managed Agents session stream and the Agents API session stream.
Parsing follows the WHATWG event-stream rules: `data:` lines join with newlines, `:` lines are
comments, a blank line dispatches, an unnamed event is `message`, and an `id:` line (the resume
cursor a provider may honour as `Last-Event-ID`) is kept on the event it belongs to. What the
event names mean is the provider adapter's business, never this parser's.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SseEvent:
    event: str
    data: str
    id: str | None = None

    def json(self) -> dict[str, Any]:
        if not self.data.strip():
            return {}
        try:
            loaded = json.loads(self.data)
        except ValueError:
            return {"text": self.data}
        return loaded if isinstance(loaded, dict) else {"value": loaded}


class _Builder:
    def __init__(self) -> None:
        self.event = ""
        self.data: list[str] = []
        self.id: str | None = None

    def line(self, line: str) -> SseEvent | None:
        if line == "":
            if not self.data and not self.event:
                return None
            event = SseEvent(event=self.event or "message", data="\n".join(self.data), id=self.id)
            self.event, self.data, self.id = "", [], None
            return event
        if line.startswith(":"):
            return None
        name, _sep, value = line.partition(":")
        value = value.removeprefix(" ")
        if name == "event":
            self.event = value
        elif name == "data":
            self.data.append(value)
        elif name == "id" and "\x00" not in value:
            self.id = value or None
        return None


async def parse_sse(lines: AsyncIterator[str]) -> AsyncIterator[SseEvent]:
    builder = _Builder()
    async for raw in lines:
        event = builder.line(raw.rstrip("\r"))
        if event is not None:
            yield event
    final = builder.line("")
    if final is not None:
        yield final


def parse_sse_text(text: str) -> list[SseEvent]:
    """Synchronous parse of a whole recorded stream (fixtures)."""

    builder = _Builder()
    events: list[SseEvent] = []
    lines: Iterable[str] = text.replace("\r\n", "\n").split("\n")
    for line in lines:
        event = builder.line(line)
        if event is not None:
            events.append(event)
    final = builder.line("")
    if final is not None:
        events.append(final)
    return events


def render_sse(events: Iterable[SseEvent]) -> str:
    """Serialize events back to the wire format (fake servers in tests)."""

    chunks: list[str] = []
    for event in events:
        lines = []
        if event.id is not None:
            lines.append(f"id: {event.id}")
        lines.append(f"event: {event.event}")
        lines.extend(f"data: {part}" for part in event.data.split("\n"))
        chunks.append("\n".join(lines) + "\n\n")
    return "".join(chunks)


__all__ = ["SseEvent", "parse_sse", "parse_sse_text", "render_sse"]
