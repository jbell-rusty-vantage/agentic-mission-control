"""Builders, constants and fakes that other test files import.

Moved from tests/unit/harness/test_cursor_cloud.py.
"""

from __future__ import annotations

from typing import Any

from mission_control.application.execution.harness.lane_turns import LaneExecutionIdentity
from mission_control.domain.execution.lane_turns import LaneTurnRequest
from tests.support.lanes import lane_stack
from tests.support.providers.cursor import CloudStack


def _turn(stack: CloudStack, **changes: Any) -> LaneTurnRequest:
    return LaneTurnRequest.model_validate(
        {"operation": stack.operation, "lane_profile": "cursor_cloud", "generation": 1, **changes}
    )


def _identity(stack: CloudStack) -> LaneExecutionIdentity:
    return LaneExecutionIdentity.of(stack.operation, "cursor_cloud", 1)


def _lanes(stack: CloudStack) -> Any:
    return lane_stack(stack.harness, operation=stack.operation)
