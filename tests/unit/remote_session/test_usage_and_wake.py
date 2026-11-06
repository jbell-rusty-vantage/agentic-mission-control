"""HL-04: usage settled only when reported, and provider webhooks reduced to wake-ups."""

from __future__ import annotations

from mission_control.adapters.remote_session.usage import (
    SNAKE_CASE_TOKENS,
    TokenFields,
    reported_usage,
)
from mission_control.adapters.remote_session.wake import SessionWake, session_wake


def test_unreported_usage_stays_unknown_never_zero() -> None:
    assert reported_usage(None).disposition == "unknown"
    assert reported_usage({}).disposition == "unknown"
    unknown = reported_usage(None, cost_micros_usd=5)
    assert unknown.cost_micros_usd is None, "a cost without tokens settles nothing"


def test_reported_tokens_settle_under_the_providers_field_names() -> None:
    settled = reported_usage({"input_tokens": 10, "output_tokens": 5, "total_tokens": 20})
    assert settled.disposition == "settled"
    assert (settled.input_tokens, settled.output_tokens, settled.total_tokens) == (10, 5, 20)
    assert settled.cost_micros_usd is None
    camel = TokenFields(input="inputTokens", output="outputTokens", total="totalTokens")
    summed = reported_usage(
        {"inputTokens": 3, "outputTokens": None}, fields=camel, cost_micros_usd=1_200
    )
    assert (summed.input_tokens, summed.output_tokens, summed.total_tokens) == (3, 0, 3)
    assert summed.cost_micros_usd == 1_200
    assert TokenFields() == SNAKE_CASE_TOKENS


def test_a_wake_keeps_the_event_type_and_resource_id_only() -> None:
    payload = {"type": "session.status_idled", "id": "sess-1", "status": "done", "usage": {}}
    wake = session_wake("claude_cloud", "msg-1", payload)
    assert wake == SessionWake(
        lane_profile="claude_cloud",
        delivery_id="msg-1",
        event_type="session.status_idled",
        resource_ref="sess-1",
    )


def test_the_resource_id_is_read_where_the_provider_documents_it() -> None:
    nested = {"type": "agent.session.idle", "id": "evt-1", "data": {"id": "sess-9"}}
    wake = session_wake("codex_cloud", "d-1", nested, id_path=("data", "id"))
    assert wake is not None and wake.resource_ref == "sess-9"
    assert (
        session_wake("codex_cloud", "d-1", {"type": "x", "data": "flat"}, id_path=("data", "id"))
        is None
    )


def test_a_payload_without_a_type_or_resource_wakes_nothing() -> None:
    assert session_wake("claude_cloud", "d", {"id": "sess-1"}) is None
    assert session_wake("claude_cloud", "d", {"type": "", "id": "sess-1"}) is None
    assert session_wake("claude_cloud", "d", {"type": "x", "id": 7}) is None
    assert session_wake("claude_cloud", "d", {"type": "x"}) is None
