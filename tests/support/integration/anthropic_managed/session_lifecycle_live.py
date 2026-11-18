"""Builders, constants and fakes that other test files import.

Moved from tests/integration/anthropic_managed/test_session_lifecycle_live.py.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Final
from uuid import uuid4

import asyncpg
from temporalio.client import Client
from temporalio.worker import Worker

from mission_control.adapters.anthropic_managed.harness import ClaudeManagedHarness
from mission_control.adapters.deep_agents.harness import DeepAgentsHarness
from mission_control.adapters.operations.conformance import ConformanceRuntime
from mission_control.adapters.postgres.environments.preparation_repository import (
    PostgresEnvironmentPreparationRepository,
)
from mission_control.adapters.postgres.frames.repository import PostgresFrameRepository
from mission_control.adapters.postgres.lanes.execution_state import PostgresLaneExecutionStateStore
from mission_control.adapters.temporal.operation_activities import OperationExecutionActivities
from mission_control.adapters.temporal.registration.activities import agent_cognitive_activities
from mission_control.application.environments.preparation import EnvironmentPreparationService
from mission_control.application.execution.harness.lane_turns import (
    LaneExecutionIdentity,
    LaneTurnService,
)
from mission_control.application.execution.harness.sessions import WorkerSessionManager
from mission_control.application.resolution.registries import LaneRegistry
from mission_control.domain.execution.contracts import (
    OperationExecutionRequest,
    OperationWorkflowRequest,
)
from mission_control.domain.execution.lanes import LaneSegmentBounds
from tests.fixtures.lane_turns import lane_stack
from tests.fixtures.managed_lane import LANE_QUEUE, PROFILE

BOUNDS: Final = LaneSegmentBounds(
    max_frames=2_000,
    max_duration_s=240,
    start_to_close_s=300,
    # Short heartbeats: a workflow cancel reaches the running activity within seconds.
    heartbeat_timeout_s=5,
    status_poll_limit=12,
    status_poll_interval_s=5,
    busy_wait_s=120,
)


def _request(operation: OperationExecutionRequest) -> OperationWorkflowRequest:
    return OperationWorkflowRequest.model_validate(
        {
            "semantic_attempt_id": operation.identity.semantic_key,
            "operation_kind": "bound_operation",
            "operation": operation,
            "segments": BOUNDS,
        }
    )


async def _frames(frames: PostgresFrameRepository, operation: OperationExecutionRequest) -> Any:
    identity = LaneExecutionIdentity.of(operation, PROFILE, 1)
    return await frames.frames_for_execution(
        identity.request_scope, identity.harness_execution_id, 1, limit=5_000
    )


def _lane_worker(
    temporal: Client,
    harness: ClaudeManagedHarness,
    operation: OperationExecutionRequest,
    pool: asyncpg.Pool,
    frames: PostgresFrameRepository,
) -> Worker:
    """The hosted lane queue's worker for one operation: the lane turn service over the
    harness, with PostgreSQL frames, lane state and the MO-16 preparation record (the governed
    boundary is the in-memory one the lane stack binds to this operation's run)."""

    boundary = lane_stack(harness, operation=operation).boundary
    service = LaneTurnService(
        lanes=LaneRegistry(
            [DeepAgentsHarness(ConformanceRuntime()), harness], allow_unqualified=True
        ),
        boundary=boundary,
        frames=frames,
        states=PostgresLaneExecutionStateStore(pool),
        frame_reader=frames,
        sessions=WorkerSessionManager(owner_ref=f"hl08-live-{uuid4().hex[:6]}"),
        preparations=EnvironmentPreparationService(PostgresEnvironmentPreparationRepository(pool)),
    )
    activities = OperationExecutionActivities(
        boundary, worker_identity=service.sessions.owner_ref, lane_turns=service
    )
    return Worker(
        temporal,
        task_queue=LANE_QUEUE,
        activities=agent_cognitive_activities(activities),
        graceful_shutdown_timeout=timedelta(0),
    )
