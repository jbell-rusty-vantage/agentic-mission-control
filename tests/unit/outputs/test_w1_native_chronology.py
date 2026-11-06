"""Required native receipts remain a final gate after report assessment (memory stores)."""

import pytest

from mission_control.application.knowledge.effect_receipts import JournalEffectReceipts
from mission_control.application.knowledge.toolset import InlineItem, _candidate
from mission_control.application.programs.goal_directed import bind_fulfillment
from mission_control.domain.outputs.contracts import Enforcement, OutputForm
from tests.unit.knowledge.test_gateway import call, harness
from tests.unit.orchestration.test_wp_bp_020_goal_directed import (
    _blueprint,
    _claim,
    _execution,
    _verification,
)
from tests.unit.outputs.scenario import obligation, text
from tests.unit.outputs.test_output_fulfillment import make_stack
from tests.unit.outputs.test_w1_convergence_fulfillment import _observation


@pytest.mark.asyncio
async def test_report_acceptance_continues_until_explicit_applied_receipt_fulfills_run():
    stack = await make_stack(
        obligation("root.report", OutputForm.TEXT),
        obligation("root.native_receipt", OutputForm.EFFECT_RECEIPT),
        obligation("root.summary", OutputForm.TEXT, enforcement=Enforcement.EXPECTED),
        obligation("root.caveats", OutputForm.TEXT, enforcement=Enforcement.OPTIONAL),
    )
    # The assessment is represented by an accepted head; this test does not claim KS proof.
    report = await stack.submit("report", "root.report", text("report", "assessed report"))
    await stack.accept(report, "root.report")
    frontier = await stack.evaluate()
    first = bind_fulfillment(_observation(), frontier)
    assert first.decision == "rejected"
    assert "output:root.native_receipt" in first.unmet_obligations
    assert first.accepted_obligation_refs == ()
    assert "expected output shortfall: root.summary" in first.findings
    assert not any("caveats" in finding for finding in first.findings)
    interpreter, state, claim = _claim(_blueprint(max_iterations=2))
    state = interpreter.apply_execution_result(state, _execution(claim))
    state = interpreter.apply_verification(
        state, _verification(claim, decision=first.decision, progress=first.progress_made)
    )
    assert state.convergence_proposal.action == "continue"

    gateway = harness()
    applied = await gateway.gateway.invoke(call(), stack.access)
    stack.outputs._effect_receipts = JournalEffectReceipts(gateway.journal)
    # Even an applied journal effect is insufficient without the producer's submission.
    assert bind_fulfillment(_observation(), await stack.evaluate()).decision == "rejected"
    document = applied.document()
    item = InlineItem(
        kind="inline",
        value={"effect_key": document["effect_key"], "receipt_ref": document["receipt_ref"]},
        effect_key=document["effect_key"],
        receipt_ref=document["receipt_ref"],
    )
    promise = await stack.submissions.pinned_obligation(stack.access, "root.native_receipt")
    receipt = await stack.submit(
        "receipt", "root.native_receipt", _candidate(item, promise, "native_receipt")
    )
    await stack.accept(receipt, "root.native_receipt")
    final = bind_fulfillment(_observation(), await stack.evaluate())
    assert final.decision == "accepted"
