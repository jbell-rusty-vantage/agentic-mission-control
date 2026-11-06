from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest
from scripts.provider_smoke import common
from scripts.provider_smoke.common import (
    RUN_LABEL,
    SKILL_NAME,
    CleanupLedger,
    SmokeRecord,
    agents_md_verdict,
    gpt_6_luna_cost_usd,
    mid_turn_delivery,
    placeholder_credential_auth,
    record_path,
    retry_on_conflict,
    skill_files,
)


@pytest.mark.parametrize(
    ("timeline", "verdict"),
    [
        (["sent", "processed", "turn_end"], "injected_mid_turn"),
        (["sent", "turn_end", "processed", "turn_end"], "queued_until_turn_end"),
        (["turn_end", "sent", "processed", "turn_end"], "injected_mid_turn"),
        (["sent", "turn_end"], "not_observed"),
        (["turn_end"], "not_sent"),
    ],
)
def test_mid_turn_delivery_reads_the_order_after_the_send(
    timeline: list[str], verdict: str
) -> None:
    assert mid_turn_delivery(timeline) == verdict


def test_agents_md_counts_only_when_no_tool_read_the_file() -> None:
    assert agents_md_verdict(canary_in_answer=True, commands_run=0) == "honoured_in_context"
    assert agents_md_verdict(canary_in_answer=True, commands_run=2) == "read_with_tools"
    assert agents_md_verdict(canary_in_answer=False, commands_run=0) == "not_honoured"


def test_gpt_6_luna_estimate_applies_token_rates_and_the_container_minimum() -> None:
    # 1M uncached input + 1M output tokens, three minutes of a small container (5-minute floor).
    cost = gpt_6_luna_cost_usd(
        input_tokens=1_000_000, cached_tokens=0, output_tokens=1_000_000, container_minutes=3
    )
    assert cost == pytest.approx(0.10 + 0.50 + 5 * 0.03 / 20)
    cached = gpt_6_luna_cost_usd(
        input_tokens=1_000_000, cached_tokens=1_000_000, output_tokens=0, container_minutes=20
    )
    assert cached == pytest.approx(0.01 + 0.03)


def test_skill_bundle_and_credential_carry_no_secret_and_the_run_label() -> None:
    [(path, body, media_type)] = skill_files()
    assert path == f"{SKILL_NAME}/SKILL.md"
    assert media_type == "text/markdown"
    assert body.decode().startswith(f"---\nname: {SKILL_NAME}\n")
    assert RUN_LABEL.lower() in SKILL_NAME
    auth = placeholder_credential_auth()
    assert auth["type"] == "environment_variable"
    assert "not-a-secret" in str(auth["secret_value"])


def test_cleanup_runs_in_reverse_and_survives_a_failure(capsys: pytest.CaptureFixture[str]) -> None:
    record = SmokeRecord(provider="p", sdk="sdk", model="m")
    ledger = CleanupLedger(record)
    order: list[str] = []

    def fail() -> None:
        order.append("agent")
        raise RuntimeError("busy")

    ledger.add("skill", "skill_1", "deleted", lambda: order.append("skill"))
    ledger.add("agent", "agent_1", "archived", fail)
    ledger.add("session", "sesn_1", "deleted", lambda: order.append("session"))
    ledger.run()

    assert order == ["session", "agent", "skill"]
    assert record.cleanup == {
        "session sesn_1": "deleted",
        "agent agent_1": "archived failed: RuntimeError",
        "skill skill_1": "deleted",
    }
    assert record.errors == ["cleanup agent: RuntimeError: busy"]
    printed = capsys.readouterr().out.splitlines()
    assert "cleanup session sesn_1 deleted" in printed
    ledger.run()  # idempotent: nothing left to clean
    assert order == ["session", "agent", "skill"]


def test_record_scrubs_key_shaped_text_and_prints_only_ids(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    record = SmokeRecord(provider="p", sdk="sdk", model="m")

    class AuthError(Exception):
        status_code = 401

    record.error("agent", AuthError("Incorrect API key provided: sk-proj-****abcd"))
    record.created("agent", "agent_1")
    record.saw("agent.session.idle")
    record.saw("agent.session.idle")

    assert record.errors == ["agent: AuthError 401: Incorrect API key provided: [redacted]"]
    out = capsys.readouterr().out
    assert "sk-" not in out
    assert out.splitlines() == ["agent - error AuthError 401", "agent agent_1 created"]

    path = record_path(str(tmp_path / "evidence" / "smoke.json"))
    record.write(path)
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["resources"] == {"agent": "agent_1"}
    assert written["event_counts"] == {"agent.session.idle": 2}
    assert written["sequence"] == ["agent.session.idle"]


class _HTTPError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


def test_retry_on_conflict_retries_409_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(common.time, "sleep", lambda _s: None)
    outcomes: list[Exception | str] = [_HTTPError(409), _HTTPError(409), "deleted"]

    def flaky() -> str:
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    assert retry_on_conflict(flaky) == "deleted"
    with pytest.raises(_HTTPError, match="400"):
        retry_on_conflict(lambda: (_ for _ in ()).throw(_HTTPError(400)))
    with pytest.raises(_HTTPError, match="409"):
        retry_on_conflict(lambda: (_ for _ in ()).throw(_HTTPError(409)), attempts=2)


def test_record_path_requires_json_and_prepares_its_directory(tmp_path: Path) -> None:
    path = record_path(str(tmp_path / "new" / "smoke.json"))
    assert path.parent.is_dir()
    with pytest.raises(argparse.ArgumentTypeError, match="json"):
        record_path("")
