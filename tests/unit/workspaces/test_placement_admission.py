"""Five members admit at most three, with explicit timer signals instead of polling."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from mission_control.application.execution.harness.dispatch import ProviderCapacityLimited
from mission_control.application.workspaces.placement import (
    InMemoryPlacementStore,
    PlacementAdmission,
)
from mission_control.domain.execution.placement import (
    PlacementCandidate,
    PlacementLimit,
    choose_placement,
)


async def test_five_members_are_throttled_at_three_and_retry_after_release() -> None:
    store = InMemoryPlacementStore()
    gate = PlacementAdmission(store, {"cursor_cloud": PlacementLimit(max_active=3)})
    ids = [uuid4() for _ in range(5)]
    now = datetime.now(UTC)
    results = await asyncio.gather(
        *(gate.reserve("scope", execution, "cursor_cloud", now) for execution in ids),
        return_exceptions=True,
    )
    assert sum(result is None for result in results) == 3
    blocked = [result for result in results if isinstance(result, ProviderCapacityLimited)]
    assert len(blocked) == 2
    assert all(result.signal.resets_at == now + timedelta(seconds=30) for result in blocked)
    await gate.release("scope", ids[0])
    await gate.reserve("scope", ids[3], "cursor_cloud", now)
    # A restarted/retried owner retains its reservation, without counting twice.
    await PlacementAdmission(store, {"cursor_cloud": PlacementLimit(max_active=3)}).reserve(
        "scope", ids[3], "cursor_cloud", now
    )


async def test_launch_rate_waits_remain_after_capacity_is_released() -> None:
    store = InMemoryPlacementStore()
    gate = PlacementAdmission(
        store, {"cursor_cloud": PlacementLimit(max_active=3, launches_per_minute=1)}
    )
    now = datetime.now(UTC)
    first, second = uuid4(), uuid4()
    await gate.reserve("scope", first, "cursor_cloud", now)
    await gate.release("scope", first)
    with pytest.raises(ProviderCapacityLimited):
        await gate.reserve("scope", second, "cursor_cloud", now)
    await gate.reserve("scope", second, "cursor_cloud", now + timedelta(minutes=1, seconds=1))


def test_preference_selects_only_explicit_qualified_eligible_candidates() -> None:
    candidates = tuple(
        PlacementCandidate(
            profile=profile, qualified=qualified, prerequisites_met=True, capacity_available=True
        )
        for profile, qualified in [
            ("codex", True),
            ("claude_managed", False),
            ("cursor_cloud", True),
        ]
    )
    assert choose_placement(candidates) == "cursor_cloud"
    assert choose_placement(candidates, "local_only") == "codex"
    assert choose_placement(candidates, "cloud_only") == "cursor_cloud"
    with pytest.raises(ValueError, match="no qualified placement"):
        choose_placement((candidates[1],))
