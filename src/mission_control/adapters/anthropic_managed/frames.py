"""`claude_managed` frames: Managed Agents session events as one turn's lane frames.

A Managed Agents session is one event log shared by every turn (SPEC-06 section 4.2). Events
carry an `id` and a `processed_at` (a client-sent event appears on the stream twice, queued
with `processed_at` null, then processed) and no sequence number; the event list is ordered by
`processed_at` (anthropic 1.13.0 `EventListParams`). This module reads that log for one turn:

- the turn is the `user.message` the lane sent (its event id is the native turn ref); it starts
  when that message is processed, so earlier events (the previous turn's tail, the queued echo)
  belong to no frame of this turn;
- `TurnFold` correlates what closes the turn: a `session.status_idle` whose stop reason ends a
  turn (`end_turn`, `retries_exhausted`, `refusal`) or `session.status_terminated`. `end_turn`
  also follows an interrupt (HL-23), so an interrupt processed inside the turn, or sent by the
  lane for it, makes the close `cancelled`. With multiagent on (read-only knowledge missions,
  DECISIONS R33) an idle is not the end while a `workflow_run` is open: that idle is stored as
  `session.status_idle.runs_open`. `requires_action` and `budget_reached` idles wait (an
  approval, a budget gate) and close nothing;
- usage: the turn's tokens are the sum of its `span.model_request_end.model_usage` (cache
  reads and writes are input), its cost the `session.usage.list_cost` (USD minor units)
  reached at its close less the one reached before it started. Cost is settled only from
  `list_cost`; nothing reported stays `unknown`;
- `span.outcome_evaluation_end` (`user.define_outcome`) is evidence recorded with the close,
  never acceptance (R33);
- positions: a stored event is keyed `managed:<turn>:<processed_at micros>.<event id>`, and the
  same position is the resume cursor `<turn>@<micros>.<id>`, so a persisted frame key alone is
  where a reattached segment resumes (history from the turn's start, folded again and stored
  only after that position).

`closing_facts` reads the turn summary the lane writes on the closing frame (`mc_turn`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from mission_control.adapters.remote_session.stream import STREAM_START
from mission_control.application.frames.kinds import bounded_key
from mission_control.domain.execution.lane_turns import MAX_EXCERPT_CHARS, ClosingFacts
from mission_control.domain.execution.lanes import UsageReport

KEY_PREFIX: Final = "managed"
SUMMARY_KEY: Final = "mc_turn"
# The closing frame synthesized from the event history when the stream ended without one.
TURN_FINAL: Final = "turn.final"
RUNS_OPEN_IDLE: Final = "session.status_idle.runs_open"
TERMINATED: Final = "session.status_terminated"
IDLE: Final = "session.status_idle"
# Stop reasons that end the turn; `requires_action` and `budget_reached` wait instead.
ENDING_STOP_REASONS: Final = frozenset({"end_turn", "retries_exhausted", "refusal"})
WAITING_STOP_REASONS: Final = frozenset({"requires_action", "budget_reached"})
# A minor unit (a US cent) of `list_cost` in micro-dollars.
MINOR_UNIT_MICROS: Final = 10_000
_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)


def processed_micros(processed_at: str) -> int:
    """`processed_at` (ISO 8601) as integer microseconds since the epoch: a position that
    sorts like the provider's ordering and holds no `:`."""

    moment = datetime.fromisoformat(processed_at.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return (moment - _EPOCH) // timedelta(microseconds=1)


def processed_iso(micros: int) -> str:
    """The `created_at[...]` filter value of a position (the filter compares `processed_at`)."""

    return (_EPOCH + timedelta(microseconds=micros)).isoformat().replace("+00:00", "Z")


def event_position(body: Mapping[str, Any]) -> str | None:
    """`<processed_at micros>.<event id>` of a processed event; None for a queued or id-less
    one (an interrupt may carry an empty id)."""

    event_id = body.get("id")
    processed_at = body.get("processed_at")
    if not event_id or not isinstance(processed_at, str):
        return None
    return f"{processed_micros(processed_at)}.{event_id}"


def parse_position(position: str) -> tuple[int, str] | None:
    micros, separator, event_id = position.partition(".")
    if not separator or not micros.isdigit() or not event_id:
        return None
    return int(micros), event_id


@dataclass(frozen=True)
class ManagedEventCursors:
    """The `StreamCursorCodec` of a Managed Agents turn: `<turn>@<position>` cursors and
    `managed:<turn>:<position>` frame keys (see the module doc)."""

    def cursor(self, turn_ref: str, event_id: str) -> str:
        return f"{turn_ref}@{event_id}"

    def resume_point(self, cursor: str | None, turn_ref: str) -> str | None:
        if cursor is None or cursor == STREAM_START:
            return None
        turn, separator, position = cursor.partition("@")
        if not separator or turn != turn_ref or parse_position(position) is None:
            return None
        return position

    def provider_key(self, turn_ref: str | None, event_id: str) -> str:
        return bounded_key(KEY_PREFIX, turn_ref, event_id)

    def resume_cursor(self, provider_key: str) -> str | None:
        prefix = f"{KEY_PREFIX}:"
        if not provider_key.startswith(prefix):
            return None
        turn, separator, position = provider_key.removeprefix(prefix).partition(":")
        if not separator or not turn or parse_position(position) is None:
            return None
        return self.cursor(turn, position)


def final_key(turn_ref: str) -> str:
    return bounded_key(KEY_PREFIX, turn_ref, "final")


def tool_call_ref(raw_kind: str, body: Mapping[str, Any]) -> str | None:
    """The tool use a frame starts or closes: built-in, MCP and custom tool uses are keyed by
    their event id; results and confirmations name it."""

    if raw_kind in {"agent.tool_use", "agent.mcp_tool_use", "agent.custom_tool_use"}:
        return _text(body.get("id"))
    if raw_kind in {"agent.tool_result", "agent.mcp_tool_result", "user.tool_confirmation"}:
        return _text(body.get("tool_use_id"))
    if raw_kind == "user.custom_tool_result":
        return _text(body.get("custom_tool_use_id"))
    return None


def stop_reason(body: Mapping[str, Any]) -> str | None:
    reason = body.get("stop_reason")
    return _text(reason.get("type")) if isinstance(reason, Mapping) else None


def list_cost_minor_units(usage: Mapping[str, Any] | None) -> int | None:
    """`list_cost.amount` (an integer string in USD minor units) of a usage snapshot."""

    cost = usage.get("list_cost") if isinstance(usage, Mapping) else None
    if not isinstance(cost, Mapping) or str(cost.get("currency") or "USD") != "USD":
        return None
    amount = str(cost.get("amount") or "")
    return int(amount) if amount.isdigit() else None


@dataclass
class TurnFold:
    """What one turn's events say so far (see the module doc); `observe` folds one event and
    names the raw kind it is stored under, or None when it is not this turn's."""

    turn_ref: str
    interrupted: bool = False
    started_at: str | None = None
    open_runs: set[str] = field(default_factory=set)
    tokens: dict[str, int] = field(default_factory=dict)
    list_cost: int | None = None
    result: str = ""
    outcome: dict[str, Any] | None = None
    error: dict[str, Any] | None = None

    @property
    def started(self) -> bool:
        return self.started_at is not None

    def observe(self, body: Mapping[str, Any]) -> str | None:
        kind = _text(body.get("type"))
        if kind is None:
            return None  # a keep-alive
        if not self.started:
            if kind == "user.message" and body.get("id") == self.turn_ref:
                self.started_at = _text(body.get("processed_at"))
                return kind if self.started else None
            return None
        processed = body.get("processed_at") is not None
        if kind == "user.interrupt" and processed:
            self.interrupted = True
        elif kind == "span.model_request_end":
            usage = body.get("model_usage")
            if isinstance(usage, Mapping):
                for name, value in usage.items():
                    if isinstance(value, int) and not isinstance(value, bool):
                        self.tokens[name] = self.tokens.get(name, 0) + value
        elif kind == "session.usage":
            reported = list_cost_minor_units(_mapping(body.get("usage")))
            if reported is not None:
                self.list_cost = reported
        elif kind == "agent.message":
            self.result = _message_text(body) or self.result
        elif kind == "workflow_run.created" and body.get("workflow_run_id"):
            self.open_runs.add(str(body["workflow_run_id"]))
        elif kind == "workflow_run.status_ended":
            self.open_runs.discard(str(body.get("workflow_run_id")))
        elif kind == "span.outcome_evaluation_end":
            self.outcome = {name: body.get(name) for name in ("outcome_id", "result", "iteration")}
        elif kind == "session.error":
            self.error = _mapping(body.get("error"))
        elif kind == IDLE and stop_reason(body) in ENDING_STOP_REASONS and self.open_runs:
            return RUNS_OPEN_IDLE
        return kind

    def closes(self, raw_kind: str, body: Mapping[str, Any]) -> bool:
        return raw_kind == TERMINATED or (
            raw_kind == IDLE and stop_reason(body) in ENDING_STOP_REASONS
        )

    def summary(self, raw_kind: str, body: Mapping[str, Any]) -> dict[str, Any]:
        """The closing facts of the turn at its closing event (`mc_turn` on that frame);
        `list_cost` is the session's cumulative cost, the lane subtracts the turn's start."""

        reason = "terminated" if raw_kind == TERMINATED else stop_reason(body)
        if reason == "end_turn":
            status = "cancelled" if self.interrupted else "finished"
        else:
            status = "error"
        summary: dict[str, Any] = {
            "status": status,
            "stop_reason": reason,
            "interrupted": self.interrupted,
            "result": self.result,
            "usage": dict(sorted(self.tokens.items())) or None,
            "list_cost": self.list_cost,
            "started_at": self.started_at,
        }
        if self.outcome is not None:
            summary["outcome"] = self.outcome
        if self.error is not None:
            summary["error"] = self.error
        return summary


def turn_usage(summary: Mapping[str, Any]) -> UsageReport:
    """Settled tokens when the turn reported model usage, its cost when `list_cost` did."""

    usage = _mapping(summary.get("usage"))
    if not usage:
        return UsageReport(disposition="unknown")
    input_tokens = sum(
        int(usage.get(name) or 0)
        for name in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
    )
    output_tokens = int(usage.get("output_tokens") or 0)
    cost = summary.get("list_cost_minor_units")
    return UsageReport(
        disposition="settled",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        cost_micros_usd=cost * MINOR_UNIT_MICROS if isinstance(cost, int) else None,
    )


def closing_facts(body: Mapping[str, Any]) -> ClosingFacts:
    summary = _mapping(body.get(SUMMARY_KEY))
    status = summary.get("status")
    if status not in {"finished", "cancelled", "error"}:
        return ClosingFacts(native_status="in_doubt", error_code="turn_summary_missing")
    usage = turn_usage(summary)
    error = _mapping(summary.get("error"))
    reason = summary.get("stop_reason")
    return ClosingFacts(
        native_status=status,
        result_excerpt=str(summary.get("result") or "")[:MAX_EXCERPT_CHARS],
        usage=usage,
        cost_disposition="settled" if usage.cost_micros_usd is not None else "unknown",
        error_code=(
            str(error.get("type") or reason or "provider_error")[:128]
            if status == "error"
            else None
        ),
    )


def final_text(body: Mapping[str, Any]) -> str | None:
    result = _mapping(body.get(SUMMARY_KEY)).get("result")
    return result if isinstance(result, str) and result else None


def _message_text(body: Mapping[str, Any]) -> str:
    blocks = body.get("content")
    if not isinstance(blocks, list):
        return ""
    return "".join(
        str(block.get("text") or "")
        for block in blocks
        if isinstance(block, Mapping) and block.get("type") == "text"
    )


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: Any) -> str | None:
    return str(value) if value else None


__all__ = [
    "ENDING_STOP_REASONS",
    "IDLE",
    "KEY_PREFIX",
    "MINOR_UNIT_MICROS",
    "RUNS_OPEN_IDLE",
    "SUMMARY_KEY",
    "TERMINATED",
    "TURN_FINAL",
    "WAITING_STOP_REASONS",
    "ManagedEventCursors",
    "TurnFold",
    "closing_facts",
    "event_position",
    "final_key",
    "final_text",
    "list_cost_minor_units",
    "parse_position",
    "processed_iso",
    "processed_micros",
    "stop_reason",
    "tool_call_ref",
    "turn_usage",
]
