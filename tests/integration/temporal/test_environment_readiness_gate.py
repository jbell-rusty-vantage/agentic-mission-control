"""MO-16: the launch readiness gate inside the real `mc.operation.v1` workflow.

Time-skipping Temporal drives `OperationWorkflow` against the real lane activities, with the
environment preparation records in a disposable PostgreSQL 17 (MISSION_CONTROL_TEST_ADMIN_DSN).
An environment below the launch policy's minimum never starts its session: the one `lane.turn`
settles `failed(environment_not_ready)` and the record stays `declared`. A prepared environment
runs to completion and its record reaches `prepared`. Every history replays.
"""

from __future__ import annotations

import asyncio
from typing import Any

import asyncpg
import pytest
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from mission_control.adapters.postgres.environments import (
    PostgresEnvironmentPreparationRepository,
)
from mission_control.adapters.temporal.operation_activities import (
    OperationExecutionActivities,
    parse_operation_result,
)
from mission_control.adapters.temporal.registration.activities import agent_cognitive_activities
from mission_control.adapters.temporal.workflow_sandbox import coordinator_workflow_runner
from mission_control.adapters.temporal.workflows.operation import OperationWorkflow
from mission_control.application.environments import EnvironmentPreparationService
from mission_control.application.execution.harness.lane_turns import LaneExecutionIdentity
from mission_control.domain.execution.contracts import (
    OperationExecutionRequest,
    OperationWorkflowRequest,
)
from mission_control.domain.execution.environment_preparation import ENVIRONMENT_NOT_READY
from mission_control.domain.execution.lanes import LaneSegmentBounds
from tests.fixtures.lane_turns import (
    ACTIVATION_UUID,
    LANE_QUEUE,
    RUN_UUID,
    PreparingLane,
    ScriptedSessionLane,
    cursor_operation,
    lane_stack,
    scripted_frames,
)
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.integration.postgres.runtime_common import common_db, owner_rows  # noqa: F401

pytestmark = pytest.mark.common_db

WORKFLOW_QUEUE = "mo16-operation-workflows"
BOUNDS = LaneSegmentBounds(max_duration_s=30, start_to_close_s=60, heartbeat_timeout_s=10)


def _operation(scope: str) -> OperationExecutionRequest:
    return cursor_operation(request_scope=scope)


def _identity(scope: str) -> LaneExecutionIdentity:
    return LaneExecutionIdentity.of(_operation(scope), "cursor_local", 1)


async def _time_skipping() -> WorkflowEnvironment:
    try:
        return await WorkflowEnvironment.start_time_skipping()
    except RuntimeError as error:
        pytest.skip(f"Temporal test server is unavailable: {error}")


def _scheduled(history: Any) -> list[str]:
    return [
        event.activity_task_scheduled_event_attributes.activity_type.name
        for event in history.events
        if event.HasField("activity_task_scheduled_event_attributes")
    ]


async def _run(db: CommonDatabase, lane: Any, workflow_id: str) -> tuple[Any, Any]:
    pool = await db.pool("mission_control_runtime")
    env = await _time_skipping()
    try:
        operation = _operation(db.scope())
        preparations = EnvironmentPreparationService(PostgresEnvironmentPreparationRepository(pool))
        stack = lane_stack(lane, operation=operation, preparations=preparations)
        stack.frames.register_run(
            db.scope(),
            operation.identity.run_id,
            RUN_UUID,
            {operation.identity.operation_id: ACTIVATION_UUID},
        )
        activities = OperationExecutionActivities(
            stack.boundary, worker_identity="mo16-worker", lane_turns=stack.service
        )
        request = OperationWorkflowRequest(
            semantic_attempt_id=operation.identity.semantic_key,
            operation_kind="bound_operation",
            operation=operation,
            segments=BOUNDS,
        )
        async with (
            env,
            Worker(
                env.client,
                task_queue=WORKFLOW_QUEUE,
                workflows=[OperationWorkflow],
                workflow_runner=coordinator_workflow_runner(),
            ),
            Worker(
                env.client,
                task_queue=LANE_QUEUE,
                activities=agent_cognitive_activities(activities),
            ),
        ):
            handle = await env.client.start_workflow(
                OperationWorkflow.run, request, id=workflow_id, task_queue=WORKFLOW_QUEUE
            )
            result = await asyncio.wait_for(handle.result(), timeout=120)
            history = await handle.fetch_history()
            await Replayer(
                workflows=[OperationWorkflow], workflow_runner=coordinator_workflow_runner()
            ).replay_workflow(history)
        return result, history
    finally:
        await pool.close()


async def _readiness(db: CommonDatabase) -> list[asyncpg.Record]:
    return await owner_rows(
        db,
        "SELECT readiness, receipt_digest FROM mission_control.environment_preparation "
        "WHERE harness_execution_id = $1",
        _identity(db.scope()).harness_execution_id,
    )


@pytest.mark.asyncio
async def test_the_operation_workflow_never_starts_an_unprepared_environment(
    common_db: CommonDatabase,  # noqa: F811
) -> None:
    lane = ScriptedSessionLane(frames=scripted_frames())
    result, history = await _run(common_db, lane, "mo16-unprepared")

    settled = parse_operation_result(result.result)
    assert settled.status == "failed" and settled.failure_code == ENVIRONMENT_NOT_READY
    assert _scheduled(history)[0] == "lane.turn" and _scheduled(history).count("lane.turn") == 1
    assert "start" not in lane.calls and not lane.sends
    (row,) = await _readiness(common_db)
    assert (row["readiness"], row["receipt_digest"]) == ("declared", None)


@pytest.mark.asyncio
async def test_the_operation_workflow_runs_a_prepared_environment(
    common_db: CommonDatabase,  # noqa: F811
) -> None:
    lane = PreparingLane(frames=scripted_frames())
    result, _history = await _run(common_db, lane, "mo16-prepared")

    assert result.disposition == "completed"
    assert parse_operation_result(result.result).status == "completed"
    (row,) = await _readiness(common_db)
    assert row["readiness"] == "prepared" and row["receipt_digest"] is not None
