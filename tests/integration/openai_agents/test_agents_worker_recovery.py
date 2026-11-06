"""Real PostgreSQL/Temporal worker-loss proof with the fixture Agents API, no paid calls."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from tests.fixtures.agents_lane import agents_harness, agents_stack
from tests.fixtures.lane_bindings import lane_fields
from tests.fixtures.lane_turns import lane_stack
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.integration.anthropic_managed.test_managed_segment_loop_real_services import (
    WITHIN_S,
    _activity_worker,
    _client,
    _replayed,
    _request,
    _workflow_worker,
)
from tests.integration.postgres.frames_common import admit_unit_attempt
from tests.integration.postgres.runtime_common import common_db  # noqa: F401

from mission_control.adapters.deep_agents.harness import DeepAgentsHarness
from mission_control.adapters.operations.conformance import ConformanceRuntime
from mission_control.adapters.postgres.environments.preparation_repository import (
    PostgresEnvironmentPreparationRepository,
)
from mission_control.adapters.postgres.frames.repository import PostgresFrameRepository
from mission_control.adapters.postgres.lanes.execution_state import PostgresLaneExecutionStateStore
from mission_control.adapters.temporal.operation_activities import parse_operation_result
from mission_control.adapters.temporal.workflows.operation import OperationWorkflow
from mission_control.application.environments.preparation import EnvironmentPreparationService
from mission_control.application.execution.harness.lane_turns import (
    LaneExecutionIdentity,
    LaneTurnService,
)
from mission_control.application.execution.harness.sessions import WorkerSessionManager
from mission_control.application.resolution.registries import LaneRegistry
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.execution.contracts import (
    OperationAttemptIdentity,
    OperationExecutionRequest,
)
from mission_control.domain.frames.contracts import FrameKind


@pytest.mark.common_db
async def test_worker_loss_restores_items_and_root_turn_once(
    common_db: CommonDatabase,  # noqa: F811
    tmp_path: Path,
) -> None:
    client = await _client()
    lane_queue, workflow_queue = f"hl12-lane-{uuid4().hex[:8]}", f"hl12-wf-{uuid4().hex[:8]}"
    pool = await common_db.pool("mission_control_runtime")
    try:
        admitted = await admit_unit_attempt(pool, common_db)
        stack = agents_stack(tmp_path, ("held",))
        binding = ProviderExecutionBinding.sealed(
            **{
                **ProviderExecutionBinding.carried_by(stack.operation).model_dump(
                    exclude={"binding_digest"}
                ),
                "task_queue": lane_queue,
            }
        )
        operation = OperationExecutionRequest.model_validate(
            {
                **stack.operation.model_dump(mode="python"),
                **lane_fields(binding),
                "request_scope": admitted.unit.request_scope,
                "runtime_unit": admitted.unit,
                "identity": OperationAttemptIdentity(
                    run_id=admitted.run_key,
                    operation_id=admitted.unit.semantic_operation_id,
                    operation_attempt=admitted.unit.semantic_attempt,
                ),
                "idempotency_key": f"hl12:{admitted.unit.unit_key}",
            }
        )
        stack.operation = operation
        lanes = lane_stack(stack.harness, operation=operation)
        frames, states = PostgresFrameRepository(pool), PostgresLaneExecutionStateStore(pool)
        preparations = PostgresEnvironmentPreparationRepository(pool)
        identity = LaneExecutionIdentity.of(operation, "codex_agents", 1)

        def service(harness, owner):
            return LaneTurnService(
                lanes=LaneRegistry(
                    [DeepAgentsHarness(ConformanceRuntime()), harness], allow_unqualified=True
                ),
                boundary=lanes.boundary,
                frames=frames,
                states=states,
                frame_reader=frames,
                sessions=WorkerSessionManager(owner_ref=owner, min_lease=timedelta(seconds=1)),
                preparations=EnvironmentPreparationService(preparations),
            )

        async with _workflow_worker(client, workflow_queue):
            dying = _activity_worker(
                client, lane_queue, lanes.boundary, service(stack.harness, "hl12-a")
            )
            running = asyncio.create_task(dying.run())
            handle = await client.start_workflow(
                OperationWorkflow.run,
                _request(operation),
                id=f"hl12-kill-{uuid4().hex[:10]}",
                task_queue=workflow_queue,
                execution_timeout=timedelta(minutes=5),
            )
            await asyncio.wait_for(stack.api.held.wait(), WITHIN_S)
            for _ in range(500):
                persisted = await frames.frames_for_execution(
                    identity.request_scope, identity.harness_execution_id, 1, limit=1000
                )
                if len(persisted) >= 4:
                    break
                await asyncio.sleep(0.1)
            else:
                pytest.fail("worker did not persist live frames before loss")
            await dying.shutdown()
            await asyncio.gather(running, return_exceptions=True)
            stack.api.release()
            successor = agents_harness(stack.api, stack.artifacts, stack.deletions)
            async with _activity_worker(
                client, lane_queue, lanes.boundary, service(successor, "hl12-b")
            ):
                result = await asyncio.wait_for(handle.result(), WITHIN_S)
            await _replayed(handle)
        assert result.disposition == "completed"
        assert parse_operation_result(result.result).status == "completed"
        assert len(stack.api.sessions_store) == len(stack.api.sends) == 1
        stored = await frames.frames_for_execution(
            identity.request_scope, identity.harness_execution_id, 1, limit=1000
        )
        assert len({frame.provider_key for frame in stored}) == len(stored)
        assert [frame.kind for frame in stored].count(FrameKind.RUN_RESULT) == 1
        state = await states.load(identity.request_scope, identity.harness_execution_id)
        assert state.native_session_ref == next(iter(stack.api.sessions_store))
        assert state.dispatch("send", f"{identity.harness_execution_id}:1:turn:1").attempts == 1
        assert len(stack.deletions.orders) == 1
    finally:
        await pool.close()
