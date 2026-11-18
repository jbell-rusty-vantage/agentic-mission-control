"""Builders, constants and fakes that other test files import.

Moved from tests/unit/frames/test_provider_lanes.py.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mission_control.application.frames.kinds import UnknownKindCounter
from mission_control.application.frames.provider_mapping import (
    claude_agent_sdk_observations,
    codex_observations,
)
from mission_control.application.frames.writer import FrameWriter
from mission_control.domain.frames.contracts import FrameObservation, LaneProfile, ProviderFrame
from tests.fixtures.provider_frames import FRAME_NOW, harness_start, in_memory_store
from tests.support.clock import SECOND, Clock
from tests.support.ids import SCOPE

FIXTURES = Path(__file__).resolve().parents[3] / "unit" / "frames" / "fixtures"


def load(relative: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    lines = (FIXTURES / relative).read_text(encoding="utf-8").splitlines()
    header, *rows = (json.loads(line) for line in lines if line.strip())
    return header, rows


def claude_observations(counter: UnknownKindCounter) -> list[FrameObservation]:
    _header, rows = load("claude_agent_sdk/task_subagent_session.jsonl")
    return [item for row in rows for item in claude_agent_sdk_observations(row, counter=counter)]


def codex_app_observations(counter: UnknownKindCounter) -> list[FrameObservation]:
    _header, rows = load("codex/app_server_child_thread.jsonl")
    return [
        item
        for row in rows
        for item in codex_observations(
            row["method"], row["params"], root_thread_id="thr_root", counter=counter
        )
    ]


async def persisted(
    observations: list[FrameObservation], lane: LaneProfile, session: str
) -> tuple[list[ProviderFrame], Any, Any]:
    """Write through the real writer and in-memory store (dedupe, ordinals, identity)."""

    store, _run_id = in_memory_store()
    handle = await store.open_execution(harness_start(lane=lane, native_session_ref=session))
    writer = FrameWriter(store, handle, clock=Clock(FRAME_NOW, step=SECOND))
    await writer.write(observations)
    frames = await store.frames_for_execution(SCOPE, handle.harness_execution_id, 1)
    return list(frames), store, handle
