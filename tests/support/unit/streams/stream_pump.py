"""Builders, constants and fakes that other test files import.

Moved from tests/unit/streams/test_stream_pump.py.
"""

from __future__ import annotations

import asyncio
from typing import Any

from mission_control.application.streams.pump import PumpSettings
from mission_control.domain.subscriptions.streams import StreamEnvelope, StreamError

FAST = PumpSettings(page_size=2, poll_interval=0.05, slow_consumer_grace=0.3)


class Recorder:
    def __init__(self) -> None:
        self.envelopes: list[StreamEnvelope] = []
        self.resyncs: list[dict[str, Any]] = []
        self.errors: list[StreamError] = []
        self.lineages: list[dict[str, Any]] = []
        self.changed = asyncio.Event()

    async def envelope(self, envelope: StreamEnvelope) -> None:
        self.envelopes.append(envelope)
        self.changed.set()

    async def resync_required(self, notice: dict[str, Any]) -> None:
        self.resyncs.append(notice)
        self.changed.set()

    async def error(self, error: StreamError) -> None:
        self.errors.append(error)
        self.changed.set()

    async def lineage(self, notice: dict[str, Any]) -> None:
        self.lineages.append(notice)
        self.changed.set()

    def seqs(self) -> list[int]:
        return [int(e.cursor.position) for e in self.envelopes if e.stream == "mission_events"]


async def until(recorder: Recorder, predicate: Any, within: float = 3.0) -> None:
    async with asyncio.timeout(within):
        while not predicate():
            recorder.changed.clear()
            if not predicate():
                await recorder.changed.wait()
