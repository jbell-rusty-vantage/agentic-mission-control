"""Bounded, non-text lifecycle evidence retained when a native body exceeds its excerpt.

Only known protocol enums and booleans survive. Prompts, results, arbitrary error messages,
URLs and provider metadata never enter this projection. The writer reads the *redacted
canonical body*, not a partial JSON excerpt. Unknown provider vocabulary stays unavailable.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

MAX_LIFECYCLE_BODY_BYTES = 4_096
LIFECYCLE_BODY_KINDS = frozenset({"run_result", "turn_ended", "error"})
_SUCCESS = frozenset({"finished", "completed", "succeeded", "success", "end_turn"})
_ERROR = frozenset({"error", "failed", "failure"})
_STATUS = (
    _SUCCESS
    | _ERROR
    | {
        "expired",
        "timeout",
        "timed_out",
        "cancelled",
        "canceled",
        "interrupted",
        "aborted",
        "unknown",
        "running",
        "creating",
        "pending",
        "idle",
        "inprogress",
        "agent_busy",
        "409",
        "429",
        "rate_limited",
        "session_token_limit_reached",
    }
)
_CODES = frozenset(
    {
        "agent_busy",
        "409",
        "429",
        "529",
        "rate_limited",
        "session_token_limit_reached",
        "provider_error",
        "capacity",
        "timeout",
        "cancelled_by_command",
        "max_turns",
        "process_exit",
        "worker_lost",
        "stream_gap",
        "aborted_streaming",
        "aborted_tools",
    }
)
_SUBTYPES = frozenset(
    {
        "success",
        "error_during_execution",
        "error_max_turns",
        "error_max_budget_usd",
        "error_max_structured_output_retries",
        "error_json_decode",
        "error_unknown",
    }
)
_ENUM_FIELDS = {
    "status": _STATUS,
    "outcome": _STATUS,
    # Some lanes use result as a status; prose/JSON completion candidates are excluded.
    "result": _STATUS,
    "subtype": _SUBTYPES,
    "type": frozenset({"turn.completed", "turn.failed"}),
    "terminal_reason": _CODES | _STATUS,
    "error_code": _CODES,
    "code": _CODES,
    "error_type": _CODES,
    "stop_reason": _STATUS,
    "synthesized_from": frozenset({"run_record", "process_exit"}),
}
_FLAGS = frozenset({"is_error", "session_ended", "unknown_state"})


def lifecycle_body(value: Any) -> dict[str, Any]:
    """Extract known scalar protocol fields, preserving their native payload shape."""
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, Any] = {}
    for key, allowed in _ENUM_FIELDS.items():
        item = value.get(key)
        if (isinstance(item, str) and item.lower() in allowed) or (
            key in {"code", "error_code"} and type(item) is int and str(item) in allowed
        ):
            result[key] = item
    for key in _FLAGS:
        if type(value.get(key)) is bool:
            result[key] = value[key]
    api_status = value.get("api_error_status")
    if type(api_status) is int and 100 <= api_status <= 599:
        result["api_error_status"] = api_status
    for key in ("turn", "error"):
        nested = value.get(key)
        if isinstance(nested, Mapping):
            # Exactly one turn/error nesting level; no arbitrary recursive payloads.
            selected = {
                name: nested[name]
                for name in ("status", "code", "error_code", "error_type", "terminal_reason")
                if name in nested
            }
            bounded = lifecycle_body(selected)
            if key == "turn" and isinstance(nested.get("error"), Mapping):
                error = lifecycle_body({"error": nested["error"]}).get("error")
                if error:
                    bounded["error"] = error
            if bounded:
                result[key] = bounded
    return result


def validate_lifecycle_body(value: Mapping[str, Any]) -> None:
    """Reject text/unknown fields and contradictory success/error flags at ingestion."""
    if lifecycle_body(value) != value:
        raise ValueError("lifecycle body contains unsupported fields or values")
    statuses = {
        item.lower()
        for name in ("status", "outcome", "result", "subtype")
        if isinstance(item := value.get(name), str)
    }
    success = bool(statuses & _SUCCESS)
    failed = bool(statuses & _ERROR) or any(item.startswith("error_") for item in statuses)
    if (success and (failed or value.get("is_error") is True)) or (
        failed and value.get("is_error") is False
    ):
        raise ValueError("lifecycle body has inconsistent success/error flags")
