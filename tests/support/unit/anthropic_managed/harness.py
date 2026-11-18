"""Builders, constants and fakes that other test files import.

Moved from tests/unit/anthropic_managed/test_harness.py.
"""

from __future__ import annotations

from typing import Any

from mission_control.application.execution.harness.lane_turns import (
    LaneExecutionIdentity,
    harness_scope,
)
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.execution.contracts import OperationExecutionRequest
from mission_control.domain.execution.lanes import (
    PrepareRequest,
    SendTurnRequest,
    SessionHandle,
    StartRequest,
    TurnHandle,
)
from tests.support.providers.managed_agents import PROFILE, ManagedStack


def _identity(operation: OperationExecutionRequest) -> LaneExecutionIdentity:
    return LaneExecutionIdentity.of(operation, PROFILE, 1)


def _fields(operation: OperationExecutionRequest, key: str) -> dict[str, Any]:
    identity = _identity(operation)
    assert ProviderExecutionBinding.carried_by(operation) is not None
    return {
        "scope": harness_scope(identity.request_scope),
        "lane_profile": PROFILE,
        "harness_execution_id": str(identity.harness_execution_id),
        "binding_digest": ProviderExecutionBinding.carried_by(operation).binding_digest,
        "idempotency_key": f"{identity.harness_execution_id}:1:{key}",
        "generation": 1,
    }


async def _started(stack: ManagedStack) -> tuple[str, SessionHandle]:
    operation = stack.operation
    heid = str(_identity(operation).harness_execution_id)
    stack.harness.stage(heid, operation)
    prepared = await stack.harness.prepare(
        PrepareRequest(
            **_fields(operation, "turn:1"),
            run_id=operation.identity.run_id,
            operation_id=operation.identity.operation_id,
            attempt_no=1,
        )
    )
    session = await stack.harness.start(
        StartRequest(**_fields(operation, "turn:1"), prepared=prepared)
    )
    return heid, session


async def _sent(stack: ManagedStack, session: SessionHandle, turn_no: int = 1) -> TurnHandle:
    return await stack.harness.send_turn(
        SendTurnRequest(
            **_fields(stack.operation, f"turn:{turn_no}"),
            session=session,
            turn_no=turn_no,
            instruction_ref=f"operation:test:turn:{turn_no}",
        )
    )
