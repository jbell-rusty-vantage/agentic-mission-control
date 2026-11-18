"""Builders, constants and fakes that other test files import.

Moved from tests/unit/harness/test_dispatch_recovery.py.
"""

from __future__ import annotations

from typing import Any

from mission_control.domain.execution.contracts import OperationExecutionRequest
from mission_control.domain.execution.lane_turns import LaneTurnRequest
from mission_control.domain.execution.lanes import LaneSegmentBounds
from tests.support.lanes import cursor_operation

BOUNDS = LaneSegmentBounds(max_frames=50, heartbeat_timeout_s=3)


def turn_request(operation: OperationExecutionRequest | None = None, **changes: Any) -> Any:
    return LaneTurnRequest.model_validate(
        {
            "operation": operation or cursor_operation(),
            "lane_profile": "cursor_local",
            "generation": 1,
            "segment": BOUNDS,
            **changes,
        }
    )
