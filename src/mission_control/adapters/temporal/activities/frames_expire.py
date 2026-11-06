"""`frames.expire`: Native Event Store retention as a Temporal activity (SPEC-03).

The activity applies each application's `frame_retention_policy` to the listed tenant
scopes (forced RLS binds one tenant per transaction). It is started by
`mc.frames_expire.v1` (workflows/frames_expire.py) on a Temporal Schedule per
application; `ensure_frames_expire_schedule` creates or updates that schedule.

Retention classes (TRACING-PROPOSAL §P8a, TR-D1): the result reports, per scope, the
delta-class frames expired by `retain_days` (`expired_delta`) and the step-class frames of
terminal runs expired by `step_retain_days` (`expired_step`, 0 while the policy leaves the
step clock unset). The pre-1.4.4 counts (`deleted_non_closing`, `deleted_closing`) stay.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol

from temporalio import activity
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleAlreadyRunningError,
    ScheduleIntervalSpec,
    ScheduleSpec,
    ScheduleUpdate,
    ScheduleUpdateInput,
)

FRAMES_EXPIRE_ACTIVITY = "frames.expire"
FRAMES_EXPIRE_WORKFLOW = "mc.frames_expire.v1"


@dataclass(frozen=True)
class FramesExpireInput:
    request_scopes: list[str]
    now: str | None = None  # ISO-8601 aware timestamp; activity clock when absent


@dataclass(frozen=True)
class FramesExpireScopeResult:
    request_scope: str
    deleted_non_closing: int
    deleted_closing: int
    retain_days: int
    keep_closing_frames: bool
    expired_delta: int = 0
    expired_step: int = 0
    step_retain_days: int | None = None
    prune_mode: str = "delete"
    # OVE-204 slice 5: Workspace Closure rows past `retain_until` (completed runs only).
    expired_closures: int = 0


@dataclass(frozen=True)
class FramesExpireResult:
    scopes: list[FramesExpireScopeResult] = field(default_factory=list)


class _ExpiryReport(Protocol):
    @property
    def deleted_non_closing(self) -> int: ...

    @property
    def deleted_closing(self) -> int: ...

    @property
    def expired_delta(self) -> int: ...

    @property
    def expired_step(self) -> int: ...


class FrameExpiryPort(Protocol):
    async def expire(self, request_scope: str, *, now: datetime) -> _ExpiryReport: ...


class FramesExpireActivities:
    def __init__(self, retention: FrameExpiryPort) -> None:
        self._retention = retention

    @activity.defn(name=FRAMES_EXPIRE_ACTIVITY)
    async def expire(self, request: FramesExpireInput) -> FramesExpireResult:
        now = datetime.fromisoformat(request.now) if request.now else datetime.now(UTC)
        if now.tzinfo is None:
            raise ValueError("frames.expire requires an aware timestamp")
        results: list[FramesExpireScopeResult] = []
        for scope in request.request_scopes:
            report = await self._retention.expire(scope, now=now)
            policy = getattr(report, "policy", None)
            step_retain_days = getattr(policy, "step_retain_days", None)
            results.append(
                FramesExpireScopeResult(
                    request_scope=scope,
                    deleted_non_closing=report.deleted_non_closing,
                    deleted_closing=report.deleted_closing,
                    retain_days=int(getattr(policy, "retain_days", 30)),
                    keep_closing_frames=bool(getattr(policy, "keep_closing_frames", True)),
                    # Reports older than 1.4.4 (and test doubles) carry the delta count under
                    # `deleted_non_closing`; the step count is 0 unless reported.
                    expired_delta=int(
                        getattr(
                            report,
                            "expired_delta",
                            report.deleted_non_closing + report.deleted_closing,
                        )
                    ),
                    expired_step=int(getattr(report, "expired_step", 0)),
                    step_retain_days=(
                        int(step_retain_days) if step_retain_days is not None else None
                    ),
                    prune_mode=str(getattr(policy, "prune_mode", "delete")),
                    expired_closures=int(getattr(report, "expired_closures", 0)),
                )
            )
            activity.heartbeat(scope)
        return FramesExpireResult(scopes=results)


async def ensure_frames_expire_schedule(
    client: Client,
    *,
    application_id: str,
    request_scopes: list[str],
    task_queue: str,
    every: timedelta = timedelta(days=1),
) -> str:
    """Create, or update in place, the per-application retention schedule."""

    schedule_id = f"mc-frames-expire:{application_id}"
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            FRAMES_EXPIRE_WORKFLOW,
            FramesExpireInput(request_scopes=list(request_scopes)),
            id=f"{schedule_id}:run",
            task_queue=task_queue,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=every)]),
    )
    try:
        await client.create_schedule(schedule_id, schedule)
    except ScheduleAlreadyRunningError:

        def _update(_input: ScheduleUpdateInput) -> ScheduleUpdate:
            return ScheduleUpdate(schedule=schedule)

        await client.get_schedule_handle(schedule_id).update(_update)
    return schedule_id
