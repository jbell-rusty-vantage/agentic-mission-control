"""W1 D19 (typed registration collisions) and D20 (legible KS refusals of evaluator documents).

D19: KS answers a registration whose record id another registration holds with other content as a
typed ``EFFECT_CONFLICT`` (``details.reason = record_id_conflict``, the record and its id). Mission
Control settles the effect rejected (never ``UNRESOLVED_EFFECT``: no 24 h effect wait) and hands the
model a refusal it can act on: the record, its id and the next action.

D20: when KS refuses an evaluator's documents (the live auditor census: "the census is not a valid
discovery"), its bounded issues reach the raised refusal (so the settlement log), the settlement
wait detail and a recorded ``unavailable`` assessment whose findings name them (inspection).
"""

from __future__ import annotations

from typing import Any

import pytest

from mission_control.adapters.deep_agents.knowledge_tools import CURRENT_INVOCATION
from mission_control.application.knowledge.gateway import TrustedAnswer, refusal_issues
from mission_control.application.knowledge.judgment import TrustedJudgmentRefused
from mission_control.contracts.knowledge_protocol_results import protocol_error
from mission_control.domain.execution.invocation_settlement import SettlementOutcome, WaitReason
from mission_control.domain.knowledge.effects import JournalState
from tests.fixtures.knowledge_binding import model_report
from tests.unit.knowledge.test_knowledge_tools import lane
from tests.unit.knowledge.test_trusted_judgment import ScriptedRunner, evaluators, world

pytestmark = pytest.mark.asyncio

ISSUES = [
    f'occurrences.{index}.span.basis: Invalid input: expected "utf16-code-units-v1"'
    for index in range(30)
]


def census_refusal() -> Any:
    return protocol_error(
        "INVALID_ENVELOPE",
        "the census is not a valid discovery",
        occurred_at="2026-10-28T22:44:00Z",
        details={"reason": "observation_invalid", "issues": ISSUES},
    )


async def test_a_record_collision_is_a_typed_actionable_refusal_never_an_effect_wait() -> None:
    h = lane()
    h.fake.invoke_script.append("refuse:EFFECT_CONFLICT")
    h.fake.refusal_details = {
        "reason": "record_id_conflict",
        "record": "assertion",
        "id": "asr-report-x",
    }
    token = CURRENT_INVOCATION.set(h.live())
    try:
        refused = await h.call("report_register", {"report": model_report("report-x")}, "c-1")
    finally:
        CURRENT_INVOCATION.reset(token)
    assert refused["ok"] is False
    refusal = refused["refusal"]
    assert refusal["code"] == "EFFECT_CONFLICT" and refusal["reason"] == "record_id_conflict"
    assert (refusal["record"], refusal["id"]) == ("assertion", "asr-report-x")
    assert "new id" in refusal["next_action"]
    ((_, row),) = h.journal.rows.items()
    assert row.state is JournalState.REJECTED  # settled; nothing waits on it
    assert row.state is not JournalState.UNCERTAIN


def test_the_ks_collision_refusal_carries_no_dispatch_state_so_mc_rejects_it() -> None:
    """Review S2: KS adds ``details.dispatch`` only to knowledge.apply refusals (service.ts
    ``withDispatchState``); a report.register collision has none and its code is not one that may
    have committed, so ``_refused_after_dispatch`` settles it rejected (the branch the lane test
    above runs end to end)."""

    from mission_control.application.knowledge.gateway import (
        EFFECT_MAY_HAVE_COMMITTED,
        dispatch_state,
    )

    error = protocol_error(
        "EFFECT_CONFLICT",
        "assertion asr-1 is already registered with other content; register it under a new id",
        occurred_at="2026-10-28T22:44:00Z",
        details={"reason": "record_id_conflict", "record": "assertion", "id": "asr-1"},
    )
    assert dispatch_state(error) is None and error.code not in EFFECT_MAY_HAVE_COMMITTED


def test_surfaced_issues_are_redacted() -> None:
    """Review S3: KS issues pass the toolset's redaction before any surface."""

    details = {
        "issues": [
            "task.originalTask: postgresql://login:pw@db.example:5432/postgres is not a ref",
            "limits.tokens: Invalid input",
        ]
    }
    issues = refusal_issues(details)
    assert "postgresql://" not in issues[0] and "<redacted>" in issues[0]
    assert issues[1] == "limits.tokens: Invalid input"


def test_ks_issues_are_bounded_and_ride_in_the_refusal() -> None:
    answer = TrustedAnswer(operation="report.observe", refusal=census_refusal())
    assert answer.reason == "observation_invalid"
    assert len(answer.issues) == 20 and all(len(item) <= 300 for item in answer.issues)
    assert refusal_issues({"violations": ["section_missing:findings"]}) == (
        "section_missing:findings",
    )
    assert refusal_issues(None) == () and refusal_issues({"issues": "nope"}) == ()


async def test_a_refused_census_is_recorded_with_its_issues_and_reaches_the_wait_detail() -> None:
    w, subject = await world("ai-engineer")
    bridge = w.bridge(ScriptedRunner({"judge": "full_support"}))
    real = bridge._gateway.trusted  # type: ignore[attr-defined]

    async def trusted(operation: str, *args: Any, **kwargs: Any) -> TrustedAnswer:
        if operation == "report.observe":
            return TrustedAnswer(operation=operation, refusal=census_refusal())
        return await real(operation, *args, **kwargs)

    bridge._gateway.trusted = trusted  # type: ignore[attr-defined,method-assign]
    with pytest.raises(TrustedJudgmentRefused) as raised:
        await bridge.assess(subject, evaluators(w), w.stack.access, w.use())
    error = raised.value
    assert error.code == "INVALID_ENVELOPE" and error.reason == "observation_invalid"
    assert len(error.issues) == 20
    assert "occurrences.0.span.basis" in str(error)  # the settlement log names what KS refused

    from mission_control.application.knowledge.judgment import standing_wait

    rows = await w.stack.store.output_assessments(w.stack.access.scope, subject.run_id)
    recorded = standing_wait(rows, subject.revision)  # the refusal is the standing wait
    assert recorded is not None and recorded.result == "unavailable"
    codes = [item.code for item in recorded.findings]
    assert codes[0] == "ks_invalid_envelope" and codes.count("ks_issue") == 8
    assert recorded.findings[1].pointer == "occurrences.0.span.basis"

    outcome = SettlementOutcome.unavailable(error)
    assert outcome.reason is WaitReason.SETTLEMENT_UNAVAILABLE
    assert outcome.detail["code"] == "INVALID_ENVELOPE"
    assert outcome.detail["reason"] == "observation_invalid"
    assert len(outcome.detail["issues"]) == 20
    assert SettlementOutcome.unavailable(RuntimeError("x")).detail == {"error_type": "RuntimeError"}
