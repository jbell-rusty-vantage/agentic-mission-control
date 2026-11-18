"""Builders, constants and fakes that other test files import.

Moved from tests/unit/operations/test_checkpoint_recovery_classification.py.
"""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import CheckpointTuple

from mission_control.domain.execution.contracts import (
    DeepAgentExecutionBinding,
    OperationExecutionRequest,
)
from tests.fixtures.checkpoint_recovery import RecoveryHarness


def _root(namespace: str, checkpoint_id: str | None = None) -> RunnableConfig:
    configurable: dict[str, Any] = {"thread_id": namespace, "checkpoint_ns": ""}
    if checkpoint_id is not None:
        configurable["checkpoint_id"] = checkpoint_id
    return {"configurable": configurable}


async def _root_checkpoints(harness: RecoveryHarness, namespace: str) -> list[CheckpointTuple]:
    return [item async for item in harness.saver.alist(_root(namespace))]


async def _chain(harness: RecoveryHarness, namespace: str, leaf_id: str) -> list[CheckpointTuple]:
    """Root checkpoints from `leaf_id` back to the first, following parent links."""

    chain: list[CheckpointTuple] = []
    cursor = await harness.saver.aget_tuple(_root(namespace, leaf_id))
    while cursor is not None:
        chain.append(cursor)
        parent = cursor.parent_config
        cursor = (
            await harness.saver.aget_tuple(
                _root(namespace, parent["configurable"]["checkpoint_id"])
            )
            if parent is not None
            else None
        )
    return chain


async def _leaf_id(harness: RecoveryHarness, namespace: str) -> str:
    latest = await harness.saver.aget_tuple(_root(namespace))
    assert latest is not None
    return str(latest.config["configurable"]["checkpoint_id"])


def _namespace(request: OperationExecutionRequest) -> str:
    assert DeepAgentExecutionBinding.carried_by(request) is not None
    namespace = DeepAgentExecutionBinding.carried_by(request).cognitive_session_namespace
    assert namespace is not None
    return namespace


AFTER_TOOL_CHECKPOINT = 6


async def _write_foreign_root_checkpoint(harness: RecoveryHarness, namespace: str) -> None:
    """A stray root checkpoint no BellLabs invocation stamped (e.g. an out-of-band write)."""

    from langgraph.checkpoint.base import empty_checkpoint

    await harness.saver.aput(_root(namespace), empty_checkpoint(), {"source": "input"}, {})
