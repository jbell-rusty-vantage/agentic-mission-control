"""Replacement turns keep session identity current under delayed native evidence."""

from __future__ import annotations

import json
from typing import Any

import pytest

from mission_control.adapters.postgres.frames.repository import PostgresFrameRepository
from mission_control.application.frames.writer import FrameWriter
from mission_control.domain.frames.contracts import FrameKind, LaneProfile
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.fixtures.provider_frames import FRAME_NOW, StepClock, observation
from tests.integration.postgres.frames_common import admit_unit_attempt
from tests.integration.postgres.runtime_common import common_db as common_db
from tests.integration.postgres.runtime_common import owner_rows

pytestmark = pytest.mark.common_db


async def _state(db: CommonDatabase, execution_id: object) -> tuple[Any, Any, dict[str, Any]]:
    sessions = await owner_rows(
        db,
        "SELECT session_id, state, ended_at FROM mission_control.agent_session "
        "WHERE harness_execution_id = $1",
        execution_id,
    )
    executions = await owner_rows(
        db,
        "SELECT lifecycle, native_identity FROM mission_control.harness_execution "
        "WHERE harness_execution_id = $1",
        execution_id,
    )
    return sessions[0], executions[0], json.loads(executions[0]["native_identity"])


async def test_reattaching_closed_generation_preserves_lifecycle_until_a_real_new_turn(
    common_db: CommonDatabase,
) -> None:
    pool = await common_db.pool()
    try:
        admitted = await admit_unit_attempt(pool, common_db)
        repository = PostgresFrameRepository(pool)
        handle = await repository.open_execution(admitted.start())
        writer = FrameWriter(repository, handle, clock=StepClock())
        closed = [
            observation("closed-start", FrameKind.TURN_STARTED, turn="closed"),
            observation("closed-end", FrameKind.TURN_ENDED, turn="closed"),
            observation("closed-result", FrameKind.RUN_RESULT, turn="closed"),
        ]
        await writer.write(closed)
        for _ in range(2):
            resumed = await repository.open_execution(admitted.start())
            receipt = await FrameWriter(repository, resumed, clock=StepClock()).write(closed)
            session, execution, identity = await _state(common_db, handle.harness_execution_id)
            assert receipt.new == 0 and receipt.duplicate == 3
            assert session["state"] == "closed" and execution["lifecycle"] == "ended"
            assert "open_turn" not in identity
        await writer.write([observation("actual-new-turn", FrameKind.TURN_STARTED, turn="new")])
        session, execution, identity = await _state(common_db, handle.harness_execution_id)
        assert session["state"] == "open" and execution["lifecycle"] == "live"
        assert identity["open_turn"]["native_turn_ref"] == "new"
    finally:
        await pool.close()


async def test_new_generation_opens_but_stale_registration_cannot_reopen_its_closed_turn(
    common_db: CommonDatabase,
) -> None:
    pool = await common_db.pool()
    try:
        admitted = await admit_unit_attempt(pool, common_db)
        repository = PostgresFrameRepository(pool)
        await repository.open_execution(admitted.start())
        second = await repository.open_execution(
            admitted.start().model_copy(update={"generation": 2})
        )
        await FrameWriter(repository, second, clock=StepClock()).write(
            [
                observation("g2-start", FrameKind.TURN_STARTED, turn="g2"),
                observation("g2-end", FrameKind.TURN_ENDED, turn="g2"),
                observation("g2-result", FrameKind.RUN_RESULT, turn="g2"),
            ]
        )
        await repository.open_execution(admitted.start())
        session, execution, identity = await _state(common_db, second.harness_execution_id)
        assert session["state"] == "closed" and execution["lifecycle"] == "ended"
        assert "open_turn" not in identity
        assert (
            await repository.current_generation(common_db.scope(), second.harness_execution_id) == 2
        )
        stale = await FrameWriter(
            repository, second.model_copy(update={"generation": 1}), clock=StepClock()
        ).write([observation("stale-start", FrameKind.TURN_STARTED, turn="stale")])
        assert stale.stale == 1
        _, execution, _ = await _state(common_db, second.harness_execution_id)
        assert execution["lifecycle"] == "ended"
    finally:
        await pool.close()


async def test_replacement_reopens_session_and_old_results_cannot_close_it(
    common_db: CommonDatabase,
) -> None:
    pool = await common_db.pool()
    try:
        admitted = await admit_unit_attempt(pool, common_db)
        repository = PostgresFrameRepository(pool)
        handle = await repository.open_execution(admitted.start())
        writer = FrameWriter(repository, handle, clock=StepClock())
        await writer.write(
            [
                observation("old-start", FrameKind.TURN_STARTED, turn="old"),
                observation("old-end", FrameKind.TURN_ENDED, {"status": "cancelled"}, turn="old"),
                observation("old-result", FrameKind.RUN_RESULT, turn="old"),
            ]
        )
        session, execution, _ = await _state(common_db, handle.harness_execution_id)
        assert session["state"] == "closed" and session["ended_at"] is not None
        assert execution["lifecycle"] == "ended"
        await writer.write([observation("replacement-start", FrameKind.TURN_STARTED, turn="new")])
        session, execution, identity = await _state(common_db, handle.harness_execution_id)
        assert session["state"] == "open" and session["ended_at"] is None
        assert execution["lifecycle"] == "live"
        replacement_start = identity["open_turn"].copy()
        await writer.write(
            [
                observation("late-old-result", FrameKind.RUN_RESULT, turn="old"),
                observation("unattributed-result", FrameKind.RUN_RESULT, turn=None),
                observation("replayed-old-start", FrameKind.TURN_STARTED, turn="old"),
                observation("duplicate-new-start", FrameKind.TURN_STARTED, turn="new"),
                observation("unattributed-start", FrameKind.TURN_STARTED, turn=None),
            ]
        )
        session, execution, identity = await _state(common_db, handle.harness_execution_id)
        assert session["state"] == "open" and execution["lifecycle"] == "live"
        assert identity["open_turn"] == replacement_start
        await writer.write(
            [
                observation("new-end", FrameKind.TURN_ENDED, {"status": "cancelled"}, turn="new"),
                observation("late-old-after-new-end", FrameKind.RUN_RESULT, turn="old"),
            ]
        )
        session, execution, identity = await _state(common_db, handle.harness_execution_id)
        assert session["state"] == "open" and execution["lifecycle"] == "live"
        assert "open_turn" not in identity
        await writer.write([observation("new-result", FrameKind.RUN_RESULT, turn="new")])
        session, execution, _ = await _state(common_db, handle.harness_execution_id)
        assert session["state"] == "closed" and execution["lifecycle"] == "ended"
        await writer.write([observation("replayed-closed-new", FrameKind.TURN_STARTED, turn="new")])
        await FrameWriter(repository, handle, clock=StepClock(FRAME_NOW)).write(
            [observation("unseen-historical-start", FrameKind.TURN_STARTED, turn="history")]
        )
        session, execution, identity = await _state(common_db, handle.harness_execution_id)
        assert session["state"] == "closed" and execution["lifecycle"] == "ended"
        assert "open_turn" not in identity
        assert (
            len(
                await repository.frames_for_execution(
                    common_db.scope(), handle.harness_execution_id, 1
                )
            )
            == 14
        )
    finally:
        await pool.close()


@pytest.mark.parametrize("lane", [LaneProfile.DEEP_AGENTS, LaneProfile.CODEX])
async def test_delayed_old_end_keeps_replacement_and_attributes_its_own_usage(
    common_db: CommonDatabase,
    lane: LaneProfile,
) -> None:
    pool = await common_db.pool()
    try:
        admitted = await admit_unit_attempt(pool, common_db)
        repository = PostgresFrameRepository(pool)
        handle = await repository.open_execution(admitted.start(lane=lane))
        writer = FrameWriter(repository, handle, clock=StepClock())

        def usage(tokens: int) -> dict[str, Any]:
            if lane == LaneProfile.CODEX:
                return {"tokenUsage": {"last": {"inputTokens": tokens}}}
            return {"input_tokens": tokens}

        await writer.write(
            [
                observation("old-start", FrameKind.TURN_STARTED, turn="old"),
                observation(
                    "old-child-start",
                    FrameKind.TURN_STARTED,
                    turn="child-old",
                    subordinate_ref="child:old",
                ),
                observation("old-usage", FrameKind.USAGE, usage(11), turn="old"),
                observation(
                    "old-child-usage",
                    FrameKind.USAGE,
                    usage(5),
                    turn="child-old",
                    subordinate_ref="child:old",
                ),
                observation("new-start", FrameKind.TURN_STARTED, turn="new"),
                observation("new-usage", FrameKind.USAGE, usage(97), turn="new"),
                observation(
                    "new-child-usage",
                    FrameKind.USAGE,
                    usage(101),
                    turn="child-new",
                    subordinate_ref="child:new",
                ),
                observation(
                    "late-old-end", FrameKind.TURN_ENDED, {"status": "cancelled"}, turn="old"
                ),
                observation("late-old-result", FrameKind.RUN_RESULT, turn="old"),
            ]
        )
        session, execution, identity = await _state(common_db, handle.harness_execution_id)
        assert session["state"] == "open" and execution["lifecycle"] == "live"
        assert identity["open_turn"]["native_turn_ref"] == "new"
        turns = await owner_rows(
            common_db,
            "SELECT native_turn_ref, started_frame_id, usage FROM mission_control.session_turn "
            "WHERE session_id = $1 ORDER BY turn_no",
            session["session_id"],
        )
        frames = await repository.frames_for_execution(
            common_db.scope(), handle.harness_execution_id, 1
        )
        assert len(turns) == 1 and turns[0]["native_turn_ref"] == "old"
        assert turns[0]["started_frame_id"] == frames[0].frame_id
        assert json.loads(turns[0]["usage"])["dimensions"]["input_tokens"]["value"] == 16
        await writer.write(
            [
                observation("new-end", FrameKind.TURN_ENDED, {"status": "cancelled"}, turn="new"),
                observation("new-result", FrameKind.RUN_RESULT, turn="new"),
            ]
        )
        session, execution, identity = await _state(common_db, handle.harness_execution_id)
        assert session["state"] == "closed" and execution["lifecycle"] == "ended"
        assert "open_turn" not in identity and identity["turns_closed"] == 2
        replacement = await owner_rows(
            common_db,
            "SELECT usage FROM mission_control.session_turn "
            "WHERE session_id = $1 AND native_turn_ref = 'new'",
            session["session_id"],
        )
        assert json.loads(replacement[0]["usage"])["dimensions"]["input_tokens"]["value"] == 198
    finally:
        await pool.close()


async def test_unidentified_legacy_session_result_still_closes(common_db: CommonDatabase) -> None:
    pool = await common_db.pool()
    try:
        admitted = await admit_unit_attempt(pool, common_db)
        repository = PostgresFrameRepository(pool)
        handle = await repository.open_execution(admitted.start())
        await FrameWriter(repository, handle, clock=StepClock()).write(
            [observation("legacy-result", FrameKind.RUN_RESULT, turn=None)]
        )
        session, execution, _ = await _state(common_db, handle.harness_execution_id)
        assert session["state"] == "closed" and execution["lifecycle"] == "ended"
    finally:
        await pool.close()


async def test_old_end_after_replacement_end_does_not_reassign_latest_turn(
    common_db: CommonDatabase,
) -> None:
    pool = await common_db.pool()
    try:
        admitted = await admit_unit_attempt(pool, common_db)
        repository = PostgresFrameRepository(pool)
        handle = await repository.open_execution(admitted.start())
        writer = FrameWriter(repository, handle, clock=StepClock())
        await writer.write(
            [
                observation("old-start", FrameKind.TURN_STARTED, turn="old"),
                observation("new-start", FrameKind.TURN_STARTED, turn="new"),
                observation("new-end", FrameKind.TURN_ENDED, {"status": "cancelled"}, turn="new"),
                observation("old-late-end", FrameKind.TURN_ENDED, turn="old"),
                observation("old-late-result", FrameKind.RUN_RESULT, turn="old"),
            ]
        )
        session, execution, identity = await _state(common_db, handle.harness_execution_id)
        assert session["state"] == "open" and execution["lifecycle"] == "live"
        assert identity["latest_turn"] == {"native_turn_ref": "new", "generation": 1}
        await writer.write([observation("new-result", FrameKind.RUN_RESULT, turn="new")])
        session, execution, _ = await _state(common_db, handle.harness_execution_id)
        assert session["state"] == "closed" and execution["lifecycle"] == "ended"
    finally:
        await pool.close()


async def test_unobserved_root_start_does_not_inherit_child_usage(
    common_db: CommonDatabase,
) -> None:
    pool = await common_db.pool()
    try:
        admitted = await admit_unit_attempt(pool, common_db)
        repository = PostgresFrameRepository(pool)
        handle = await repository.open_execution(admitted.start())
        await FrameWriter(repository, handle, clock=StepClock()).write(
            [
                observation(
                    "unattributed-child-usage",
                    FrameKind.USAGE,
                    {"input_tokens": 41},
                    turn="child-unknown",
                    subordinate_ref="child:unknown",
                ),
                observation("new-start", FrameKind.TURN_STARTED, turn="new"),
                observation(
                    "new-child-usage",
                    FrameKind.USAGE,
                    {"input_tokens": 97},
                    turn="child-new",
                    subordinate_ref="child:new",
                ),
                observation("unobserved-old-end", FrameKind.TURN_ENDED, turn="old"),
            ]
        )
        session, execution, identity = await _state(common_db, handle.harness_execution_id)
        assert session["state"] == "open" and execution["lifecycle"] == "live"
        assert identity["open_turn"]["native_turn_ref"] == "new"
        old = await owner_rows(
            common_db,
            "SELECT started_frame_id, usage FROM mission_control.session_turn "
            "WHERE session_id = $1 AND native_turn_ref = 'old'",
            session["session_id"],
        )
        assert old[0]["started_frame_id"] is None
        assert json.loads(old[0]["usage"])["dimensions"]["input_tokens"]["value"] is None
    finally:
        await pool.close()
