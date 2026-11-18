"""MP-07 production routing on the real local Temporal server (127.0.0.1:7233) and the
disposable PostgreSQL 17 (`MISSION_CONTROL_TEST_ADMIN_DSN`, scratch `mct_*` databases).

A claude unit runs through the production `OperationWorkflow` (`mc.operation.v1` segment
loop, `SEGMENT_LOOP_PATCH`): `OperationWorkflowRequest.activity_task_queue` routes its
`lane.turn` segments to `provider_binding.task_queue`, where the production
`OperationExecutionActivities` run `LaneTurnService` over `PostgresFrameRepository` and
`PostgresLaneExecutionStateStore` (runtime role) with the FIXTURE SDK client
(`tests/unit/claude/fixtures.py`: no Claude Code runs, nothing is paid for). Every history is
replayed with `Replayer` against `OperationWorkflow`.

The MP-07 test-local segment loop (`mp07_segment_loop.py`) only stood in for this workflow
while the queue delta was missing; it proved nothing the production workflow does not, and
was removed.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from mission_control.adapters.temporal.operation_activities import (
    parse_operation_result,
)
from mission_control.adapters.temporal.workflows.operation import (
    SEGMENT_LOOP_PATCH,
)
from mission_control.application.execution.harness.lane_turns import (
    LaneExecutionIdentity,
)
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.execution.contracts import (
    OperationWorkflowResult,
)
from mission_control.domain.execution.lanes import CursorExecutionBinding
from mission_control.domain.frames.contracts import FrameKind
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.fixtures.temporal_history import completed_activity_results, patch_ids
from tests.support.integration.temporal.mp07_claude_lane_turns import (
    WORKER,
    claude_unit,
    operation_workers,
    queues,
    replayed,
    start_operation,
    temporal_client,
    workflow_request,
)
from tests.unit.claude.fixtures import (
    PROFILE,
    SESSION_ID,
    claude_operation,
)


def scheduled(history: Any) -> list[str]:
    return [
        event.activity_task_scheduled_event_attributes.activity_type.name
        for event in history.events
        if event.HasField("activity_task_scheduled_event_attributes")
    ]


def lane_queues(history: Any) -> set[str]:
    return {
        event.activity_task_scheduled_event_attributes.task_queue.name
        for event in history.events
        if event.HasField("activity_task_scheduled_event_attributes")
    }


@pytest.mark.common_db
async def test_a_claude_unit_runs_through_the_production_operation_workflow(
    common_db: CommonDatabase,
    tmp_path: Path,
) -> None:
    client = await temporal_client()
    lane_queue, workflow_queue = queues()
    pool = await common_db.pool("mission_control_runtime")
    try:
        stack, service, frames, states = await claude_unit(
            pool, common_db, tmp_path, script="full_run", lane_queue=lane_queue
        )
        request = workflow_request(stack.operation)
        # The production routing: the claude unit's segments go to its binding's queue.
        assert request.segment_driven and request.activity_task_queue == lane_queue
        async with operation_workers(client, stack, service, workflow_queue):
            handle = await start_operation(client, request, workflow_queue)
            result: OperationWorkflowResult = await asyncio.wait_for(handle.result(), timeout=180)
            history = await replayed(handle)

        assert result.disposition == "completed"
        settled = parse_operation_result(result.result)
        assert settled.status == "completed"
        names = scheduled(history)
        # Segments of three, then MO-05's `lane.cleanup` after the settlement.
        assert names[-1] == "lane.cleanup" and set(names[:-1]) == {"lane.turn"}
        assert len(names) >= 4, "segments of three"
        cleaned = completed_activity_results(history, "lane.cleanup")
        assert [entry["outcome"] for entry in cleaned] == ["removed"]
        assert lane_queues(history) == {lane_queue}
        assert SEGMENT_LOOP_PATCH in patch_ids(history)
        client_fixture = stack.factory.last
        assert len(stack.factory.clients) == 1, "the live session outlived every segment"
        assert len(client_fixture.sent) == 1, "segments reattach; the turn is sent once"
        assert client_fixture.disconnected, "end_session closed the SDK client"
        identity = LaneExecutionIdentity.of(stack.operation, PROFILE, 1)
        stored = await frames.frames_for_execution(
            identity.request_scope, identity.harness_execution_id, 1, limit=10_000
        )
        ordinals = [frame.arrival_ordinal for frame in stored]
        assert ordinals == list(range(1, len(ordinals) + 1)), "no duplicate frame across segments"
        kinds = [frame.kind for frame in stored]
        assert kinds[0] is FrameKind.SESSION_INIT and kinds[-1] is FrameKind.RUN_RESULT
        assert FrameKind.HOOK_RESULT in kinds and FrameKind.TOOL_CALL_COMPLETED in kinds
        assert {frame.native_session_ref for frame in stored} == {SESSION_ID}
        state = await states.load(identity.request_scope, identity.harness_execution_id)
        assert state is not None and state.native_session_ref == SESSION_ID
        assert state.native_turn_ref == client_fixture.sent[0][0]
        assert state.owner is not None and state.owner.owner_ref == WORKER
        send = state.dispatch("send", f"{identity.harness_execution_id}:1:turn:1")
        assert send is not None and send.phase == "acknowledged"
        create = state.dispatch("create", f"{identity.harness_execution_id}:1:turn:1")
        assert create is not None and (create.phase, create.native_ref) == (
            "acknowledged",
            SESSION_ID,
        )
        (lease,) = stack.workspace.registry.values()
        assert lease.released and state.bridge_state_root is not None
        assert not await asyncio.to_thread(Path(lease.path).exists), "removed after settlement"
    finally:
        await pool.close()


@pytest.mark.common_db
async def test_a_provider_error_result_settles_failed_capacity_through_the_operation_workflow(
    common_db: CommonDatabase,
    tmp_path: Path,
) -> None:
    client = await temporal_client()
    lane_queue, workflow_queue = queues()
    pool = await common_db.pool("mission_control_runtime")
    try:
        stack, service, _frames, _states = await claude_unit(
            pool, common_db, tmp_path, script="error_result", lane_queue=lane_queue
        )
        request = workflow_request(stack.operation)
        async with operation_workers(client, stack, service, workflow_queue):
            handle = await start_operation(client, request, workflow_queue)
            result: OperationWorkflowResult = await asyncio.wait_for(handle.result(), timeout=180)
            history = await replayed(handle)
        assert result.disposition == "failed"
        settled = parse_operation_result(result.result)
        assert settled.status == "failed"
        assert set(scheduled(history)) == {"lane.turn"}
        assert lane_queues(history) == {lane_queue}
        assert "capacity" in (settled.failure_code or "") + (settled.failure_message or "")
    finally:
        await pool.close()


def test_the_operation_request_routes_a_claude_unit_to_its_binding_queue() -> None:
    """`activity_task_queue` reads `provider_binding.task_queue` (the integrated delta); a
    claude unit carries no Cursor binding and no native placement."""

    operation = claude_operation(task_queue="mp07-lane-queue")
    request = workflow_request(operation)
    assert (
        CursorExecutionBinding.carried_by(operation) is None and operation.native_placement is None
    )
    assert ProviderExecutionBinding.carried_by(operation) is not None
    assert request.activity_task_queue == "mp07-lane-queue"
