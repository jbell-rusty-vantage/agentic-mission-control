"""W1 native write inside one invocation (integrator decisions 2026-10-29; ESCALATION H11/H12).

The host sequence over doubles of the KS transport: an accepted, officially usable report member
of the sealed plan -> the application's existing native intent -> the exact native digest of
THIS invocation -> plan-level ``report.decide`` -> recorded decision (subject, invocation and
decision digest) -> apply, or a typed ``pending_review`` the same invocation's settlement applies
once the plan decision is usable. Replays reuse the recorded decision; another invocation can
neither settle nor apply it; Biotech's schema has no report intent and refuses typed.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from mission_control.adapters.knowledge.decisions import InMemoryUseDecisionStore
from mission_control.application.knowledge.access import InvocationAccess
from mission_control.application.knowledge.apply_payload import INTENT_ENVELOPE, apply_payload
from mission_control.application.knowledge.native_write import (
    ClaimMaterializeIntentBuilder,
    KnowledgePlanPreview,
    LocalIntentEnvelopePreview,
    NativePlanDigest,
    NoNativeIntent,
    ReportRecords,
)
from mission_control.application.knowledge.operations import KnowledgeRefused
from mission_control.application.knowledge.toolset import ApplyArgs
from mission_control.contracts.knowledge_protocol import bound_effect_digest, canonical_json
from tests.support.knowledge.gateway import TENANT, origin
from tests.support.unit.knowledge.native_write import (
    BINDING,
    DIGEST,
    PLAN,
    RUN_DECISION,
    Applier,
    Bridge,
    Preview,
    accepted_report,
    service,
)
from tests.support.unit.outputs.w1_d28_d29 import (
    HANDLE,
    bridge_judges,
    make_stack,
    report_candidate,
    report_promise,
)
from tests.unit.outputs.scenario import digest_of

pytestmark = pytest.mark.asyncio


async def test_the_whole_sequence_runs_in_one_invocation_and_replays_one_decision() -> None:
    stack = await accepted_report()
    bridge = Bridge(InMemoryUseDecisionStore())
    preview = Preview()
    native = service(stack, bridge, preview=preview)
    apply = Applier()
    outcome = await native.write(
        stack.access, HANDLE, DIGEST, plan_reports=PLAN, attempt=1, apply=apply
    )
    assert outcome.state == "applied" and apply.handles == [outcome.decision.handle]
    ((intent, effect_key),) = preview.calls
    assert effect_key.startswith("preview-")
    assert intent["proposals"][0]["kind"] == "claim.materialize"
    assert intent["proposals"][0]["runId"] == "run-77"  # the report decision's KS run
    assert [c["statement"] for c in intent["evidence"]["claims"]] == [
        "Model A has 7B params.",
        "Model B has 70B params.",
    ]
    assert intent["declaredUse"] == {
        "use": "engineering_reference.model_facts",
        "audience": "official",
    }
    (decided,) = bridge.decided
    assert decided["bound_effect_digest"] == digest_of("bound-" + stack.access.invocation_ref)
    assert decided["target_schema"] == "knowledge-ingestion-intent.v1"
    decision = outcome.decision
    assert decision.subject_ref == f"{HANDLE}#{DIGEST}"
    assert decision.invocation_ref == stack.access.invocation_ref
    assert decision.decision_digest is not None and decision.processed_epoch == 5
    assert decision.normalized_values_digest == digest_of("values")
    assert decision.handle.startswith(f"kh:{BINDING}/decision/")
    # A replay (worker restart after the decision was recorded) never decides again.
    again = await native.write(
        stack.access, HANDLE, DIGEST, plan_reports=PLAN, attempt=2, apply=apply
    )
    assert len(bridge.decided) == 1 and again.decision == decision
    assert (
        len(await bridge.store.for_invocation(stack.access.scope, stack.access.invocation_ref)) == 1
    )


async def test_a_pending_plan_review_waits_and_the_same_invocations_settlement_applies() -> None:
    stack = await accepted_report()
    bridge = Bridge(InMemoryUseDecisionStore(), pending=True)
    native = service(stack, bridge)
    apply = Applier()
    outcome = await native.write(
        stack.access, HANDLE, DIGEST, plan_reports=PLAN, attempt=1, apply=apply
    )
    assert outcome.state == "pending_review" and not apply.handles
    assert outcome.pending_reviews[0].startswith("ks-use-decision:ud-native-")
    assert (
        await native.settle(stack.access, attempt=2, apply=apply)
    ).pending_reviews == outcome.pending_reviews
    assert not apply.handles  # still waiting: nothing dispatched
    # Another invocation (another iteration or stage) has nothing to settle for it.
    other = InvocationAccess(
        origin=origin(1, operation_id="goal-iteration/2/executor"),
        subject="mission-control-runtime",
        invocation_id="inv-other",
        authenticated_at=stack.access.authenticated_at,
    )
    assert (await native.settle(other, attempt=3, apply=apply)).outcomes == ()
    bridge.pending = False  # the qualified reviewer approved the plan decision
    assert (await native.settle(stack.access, attempt=4, apply=apply)).pending_reviews == ()
    assert apply.handles == [outcome.decision.handle] and len(bridge.decided) == 1


async def test_only_an_officially_usable_member_of_the_sealed_plan_is_written() -> None:
    stack = await accepted_report()
    native = service(stack, Bridge(InMemoryUseDecisionStore()))
    with pytest.raises(KnowledgeRefused) as off_plan:
        await native.write(
            stack.access, HANDLE, DIGEST, plan_reports={}, attempt=1, apply=Applier()
        )
    assert off_plan.value.code == "SCOPE_DENIED"
    held = await make_stack(report_promise())
    ack = await held.submit("k1", "root.report", report_candidate(), position="root")
    revision = ack.revisions[0]
    await bridge_judges(held, revision.revision_id, revision.content_digest, "review", RUN_DECISION)
    with pytest.raises(KnowledgeRefused) as not_usable:
        await service(held, Bridge(InMemoryUseDecisionStore())).write(
            held.access, HANDLE, DIGEST, plan_reports=PLAN, attempt=1, apply=Applier()
        )
    assert not_usable.value.code == "STALE_DECISION"


async def test_biotech_has_no_report_intent_and_refuses_typed() -> None:
    stack = await accepted_report()
    native = service(stack, Bridge(InMemoryUseDecisionStore()), builder=NoNativeIntent())
    with pytest.raises(KnowledgeRefused) as refused:
        await native.write(
            stack.access, HANDLE, DIGEST, plan_reports=PLAN, attempt=1, apply=Applier()
        )
    assert refused.value.code == "SCHEMA_UNSUPPORTED"


async def test_the_intent_envelope_digest_is_the_one_apply_checks_for_this_origin_only() -> None:
    stack = await accepted_report()
    plan = {"intentId": "i-1", "proposals": [{"kind": "node.upsert"}]}
    digest = await LocalIntentEnvelopePreview().preview(plan, effect_key="e", access=stack.access)
    native = canonical_json(plan).encode("utf-8")
    assert digest.bound_effect_digest == bound_effect_digest(native, stack.access.wire_origin())
    from mission_control.application.ports.knowledge import RecordedUseDecision

    decision = RecordedUseDecision(
        handle="h",
        binding_id=BINDING,
        tenant_id=TENANT,
        use_decision_id="ud-1",
        bound_effect_digest=digest.bound_effect_digest,
        processed_epoch=1,
        plan=plan,
    )
    port = SimpleNamespace(
        intent_schema_ref=INTENT_ENVELOPE,
        apply_contract_name="biotech-knowledge-apply",
        apply_contract_version="v1",
    )
    built = apply_payload(port, decision, effect_key="e", originating=stack.access.wire_origin())  # type: ignore[arg-type]
    assert built.plan == plan
    other = InvocationAccess(
        origin=origin(1, operation_id="goal-iteration/2/executor"),
        subject="mission-control-runtime",
        invocation_id="inv-other",
        authenticated_at=stack.access.authenticated_at,
    )
    with pytest.raises(KnowledgeRefused) as conflict:
        apply_payload(port, decision, effect_key="e", originating=other.wire_origin())  # type: ignore[arg-type]
    assert conflict.value.code == "EFFECT_CONFLICT"


async def test_the_ks_plan_preview_is_one_synchronous_nonce_per_call_and_records_nothing() -> None:
    """KS `knowledge.plan_preview` (f457e8f): the apply envelope with `effect: null` under a
    non-effect credential granting only that operation; the answer arrives in the call; every
    call (a replay after a crash included) mints a fresh credential nonce; nothing is recorded."""

    from mission_control.contracts.knowledge_protocol import KnowledgePlanPreview as Answer
    from mission_control.contracts.knowledge_protocol import digest_canonical
    from tests.support.knowledge.gateway import harness

    h = harness()
    empty = digest_canonical({})

    def previewer(envelope: Any) -> Answer:
        return Answer(
            planId="plan-1",
            semanticPayloadDigest=digest_of("s"),
            boundEffectDigest=digest_of("b"),
            normalizedValuesDigest=empty,
            processedEpoch=9,
            migrationHead="20261029",
        )

    h.client.previewer = previewer
    access = h.access()
    plan = {"schemaVersion": "knowledge-ingestion-intent.v1", "intentId": "mc-1"}
    preview = KnowledgePlanPreview(h.gateway)
    first = await preview.preview(plan, effect_key="ek-1", access=access)
    again = await preview.preview(plan, effect_key="ek-1", access=access)  # a replay
    assert (
        first
        == again
        == NativePlanDigest(
            semantic_payload_digest=digest_of("s"),
            bound_effect_digest=digest_of("b"),
            plan_id="plan-1",
            normalized_values_digest=empty,
            processed_epoch=9,
            migration_head="20261029",
        )
    )
    sent = h.client.calls_of("invoke")
    assert len(sent) == 2
    for item in sent:
        assert item.envelope is not None and item.envelope.operation == "knowledge.plan_preview"
        assert item.envelope.effect is None
        assert list(item.claims.operations) == ["knowledge.plan_preview"]
        assert item.claims.effect is None  # a non-effect credential
        payload = item.envelope.input.inlinePayload  # type: ignore[union-attr]
        assert payload["exactUse"]["effectKey"] == "ek-1"
        assert set(payload["exactUse"]) == {"effectKey", "originatingOrigin"}
        assert item.envelope.input.nativeContract.name == knowledge_contract(h)  # type: ignore[union-attr]
    assert sent[0].claims.jti != sent[1].claims.jti  # a fresh nonce per call
    assert sent[0].envelope.dispatchId != sent[1].envelope.dispatchId  # type: ignore[union-attr]
    assert h.handles.rows == {}  # no handle recorded
    assert await h.journal.transitions(access.scope, "ek-1") == []  # nothing journaled
    # An echo of normalized values the plan decision does not declare is refused.
    h.client.previewer = lambda envelope: previewer(envelope).model_copy(
        update={"normalizedValuesDigest": digest_of("values")}
    )
    with pytest.raises(KnowledgeRefused) as declared:
        await preview.preview(plan, effect_key="ek-1", access=access)
    assert declared.value.code == "SCHEMA_UNSUPPORTED"
    h.client.previewer = None  # a binding that previews nothing refuses typed
    with pytest.raises(KnowledgeRefused) as refused:
        await preview.preview(plan, effect_key="ek-1", access=access)
    assert refused.value.code == "SCHEMA_UNSUPPORTED"


def knowledge_contract(h: Any) -> str:
    return h.gateway.knowledge.apply_contract_name


async def test_the_toolset_answers_pending_review_and_its_settlement_applies() -> None:
    """The tool answer (typed `pending_review`, nothing dispatched) and the settlement wiring:
    `settle_saved` reports the plan review as pending, then applies it once it is usable."""

    from dataclasses import replace as dc_replace

    from mission_control.application.knowledge.toolset import LiveInvocation, ReadScope
    from tests.support.knowledge.gateway import lane

    stack = await accepted_report()
    bridge = Bridge(InMemoryUseDecisionStore(), pending=True)
    native = service(stack, bridge)
    tools = lane()
    applied: list[str] = []

    async def apply_decision(handle: str, access: Any, **_: Any) -> Any:
        applied.append(handle)
        return SimpleNamespace(handle=handle)

    tools.toolset.native = native
    tools.toolset.gateway._decisions = bridge.store
    tools.toolset.gateway.apply_decision = apply_decision  # type: ignore[method-assign]
    origin_ = stack.access.origin
    live = LiveInvocation(
        request_scope=stack.access.scope,
        run_id=origin_.run_id,
        operation_id=origin_.operation_id,
        operation_attempt=origin_.attempt,
        execution_generation=origin_.generation,
        lane=origin_.lane,
        read_scope=ReadScope(purpose="dependent_input", isolated=False, reports=PLAN),
        mission_id=origin_.mission_id,
        activation_id=origin_.activation_id,
    )
    tools.toolset.issuer = origin_.issuer
    answer = await tools.toolset.dispatch(
        "knowledge_apply", {"report": HANDLE, "digest": DIGEST}, live, tool_call_id="t1"
    )
    assert answer["ok"] and answer["result"]["state"] == "pending_review"
    assert answer["result"]["pending_reviews"] and not applied
    _report, pending = await tools.toolset.settle_saved(dc_replace(live))
    assert answer["result"]["pending_reviews"][0] in pending and not applied
    bridge.pending = False  # the reviewer approved the plan decision
    _report, pending = await tools.toolset.settle_saved(dc_replace(live))
    assert applied == [answer["result"]["decision"]]
    assert answer["result"]["pending_reviews"][0] not in pending


def test_the_claim_intent_is_deterministic_and_needs_assertions() -> None:
    access = InvocationAccess(
        origin=origin(1),
        subject="mission-control-runtime",
        invocation_id="inv-a",
        authenticated_at=__import__("datetime").datetime(
            2026, 10, 29, tzinfo=__import__("datetime").UTC
        ),
    )
    records = ReportRecords(HANDLE, DIGEST, "run-77", (("a-1", "A"),))
    builder = ClaimMaterializeIntentBuilder("knowledge-ingestion-intent.v1")
    first = builder.build(records, access=access, use="u", audience="official")
    assert first == builder.build(records, access=access, use="u", audience="official")
    with pytest.raises(KnowledgeRefused):
        builder.build(
            ReportRecords(HANDLE, DIGEST, "run-77", ()), access=access, use="u", audience="o"
        )


def test_knowledge_apply_names_exactly_one_subject() -> None:
    assert ApplyArgs(decision="kh:b/decision/d@use-decision.v1").report is None
    assert ApplyArgs(report=HANDLE, digest=DIGEST).decision is None
    for bad in ({}, {"decision": "x", "report": HANDLE, "digest": DIGEST}, {"report": HANDLE}):
        with pytest.raises(ValueError):
            ApplyArgs.model_validate(bad)
