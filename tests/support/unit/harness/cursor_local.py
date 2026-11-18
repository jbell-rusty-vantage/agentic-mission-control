"""Builders, constants and fakes that other test files import.

Moved from tests/unit/harness/test_cursor_local.py.
"""

from __future__ import annotations

from typing import Any

from mission_control.application.execution.harness.lane_turns import LaneExecutionIdentity
from mission_control.domain.execution.lane_turns import LaneTurnRequest
from tests.fixtures.cursor_local import LocalStack
from tests.fixtures.lane_turns import lane_stack


def _identity(stack: LocalStack) -> LaneExecutionIdentity:
    return LaneExecutionIdentity.of(stack.operation, "cursor_local", 1)


def _turn(stack: LocalStack, **changes: Any) -> LaneTurnRequest:
    return LaneTurnRequest.model_validate(
        {
            "operation": stack.operation,
            "lane_profile": "cursor_local",
            "generation": 1,
            **changes,
        }
    )


def _service(stack: LocalStack) -> Any:
    return lane_stack(stack.harness, frames=stack.frames, operation=stack.operation)
