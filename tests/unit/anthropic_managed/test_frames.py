"""The `claude_managed` frame classifier: turn correlation, positions, kinds and closing facts.

Pure: event bodies in the shapes of the pinned `anthropic` 1.13.0 session event types and the
HL-23 smoke sequence (research/provider-smoke-2026-10.md section 2.3).
"""

from __future__ import annotations

from typing import Any, Final

import pytest

from mission_control.adapters.anthropic_managed import frames
from mission_control.adapters.remote_session.stream import STREAM_START
from mission_control.application.frames.kinds import (
    DEDUPE_KEY_RULES,
    KIND_TABLES,
    UnknownKindCounter,
    classify,
)
from mission_control.domain.frames.contracts import FrameKind, LaneProfile

TURN: Final = "sevt_turn"
LANE: Final = LaneProfile.CLAUDE_MANAGED
# `BetaManagedAgentsSessionEventType` in anthropic 1.13.0: every event the session log carries.
SDK_EVENT_TYPES: Final = (
    "user.message",
    "user.interrupt",
    "user.tool_confirmation",
    "user.custom_tool_result",
    "agent.custom_tool_use",
    "agent.message",
    "agent.thinking",
    "agent.mcp_tool_use",
    "agent.mcp_tool_result",
    "agent.tool_use",
    "agent.tool_result",
    "agent.thread_message_received",
    "agent.thread_message_sent",
    "agent.thread_context_compacted",
    "session.error",
    "session.status_rescheduled",
    "session.status_running",
    "session.status_idle",
    "session.status_terminated",
    "session.thread_created",
    "span.outcome_evaluation_start",
    "span.outcome_evaluation_end",
    "span.model_request_start",
    "span.model_request_end",
    "span.outcome_evaluation_ongoing",
    "user.define_outcome",
    "session.thread_status_running",
    "session.thread_status_idle",
    "session.thread_status_terminated",
    "user.tool_result",
    "session.thread_status_rescheduled",
    "session.updated",
    "system.message",
    "session.usage",
    "workflow_run.created",
    "workflow_run.status_running",
    "workflow_run.status_idle",
    "workflow_run.status_ended",
    "workflow_run.error",
    "workflow_run.phase_started",
    "workflow_run.phase_ended",
)
_ticks = iter(range(1, 10_000))


def event(kind: str, **fields: Any) -> dict[str, Any]:
    tick = next(_ticks)
    return {
        "type": kind,
        "id": f"sevt_{tick:04d}",
        "processed_at": f"2026-10-13T09:00:00.{tick:06d}Z",
        **fields,
    }


def message() -> dict[str, Any]:
    return {**event("user.message", content=[]), "id": TURN}


def idle(reason: str) -> dict[str, Any]:
    return event("session.status_idle", stop_reason={"type": reason})


def fold(*bodies: dict[str, Any], **changes: Any) -> tuple[frames.TurnFold, list[str | None]]:
    folded = frames.TurnFold(TURN, **changes)
    return folded, [folded.observe(body) for body in bodies]


# --- positions and cursors ---------------------------------------------------------------------


def test_a_position_is_the_processed_time_and_id_and_round_trips() -> None:
    body = event("agent.message")
    position = frames.event_position(body)
    assert position is not None
    micros, event_id = frames.parse_position(position) or (0, "")
    assert event_id == body["id"]
    assert frames.processed_iso(micros) == body["processed_at"]
    assert frames.event_position({**body, "processed_at": None}) is None, "queued: no position"
    assert frames.event_position({**body, "id": ""}) is None, "an interrupt may carry no id"


def test_a_frame_key_alone_names_the_cursor_a_reattach_resumes_from() -> None:
    cursors = frames.ManagedEventCursors()
    position = frames.event_position(event("span.model_request_end")) or ""
    key = cursors.provider_key(TURN, position)
    assert key == f"managed:{TURN}:{position}" and ":" not in position
    cursor = cursors.resume_cursor(key)
    assert cursor == cursors.cursor(TURN, position) == f"{TURN}@{position}"
    assert cursors.resume_point(cursor, TURN) == position
    assert cursors.resume_point(cursor, "sevt_other") is None, "another turn resumes nothing"
    assert cursors.resume_point(STREAM_START, TURN) is None
    assert cursors.resume_cursor(frames.final_key(TURN)) is None
    assert cursors.resume_cursor("sse-open:sevt_turn:start") is None


# --- turn correlation --------------------------------------------------------------------------


def test_events_before_the_turns_message_was_processed_are_not_the_turns() -> None:
    folded, kinds = fold(
        idle("end_turn"),  # the previous turn's close
        {**message(), "processed_at": None},  # the queued echo
        event("session.status_running"),
        message(),
        event("agent.message", content=[{"type": "text", "text": "Answer"}]),
        idle("end_turn"),
    )
    assert kinds == [None, None, None, "user.message", "agent.message", "session.status_idle"]
    assert folded.started and folded.result == "Answer"


@pytest.mark.parametrize(
    ("reason", "interrupted", "status"),
    [
        ("end_turn", False, "finished"),
        ("end_turn", True, "cancelled"),
        ("retries_exhausted", False, "error"),
        ("refusal", False, "error"),
    ],
)
def test_an_ending_idle_closes_the_turn(reason: str, interrupted: bool, status: str) -> None:
    closing = idle(reason)
    folded, kinds = fold(message(), closing, interrupted=interrupted)
    assert kinds[-1] == frames.IDLE and folded.closes(frames.IDLE, closing)
    summary = folded.summary(frames.IDLE, closing)
    assert (summary["status"], summary["stop_reason"]) == (status, reason)


def test_an_interrupt_processed_inside_the_turn_makes_its_end_turn_cancelled() -> None:
    """HL-23: an interrupt lets the in-flight request finish, then idles with `end_turn`."""

    closing = idle("end_turn")
    folded, _kinds = fold(
        message(), event("user.interrupt"), event("span.model_request_end"), closing
    )
    assert folded.interrupted and folded.summary(frames.IDLE, closing)["status"] == "cancelled"


@pytest.mark.parametrize("reason", sorted(frames.WAITING_STOP_REASONS))
def test_an_idle_waiting_on_an_answer_or_the_budget_closes_nothing(reason: str) -> None:
    waiting = idle(reason)
    folded, kinds = fold(message(), waiting)
    assert kinds[-1] == frames.IDLE and not folded.closes(frames.IDLE, waiting)


def test_a_terminated_session_closes_the_turn_as_an_error() -> None:
    terminated = event("session.status_terminated")
    folded, _kinds = fold(message(), terminated)
    assert folded.closes(frames.TERMINATED, terminated)
    assert folded.summary(frames.TERMINATED, terminated)["status"] == "error"


def test_with_multiagent_an_idle_is_not_the_end_while_a_workflow_run_is_open() -> None:
    """R33: `idle` is not done while `workflow_run.*` is open."""

    early = idle("end_turn")
    folded, kinds = fold(
        message(), event("workflow_run.created", workflow_run_id="wfr_1", name="survey"), early
    )
    assert kinds[-1] == frames.RUNS_OPEN_IDLE and not folded.closes(kinds[-1] or "", early)
    late = idle("end_turn")
    kinds += [
        folded.observe(event("workflow_run.status_ended", workflow_run_id="wfr_1")),
        folded.observe(late),
    ]
    assert kinds[-1] == frames.IDLE and folded.closes(frames.IDLE, late)


def test_an_outcome_is_evidence_on_the_close_never_acceptance() -> None:
    closing = idle("end_turn")
    folded, _kinds = fold(
        message(),
        event(
            "span.outcome_evaluation_end",
            outcome_id="out_1",
            result="satisfied",
            iteration=2,
            explanation="All criteria met.",
        ),
        closing,
    )
    summary = folded.summary(frames.IDLE, closing)
    assert summary["outcome"] == {"outcome_id": "out_1", "result": "satisfied", "iteration": 2}
    facts = frames.closing_facts({frames.SUMMARY_KEY: summary})
    assert facts.native_status == "finished", "the turn's own close, whatever the grader said"


# --- usage and closing facts -------------------------------------------------------------------


def test_turn_tokens_sum_its_model_requests_and_cost_comes_from_list_cost() -> None:
    usage = {
        "input_tokens": 89,
        "output_tokens": 325,
        "cache_read_input_tokens": 15_070,
        "cache_creation_input_tokens": 13_510,
    }
    closing = idle("end_turn")
    folded, _kinds = fold(
        message(),
        event("span.model_request_end", model_usage=usage),
        event("span.model_request_end", model_usage=usage),
        event("session.usage", usage={"list_cost": {"amount": "4", "currency": "USD"}}),
        closing,
    )
    summary = {**folded.summary(frames.IDLE, closing), "list_cost_minor_units": 4}
    report = frames.turn_usage(summary)
    assert report.disposition == "settled"
    assert report.input_tokens == 2 * (89 + 15_070 + 13_510) and report.output_tokens == 650
    assert report.total_tokens == report.input_tokens + report.output_tokens
    assert report.cost_micros_usd == 40_000, "four cents"
    facts = frames.closing_facts({frames.SUMMARY_KEY: summary})
    assert facts.cost_disposition == "settled" and facts.usage == report


def test_nothing_reported_stays_unknown_and_a_missing_summary_is_in_doubt() -> None:
    closing = idle("end_turn")
    folded, _kinds = fold(message(), event("span.model_request_end"), closing)
    facts = frames.closing_facts({frames.SUMMARY_KEY: folded.summary(frames.IDLE, closing)})
    assert facts.usage.disposition == "unknown" and facts.cost_disposition == "unknown"
    assert frames.closing_facts({}).native_status == "in_doubt"
    assert frames.list_cost_minor_units({"list_cost": {"amount": "3", "currency": "EUR"}}) is None


def test_a_session_error_names_the_errored_close() -> None:
    closing = idle("retries_exhausted")
    folded, _kinds = fold(
        message(), event("session.error", error={"type": "model_overloaded_error"}), closing
    )
    facts = frames.closing_facts({frames.SUMMARY_KEY: folded.summary(frames.IDLE, closing)})
    assert (facts.native_status, facts.error_code) == ("error", "model_overloaded_error")


# --- kind table and tool calls -----------------------------------------------------------------


def test_every_session_event_type_has_a_kind_row() -> None:
    counter = UnknownKindCounter()
    for kind in (*SDK_EVENT_TYPES, frames.RUNS_OPEN_IDLE, frames.TURN_FINAL, "status"):
        assert classify(LANE, kind, {}, counter=counter).known, kind
    assert not counter.snapshot()
    assert set(SDK_EVENT_TYPES) <= set(KIND_TABLES[LANE])
    assert DEDUPE_KEY_RULES[LANE].startswith("managed:<turn user.message id>")


@pytest.mark.parametrize(
    ("raw_kind", "body", "kind"),
    [
        ("session.status_idle", {"stop_reason": {"type": "end_turn"}}, FrameKind.RUN_RESULT),
        ("session.status_idle", {"stop_reason": {"type": "requires_action"}}, FrameKind.STATUS),
        ("session.status_idle", {"stop_reason": {"type": "budget_reached"}}, FrameKind.STATUS),
        ("session.status_idle.runs_open", {}, FrameKind.STATUS),
        ("agent.tool_use", {"evaluated_permission": "ask"}, FrameKind.APPROVAL_REQUESTED),
        ("agent.tool_use", {"evaluated_permission": "allow"}, FrameKind.TOOL_CALL_STARTED),
        ("agent.tool_result", {"is_error": True}, FrameKind.TOOL_CALL_FAILED),
        ("agent.tool_result", {}, FrameKind.TOOL_CALL_COMPLETED),
        ("user.tool_confirmation", {}, FrameKind.APPROVAL_RESOLVED),
        ("session.usage", {}, FrameKind.USAGE),
        ("span.outcome_evaluation_end", {}, FrameKind.STATUS),
    ],
)
def test_kinds_follow_the_body_where_the_table_says(
    raw_kind: str, body: dict[str, Any], kind: FrameKind
) -> None:
    assert classify(LANE, raw_kind, body).kind == kind


def test_a_tool_use_and_its_result_name_the_same_call() -> None:
    use = event("agent.tool_use", name="read")
    assert frames.tool_call_ref("agent.tool_use", use) == use["id"]
    result = event("agent.tool_result", tool_use_id=use["id"])
    assert frames.tool_call_ref("agent.tool_result", result) == use["id"]
    custom = event("agent.custom_tool_use", name="mc_signal")
    answer = event("user.custom_tool_result", custom_tool_use_id=custom["id"])
    assert frames.tool_call_ref("user.custom_tool_result", answer) == custom["id"]
    assert frames.tool_call_ref("agent.message", event("agent.message")) is None
