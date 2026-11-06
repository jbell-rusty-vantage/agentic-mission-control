"""`watchers.evaluate`: one Watcher Evaluator pass as a Temporal activity (SPEC-04 §5.3).

The activity resolves the tenant's evaluation service by request scope (forced RLS binds one
tenant per transaction), runs one pass at the workflow's clock and returns the new position.
It holds no state of its own: the journal is the authority, so a retry re-plans the same
facts and every action replays by its deterministic request id.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import cast

from temporalio import activity
from temporalio.exceptions import ApplicationError

from mission_control.adapters.temporal.workflows.watchers import (
    WATCHER_EVALUATE_ACTIVITY,
    HeldWatcherTrigger,
    WatcherFiringSummary,
    WatcherPassInput,
    WatcherPassResult,
)
from mission_control.application.watchers.ports import WatcherCursor
from mission_control.application.watchers.service import (
    WatcherEvaluationService,
    WatcherPassRequest,
)
from mission_control.domain.programs.watchers import (
    TRUST_RANK,
    HeldTrigger,
    Observation,
    TrustTier,
)

WatcherServices = Callable[[str], WatcherEvaluationService | None]


def _moment(value: str | None) -> datetime | None:
    if value is None:
        return None
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        raise ApplicationError("watcher timestamps are timezone-aware", non_retryable=True)
    return moment


def _held_in(item: HeldWatcherTrigger) -> HeldTrigger:
    at = _moment(item.at)
    if (
        item.source not in {"event", "signal"}
        or at is None
        or item.trust not in {None, *TRUST_RANK}
    ):
        raise ApplicationError("a held watcher trigger is malformed", non_retryable=True)
    return HeldTrigger(
        watcher_id=item.watcher_id,
        observation=Observation(
            source="event" if item.source == "event" else "signal",
            ref=item.ref,
            types=tuple(item.types),
            at=at,
            seq=item.seq,
            causation_ref=item.causation_ref,
            node_key=item.node_key,
            data=dict(item.data),
            trust=cast(TrustTier | None, item.trust),
        ),
    )


def _held_out(item: HeldTrigger) -> HeldWatcherTrigger:
    observation = item.observation
    return HeldWatcherTrigger(
        watcher_id=item.watcher_id,
        source=observation.source,
        ref=observation.ref,
        types=list(observation.types),
        at=observation.at.isoformat(),
        seq=observation.seq,
        causation_ref=observation.causation_ref,
        node_key=observation.node_key,
        data=dict(observation.data),
        trust=observation.trust,
    )


class WatcherActivities:
    def __init__(
        self,
        services: WatcherServices,
        *,
        sources: Callable[[str, str, datetime], Awaitable[None]] | None = None,
    ) -> None:
        self._services = services
        self._sources = sources

    @activity.defn(name=WATCHER_EVALUATE_ACTIVITY)
    async def evaluate(self, request: WatcherPassInput) -> WatcherPassResult:
        service = self._services(request.request_scope)
        if service is None:
            raise ApplicationError(
                f"no watcher evaluator is composed for {request.request_scope}",
                type="WatcherScopeUnavailable",
                non_retryable=True,
            )
        armed_at, now = _moment(request.armed_at), _moment(request.now)
        assert armed_at is not None and now is not None
        activity.heartbeat({"phase": "sources"})
        if self._sources is not None:
            await self._sources(request.request_scope, request.run_id, now)
        activity.heartbeat({"phase": "evaluate"})
        report = await service.run_pass(
            WatcherPassRequest(
                run_id=request.run_id,
                cursor=WatcherCursor(
                    event_seq=request.event_seq,
                    signal_at=_moment(request.signal_at),
                    signal_ref=request.signal_ref,
                ),
                armed_at=armed_at,
                now=now,
                retired=frozenset(request.retired),
                held=tuple(_held_in(item) for item in request.held),
            )
        )
        cursor = report.cursor
        return WatcherPassResult(
            event_seq=cursor.event_seq,
            signal_at=cursor.signal_at.isoformat() if cursor.signal_at is not None else None,
            signal_ref=cursor.signal_ref,
            retired=sorted(report.retired),
            next_deadline=(
                report.next_deadline.isoformat() if report.next_deadline is not None else None
            ),
            more=report.more,
            finished=report.finished,
            firings=[
                WatcherFiringSummary(
                    watcher_id=item.watcher_id,
                    trigger_key=item.trigger_key,
                    outcome=item.outcome,
                    recorded=item.recorded,
                )
                for item in report.firings
            ],
            suppressed=dict(report.counts),
            held=[_held_out(item) for item in report.held],
        )


__all__ = ["WatcherActivities", "WatcherServices"]
