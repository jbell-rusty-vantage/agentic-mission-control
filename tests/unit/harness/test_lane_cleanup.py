"""MO-05: `lane.cleanup` over a scripted Session Lane (SPEC-03 section 2).

The service removes a unit generation's leased worktree through its lane only after the unit
settled (its Artifacts registered and its liabilities settled); a lane that leases no
workspace has none to clean, and a lane's refusal keeps the worktree and names why.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mission_control.application.execution.harness.lane_turns import (
    UNIT_NOT_SETTLED,
    LaneExecutionIdentity,
)
from mission_control.application.execution.harness.protocol import WorkspaceLeasingLane
from mission_control.application.workspaces.errors import WORKSPACE_CUSTODY_STALE, WorkspaceError
from mission_control.domain.execution.lane_turns import (
    CleanupOutcome,
    LaneCleanupRequest,
    LaneCleanupResult,
    LaneTurnRequest,
)
from tests.fixtures.lane_turns import (
    LaneStack,
    RecordingSignals,
    ScriptedSessionLane,
    cursor_operation,
    lane_stack,
    scripted_frames,
)


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


def _cleanup() -> LaneCleanupRequest:
    return LaneCleanupRequest(
        operation=cursor_operation(), lane_profile="cursor_local", generation=1
    )


def _identity() -> LaneExecutionIdentity:
    return LaneExecutionIdentity.of(cursor_operation(), "cursor_local", 1)


async def _settle(stack: LaneStack) -> None:
    turn = LaneTurnRequest(operation=cursor_operation(), lane_profile="cursor_local", generation=1)
    signals = RecordingSignals(stack.frames, _identity().harness_execution_id)
    result = await stack.service.turn(turn, signals)
    assert result.done


async def test_a_lane_that_leases_no_workspace_has_none_to_clean() -> None:
    stack = lane_stack()
    assert not isinstance(stack.lane, WorkspaceLeasingLane)
    assert await stack.service.cleanup(_cleanup()) == LaneCleanupResult(outcome="not_required")


async def test_cleanup_waits_for_the_unit_settlement() -> None:
    lane = CleaningLane(frames=scripted_frames())
    stack = lane_stack(lane)
    early = await stack.service.cleanup(_cleanup())
    assert early == LaneCleanupResult(outcome="retained", reason_code=UNIT_NOT_SETTLED)
    assert lane.cleanups == []

    await _settle(stack)
    cleaned = await stack.service.cleanup(_cleanup())
    identity = _identity()
    assert cleaned == LaneCleanupResult(outcome="removed")
    assert lane.cleanups == [(identity.request_scope, str(identity.harness_execution_id), 1)]


async def test_a_refusal_keeps_the_worktree_and_names_why() -> None:
    lane = CleaningLane(
        frames=scripted_frames(),
        refusal=WorkspaceError(WORKSPACE_CUSTODY_STALE, "changed after custody"),
    )
    stack = lane_stack(lane)
    await _settle(stack)
    kept = await stack.service.cleanup(_cleanup())
    assert kept == LaneCleanupResult(outcome="retained", reason_code=WORKSPACE_CUSTODY_STALE)
