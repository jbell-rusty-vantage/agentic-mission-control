"""Hosted review uses the ERC actually recorded by the lane, with real restricted PG."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from mission_control.adapters.postgres.approvals.context import PostgresApprovalContextProbe
from mission_control.adapters.postgres.approvals.tasks import PostgresApprovalTaskRepository
from mission_control.adapters.postgres.frames.repository import PostgresFrameRepository
from mission_control.adapters.postgres.human_tasks.repository import PostgresHumanTaskRepository
from mission_control.adapters.postgres.lanes.execution_state import PostgresLaneExecutionStateStore
from mission_control.adapters.postgres.lanes.hook_tokens import PostgresHookIntentLedger
from mission_control.adapters.postgres.run_control.stop_fence import PostgresStopFenceRepository
from mission_control.adapters.temporal.provider_lane_composition import compose_approval_broker
from mission_control.application.execution.harness.lane_turns import (
    LaneExecutionIdentity,
    execution_start,
)
from mission_control.application.execution.hosted_tools import HostedCall, HostedToolGate
from mission_control.application.human_tasks.service import HumanTaskService
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.execution.contracts import (
    OperationAttemptIdentity,
    OperationExecutionRequest,
)
from mission_control.domain.policies.contracts import ActorContext
from tests.fixtures.agents_lane import agents_stack
from tests.fixtures.managed_lane import managed_stack
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.integration.postgres.frames_common import admit_unit_attempt
from tests.integration.postgres.runtime_common import common_db  # noqa: F401
from tests.unit.approvals.fixtures import answer


@pytest.mark.common_db
@pytest.mark.parametrize("profile", ["claude_managed", "codex_agents"])
async def test_hosted_review_revalidates_recorded_erc(
    common_db: CommonDatabase,  # noqa: F811
    tmp_path: Path,
    profile: str,
) -> None:
    pool = await common_db.pool("mission_control_runtime")
    try:
        admitted = await admit_unit_attempt(pool, common_db)
        stack = managed_stack(tmp_path) if profile == "claude_managed" else agents_stack(tmp_path)
        operation = OperationExecutionRequest.model_validate(
            {
                **stack.operation.model_dump(mode="python"),
                "request_scope": admitted.unit.request_scope,
                "runtime_unit": admitted.unit,
                "identity": OperationAttemptIdentity(
                    run_id=admitted.run_key,
                    operation_id=admitted.unit.semantic_operation_id,
                    operation_attempt=admitted.unit.semantic_attempt,
                ),
            }
        )
        identity = LaneExecutionIdentity.of(operation, profile, 1)
        await PostgresFrameRepository(pool).open_execution(
            execution_start(operation, identity, 1, "session-fixture")
        )
        await PostgresLaneExecutionStateStore(pool).claim_owner(
            identity.request_scope,
            identity.harness_execution_id,
            owner_ref="hosted-proof",
            generation=1,
            now=datetime.now(UTC),
            lease=timedelta(minutes=1),
        )
        current = await PostgresApprovalContextProbe(pool).current(
            identity.request_scope,
            run_id=identity.run_key,
            harness_execution_id=str(identity.harness_execution_id),
        )
        assert current.granted and current.policy_digest == operation.effective_configuration_digest
        assert (
            current.policy_digest != ProviderExecutionBinding.carried_by(operation).binding_digest
        )
        broker = compose_approval_broker(pool, connection_ref="hosted-proof")
        tasks = PostgresApprovalTaskRepository(pool)
        human = HumanTaskService(
            PostgresHumanTaskRepository(pool),
            request_scope=identity.request_scope,
            approvals=tasks,
            approval_wake=broker.hub,
        )
        gate = HostedToolGate(
            fences=PostgresStopFenceRepository(pool),
            intents=PostgresHookIntentLedger(pool),
            broker=broker,
            reviewers=("owner",),
            allowed_tools=frozenset({"bash"}),
            wait_seconds=5,
        )
        waiting = asyncio.create_task(
            gate.permission(
                operation,
                identity,
                HostedCall(
                    "session-fixture",
                    "turn-fixture",
                    "call-fixture",
                    "bash",
                    {"command": "echo bounded"},
                ),
                "shell",
            )
        )
        for _ in range(100):
            pending = await tasks.list_tasks(
                identity.request_scope, run_id=identity.run_key, lifecycle="open"
            )
            if pending:
                break
            await asyncio.sleep(0.01)
        assert len(pending) == 1
        await human.resolve(
            pending[0].human_task_id, answer(pending[0]), ActorContext(actor_id="owner")
        )
        assert await asyncio.wait_for(waiting, 6) == {"result": "allow"}
    finally:
        await pool.close()
