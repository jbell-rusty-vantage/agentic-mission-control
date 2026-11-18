"""Builders, constants and fakes that other test files import.

Moved from tests/unit/frames/test_frame_boundary_points.py.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from mission_control.domain.frames.contracts import (
    FrameKind,
    FrameScope,
    LaneProfile,
    ProviderFrame,
    is_closing,
)
from tests.support.ids import SCOPE
from tests.support.provider_frames import FRAME_NOW

EXECUTION = uuid4()
RUN = uuid4()
ACTIVATION = uuid4()


def frame(
    ordinal: int, kind: FrameKind, *, turn: str | None = "turn-1", **updates: Any
) -> ProviderFrame:
    values: dict[str, Any] = {
        "frame_id": uuid4(),
        "scope": FrameScope.from_request_scope(SCOPE),
        "run_id": RUN,
        "activation_id": ACTIVATION,
        "attempt_no": 1,
        "harness_execution_id": EXECUTION,
        "generation": 1,
        "lane_profile": LaneProfile.CLAUDE_AGENT_SDK,
        "native_session_ref": "session-1",
        "native_turn_ref": turn,
        "provider_key": f"session-1::{turn}:{ordinal}:{kind.value}",
        "arrival_ordinal": ordinal,
        "observed_at": FRAME_NOW,
        "kind": kind,
        "closing": is_closing(kind),
        "body_digest": "sha256:" + "a" * 64,
        "body_bytes": 2,
        "body_media_type": "application/json",
        "body_excerpt": "{}",
        "raw_kind": f"raw.{kind.value}",
    }
    values.update(updates)
    return ProviderFrame.model_validate(values)
