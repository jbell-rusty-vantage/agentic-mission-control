"""Production placement refusal uses a real durable Temporal timer before prepare."""

import asyncio
from uuid import uuid4

from mission_control.application.execution.harness.lane_turns import LaneTurnService
from mission_control.application.execution.harness.sessions import WorkerSessionManager
from mission_control.application.workspaces.placement import PlacementAdmission
from mission_control.domain.execution.placement import PlacementLimit
from tests.integration.temporal.test_mp06_dispatch_recovery import (
    CapacityLimitedLane,
    _activity_worker,
    _client,
    _replayed,
    _request,
    _scheduled,
    _start,
    _workflow_worker,
    cursor_binding,
    cursor_operation,
    lane_stack,
    scripted_frames,
)


class OneCapacityWait:
    """Synthetic occupancy; PostgreSQL concurrency is tested separately."""

    def __init__(self):
        self.reserves = 0

    async def reserve(self, scope, execution, profile, limit, now):
        self.reserves += 1
        return self.reserves > 1

    async def release(self, scope, execution):
        pass


async def test_placement_capacity_waits_on_real_temporal_timer_before_prepare():
    client = await _client()
    lane_queue, workflow_queue = f"mo52-lane-{uuid4().hex[:8]}", f"mo52-wf-{uuid4().hex[:8]}"
    operation = cursor_operation(binding=cursor_binding(task_queue=lane_queue))
    lane = CapacityLimitedLane(frames=scripted_frames(), limited=0, reset_in_s=1)
    stack = lane_stack(lane, operation=operation)
    store = OneCapacityWait()
    service = LaneTurnService(
        lanes=stack.service._lanes,
        boundary=stack.boundary,
        frames=stack.frames,
        states=stack.states,
        sessions=WorkerSessionManager(owner_ref="worker-a"),
        placement=PlacementAdmission(
            store, {"cursor_local": PlacementLimit(max_active=1, retry_after_s=1)}
        ),
    )
    async with (
        _workflow_worker(client, workflow_queue),
        _activity_worker(client, lane_queue, stack.boundary, service),
    ):
        handle = await _start(client, _request(operation), workflow_queue, "mo52-capacity")
        result = await asyncio.wait_for(handle.result(), timeout=60)
        history = await _replayed(handle)
    assert result.disposition == "completed"
    assert store.reserves == 2 and len(lane.sends) == 1
    assert any(event.HasField("timer_started_event_attributes") for event in history.events)
    assert _scheduled(history) == ["lane.turn", "lane.turn", "lane.cleanup"]
