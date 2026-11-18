"""Builders, constants and fakes that other test files import.

Moved from tests/unit/harness/test_lane_cleanup.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mission_control.application.workspaces.errors import WorkspaceError
from mission_control.domain.execution.lane_turns import CleanupOutcome
from tests.fixtures.lane_turns import ScriptedSessionLane


@dataclass
class CleaningLane(ScriptedSessionLane):
    """The scripted lane, leasing its workspaces: records each cleanup it is asked for."""

    refusal: WorkspaceError | None = None
    cleanups: list[tuple[str, str, int]] = field(default_factory=list)

    async def cleanup_workspace(
        self, *, request_scope: str, harness_execution_id: str, generation: int
    ) -> CleanupOutcome:
        self.cleanups.append((request_scope, harness_execution_id, generation))
        if self.refusal is not None:
            raise self.refusal
        return "removed"
