"""MP-06 on the real local Temporal server (127.0.0.1:7233, `make temporal-up`).

The real `OperationWorkflow` drives the real `lane.*` activities on isolated task queues;
every history is replayed with `Replayer`. Providers are labelled fixtures
(`tests/support/lanes.py`); nothing here proves live provider behaviour.

- V07: the worker dies after the provider accepted the send and before the local receipt.
  Another worker takes the session over once the lease expires (higher epoch), reconciles
  the journaled send (PostgreSQL 17) and observes it: one native turn, never two; the dead
  owner's late receipt is refused.
- V06: an immediate cancel's Stop Fence lands while `cancel_and_replace` drains the old
  turn: the replacement is never sent, the pre-fence effect keeps its disposition, a
  post-fence effect is denied, and the four cancel timestamps are recorded independently.
- MP-05 wiring: a provider limit refusal waits for the reset on a Temporal timer (patched
  `mp05-capacity-wait`) and the turn is sent once after it; a cancel during a long reset wait
  wakes it at once and nothing is sent.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from mission_control.adapters.temporal.operation_activities import (
    parse_operation_result,
)
from mission_control.adapters.temporal.workflows.operation import (
    CAPACITY_WAIT_PATCH,
)
from mission_control.application.execution.harness.dispatch import StaleSessionOwner
from mission_control.application.execution.harness.lane_turns import (
    LaneExecutionIdentity,
    LaneTurnService,
)
from mission_control.application.execution.harness.sessions import WorkerSessionManager
from mission_control.application.execution.stop_fence import (
    InMemoryStopFenceRepository,
    KernelHookFenceGate,
)
from mission_control.application.frames.sink import InMemoryFrameStore
from mission_control.domain.execution.contracts import (
    OperationExecutionRequest,
)
from mission_control.domain.execution.lanes import (
    CancelReceipt,
    CancelTurnRequest,
)
from mission_control.domain.policies.stop_fence import EffectAdmission, StopFence
from tests.support.db import CommonDatabase
from tests.support.db_builders import pg_lane_unit
from tests.support.integration.temporal.dispatch_recovery_temporal import (
    _activity_worker,
    _client,
    _replayed,
    _request,
    _scheduled,
    _start,
    _workflow_worker,
)
from tests.support.lanes import (
    CapacityLimitedLane,
    ReconcilingLossyLane,
    ScriptedSessionLane,
    cursor_binding,
    cursor_operation,
    lane_stack,
    scripted_frames,
)
from tests.support.temporal import patch_ids


def _attempts(history: Any) -> list[int]:
    return [
        event.activity_task_started_event_attributes.attempt
        for event in history.events
        if event.HasField("activity_task_started_event_attributes")
    ]


# --- V07: crash between the native send and the local receipt ---------------------------------


@pytest.mark.common_db
async def test_a_worker_lost_after_the_native_send_never_duplicates_the_turn(
    common_db: CommonDatabase,
) -> None:
    client = await _client()
    lane_queue, workflow_queue = f"mp06-lane-{uuid4().hex[:8]}", f"mp06-wf-{uuid4().hex[:8]}"
    pool = await common_db.pool("mission_control_runtime")
    try:
        lane = ReconcilingLossyLane(frames=scripted_frames(), loss="hang")
        unit = await pg_lane_unit(pool, common_db, lane, task_queue=lane_queue)
        worker_a = unit.service("worker-a")
        worker_b = unit.service("worker-b")
        scope, heid = unit.identity.request_scope, unit.identity.harness_execution_id
        async with _workflow_worker(client, workflow_queue):
            dying = _activity_worker(client, lane_queue, unit.stack.boundary, worker_a)
            running = asyncio.create_task(dying.run())
            handle = await _start(client, _request(unit.operation), workflow_queue, "mp06-v07")
            await asyncio.wait_for(lane.accepted_event.wait(), timeout=60)
            # The provider accepted the turn; the worker dies before the receipt is recorded.
            await dying.shutdown()
            with suppress(BaseException):
                await running
            state = await unit.states.load(scope, heid)
            assert state is not None and state.owner is not None
            dead_owner = state.owner
            pending = state.dispatch("send", unit.send_key)
            assert pending is not None and pending.phase == "intended"
            assert state.native_turn_ref is None

            async with _activity_worker(client, lane_queue, unit.stack.boundary, worker_b):
                result = await asyncio.wait_for(handle.result(), timeout=180)
            # The dead process's in-flight call returns late: its receipt is refused.
            lane.hang_release.set()
            await asyncio.sleep(1)
            history = await _replayed(handle)

        assert result.disposition == "completed"
        assert parse_operation_result(result.result).status == "completed"
        assert lane.native_sends == [unit.send_key], "one native turn, never a duplicate"
        assert lane.ledger.accepted == {unit.send_key: "run-fake-1"}
        assert lane.lookups == [f"send:{unit.send_key}"]
        assert _scheduled(history) == ["lane.turn", "lane.cleanup"], (
            "retries of one activity, nothing re-sent"
        )
        assert max(_attempts(history)) >= 2
        state = await unit.states.load(scope, heid)
        assert state is not None and state.owner is not None
        assert (state.owner.owner_ref, state.owner.epoch) == (
            worker_b.sessions.owner_ref,
            dead_owner.epoch + 1,
        )
        record = state.dispatch("send", unit.send_key)
        assert record is not None and record.phase == "acknowledged"
        assert (record.owner_ref, record.owner_epoch) == (state.owner.owner_ref, state.owner.epoch)
        assert state.native_turn_ref == "run-fake-1"
        with pytest.raises(StaleSessionOwner):
            await unit.states.assert_owner(scope, heid, dead_owner)
    finally:
        await pool.close()


# --- V06: a cancel racing cancel_and_replace ---------------------------------------------------


@dataclass
class _FencedDuringDrainLane(ScriptedSessionLane):
    """FIXTURE: the operator's immediate cancel persists its Stop Fence exactly while the
    lane cancels the old turn for an `interrupt_and_inject` replacement."""

    fences: Any = None
    fence: StopFence | None = None
    fenced: asyncio.Event = field(default_factory=asyncio.Event)

    async def cancel_turn(self, request: CancelTurnRequest) -> CancelReceipt:
        if request.reason == "interrupt_and_inject" and self.fence is not None:
            await self.fences.persist(self.fence)
            self.fenced.set()
        return await super().cancel_turn(request)


async def test_a_stop_fence_during_cancel_and_replace_blocks_the_replacement() -> None:
    from tests.support.cursor_lane_controls import FAST, admitted_unit, compose_control_stack

    client = await _client()
    lane_queue, workflow_queue = f"mp06-lane-{uuid4().hex[:8]}", f"mp06-wf-{uuid4().hex[:8]}"
    fences = InMemoryStopFenceRepository()
    run_control, repository, run_id, unit, changes = await admitted_unit((), None)
    operation = OperationExecutionRequest.model_validate(
        {
            **cursor_operation(binding=cursor_binding(task_queue=lane_queue)).model_dump(
                mode="python"
            ),
            **changes,
        }
    )
    frames = [
        ("system", {"subtype": "init"}),
        ("tool_call", {"call_id": "call-0", "status": "running"}),
        ("tool_call", {"call_id": "call-0", "status": "completed"}),
        *scripted_frames(tool_calls=0)[1:],
    ]
    lane = _FencedDuringDrainLane(frames=frames, hold_after=2, fences=fences)
    lane.fence = StopFence(
        request_scope=operation.request_scope,
        run_id=run_id,
        generation=1,
        command_id="cancel-now",
        reason="operator immediate cancel",
        requested_at=datetime.now(UTC),
    )
    stack = compose_control_stack(
        None,
        lane,
        InMemoryFrameStore(),
        operation,
        run_control=run_control,
        repository=repository,
        run_id=run_id,
        unit=unit,
        settings=FAST,
        profile="cursor_local",
    )
    stack.lanes.boundary._stop_fences = fences
    service = LaneTurnService(
        lanes=stack.service._lanes,
        boundary=stack.lanes.boundary,
        frames=stack.lanes.frames,
        states=stack.lanes.states,
        mailbox=stack.mailbox,
        injections=stack.injections,
        sessions=WorkerSessionManager(owner_ref="worker-a"),
        fences=fences,
    )
    gate = KernelHookFenceGate(fences)
    scope = operation.request_scope

    def effect(ref: str) -> EffectAdmission:
        return EffectAdmission(
            request_scope=scope, run_id=run_id, generation=1, effect_ref=ref, effect_kind="shell"
        )

    async with (
        _workflow_worker(client, workflow_queue),
        _activity_worker(client, lane_queue, stack.lanes.boundary, service),
    ):
        handle = await _start(client, _request(operation), workflow_queue, "mp06-v06")
        await asyncio.wait_for(lane.held.wait(), timeout=60)
        pre = await gate.before_effect(effect("call-0"))  # admitted while the tool ran
        await stack.command("interrupt_and_inject", "Use release/2.3.")
        await asyncio.wait_for(lane.fenced.wait(), timeout=60)
        receipt = await handle.execute_update("cancel_command", args=["cancel-now", "immediate"])
        post = await gate.before_effect(effect("call-1"))  # the agent tries another tool
        result = await asyncio.wait_for(handle.result(), timeout=180)
        history = await _replayed(handle)

    assert pre.allowed and not post.allowed and post.frame is not None
    assert (await gate.before_effect(effect("call-0"))).allowed, "pre-fence stays admitted"
    assert receipt["delivery_semantics"] == "turn_boundary_guaranteed"
    assert result.disposition == "cancelled"
    assert len(lane.sends) == 1, "the replacement was never sent after the fence"
    assert lane.cancels and lane.cancels[0] == "interrupt_and_inject"
    identity = LaneExecutionIdentity.of(operation, "cursor_local", 1)
    state = await stack.lanes.states.load(identity.request_scope, identity.harness_execution_id)
    assert state is not None
    replacement = state.dispatch("send", f"{identity.harness_execution_id}:1:replace:run-fake-1")
    # The fence itself refused the replacement dispatch (a denied governed effect).
    assert replacement is not None
    assert (replacement.phase, replacement.reason) == ("declined", "stop_fenced")
    report = await fences.report(scope, run_id)
    assert report is not None
    assert report.provider_acknowledged_at is not None and report.settled_at is not None
    assert report.requested_at <= report.fence_persisted_at
    assert report.fence_persisted_at <= report.provider_acknowledged_at <= report.settled_at
    assert "lane.turn" in _scheduled(history)


# --- MP-05 capacity wait wired into the segment loop -------------------------------------------


async def test_a_provider_limit_waits_on_a_temporal_timer_then_sends_once() -> None:
    client = await _client()
    lane_queue, workflow_queue = f"mp06-lane-{uuid4().hex[:8]}", f"mp06-wf-{uuid4().hex[:8]}"
    operation = cursor_operation(binding=cursor_binding(task_queue=lane_queue))
    lane = CapacityLimitedLane(frames=scripted_frames(), limited=1, reset_in_s=2)
    stack = lane_stack(lane, operation=operation)
    service = LaneTurnService(
        lanes=stack.service._lanes,
        boundary=stack.boundary,
        frames=stack.frames,
        states=stack.states,
        sessions=WorkerSessionManager(owner_ref="worker-a"),
    )
    async with (
        _workflow_worker(client, workflow_queue),
        _activity_worker(client, lane_queue, stack.boundary, service),
    ):
        handle = await _start(client, _request(operation), workflow_queue, "mp06-capacity")
        result = await asyncio.wait_for(handle.result(), timeout=180)
        history = await _replayed(handle)

    assert result.disposition == "completed"
    assert lane.refusals == 1 and len(lane.sends) == 1
    assert CAPACITY_WAIT_PATCH in patch_ids(history)
    timers = [event for event in history.events if event.HasField("timer_started_event_attributes")]
    assert timers, "the reset was waited out on a Temporal timer"
    assert _scheduled(history) == ["lane.turn", "lane.turn", "lane.cleanup"]


async def _timer_started(handle: Any) -> None:
    async with asyncio.timeout(60):
        while True:
            history = await handle.fetch_history()
            if any(event.HasField("timer_started_event_attributes") for event in history.events):
                return
            await asyncio.sleep(0.1)


async def test_a_cancel_wakes_a_long_provider_limit_wait_and_nothing_is_sent() -> None:
    """A cancel during a ten-minute reset wait wakes it at once on real Temporal timers, so
    the cancel path reaches the pending turn: nothing is sent and the unit settles cancelled."""

    client = await _client()
    lane_queue, workflow_queue = f"mp06-lane-{uuid4().hex[:8]}", f"mp06-wf-{uuid4().hex[:8]}"
    operation = cursor_operation(binding=cursor_binding(task_queue=lane_queue))
    lane = CapacityLimitedLane(frames=scripted_frames(), limited=1, reset_in_s=600)
    stack = lane_stack(lane, operation=operation)
    service = LaneTurnService(
        lanes=stack.service._lanes,
        boundary=stack.boundary,
        frames=stack.frames,
        states=stack.states,
        sessions=WorkerSessionManager(owner_ref="worker-a"),
    )
    began = asyncio.get_running_loop().time()
    async with (
        _workflow_worker(client, workflow_queue),
        _activity_worker(client, lane_queue, stack.boundary, service),
    ):
        handle = await _start(client, _request(operation), workflow_queue, "mp06-capacity-cancel")
        await _timer_started(handle)
        await handle.execute_update("cancel_command", args=["cancel-during-wait", "normal"])
        result = await asyncio.wait_for(handle.result(), timeout=60)
        history = await _replayed(handle)

    assert asyncio.get_running_loop().time() - began < 60, "the wait never ran to its reset"
    assert result.disposition == "cancelled"
    assert lane.refusals == 1 and lane.sends == []
    assert CAPACITY_WAIT_PATCH in patch_ids(history)
    assert _scheduled(history).count("lane.turn") == 1
