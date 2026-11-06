"""HL-18: the Remote Session Lane base orders a non-ZDR session's deletion after custody."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from mission_control.adapters.remote_session.retention import ProviderSessionRetention
from mission_control.application.execution.harness.lane_turns import LaneExecutionIdentity
from mission_control.application.execution.harness.retention import SessionRetentionService
from mission_control.domain.execution.lanes import LaneProfileName
from mission_control.domain.execution.session_retention import SessionRetentionPolicy
from tests.fixtures.lane_turns import cursor_operation
from tests.fixtures.session_retention import RecordingDeletionScheduler

CUSTODY = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


def _identity(profile: LaneProfileName) -> LaneExecutionIdentity:
    identity: LaneExecutionIdentity = LaneExecutionIdentity.of(cursor_operation(), profile, 1)
    return identity


@pytest.mark.parametrize("profile", ["claude_managed", "codex_agents"])
def test_a_non_zdr_lane_cannot_be_composed_without_session_retention(
    profile: LaneProfileName,
) -> None:
    with pytest.raises(ValueError, match="not ZDR-eligible"):
        ProviderSessionRetention(None, lane_profile=profile)


@pytest.mark.parametrize("profile", ["claude_managed", "codex_agents"])
async def test_the_session_is_ordered_deleted_under_the_identitys_scope(
    profile: LaneProfileName,
) -> None:
    scheduler = RecordingDeletionScheduler()
    retention = ProviderSessionRetention(
        SessionRetentionService(
            scheduler,
            policy=SessionRetentionPolicy(retention=timedelta(hours=2)),
            clock=lambda: CUSTODY,
        ),
        lane_profile=profile,
    )
    identity = _identity(profile)
    order = await retention.after_custody(identity, "session-1")
    assert order is not None
    assert (order.lane_profile, order.request_scope, order.session_ref) == (
        profile,
        identity.request_scope,
        "session-1",
    )
    assert order.delete_after == CUSTODY + timedelta(hours=2)
    assert list(scheduler.orders.values()) == [order]
    # A session that was never created orders nothing.
    assert await retention.after_custody(identity, None) is None
    assert len(scheduler.orders) == 1


async def test_cursor_cloud_archives_and_is_never_ordered_deleted() -> None:
    scheduler = RecordingDeletionScheduler()
    composed = ProviderSessionRetention(
        SessionRetentionService(scheduler), lane_profile="cursor_cloud"
    )
    bare = ProviderSessionRetention(None, lane_profile="cursor_cloud")
    identity = _identity("cursor_cloud")
    assert await composed.after_custody(identity, "bc-1") is None
    assert await bare.after_custody(identity, "bc-1") is None
    assert scheduler.orders == {}
