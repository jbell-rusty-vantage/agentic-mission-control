"""WI-04 / OVE-166: the Deep Agents lane's submission wiring and its saved-result settlement.

* The live invocation carries its host-bound position, pins the promise revisions at start and
  declares the promises that position owns, so the finalization iterates them.
* ``submit_output`` serves inline text, structured values and code changes for a named promise
  (the host computes the digest; a given wrong digest refuses); a run without promises refuses
  inline candidates.
* ``KnowledgeLaneSupport.settle`` consumes the finalization outcome as a typed settlement: an
  unresolved effect is an effect wait (nothing recorded), an assessment without a verdict a
  review wait, a late verdict settles; a fenced (cancelled) pass starts no assessment.
"""

from __future__ import annotations

from collections import deque
from dataclasses import replace

import pytest

from mission_control.adapters.deep_agents.knowledge_tools import CURRENT_INVOCATION
from mission_control.application.outputs.fulfillment import OutputFulfillmentService
from mission_control.application.outputs.submission_service import SubmissionService
from mission_control.domain.execution.invocation_settlement import WaitReason
from mission_control.domain.knowledge.effects import JournalState
from mission_control.domain.outputs.contracts import OutputForm
from mission_control.domain.outputs.rules import code_change_digest
from tests.fixtures.knowledge_binding import model_report
from tests.fixtures.output_contracts import InMemoryOutputContractStore
from tests.unit.knowledge.test_knowledge_tools import (
    RUN,
    TOOL_NAMES,
    _runtime_invocation,
    lane,
)
from tests.unit.outputs.scenario import (
    BASE,
    CLAIMS_SCHEMA,
    HEAD,
    REPO,
    code_change,
    host_access,
    obligation,
    promises,
    schema,
)

pytestmark = pytest.mark.asyncio
POSITION = "stage/draft"


async def _promised_lane():  # type: ignore[no-untyped-def]
    h = lane()
    contracts = InMemoryOutputContractStore()
    submissions = SubmissionService(contracts.submissions, contracts=contracts, clock=h.clock)
    toolset = replace(h.toolset, submissions=submissions)
    live = replace(h.live(), position=POSITION, obligations=())
    registered = await OutputFulfillmentService(contracts, submissions).register_promises(
        host_access(toolset.access(live).scope),
        RUN,
        promises(
            obligation("stage.summary", OutputForm.TEXT, position=POSITION),
            obligation(
                "stage.claims",
                OutputForm.STRUCTURED,
                position=POSITION,
                schema_pin=schema("claim_table@1", CLAIMS_SCHEMA),
            ),
            obligation("stage.patch", OutputForm.CODE_CHANGE, position=POSITION, repository=REPO),
            obligation("review.verdict", OutputForm.TEXT, position="stage/review"),
        ),
    )
    assert isinstance(registered, tuple)
    return h, toolset, contracts, live


async def test_lane_declares_its_positions_promises_and_submits_inline_values() -> None:
    _h, toolset, contracts, live = await _promised_lane()
    live = await toolset.begin(live)
    # Only the promises this position owns are declared for the invocation.
    assert live.obligations == ("stage.claims", "stage.patch", "stage.summary")
    text = await toolset.dispatch(
        "submit_output",
        {"obligation": "stage.summary", "items": [{"kind": "inline", "text": "# Summary"}]},
        live,
        tool_call_id="c-text",
    )
    assert text["ok"], text
    value = {"claims": [{"study": "s1", "claim": "c"}]}
    claims = await toolset.dispatch(
        "submit_output",
        {"obligation": "stage.claims", "items": [{"kind": "inline", "value": value}]},
        live,
        tool_call_id="c-claims",
    )
    assert claims["ok"], claims
    patch = await toolset.dispatch(
        "submit_output",
        {
            "obligation": "stage.patch",
            "items": [
                {
                    "kind": "code_change",
                    "repository": REPO,
                    "base": BASE,
                    "head": HEAD,
                    "changed_paths": ["src/a.py"],
                }
            ],
        },
        live,
        tool_call_id="c-patch",
    )
    assert patch["ok"], patch
    expected = code_change("patch").digest
    assert patch["result"]["revisions"][0]["content_digest"] == expected
    assert expected == code_change_digest(code_change("patch"))
    wrong = await toolset.dispatch(
        "submit_output",
        {
            "obligation": "stage.summary",
            "items": [{"kind": "inline", "text": "other", "digest": "sha256:" + "f" * 64}],
        },
        live,
        tool_call_id="c-wrong",
    )
    assert wrong["refusal"]["code"] == "DIGEST_MISMATCH"
    foreign = await toolset.dispatch(
        "submit_output",
        {"obligation": "review.verdict", "items": [{"kind": "inline", "text": "x"}]},
        live,
        tool_call_id="c-foreign",
    )
    assert foreign["refusal"]["code"] == "POSITION_MISMATCH"
    assert len(contracts.submissions.rows) == 3


async def test_a_run_without_promises_refuses_inline_candidates() -> None:
    h = lane()
    refused = await h.toolset.dispatch(
        "submit_output",
        {"obligation": "report", "items": [{"kind": "inline", "text": "x"}]},
        h.live(),
        tool_call_id="c-1",
    )
    assert refused["refusal"]["code"] == "SCHEMA_UNSUPPORTED"
    assert not h.store.rows


async def test_settlement_consumes_an_unresolved_effect_as_an_effect_wait() -> None:
    h = lane()
    h.fake.invoke_script.append("pending")
    token = CURRENT_INVOCATION.set(h.live())
    try:
        pending = await h.call("knowledge_apply", {"decision": await h.decide("d-queued")}, "c-1")
    finally:
        CURRENT_INVOCATION.reset(token)
    assert pending["ok"]
    invocation = _runtime_invocation(h.live(), tool_names=TOOL_NAMES)
    outcome = await h.support.settle(invocation)
    ((_key, row),) = h.journal.rows.items()
    assert outcome.state == "waiting" and outcome.reason is WaitReason.EFFECT_PENDING
    assert outcome.pending_effects == (row.effect_key,)
    assert row.state is JournalState.UNCERTAIN
    assert not h.store.finalizations, "nothing is recorded over an unresolved effect"
    writes = len(h.fake.calls_of("invoke"))
    # A fenced pass (cancellation) still only reconciles; it never dispatches the write again.
    fenced = await h.support.settle(invocation, fenced=True)
    assert fenced.reason is WaitReason.EFFECT_PENDING
    assert len(h.fake.calls_of("invoke")) == writes


async def test_lost_protocol_receipt_waits_then_settles_without_redispatch() -> None:
    """WI-05 wait bridge: the binding committed natively and answered INTERNAL (protocol receipt
    lost). The effect is uncertain, so settlement waits on it (effect wait); once the binding
    reconstructs the original receipt, the next pass settles from it. Nothing is re-dispatched."""

    h = lane()
    h.fake.invoke_script.append("commit_refuse:INTERNAL")
    h.fake.lookups.append("unresolved")
    token = CURRENT_INVOCATION.set(h.live())
    try:
        await h.call("knowledge_apply", {"decision": await h.decide("d-lost-ack")}, "c-1")
    finally:
        CURRENT_INVOCATION.reset(token)
    ((_key, row),) = h.journal.rows.items()
    assert row.state is JournalState.UNCERTAIN
    invocation = _runtime_invocation(h.live(), tool_names=TOOL_NAMES)
    # The binding keeps answering `unresolved` for the whole pass (reconstruction not yet possible).
    h.fake.lookups.extend(["unresolved"] * 50)
    waiting = await h.support.settle(invocation)
    assert waiting.state == "waiting" and waiting.reason is WaitReason.EFFECT_PENDING
    assert waiting.pending_effects == (row.effect_key,)
    assert not h.store.finalizations
    h.fake.lookups.clear()  # the binding now answers the reconstructed original receipt
    settled = await h.support.settle(invocation)
    assert settled.state == "settled"
    ((_key, row),) = h.journal.rows.items()
    assert row.state is JournalState.APPLIED and row.reconciled
    assert len(h.fake.calls_of("invoke")) == 1, "the native write is never dispatched again"
    assert len(h.store.finalizations) == 1


async def test_settlement_waits_for_a_review_verdict_and_settles_when_it_arrives_late() -> None:
    """A declared obligation's report assessment has no verdict yet: the pass records the
    finalization once and reports the open review; a later pass records the late verdict."""

    h = lane()
    h.fake.operation_statuses["report.assess"] = deque()  # running until a verdict
    token = CURRENT_INVOCATION.set(h.live())
    try:
        await h.call("report_register", {"report": model_report("report-7")}, "c")
        receipt = next(iter(h.fake.committed.values()))
        (report,) = receipt.affectedRefs
        item = {
            "kind": "handle",
            "ref": f"kh:{report.binding}/report/{report.id}@{report.version}",
            "digest": report.digest,
        }
        submitted = await h.call("submit_output", {"obligation": "report", "items": [item]}, "s")
    finally:
        CURRENT_INVOCATION.reset(token)
    assert submitted["ok"]
    first, open_reviews = await h.toolset.settle_saved(h.live())
    assert not first.blocked and first.finalization_id is not None
    assert open_reviews and open_reviews == first.open_assessments
    h.fake.operation_statuses["report.assess"].append("succeeded")  # the late verdict
    late, still_open = await h.toolset.settle_saved(h.live())
    assert still_open == () and late.finalization_id == first.finalization_id
    assert len(h.store.finalizations) == 1
    (row,) = h.store.rows.values()
    assert row.assessment_state == "assessed"
    # A fenced pass after the cancel starts and polls no assessment.
    polls = len(h.fake.calls_of("operation.get"))
    await h.toolset.settle_saved(h.live(), fenced=True)
    assert len(h.fake.calls_of("operation.get")) == polls


async def test_fenced_native_settlement_preserves_last_durable_receipt_snapshot() -> None:
    from datetime import timedelta
    from types import SimpleNamespace

    from tests.unit.operations.test_native_receipt_evidence import AT, RECEIPT, REFERENCES, saved

    h = lane()
    calls = []

    class Native:
        async def settle(self, access, *, attempt, apply):
            calls.append(access.invocation_ref)
            return SimpleNamespace(
                pending_reviews=("review:other-native-plan",),
                outcomes=(SimpleNamespace(document=lambda: dict(REFERENCES)),),
            )

    h.toolset.native = Native()
    invocation = _runtime_invocation(h.live(), tool_names=TOOL_NAMES)
    outcome = await h.support.settle(invocation)
    waiting = saved().advanced(outcome, claim_fence=2, at=AT)
    assert (
        waiting.evidence()["invocation_settlement"]["native_effects"][0]["receipt_ref"] == RECEIPT
    )
    fenced = await h.support.settle(invocation, fenced=True)
    assert "native_effects" not in fenced.detail
    cancelled = waiting.advanced(
        fenced, claim_fence=2, at=AT + timedelta(seconds=1), stop_fence="cancelled"
    )
    assert (
        cancelled.evidence()["invocation_settlement"]["native_effects"][0]["receipt_ref"] == RECEIPT
    )
    assert len(calls) == 1, "the fenced pass dispatched no native work"
