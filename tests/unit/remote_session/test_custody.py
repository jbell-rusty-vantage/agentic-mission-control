"""HL-04: provider workspace custody through the real `WorkspaceAllocator` (in-memory ledger)."""

from __future__ import annotations

from pathlib import Path
from typing import Final
from uuid import uuid4

import pytest

from mission_control.adapters.remote_session.custody import (
    ProviderWorkspaceCustody,
    parse_branch_snapshot,
)
from mission_control.application.execution.harness.lane_turns import LaneExecutionIdentity
from mission_control.application.execution.harness.protocol import NativeTurnLost
from mission_control.application.workspaces.snapshots import branch_snapshot_ref
from tests.fixtures.lane_turns import cursor_operation
from tests.unit.workspaces.workspace_fixtures import policy, stack

PROFILE: Final = "cursor_cloud"
REPOSITORY = "https://example.invalid/repo.git"


def _custody(tmp_path: Path) -> ProviderWorkspaceCustody:
    return ProviderWorkspaceCustody(
        stack(tmp_path).allocator,
        lane_profile=PROFILE,
        policy=policy(mode="provider_workspace", reuse="within_run"),
    )


async def _allocate(custody: ProviderWorkspaceCustody, generation: int = 1) -> object:
    operation = cursor_operation(PROFILE)
    return await custody.allocate(
        LaneExecutionIdentity.of(operation, PROFILE, generation),
        harness_execution_id=str(uuid4()),
        generation=generation,
        run_id=operation.identity.run_id,
        repository=REPOSITORY,
        base_ref="main",
        branch="mc/run-1",
        base_commit="1" * 40,
    )


def test_branch_snapshot_refs_round_trip() -> None:
    assert parse_branch_snapshot(branch_snapshot_ref("mc/run@1", "a" * 40)) == (
        "mc/run@1",
        "a" * 40,
    )
    assert parse_branch_snapshot("branch:mc/run") is None
    assert parse_branch_snapshot("branch:@abc") is None
    assert parse_branch_snapshot("lease:mc/run@abc") is None


async def test_without_an_allocator_nothing_is_recorded() -> None:
    custody = ProviderWorkspaceCustody(None, lane_profile=PROFILE, policy=policy())
    assert not custody.composed
    assert await _allocate(custody) is None
    assert await custody.record_head(None, "2" * 40) is None
    assert await custody.release(None, None) is None


async def test_the_branch_head_is_recorded_then_the_lease_released_after_custody(
    tmp_path: Path,
) -> None:
    custody = _custody(tmp_path)
    assert custody.composed
    lease = await _allocate(custody)
    assert lease is not None
    captured = await custody.record_head(lease, "2" * 40)  # type: ignore[arg-type]
    assert captured is not None
    assert parse_branch_snapshot(captured.snapshot_ref) == ("mc/run-1", "2" * 40)
    assert captured.snapshot.base_commit == "1" * 40
    released = await custody.release(lease, captured)  # type: ignore[arg-type]
    assert released is not None and released.cleanup_status == "not_required"


async def test_a_slot_held_by_another_generation_loses_the_turn(tmp_path: Path) -> None:
    custody = _custody(tmp_path)
    assert await _allocate(custody, generation=1) is not None
    with pytest.raises(NativeTurnLost, match="held elsewhere"):
        await _allocate(custody, generation=2)


async def test_a_refused_snapshot_loses_the_turn(tmp_path: Path) -> None:
    custody = _custody(tmp_path)
    lease = await _allocate(custody)
    released = await custody.release(lease, None)  # type: ignore[arg-type]
    with pytest.raises(NativeTurnLost, match="snapshot was refused"):
        await custody.record_head(released, "3" * 40)
