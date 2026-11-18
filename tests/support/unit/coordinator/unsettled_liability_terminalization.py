"""Builders, constants and fakes that other test files import.

Moved from tests/unit/coordinator/test_unsettled_liability_terminalization.py.
"""

from __future__ import annotations

from typing import Any

from mission_control.application.execution.family_failure import FamilyFailureTerminalization
from mission_control.application.programs.service import orchestration_lifecycle_actor
from tests.support.journaled_goal_loop import SCOPE
from tests.support.unit.orchestration.goal_loop_operation_settlement import (
    _claim,
    _composition,
    _preparation,
)


async def _stuck_unit() -> tuple[Any, str, FamilyFailureTerminalization]:
    """A started run whose executor unit is admitted (reservation held) and never settles."""

    composition, run_id = await _composition()
    claim = await _claim(run_id)
    run = await composition.run_control.get_run(SCOPE, run_id)
    await composition.family.execute_iteration(
        _preparation(run_id, claim, "executor", run.version, 0)
    )
    service = FamilyFailureTerminalization(composition.run_control, orchestration_lifecycle_actor())
    return composition, run_id, service
