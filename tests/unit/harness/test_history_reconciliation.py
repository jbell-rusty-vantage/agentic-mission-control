"""MO75: owner-only native replay, exact receipts, and bounded pending ingress."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from mission_control.adapters.cursor.describe import CURSOR_CLOUD_DESCRIBE
from mission_control.application.execution.harness.dispatch import StaleSessionOwner
from mission_control.application.execution.harness.lane_turns import LaneExecutionIdentity
from mission_control.application.execution.harness.state import (
    InMemoryLaneExecutionStateStore,
    LaneExecutionState,
    LaneExecutionUpdate,
)
from mission_control.domain.execution.history_reconciliation import (
    HistoryAcknowledgment,
    HistoryDeferred,
    HistoryJournal,
    HistoryReplayComplete,
    HistoryReplayIncomplete,
    HistoryRequest,
    enqueue_history,
)
from mission_control.domain.execution.lane_turns import LaneSegmentBounds, LaneTurnRequest
from tests.fixtures.lane_turns import (
    RecordingSignals,
    ScriptedSessionLane,
    cursor_operation,
    lane_stack,
    scripted_frames,
)

NOW = datetime(2026, 10, 14, tzinfo=UTC)


def history_request(**changes):
    return HistoryRequest.model_validate(
        {
            "request_scope": "scope",
            "run_id": "run",
            "harness_execution_id": uuid4(),
            "generation": 1,
            "lane_profile": "cursor_cloud",
            "session_binding_id": uuid4(),
            "workflow_id": "workflow",
            "native_session_ref": "session",
            "native_turn_ref": "turn",
            "ingress_id": uuid4(),
            "received_at": NOW,
            **changes,
        }
    )


async def state_for(request):
    states = InMemoryLaneExecutionStateStore()
    owner = await states.claim_owner(
        request.request_scope,
        request.harness_execution_id,
        owner_ref="owner",
        generation=request.generation,
        now=NOW,
        lease=timedelta(minutes=5),
    )
    await states.record(
        request.request_scope,
        request.harness_execution_id,
        LaneExecutionUpdate(
            native_session_ref=request.native_session_ref, native_turn_ref=request.native_turn_ref
        ),
    )
    return states, owner


async def test_enqueue_close_and_supersession_are_serialized():
    request = history_request()
    states, owner = await state_for(request)
    await states.request_history(request)
    with pytest.raises(HistoryDeferred):
        await states.close_history_window(
            request.request_scope, request.harness_execution_id, owner=owner, native_turn_ref="turn"
        )
    with pytest.raises(HistoryDeferred):
        await states.record(
            request.request_scope,
            request.harness_execution_id,
            LaneExecutionUpdate(native_turn_ref="next", supersedes_turn_ref="turn"),
        )
    await states.acknowledge_history(request, owner=owner, cursor="durable", at=NOW)
    await states.close_history_window(
        request.request_scope, request.harness_execution_id, owner=owner, native_turn_ref="turn"
    )
    assert (await states.request_history(request)).covers(request)
    later = request.model_copy(
        update={"ingress_id": uuid4(), "received_at": NOW + timedelta(seconds=1)}
    )
    with pytest.raises(ValueError, match="closed"):
        await states.request_history(later)
    await states.record(
        request.request_scope,
        request.harness_execution_id,
        LaneExecutionUpdate(native_turn_ref="next", supersedes_turn_ref="turn"),
    )
    state = await states.load(request.request_scope, request.harness_execution_id)
    assert state.history_closed_turn is None
    with pytest.raises(ValueError, match="identity"):
        await states.request_history(later)
    next_request = later.model_copy(update={"native_turn_ref": "next"})
    await states.request_history(next_request)
    await states.acknowledge_history(next_request, owner=owner, cursor="next-durable", at=NOW)
    # A crash before wake of the prior turn retains exactly that turn's proof.
    journal = await states.request_history(request)
    assert journal.receipt_for(request).persisted_cursor == "durable"
    assert not journal.covers(later)


async def test_close_wins_and_stale_owner_cannot_acknowledge():
    request = history_request()
    states, owner = await state_for(request)
    await states.close_history_window(
        request.request_scope, request.harness_execution_id, owner=owner, native_turn_ref="turn"
    )
    with pytest.raises(ValueError, match="closed"):
        await states.request_history(request)
    with pytest.raises(StaleSessionOwner):
        await states.acknowledge_history(
            request, owner=owner.model_copy(update={"owner_ref": "other"}), cursor="x", at=NOW
        )


def test_coalescing_is_monotonic_and_receipt_capacity_never_evicts():
    request = history_request()
    journal = HistoryJournal(requested=request)
    later = request.model_copy(update={"received_at": NOW + timedelta(seconds=1)})
    assert enqueue_history(journal, later).requested == later
    assert enqueue_history(enqueue_history(journal, later), request).requested == later
    other_turn = later.model_copy(update={"native_turn_ref": "next"})
    with pytest.raises(HistoryDeferred):
        enqueue_history(journal, other_turn)
    receipts = tuple(
        HistoryAcknowledgment(
            request=request.model_copy(update={"native_turn_ref": str(i)}),
            acknowledged_at=NOW,
            persisted_cursor=str(i),
        )
        for i in range(64)
    )
    saturated = HistoryJournal(requested=receipts[-1].request, acknowledgments=receipts)
    with pytest.raises(HistoryDeferred, match="capacity"):
        enqueue_history(saturated, other_turn)
    assert len(saturated.acknowledgments) == 64
    assert not saturated.covers(request)


def test_absent_fields_preserve_legacy_serialization():
    state = LaneExecutionState(harness_execution_id=uuid4())
    from mission_control.domain.authoring.canonical import stable_json_dump

    assert "history_" not in state.model_dump_json()
    assert not any(key.startswith("history_") for key in stable_json_dump(state))


class HistoryLane(ScriptedSessionLane):
    def __init__(self, *, incomplete=False):
        super().__init__(
            frames=scripted_frames(), hold_after=1, describe_matrix=CURSOR_CLOUD_DESCRIBE
        )
        self.incomplete = incomplete
        self.replays = 0
        self.observing = False

    async def observe(self, request):
        self.observing = True
        try:
            async for frame in super().observe(request):
                yield frame
        finally:
            self.observing = False

    async def reconcile_history(self, request):
        assert not self.observing, "owner must close its outstanding SSE read first"
        self.replays += 1
        if self.incomplete:
            raise HistoryReplayIncomplete("fixture missing finite boundary")
        self.hold_after = None
        async for frame in super().observe(request):
            yield frame
        yield HistoryReplayComplete()


@pytest.mark.parametrize("incomplete", [False, True])
async def test_idle_sse_owner_drains_history_without_workflow_wake(monkeypatch, incomplete):
    monkeypatch.setattr(
        "mission_control.application.execution.harness.lane_turns.HISTORY_POLL_SECONDS", 0.01
    )
    lane = HistoryLane(incomplete=incomplete)
    operation = cursor_operation("cursor_cloud")
    stack = lane_stack(lane, operation=operation)
    identity = LaneExecutionIdentity.of(operation, "cursor_cloud", 1)
    request = LaneTurnRequest(
        operation=operation,
        lane_profile="cursor_cloud",
        generation=1,
        segment=LaneSegmentBounds(max_duration_s=1, start_to_close_s=5, heartbeat_timeout_s=3),
    )
    running = asyncio.create_task(
        stack.service.turn(request, RecordingSignals(stack.frames, identity.harness_execution_id))
    )
    await asyncio.wait_for(lane.held.wait(), 2)
    hint = history_request(
        request_scope=identity.request_scope,
        run_id=identity.run_key,
        harness_execution_id=identity.harness_execution_id,
        native_session_ref="agent-fake-1",
        native_turn_ref="run-fake-1",
    )
    await stack.states.request_history(hint)
    result = await asyncio.wait_for(running, 5)
    state = await stack.states.load(identity.request_scope, identity.harness_execution_id)
    assert state.history_reconciliation.covers(hint) is not incomplete
    assert result.done is not incomplete
    assert lane.replays == 1
    assert len(lane.sends) == 1 and not lane.cancels
    if not incomplete:
        assert len(stack.frames._executions[identity.harness_execution_id].frames) == len(
            scripted_frames()
        )


async def test_interrupt_refuses_pending_history_before_delivery_or_provider_effect(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from mission_control.application.execution.harness.lane_turns import _SegmentProgress
    from mission_control.domain.execution.lanes import SessionHandle, TurnHandle

    monkeypatch.setattr(
        "mission_control.application.execution.harness.lane_turns.unit_boundary",
        lambda operation: ("stage_graph", "stage"),
    )
    operation = cursor_operation("cursor_cloud")
    lane = HistoryLane(incomplete=True)
    stack = lane_stack(lane, operation=operation)
    identity = LaneExecutionIdentity.of(operation, "cursor_cloud", 1)
    hint = history_request(
        request_scope=identity.request_scope,
        run_id=identity.run_key,
        harness_execution_id=identity.harness_execution_id,
    )
    states, owner = await state_for(hint)
    stack.service._states = states
    await states.request_history(hint)
    deliver = AsyncMock()
    stack.service._mailbox = SimpleNamespace(deliver=deliver)
    stack.service._injections = object()
    request = LaneTurnRequest(operation=operation, lane_profile="cursor_cloud", generation=1)
    fields = stack.service._fields(operation, identity, 1, "observe")
    session = SessionHandle(
        lane_profile="cursor_cloud",
        harness_execution_id=str(identity.harness_execution_id),
        generation=1,
        native_session_ref="session",
    )
    turn = TurnHandle(session=session, turn_no=1, native_turn_ref="turn")
    with pytest.raises(HistoryDeferred):
        await stack.service._interrupt(
            request,
            lane,
            identity,
            fields,
            turn,
            SimpleNamespace(command_id="inject"),
            AsyncMock(),
            RecordingSignals(stack.frames),
            _SegmentProgress(owner=owner),
            cancel_first=True,
        )
    assert deliver.await_count == 0 and not lane.sends and not lane.cancels


async def test_simultaneous_frame_and_history_watch_persists_the_consumed_frame(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from mission_control.application.execution.harness.lane_turns import _SegmentProgress
    from mission_control.domain.execution.lanes import SessionHandle, TurnHandle

    operation = cursor_operation("cursor_cloud")
    lane = HistoryLane()
    stack = lane_stack(lane, operation=operation)
    identity = LaneExecutionIdentity.of(operation, "cursor_cloud", 1)
    hint = history_request(
        request_scope=identity.request_scope,
        run_id=identity.run_key,
        harness_execution_id=identity.harness_execution_id,
    )
    _, owner = await state_for(hint)
    monkeypatch.setattr(stack.service, "_watch_history", AsyncMock(return_value=hint))
    persisted = AsyncMock(return_value=None)
    monkeypatch.setattr(stack.service, "_take", persisted)
    request = LaneTurnRequest(operation=operation, lane_profile="cursor_cloud", generation=1)
    fields = stack.service._fields(operation, identity, 1, "observe")
    session = SessionHandle(
        lane_profile="cursor_cloud",
        harness_execution_id=str(identity.harness_execution_id),
        generation=1,
        native_session_ref="session",
    )
    turn = TurnHandle(session=session, turn_no=1, native_turn_ref="turn")
    pumped = await stack.service._pump(
        request,
        lane,
        identity,
        fields,
        turn,
        SimpleNamespace(),
        RecordingSignals(stack.frames),
        _SegmentProgress(owner=owner),
    )
    assert pumped.history == hint
    assert persisted.await_count == 1
    assert persisted.call_args.args[0].provider_key == "fake:run-fake-1:0"


@pytest.mark.parametrize("failure", ["timeout", "overflow"])
async def test_replay_timeout_and_overflow_keep_the_receipt_pending(monkeypatch, failure):
    from unittest.mock import AsyncMock

    from mission_control.application.execution.harness.lane_turns import _SegmentProgress
    from mission_control.domain.execution.lanes import SessionHandle, TurnHandle

    class BoundedLane(HistoryLane):
        async def reconcile_history(self, request):
            if failure == "timeout":
                await asyncio.Event().wait()
            self.hold_after = None
            async for frame in super(HistoryLane, self).observe(request):
                yield frame
            yield HistoryReplayComplete()

    operation = cursor_operation("cursor_cloud")
    lane = BoundedLane()
    stack = lane_stack(lane, operation=operation)
    identity = LaneExecutionIdentity.of(operation, "cursor_cloud", 1)
    hint = history_request(
        request_scope=identity.request_scope,
        run_id=identity.run_key,
        harness_execution_id=identity.harness_execution_id,
    )
    states, owner = await state_for(hint)
    stack.service._states = states
    await states.request_history(hint)
    monkeypatch.setattr(
        "mission_control.application.execution.harness.lane_turns.HISTORY_TIMEOUT_SECONDS", 0.01
    )
    monkeypatch.setattr(
        "mission_control.application.execution.harness.lane_turns.MAX_HISTORY_FRAMES", 1
    )
    monkeypatch.setattr(stack.service, "_take", AsyncMock(return_value=None))
    session = SessionHandle(
        lane_profile="cursor_cloud",
        harness_execution_id=str(identity.harness_execution_id),
        generation=1,
        native_session_ref="session",
    )
    turn = TurnHandle(session=session, turn_no=1, native_turn_ref="turn")
    result = await stack.service._replay_history(
        lane,
        identity,
        stack.service._fields(operation, identity, 1, "observe"),
        turn,
        AsyncMock(),
        RecordingSignals(stack.frames),
        _SegmentProgress(owner=owner),
        hint,
    )
    assert result.terminal is None
    state = await states.load(hint.request_scope, hint.harness_execution_id)
    assert state.history_reconciliation.pending


async def test_rejected_later_hint_preserves_prior_success_and_allows_supersession():
    from mission_control.application.execution.harness.state import reject_history_state
    from mission_control.domain.authoring.canonical import stable_json_dump

    first = history_request()
    states, owner = await state_for(first)
    initial = await states.request_history(first)
    assert "rejection" not in initial.model_dump(mode="json")
    assert "rejection" not in stable_json_dump(initial)
    await states.acknowledge_history(first, owner=owner, cursor="old-proof", at=NOW)
    later = first.model_copy(
        update={"received_at": NOW + timedelta(seconds=1), "ingress_id": uuid4()}
    )
    await states.request_history(later)
    state = await states.load(first.request_scope, first.harness_execution_id)
    rejected = reject_history_state(state, later, owner=owner, at=NOW)
    states._put(first.request_scope, state.model_copy(update={"history_reconciliation": rejected}))
    assert rejected.covers(first) and rejected.rejects(later)
    assert not rejected.covers(later) and not rejected.pending
    assert rejected.receipt_for(first).persisted_cursor == "old-proof"
    assert await states.acknowledge_history(later, owner=owner, cursor="fake", at=NOW) == rejected
    await states.close_history_window(
        first.request_scope, first.harness_execution_id, owner=owner, native_turn_ref="turn"
    )
    await states.record(
        first.request_scope,
        first.harness_execution_id,
        LaneExecutionUpdate(native_turn_ref="next", supersedes_turn_ref="turn"),
    )
    following = later.model_copy(
        update={"native_turn_ref": "next", "received_at": NOW + timedelta(seconds=2)}
    )
    assert (await states.request_history(following)).pending


@pytest.mark.parametrize("when", ["before", "during"])
async def test_rejected_hint_does_not_block_native_operation_completion(monkeypatch, when):
    from mission_control.application.execution.harness.state import reject_history_state

    monkeypatch.setattr(
        "mission_control.application.execution.harness.lane_turns.HISTORY_POLL_SECONDS", 0.01
    )
    lane = HistoryLane()
    operation = cursor_operation("cursor_cloud")
    stack = lane_stack(lane, operation=operation)
    identity = LaneExecutionIdentity.of(operation, "cursor_cloud", 1)
    rejected_event = asyncio.Event()

    async def reject(request, *, owner, at, **kwargs):
        state = await stack.states.load(request.request_scope, request.harness_execution_id)
        journal = reject_history_state(state, request, owner=owner, at=at)
        stack.states._put(
            request.request_scope, state.model_copy(update={"history_reconciliation": journal})
        )
        rejected_event.set()
        return journal

    if when == "before":
        monkeypatch.setattr(stack.states, "refresh_history_authority", reject)
    else:
        monkeypatch.setattr(stack.states, "acknowledge_history", reject)
    request = LaneTurnRequest(
        operation=operation,
        lane_profile="cursor_cloud",
        generation=1,
        segment=LaneSegmentBounds(max_duration_s=2, start_to_close_s=5, heartbeat_timeout_s=3),
    )
    running = asyncio.create_task(
        stack.service.turn(request, RecordingSignals(stack.frames, identity.harness_execution_id))
    )
    await asyncio.wait_for(lane.held.wait(), 2)
    hint = history_request(
        request_scope=identity.request_scope,
        run_id=identity.run_key,
        harness_execution_id=identity.harness_execution_id,
        native_session_ref="agent-fake-1",
        native_turn_ref="run-fake-1",
    )
    await stack.states.request_history(hint)
    await asyncio.wait_for(rejected_event.wait(), 2)
    lane.released.set()
    result = await asyncio.wait_for(running, 5)
    state = await stack.states.load(identity.request_scope, identity.harness_execution_id)
    assert result.done and state.history_reconciliation.rejects(hint)
    assert not state.history_reconciliation.covers(hint)
    assert not state.history_reconciliation.acknowledgments
    assert lane.replays == (0 if when == "before" else 1)
    assert len(lane.sends) == 1 and not lane.cancels


async def test_generation_takeover_rejects_only_exact_old_hint_and_allows_next_turn():
    request = history_request()
    states, stale = await state_for(request)
    await states.request_history(request)
    owner = await states.claim_owner(
        request.request_scope,
        request.harness_execution_id,
        owner_ref="new-owner",
        generation=2,
        now=NOW,
        lease=timedelta(minutes=5),
    )
    for invalid_owner in (stale, owner.model_copy(update={"epoch": owner.epoch + 1})):
        with pytest.raises(StaleSessionOwner):
            await states.refresh_history_authority(request, owner=invalid_owner, at=NOW)
    for changes in (
        {"native_turn_ref": "forged"},
        {"session_binding_id": uuid4()},
        {"generation": 3},
    ):
        with pytest.raises(ValueError):
            await states.refresh_history_authority(
                request.model_copy(update=changes),
                owner=owner,
                at=NOW,
            )
    with pytest.raises(ValueError):
        await states.acknowledge_history(request, owner=owner, cursor="unseen", at=NOW)
    journal = await states.refresh_history_authority(request, owner=owner, at=NOW)
    assert journal.rejects(request) and not journal.covers(request) and not journal.pending
    assert not journal.acknowledgments
    assert await states.refresh_history_authority(request, owner=owner, at=NOW) == journal
    await states.close_history_window(
        request.request_scope,
        request.harness_execution_id,
        owner=owner,
        native_turn_ref="turn",
    )
    await states.record(
        request.request_scope,
        request.harness_execution_id,
        LaneExecutionUpdate(native_turn_ref="next", supersedes_turn_ref="turn"),
    )
    following = request.model_copy(
        update={
            "generation": 2,
            "native_turn_ref": "next",
            "session_binding_id": uuid4(),
            "ingress_id": uuid4(),
            "received_at": NOW + timedelta(seconds=1),
        }
    )
    assert (await states.request_history(following)).pending


async def test_generation_takeover_resolves_old_hint_before_native_resume():
    operation = cursor_operation("cursor_cloud")
    lane = HistoryLane()
    lane.hold_after = None
    stack = lane_stack(lane, operation=operation)
    identity = LaneExecutionIdentity.of(operation, "cursor_cloud", 2)
    hint = history_request(
        request_scope=identity.request_scope,
        run_id=identity.run_key,
        harness_execution_id=identity.harness_execution_id,
        native_session_ref="agent-fake-1",
        native_turn_ref="run-fake-1",
    )
    states, _ = await state_for(hint)
    await states.request_history(hint)
    stack.service._states = states
    request = LaneTurnRequest(
        operation=operation,
        lane_profile="cursor_cloud",
        generation=2,
        phase="resume",
        segment=LaneSegmentBounds(max_duration_s=1, start_to_close_s=5, heartbeat_timeout_s=3),
    )
    result = await stack.service.turn(
        request,
        RecordingSignals(stack.frames, identity.harness_execution_id),
    )
    state = await states.load(identity.request_scope, identity.harness_execution_id)
    assert result.done and state.history_reconciliation.rejects(hint)
    assert not state.history_reconciliation.covers(hint)
    assert lane.replays == 0 and not lane.sends and not lane.cancels
