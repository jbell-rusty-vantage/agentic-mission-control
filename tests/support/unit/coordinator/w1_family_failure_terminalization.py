"""Builders, constants and fakes that other test files import.

Moved from tests/unit/coordinator/test_failed_run_terminalization.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from mission_control.domain.programs.family_failure import FamilyFailureTerminalizationRequest
from tests.support.journaled_goal_loop import SCOPE

NOW = datetime(2026, 10, 28, tzinfo=UTC)


def _request(run_id: str, *, epoch: int = 1, cause: str = "application_error:x") -> Any:
    return FamilyFailureTerminalizationRequest(
        request_scope=SCOPE,
        run_id=run_id,
        execution_epoch=epoch,
        family="GoalDirected",
        family_workflow_id=f"family/{run_id}/1",
        cause=cause,
        cause_digest="sha256:" + "1" * 64,
        occurred_at=NOW,
    )
