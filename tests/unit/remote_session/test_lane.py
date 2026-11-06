"""HL-04: the Remote Session Lane base's staging, stream-then-reconcile observe loop, dispatch
routing and handover state, proven against a scripted provider (FIXTURE)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from mission_control.adapters.cursor.describe import CURSOR_CLOUD_DESCRIBE
from mission_control.adapters.remote_session.errors import (
    CapacityLimited,
    InvalidStreamCursor,
    StreamExpired,
)
from mission_control.adapters.remote_session.lane import FINAL_TEXT_FIELDS, terminal_text
from mission_control.adapters.remote_session.sse import SseEvent
from mission_control.adapters.remote_session.stream import STREAM_START, StreamOpened
from mission_control.adapters.remote_session.wake import SessionWake
from mission_control.application.execution.harness.controls import SessionHandover
from mission_control.application.execution.harness.dispatch import (
    DispatchKind,
    DispatchRecord,
    ProviderCapacityLimited,
    instruction_digest,
)
from mission_control.application.execution.harness.protocol import NativeTurnLost
from mission_control.domain.execution.lanes import LaneFrame
from tests.unit.remote_session.support import (
    PROFILE,
    SESSION,
    TURN,
    ScriptedRemoteLane,
    event,
    observe_request,
    observed,
    opened,
    session_handle,
    staged_lane,
)


def _keys(frames: list[LaneFrame]) -> list[str]:
    return [frame.provider_key for frame in frames]


# --- staging ---------------------------------------------------------------------------------


def test_the_describe_must_name_the_lanes_profile() -> None:
    class Mislabelled(ScriptedRemoteLane):
        def __init__(self) -> None:
            super(ScriptedRemoteLane, self).__init__(describe=CURSOR_CLOUD_DESCRIBE)

    with pytest.raises(ValueError, match=PROFILE):
        Mislabelled()


async def test_staging_is_idempotent_per_operation_and_refreshes_identity_per_generation() -> None:
    lane = ScriptedRemoteLane()
    op = staged_lane(lane)
    lane.stage("heid-1", op)  # the same operation again: a no-op
    other = op.model_copy(update={"request_scope": op.request_scope + "-other"})
    with pytest.raises(ValueError, match="another operation"):
        lane.stage("heid-1", other)
    with pytest.raises(ValueError, match="bound operation"):
        lane.stage("heid-2", op.model_copy(update={"lane_binding": None}))
    request = observe_request(op).model_copy(update={"generation": 3})
    assert lane._session(request).identity.attempt_no == 3
    with pytest.raises(NativeTurnLost, match="not staged"):
        lane._session(observe_request(op, "heid-unknown"))


async def test_later_turn_texts_and_the_handover_offer_are_session_state() -> None:
    lane = ScriptedRemoteLane()
    staged_lane(lane)
    lane.stage_turn("heid-1", "replace:turn-1", "do it differently")
    session = lane._sessions["heid-1"]
    assert session.turn_texts == {"replace:turn-1": "do it differently"}
    with pytest.raises(NativeTurnLost):
        lane.stage_turn("heid-unknown", "x", "y")
    session.session_ref = SESSION
    session.handover = SessionHandover(
        transfer_id="t-1",
        session=session_handle(ref="sess-2"),
        instruction_ref="continuation:t-1",
        source_session_ref=SESSION,
    )
    assert (await lane.pending_handover("heid-1")) is session.handover
    await lane.complete_handover("heid-1", "t-other")
    assert session.session_ref == SESSION, "another transfer completes nothing"
    await lane.complete_handover("heid-1", "t-1")
    assert session.session_ref == "sess-2" and session.handover is None
    assert await lane.pending_handover("heid-unknown") is None


def test_rehydration_facts_accumulate_once_each() -> None:
    lane = ScriptedRemoteLane()
    staged_lane(lane)
    session = lane._sessions["heid-1"]
    session.record_rehydration(["branch"])
    session.record_rehydration([])
    session.record_rehydration(["branch", "workspace_lease"])
    assert lane.rehydration_receipt("heid-1") == ("branch", "workspace_lease")
    assert lane.rehydration_receipt("heid-unknown") == ()


def test_a_wake_names_the_staged_execution_of_its_session_only() -> None:
    lane = ScriptedRemoteLane()
    staged_lane(lane)
    lane._sessions["heid-1"].session_ref = SESSION
    wake = SessionWake(
        lane_profile=PROFILE, delivery_id="d-1", event_type="session.idle", resource_ref=SESSION
    )
    assert lane.wake_target(wake) == "heid-1"
    assert lane.wake_target(SessionWake("cursor_cloud", "d-1", "x", SESSION)) is None
    assert lane.wake_target(SessionWake(PROFILE, "d-1", "x", "sess-other")) is None


# --- observe: stream ---------------------------------------------------------------------------


async def test_events_are_keyed_by_id_or_content_until_the_terminal_event() -> None:
    lane = ScriptedRemoteLane(
        streams=[
            [
                opened(retention=600),
                event("status", {"status": "running"}),
                event("ping"),
                event("message", {"text": "hello"}, "1"),
                event("turn.done", {"status": "done", "result": "all good"}, "2"),
                event("message", {"text": "after the end"}, "3"),
            ]
        ]
    )
    op = staged_lane(lane)
    frames = await observed(lane, observe_request(op))
    assert [frame.raw_kind for frame in frames] == ["status", "status", "message", "turn.done"]
    opened_frame, status, message, done = frames
    assert opened_frame.provider_key == f"sse-open:{TURN}:start"
    assert opened_frame.body == {
        "stream": "opened",
        "retention_seconds": 600,
        "last_event_id": None,
    }
    assert status.provider_key.startswith(f"sse-content:status:{TURN}:")
    assert status.cursor == STREAM_START, "an id-less event does not move the cursor"
    assert (message.provider_key, message.cursor) == (f"sse:{TURN}:1", f"{TURN}@1")
    assert done.terminal and done.body["attributed_to"] == f"{SESSION}/{TURN}"
    assert lane._sessions["heid-1"].retention_seconds == 600
    assert lane.calls.reads == 0, "a terminal event needs no turn record"
    assert lane.final_text(None, done) == "all good"  # type: ignore[arg-type]


async def test_a_stored_cursor_resumes_at_its_event_and_a_replay_stores_nothing_twice() -> None:
    first: list[SseEvent | StreamOpened | Exception] = [
        opened(),
        event("status", {"status": "running"}),
        event("message", {"n": 1}, "1"),
    ]
    lane = ScriptedRemoteLane(
        streams=[
            [*first, event("end")],
            [
                opened(after="1"),
                event("status", {"status": "running"}),
                event("turn.done", {}, "2"),
            ],
        ],
        records=[{"status": "running"}],
    )
    op = staged_lane(lane)
    segment = await observed(lane, observe_request(op))
    assert not any(frame.terminal for frame in segment), "the stream ended; the turn did not"
    assert lane.calls.reads == 1, "an ended stream asks the turn record once, then yields"
    resumed = await observed(lane, observe_request(op, after=segment[-1].cursor))
    assert lane.calls.opened_after == [None, "1"]
    status_keys = [k for k in _keys(segment + resumed) if k.startswith("sse-content:")]
    assert len(set(status_keys)) == 1, "the re-sent leading status has one key"
    assert resumed[-1].terminal and resumed[-1].cursor == f"{TURN}@2"


async def test_a_cursor_of_another_turn_resumes_from_the_start() -> None:
    lane = ScriptedRemoteLane(streams=[[opened(), event("turn.done", {}, "1")]])
    op = staged_lane(lane)
    await observed(lane, observe_request(op, after="turn-0@7"))
    assert lane.calls.opened_after == [None]


async def test_a_refused_cursor_replays_the_stream_once_from_the_start() -> None:
    lane = ScriptedRemoteLane(
        streams=[
            InvalidStreamCursor("foreign cursor"),
            [opened(), event("message", {}, "1"), event("turn.done", {}, "2")],
        ]
    )
    op = staged_lane(lane)
    frames = await observed(lane, observe_request(op, after=f"{TURN}@zz"))
    assert lane.calls.opened_after == ["zz", None]
    assert frames[-1].terminal and len(set(_keys(frames))) == len(frames)


# --- observe: reconcile from the turn record ---------------------------------------------------


async def test_an_ended_stream_settles_from_a_terminal_turn_record() -> None:
    lane = ScriptedRemoteLane(
        streams=[[opened(), event("message", {}, "1"), event("end")]],
        records=[{"status": "DONE", "result": "from the record"}],
    )
    op = staged_lane(lane)
    frames = await observed(lane, observe_request(op))
    final = frames[-1]
    assert final.terminal and final.raw_kind == "turn.final"
    assert final.provider_key == f"scripted:{TURN}:final" and final.cursor == f"{TURN}@1"
    assert final.body["synthesized_from"] == "turn_record"
    assert final.body["observation"] == {"source": "turn_record", "stream": "ended"}
    assert final.body["attributed_to"] == f"{SESSION}/{TURN}"


async def test_expiry_is_recorded_once_and_the_record_is_polled_with_one_frame_per_change() -> None:
    lane = ScriptedRemoteLane(
        streams=[[opened(retention=30), event("message", {}, "4"), StreamExpired("gone")]],
        records=[
            {"status": "running"},
            {"status": "running"},
            {"status": "finishing"},
            {"status": "failed", "error": {"code": "boom"}},
        ],
        poll_limit=10,
    )
    op = staged_lane(lane)
    frames = await observed(lane, observe_request(op, after=f"{TURN}@3"))
    expired = [frame for frame in frames if frame.provider_key.startswith("sse-expired:")]
    assert len(expired) == 1
    assert expired[0].provider_key == f"sse-expired:{TURN}:3"
    assert expired[0].body == {
        "stream": "expired",
        "retention_seconds": 30,
        "last_event_id": "3",
        "observation": "turn_record",
    }
    statuses = [frame for frame in frames if frame.provider_key.startswith("turn-status:")]
    assert [frame.body["status"] for frame in statuses] == ["running", "finishing"]
    assert statuses[0].body == {"turn_ref": TURN, "status": "running", "observation": "turn_record"}
    final = frames[-1]
    assert final.terminal and final.body["observation"] == {
        "source": "turn_record",
        "stream": "expired",
    }
    assert lane._sessions["heid-1"].expired_streams == {TURN: f"{TURN}@4"}


async def test_an_expired_turn_never_reopens_its_stream_and_polling_is_bounded() -> None:
    lane = ScriptedRemoteLane(streams=[[opened(), StreamExpired("gone")]], poll_limit=3)
    op = staged_lane(lane)
    first = await observed(lane, observe_request(op))
    assert lane.calls.reads == 3, "the poll limit bounds one observe call"
    again = await observed(lane, observe_request(op))
    assert lane.calls.opened_after == [None], "the stream is never asked again"
    assert lane.calls.reads == 6
    assert not any(frame.terminal for frame in first + again)
    (status,) = [frame for frame in first if frame.provider_key.startswith("turn-status:")]
    assert _keys(again) == [status.provider_key], "an unchanged status keeps its one key"


async def test_expiry_during_a_cursor_replay_still_reconciles_the_turn() -> None:
    lane = ScriptedRemoteLane(
        streams=[InvalidStreamCursor("foreign"), [opened(), StreamExpired("gone")]],
        records=[{"status": "done"}],
    )
    op = staged_lane(lane)
    frames = await observed(lane, observe_request(op, after=f"{TURN}@foreign"))
    assert lane.calls.opened_after == ["foreign", None]
    assert frames[-1].terminal and frames[-1].raw_kind == "turn.final"


async def test_a_lost_turn_record_loses_the_turn() -> None:
    lane = ScriptedRemoteLane(streams=[[opened(), event("end")]], records=[{"status": "gone"}])
    op = staged_lane(lane)
    with pytest.raises(NativeTurnLost):
        await observed(lane, observe_request(op))


async def test_nothing_is_observed_without_a_provider_turn() -> None:
    lane = ScriptedRemoteLane()
    op = staged_lane(lane)
    request = observe_request(op)
    no_turn = request.turn.model_copy(update={"native_turn_ref": None})
    with pytest.raises(NativeTurnLost, match="no provider turn"):
        await observed(lane, request.model_copy(update={"turn": no_turn}))


# --- observe: a provider without native resume ---------------------------------------------------


async def test_history_is_replayed_after_the_stream_opens_and_live_duplicates_are_dropped() -> None:
    lane = ScriptedRemoteLane(
        streams=[
            [
                opened(retention=None),
                event("message", {"n": 2}, "e2"),
                event("message", {"n": 3}, "e3"),
                event("turn.done", {"status": "done"}, "e4"),
            ]
        ],
        history=[event("message", {"n": 1}, "e1"), event("message", {"n": 2}, "e2")],
    )
    op = staged_lane(lane)
    frames = await observed(lane, observe_request(op))
    assert _keys(frames) == [
        f"sse-open:{TURN}:start",
        f"sse:{TURN}:e1",
        f"sse:{TURN}:e2",
        f"sse:{TURN}:e3",
        f"sse:{TURN}:e4",
    ]
    assert frames[-1].terminal


# --- reading, dispatch, capacity -----------------------------------------------------------------


def test_the_final_text_is_the_first_non_empty_text_field() -> None:
    assert FINAL_TEXT_FIELDS == ("result", "text")
    assert terminal_text({"result": "", "text": "fallback"}) == "fallback"
    assert terminal_text({"result": {"not": "text"}}) is None
    assert terminal_text({}) is None
    assert terminal_text({"output": "x"}, ("output",)) == "x"


def test_resume_cursors_come_from_the_codec() -> None:
    lane = ScriptedRemoteLane()
    assert lane.resume_cursor(f"sse:{TURN}:9") == f"{TURN}@9"
    assert lane.resume_cursor("sse-content:status:x") is None


def _record(kind: DispatchKind, key: str) -> DispatchRecord:
    return DispatchRecord(
        kind=kind,
        idempotency_key=key,
        expected_generation=1,
        instruction_digest=instruction_digest(
            kind=kind,
            instruction_ref=None,
            binding_digest="sha256:" + "0" * 64,
            turn_no=1,
        ),
        owner_ref="worker",
        owner_epoch=1,
        intended_at=datetime(2026, 10, 12, tzinfo=UTC),
    )


async def test_reconcile_dispatch_routes_by_the_parsed_dispatch_key() -> None:
    lane = ScriptedRemoteLane()
    staged_lane(lane)
    malformed = await lane.reconcile_dispatch(_record("create", "not-a-key"), session=None)
    assert malformed.outcome == "unknown" and "names no execution" in malformed.detail
    create = await lane.reconcile_dispatch(_record("create", "heid-1:1:turn:1"), session=None)
    assert create.outcome == "not_received"
    send = await lane.reconcile_dispatch(
        _record("send", "heid-1:1:turn:2"), session=session_handle()
    )
    assert send.outcome == "unknown", "no acknowledged turn anchors the session yet"
    lane._sessions["heid-1"].turns.acknowledge("turn-1")
    accepted = await lane.reconcile_dispatch(
        _record("send", "heid-1:1:turn:3"), session=session_handle()
    )
    assert (accepted.outcome, accepted.native_ref) == ("found", "turn-9")
    assert lane.calls.reconciled == [("create", "heid-1"), ("send", "turn"), ("send", "turn")]


def test_a_429_becomes_the_lanes_capacity_signal() -> None:
    lane = ScriptedRemoteLane()
    raised = lane._capacity(CapacityLimited("send", native_code="rate_limited", retry_after_s=5))
    assert isinstance(raised, ProviderCapacityLimited)
    assert raised.signal.lane_profile == PROFILE
    assert raised.signal.source == f"{PROFILE}.http_429"
    assert raised.signal.resets_at is not None
