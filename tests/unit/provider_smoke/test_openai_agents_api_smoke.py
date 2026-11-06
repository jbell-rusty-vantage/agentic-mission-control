from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from scripts.provider_smoke import common
from scripts.provider_smoke.common import (
    AGENTS_MD_CANARY,
    LONG_TURN_PROMPT,
    MIDTURN_ACK,
    MIDTURN_MESSAGE,
    CleanupLedger,
    SmokeRecord,
)
from scripts.provider_smoke.openai_agents_api import (
    CANARY_PROMPT,
    FIRST_PROMPT,
    MODEL,
    ModelRefusedError,
    SessionDriver,
    _audit_history,
    _record_usage,
    provision,
)


class Conflict(Exception):
    status_code = 409


class FakeEvents:
    """`client.beta.agents.sessions.events`: records sends; the first cancel races (409)."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.keys: set[str] = set()
        self.cancel_conflicts = 1

    def create(
        self, session_id: str, *, events: list[dict[str, Any]], idempotency_key: str
    ) -> None:
        assert session_id == "sess_1"
        assert idempotency_key not in self.keys
        self.keys.add(idempotency_key)
        if events[0]["type"] == "agent.session.input.cancel" and self.cancel_conflicts:
            self.cancel_conflicts -= 1
            raise Conflict("active session turn changed during cancellation; retry the request")
        self.sent.extend(events)


def _driver() -> tuple[SessionDriver, FakeEvents]:
    events = FakeEvents()
    sessions = SimpleNamespace(events=events)
    client: Any = SimpleNamespace(beta=SimpleNamespace(agents=SimpleNamespace(sessions=sessions)))
    record = SmokeRecord(provider="openai_agents_api", sdk="sdk", model=MODEL)
    return SessionDriver(client=client, session_id="sess_1", record=record), events


def ev(event_type: str, **fields: Any) -> SimpleNamespace:
    return SimpleNamespace(type=event_type, **fields)


def turn(event_type: str, turn_id: str, status: str = "in_progress") -> SimpleNamespace:
    return ev(event_type, turn_id=turn_id, turn=SimpleNamespace(status=status, error=None))


def assistant(body: str) -> SimpleNamespace:
    item = SimpleNamespace(type="message", role="assistant", content=[SimpleNamespace(text=body)])
    return ev("agent.session.turn.item.done", item=item)


def requires_action() -> SimpleNamespace:
    call = SimpleNamespace(type="function_call", call_id="call_1", turn_id="t1", name="mc_signal")
    return ev("agent.session.requires_action", session=SimpleNamespace(required_actions=[call]))


def _texts(events: FakeEvents) -> list[str]:
    return [
        event["input"][0]["content"][0]["text"]
        for event in events.sent
        if event["type"] == "agent.session.input.message"
    ]


def test_three_turn_script_answers_steers_reads_the_canary_and_cancels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(common.time, "sleep", lambda _s: None)
    driver, events = _driver()
    driver.start()
    command = SimpleNamespace(type="command_execution", output=".\n..\nAGENTS.md\n")
    for event in (
        turn("agent.session.turn.created", "t1"),
        requires_action(),
        requires_action(),  # the same pending call is answered once
        ev("agent.session.turn.item.done", item=command),
        assistant(f"AGENTS.md {MIDTURN_ACK}"),
        turn("agent.session.turn.completed", "t1", "completed"),
        ev("agent.session.idle"),
        turn("agent.session.turn.created", "t2"),
        assistant(AGENTS_MD_CANARY),
        turn("agent.session.turn.completed", "t2", "completed"),
        ev("agent.session.idle"),
        turn("agent.session.turn.created", "t3"),
        turn("agent.session.turn.in_progress", "t3"),
        turn("agent.session.turn.cancelled", "t3", "cancelled"),
    ):
        driver.handle(event)
    driver.summarize()

    assert _texts(events) == [FIRST_PROMPT, MIDTURN_MESSAGE, CANARY_PROMPT, LONG_TURN_PROMPT]
    [tool_result] = [e for e in events.sent if e["type"] == "agent.session.input.tool_result"]
    assert tool_result == {
        "type": "agent.session.input.tool_result",
        "turn_id": "t1",
        "call_id": "call_1",
        "success": True,
        "output": "ok",
    }
    assert events.sent[-1] == {"type": "agent.session.input.cancel"}  # retried after the 409
    assert driver.done
    findings = driver.record.findings
    assert findings["model_accepted"] is True
    assert findings["q_m1_verdict"] == "injected_mid_turn"
    assert findings["q_o2_verdict"] == "honoured_in_context"
    assert findings["agents_md_listed"] is True
    assert findings["turns_created"] == 3
    assert findings["cancelled_turn_status"] == "cancelled"


def test_a_tool_read_of_agents_md_does_not_count_as_honoured() -> None:
    driver, _events = _driver()
    driver.phase = "canary"
    read = SimpleNamespace(type="command_execution", output=f"canary {AGENTS_MD_CANARY}")
    driver.handle(ev("agent.session.turn.item.done", item=read))
    driver.handle(assistant(AGENTS_MD_CANARY))
    driver.summarize()

    assert driver.record.findings["q_o2_verdict"] == "read_with_tools"


def test_a_model_error_on_the_first_turn_stops_and_marks_the_model_refused() -> None:
    driver, _events = _driver()
    error = SimpleNamespace(code="invalid_request", message=f"The model '{MODEL}' is not available")
    failed = ev(
        "agent.session.turn.failed",
        turn_id="t1",
        turn=SimpleNamespace(status="failed", error=error),
    )
    driver.handle(failed)

    assert driver.done
    assert driver.record.findings["model_accepted"] is False
    assert driver.record.errors == [f"invalid_request: The model '{MODEL}' is not available"]


class FakeProvisionClient:
    """Skills and vault calls succeed; saving the agent refuses the model."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        skill = SimpleNamespace(id="skill_1", default_version="1", latest_version="1")
        self.skills = SimpleNamespace(
            create=lambda **_kw: skill, delete=lambda sid: self.calls.append(f"delete {sid}")
        )
        credentials = SimpleNamespace(
            create=lambda vault_id, **_kw: SimpleNamespace(id="credential_1"),
            delete=lambda cid, vault_id: self.calls.append(f"delete {cid}"),
        )
        vaults = SimpleNamespace(
            create=lambda **_kw: SimpleNamespace(id="vault_1"),
            delete=lambda vid: self.calls.append(f"delete {vid}"),
            credentials=credentials,
        )
        self.beta = SimpleNamespace(agents=SimpleNamespace(vaults=vaults, create=self._refuse))

    @staticmethod
    def _refuse(**kwargs: Any) -> None:
        assert kwargs["model"] == MODEL
        raise ValueError(f"Error code: 400 - model '{MODEL}' is not supported for agents")


def test_a_refused_model_stops_provisioning_and_cleans_up_what_was_created() -> None:
    client: Any = FakeProvisionClient()
    record = SmokeRecord(provider="openai_agents_api", sdk="sdk", model=MODEL)
    ledger = CleanupLedger(record)

    with pytest.raises(ModelRefusedError, match=MODEL):
        provision(client, record, ledger)
    ledger.run()

    assert record.findings["model_accepted"] is False
    assert "agent" not in record.resources
    assert client.calls == ["delete credential_1", "delete vault_1", "delete skill_1"]


def test_history_audit_locates_the_steer_and_usage_falls_back_to_turns() -> None:
    def message(role: str, turn_id: str, body: str, phase: str | None = None) -> SimpleNamespace:
        content = [SimpleNamespace(text=body)]
        return SimpleNamespace(
            type="message", role=role, turn_id=turn_id, phase=phase, content=content
        )

    items = [
        message("user", "t1", "go"),
        SimpleNamespace(type="function_call", turn_id="t1"),
        message("user", "t1", MIDTURN_MESSAGE),
        message("assistant", "t1", MIDTURN_ACK, phase="final_answer"),
    ]
    usage = {"input_tokens": 1000, "input_tokens_details": {"cached_tokens": 0}, "output_tokens": 0}
    turns = [
        SimpleNamespace(id="t1", usage=SimpleNamespace(model_dump=lambda mode: usage)),
        SimpleNamespace(id="t2", usage=None),
    ]
    sessions = SimpleNamespace(
        items=SimpleNamespace(list=lambda sid, order: items),
        turns=SimpleNamespace(list=lambda sid, order: turns),
        retrieve=lambda sid: SimpleNamespace(status="idle", usage=None),
    )
    client: Any = SimpleNamespace(beta=SimpleNamespace(agents=SimpleNamespace(sessions=sessions)))
    record = SmokeRecord(provider="openai_agents_api", sdk="sdk", model=MODEL)

    _audit_history(client, "sess_1", record, ["t1"])
    _record_usage(client, "sess_1", record, started=0.0)

    findings = record.findings
    assert findings["item_sequence"] == [
        "message:user",
        "function_call",
        "message:user",
        "message:assistant",
    ]
    assert findings["steer_item_in_first_turn"] is True
    assert findings["steer_item_before_final_answer"] is True
    assert findings["usage_source"] == "turns"
    assert findings["turns_with_unknown_usage"] == 1
    assert isinstance(findings["estimated_cost_usd"], float)
    assert findings["estimated_cost_usd"] >= 1000 * 0.10 / 1_000_000
