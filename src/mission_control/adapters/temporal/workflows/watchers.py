"""`mc.watchers.v1`: the Watcher Evaluator's durable loop for one run (SPEC-04 §5.3, ADR-0046).

Temporal is the only scheduler of watcher work. The workflow holds the evaluation position
(journal sequence, signal position, retired watchers, held ``satisfy_wait`` triggers) and the
arming time, and runs one short ``watchers.evaluate`` activity per pass. Between passes it
waits durably on a timer: the earliest ``absence``/``schedule`` deadline the pass reported, or
the poll interval; the journal is the authority, so nothing is pushed to the workflow.

Every firing, action and dedupe key is decided inside the activity from the journal, so a
replayed history issues nothing; a retried activity re-plans the same journal and its
commands replay by request id. The loop ends after the pass that sees the run terminal with
its journal fully read (watchers die with the run; notify on the terminal event has fired by
then) and continues as new after ``passes_per_history`` passes.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

WATCHERS_WORKFLOW = "mc.watchers.v1"
WATCHER_EVALUATE_ACTIVITY = "watchers.evaluate"
# A pass always waits at least this long for its next one (a deadline already passed while the
# activity ran is due on the next pass), so a planner fault can never spin the loop.
MIN_WAIT = timedelta(seconds=1)


@dataclass(frozen=True)
class HeldWatcherTrigger:
    """A matched fact held for a ``satisfy_wait`` firing until the run declares its wait."""

    watcher_id: str
    source: str
    ref: str
    types: list[str]
    at: str
    seq: int | None = None
    causation_ref: str | None = None
    node_key: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    trust: str | None = None


@dataclass(frozen=True)
class WatchersWorkflowInput:
    request_scope: str
    run_id: str
    armed_at: str | None = None  # ISO-8601; the first run arms at workflow time
    event_seq: int = 0
    signal_at: str | None = None
    signal_ref: str | None = None
    retired: list[str] = field(default_factory=list)
    held: list[HeldWatcherTrigger] = field(default_factory=list)
    poll_seconds: int = 30
    passes_per_history: int = 500
    activity_timeout_seconds: int = 120
    fired: int = 0
    failed: int = 0


@dataclass(frozen=True)
class WatcherPassInput:
    request_scope: str
    run_id: str
    armed_at: str
    now: str
    event_seq: int = 0
    signal_at: str | None = None
    signal_ref: str | None = None
    retired: list[str] = field(default_factory=list)
    held: list[HeldWatcherTrigger] = field(default_factory=list)


@dataclass(frozen=True)
class WatcherFiringSummary:
    watcher_id: str
    trigger_key: str
    outcome: str
    recorded: bool


@dataclass(frozen=True)
class WatcherPassResult:
    event_seq: int
    signal_at: str | None
    signal_ref: str | None
    retired: list[str]
    next_deadline: str | None
    more: bool
    finished: bool
    firings: list[WatcherFiringSummary] = field(default_factory=list)
    suppressed: dict[str, int] = field(default_factory=dict)
    held: list[HeldWatcherTrigger] = field(default_factory=list)


@dataclass(frozen=True)
class WatchersWorkflowResult:
    run_id: str
    passes: int
    fired: int
    failed: int
    event_seq: int


@workflow.defn(name=WATCHERS_WORKFLOW)
class WatchersWorkflow:
    def __init__(self) -> None:
        self._passes = 0
        self._last: WatcherPassResult | None = None

    @workflow.query
    def state(self) -> dict[str, Any]:
        last = self._last
        return {
            "passes": self._passes,
            "event_seq": last.event_seq if last is not None else None,
            "next_deadline": last.next_deadline if last is not None else None,
            "suppressed": dict(last.suppressed) if last is not None else {},
        }

    @workflow.run
    async def run(self, request: WatchersWorkflowInput) -> WatchersWorkflowResult:
        armed_at = request.armed_at or workflow.now().isoformat()
        state = replace(request, armed_at=armed_at)
        timeout = timedelta(seconds=request.activity_timeout_seconds)
        retry = RetryPolicy(maximum_interval=timedelta(minutes=1))
        while True:
            if self._passes == request.passes_per_history:
                workflow.continue_as_new(state)
            result = await workflow.execute_activity(
                WATCHER_EVALUATE_ACTIVITY,
                WatcherPassInput(
                    request_scope=state.request_scope,
                    run_id=state.run_id,
                    armed_at=armed_at,
                    now=workflow.now().isoformat(),
                    event_seq=state.event_seq,
                    signal_at=state.signal_at,
                    signal_ref=state.signal_ref,
                    retired=list(state.retired),
                    held=list(state.held),
                ),
                result_type=WatcherPassResult,
                start_to_close_timeout=timeout,
                heartbeat_timeout=timedelta(seconds=30),
                retry_policy=retry,
            )
            self._passes += 1
            self._last = result
            state = replace(
                state,
                event_seq=result.event_seq,
                signal_at=result.signal_at,
                signal_ref=result.signal_ref,
                retired=list(result.retired),
                held=list(result.held),
                fired=state.fired + sum(item.outcome == "fired" for item in result.firings),
                failed=state.failed + sum(item.outcome == "failed" for item in result.firings),
            )
            if result.finished:
                return WatchersWorkflowResult(
                    run_id=state.run_id,
                    passes=self._passes,
                    fired=state.fired,
                    failed=state.failed,
                    event_seq=state.event_seq,
                )
            if result.more:
                continue
            wait = timedelta(seconds=request.poll_seconds)
            if result.next_deadline is not None:
                wait = min(wait, datetime.fromisoformat(result.next_deadline) - workflow.now())
            await workflow.sleep(max(wait, MIN_WAIT))


__all__ = [
    "MIN_WAIT",
    "WATCHERS_WORKFLOW",
    "WATCHER_EVALUATE_ACTIVITY",
    "HeldWatcherTrigger",
    "WatcherFiringSummary",
    "WatcherPassInput",
    "WatcherPassResult",
    "WatchersWorkflow",
    "WatchersWorkflowInput",
    "WatchersWorkflowResult",
]
