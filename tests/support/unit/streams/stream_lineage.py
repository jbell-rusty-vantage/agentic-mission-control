"""Builders, constants and fakes that other test files import.

Moved from tests/unit/streams/test_stream_lineage.py.
"""

from __future__ import annotations

import asyncio
from typing import Any

from mission_control.application.streams.flow import ConnectionBudget, InflightWindow
from mission_control.application.streams.pump import SubscriptionPump
from mission_control.domain.frames.contracts import ProviderFrame
from tests.support.provider_frames import FIXTURE_HARNESS
from tests.support.unit.streams.stream_pump import FAST, Recorder


def rekeyed(frames: list[ProviderFrame]) -> list[ProviderFrame]:
    return [frame.model_copy(update={"harness_execution_id": FIXTURE_HARNESS}) for frame in frames]


async def run_pump(
    svc: Any, opened: Any, recorder: Recorder, *, max_bytes: int = 1_048_576
) -> asyncio.Task[str]:
    window = InflightWindow(max_bytes, ConnectionBudget(max_bytes))
    pump = SubscriptionPump(svc, opened, recorder, window, FAST, authorized=lambda: True)
    return asyncio.create_task(pump.run())


async def stop(task: asyncio.Task[str]) -> None:
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
