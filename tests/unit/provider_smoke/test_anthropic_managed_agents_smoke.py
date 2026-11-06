from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from scripts.provider_smoke.anthropic_managed_agents import SessionDriver
from scripts.provider_smoke.common import (
    LONG_TURN_PROMPT,
    MIDTURN_ACK,
    MIDTURN_MESSAGE,
    SmokeRecord,
)


class FakeEvents:
    """`client.beta.sessions.events`: records sends and returns server-assigned event ids."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def send(self, session_id: str, *, events: list[dict[str, Any]]) -> SimpleNamespace:
        assert session_id == "sesn_1"
        self.sent.extend(events)
        return SimpleNamespace(data=[SimpleNamespace(id=f"sevt_sent_{len(self.sent)}")])


def _driver() -> tuple[SessionDriver, FakeEvents]:
    events = FakeEvents()
    client: Any = SimpleNamespace(beta=SimpleNamespace(sessions=SimpleNamespace(events=events)))
    record = SmokeRecord(provider="anthropic_managed_agents", sdk="sdk", model="m")
    return SessionDriver(client=client, session_id="sesn_1", record=record), events


def ev(event_type: str, event_id: str, **fields: Any) -> SimpleNamespace:
    fields.setdefault("processed_at", None)
    return SimpleNamespace(type=event_type, id=event_id, **fields)


def idle(event_id: str, stop_reason: str) -> SimpleNamespace:
    return ev("session.status_idle", event_id, stop_reason=SimpleNamespace(type=stop_reason))


def text(event_id: str, body: str) -> SimpleNamespace:
    return ev("agent.message", event_id, content=[SimpleNamespace(type="text", text=body)])


def _first_turn_until_midturn(driver: SessionDriver) -> None:
    # History replay (events emitted before the stream opened), then the live stream.
    for event in (
        ev("session.status_running", "e1"),
        ev("user.message", "e0", processed_at="t0"),
        ev("agent.custom_tool_use", "e2", name="mc_signal", input={"name": "smoke.start"}),
        ev("agent.custom_tool_use", "e2", name="mc_signal", input={"name": "smoke.start"}),
        idle("e3", "requires_action"),
        ev("session.status_running", "e4"),
    ):
        driver.handle(event)


def test_mid_turn_message_is_sent_after_running_resumes_and_classified_injected() -> None:
    driver, events = _driver()
    _first_turn_until_midturn(driver)

    assert [event["type"] for event in events.sent] == ["user.custom_tool_result", "user.message"]
    assert events.sent[0]["custom_tool_use_id"] == "e2"  # answered once despite the replay
    assert events.sent[1]["content"][0]["text"] == MIDTURN_MESSAGE
    assert driver.midturn_event_id == "sevt_sent_2"

    for event in (
        ev("user.message", "sevt_sent_2"),  # queued echo
        ev("user.message", "sevt_sent_2", processed_at="t5"),  # consumed
        text("e6", f"counts 4 3 5 {MIDTURN_ACK}"),
        idle("e7", "end_turn"),
    ):
        driver.handle(event)
    assert events.sent[-1]["content"][0]["text"] == LONG_TURN_PROMPT

    for event in (
        ev("span.model_request_start", "e8"),
        ev("span.model_request_start", "e9"),
        idle("e10", "end_turn"),
    ):
        driver.handle(event)
    driver.summarize()

    assert [event["type"] for event in events.sent][-1] == "user.interrupt"
    assert sum(event["type"] == "user.interrupt" for event in events.sent) == 1
    assert driver.done
    findings = driver.record.findings
    assert findings["q_m1_verdict"] == "injected_mid_turn"
    assert findings["midturn_ack_in_same_turn"] is True
    assert findings["interrupt_stop_reason"] == "end_turn"
    assert findings["agent_messages_after_interrupt"] == 0
    assert driver.record.event_counts["agent.custom_tool_use"] == 1


def test_mid_turn_message_consumed_after_the_turn_is_classified_queued() -> None:
    driver, events = _driver()
    _first_turn_until_midturn(driver)

    driver.handle(idle("e6", "end_turn"))
    assert driver.phase == "first"  # waits for the queued message before the second phase
    assert len(events.sent) == 2

    driver.handle(ev("user.message", "sevt_sent_2", processed_at="t7"))
    driver.handle(text("e8", MIDTURN_ACK))
    driver.handle(idle("e9", "end_turn"))
    driver.summarize()

    assert driver.phase == "second"
    assert driver.record.findings["q_m1_verdict"] == "queued_until_turn_end"
    assert driver.record.findings["midturn_ack_in_same_turn"] is False


def test_unexpected_ask_is_denied_and_a_budget_stop_ends_the_script() -> None:
    driver, events = _driver()
    driver.handle(ev("agent.tool_use", "e1", evaluated_permission="ask"))
    driver.handle(idle("e2", "budget_reached"))

    assert events.sent == [
        {"type": "user.tool_confirmation", "tool_use_id": "e1", "result": "deny"}
    ]
    assert driver.done
    assert driver.record.findings["terminal_stop_reason"] == "budget_reached"
