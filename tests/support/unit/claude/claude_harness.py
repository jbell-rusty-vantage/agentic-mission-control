"""Builders, constants and fakes that other test files import.

Moved from tests/unit/claude/test_claude_harness.py.
"""

from __future__ import annotations

from typing import Any

from mission_control.application.execution.harness.lane_turns import (
    LaneExecutionIdentity,
    harness_scope,
)
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.execution.lane_turns import LaneSegmentBounds, LaneTurnRequest
from tests.unit.claude.fixtures import PROFILE, ClaudeStack

SMALL = LaneSegmentBounds(
    max_frames=50,
    max_duration_s=20,
    start_to_close_s=40,
    heartbeat_timeout_s=3,
    status_poll_limit=2,
    status_poll_interval_s=1,
    busy_wait_s=10,
)


def _identity(stack: ClaudeStack) -> LaneExecutionIdentity:
    return LaneExecutionIdentity.of(stack.operation, PROFILE, 1)


def _turn(stack: ClaudeStack, **changes: Any) -> LaneTurnRequest:
    return LaneTurnRequest.model_validate(
        {
            "operation": stack.operation,
            "lane_profile": PROFILE,
            "generation": 1,
            "segment": SMALL,
            **changes,
        }
    )


def _frames(stack: ClaudeStack) -> list[Any]:
    execution = stack.frames._executions[_identity(stack).harness_execution_id]
    return sorted(execution.frames.values(), key=lambda frame: frame.arrival_ordinal)


def _fields(stack: ClaudeStack, key: str) -> dict[str, Any]:
    identity = _identity(stack)
    assert ProviderExecutionBinding.carried_by(stack.operation) is not None
    return {
        "scope": harness_scope(identity.request_scope),
        "lane_profile": PROFILE,
        "harness_execution_id": str(identity.harness_execution_id),
        "binding_digest": ProviderExecutionBinding.carried_by(stack.operation).binding_digest,
        "idempotency_key": f"{identity.harness_execution_id}:1:{key}",
        "generation": 1,
    }
