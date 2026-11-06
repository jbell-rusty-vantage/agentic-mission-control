"""HL-08 on the real local Temporal server (127.0.0.1:7233, `make temporal-up`) and a
disposable PostgreSQL 17 (127.0.0.1:55433, `MISSION_CONTROL_TEST_ADMIN_DSN`).

The real `OperationWorkflow` segment loop drives the real `claude_managed` harness over the
FIXTURE Managed Agents API (`tests/fixtures/managed_agents.FakeManagedAgentsApi` behind
`httpx.MockTransport`), with frames, lane state, the MP-06 dispatch journal, session ownership
and the MO-16 environment preparation record in PostgreSQL (runtime role, forced RLS); every
history is replayed with `Replayer`. No Anthropic API is called and nothing here proves live
provider behaviour.

The worker is killed while the turn runs (its activity worker shuts down with no grace after
frames were persisted). A second worker, with a fresh harness process and no in-process state,
takes the session over when Temporal retries the segment: it reattaches to the same session,
resumes from the persisted frames' position and settles the turn. One session, one message,
each event stored once, one closing frame.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import pytest
from temporalio.client import Client, WorkflowHandle
from temporalio.worker import Replayer, Worker

from mission_control.adapters.anthropic_managed.harness import ClaudeManagedHarness
from mission_control.adapters.deep_agents.harness import DeepAgentsHarness
from mission_control.adapters.operations.conformance import ConformanceRuntime
from mission_control.adapters.postgres.environments.preparation_repository import (
    PostgresEnvironmentPreparationRepository,
)
from mission_control.adapters.postgres.frames.repository import PostgresFrameRepository
from mission_control.adapters.postgres.lanes.execution_state import PostgresLaneExecutionStateStore
from mission_control.adapters.temporal.operation_activities import (
    OperationExecutionActivities,
    parse_operation_result,
)
from mission_control.adapters.temporal.registration.activities import agent_cognitive_activities
from mission_control.adapters.temporal.workflow_sandbox import coordinator_workflow_runner
from mission_control.adapters.temporal.workflows.operation import OperationWorkflow
from mission_control.application.environments.preparation import EnvironmentPreparationService
from mission_control.application.execution.harness.lane_turns import (
    LaneExecutionIdentity,
    LaneTurnService,
)
from mission_control.application.execution.harness.sessions import WorkerSessionManager
from mission_control.application.resolution.registries import LaneRegistry
from mission_control.domain.execution.contracts import (
    OperationAttemptIdentity,
    OperationExecutionRequest,
    OperationWorkflowRequest,
)
from mission_control.domain.execution.environment_preparation import ReadinessLevel
from mission_control.domain.execution.lanes import LaneSegmentBounds
from mission_control.domain.frames.contracts import FrameKind
from tests.fixtures.lane_turns import LaneStack, lane_stack
from tests.fixtures.managed_lane import (
    PROFILE,
    ManagedStack,
    managed_binding,
    managed_harness,
    managed_operation,
    managed_stack,
)
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.integration.postgres.frames_common import admit_unit_attempt
from tests.integration.postgres.runtime_common import common_db  # noqa: F401

ADDRESS = os.environ.get("MC_TEMPORAL_TEST_ADDRESS", "127.0.0.1:7233")
NAMESPACE = os.environ.get("MC_TEMPORAL_TEST_NAMESPACE", "default")
BOUNDS = LaneSegmentBounds(
    max_frames=50,
    max_duration_s=30,
    start_to_close_s=60,
    heartbeat_timeout_s=3,
    status_poll_limit=3,
    status_poll_interval_s=1,
    busy_wait_s=30,
)
WITHIN_S = 120.0


async def _client() -> Client:
    try:
        return await Client.connect(ADDRESS, namespace=NAMESPACE)
    except RuntimeError as error:
        pytest.fail(f"the real local Temporal server at {ADDRESS} is required: {error}")


@dataclass
class PgManagedUnit:
    operation: OperationExecutionRequest
    lanes: LaneStack
    managed: ManagedStack
    frames: PostgresFrameRepository
    states: PostgresLaneExecutionStateStore
    preparations: PostgresEnvironmentPreparationRepository

    @property
    def identity(self) -> LaneExecutionIdentity:
        return LaneExecutionIdentity.of(self.operation, PROFILE, 1)

    def service(self, harness: ClaudeManagedHarness, owner: str) -> LaneTurnService:
        """One worker process: its own harness instance and session manager."""

        return LaneTurnService(
            lanes=LaneRegistry(
                [DeepAgentsHarness(ConformanceRuntime()), harness], allow_unqualified=True
            ),
            boundary=self.lanes.boundary,
            frames=self.frames,
            states=self.states,
            frame_reader=self.frames,
            sessions=WorkerSessionManager(owner_ref=owner, min_lease=timedelta(seconds=1)),
            preparations=EnvironmentPreparationService(self.preparations),
        )


async def pg_managed_unit(
    pool: asyncpg.Pool, db: CommonDatabase, tmp_path: Path, *, task_queue: str
) -> PgManagedUnit:
    """A `claude_managed` operation bound to one admitted runtime unit of a real run in
    PostgreSQL, over the fixture API (its binding sealed with the test queue)."""

    admitted = await admit_unit_attempt(pool, db)
    unit = admitted.unit
    managed = managed_stack(tmp_path, scripts=("held",))
    binding = managed_binding(managed.pack.materialization_digest, task_queue=task_queue)
    payload = managed_operation(binding).model_dump(mode="python")
    payload.update(
        request_scope=unit.request_scope,
        identity=OperationAttemptIdentity(
            run_id=admitted.run_key,
            operation_id=unit.semantic_operation_id,
            operation_attempt=unit.semantic_attempt,
        ),
        runtime_unit=unit,
        idempotency_key=f"hl08:{unit.unit_key}",
    )
    operation = OperationExecutionRequest.model_validate(payload)
    managed.operation = operation
    return PgManagedUnit(
        operation=operation,
        lanes=lane_stack(managed.harness, operation=operation),
        managed=managed,
        frames=PostgresFrameRepository(pool),
        states=PostgresLaneExecutionStateStore(pool),
        preparations=PostgresEnvironmentPreparationRepository(pool),
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


def _workflow_worker(client: Client, queue: str) -> Worker:
    return Worker(
        client,
        task_queue=queue,
        workflows=[OperationWorkflow],
        workflow_runner=coordinator_workflow_runner(),
    )


def _activity_worker(client: Client, queue: str, boundary: Any, service: LaneTurnService) -> Worker:
    activities = OperationExecutionActivities(
        boundary, worker_identity=service.sessions.owner_ref, lane_turns=service
    )
    return Worker(
        client,
        task_queue=queue,
        activities=agent_cognitive_activities(activities),
        graceful_shutdown_timeout=timedelta(0),
    )


async def _replayed(handle: WorkflowHandle[Any, Any]) -> Any:
    history = await handle.fetch_history()
    await Replayer(
        workflows=[OperationWorkflow], workflow_runner=coordinator_workflow_runner()
    ).replay_workflow(history)
    return history


async def _frames_stored(unit: PgManagedUnit) -> int:
    scope, heid = unit.identity.request_scope, unit.identity.harness_execution_id
    return len(await unit.frames.frames_for_execution(scope, heid, 1, limit=1_000))


async def _frames_stored_at_least(unit: PgManagedUnit, count: int) -> int:
    """How many frames the held turn persisted, once at least `count` are."""

    for _poll in range(int(WITHIN_S / 0.1)):
        stored = await _frames_stored(unit)
        if stored >= count:
            return stored
        await asyncio.sleep(0.1)
    raise AssertionError(f"fewer than {count} frames persisted within {WITHIN_S:g}s")


@pytest.mark.common_db
async def test_a_worker_killed_mid_turn_is_reattached_by_another_without_duplicate_frames(
    common_db: CommonDatabase,  # noqa: F811
    tmp_path: Path,
) -> None:
    client = await _client()
    lane_queue, workflow_queue = f"hl08-lane-{uuid4().hex[:8]}", f"hl08-wf-{uuid4().hex[:8]}"
    pool = await common_db.pool("mission_control_runtime")
    try:
        unit = await pg_managed_unit(pool, common_db, tmp_path, task_queue=lane_queue)
        api = unit.managed.api
        first = unit.service(unit.managed.harness, f"hl08-worker-a-{uuid4().hex[:6]}")
        async with _workflow_worker(client, workflow_queue):
            dying = _activity_worker(client, lane_queue, unit.lanes.boundary, first)
            running = asyncio.create_task(dying.run())
            handle = await client.start_workflow(
                OperationWorkflow.run,
                _request(unit.operation),
                id=f"hl08-kill-{uuid4().hex[:10]}",
                task_queue=workflow_queue,
                execution_timeout=timedelta(minutes=5),
            )
            await asyncio.wait_for(api.held.wait(), WITHIN_S)
            before = await _frames_stored_at_least(unit, 4)
            # The worker dies with the turn still running at the provider.
            await dying.shutdown()
            await asyncio.gather(running, return_exceptions=True)
            api.release()
            # Another worker process: a fresh harness, nothing of the first one's state.
            successor = managed_harness(api, unit.managed.pack, deletions=unit.managed.deletions)
            second = unit.service(successor, f"hl08-worker-b-{uuid4().hex[:6]}")
            async with _activity_worker(client, lane_queue, unit.lanes.boundary, second):
                result = await asyncio.wait_for(handle.result(), WITHIN_S)
            history = await _replayed(handle)

        assert result.disposition == "completed"
        assert parse_operation_result(result.result).status == "completed"
        scheduled = [
            event.activity_task_scheduled_event_attributes.activity_type.name
            for event in history.events
            if event.HasField("activity_task_scheduled_event_attributes")
        ]
        assert scheduled.count("lane.turn") >= 1
        assert len(api.sessions) == 1 and len(api.messages()) == 1, "one session, one send"
        (session_id,) = api.sessions
        assert api.archived() == [session_id] and len(unit.managed.deletions.orders) == 1

        scope, heid = unit.identity.request_scope, unit.identity.harness_execution_id
        frames = await unit.frames.frames_for_execution(scope, heid, 1, limit=1_000)
        assert len(frames) > before > 0, "the successor stored what the first did not"
        keys = [frame.provider_key for frame in frames]
        assert len(keys) == len(set(keys)), "frames stored once in PostgreSQL"
        assert [frame.kind for frame in frames].count(FrameKind.RUN_RESULT) == 1
        stored_events = [frame.raw_kind for frame in frames if frame.raw_kind != "status"]
        provider_events = [
            event["type"]
            for event in api.events[session_id]
            if event["type"] != "session.status_running"
        ]
        assert stored_events == provider_events, "every event of the turn stored once, in order"

        state = await unit.states.load(scope, heid)
        assert state is not None and state.native_session_ref == session_id
        create = state.dispatch("create", f"{heid}:1:turn:1")
        send = state.dispatch("send", f"{heid}:1:turn:1")
        assert create is not None and create.phase == "acknowledged" and create.attempts == 1
        assert send is not None and send.phase == "acknowledged" and send.attempts == 1
        assert send.native_ref == state.native_turn_ref

        # MO-16: the launch was admitted at `delivered`, the provider environment.
        (record,) = await unit.preparations.for_run(scope, unit.identity.run_key)
        assert record.readiness == ReadinessLevel.DELIVERED
        assert record.harness_execution_id == UUID(str(heid))
        assert record.deliveries[0].channel == "provider_environment"
    finally:
        await pool.close()
