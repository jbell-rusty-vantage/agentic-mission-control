"""Agents API closing facts from saved items and root turn records, never deltas.

Shapes follow openai 3.29.0 and SPEC-06 section 5.2. Event ids identify live
notifications; item ids identify the durable history restored after disconnect.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mission_control.domain.execution.lane_turns import MAX_EXCERPT_CHARS, ClosingFacts
from mission_control.domain.execution.lanes import UsageReport

PREFIX = "agent.session."
ITEM_DONE = PREFIX + "turn.item.done"
TURN_FINAL = "turn.final"
TERMINAL = frozenset({"completed", "failed", "cancelled"})
TERMINAL_EVENTS = frozenset(PREFIX + "turn." + value for value in TERMINAL)
ENVIRONMENT_EVENTS = frozenset(
    PREFIX + "environment." + value
    for value in (
        "pending",
        "ready",
        "connected",
        "disconnected",
        "failed",
        "suspended",
        "expired",
        "reset",
    )
)


def mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def root_turn(body: Mapping[str, Any], turn_id: str) -> bool:
    turn = mapping(body.get("turn"))
    return body.get("turn_id", turn.get("id")) == turn_id and turn.get("subagent_id") is None


def final_text(items: Mapping[str, Mapping[str, Any]]) -> str:
    answers = []
    for item in items.values():
        if (
            item.get("type") == "message"
            and item.get("role") == "assistant"
            and item.get("status") == "completed"
            and item.get("phase") == "final_answer"
        ):
            answers.append(
                "".join(
                    str(part.get("text") or "")
                    for part in item.get("content") or []
                    if isinstance(part, Mapping) and part.get("type") == "output_text"
                )
            )
    return "\n\n".join(answers)


def usage_report(turn: Mapping[str, Any]) -> UsageReport:
    usage = mapping(turn.get("usage"))
    values = [usage.get(key) for key in ("input_tokens", "output_tokens", "total_tokens")]
    if not all(
        isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in values
    ):
        return UsageReport(disposition="unknown")
    return UsageReport(
        disposition="settled",
        input_tokens=values[0],
        output_tokens=values[1],
        total_tokens=values[2],
    )


def closing_facts(body: Mapping[str, Any]) -> ClosingFacts:
    turn = mapping(body.get("turn")) or dict(body)
    status = {"completed": "finished", "failed": "error", "cancelled": "cancelled"}.get(
        str(turn.get("status"))
    )
    error = mapping(turn.get("error"))
    return ClosingFacts(
        native_status=status or "in_doubt",
        result_excerpt=str(body.get("result") or "")[:MAX_EXCERPT_CHARS],
        usage=usage_report(turn),
        cost_disposition="unknown",
        error_code=str(error.get("code"))[:128] if error.get("code") else None,
    )
