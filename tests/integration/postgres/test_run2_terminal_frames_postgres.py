"""Actual restricted-role fenced append, terminal identity and snapshot usage proof."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from mission_control.adapters.postgres.frames.repository import PostgresFrameRepository
from mission_control.adapters.postgres.lanes.execution_state import PostgresLaneExecutionStateStore
from mission_control.application.execution.harness.dispatch import StaleSessionOwner
from mission_control.application.frames.writer import FrameWriter
from mission_control.domain.frames.contracts import FrameKind, LaneProfile
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.fixtures.provider_frames import observation
from tests.integration.postgres.frames_common import admit_unit_attempt
from tests.integration.postgres.runtime_common import common_db as common_db
from tests.integration.postgres.runtime_common import owner_rows

pytestmark = pytest.mark.common_db


async def test_fenced_terminal_snapshot_is_atomic_idempotent_and_rejects_stale_owner(
    common_db: CommonDatabase,
):
    pool = await common_db.pool("mission_control_runtime", max_size=1)
    try:
        admitted = await admit_unit_attempt(pool, common_db)
        scope = common_db.scope()
        frames, states = PostgresFrameRepository(pool), PostgresLaneExecutionStateStore(pool)
        handle = await frames.open_execution(
            admitted.start(lane=LaneProfile.CURSOR_LOCAL, native_session_ref="agent-owned-fixture")
        )
        await FrameWriter(frames, handle).write(
            [
                observation("start", FrameKind.TURN_STARTED, {}, turn="native-owned-fixture"),
                observation(
                    "partial-usage",
                    FrameKind.USAGE,
                    {"inputTokens": 1, "outputTokens": 1},
                    turn="native-owned-fixture",
                ),
            ]
        )
        old = await states.claim_owner(
            scope,
            handle.harness_execution_id,
            owner_ref="expired-fixture",
            generation=1,
            now=datetime.now(UTC) - timedelta(minutes=2),
            lease=timedelta(seconds=1),
        )
        owner = await states.claim_owner(
            scope,
            handle.harness_execution_id,
            owner_ref="recovery-fixture",
            generation=1,
            now=datetime.now(UTC),
            lease=timedelta(minutes=2),
        )
        assert owner.epoch == old.epoch + 1

        class Fenced:
            async def append(self, batch):
                return await frames.append_fenced(batch, owner=owner)

            async def last_cursor(self, *args, **kwargs):
                return await frames.last_cursor(*args, **kwargs)

        body = {
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
        }
        closing = [
            observation(
                "recovered-result", FrameKind.RUN_RESULT, body, turn="native-owned-fixture"
            ),
            observation(
                "recovered-end",
                FrameKind.TURN_ENDED,
                body,
                turn="native-owned-fixture",
                raw_kind="mc.terminal-adoption.turn-ended",
            ),
        ]
        assert (await FrameWriter(Fenced(), handle).write(closing)).new == 2
        stored = await frames.frames_for_execution(scope, handle.harness_execution_id, 1)
        assert len(stored) == 4
        assert (await frames.append_fenced(stored[-2:], owner=owner)).duplicate == 2
        with pytest.raises(StaleSessionOwner):
            await frames.append_fenced(stored[-2:], owner=old)
        with pytest.raises(ValueError, match="different evidence"):
            await frames.append_fenced(
                [stored[-1].model_copy(update={"body_digest": "sha256:" + "b" * 64})], owner=owner
            )
        rows = await owner_rows(
            common_db, "SELECT usage,execution_outcome FROM mission_control.session_turn"
        )
        assert len(rows) == 1 and rows[0]["execution_outcome"] == "succeeded"
        usage = json.loads(rows[0]["usage"])["dimensions"]
        assert usage["input_tokens"]["value"] == 456013 and usage["output_tokens"]["value"] == 14072
        assert usage["cost_micros"]["value"] is None
        sessions = await owner_rows(common_db, "SELECT state FROM mission_control.agent_session")
        assert [row["state"] for row in sessions] == ["closed"]
    finally:
        await pool.close()
