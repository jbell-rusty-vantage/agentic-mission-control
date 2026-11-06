"""Oversized native terminal evidence survives a fresh repository/process projection."""

import pytest

from mission_control.adapters.postgres.frames.repository import PostgresFrameRepository
from mission_control.application.frames.reducer import CompletionEvidence, DeriveContext, derive
from mission_control.application.frames.writer import FrameWriter
from mission_control.domain.frames.contracts import FrameKind, LaneProfile
from mission_control.domain.frames.facts import ExecutionOutcomeFact
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.fixtures.provider_frames import observation
from tests.integration.postgres.frames_common import admit_unit_attempt
from tests.integration.postgres.runtime_common import common_db as common_db

pytestmark = pytest.mark.common_db


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("lane", "terminal", "expected"),
    [
        (LaneProfile.CURSOR_CLOUD, {"status": "finished"}, "succeeded"),
        (LaneProfile.CURSOR_CLOUD, {"status": "error"}, "failed"),
        (LaneProfile.CURSOR_CLOUD, {"status": "cancelled"}, "cancelled"),
        (LaneProfile.CLAUDE_AGENT_SDK, {"subtype": "success", "is_error": False}, "succeeded"),
        (
            LaneProfile.CLAUDE_AGENT_SDK,
            {"subtype": "error_during_execution", "is_error": True},
            "failed",
        ),
        (LaneProfile.CLAUDE_AGENT_SDK, {"terminal_reason": "cancelled"}, "cancelled"),
        (
            LaneProfile.CLAUDE_AGENT_SDK,
            {"terminal_reason": "aborted_tools", "subtype": "success"},
            "cancelled",
        ),
        (
            LaneProfile.CLAUDE_AGENT_SDK,
            {"terminal_reason": "aborted_streaming", "is_error": True},
            "cancelled",
        ),
    ],
)
async def test_oversized_terminal_write_reload_reduce(
    common_db: CommonDatabase, lane: LaneProfile, terminal: dict[str, object], expected: str
) -> None:
    pool = await common_db.pool(max_size=4)
    try:
        admitted = await admit_unit_attempt(pool, common_db)
        repository = PostgresFrameRepository(pool)
        handle = await repository.open_execution(admitted.start(lane=lane))
        writer = FrameWriter(repository, handle)
        body = {"message": "provider output " * 2000, "url": "https://private.invalid", **terminal}
        event = observation("oversized-result", FrameKind.RUN_RESULT, body)
        assert (await writer.write([event])).new == 1
        # Recreate the repository and writer, exercising DB decoding and idempotency.
        reloaded = PostgresFrameRepository(pool)
        resumed_handle = await reloaded.open_execution(admitted.start(lane=lane))
        assert (await FrameWriter(reloaded, resumed_handle).write([event])).duplicate == 1
        frames = await reloaded.frames_for_execution(
            common_db.scope(), handle.harness_execution_id, 1
        )
        assert len(frames) == 1
        assert frames[0].body_bytes > len(frames[0].body_excerpt.encode("utf-8"))
        assert frames[0].lifecycle_body == terminal
        facts = derive(
            frames,
            DeriveContext(
                lane=lane,
                current_generation=1,
                completion=CompletionEvidence(),
                cancel_command_admitted=True,
            ),
        )
        outcomes = [fact for fact in facts if isinstance(fact, ExecutionOutcomeFact)]
        assert [fact.outcome for fact in outcomes] == [expected]
    finally:
        await pool.close()
