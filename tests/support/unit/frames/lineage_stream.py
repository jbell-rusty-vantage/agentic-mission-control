"""Builders, constants and fakes that other test files import.

Moved from tests/unit/frames/test_lineage_stream.py.
"""

from __future__ import annotations

from mission_control.application.frames.kinds import UnknownKindCounter
from mission_control.domain.frames.contracts import LaneProfile, ProviderFrame
from tests.support.unit.frames.provider_lanes import (
    claude_observations,
    codex_app_observations,
    persisted,
)


async def claude_frames() -> list[ProviderFrame]:
    frames, _store, _handle = await persisted(
        claude_observations(UnknownKindCounter()), LaneProfile.CLAUDE_AGENT_SDK, "sess-fixture-1"
    )
    return frames


async def codex_frames() -> list[ProviderFrame]:
    frames, _store, _handle = await persisted(
        codex_app_observations(UnknownKindCounter()), LaneProfile.CODEX, "thr_root"
    )
    return frames
