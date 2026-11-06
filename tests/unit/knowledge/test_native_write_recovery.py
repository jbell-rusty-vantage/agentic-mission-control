"""B3 recovery regressions: immutable history, drift, crash windows and receipts."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from mission_control.adapters.knowledge.decisions import InMemoryUseDecisionStore
from mission_control.application.knowledge.native_write import NativePlanDigest
from mission_control.application.knowledge.operations import KnowledgeRefused, KnowledgeResult
from mission_control.contracts.knowledge_protocol import digest_canonical
from mission_control.domain.knowledge.effects import JournalState
from tests.unit.knowledge.test_native_write import (
    DIGEST,
    HANDLE,
    PLAN,
    Applier,
    Bridge,
    Preview,
    accepted_report,
    resolution,
    service,
)
from tests.unit.outputs.scenario import digest_of

pytestmark = pytest.mark.asyncio


class MovingPreview(Preview):
    epoch = 1

    async def preview(self, plan, *, effect_key, access):
        self.calls.append((dict(plan), effect_key))
        return NativePlanDigest(
            digest_of("payload"),
            digest_of(f"bound-{self.epoch}"),
            normalized_values_digest=digest_canonical({}),
            processed_epoch=self.epoch,
        )


async def test_drift_selects_matching_digest_and_preserves_history_without_handle_ordering():
    stack = await accepted_report()
    bridge = Bridge(InMemoryUseDecisionStore())
    preview = MovingPreview()
    native = service(stack, bridge, preview=preview)
    apply = Applier()
    first = await native.write(
        stack.access, HANDLE, DIGEST, plan_reports=PLAN, attempt=1, apply=apply
    )
    preview.epoch = 2
    second = await native.write(
        stack.access, HANDLE, DIGEST, plan_reports=PLAN, attempt=2, apply=apply
    )
    assert first.decision != second.decision
    assert (
        len(await bridge.store.for_invocation(stack.access.scope, stack.access.invocation_ref)) == 2
    )
    assert await bridge.store.get(stack.access.scope, first.decision.handle) == first.decision
    again = await native.write(
        stack.access, HANDLE, DIGEST, plan_reports=PLAN, attempt=3, apply=apply
    )
    assert again.decision == second.decision and len(bridge.decided) == 2


async def test_preview_to_apply_conflict_refreshes_once_and_applies_successor():
    stack = await accepted_report()
    bridge = Bridge(InMemoryUseDecisionStore())
    preview = MovingPreview()
    native = service(stack, bridge, preview=preview)
    calls = []

    async def apply(handle):
        calls.append(handle)
        if len(calls) == 1:
            preview.epoch = 2
            return KnowledgeResult("knowledge.apply", refusal_code="EFFECT_CONFLICT")
        return "done"

    outcome = await native.write(
        stack.access, HANDLE, DIGEST, plan_reports=PLAN, attempt=1, apply=apply
    )
    assert outcome.state == "applied" and len(calls) == 2
    assert len(set(calls)) == 2 and len(bridge.decided) == 2


async def test_unchanged_stale_digest_refuses_without_unbounded_redecision():
    stack = await accepted_report()
    bridge = Bridge(InMemoryUseDecisionStore())
    native = service(stack, bridge)

    async def apply(handle):
        raise KnowledgeRefused("STALE_DECISION", "revoked")

    with pytest.raises(KnowledgeRefused, match="STALE_DECISION"):
        await native.write(stack.access, HANDLE, DIGEST, plan_reports=PLAN, attempt=1, apply=apply)
    assert len(bridge.decided) == 1


async def test_applied_journal_skips_preview_and_dispatch_after_restart():
    stack = await accepted_report()
    bridge = Bridge(InMemoryUseDecisionStore())
    preview = MovingPreview()
    native = service(stack, bridge, preview=preview)
    first = await native.write(
        stack.access, HANDLE, DIGEST, plan_reports=PLAN, attempt=1, apply=Applier()
    )
    restarted = service(stack, bridge, preview=preview)

    async def existing(handle, access):
        assert handle == first.decision.handle
        return SimpleNamespace(
            state=JournalState.APPLIED,
            refusal_code=None,
            document=lambda: {"effect_key": "effect-1", "receipt_ref": "receipt-1"},
        )

    restarted._existing_effect = existing
    apply = Applier()
    outcome = await restarted.settle(stack.access, attempt=2, apply=apply)
    assert not apply.handles and len(preview.calls) == 1
    assert outcome.outcomes[0].document()["receipt_ref"] == "receipt-1"


async def test_independent_subjects_survive_refusal_and_foreign_invocation_is_ignored():
    stack = await accepted_report()
    bridge = Bridge(InMemoryUseDecisionStore())
    native = service(stack, bridge)
    first = await native.write(
        stack.access, HANDLE, DIGEST, plan_reports=PLAN, attempt=1, apply=Applier()
    )
    bad = replace(first.decision, handle="bad", subject_ref="bad#" + DIGEST)
    foreign = replace(first.decision, handle="foreign", invocation_ref="other-invocation")
    await bridge.store.record(stack.access.scope, bad)
    await bridge.store.record(stack.access.scope, foreign)
    apply = Applier()
    result = await native.settle(stack.access, attempt=2, apply=apply)
    assert len(result.outcomes) == 2
    assert [o.refusal_code for o in result.outcomes if o.state == "refused"] == ["STALE_DECISION"]
    assert apply.handles == [first.decision.handle]


async def test_authoritative_run_id_is_required_and_not_inferred_from_decision_name():
    stack = await accepted_report()
    bridge = Bridge(InMemoryUseDecisionStore())
    original = bridge.resolve

    async def resolve(access, decision, *, attempt, fresh=False):
        result = await original(access, decision, attempt=attempt)
        return result.model_copy(update={"runId": None})

    bridge.resolve = resolve
    with pytest.raises(KnowledgeRefused, match="authoritative runId"):
        await service(stack, bridge).write(
            stack.access, HANDLE, DIGEST, plan_reports=PLAN, attempt=1, apply=Applier()
        )
    assert not bridge.decided


@pytest.mark.parametrize("drift", [False, True])
async def test_decide_before_record_crash_replays_or_leaves_harmless_lineage(drift):
    stack = await accepted_report()
    bridge = Bridge(InMemoryUseDecisionStore())
    preview = MovingPreview()
    native = service(stack, bridge, preview=preview)
    original = bridge.record_apply_decision
    count = 0

    async def record(access, decision):
        nonlocal count
        count += 1
        if count == 1:
            raise RuntimeError("crash after decide")
        return await original(access, decision)

    bridge.record_apply_decision = record
    apply = Applier()
    with pytest.raises(RuntimeError, match="crash"):
        await native.write(stack.access, HANDLE, DIGEST, plan_reports=PLAN, attempt=1, apply=apply)
    assert not apply.handles and not await bridge.store.for_invocation(
        stack.access.scope, stack.access.invocation_ref
    )
    preview.epoch = 2 if drift else 1
    outcome = await native.write(
        stack.access, HANDLE, DIGEST, plan_reports=PLAN, attempt=2, apply=apply
    )
    assert apply.handles == [outcome.decision.handle]
    ids = [bridge.decision(row["bound_effect_digest"]).id for row in bridge.decided]
    assert (ids[0] != ids[1]) == drift
    assert (
        len(await bridge.store.for_invocation(stack.access.scope, stack.access.invocation_ref)) == 1
    )


async def test_native_decide_request_identity_excludes_attempt_but_resolve_refreshes():
    from mission_control.application.knowledge.judgment import TrustedJudgmentBridge, UseSpec
    from tests.unit.knowledge.test_native_write import ref

    calls = []
    decision = ref("use_decision", "opaque-decision", "research-core.use_decision.v2")

    class Calls:
        async def _call(self, operation, request, host, *, key):
            calls.append((operation, key))
            return {"decision": decision.model_dump(mode="json")}

        async def resolve(self, host, decision, *, attempt, fresh=False):
            calls.append(("resolve-attempt", attempt))
            return resolution(decision, pending=False)

    stack = await accepted_report()
    use = UseSpec(
        use="u", audience="official", policy=ref("policy", "p"), rubric=ref("rubric", "r")
    )
    for attempt in [1000, 2000]:
        await TrustedJudgmentBridge.decide_native_plan(
            Calls(),
            stack.access,
            ref("report", "r"),
            use,
            revision_id="revision",
            bound_effect_digest=DIGEST,
            target_schema="native.v1",
            attempt=attempt,
        )
    assert calls[0] == calls[2]
    assert calls[1] != calls[3]


async def test_fresh_resolution_under_a_frozen_clock_uses_distinct_request_keys():
    from mission_control.application.knowledge.judgment import TrustedJudgmentBridge
    from tests.unit.knowledge.test_native_write import ref

    decision = ref("use_decision", "d", "research-core.use_decision.v2")
    keys = []

    class Calls:
        async def _call(self, operation, request, host, *, key):
            keys.append(key)
            return resolution(decision, pending=False).model_dump(mode="json", by_alias=True)

    stack = await accepted_report()
    for _ in range(2):
        await TrustedJudgmentBridge.resolve(
            Calls(), stack.access, decision, attempt=1000, fresh=True
        )
    assert keys[0] != keys[1]


async def test_explicit_effect_candidate_from_settlement_can_fulfill_a_named_promise():
    from mission_control.application.knowledge.effect_receipts import JournalEffectReceipts
    from mission_control.application.knowledge.toolset import InlineItem, _candidate
    from mission_control.domain.outputs.contracts import OutputForm
    from tests.unit.knowledge.test_gateway import call, harness
    from tests.unit.outputs.scenario import fulfillment, obligation
    from tests.unit.outputs.test_output_fulfillment import make_stack

    h = harness()
    stack = await make_stack(obligation("draft.native_receipt", OutputForm.EFFECT_RECEIPT))
    result = await h.gateway.invoke(call(), stack.access)
    assert result.journal.state is JournalState.APPLIED
    stack.outputs._effect_receipts = JournalEffectReceipts(h.journal)
    document = result.document()
    item = InlineItem(
        kind="inline",
        value={"effect_key": document["effect_key"], "receipt_ref": document["receipt_ref"]},
        effect_key=document["effect_key"],
        receipt_ref=document["receipt_ref"],
    )
    promise = await stack.submissions.pinned_obligation(stack.access, "draft.native_receipt")
    candidate = _candidate(item, promise, "native_receipt")
    ack = await stack.submit("settled-receipt", "draft.native_receipt", candidate)
    await stack.accept(ack, "draft.native_receipt")
    assert fulfillment(await stack.evaluate(), "draft.native_receipt").disposition == "fulfilled"


async def test_native_effect_inspection_survives_json_serialization_and_lane_settlement():
    import json

    from mission_control.adapters.deep_agents.knowledge_tools import KnowledgeLaneSupport
    from mission_control.application.knowledge.native_write import (
        NativeSettlement,
        NativeWriteOutcome,
    )
    from tests.unit.knowledge.test_knowledge_tools import TOOL_NAMES, _runtime_invocation, lane

    stack = await accepted_report()
    bridge = Bridge(InMemoryUseDecisionStore())
    native = service(stack, bridge)
    first = await native.write(
        stack.access, HANDLE, DIGEST, plan_reports=PLAN, attempt=1, apply=Applier()
    )
    h = lane()

    class Settler:
        async def settle(self, access, *, attempt, apply):
            return NativeSettlement(
                (
                    NativeWriteOutcome(
                        "applied",
                        first.decision,
                        result=SimpleNamespace(
                            document=lambda: {"effect_key": "effect1", "receipt_ref": "receipt1"}
                        ),
                    ),
                )
            )

    h.toolset.native = Settler()
    report, _ = await h.toolset.settle_saved(h.live())
    assert json.loads(json.dumps(report.native_effects))[0]["receipt_ref"] == "receipt1"
    support = KnowledgeLaneSupport(h.toolset)
    outcome = await support.settle(_runtime_invocation(h.live(), tool_names=TOOL_NAMES))
    assert (
        json.loads(json.dumps(dict(outcome.detail)))["native_effects"][0]["effect_key"] == "effect1"
    )


@pytest.mark.parametrize(
    "state",
    [
        JournalState.NOOP,
        JournalState.PARTIAL,
        JournalState.UNCERTAIN,
        JournalState.PREPARED,
        JournalState.DISPATCHED,
    ],
)
async def test_terminal_or_unknown_effect_never_creates_a_successor_or_redispatches(state):
    stack = await accepted_report()
    bridge = Bridge(InMemoryUseDecisionStore())
    preview = MovingPreview()
    native = service(stack, bridge, preview=preview)
    first = await native.write(
        stack.access, HANDLE, DIGEST, plan_reports=PLAN, attempt=1, apply=Applier()
    )

    async def existing(handle, access):
        return SimpleNamespace(
            state=state,
            refusal_code=None,
            document=lambda: {"effect_key": "same-effect", "journal_state": state.value},
        )

    restarted = service(stack, bridge, preview=preview)
    restarted._existing_effect = existing
    apply = Applier()
    outcome = await restarted.write(
        stack.access, HANDLE, DIGEST, plan_reports=PLAN, attempt=2, apply=apply
    )
    assert outcome.state == {JournalState.NOOP: "noop", JournalState.PARTIAL: "partial"}.get(
        state, "pending_effect"
    )
    assert not apply.handles and len(preview.calls) == 1 and len(bridge.decided) == 1
    assert outcome.decision == first.decision


class IntentPreview(Preview):
    async def preview(self, plan, *, effect_key, access):
        self.calls.append((dict(plan), effect_key))
        return NativePlanDigest(
            digest_of("payload"),
            digest_canonical(dict(plan)),
            normalized_values_digest=digest_canonical({}),
            processed_epoch=1,
        )


async def test_durable_rejection_creates_one_stable_successor_then_replays_its_receipt():
    stack = await accepted_report()
    bridge = Bridge(InMemoryUseDecisionStore())
    preview = IntentPreview()
    native = service(stack, bridge, preview=preview)
    effects = {}

    async def existing(handle, access):
        return effects.get(handle)

    native._existing_effect = existing
    calls = []

    async def apply(handle):
        calls.append(handle)
        state = JournalState.REJECTED if len(calls) == 1 else JournalState.APPLIED
        result = SimpleNamespace(
            state=state,
            refusal_code="STALE_DECISION" if len(calls) == 1 else None,
            document=lambda: {"effect_key": handle, "journal_state": state.value},
        )
        effects[handle] = result
        return result

    outcome = await native.write(
        stack.access, HANDLE, DIGEST, plan_reports=PLAN, attempt=1, apply=apply
    )
    assert outcome.state == "applied" and len(calls) == 2
    rows = await bridge.store.for_invocation(stack.access.scope, stack.access.invocation_ref)
    assert len(rows) == 2
    plans = [plan for plan, key in preview.calls]
    assert plans[0]["intentId"].startswith("mc-")
    assert (
        plans[1]["intentId"].startswith("mc-retry-")
        and plans[0]["intentId"] != plans[1]["intentId"]
    )
    assert plans[0]["proposals"] == plans[1]["proposals"]
    # A fresh service reconstructs the admitted successor and its terminal receipt.
    restarted = service(stack, bridge, preview=preview)
    restarted._existing_effect = existing
    again = await restarted.write(
        stack.access, HANDLE, DIGEST, plan_reports=PLAN, attempt=2, apply=apply
    )
    assert again.decision == outcome.decision and len(calls) == 2 and len(preview.calls) == 2


async def test_rejected_successor_identity_is_stable_across_decide_before_record_crash():
    stack = await accepted_report()
    bridge = Bridge(InMemoryUseDecisionStore())
    preview = IntentPreview()
    native = service(stack, bridge, preview=preview)
    first = await native.write(
        stack.access, HANDLE, DIGEST, plan_reports=PLAN, attempt=1, apply=Applier()
    )

    async def existing(handle, access):
        if handle == first.decision.handle:
            return SimpleNamespace(state=JournalState.REJECTED, refusal_code="STALE_DECISION")
        return None

    native._existing_effect = existing
    original = bridge.record_apply_decision

    async def crash(access, decision):
        raise RuntimeError("before recording successor")

    bridge.record_apply_decision = crash
    with pytest.raises(RuntimeError, match="successor"):
        await native.write(
            stack.access, HANDLE, DIGEST, plan_reports=PLAN, attempt=2, apply=Applier()
        )
    crash_intent = preview.calls[-1][0]
    bridge.record_apply_decision = original
    apply = Applier()
    done = await native.write(
        stack.access, HANDLE, DIGEST, plan_reports=PLAN, attempt=3, apply=apply
    )
    assert preview.calls[-1][0] == crash_intent
    assert apply.handles == [done.decision.handle]
    assert (
        len(await bridge.store.for_invocation(stack.access.scope, stack.access.invocation_ref)) == 2
    )


async def test_unreviewable_stale_resolution_is_refused_without_phantom_review_wait():
    stack = await accepted_report()
    bridge = Bridge(InMemoryUseDecisionStore())
    original = bridge.resolve

    async def resolve(access, decision, *, attempt, fresh=False):
        answer = await original(access, decision, attempt=attempt, fresh=fresh)
        if decision.id.startswith("ud-native-"):
            return answer.model_copy(
                update={
                    "reviewPending": False,
                    "admissibility": answer.admissibility.model_copy(
                        update={"status": "held", "reason": "revoked"}
                    ),
                }
            )
        return answer

    bridge.resolve = resolve
    native = service(stack, bridge)
    with pytest.raises(KnowledgeRefused, match="STALE_DECISION"):
        await native.write(
            stack.access, HANDLE, DIGEST, plan_reports=PLAN, attempt=1, apply=Applier()
        )
    settled = await native.settle(stack.access, attempt=2, apply=Applier())
    assert settled.pending_reviews == ()
    assert (
        settled.outcomes[0].state == "refused"
        and settled.outcomes[0].refusal_code == "STALE_DECISION"
    )
