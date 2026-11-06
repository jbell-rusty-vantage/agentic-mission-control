"""B4b: a selected pending effect key is an identity, never apply authority."""

from dataclasses import replace

import pytest

from mission_control.application.knowledge.operations import KnowledgeRefused
from mission_control.application.ports.knowledge import RecordedUseDecision
from mission_control.contracts.knowledge_protocol import digest_canonical
from mission_control.domain.knowledge.effects import JournalState, mint_effect_key
from tests.fixtures.knowledge_binding import BINDING
from tests.unit.knowledge.test_gateway import TENANT, call, harness

pytestmark = pytest.mark.asyncio
PIN = "knowledge.knowledge_apply@1"


async def recorded(h, **changes):
    access = h.access()
    row = RecordedUseDecision(
        handle=f"kh:{BINDING}/decision/native@use-decision.v1",
        binding_id=BINDING,
        tenant_id=TENANT,
        use_decision_id="native",
        bound_effect_digest=digest_canonical({"native": 1}),
        processed_epoch=0,
        plan={
            "schemaVersion": "knowledge-ingestion-intent.v1",
            "intentId": "native",
            "context": {"tenantId": TENANT},
            "proposals": [{"kind": "claim.add", "claim": "one"}],
        },
        normalized_values_digest=digest_canonical({}),
        invocation_ref=access.invocation_ref,
    )
    row = replace(row, **changes)
    from mission_control.adapters.knowledge.decisions import InMemoryUseDecisionStore

    h.gateway._decisions = InMemoryUseDecisionStore()
    await h.gateway._decisions.record(access.scope, row)
    return row


async def test_pending_key_lookup_is_read_only_and_identical_to_apply_and_replay():
    h = harness()
    row = await recorded(h)
    access = h.access()
    before = len(h.minter.minted)
    key = await h.gateway.decision_effect_key(row.handle, access, capability_pin=PIN)
    assert key == mint_effect_key(
        access.origin,
        PIN,
        digest_canonical(
            {"useDecisionId": row.use_decision_id, "boundEffectDigest": row.bound_effect_digest}
        ),
    )
    assert h.journal.rows == {} and not h.client.calls
    assert len(h.minter.minted) == before
    first = await h.gateway.apply_decision(
        row.handle, access, capability_pin=PIN, governors=call().governors
    )
    assert first.effect_key == key and first.state is JournalState.APPLIED
    replay = await h.gateway.apply_decision(
        row.handle, access, capability_pin=PIN, governors=call().governors
    )
    assert replay.effect_key == key
    assert len(h.client.calls_of("invoke")) == 1
    assert (
        await h.gateway.existing_decision_effect(row.handle, access, capability_pin=PIN)
    ).effect_key == key


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"binding_id": "foreign"}, "SCOPE_DENIED"),
        ({"tenant_id": "other"}, "SCOPE_DENIED"),
        ({"invocation_ref": "foreign"}, "ORIGIN_MISMATCH"),
        ({"invocation_ref": None}, "ORIGIN_MISMATCH"),
    ],
)
async def test_pending_key_rejects_foreign_or_unbound_native_decisions(changes, code):
    h = harness()
    row = await recorded(h, **changes)
    with pytest.raises(KnowledgeRefused) as refused:
        await h.gateway.decision_effect_key(row.handle, h.access(), capability_pin=PIN)
    assert refused.value.code == code
    assert not h.journal.rows and not h.client.calls


async def test_missing_decision_does_not_mint_a_key():
    h = harness()
    with pytest.raises(KnowledgeRefused) as refused:
        await h.gateway.decision_effect_key("missing", h.access(), capability_pin=PIN)
    assert refused.value.code == "NOT_FOUND"
    assert not h.journal.rows and not h.client.calls


async def test_explicit_pending_candidate_fulfills_after_same_id_approval_double():
    from tests.fixtures.native_receipt_selection import PIN as CUSTOM_PIN
    from tests.fixtures.native_receipt_selection import pending_receipt_case

    case = await pending_receipt_case()
    await case.select()
    key = case.answer["result"]["effect_key"]
    access = case.tools.toolset.access(case.live)
    assert key == await case.tools.toolset.gateway.decision_effect_key(
        case.answer["result"]["decision"], access, capability_pin=CUSTOM_PIN
    )
    assert not case.tools.journal.rows and not case.tools.fake.calls_of("invoke")
    assert (await case.converge()).disposition != "fulfilled"
    _report, pending = await case.tools.toolset.settle_saved(case.live)
    assert pending and not case.tools.journal.rows
    case.bridge.pending = False
    report, pending = await case.tools.toolset.settle_saved(case.live)
    assert not pending
    assert (await case.converge()).disposition == "fulfilled"
    assert report.native_effects[0]["effect_key"] == key
    assert case.selections == 1
    assert len(case.tools.fake.calls_of("invoke")) == 1
    replay, pending = await case.tools.toolset.settle_saved(case.live)
    assert not pending and replay.native_effects[0]["effect_key"] == key
    assert len(case.tools.fake.calls_of("invoke")) == 1
    rows = await case.stack.submissions._store.list_for_invocation(
        access.scope, access.invocation_ref
    )
    assert len(rows) == 1, "settlement did not submit another candidate"


@pytest.mark.parametrize("outcome", ["noop", "partial", "pending"])
async def test_non_applied_receipt_never_fulfills_selected_native_promise(outcome):
    from tests.fixtures.native_receipt_selection import pending_receipt_case

    case = await pending_receipt_case()
    await case.select()
    case.bridge.pending = False
    case.tools.fake.invoke_script.append(outcome)
    await case.tools.toolset.settle_saved(case.live)
    assert (await case.converge()).disposition != "fulfilled"


async def test_foreign_run_receipt_cannot_fulfill_explicit_selection():
    from tests.fixtures.native_receipt_selection import pending_receipt_case

    case = await pending_receipt_case()
    await case.select()
    case.bridge.pending = False
    await case.tools.toolset.settle_saved(case.live)
    scope = case.tools.toolset.access(case.live).scope
    key = case.answer["result"]["effect_key"]
    row = case.tools.journal.rows[(scope, key)]
    origin = row.originating_origin
    case.tools.journal.rows[(scope, key)] = replace(
        row,
        originating_origin=origin.model_copy(
            update={"mission": origin.mission.model_copy(update={"runId": "foreign-run"})}
        ),
    )
    result = await case.converge()
    assert result.disposition != "fulfilled"
    assert any(item.code == "EFFECT_FOREIGN_RUN" for item in result.unmet)


async def test_composed_recovery_callback_uses_the_configured_nondefault_pin():
    from types import SimpleNamespace

    from mission_control.bootstrap.trusted_judgment import compose_native_write
    from tests.fixtures.native_receipt_selection import PIN as CUSTOM_PIN
    from tests.fixtures.native_receipt_selection import pending_receipt_case
    from tests.unit.knowledge.test_native_write import DIGEST, HANDLE, PLAN, Plans

    case = await pending_receipt_case()
    await case.select()
    case.bridge.pending = (
        False  # same-id eligibility double; real KS successor is a separate known gap
    )
    await case.tools.toolset.settle_saved(case.live)
    access = case.tools.toolset.access(case.live)
    composed = compose_native_write(
        SimpleNamespace(_bridge=case.bridge, _plans=Plans()),
        case.tools.toolset.gateway,
        case.stack.store,
        capability_pin=CUSTOM_PIN,
    )
    existing = await composed._existing_effect(case.answer["result"]["decision"], access)
    assert existing.effect_key == case.answer["result"]["effect_key"]

    async def forbidden_apply(handle):
        raise AssertionError("the composed callback must recover this applied effect")

    replay = await composed.write(
        access, HANDLE, DIGEST, plan_reports=PLAN, attempt=2, apply=forbidden_apply
    )
    assert replay.state == "applied" and replay.result.effect_key == existing.effect_key
    assert len(case.tools.fake.calls_of("invoke")) == 1


async def test_stale_successor_never_retargets_the_producers_selected_candidate():
    from tests.fixtures.native_receipt_selection import pending_receipt_case
    from tests.unit.knowledge.test_native_write_recovery import IntentPreview

    case = await pending_receipt_case()
    case.native._preview = IntentPreview()
    await case.select()
    original_key = case.answer["result"]["effect_key"]
    revision_id = case.submission["result"]["revisions"][0]["revision_id"]
    original = await case.stack.store.output_revision(case.stack.host.scope, revision_id)
    case.bridge.pending = False  # same-id eligibility double
    case.tools.fake.invoke_script.append("refuse:STALE_DECISION")
    report, _ = await case.tools.toolset.settle_saved(case.live)
    assert report.native_effects[0]["effect_key"] != original_key
    assert report.native_effects[0]["journal_state"] == "applied"
    unchanged = await case.stack.store.output_revision(case.stack.host.scope, revision_id)
    assert unchanged == original and unchanged.candidate["effect_key"] == original_key
    assert (await case.converge()).disposition != "fulfilled"
    assert case.selections == 1


async def successor_case():
    from tests.fixtures.native_receipt_selection import pending_receipt_case
    from tests.unit.knowledge.test_native_write import RUN_DECISION

    case = await pending_receipt_case()
    await case.select()
    original_resolve = case.bridge.resolve

    async def resolve(access, decision, *, attempt, fresh=False):
        answer = await original_resolve(access, decision, attempt=attempt, fresh=fresh)
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
    return case


async def test_review_successor_authorizes_original_selected_effect_without_rewriting_root():
    case = await successor_case()
    key = case.answer["result"]["effect_key"]
    access = case.tools.toolset.access(case.live)
    roots = await case.bridge.store.for_invocation(access.scope, access.invocation_ref)
    root = roots[0]
    report, pending = await case.tools.toolset.settle_saved(case.live)
    assert not pending and report.native_effects[0]["effect_key"] == key
    assert (await case.converge()).disposition == "fulfilled"
    assert await case.bridge.store.for_invocation(access.scope, access.invocation_ref) == roots
    sent = case.tools.fake.calls_of("invoke")[0].envelope.input.inlinePayload
    assert sent["exactUse"]["useDecisionId"] == root.use_decision_id + "-review"
    assert sent["exactUse"]["boundEffectDigest"] == root.bound_effect_digest
    assert sent["exactUse"]["processedEpoch"] == root.processed_epoch
    assert sent["exactUse"]["normalizedValuesDigest"] == root.normalized_values_digest
    assert {k: v for k, v in sent.items() if k != "exactUse"} == root.plan
    await case.tools.toolset.settle_saved(case.live)
    assert len(case.tools.fake.calls_of("invoke")) == 1 and case.selections == 1


@pytest.mark.parametrize(
    "field", ["requested", "chain", "current", "report", "subject", "use", "audience", "runId"]
)
async def test_successor_resolution_with_foreign_context_never_dispatches(field):
    case = await successor_case()
    original = case.bridge.resolve
    from tests.unit.knowledge.test_native_write import RUN_DECISION

    async def resolve(access, decision, *, attempt, fresh=False):
        answer = await original(access, decision, attempt=attempt, fresh=fresh)
        if decision.id == RUN_DECISION:
            return answer
        value = getattr(answer, field)
        if field == "chain":
            value = (answer.current,)
        elif field in {"requested", "current", "report", "subject"}:
            value = value.model_copy(update={"tenant": "foreign"})
        else:
            value = "foreign"
        return answer.model_copy(update={field: value})

    case.bridge.resolve = resolve
    report, pending = await case.tools.toolset.settle_saved(case.live)
    assert not pending and report.native_effects[0]["refusal_code"] == "STALE_DECISION"
    assert not case.tools.fake.calls_of("invoke") and not case.tools.journal.rows
    assert (await case.converge()).disposition != "fulfilled"


@pytest.mark.parametrize("state", list(JournalState))
async def test_journaled_root_never_accepts_revised_successor_payload(state):
    from mission_control.application.ports.knowledge import PrepareRequest
    from mission_control.contracts.knowledge_protocol import Ref

    h = harness()
    root = await recorded(h)
    access = h.access()
    key = await h.gateway.decision_effect_key(root.handle, access, capability_pin=PIN)
    old = await h.journal.prepare(
        PrepareRequest(
            scope=access.scope,
            effect_key=key,
            semantic_payload_digest=digest_canonical({"original": True}),
            bound_effect_digest=root.bound_effect_digest,
            originating_origin=access.wire_origin(),
            current_caller_origin=access.wire_origin(),
            coordinates=access.coordinates(),
            capability_pin=PIN,
            binding_id=BINDING,
            actor_ref="test",
        )
    )
    h.journal.rows[(access.scope, key)] = replace(old, state=state)
    admission = Ref(
        kind="use_decision",
        id="review-successor",
        version="research-core.use_decision.v2",
        digest=digest_canonical({}),
        binding=BINDING,
        tenant=TENANT,
    )
    result = await h.gateway.apply_native_decision(
        root.handle, access, admission=admission, capability_pin=PIN, governors=call().governors
    )
    assert result.effect_key == key and result.state is state
    assert not h.client.calls_of("invoke") and not h.minter.minted
    assert (
        h.journal.rows[(access.scope, key)].semantic_payload_digest == old.semantic_payload_digest
    )


async def test_competing_prepared_payload_is_not_dispatched_under_successor_authority():
    from mission_control.contracts.knowledge_protocol import Ref

    h = harness()
    root = await recorded(h)
    original_prepare = h.journal.prepare

    async def raced_prepare(request):
        return await original_prepare(
            replace(request, semantic_payload_digest=digest_canonical({"earlier-authority": True}))
        )

    h.journal.prepare = raced_prepare
    admission = Ref(
        kind="use_decision",
        id="review-successor",
        version="research-core.use_decision.v2",
        digest=digest_canonical({}),
        binding=BINDING,
        tenant=TENANT,
    )
    result = await h.gateway.apply_native_decision(
        root.handle, h.access(), admission=admission, capability_pin=PIN, governors=call().governors
    )
    assert result.state is JournalState.PREPARED
    assert not h.client.calls_of("invoke") and not h.minter.minted
