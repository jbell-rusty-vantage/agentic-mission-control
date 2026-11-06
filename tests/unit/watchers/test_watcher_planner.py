"""MO-44: the pure Watcher Evaluator planner fires deterministically and enforces every
boundary (SPEC-04 §5.2-5.3)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

import pytest

from mission_control.domain.programs.watchers import (
    FiringRecord,
    Observation,
    WatcherDescriptor,
    WatcherPlan,
    WatcherPlanInput,
    WatcherSpec,
    action_request_id,
    compile_watcher,
    firing_event_id,
    parse_rate,
    plan_watchers,
    wait_condition_id,
)
from tests.unit.watchers.fakes import RUN_ID, T0, at


def watcher(watcher_id: str, body: dict[str, Any]) -> WatcherDescriptor:
    return compile_watcher(
        WatcherSpec.model_validate(body),
        watcher_id=watcher_id,
        origin="manifest",
        pointer=f"/mission/controls/watchers/{watcher_id}",
    )


def event(
    event_type: str,
    data: dict[str, Any] | None = None,
    *,
    when: datetime,
    seq: int,
    causation_ref: str | None = None,
    alias: str | None = None,
) -> Observation:
    return Observation(
        source="event",
        ref=f"event-{seq}",
        types=(event_type, alias) if alias else (event_type,),
        at=when,
        seq=seq,
        causation_ref=causation_ref,
        data=data or {},
    )


def signal(
    signal_type: str, data: dict[str, Any], *, when: datetime, ref: str, trust: Any = "run_token"
) -> Observation:
    return Observation(
        source="signal", ref=ref, types=(signal_type,), at=when, data=data, trust=trust
    )


def plan(
    descriptors: Sequence[WatcherDescriptor],
    observations: Sequence[Observation] = (),
    *,
    now: datetime | None = None,
    history: Sequence[FiringRecord] = (),
    **kwargs: Any,
) -> WatcherPlan:
    return plan_watchers(
        WatcherPlanInput(
            run_id=RUN_ID,
            descriptors=tuple(descriptors),
            observations=tuple(observations),
            history=tuple(history),
            armed_at=T0,
            now=now or at(3600),
            run=kwargs.pop("run", {"phase": "active", "branch_prefix": "mc/run-1/"}),
            **kwargs,
        )
    )


CI_RED_FIX = watcher(
    "ci-red-fix",
    {
        "on": {
            "signal": "github.check_suite.completed",
            "where": "event.conclusion == 'failure' and "
            "startswith(event.head_branch, run.branch_prefix)",
        },
        "then": [{"instruct": {"text": "CI is red; fix it.", "include": ["event.summary"]}}],
        "limits": {"max_fires": 3, "min_interval": "10m"},
    },
)
STALLED = watcher(
    "stalled",
    {
        "on": {
            "absence": {"of": ["frame", "signal"], "for": "20m"},
            "while": "run.phase == 'active'",
        },
        "then": [
            {"notify": {"kind": "blocked", "text": "No progress for 20 minutes"}},
            {"probe": {}},
        ],
        "limits": {"max_fires": 2},
    },
)


def red(index: int, minute: float, branch: str = "mc/run-1/fix") -> Observation:
    return signal(
        "github.check_suite.completed",
        {"conclusion": "failure", "head_branch": branch, "summary": f"run {index} failed"},
        when=at(minute * 60),
        ref=f"frame-{index}",
    )


def test_condition_filters_and_firings_are_keyed_deterministically() -> None:
    observations = [
        red(1, 1),
        red(2, 2, branch="main"),  # another branch: filtered by `where`
        signal("github.check_suite.completed", {"conclusion": "success"}, when=at(180), ref="f3"),
    ]
    first = plan([CI_RED_FIX], observations)
    again = plan([CI_RED_FIX], observations)
    assert first == again
    (firing,) = first.firings
    assert firing.trigger_key == "signal:frame-1" and firing.depth == 1
    assert firing.trigger.type == "github.check_suite.completed"
    assert firing.included == {"event.summary": "run 1 failed"}
    (action,) = firing.actions
    assert action.request_id == action_request_id(RUN_ID, "ci-red-fix", "signal:frame-1", 0)
    assert (
        firing_event_id(RUN_ID, "ci-red-fix", firing.trigger_key, failed=False)
        == f"watcher.fired:{RUN_ID}:ci-red-fix:signal:frame-1"
    )


def test_max_fires_min_interval_and_history_dedupe() -> None:
    observations = [red(index, minute) for index, minute in enumerate((1, 5, 12, 25, 40), 1)]
    result = plan([CI_RED_FIX], observations)
    assert [item.trigger_key for item in result.firings] == [
        "signal:frame-1",
        "signal:frame-3",
        "signal:frame-4",
    ]
    assert [(item.trigger_key, item.reason) for item in result.suppressed] == [
        ("signal:frame-2", "min_interval"),
        ("signal:frame-5", "max_fires"),
    ]
    # A replayed page with its firings already in the journal fires nothing again.
    history = [
        FiringRecord("ci-red-fix", item.trigger_key, item.at, item.depth, "fired")
        for item in result.firings
    ]
    replayed = plan([CI_RED_FIX], observations, history=history)
    assert replayed.firings == ()
    assert {item.reason for item in replayed.suppressed} == {"max_fires"}


def test_rate_limit_counts_fires_within_the_window() -> None:
    artifact = watcher(
        "artifact-to-ingest",
        {
            "on": {"signal": "artifact.ready", "where": "event.media_type == 'application/pdf'"},
            "then": [
                {"instruct": {"text": "Ingest the artifact.", "include": ["event.artifact_ref"]}}
            ],
            "limits": {"max_fires": 50, "rate": "2/h"},
        },
    )
    observations = [
        signal(
            "artifact.ready",
            {"media_type": "application/pdf", "artifact_ref": f"artifact://a/{index}"},
            when=at(index * 600),
            ref=f"f{index}",
        )
        for index in range(1, 8)
    ]
    result = plan([artifact], observations, now=at(10_000))
    fired = [item.trigger_key for item in result.firings]
    assert fired == ["signal:f1", "signal:f2", "signal:f7"]
    assert parse_rate("2/h") == (2, 3600) and parse_rate("3/10m") == (3, 600)


def test_signal_trust_tier_gates_driving_actions() -> None:
    weak = signal(
        "github.check_suite.completed",
        {"conclusion": "failure", "head_branch": "mc/run-1/x"},
        when=at(60),
        ref="weak",
        trust="environment_key",
    )
    unknown = signal(
        "github.check_suite.completed",
        {"conclusion": "failure", "head_branch": "mc/run-1/x"},
        when=at(61),
        ref="unknown",
        trust=None,
    )
    signed = signal(
        "github.check_suite.completed",
        {"conclusion": "failure", "head_branch": "mc/run-1/x"},
        when=at(1000),
        ref="signed",
        trust="provider_signed",
    )
    result = plan([CI_RED_FIX], [weak, unknown, signed])
    assert [item.trigger_key for item in result.firings] == ["signal:signed"]
    assert [item.reason for item in result.suppressed] == ["trust_tier", "trust_tier"]
    with pytest.raises(ValueError, match="need min_trust provider_signed"):
        WatcherSpec.model_validate(
            {
                "on": {"signal": "x.y"},
                "then": [{"command": {"kind": "cancel"}}],
                "limits": {"min_trust": "environment_key"},
            }
        )


def test_a_due_clock_that_satisfies_a_wait_fires_only_once_the_wait_is_declared() -> None:
    nudge = watcher(
        "nudge",
        {
            "on": {"absence": {"of": ["frame"], "for": "20m"}},
            "then": [{"satisfy_wait": {"node": "await-merge"}}],
        },
    )
    held = plan([nudge], now=at(30 * 60))
    assert held.firings == () and held.suppressed == ()
    declared = plan([nudge], now=at(30 * 60), waits=frozenset({wait_condition_id("await-merge")}))
    (firing,) = declared.firings
    assert firing.trigger_key == f"absence:{T0.isoformat()}"


def test_absence_fires_once_per_silence_and_respects_while_and_terminal() -> None:
    # Frames until minute 5, then silence: due at 25 minutes, again at 45, then max_fires.
    result = plan([STALLED], now=at(50 * 60), last_seen={"frame": at(5 * 60)})
    assert [item.at for item in result.firings] == [at(25 * 60)]
    assert result.firings[0].trigger_key == f"absence:{at(5 * 60).isoformat()}"
    history = [
        FiringRecord("stalled", item.trigger_key, item.at, 1, "fired") for item in result.firings
    ]
    second = plan([STALLED], now=at(50 * 60), last_seen={"frame": at(5 * 60)}, history=history)
    assert [item.at for item in second.firings] == [at(45 * 60)]
    third = plan(
        [STALLED],
        now=at(70 * 60),
        last_seen={"frame": at(5 * 60)},
        history=[*history, FiringRecord("stalled", "absence:2", at(45 * 60), 1, "fired")],
    )
    assert third.firings == () and [item.reason for item in third.suppressed] == ["max_fires"]
    # Not yet due: the deadline is reported for the workflow timer.
    early = plan([STALLED], now=at(10 * 60), last_seen={"frame": at(5 * 60)})
    assert early.firings == () and early.next_deadline == at(25 * 60)
    # `while` gates the clock; a terminal run arms no clocks at all.
    paused = plan([STALLED], now=at(50 * 60), run={"phase": "paused"})
    assert paused.firings == ()
    assert plan([STALLED], now=at(50 * 60), run_terminal=True).next_deadline is None


def test_schedule_ticks_collapse_to_the_latest_and_report_the_next() -> None:
    heartbeat = watcher(
        "heartbeat",
        {"on": {"schedule": {"every": "15m"}}, "then": [{"notify": {"kind": "progress"}}]},
    )
    result = plan([heartbeat], now=at(50 * 60))
    (firing,) = result.firings
    assert firing.trigger_key == "schedule:3" and firing.at == at(45 * 60)
    assert result.next_deadline == at(60 * 60)


def drive(descriptor: WatcherDescriptor, *, until: datetime) -> list[datetime]:
    """Run passes the way ``mc.watchers.v1`` does (at the reported deadline, else after the
    poll interval) and return the firing moments; a deadline always lies after its pass."""

    history: list[FiringRecord] = []
    now = T0
    while now < until:
        result = plan([descriptor], now=now, history=history)
        history.extend(
            FiringRecord(item.watcher.watcher_id, item.trigger_key, item.at, 1, "fired")
            for item in result.firings
        )
        assert result.next_deadline is None or result.next_deadline > now
        now = result.next_deadline or now + timedelta(minutes=5)
    return [item.at for item in history]


@pytest.mark.parametrize(
    ("trigger", "limits", "expected_minutes"),
    [
        # min_interval longer than the silence: the held silence fires once the interval allows.
        ({"absence": {"of": ["frame"], "for": "20m"}}, {"min_interval": "60m"}, [20, 80, 140, 200]),
        # A rate stricter than the tick: the latest tick fires as the window frees.
        ({"schedule": {"every": "10m"}}, {"rate": "1/30m"}, [10, 40, 70, 100, 130]),
        ({"schedule": {"every": "10m"}}, {"min_interval": "25m"}, [10, 35, 60, 85, 110]),
    ],
)
def test_clock_triggers_held_by_interval_or_rate_fire_once_allowed_and_never_spin(
    trigger: dict[str, Any], limits: dict[str, Any], expected_minutes: list[int]
) -> None:
    clock = watcher(
        "clock",
        {
            "on": trigger,
            "then": [{"notify": {"kind": "blocked"}}],
            "limits": {"max_fires": len(expected_minutes), **limits},
        },
    )
    fired = drive(clock, until=at(6 * 3600))
    assert fired == [at(minute * 60) for minute in expected_minutes]


def test_a_spent_or_over_budget_clock_watcher_reports_no_past_deadline() -> None:
    spent = watcher(
        "spent",
        {
            "on": {"absence": {"of": ["frame"], "for": "20m"}},
            "then": [{"instruct": {"text": "nudge"}}],
            "limits": {"max_fires": 1, "min_interval": "60m", "budget": {"tokens": 10}},
        },
    )
    history = [FiringRecord("spent", "absence:x", at(20 * 60), 1, "fired")]
    exhausted = plan([spent], now=at(90 * 60), history=history)
    assert [item.reason for item in exhausted.suppressed] == ["max_fires"]
    assert exhausted.next_deadline is None
    over = plan([spent], now=at(30 * 60), usage={"tokens.total": 10})
    assert [item.reason for item in over.suppressed] == ["budget_exhausted"]
    assert over.next_deadline is None


def test_recursion_depth_follows_causation_and_watcher_events() -> None:
    echo = watcher(
        "echo",
        {
            "on": {"event": "workflow_run.queue_instruction"},
            "then": [{"instruct": {"text": "again"}}],
            "limits": {"max_fires": 10, "min_trust": "provider_signed"},
        },
    )
    seed = event("workflow_run.queue_instruction", when=at(1), seq=1)
    first = plan([echo], [seed])
    (firing,) = first.firings
    assert firing.depth == 1
    request = str(firing.actions[0].request_id)
    history = [FiringRecord("echo", firing.trigger_key, firing.at, 1, "fired", (request,))]
    caused = event("workflow_run.queue_instruction", when=at(2), seq=2, causation_ref=request)
    second = plan([echo], [caused], history=history)
    assert [item.depth for item in second.firings] == [2]
    request_2 = str(second.firings[0].actions[0].request_id)
    loop = event("workflow_run.queue_instruction", when=at(3), seq=3, causation_ref=request_2)
    third = plan(
        [echo],
        [loop],
        history=[*history, FiringRecord("echo", "k2", at(2), 2, "fired", (request_2,))],
    )
    assert third.firings == () and third.suppressed[0].reason == "recursion_bound"
    # A watcher reacting to watcher.fired inherits that firing's depth.
    meta = watcher(
        "meta", {"on": {"event": "watcher.fired"}, "then": [{"notify": {"kind": "progress"}}]}
    )
    fired = event("watcher.fired", {"watcher_id": "echo", "depth": 2}, when=at(4), seq=4)
    assert plan([meta], [fired]).suppressed[0].reason == "recursion_bound"


def test_budget_stops_instruct_once_usage_reaches_it() -> None:
    guarded = watcher(
        "guarded",
        {
            "on": {"event": "artifact.admitted"},
            "then": [{"instruct": {"text": "ingest"}}],
            "limits": {"budget": {"tokens": 1000, "usd": "2.50"}},
        },
    )
    item = event("artifact.admitted", when=at(1), seq=1)
    assert plan([guarded], [item], usage={"tokens.total": 999}).firings
    assert plan([guarded], [item], usage={"tokens.total": 1000}).suppressed[0].reason == (
        "budget_exhausted"
    )
    assert plan([guarded], [item], usage={"currency.estimated_micros": 2_500_000}).suppressed[
        0
    ].reason == ("budget_exhausted")


def test_public_aliases_match_and_until_retires_the_watcher() -> None:
    done = watcher(
        "done-notify",
        {"on": {"event": "run.completed"}, "then": [{"notify": {"kind": "terminal_result"}}]},
    )
    terminal = event("workflow_run.terminalize", when=at(5), seq=5, alias="run.completed")
    (firing,) = plan([done], [terminal]).firings
    assert firing.trigger.type == "run.completed"
    bounded = watcher(
        "until-merged",
        {
            "on": {"event": "artifact.admitted"},
            "then": [{"notify": {"kind": "accepted_output"}}],
            "until": {"event": "chain.completed"},
        },
    )
    observations = [
        event("artifact.admitted", when=at(1), seq=1),
        event("chain.completed", when=at(2), seq=2),
        event("artifact.admitted", when=at(3), seq=3),
    ]
    result = plan([bounded], observations)
    assert [item.trigger_key for item in result.firings] == ["event:event-1"]
    assert result.retired == frozenset({"until-merged"})
    # Retirement is carried between passes by the workflow.
    later = plan([bounded], [event("artifact.admitted", when=at(4), seq=4)], retired=result.retired)
    assert later.firings == ()
    deadline = watcher(
        "until-deadline",
        {
            "on": {"event": "artifact.admitted"},
            "then": [{"notify": {"kind": "accepted_output"}}],
            "until": {"deadline": (T0 + timedelta(seconds=2)).isoformat()},
        },
    )
    assert [item.trigger_key for item in plan([deadline], observations).firings] == [
        "event:event-1"
    ]
