"""The real identity writer uses a fenced terminal snapshot, retaining unknown cost."""

import json
from uuid import uuid4

import pytest
from tests.fixtures.provider_frames import (
    SCOPE,
    harness_start,
    in_memory_store,
    observation,
    opened_writer,
)

from mission_control.adapters.postgres.frames import identity
from mission_control.domain.frames.contracts import FrameKind, LaneProfile


class Connection:
    def __init__(self, frame):
        self.frame, self.usage = frame, None
        self.started = uuid4()
        self.old_usage = uuid4()

    async def fetchval(self, query, *args):
        if "SELECT native_identity" in query:
            return {
                "open_turn": {
                    "native_turn_ref": self.frame.native_turn_ref,
                    "generation": 1,
                    "started_frame_id": str(self.started),
                    "started_ordinal": 1,
                }
            }
        if "COALESCE(max(turn_no)" in query:
            return 1
        return None

    async def fetch(self, query, *args):
        assert "kind = 'usage'" in query
        content = b'{"inputTokens":10,"outputTokens":2}'
        return [
            {
                "frame_id": self.old_usage,
                "body_excerpt": content,
                "body_bytes": len(content),
                "subordinate_ref": None,
            }
        ]

    async def execute(self, query, *args):
        if "INSERT INTO mission_control.session_turn" in query:
            self.usage = json.loads(args[15])


@pytest.mark.parametrize("fenced", [False, True])
async def test_only_fenced_capture_replaces_incomplete_usage_deltas(fenced):
    store, _ = in_memory_store()
    writer, handle = await opened_writer(store, harness_start(lane=LaneProfile.CURSOR_LOCAL))
    await writer.write(
        [
            observation(
                "captured-end",
                FrameKind.TURN_ENDED,
                {
                    "status": "finished",
                    "recovered_observation": True,
                    "capture_manifest_digest": "sha256:" + "a" * 64,
                    "usage": {
                        "inputTokens": 456013,
                        "outputTokens": 14072,
                        "cacheReadTokens": 417705,
                        "cacheWriteTokens": 38280,
                        "totalTokens": 926070,
                    },
                },
                raw_kind="mc.terminal-adoption.turn-ended",
            )
        ]
    )
    frame = (await store.frames_for_execution(SCOPE, handle.harness_execution_id, 1))[0]
    connection = Connection(frame)
    await identity._close_turn(
        connection,
        (1, "fixture", 2),
        uuid4(),
        frame,
        actor_ref="fixture",
        fenced_terminal_capture=fenced,
    )
    assert connection.usage is not None
    dimensions = connection.usage["dimensions"]
    assert dimensions["input_tokens"]["value"] == (456013 if fenced else 10)
    assert dimensions["output_tokens"]["value"] == (14072 if fenced else 2)
    assert dimensions["cost_micros"]["value"] is None
    assert dimensions["cost_micros"]["disposition"] == "unknown"
