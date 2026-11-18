"""Builders, constants and fakes that other test files import.

Moved from tests/integration/deep_agents/test_checkpoint_lineage_postgres_saver.py.
"""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from mission_control.domain.execution.checkpoint_lineage import OperationActivityAttempt
from mission_control.domain.execution.contracts import (
    OperationExecutionRequest,
)
from mission_control.domain.graph_runtime.identities import RuntimeUnitIdentity

SAVER_SCHEMA = "mission_control_runtime"


class AcceptingAuthority:
    async def verify(self, request: OperationExecutionRequest) -> None:
        del request

    async def verify_continuation(self, request: OperationExecutionRequest, binding: Any) -> None:
        del request, binding

    async def verify_cancellation(self, request: OperationExecutionRequest, binding: Any) -> None:
        del request, binding


def delivery(attempt: int, unit: RuntimeUnitIdentity) -> OperationActivityAttempt:
    return OperationActivityAttempt(
        workflow_id=f"operation/{unit.semantic_operation_id}",
        workflow_run_id="temporal-run-1",
        activity_id="1",
        attempt=attempt,
        worker_identity="worker:rrm-003",
    )


def root(namespace: str, checkpoint_id: str | None = None) -> RunnableConfig:
    configurable: dict[str, Any] = {"thread_id": namespace, "checkpoint_ns": ""}
    if checkpoint_id is not None:
        configurable["checkpoint_id"] = checkpoint_id
    return {"configurable": configurable}


async def root_lineage(saver: AsyncPostgresSaver, namespace: str) -> list[Any]:
    """Root checkpoints from the latest back to the first, following parent links."""

    chain = []
    cursor = await saver.aget_tuple(root(namespace))
    while cursor is not None:
        chain.append(cursor)
        parent = cursor.parent_config
        cursor = (
            await saver.aget_tuple(root(namespace, parent["configurable"]["checkpoint_id"]))
            if parent is not None
            else None
        )
    return chain
