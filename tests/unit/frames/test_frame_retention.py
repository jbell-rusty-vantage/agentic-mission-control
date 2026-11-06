"""WP-TR-3 (stream R3): retention classes on the policy and the expiry contract (TR-D1, P8a).

`retain_days` governs the delta class, `step_retain_days` (nullable, at least 30) the step
class of terminal runs only, `prune_mode` is reserved; `frames.expire` reports both counts
additively over the pre-1.4.4 contract. The deletions themselves are proven on the common
database (`tests/integration/postgres/test_transcript_entries.py`, FX-TR-RETAIN).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from temporalio.testing import ActivityEnvironment

from mission_control.adapters.postgres.frames.retention import (
    MIN_STEP_RETAIN_DAYS,
    FrameExpiryReport,
    FrameRetentionPolicy,
    retention_cutoffs,
)
from mission_control.adapters.temporal.activities.frames_expire import (
    FramesExpireActivities,
    FramesExpireInput,
)

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)


def test_policy_defaults_keep_step_frames_for_the_evidence_life() -> None:
    policy = FrameRetentionPolicy()
    assert (policy.retain_days, policy.step_retain_days, policy.prune_mode) == (30, None, "delete")
    assert retention_cutoffs(policy, NOW) == (NOW - timedelta(days=30), None)
    stepped = FrameRetentionPolicy(retain_days=7, step_retain_days=45, prune_mode="tombstone")
    assert retention_cutoffs(stepped, NOW) == (NOW - timedelta(days=7), NOW - timedelta(days=45))


def test_policy_rejects_a_short_step_clock_a_zero_delta_clock_and_an_unknown_mode() -> None:
    with pytest.raises(ValueError, match=f"at least {MIN_STEP_RETAIN_DAYS}"):
        FrameRetentionPolicy(step_retain_days=MIN_STEP_RETAIN_DAYS - 1)
    with pytest.raises(ValueError, match="retain_days"):
        FrameRetentionPolicy(retain_days=0)
    with pytest.raises(ValueError, match="prune_mode"):
        FrameRetentionPolicy(prune_mode="shred")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="timezone-aware"):
        retention_cutoffs(FrameRetentionPolicy(), NOW.replace(tzinfo=None))


class _Retention:
    def __init__(self, report: object) -> None:
        self.report = report
        self.calls: list[tuple[str, datetime]] = []

    async def expire(self, request_scope: str, *, now: datetime) -> object:
        self.calls.append((request_scope, now))
        return self.report


@pytest.mark.asyncio
async def test_expire_activity_reports_both_retention_classes_per_scope() -> None:
    policy = FrameRetentionPolicy(retain_days=30, step_retain_days=60)
    retention = _Retention(
        FrameExpiryReport(
            request_scope="mc/i/biotech/t",
            cutoff=NOW - timedelta(days=30),
            deleted_non_closing=3,
            deleted_closing=0,
            policy=policy,
            expired_delta=3,
            expired_step=2,
            step_cutoff=NOW - timedelta(days=60),
        )
    )
    result = await ActivityEnvironment().run(
        FramesExpireActivities(retention).expire,  # type: ignore[arg-type]
        FramesExpireInput(request_scopes=["mc/i/biotech/t"], now=NOW.isoformat()),
    )
    (scope,) = result.scopes
    assert (scope.expired_delta, scope.expired_step) == (3, 2)
    assert (scope.deleted_non_closing, scope.deleted_closing) == (3, 0)
    assert (scope.retain_days, scope.step_retain_days, scope.prune_mode) == (30, 60, "delete")
    assert retention.calls == [("mc/i/biotech/t", NOW)]


@dataclass(frozen=True)
class _LegacyPolicy:
    retain_days: int = 30
    keep_closing_frames: bool = True


@dataclass(frozen=True)
class _LegacyReport:
    deleted_non_closing: int
    deleted_closing: int
    policy: _LegacyPolicy


@pytest.mark.asyncio
async def test_expire_activity_keeps_the_pre_144_report_shape_additively() -> None:
    result = await ActivityEnvironment().run(
        FramesExpireActivities(_Retention(_LegacyReport(4, 1, _LegacyPolicy()))).expire,  # type: ignore[arg-type]
        FramesExpireInput(request_scopes=["mc/i/biotech/t"]),
    )
    (scope,) = result.scopes
    assert (scope.expired_delta, scope.expired_step) == (5, 0)
    assert (scope.step_retain_days, scope.prune_mode) == (None, "delete")
