"""Builders, constants and fakes that other test files import.

Moved from tests/unit/codex/test_harness.py.
"""

from __future__ import annotations

from mission_control.domain.execution.lanes import LaneSegmentBounds

BOUNDS = LaneSegmentBounds(max_duration_s=20, start_to_close_s=60, heartbeat_timeout_s=3)
