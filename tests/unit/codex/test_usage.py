"""Codex turn accounting: cumulative counters, replay and interrupted replacements.

These are offline fixtures. A model call is smaller than a native turn, and a
thread total spans native turns; neither can substitute for attributable turn usage.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from mission_control.adapters.codex.frames import TurnUsageTracker, occupancy_from_usage
from mission_control.adapters.codex.protocol import ThreadTokenUsage, TokenUsageBreakdown
from mission_control.application.frames.kinds import classify
from mission_control.domain.execution.lanes import CancelTurnRequest, UsageRequest
from mission_control.domain.frames.contracts import LaneProfile
from tests.unit.codex.drive import fields, observed, sent, started
from tests.unit.codex.fixture_app_server import FixtureLauncher
from tests.unit.codex.support import codex_stack


def _usage(
    input_tokens: int,
    output_tokens: int,
    *,
    cached: int = 0,
    written: int = 0,
    last_input: int | None = None,
    last_output: int | None = None,
) -> ThreadTokenUsage:
    total = TokenUsageBreakdown(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        cached_input_tokens=cached,
        cache_write_input_tokens=written,
    )
    last = TokenUsageBreakdown(
        input_tokens=input_tokens if last_input is None else last_input,
        output_tokens=output_tokens if last_output is None else last_output,
        total_tokens=(input_tokens if last_input is None else last_input)
        + (output_tokens if last_output is None else last_output),
    )
    return ThreadTokenUsage(last=last, total=total, model_context_window=10_000)


def test_multiple_calls_and_duplicate_notifications_count_once_with_cache_breakdowns() -> None:
    tracker = TurnUsageTracker()
    tracker.start_thread("thread")
    tracker.begin("turn-1")
    first = _usage(100, 10, cached=20, written=70)
    snapshot = tracker.record("turn-1", first, epoch="e", seq=1)
    tracker.record("turn-1", first, epoch="e", seq=2)
    final = _usage(220, 30, cached=100, written=100, last_input=120, last_output=20)
    tracker.record("turn-1", final, epoch="e", seq=3)
    report = tracker.report("turn-1")
    assert (report.input_tokens, report.output_tokens, report.total_tokens) == (220, 30, 250)
    assert (report.cache_read_tokens, report.cache_write_tokens) == (100, 100)
    assert report.cost_micros_usd is None
    assert tracker.record("turn-1", first, epoch="e", seq=1) is snapshot
    assert snapshot.report().total_tokens == 110, "pump-ahead cannot rewrite an old snapshot"
    assert occupancy_from_usage(final).used_tokens == 140, "occupancy still uses last call"


def test_replacement_turn_subtracts_the_interrupted_turn_instead_of_billing_twice() -> None:
    tracker = TurnUsageTracker()
    tracker.start_thread("thread")
    tracker.begin("interrupted")
    tracker.record("interrupted", _usage(100, 10), epoch="e", seq=1)
    tracker.begin("replacement")
    tracker.record("replacement", _usage(400, 60), epoch="e", seq=2)
    assert tracker.report("interrupted").total_tokens == 110
    assert tracker.report("replacement").total_tokens == 350
    assert tracker.latest["replacement"].provenance()["baseline_source"] == "previous_turn_total"
    assert tracker.latest["replacement"].provenance()["root_thread_id"] == "thread"


def test_history_and_missing_previous_turn_usage_cannot_establish_zero() -> None:
    tracker = TurnUsageTracker()
    tracker.resume_thread("existing-thread")
    tracker.begin("historical-turn")
    value = tracker.record("historical-turn", _usage(400, 60), epoch="e", seq=1)
    assert value.report().disposition == "unknown"
    assert value.provenance()["baseline_total"] is None
    tracker.start_thread("new-thread")
    tracker.begin("unreported-turn")
    tracker.begin("next-turn")
    tracker.record("next-turn", _usage(700, 80), epoch="e", seq=2)
    assert tracker.report("next-turn").disposition == "unknown"


def test_known_turn_baseline_survives_reconnect_but_a_gap_cannot_seed_a_new_turn() -> None:
    tracker = TurnUsageTracker()
    tracker.start_thread("thread")
    tracker.begin("turn")
    tracker.record("turn", _usage(100, 10), epoch="old", seq=1)
    tracker.resume_thread("thread")
    tracker.record("turn", _usage(200, 30), epoch="new", seq=1)
    assert tracker.report("turn").total_tokens == 230
    tracker.resume_thread("thread")
    tracker.begin("new-turn-after-gap")
    tracker.record("new-turn-after-gap", _usage(400, 60), epoch="newer", seq=1)
    assert tracker.report("new-turn-after-gap").disposition == "unknown"


@pytest.mark.parametrize("bad", [_usage(90, 10), _usage(100, 9), _usage(100, 10, cached=19)])
def test_counter_regressions_refuse_attribution(bad: ThreadTokenUsage) -> None:
    tracker = TurnUsageTracker()
    tracker.start_thread("thread")
    tracker.begin("turn")
    tracker.record("turn", _usage(100, 10, cached=20), epoch="e", seq=1)
    value = tracker.record("turn", bad, epoch="e", seq=2)
    assert value.report().disposition == "unknown"
    assert value.provenance()["monotonic"] is False
    tracker.record("turn", _usage(200, 20, cached=40), epoch="e", seq=3)
    assert tracker.report("turn").disposition == "unknown", "a reset cannot repair its baseline"


def test_late_previous_turn_increment_invalidates_the_next_turn_boundary() -> None:
    tracker = TurnUsageTracker()
    tracker.start_thread("thread")
    tracker.begin("first")
    tracker.record("first", _usage(100, 10), epoch="e", seq=1)
    tracker.begin("next")
    tracker.record("first", _usage(120, 12), epoch="e", seq=2)
    tracker.record("next", _usage(200, 20), epoch="e", seq=3)
    assert tracker.report("next").disposition == "unknown"


def test_duplicate_predecessor_counter_cannot_regress_or_invalidate_replacement_usage() -> None:
    tracker = TurnUsageTracker()
    tracker.start_thread("thread")
    tracker.begin("first")
    first = _usage(100, 10)
    tracker.record("first", first, epoch="e", seq=1)
    tracker.begin("replacement")
    tracker.record("replacement", _usage(300, 30), epoch="e", seq=2)
    tracker.record("first", first, epoch="e", seq=3)
    tracker.record("replacement", _usage(400, 40), epoch="e", seq=4)
    assert tracker.report("first").total_tokens == 110
    assert tracker.report("replacement").total_tokens == 330


async def test_multicall_turn_emits_attributed_companions_without_changing_provider_frames(
    tmp_path: Path,
) -> None:
    launcher = FixtureLauncher(
        scripts=[
            [
                {"step": "usage", "input": 100, "output": 10},
                {"step": "usage", "input": 200, "output": 20},
                {"step": "complete"},
            ]
        ]
    )
    stack = codex_stack(tmp_path, launcher=launcher)
    session = await started(stack)
    turn = await sent(stack, session)
    frames = await observed(stack, turn)
    raw = [
        f for f in frames if f.raw_kind == "thread/tokenUsage/updated" and "tokenUsage" in f.body
    ]
    attributed = [f for f in frames if "codex_usage_provenance" in f.body]
    assert len(raw) == len(attributed) == 2
    assert raw[-1].body["tokenUsage"]["last"]["totalTokens"] == 220
    assert raw[-1].body["tokenUsage"]["total"]["totalTokens"] == 330
    assert "usage" not in raw[-1].body
    assert attributed[-1].body["usage"]["total_tokens"] == 330
    assert stack.harness.closing_facts(turn, frames[-1]).usage.total_tokens == 330
    report = await stack.harness.usage(UsageRequest(**fields(stack), session=session, turn=turn))
    assert report.total_tokens == 330
    replay = await observed(stack, turn, after=raw[0].cursor)
    assert replay[0].provider_key == attributed[0].provider_key
    assert replay[0].body == attributed[0].body
    await launcher.shutdown()


async def test_cancelled_original_and_replacement_have_separate_attributable_usage(
    tmp_path: Path,
) -> None:
    launcher = FixtureLauncher(
        scripts=[
            [{"step": "usage", "input": 100, "output": 10}, {"step": "hold"}],
            [
                {"step": "usage", "input": 200, "output": 20},
                {"step": "usage", "input": 300, "output": 30},
                {"step": "complete"},
            ],
        ]
    )
    stack = codex_stack(tmp_path, launcher=launcher)
    session = await started(stack)
    first = await sent(stack, session)
    await asyncio.wait_for(launcher.server.held.wait(), timeout=5)
    receipt = await stack.harness.cancel_turn(
        CancelTurnRequest(**fields(stack), turn=first, reason="replace")
    )
    assert receipt.acknowledged
    first_frames = await observed(stack, first)
    second = await sent(stack, session, "replacement", turn_no=2)
    second_frames = await observed(stack, second)
    assert stack.harness.closing_facts(first, first_frames[-1]).usage.total_tokens == 110
    assert stack.harness.closing_facts(second, second_frames[-1]).usage.total_tokens == 550
    assert second_frames[-1].native_turn_ref == second.native_turn_ref
    await launcher.shutdown()


async def test_late_previous_turn_companion_invalidates_persisted_replacement_attribution(
    tmp_path: Path,
) -> None:
    from mission_control.adapters.codex.usage import observed_usage

    late = _usage(220, 22, last_input=20, last_output=2)
    late_params = {"turnId": "filled-after-first-turn", "tokenUsage": late.wire()}
    launcher = FixtureLauncher(
        scripts=[
            [{"step": "usage", "input": 100, "output": 10}, {"step": "complete"}],
            [
                {"step": "usage", "input": 100, "output": 10},
                {"step": "notify", "method": "thread/tokenUsage/updated", "params": late_params},
                {"step": "complete"},
            ],
        ]
    )
    stack = codex_stack(tmp_path, launcher=launcher)
    session = await started(stack)
    first = await sent(stack, session)
    first_frames = await observed(stack, first)
    late_params["turnId"] = first.native_turn_ref
    replacement = await sent(stack, session, "replacement", turn_no=2)
    replacement_frames = await observed(stack, replacement)
    frames = first_frames + replacement_frames
    companion = next(
        f
        for f in replacement_frames
        if f.body.get("codex_usage_provenance", {}).get("invalidates_turn_ref")
        == replacement.native_turn_ref
    )
    assert companion.native_turn_ref == first.native_turn_ref
    assert companion.body["usage"]["disposition"] == "unknown"
    assert companion.body["codex_usage_provenance"]["monotonic"] is False
    persisted = []
    for frame in frames:
        body = json.dumps(frame.body)
        persisted.append(
            SimpleNamespace(
                lane_profile=LaneProfile.CODEX,
                native_session_ref=session.native_session_ref,
                native_turn_ref=frame.native_turn_ref,
                kind=classify(LaneProfile.CODEX, frame.raw_kind, frame.body).kind,
                subordinate_ref=frame.subordinate_ref,
                body_excerpt=body,
                body_bytes=len(body.encode()),
                lifecycle_body={},
            )
        )
    reports = observed_usage(persisted)
    assert (
        reports[(session.native_session_ref, replacement.native_turn_ref)].disposition == "unknown"
    )
    assert (
        stack.harness.closing_facts(replacement, replacement_frames[-1]).usage.disposition
        == "unknown"
    )
    await launcher.shutdown()
