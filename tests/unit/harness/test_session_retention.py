"""HL-18: hosted sessions are ordered deleted after custody plus the retention interval, and a
due order deletes through the profile's provider deleter (SPEC-06 section 8)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from mission_control.application.execution.harness.retention import (
    SessionDeleterUnavailable,
    SessionDeletionService,
    SessionRetentionService,
)
from mission_control.domain.execution.lanes import LANE_PROFILES
from mission_control.domain.execution.session_retention import (
    DEFAULT_SESSION_RETENTION,
    SESSION_DELETED_PROFILES,
    SessionDeletion,
    SessionRetentionPolicy,
)
from tests.fixtures.session_retention import FakeSessionDeleter, RecordingDeletionScheduler

SCOPE = "mc/00000000-0000-0000-0000-000000000001/ai-engineer/00000000-0000-0000-0000-000000000002"
CUSTODY = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


def test_only_the_non_zdr_hosted_agent_apis_are_ordered_deleted() -> None:
    assert {"claude_managed", "codex_agents"} == SESSION_DELETED_PROFILES
    policy = SessionRetentionPolicy()
    for profile in LANE_PROFILES:
        order = policy.deletion(
            lane_profile=profile, request_scope=SCOPE, session_ref="s-1", custody_at=CUSTODY
        )
        assert (order is not None) is (profile in SESSION_DELETED_PROFILES)


def test_a_deletion_is_due_after_custody_plus_the_retention_interval() -> None:
    order = SessionRetentionPolicy(retention=timedelta(hours=6)).deletion(
        lane_profile="claude_managed", request_scope=SCOPE, session_ref="s-1", custody_at=CUSTODY
    )
    assert order is not None
    assert order.custody_at == CUSTODY
    assert order.delete_after == CUSTODY + timedelta(hours=6)
    assert order.key == f"{SCOPE}:claude_managed:s-1"
    assert SessionRetentionPolicy().retention == DEFAULT_SESSION_RETENTION == timedelta(days=7)


def test_a_retention_interval_cannot_be_negative() -> None:
    with pytest.raises(ValidationError, match="cannot be negative"):
        SessionRetentionPolicy(retention=timedelta(seconds=-1))


async def test_the_retention_service_schedules_one_order_per_session_at_custody() -> None:
    scheduler = RecordingDeletionScheduler()
    service = SessionRetentionService(
        scheduler,
        policy=SessionRetentionPolicy(retention=timedelta(days=1)),
        clock=lambda: CUSTODY,
    )
    order = await service.after_custody(
        lane_profile="codex_agents", request_scope=SCOPE, session_ref="sess_1"
    )
    again = await service.after_custody(
        lane_profile="codex_agents", request_scope=SCOPE, session_ref="sess_1"
    )
    assert order == again and order is not None
    assert list(scheduler.orders.values()) == [order]
    assert order.delete_after == CUSTODY + timedelta(days=1)
    assert (
        await service.after_custody(
            lane_profile="cursor_cloud", request_scope=SCOPE, session_ref="bc-1"
        )
        is None
    )
    assert len(scheduler.orders) == 1


def _order(profile: str, session_ref: str) -> SessionDeletion:
    return SessionDeletion.model_validate(
        {
            "lane_profile": profile,
            "request_scope": SCOPE,
            "session_ref": session_ref,
            "custody_at": CUSTODY,
            "delete_after": CUSTODY,
        }
    )


async def test_a_due_order_deletes_through_its_profiles_deleter() -> None:
    managed = FakeSessionDeleter({"sesn_1"})
    agents = FakeSessionDeleter({"sess_1"})
    service = SessionDeletionService({"claude_managed": managed, "codex_agents": agents})
    assert await service.delete(_order("claude_managed", "sesn_1")) == "deleted"
    assert await service.delete(_order("claude_managed", "sesn_1")) == "absent"
    assert managed.calls == ["sesn_1", "sesn_1"] and agents.calls == []
    assert managed.live == set() and agents.live == {"sess_1"}


async def test_an_order_without_a_composed_deleter_fails_to_be_retried() -> None:
    service = SessionDeletionService({"claude_managed": FakeSessionDeleter()})
    with pytest.raises(SessionDeleterUnavailable, match="codex_agents"):
        await service.delete(_order("codex_agents", "sess_1"))


def test_a_deleter_is_composed_only_for_a_deleted_profile() -> None:
    with pytest.raises(ValueError, match="cursor_cloud"):
        SessionDeletionService({"cursor_cloud": FakeSessionDeleter()})
