"""Builders, constants and fakes that other test files import.

Moved from tests/unit/orchestration/test_goal_failure_paths.py.
"""

from __future__ import annotations

from typing import Any

from mission_control.domain.programs.goal_directed_runtime import GoalOperationDispatch
from tests.support.journaled_goal_loop import SCOPE
from tests.support.unit.orchestration.goal_loop_operation_settlement import (
    _claim,
    _composition,
    _preparation,
)


async def _executor_dispatch() -> tuple[Any, str, Any, GoalOperationDispatch]:
    composition, run_id = await _composition()
    claim = await _claim(run_id)
    run = await composition.run_control.get_run(SCOPE, run_id)
    dispatch = await composition.family.execute_iteration(
        _preparation(run_id, claim, "executor", run.version, 0)
    )
    return composition, run_id, claim, dispatch
