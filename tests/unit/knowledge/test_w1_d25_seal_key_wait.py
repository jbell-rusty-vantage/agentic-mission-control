"""W1 D25 (OVE-169): a seal KS cannot sign (its seal key is not registered) is an actionable wait.

Offline: the in-memory trusted world of ``test_trusted_judgment``. KS refuses ``report.seal`` with
``CAPABILITY_UNAVAILABLE`` / ``seal_key_unregistered`` naming the key id (the remotes' state before
the installers' ``seal-key`` step). The pass raises a typed refusal that the settlement records as
``settlement_unavailable`` with the reason, KS's message and the operator action; the next pass,
after the key is registered, recovers every evaluator's observation from KS (no paid evaluator
runs again, no second observation) and seals. The HTTP client never re-sends a ``report.seal``
``invoke``, even on ``503`` with ``Retry-After``.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from mission_control.adapters.knowledge.http_client import HttpKnowledgeBindingClient
from mission_control.application.knowledge.judgment import TrustedJudgmentRefused
from mission_control.application.ports.knowledge import KnowledgeProtocolRefusal
from mission_control.contracts.knowledge_protocol import OperationEnvelope
from mission_control.contracts.knowledge_protocol_results import protocol_error
from mission_control.domain.execution.invocation_settlement import SettlementOutcome, WaitReason
from tests.unit.knowledge.test_http_client import VECTORS
from tests.unit.knowledge.test_trusted_judgment import ScriptedRunner, evaluators, world

pytestmark = pytest.mark.asyncio

KEY_ID = "ks-seal-0a1b2c3d"
UNREGISTERED = (
    "CAPABILITY_UNAVAILABLE",
    f"SEAL_KEY_UNREGISTERED: seal key {KEY_ID} is not registered in "
    "knowledge_verification.seal_signing_key",
    "seal_key_unregistered",
)


async def test_an_unregistered_seal_key_waits_and_the_next_pass_never_reruns_evaluators() -> None:
    w, subject = await world(review_required=False)
    host, use = w.stack.access, w.use()
    w.ks.seal_refusal = UNREGISTERED
    first = ScriptedRunner({"judge": "full_support"})
    with pytest.raises(TrustedJudgmentRefused) as refused:
        await w.bridge(first).assess(subject, evaluators(w), host, use)
    assert first.calls == ["judge", "auditor"]  # each paid evaluator ran once
    error = refused.value
    assert (error.code, error.reason, error.billed) == (
        "CAPABILITY_UNAVAILABLE",
        "seal_key_unregistered",
        False,
    )
    assert KEY_ID in error.issues[0]
    assert error.issues[1].startswith("operator: register the KS executor's seal key")

    # The settlement wait names the reason, the key id and the action (W1 D20 detail).
    outcome = SettlementOutcome.unavailable(error)
    assert outcome.state == "waiting" and outcome.reason == WaitReason.SETTLEMENT_UNAVAILABLE
    assert outcome.detail["code"] == "CAPABILITY_UNAVAILABLE"
    assert outcome.detail["reason"] == "seal_key_unregistered"
    assert any(KEY_ID in issue for issue in outcome.detail["issues"])

    # The operator registers the key; the next pass recovers both observations and seals.
    w.ks.seal_refusal = None
    again = ScriptedRunner({"judge": "full_support"})
    passed = await w.bridge(again).assess(subject, evaluators(w), host, use)
    assert again.calls == []  # no paid evaluator ran again
    observes = [call for call in w.ks.calls if call[0] == "report.observe"]
    assert sorted(role for _, role, _ in observes) == ["auditor", "judge"]  # once each
    assert w.ks.gets  # recovered from KS by operation.get (unbilled)
    seals = [call for call in w.ks.calls if call[0] == "report.seal"]
    assert len(seals) == 2  # the refused seal, then the one that signed
    assert passed.result == "pass" and passed.promoted
    assert set(passed.locked_roles) == {"judge", "auditor"}


async def test_other_seal_refusals_pass_through_unchanged() -> None:
    w, subject = await world(review_required=False)
    host, use = w.stack.access, w.use()
    w.ks.seal_refusal = (
        "CAPABILITY_UNAVAILABLE",
        "no seal key configured",
        "seal_key_unconfigured",
    )
    with pytest.raises(TrustedJudgmentRefused) as refused:
        await w.bridge(ScriptedRunner({"judge": "full_support"})).assess(
            subject, evaluators(w), host, use
        )
    # `seal_key_unconfigured` is the executor's own configuration, also a seal_key_* gap.
    assert refused.value.reason == "seal_key_unconfigured"
    assert refused.value.issues[1].startswith("operator:")
    w.ks.seal_refusal = ("EXACT_REVISION_UNAVAILABLE", "unknown revision", "revision_unavailable")
    with pytest.raises(TrustedJudgmentRefused) as other:
        await w.bridge(ScriptedRunner({"judge": "full_support"})).assess(
            subject, evaluators(w), host, use
        )
    assert other.value.code == "EXACT_REVISION_UNAVAILABLE" and other.value.issues == ()


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> HttpKnowledgeBindingClient:
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    return HttpKnowledgeBindingClient(
        "http://ks.test", transport=httpx.MockTransport(handler), sleep=sleep
    )


async def test_report_seal_invoke_is_never_resent_by_the_http_client() -> None:
    posts: list[str] = []
    error = protocol_error(
        "CAPABILITY_UNAVAILABLE", UNREGISTERED[1], occurred_at="2026-10-29T10:00:00Z"
    ).model_copy(update={"details": {"reason": "seal_key_unregistered", "keyId": KEY_ID}})

    def handler(request: httpx.Request) -> httpx.Response:
        posts.append(request.method)
        return httpx.Response(503, headers={"Retry-After": "1"}, json=error.model_dump(mode="json"))

    http = _client(handler)
    envelope = OperationEnvelope.model_validate(VECTORS["apply-envelope"]["envelope"])
    seal = envelope.model_copy(update={"operation": "report.seal"})
    minted = iter(f"token-{n}" for n in range(5))
    # Even with a fresh credential per transmission available, invoke is sent exactly once.
    with pytest.raises(KnowledgeProtocolRefusal) as refused:
        await http.invoke(seal, lambda: next(minted))  # type: ignore[arg-type]
    assert posts == ["POST"]
    assert refused.value.error.details == {"reason": "seal_key_unregistered", "keyId": KEY_ID}
