"""Existing knowledge/output fixtures composed for explicit native receipt selection."""

from dataclasses import dataclass, replace
from typing import Any

from tests.fixtures.output_contracts import InMemoryOutputContractStore
from tests.unit.knowledge.test_knowledge_tools import MISSION, lane
from tests.unit.knowledge.test_native_write import (
    DIGEST,
    HANDLE,
    PLAN,
    RUN_DECISION,
    Bridge,
    bridge_judges,
    report_candidate,
    report_promise,
    service,
)
from tests.unit.outputs.scenario import build_stack, fulfillment, obligation

from mission_control.adapters.knowledge.decisions import InMemoryUseDecisionStore
from mission_control.application.knowledge.effect_receipts import JournalEffectReceipts
from mission_control.application.knowledge.toolset import LiveInvocation, ReadScope
from mission_control.application.outputs.fulfillment import TrustedReferenceUses
from mission_control.domain.outputs.contracts import OutputForm

PIN = "knowledge.custom-native-apply@2"


class ScopedBridge(Bridge):
    async def resolve(self, access, decision, *, attempt, fresh=False):
        result = await super().resolve(access, decision, attempt=attempt, fresh=fresh)
        return result.model_copy(
            update={
                "report": result.report.model_copy(update={"tenant": access.origin.tenant_id}),
                "subject": result.subject.model_copy(update={"tenant": access.origin.tenant_id}),
            }
        )


@dataclass
class PendingReceiptCase:
    tools: Any
    stack: Any
    bridge: Any
    native: Any
    live: LiveInvocation
    answer: Any = None
    submission: Any = None
    selections: int = 0

    async def select(self):
        """The producer's explicit tool calls, before its cognition result is saved/finalized."""
        self.selections += 1
        self.answer = await self.tools.toolset.dispatch(
            "knowledge_apply",
            {"report": HANDLE, "digest": DIGEST},
            self.live,
            tool_call_id="native-write",
        )
        assert self.answer["ok"] and self.answer["result"]["state"] == "pending_review", self.answer
        key = self.answer["result"]["effect_key"]
        self.submission = await self.tools.toolset.dispatch(
            "submit_output",
            {
                "obligation": "root.native_receipt",
                "items": [{"kind": "inline", "value": {"effect_key": key}, "effect_key": key}],
            },
            self.live,
            tool_call_id="native-receipt-selection",
        )
        assert self.submission["ok"], self.submission

    async def converge(self):
        await self.stack.outputs.converge(
            self.stack.host,
            self.stack.run_id,
            operation_ref=self.live.operation_id,
            generation=self.live.execution_generation,
        )
        return fulfillment(await self.stack.evaluate(), "root.native_receipt")


async def pending_receipt_case(live: LiveInvocation | None = None):
    tools = lane()
    if live is not None:
        # Provenance slice 1: the in-memory ledger knows the actual runtime run.
        tools.locator.missions.setdefault(live.run_id, MISSION)
        live = await tools.toolset.locate(live)
    live = replace(
        live or tools.live(),
        position="root",
        obligations=(),
        read_scope=ReadScope(purpose="dependent_input", isolated=False, reports=PLAN),
    )
    tools.toolset.capability_pins = {"knowledge_apply": PIN}
    source = tools.toolset.access(replace(live, operation_id="prior-report-producer"))
    store = InMemoryOutputContractStore()
    stack = await build_stack(
        store,
        store.submissions,
        source,
        report_promise(),
        obligation("root.native_receipt", OutputForm.EFFECT_RECEIPT, position="root"),
    )
    stack.outputs._reference_uses = TrustedReferenceUses(store)
    stack.outputs._effect_receipts = JournalEffectReceipts(tools.journal)
    report = await stack.submit("source-report", "root.report", report_candidate(), position="root")
    revision = report.revisions[0]
    await bridge_judges(stack, revision.revision_id, revision.content_digest, "pass", RUN_DECISION)
    await stack.accept(report, "root.report")
    bridge = ScopedBridge(InMemoryUseDecisionStore(), pending=True)
    native = service(stack, bridge)
    tools.decisions = bridge.store
    tools.toolset.gateway._decisions = bridge.store
    tools.toolset.submissions = stack.submissions
    tools.toolset.native = native

    async def existing(handle, access):
        return await tools.toolset.gateway.existing_decision_effect(
            handle, access, capability_pin=PIN
        )

    native._existing_effect = existing
    live = await tools.toolset.begin(live)
    return PendingReceiptCase(tools, stack, bridge, native, live)


def approve_review_successor(case):
    """KS transport double of its immutable successor chain, not a same-ID approval toggle."""
    from mission_control.contracts.knowledge_protocol import digest_canonical

    original = case.bridge.resolve

    async def resolve(access, decision, *, attempt, fresh=False):
        answer = await original(access, decision, attempt=attempt, fresh=fresh)
        if decision.id == RUN_DECISION:
            return answer
        current = decision.model_copy(
            update={
                "id": decision.id + "-review",
                "digest": digest_canonical({"review": decision.id}),
            }
        )
        return answer.model_copy(
            update={
                "current": current,
                "chain": (decision, current),
                "reviewPending": False,
                "admissibility": answer.admissibility.model_copy(update={"status": "admitted"}),
            }
        )

    case.bridge.resolve = resolve
