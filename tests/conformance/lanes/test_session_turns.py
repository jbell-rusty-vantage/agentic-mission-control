"""Session-turn scenarios for every lane that claims them (SPEC-06 section 3).

Each runs the lane's fake provider through the production lane turn service inside a real Run
(command mailbox, interrupt_and_inject service, governed operation boundary), so a lane passes
only when Mission Control's own controls work on it: a turn starts, is observed and settles from
its closing facts; a resumed segment stores no frame twice; nothing is sent while a turn runs;
cancel and interrupt_and_inject do what the describe says; a turn past its budget stops; and
usage the provider never reported stays unknown.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mission_control.adapters.codex.usage import observed_usage
from mission_control.domain.frames.body import frame_body_object
from mission_control.domain.frames.contracts import FrameKind
from mission_control.domain.policies.mailbox import MailboxState
from tests.conformance.lanes.adapters.codex import CodexConformance
from tests.conformance.lanes.contract import LaneAdapter, Scenario, Script
from tests.conformance.lanes.drive import (
    SEGMENT,
    cancel_held,
    cancel_request,
    delivery_states,
    finish,
    held_turn,
    lane_state,
    run_turn,
    settled,
)
from tests.conformance.lanes.registry import lanes_for

QUEUED = "Also record the run in the report's change log."
LATER = "Then run the linters."
INJECTED = "Redirect: build on release/2.3."
# The interrupt delivery every lane claiming the scenario declares today; a lane declaring
# `cooperative_inject` (a steer into the running turn) adds its expectation here first.
INTERRUPT_SEMANTICS = "cancel_and_replace"


@pytest.mark.parametrize("lane", lanes_for(Scenario.START_OBSERVE_SETTLE))
async def test_a_turn_starts_is_observed_and_settles_from_its_closing_facts(
    lane: LaneAdapter, tmp_path: Path
) -> None:
    fake = await lane.open(tmp_path, Script.FULL_TURN)
    result = await run_turn(fake)
    assert result.done and settled(result).status == "completed"
    facts = result.closing_facts
    assert facts is not None and facts.native_status == "finished"
    assert facts.usage.disposition != "unknown" and facts.usage.total_tokens > 0
    state = await lane_state(fake)
    assert state is not None and state.native_session_ref and state.native_turn_ref
    assert result.native.session_ref == state.native_session_ref
    frames = fake.frames()
    assert [frame.kind for frame in frames].count(FrameKind.RUN_RESULT) >= 1
    assert len({frame.provider_key for frame in frames}) == len(frames)
    assert len(fake.sends()) == 1
    assert fake.ended(), "end_session released the native resources after custody"


@pytest.mark.parametrize("lane", lanes_for(Scenario.REATTACH_MID_STREAM))
async def test_a_resumed_segment_reattaches_without_a_send_or_a_duplicate_frame(
    lane: LaneAdapter, tmp_path: Path
) -> None:
    fake = await lane.open(tmp_path, Script.FULL_TURN)
    first = await run_turn(fake, segment=SEGMENT.model_copy(update={"max_frames": 3}))
    assert not first.done and first.cursor is not None, "the segment ended mid-stream"
    result = await run_turn(fake, phase="resume", cursor=first.cursor, segment_no=2)
    assert result.done
    assert settled(result).status == "completed"
    assert len(fake.sends()) == 1, "a resumed segment never sends again"
    frames = fake.frames()
    assert len({frame.provider_key for frame in frames}) == len(frames)
    assert [frame.kind for frame in frames].count(FrameKind.RUN_RESULT) == 1


@pytest.mark.parametrize("lane", lanes_for(Scenario.SEND_TURN_WHILE_BUSY))
async def test_nothing_is_sent_while_a_turn_runs(lane: LaneAdapter, tmp_path: Path) -> None:
    """A queued instruction rides the next send with the declared semantics; one queued while
    the turn runs waits in the mailbox for the next boundary instead of reaching the busy
    session."""

    fake = await lane.open(tmp_path, Script.HELD_TURN)
    declared = fake.describe.delivery_semantics["queue_instruction"]
    first = await fake.control.command("queue_instruction", QUEUED)
    await fake.control.deliver()
    task = await held_turn(fake)
    status = await fake.control.status(first)
    report = status.receipts[-1].delivery_report
    assert delivery_states(status)[-1] == "observed" and report is not None
    assert report.requested_semantics == report.delivered_semantics == declared
    second = await fake.control.command("queue_instruction", LATER)
    fake.release()
    assert settled(await finish(task)).status == "completed"
    assert delivery_states(await fake.control.status(first))[-1] == "applied"
    entries = {entry.command_id: entry for entry in await fake.control.entries()}
    assert entries[str(second.request_id)].state == MailboxState.QUEUED
    assert len(fake.sends()) == 1, "the busy session received nothing while its turn ran"


@pytest.mark.parametrize("lane", lanes_for(Scenario.CANCEL))
async def test_cancel_reaches_the_provider_and_settles_cancelled_once(
    lane: LaneAdapter, tmp_path: Path
) -> None:
    fake = await lane.open(tmp_path, Script.HELD_TURN)
    task = await held_turn(fake, cancel=True)
    outcome = await cancel_held(fake, task)
    result = settled(outcome)
    assert (result.status, result.failure_code) == ("cancelled", "cancelled")
    if lane.profile == "codex":
        assert result.usage.amounts["tokens.total"] == 90
        usage_frames = [frame for frame in fake.frames() if frame.kind == FrameKind.USAGE]
        attributed = [
            (frame, body)
            for frame in usage_frames
            if "codex_usage_provenance"
            in (
                body := frame_body_object(
                    frame.body_excerpt, frame.body_bytes, frame.lifecycle_body
                )
            )
        ]
        assert len(attributed) == 1
        frame, body = attributed[0]
        provenance = body["codex_usage_provenance"]
        assert body["threadId"] == frame.native_session_ref == provenance["root_thread_id"]
        assert body["turnId"] == frame.native_turn_ref
        assert provenance["baseline_source"] == "fresh_thread"
        assert not any(provenance["baseline_total"].values())
        assert {
            key: provenance["current_total"][key]
            for key in ("inputTokens", "outputTokens", "totalTokens")
        } == {"inputTokens": 60, "outputTokens": 30, "totalTokens": 90}
        reports = observed_usage(fake.frames())
        assert reports == observed_usage([*fake.frames(), *fake.frames()])
        assert reports[(frame.native_session_ref, frame.native_turn_ref)].total_tokens == 90
    cancels = fake.cancels()
    assert cancels >= 1, "the requested cancel reached the provider"
    again = await fake.control.service.cancel(cancel_request(fake))
    assert again.settled and again.operation_result == outcome.operation_result
    assert fake.cancels() == cancels, "a settled cancel is idempotent"


async def test_codex_interrupted_without_counters_retains_reconciliation(tmp_path: Path) -> None:
    fake = await CodexConformance(held_usage=False).open(tmp_path, Script.HELD_TURN)
    task = await held_turn(fake, cancel=True)
    outcome = await cancel_held(fake, task)
    result = settled(outcome)
    assert fake.cancels() >= 1
    assert not outcome.settled
    assert (result.status, result.failure_code) == (
        "in_doubt",
        "codex_usage_requires_reconciliation",
    )
    assert "tokens.total" not in result.usage.amounts
    reports = observed_usage(fake.frames())
    assert reports and all(report.disposition == "unknown" for report in reports.values())
    assert all(report.total_tokens == 0 for report in reports.values())
    assert any(frame.kind == FrameKind.RUN_RESULT for frame in fake.frames())
    assert not fake.control.lanes.budget.settlements
    assert await fake.control.lanes.boundary.lane_settlement(fake.operation) is None
    sends = fake.sends()
    again = await fake.control.service.cancel(cancel_request(fake))
    assert not again.settled
    # Cleanup can leave no fresh provider observation on a later control. The
    # durable operation stays unsettled; an absent result never means free usage.
    assert again.operation_result is None
    assert await fake.control.lanes.boundary.lane_settlement(fake.operation) is None
    assert fake.sends() == sends
    assert observed_usage(fake.frames()) == reports
    assert not fake.control.lanes.budget.settlements


@pytest.mark.parametrize("lane", lanes_for(Scenario.INTERRUPT_AND_INJECT))
async def test_interrupt_and_inject_delivers_with_the_declared_semantics(
    lane: LaneAdapter, tmp_path: Path
) -> None:
    fake = await lane.open(tmp_path, Script.INTERRUPTIBLE_TURN)
    assert fake.describe.delivery_semantics["interrupt_and_inject"] == INTERRUPT_SEMANTICS
    task = await held_turn(fake)
    receipt = await fake.control.command("interrupt_and_inject", INJECTED)
    result = settled(await finish(task))
    assert result.status == "completed"
    if lane.profile == "codex":
        assert result.usage.amounts["tokens.total"] == 250
    sends = fake.sends()
    assert len(sends) == 2 and sends[0][0] == sends[1][0], "a replacement turn, same session"
    assert INJECTED in sends[1][1] and INJECTED not in sends[0][1]
    status = await fake.control.status(receipt)
    assert delivery_states(status)[-1] == "applied"
    (report,) = [
        item.delivery_report
        for item in status.receipts
        if item.delivery_report and item.delivery_report.native_refs.replacement_turn_ref
    ]
    assert report.delivered_semantics == INTERRUPT_SEMANTICS
    cancelled = report.native_refs.cancelled_turn_ref
    replacement = report.native_refs.replacement_turn_ref
    assert cancelled and cancelled != replacement, "the replacement is a new native turn"
    frames = fake.frames()
    assert len({frame.provider_key for frame in frames}) == len(frames)
    assert {cancelled, replacement} <= {frame.native_turn_ref for frame in frames}


@pytest.mark.parametrize("lane", lanes_for(Scenario.BUDGET_STOP))
async def test_a_turn_past_its_budget_stops_budget_exceeded(
    lane: LaneAdapter, tmp_path: Path
) -> None:
    fake = await lane.open(
        tmp_path,
        Script.FULL_TURN,
        operation_changes={"budget_limits": {"model.turns": 2, "tokens.total": 1}},
    )
    result = settled(await run_turn(fake))
    assert (result.status, result.failure_code) == ("failed", "budget_exceeded")
    assert result.usage.amounts["tokens.total"] > 1, "the observed usage is recorded, never zero"


@pytest.mark.parametrize("lane", lanes_for(Scenario.UNKNOWN_USAGE))
async def test_usage_the_provider_never_reported_stays_unknown(
    lane: LaneAdapter, tmp_path: Path
) -> None:
    fake = await lane.open(tmp_path, Script.NO_USAGE)
    result = await run_turn(fake)
    assert result.done
    if lane.profile == "codex":
        assert (settled(result).status, settled(result).failure_code) == (
            "in_doubt",
            "codex_usage_requires_reconciliation",
        )
    else:
        assert settled(result).status == "completed"
    facts = result.closing_facts
    assert facts is not None
    assert facts.usage.disposition == "unknown" and facts.usage.total_tokens == 0
    assert facts.cost_disposition == "unknown"
    assert result.usage_estimate.disposition == "unknown"
    assert "tokens.total" not in settled(result).usage.amounts, "unknown is never charged as zero"
