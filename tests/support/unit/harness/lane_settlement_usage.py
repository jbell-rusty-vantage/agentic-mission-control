"""Builders, constants and fakes that other test files import.

Moved from tests/unit/harness/test_lane_settlement_usage.py.
"""

from __future__ import annotations

from mission_control.domain.execution.contracts import OperationExecutionRequest
from tests.support.lanes import cursor_operation

STAGE_RESERVATION = {"operation.attempts": 1, "concurrency.slots": 1}


def _stage_operation() -> OperationExecutionRequest:
    """A Stage Graph stage unit: its limits are its reservation (no token dimension)."""

    return cursor_operation().model_copy(update={"budget_limits": dict(STAGE_RESERVATION)})
