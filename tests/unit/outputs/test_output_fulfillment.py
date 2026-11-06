"""WI-01 / OVE-163: named promises through the ordinary handlers (in-memory 1.7.0 rules).

Each test observes a refused, waiting, pending or fulfilled result of ``submit_output``,
``promote_output``, ``record_assessment``, ``evaluate_frontier``, ``activate_contract_successor``,
``activate_at_boundary`` or ``resolve_missing_submission``; nothing here inspects internals.
"""

from __future__ import annotations

import asyncio
import dataclasses
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from mission_control.application.knowledge.access import InvocationAccess
from mission_control.application.knowledge.effect_receipts import JournalEffectReceipts
from mission_control.application.outputs.fulfillment import (
    AssessmentInput,
    AuthorAccess,
    OutputSetRef,
    PromoteOutput,
)
from mission_control.application.outputs.submission_service import (
    OutputSelection,
    SelectedItem,
    SubmissionService,
)
from mission_control.domain.knowledge.effects import JournalState
from mission_control.domain.outputs.contracts import (
    AdmittedBinding,
    AllOf,
    AnyOf,
    AssessmentLeaf,
    CandidateRef,
    Cardinality,
    CriterionLeaf,
    Enforcement,
    EvaluationScope,
    HumanResolutionLeaf,
    IntegrityLeaf,
    MemberGuarantee,
    MemberRef,
    ObligationLeaf,
    OutputContract,
    OutputForm,
    Requirement,
)
from mission_control.domain.outputs.successors import (
    ContractRevisionProposal,
    RegisteredCandidate,
    TransferSuccessorSeam,
    WeakeningGrant,
    classify_successor,
)
from tests.fixtures.output_contracts import InMemoryOutputContractStore
from tests.unit.knowledge.test_gateway import call as gateway_call
from tests.unit.knowledge.test_gateway import harness as gateway_harness
from tests.unit.knowledge.test_gateway import origin
from tests.unit.outputs.scenario import (
    CLAIMS_SCHEMA,
    INDEX_SCHEMA,
    Stack,
    build_stack,
    code_change,
    codes,
    digest_of,
    eight_forms,
    fulfillment,
    host_access,
    obligation,
    promises,
    schema,
    structured,
    text,
)

pytestmark = pytest.mark.asyncio
AT = datetime(2026, 10, 27, 12, tzinfo=UTC)


def invocation(attempt: int = 1, **updates: object) -> InvocationAccess:
    return InvocationAccess(
        origin=origin(attempt, **updates),
        subject="mission-control-runtime",
        invocation_id=f"inv-{attempt:04d}",
        authenticated_at=AT,
    )


async def make_stack(*obligations, completion=None, **vocab) -> Stack:  # type: ignore[no-untyped-def]
    store = InMemoryOutputContractStore()
    return await build_stack(
        store, store.submissions, invocation(), *obligations, completion=completion, **vocab
    )


async def judge(stack: Stack, revision_id: str, digest: str, **results: str) -> None:
    receipt = await stack.judge(revision_id, digest, **results)
    assert receipt.status == "recorded", receipt.error


INDEXED = obligation(
    "draft.index",
    OutputForm.STRUCTURED,
    schema_pin=schema("report_index@1", INDEX_SCHEMA),
    requirements=(Requirement(key="verified", validator="ks.verify@1", subject="member"),),
    member_contract=MemberGuarantee(pointer="/members", requirement_keys=("verified",)),
)


# ---------------------------------------------------------------- enforcement and omission


async def test_omitted_obligations_are_decided_and_enforcement_separates_block_and_shortfall():
    stack = await make_stack(
        obligation("draft.report", OutputForm.TEXT),
        obligation("draft.appendix", OutputForm.TEXT, enforcement=Enforcement.EXPECTED),
        obligation("draft.notes", OutputForm.TEXT, enforcement=Enforcement.OPTIONAL),
    )
    nothing = await stack.evaluate()
    assert [item.obligation_key for item in nothing.fulfillments] == [
        "draft.report",
        "draft.appendix",
        "draft.notes",
    ]
    assert nothing.completion == "waiting"
    assert nothing.blocking == ("draft.report",)  # required absence blocks
    assert nothing.shortfalls == ("draft.appendix",)  # expected shortfall visible
    assert "draft.notes" not in nothing.shortfalls  # optional absence is silent
    assert codes(nothing, "draft.report") == ["MISSING"]

    ack = await stack.submit("call-1", "draft.report", text("report", "# Findings\n"))
    await stack.accept(ack, "draft.report")
    done = await stack.evaluate()
    assert fulfillment(done, "draft.report").disposition == "fulfilled"
    assert done.completion == "satisfied" and done.blocking == ()
    assert done.shortfalls == ("draft.appendix",)


async def test_text_exact_bytes_and_a_declared_optional_failure_stays_visible():
    stack = await make_stack(
        obligation("draft.report", OutputForm.TEXT, media_type="text/markdown"),
        obligation(
            "draft.notes",
            OutputForm.TEXT,
            enforcement=Enforcement.OPTIONAL,
            requirements=(Requirement(key="cited", validator="mc.validator.citations@1"),),
        ),
    )
    forged = await stack.submit(
        "call-1", "draft.report", text("report", "bytes", digest=digest_of("other"))
    )
    assert forged.status == "refused" and forged.error.code == "DIGEST_MISMATCH"
    wrong_media = await stack.submit(
        "call-2", "draft.report", text("report", "bytes", media_type="text/html")
    )
    assert wrong_media.error.code == "MEDIA_TYPE_MISMATCH"
    notes = await stack.submit("call-3", "draft.notes", text("notes", "unsourced"))
    revision = await stack.accept(notes, "draft.notes")
    await judge(stack, revision, notes.revisions[0].content_digest, cited="fail")
    result = await stack.evaluate()
    assert fulfillment(result, "draft.notes").disposition == "unfulfilled"
    assert "REQUIREMENT_FAILED" in codes(result, "draft.notes")
    assert "draft.notes" in result.shortfalls and "draft.notes" not in result.blocking


# ---------------------------------------------------------------- structured, index, coverage


async def test_structured_schema_version_shape_coverage_and_no_unvalidated_pass():
    stack = await make_stack(*eight_forms()[1:2])
    claims = {"claims": [{"study": "s1", "claim": "c"}]}
    wrong_version = await stack.submit(
        "c1", "draft.claims", structured("claims", claims, schema_ref="claim_table@2")
    )
    assert wrong_version.error.code == "SCHEMA_PIN_MISMATCH"
    wrong_shape = await stack.submit(
        "c2", "draft.claims", structured("claims", {"claims": [{"study": "s1"}]})
    )
    assert wrong_shape.error.code == "SCHEMA_INVALID"
    partial = await stack.submit("c3", "draft.claims", structured("claims", claims))
    await stack.accept(partial, "draft.claims")
    waiting = await stack.evaluate()
    assert codes(waiting, "draft.claims") == ["COVERAGE_INCOMPLETE"]
    complete = {"claims": [{"study": "s1", "claim": "c"}, {"study": "s2", "claim": "d"}]}
    revised = await stack.submit("c4", "draft.claims", structured("claims", complete))
    assert revised.revisions[0].revision == 2  # a revision of the same deliverable
    await stack.accept(revised, "draft.claims")
    done = await stack.evaluate()
    assert fulfillment(done, "draft.claims").disposition == "fulfilled"
    assert fulfillment(done, "draft.claims").distinct_count == 1  # revisions count once
    unvalidated = SubmissionService(
        stack.store.submissions,  # type: ignore[attr-defined]
        contracts=stack.store,
        validate_schema=None,
    )
    refused = await unvalidated.submit_output(
        stack.access,
        stack_request("c5", "draft.claims", structured("claims", complete)),
        position="draft",
    )
    assert refused.error.code == "SCHEMA_UNVALIDATED"  # a bound schema never passes unchecked


def stack_request(key, obligation_key, *items):  # type: ignore[no-untyped-def]
    from mission_control.domain.outputs.contracts import SubmitOutput

    return SubmitOutput(submission_key=key, obligation_key=obligation_key, items=items)


async def test_index_only_output_proves_every_listed_nested_member_guarantee():
    stack = await make_stack(INDEXED)
    refs = [
        {"ref": "kh:aiengineer-postgres/report/r1@research_report.v1", "digest": digest_of("r1")},
        {"ref": "kh:aiengineer-postgres/report/r2@research_report.v1", "digest": digest_of("r2")},
    ]
    loose = await stack.submit(
        "i0",
        "draft.index",
        structured("index", {"members": [{"ref": refs[0]["ref"]}]}, schema_ref="report_index@1"),
    )
    assert loose.error.code == "MEMBER_REF_NOT_EXACT"
    ack = await stack.submit(
        "i1", "draft.index", structured("index", {"members": refs}, schema_ref="report_index@1")
    )
    index = await stack.accept(ack, "draft.index")
    waiting = await stack.evaluate()
    assert codes(waiting, "draft.index") == ["NESTED_GUARANTEE_UNPROVEN"] * 2
    unlisted = await stack.judge(
        "kh:aiengineer-postgres/report/r3@research_report.v1",
        digest_of("r3"),
        kind="member",
        index_revision_id=index,
        verified="pass",
    )
    assert unlisted.error.code == "MEMBER_NOT_LISTED"
    for ref in refs:
        await judge(
            stack,
            ref["ref"],
            ref["digest"],
            kind="member",
            index_revision_id=index,
            verified="pass",
        )
    assert fulfillment(await stack.evaluate(), "draft.index").disposition == "fulfilled"
    with pytest.raises(ValidationError):  # nested keys name the contract's member requirements
        OutputContract(
            form=OutputForm.STRUCTURED,
            schema_pin=schema("report_index@1", INDEX_SCHEMA),
            member_contract=MemberGuarantee(pointer="/members", requirement_keys=("ghost",)),
        )


# ---------------------------------------------------------------- code_change and control_record


async def test_code_change_exact_identity_declared_checks_and_no_inferred_merge():
    stack = await make_stack(*eight_forms()[5:6])
    missing = await stack.submit("p0", "draft.patch", code_change(base=None))
    assert missing.error.code == "MISSING_FIELD"
    other_repo = await stack.submit("p1", "draft.patch", code_change(repository="github.com/x/y"))
    assert other_repo.error.code == "REPOSITORY_MISMATCH"
    with pytest.raises(ValidationError):
        CandidateRef.model_validate(code_change().document() | {"merge": True})
    ack = await stack.submit("p2", "draft.patch", code_change())
    assert ack.status == "accepted" and "merge" not in " ".join(ack.next_actions)
    revision = await stack.accept(ack, "draft.patch")
    waiting = await stack.evaluate()
    assert codes(waiting, "draft.patch") == ["REQUIREMENT_UNASSESSED", "REQUIREMENT_UNASSESSED"]
    await judge(stack, revision, ack.revisions[0].content_digest, tests="pass", lint="pass")
    done = await stack.evaluate()
    assert fulfillment(done, "draft.patch").disposition == "fulfilled"
    stored = await stack.store.output_revision(stack.host.scope, revision)
    assert stored is not None and {"merge", "push", "deploy"}.isdisjoint(stored.candidate)


async def test_control_record_is_attributed_and_grants_no_authority():
    stack = await make_stack(*eight_forms()[7:8])
    claimed = await stack.submit(
        "n0",
        "draft.note",
        structured(
            "note",
            {"finding": "ok", "accept": True},
            schema_ref="finding_note@1",
            form=OutputForm.CONTROL_RECORD,
        ),
    )
    assert claimed.error.code == "SELF_GRANTED_AUTHORITY"
    ack = await stack.submit(
        "n1",
        "draft.note",
        structured(
            "note", {"finding": "gap"}, schema_ref="finding_note@1", form=OutputForm.CONTROL_RECORD
        ),
    )
    revision = await stack.store.output_revision(stack.host.scope, ack.revisions[0].revision_id)
    assert revision is not None and revision.producer_origin_ref == stack.access.invocation_ref


# ---------------------------------------------------------------- collections (WI-07)


async def test_a_promoted_collection_without_member_requirements_is_fulfilled_by_its_shape():
    """WI-07 retired the collection deferral: with no member requirement the exact manifest's
    shape is the promised layer (per-member proofs: tests/unit/outputs/test_collections.py)."""

    stack = await make_stack(*eight_forms())
    candidate = CandidateRef(
        deliverable_id="dataset",
        form=OutputForm.COLLECTION,
        kind="handle",
        ref="kh:aiengineer-postgres/collection/c1@collection.v1",
        digest=digest_of("c1"),
        members=(MemberRef(ref="m1", digest=digest_of("m1")),),
    )
    ack = await stack.submit("k1", "draft.dataset", candidate)
    assert ack.status == "accepted", ack.error
    await stack.accept(ack, "draft.dataset")
    decided = fulfillment(await stack.evaluate(), "draft.dataset")
    assert decided.disposition == "fulfilled" and decided.distinct_count == 1


SOURCE = CandidateRef(
    deliverable_id="source",
    form=OutputForm.REFERENCE,
    kind="handle",
    ref="kh:aiengineer-postgres/report/r9@research_report.v1",
    digest=digest_of("r9"),
)


class _ReferenceUses:
    def __init__(self) -> None:
        self.uses: dict[str, str] = {}

    async def reference_uses(self, scope: str, members):  # type: ignore[no-untyped-def]
        return {
            m.revision_id: self.uses[m.revision_id] for m in members if m.revision_id in self.uses
        }


async def test_a_reference_promise_needs_current_official_use_of_its_exact_revision() -> None:
    """WI-03 (RV-08): an exact handle is not enough; the referenced revision must be usable for
    its official purpose now (a current KS exact-use decision), never a held or stale one."""

    stack = await make_stack(obligation("draft.source", OutputForm.REFERENCE))
    uses = _ReferenceUses()
    stack.outputs._reference_uses = uses  # the composed ReferenceUsePort
    ack = await stack.submit("k1", "draft.source", SOURCE)
    revision_id = await stack.accept(ack, "draft.source")
    unproven = await stack.evaluate()
    assert codes(unproven, "draft.source") == ["REFERENCE_USE_UNPROVEN"]
    assert fulfillment(unproven, "draft.source").unmet[0].owner == "knowledge_service"
    uses.uses[revision_id] = "ks-use-decision:ud-r9-1-rv@sha256:" + "a" * 64
    fulfilled = fulfillment(await stack.evaluate(), "draft.source")
    assert fulfilled.disposition == "fulfilled"
    assert uses.uses[revision_id] in fulfilled.assessment_refs


def _effect_candidate(effect_key: str, receipt_ref: str | None = None) -> CandidateRef:
    return CandidateRef(
        deliverable_id="ingest",
        form=OutputForm.EFFECT_RECEIPT,
        kind="handle",
        ref="kh:aiengineer-postgres/effect/e1@effect.v1",
        digest=digest_of("e1"),
        effect_key=effect_key,
        receipt_ref=receipt_ref,
    )


async def test_an_effect_receipt_promise_is_fulfilled_only_by_the_settled_native_effect() -> None:
    """WI-05 (OC-D117, RV-06): the named effect must have settled applied from its protocol
    receipt. After a lost acknowledgment it is uncertain and waits (never fulfilled from the
    producer's claim); once the reconstructed original receipt settles it, the promise holds."""

    h = gateway_harness()
    stack = await make_stack(obligation("draft.ingest", OutputForm.EFFECT_RECEIPT))
    stack.outputs._effect_receipts = JournalEffectReceipts(h.journal)  # the composed port
    h.client.invoke_script.append("commit_refuse:INTERNAL")
    h.client.lookups.append("unresolved")
    lost = await h.gateway.invoke(gateway_call(), stack.access)
    key = lost.effect_key or ""
    ack = await stack.submit("k1", "draft.ingest", _effect_candidate(key))
    await stack.accept(ack, "draft.ingest")
    waiting = await stack.evaluate()
    assert codes(waiting, "draft.ingest") == ["EFFECT_UNRESOLVED"]
    assert fulfillment(waiting, "draft.ingest").unmet[0].waiting
    settled = await h.gateway.invoke(gateway_call(), stack.access)
    assert settled.journal is not None and settled.journal.terminal_receipt_ref is not None
    fulfilled = fulfillment(await stack.evaluate(), "draft.ingest")
    assert fulfilled.disposition == "fulfilled"
    assert settled.journal.terminal_receipt_ref in fulfilled.assessment_refs
    assert len(h.client.calls_of("invoke")) == 1


async def test_an_effect_receipt_naming_a_rejected_unknown_or_other_receipt_never_fulfills() -> (
    None
):
    h = gateway_harness()
    stack = await make_stack(
        obligation("draft.ingest", OutputForm.EFFECT_RECEIPT, cardinality=Cardinality(min=1, max=3))
    )
    stack.outputs._effect_receipts = JournalEffectReceipts(h.journal)
    h.client.invoke_script.append("refuse:STALE_DECISION")
    rejected = await h.gateway.invoke(gateway_call(), stack.access)
    applied = await h.gateway.invoke(gateway_call(payload={"intent": "other"}), stack.access)
    candidates = (
        _effect_candidate(rejected.effect_key or ""),
        _effect_candidate("effect:never-dispatched").model_copy(
            update={"deliverable_id": "unknown"}
        ),
        _effect_candidate(applied.effect_key or "", receipt_ref="ks-receipt:another").model_copy(
            update={"deliverable_id": "other"}
        ),
    )
    for index, candidate in enumerate(candidates):
        ack = await stack.submit(f"k{index}", "draft.ingest", candidate)
        await stack.accept(ack, "draft.ingest")
    decided = fulfillment(await stack.evaluate(), "draft.ingest")
    assert decided.disposition == "blocked"
    assert [u.code for u in decided.unmet][:3] == ["EFFECT_NOT_APPLIED"] * 3
    assert not any(u.waiting for u in decided.unmet if u.code == "EFFECT_NOT_APPLIED")


class _FixedJournal:
    """A journal answering one settled record (to state the run identity of an effect)."""

    def __init__(self, record):  # type: ignore[no-untyped-def]
        self.record = record

    async def lookup(self, scope, effect_key):  # type: ignore[no-untyped-def]
        return self.record if effect_key == self.record.effect_key else None


@pytest.mark.parametrize(
    ("mission", "code"),
    [
        (None, "EFFECT_ORIGIN_UNPROVEN"),
        ("44444444-4444-4444-8444-444444444444", "EFFECT_FOREIGN_RUN"),
    ],
    ids=["standalone-origin", "forked-or-child-run"],
)
async def test_an_effect_receipt_of_another_run_or_without_a_run_is_refused_typed(
    mission, code
) -> None:
    """WI-05 review: an applied effect fulfills only the run that journaled it. A standalone or
    recovery origin (no mission) refuses ``EFFECT_ORIGIN_UNPROVEN``; another run's effect,
    a fork's or a child's included, refuses ``EFFECT_FOREIGN_RUN`` (never waiting)."""

    h = gateway_harness()
    stack = await make_stack(obligation("draft.ingest", OutputForm.EFFECT_RECEIPT))
    applied = await h.gateway.invoke(gateway_call(), stack.access)
    record = applied.journal
    assert record is not None and record.state is JournalState.APPLIED
    wire = record.originating_origin
    if mission is None:
        origin_doc = wire.model_copy(update={"kind": "standalone", "mission": None})
    else:
        assert wire.mission is not None
        origin_doc = wire.model_copy(
            update={"mission": wire.mission.model_copy(update={"runId": mission})}
        )
    stack.outputs._effect_receipts = JournalEffectReceipts(
        _FixedJournal(dataclasses.replace(record, originating_origin=origin_doc))  # type: ignore[arg-type]
    )
    ack = await stack.submit("k1", "draft.ingest", _effect_candidate(record.effect_key))
    await stack.accept(ack, "draft.ingest")
    decided = fulfillment(await stack.evaluate(), "draft.ingest")
    assert [u.code for u in decided.unmet] == [code]
    assert not decided.unmet[0].waiting


async def test_an_uncomposed_effect_receipt_port_is_a_host_fault_not_a_wait() -> None:
    stack = await make_stack(obligation("draft.ingest", OutputForm.EFFECT_RECEIPT))
    ack = await stack.submit("k1", "draft.ingest", _effect_candidate("effect:any"))
    await stack.accept(ack, "draft.ingest")
    decided = fulfillment(await stack.evaluate(), "draft.ingest")
    assert [u.code for u in decided.unmet] == ["EFFECT_EVIDENCE_UNWIRED"]
    assert decided.unmet[0].owner == "host" and not decided.unmet[0].waiting


class _Realizations:
    def __init__(self) -> None:
        self.realized: dict[str, str] = {}
        self.asked: list[list[str]] = []

    async def file_realizations(self, scope: str, source_refs):  # type: ignore[no-untyped-def]
        self.asked.append(list(source_refs))
        return {ref: self.realized[ref] for ref in source_refs if ref in self.realized}


async def test_a_file_promise_is_fulfilled_only_by_a_receiving_backend_read() -> None:
    """WI-02: custody digest and retention are not enough; the exact file revision must have
    been read back through an actual receiving backend (a transfer member receipt)."""

    stack = await make_stack(*eight_forms())
    realizations = _Realizations()
    stack.outputs._realizations = realizations  # the composed port
    figure = CandidateRef(
        deliverable_id="figure",
        form=OutputForm.FILE,
        kind="path",
        ref="outputs/figure.png",
        digest=digest_of("png"),
        size_bytes=10,
        media_type="image/png",
    )
    ack = await stack.submit("k-file", "draft.figure", figure)
    revision_id = await stack.accept(ack, "draft.figure")
    unrealized = fulfillment(await stack.evaluate(), "draft.figure")
    assert unrealized.disposition != "fulfilled"
    assert [item.code for item in unrealized.unmet] == ["FILE_NOT_REALIZED"]
    realizations.realized[revision_id] = "transfer-receipt:r1#/inputs/fig/1/figure.png"
    realized = fulfillment(await stack.evaluate(), "draft.figure")
    assert realized.disposition == "fulfilled", realized.unmet
    assert realizations.asked[-1] == [revision_id]


# ---------------------------------------------------------------- references and bare ids


async def test_a_bare_id_resolves_only_under_one_exact_admitted_binding():
    stack = await make_stack(*eight_forms()[4:5])
    bare = CandidateRef(
        deliverable_id="source",
        form=OutputForm.REFERENCE,
        kind="native_id",
        ref="report-77",
        native_kind="report",
        digest=digest_of("r77"),
    )
    one = AdmittedBinding(
        binding_id="aiengineer-postgres",
        issuer="ks",
        native_kinds=("report",),
        revision="research_report.v1",
    )
    other = one.model_copy(update={"binding_id": "biotech-graph"})
    none = await stack.submit("r0", "draft.source", bare)
    assert none.error.code == "UNRESOLVED_REFERENCE"
    two = await stack.submit("r1", "draft.source", bare, bindings=(one, other))
    assert two.error.code == "AMBIGUOUS_REFERENCE"
    ack = await stack.submit("r2", "draft.source", bare, bindings=(one,))
    assert ack.status == "accepted" and [f.code for f in ack.findings] == ["bare_id_resolved"]
    revision = await stack.store.output_revision(stack.host.scope, ack.revisions[0].revision_id)
    assert revision is not None
    assert revision.candidate["ref"] == "kh:aiengineer-postgres/report/report-77@research_report.v1"


# ---------------------------------------------------------------- keys, declaration, heads


async def test_changed_key_refuses_and_an_identical_retry_is_the_same_receipt():
    stack = await make_stack(obligation("draft.report", OutputForm.TEXT))
    first = await stack.submit("call-1", "draft.report", text("report", "v1"))
    again = await stack.submit("call-1", "draft.report", text("report", "v1"))
    assert again.submission_id == first.submission_id and again.revisions == first.revisions
    changed = await stack.submit("call-1", "draft.report", text("report", "v2"))
    assert changed.status == "refused" and changed.error.code == "SUBMISSION_CONFLICT"
    await stack.submissions.finalize(stack.access.identity(("draft.report",)))
    replay = await stack.submit("call-1", "draft.report", text("report", "v1"))
    assert replay.submission_id == first.submission_id  # a retry after finalization: receipt
    late = await stack.submit("call-9", "draft.report", text("report", "v3"))
    assert late.error.code == "INVOCATION_FINALIZED"


async def test_undeclared_promise_foreign_or_missing_position_and_unpinned_invocation_refuse():
    stack = await make_stack(obligation("draft.report", OutputForm.TEXT))
    undeclared = await stack.submit("x", "draft.other", text("report", "v1"))
    assert undeclared.error.code == "OBLIGATION_UNDECLARED"
    foreign = await stack.submit("y", "draft.report", text("report", "v1"), position="review")
    assert foreign.error.code == "POSITION_MISMATCH"
    unbound = await stack.submit("u", "draft.report", text("report", "v1"), position=None)
    assert unbound.error.code == "POSITION_UNBOUND"
    too_many = await stack.submit("z", "draft.report", text("a", "1"), text("b", "2"))
    assert too_many.error.code == "CARDINALITY_EXCEEDED"
    unpinned = Stack(
        stack.store, stack.submissions, stack.outputs, invocation(2), stack.host, stack.assessor
    )
    assert (await unpinned.submit("w", "draft.report", text("report", "v1"))).error.code == (
        "INVOCATION_UNPINNED"
    )


async def test_new_drafts_never_replace_the_accepted_head_and_promotion_is_cas():
    stack = await make_stack(obligation("draft.report", OutputForm.TEXT))
    first = await stack.submit("call-1", "draft.report", text("report", "v1"))
    accepted = await stack.accept(first, "draft.report")
    draft = await stack.submit("call-2", "draft.report", text("report", "v2"))
    head = await stack.store.accepted_head(stack.host.scope, stack.run_id, "draft.report", "report")
    assert head is not None and head.revision_id == accepted  # the draft did not move it
    pinned = await stack.outputs.pin_frontier(stack.host, stack.run_id)
    assert [m.revision_id for m in pinned.members] == [accepted]

    def promote(revision_id, expected, generation=1, run_id=None):  # type: ignore[no-untyped-def]
        return stack.outputs.promote_output(
            stack.host,
            PromoteOutput(
                run_id=run_id or stack.run_id,
                revision_id=revision_id,
                expected_head=expected,
                generation=generation,
            ),
        )

    draft_id = draft.revisions[0].revision_id
    assert (await promote(draft_id, None)).error.code == "STALE_HEAD"
    assert (
        await promote(draft_id, accepted, run_id="99999999-9999-4999-8999-999999999999")
    ).error.code == "RUN_MISMATCH"
    assert (await promote(draft_id, accepted, generation=2)).status == "promoted"
    older = await promote(accepted, draft_id, generation=1)
    assert older.error.code == "STALE_GENERATION"
    back = await promote(accepted, draft_id, generation=2)
    assert back.error.code == "OLDER_REVISION"  # an older revision never replaces a newer head


async def test_concurrent_promotions_of_one_deliverable_one_wins():
    stack = await make_stack(obligation("draft.report", OutputForm.TEXT))
    a = await stack.submit("a", "draft.report", text("report", "A"))
    b = await stack.submit("b", "draft.report", text("report", "B"))
    results = await asyncio.gather(
        *(
            stack.outputs.promote_output(
                stack.host,
                PromoteOutput(
                    run_id=stack.run_id, revision_id=ack.revisions[0].revision_id, generation=1
                ),
            )
            for ack in (a, b)
        )
    )
    assert sorted(item.status for item in results) == ["promoted", "refused"]
    assert next(item for item in results if item.status == "refused").error.code == "STALE_HEAD"


async def test_distinct_accepted_deliverables_beyond_the_maximum_block():
    stack = await make_stack(
        obligation("draft.report", OutputForm.TEXT, cardinality=Cardinality(min=1, max=1))
    )
    for name in ("a", "b"):
        await stack.accept(
            await stack.submit(name, "draft.report", text(name, name)), "draft.report"
        )
    result = await stack.evaluate()
    assert codes(result, "draft.report") == ["CARDINALITY_EXCEEDED"]
    assert result.completion == "blocked"


# ---------------------------------------------------------------- assessments


async def test_assessments_never_self_judge_combine_conservatively_and_retry_as_one():
    stack = await make_stack(
        obligation(
            "draft.report",
            OutputForm.TEXT,
            requirements=(
                Requirement(key="grounded", validator="mc.validator.judge@1"),
                Requirement(key="whole", validator="mc.validator.set@1", subject="set"),
            ),
        )
    )
    ack = await stack.submit("call-1", "draft.report", text("report", "v1"))
    revision = await stack.accept(ack, "draft.report")
    digest = ack.revisions[0].content_digest
    before = await stack.outputs.pin_frontier(stack.host, stack.run_id)
    producer = host_access(stack.host.scope, role="assessor", origin=stack.access.invocation_ref)
    own = await stack.outputs.record_assessment(
        producer,
        AssessmentInput(
            run_id=stack.run_id,
            subject_kind="output_set",
            subject_id=before.set_id,
            subject_digest=before.membership_digest,
            requirement_results={"whole": "pass"},
            method_pin="m@1",
            policy_pin="p@1",
        ),
    )
    assert own.error.code == "SELF_ASSESSMENT"  # a member's producer never judges the set
    reconciler = host_access(stack.host.scope, role="reconciler")
    stranger = Stack(
        stack.store, stack.submissions, stack.outputs, stack.access, stack.host, reconciler
    )
    assert (await stranger.judge(revision, digest, grounded="pass")).error.code == (
        "ASSESSOR_UNAUTHORIZED"
    )
    failed = await stack.judge(revision, digest, grounded="fail")
    again = await stack.judge(revision, digest, grounded="fail")
    assert again.assessment.assessment_id == failed.assessment.assessment_id  # retry: same row
    await judge(stack, revision, digest, method_pin="mc.method.other@1", grounded="pass")
    await judge(stack, before.set_id, before.membership_digest, kind="output_set", whole="pass")
    after = await stack.outputs.pin_frontier(stack.host, stack.run_id)
    assert (after.set_id, after.membership_digest) == (before.set_id, before.membership_digest)
    held = await stack.evaluate()
    # A later pass under another method does not silently override the standing failure.
    assert codes(held, "draft.report") == ["REQUIREMENT_FAILED"]
    # WI-03 supersession authority: only the trusted bridge's actor, with KS successor lineage of
    # the decision the failure rested on, supersedes; the failure stands.
    bare = await stack.judge(
        revision, digest, supersedes=failed.assessment.assessment_id, grounded="pass"
    )
    assert bare.error.code == "SUPERSESSION_UNAUTHORIZED"
    assert codes(await stack.evaluate(), "draft.report") == ["REQUIREMENT_FAILED"]


# ---------------------------------------------------------------- closed completion


async def test_completion_is_admitted_with_the_promises_and_names_only_declared_vocabulary():
    report = obligation(
        "draft.report",
        OutputForm.TEXT,
        requirements=(
            Requirement(key="grounded", validator="mc.validator.judge@1"),
            Requirement(key="styled", validator="mc.validator.style@1", required=False),
        ),
    )
    notes = obligation("draft.notes", OutputForm.TEXT, enforcement=Enforcement.OPTIONAL)
    completion = AllOf(
        items=(
            ObligationLeaf(obligation="draft.report"),
            AnyOf(
                items=(
                    ObligationLeaf(obligation="draft.notes"),
                    AssessmentLeaf(
                        obligation="draft.report", requirement="styled", allowed=("pass", "review")
                    ),
                )
            ),
            AnyOf(
                items=(
                    IntegrityLeaf(check="digests"),
                    HumanResolutionLeaf(task="owner-review"),
                    CriterionLeaf(criterion="goal.coverage"),
                )
            ),
        )
    )
    vocab = {
        "integrity_checks": ("digests",),
        "human_tasks": ("owner-review",),
        "criteria": ("goal.coverage",),
    }
    stack = await make_stack(report, notes, completion=completion, **vocab)
    ack = await stack.submit("call-1", "draft.report", text("report", "v1"))
    revision = await stack.accept(ack, "draft.report")
    await judge(stack, revision, ack.revisions[0].content_digest, grounded="pass")
    # The absent optional notes never satisfy the alternative; the styled review is pending.
    assert (await stack.evaluate(facts={"criterion:goal.coverage": True})).completion == "waiting"
    await judge(stack, revision, ack.revisions[0].content_digest, styled="review")
    facts = {"human:owner-review": False, "integrity:digests": False}
    assert (
        await stack.evaluate(facts=facts | {"criterion:goal.coverage": False})
    ).completion == "blocked"
    assert (await stack.evaluate(facts={"criterion:goal.coverage": True})).completion == (
        "satisfied"
    )
    refused = [
        # a required promise that is not a conjunct
        {
            "completion": AnyOf(
                items=(
                    ObligationLeaf(obligation="draft.report"),
                    ObligationLeaf(obligation="draft.notes"),
                )
            )
        },
        # a review disposition over a required requirement (fulfillment decides it by pass)
        {
            "completion": AllOf(
                items=(
                    ObligationLeaf(obligation="draft.report"),
                    AssessmentLeaf(
                        obligation="draft.report", requirement="grounded", allowed=("review",)
                    ),
                )
            )
        },
        # undeclared vocabulary
        {
            "completion": AllOf(
                items=(ObligationLeaf(obligation="draft.report"), IntegrityLeaf(check="ghost"))
            )
        },
        {"completion": ObligationLeaf(obligation="draft.unknown")},
        {"completion": "everything looks good"},
    ]
    for case in refused:
        with pytest.raises(ValidationError):
            promises(report, notes, **case)


# ---------------------------------------------------------------- reminder and association


async def test_one_reminder_one_unambiguous_association_then_not_missing():
    stack = await make_stack(obligation("draft.report", OutputForm.TEXT))
    registered = RegisteredCandidate(
        candidate=text("report", "registered body"), source="registered_output"
    )
    duplicate = registered.model_copy()

    def resolve():  # type: ignore[no-untyped-def]
        return stack.outputs.resolve_missing_submission(
            stack.host, stack.access, "draft.report", (registered, duplicate), position="draft"
        )

    assert (await resolve()).action == "remind"
    associated = await resolve()  # identical duplicates are one candidate, not ambiguity
    assert associated.action == "associate" and associated.ack.status == "accepted"
    assert (await resolve()).action == "not_missing"
    assert await stack.store.association_steps(
        stack.host.scope, stack.access.invocation_ref, "draft.report"
    ) == frozenset({"reminder", "auto_associated"})


async def test_a_named_receipt_associates_only_for_a_capability_the_promise_declares():
    stack = await make_stack(
        obligation(
            "draft.report",
            OutputForm.TEXT,
            receipt_capabilities=("capability:writer@1",),
        )
    )
    foreign = RegisteredCandidate(
        candidate=text("report", "foreign"),
        source="named_capability_receipt",
        capability_ref="capability:other@1",
    )
    named = foreign.model_copy(
        update={"candidate": text("report", "named"), "capability_ref": "capability:writer@1"}
    )
    actions = [
        (
            await stack.outputs.resolve_missing_submission(
                stack.host, stack.access, "draft.report", (foreign, named), position="draft"
            )
        )
        for _ in range(2)
    ]
    assert [item.action for item in actions] == ["remind", "associate"]
    stored = await stack.store.output_revision(
        stack.host.scope, actions[1].ack.revisions[0].revision_id
    )
    assert stored is not None and stored.candidate["text"] == "named"


async def test_ambiguity_gets_one_repair_then_blocks_and_never_guesses():
    stack = await make_stack(obligation("draft.report", OutputForm.TEXT))
    both = (
        RegisteredCandidate(candidate=text("a", "one"), source="registered_output"),
        RegisteredCandidate(candidate=text("b", "two"), source="registered_output"),
    )
    actions = [
        (
            await stack.outputs.resolve_missing_submission(
                stack.host, stack.access, "draft.report", both, position="draft"
            )
        ).action
        for _ in range(3)
    ]
    assert actions == ["remind", "request_repair", "block"]
    assert stack.store.submissions.rows == {}  # type: ignore[attr-defined]


async def test_no_matching_candidate_blocks_after_the_one_reminder():
    stack = await make_stack(obligation("draft.report", OutputForm.TEXT))
    wrong_form = RegisteredCandidate(candidate=code_change("change-1"), source="registered_output")
    actions = [
        (
            await stack.outputs.resolve_missing_submission(
                stack.host, stack.access, "draft.report", (wrong_form,), position="draft"
            )
        ).action
        for _ in range(3)
    ]
    assert actions == ["remind", "block", "block"]


# ---------------------------------------------------------------- governed successors


def proposal(stack: Stack, successor, **extra):  # type: ignore[no-untyped-def]
    values = {
        "run_id": stack.run_id,
        "obligation_key": successor.key,
        "expected_prior_revision": successor.revision - 1,
        "successor": successor,
        "actor_id": "owner",
        "actor_role": "author",
        "reason": "the review needs two reports",
        "delegation_ref": "delegation:owner",
        "boundary": "between_iterations",
        "boundary_ref": "iteration:3",
    } | extra
    return ContractRevisionProposal(**values)


def author(stack: Stack, *grants: WeakeningGrant, role: str = "author") -> AuthorAccess:
    return AuthorAccess(
        scope=stack.host.scope,
        actor_id="owner" if role == "author" else "agent",
        role=role,  # type: ignore[arg-type]
        delegation_refs=frozenset({"delegation:owner"}),
        weakening_grants=grants,
    )


async def test_in_flight_invocations_keep_their_pin_and_a_successor_waits_for_its_boundary():
    prior = obligation("draft.report", OutputForm.TEXT, cardinality=Cardinality(min=1, max=2))
    stack = await make_stack(prior)
    tighter = prior.model_copy(update={"revision": 2, "cardinality": Cardinality(min=2, max=2)})
    pending = await stack.outputs.activate_contract_successor(
        author(stack), proposal(stack, tighter)
    )
    assert pending.status == "pending" and pending.tightenings
    # Not yet active: a new invocation still pins revision 1 until the boundary is reached.
    assert (await stack.store.invocation_pins(stack.host.scope, stack.access.invocation_ref)) == {
        "draft.report": 1
    }
    in_flight = await stack.submit("call-1", "draft.report", text("report", "v1"))
    wrong = await stack.outputs.activate_at_boundary(
        stack.host, stack.run_id, boundary="between_stages", boundary_ref="stage:b"
    )
    assert wrong == ()  # a boundary of another kind activates nothing
    activated = await stack.outputs.activate_at_boundary(
        stack.host, stack.run_id, boundary="between_iterations", boundary_ref="iteration:3"
    )
    assert [item.revision for item in activated] == [2]
    # The in-flight invocation keeps revision 1: its next draft is still judged under 1.
    later_draft = await stack.submit("call-2", "draft.report", text("report", "v2"))
    stored = await stack.store.output_revision(
        stack.host.scope, later_draft.revisions[0].revision_id
    )
    assert stored is not None and stored.obligation_revision == 1
    await stack.accept(in_flight, "draft.report")
    # A new invocation after the boundary pins revision 2.
    after = await stack.start(invocation(2))
    assert (await after.store.invocation_pins(after.host.scope, after.access.invocation_ref)) == {
        "draft.report": 2
    }
    fresh = await after.submit("call-1", "draft.report", text("report2", "x"))
    fresh_revision = await stack.store.output_revision(
        stack.host.scope, fresh.revisions[0].revision_id
    )
    assert fresh_revision is not None and fresh_revision.obligation_revision == 2


async def test_successors_weaken_only_with_scoped_authority_and_fail_closed():
    prior = obligation("draft.report", OutputForm.TEXT, cardinality=Cardinality(min=1, max=2))
    stack = await make_stack(prior)
    weaker = prior.model_copy(update={"revision": 2, "enforcement": Enforcement.EXPECTED})
    unauthorized = await stack.outputs.activate_contract_successor(
        author(stack), proposal(stack, weaker)
    )
    assert unauthorized.error.code == "WEAKENING_UNAUTHORIZED"
    other_run = WeakeningGrant(ref="grant:1", scope=stack.host.scope, run_id="another-run")
    misplaced = await stack.outputs.activate_contract_successor(
        author(stack, other_run), proposal(stack, weaker, weakening_authority_ref="grant:1")
    )
    assert misplaced.error.code == "WEAKENING_UNAUTHORIZED"  # a grant for another run
    own = WeakeningGrant(ref="grant:1", scope=stack.host.scope, run_id=stack.run_id)
    waiver = await stack.outputs.activate_contract_successor(
        author(stack, own, role="executor"),
        proposal(
            stack,
            weaker,
            actor_id="agent",
            actor_role="executor",
            weakening_authority_ref="grant:1",
        ),
    )
    assert waiver.error.code == "SELF_WAIVER"
    undelegated = await stack.outputs.activate_contract_successor(
        author(stack, own), proposal(stack, weaker, delegation_ref="delegation:nobody")
    )
    assert undelegated.error.code == "DELEGATION_REQUIRED"
    with pytest.raises(ValidationError):  # every proposal records its delegation
        proposal(stack, weaker, delegation_ref=None)
    unsafe = await stack.outputs.activate_contract_successor(
        author(stack), proposal(stack, weaker, boundary="mid_invocation")
    )
    assert unsafe.error.code == "UNSAFE_BOUNDARY"
    seam = await stack.outputs.activate_contract_successor(
        author(stack),
        proposal(
            stack,
            weaker,
            transfer_successor=TransferSuccessorSeam(
                transfer_policy_ref="report-review@v1", expected_prior_digest=digest_of("t")
            ),
        ),
    )
    assert seam.error.code == "TRANSFER_SUCCESSOR_UNSUPPORTED"
    granted = await stack.outputs.activate_contract_successor(
        author(stack, own), proposal(stack, weaker, weakening_authority_ref="grant:1")
    )
    assert granted.status == "pending" and granted.weakenings
    again = await stack.outputs.activate_contract_successor(
        author(stack, own), proposal(stack, weaker, weakening_authority_ref="grant:1")
    )
    assert again.error.code == "STALE_REVISION"  # one pending successor per revision
    # Fail closed: an unclassified change anywhere is a weakening.
    scoped = prior.model_copy(update={"revision": 2, "evaluation_scope": EvaluationScope.MISSION})
    assert classify_successor(prior, scoped).weakenings == ("evaluation_scope changed",)
    bounded = prior.model_copy(
        update={"revision": 2, "contract": prior.contract.model_copy(update={"max_bytes": 10})}
    )
    assert classify_successor(prior, bounded).weakenings == ("contract.max_bytes changed",)


# ---------------------------------------------------------------- finalization


async def test_finalization_never_falls_back_to_submitted_rows_or_counts_them():
    store = InMemoryOutputContractStore()
    service = SubmissionService(store.submissions)
    access = invocation()
    item = SelectedItem(kind="path", ref="outputs/r.md", digest=digest_of("r"))
    await service.submit(access, "report", OutputSelection(items=(item,)), "call-1")
    undeclared = await service.finalize(access.identity())
    assert (undeclared.outcome, undeclared.outcome_basis) == (
        "unfulfilled",
        "no_declared_obligations",
    )
    assert undeclared.obligations == ()
    other = invocation(2)
    await service.submit(other, "report", OutputSelection(items=(item,)), "call-1")
    covered = await service.finalize(other.identity(("report",)))
    # A submitted row is coverage, never fulfillment: no verdict, no fulfilled outcome.
    assert (covered.outcome, covered.outcome_basis) == ("unfulfilled", "declared_obligations")
    assert covered.obligations[0].covered is True


async def test_the_legacy_selection_path_refuses_once_promises_are_registered():
    stack = await make_stack(obligation("draft.report", OutputForm.TEXT))
    from mission_control.application.outputs.submission_service import PromisesRegistered

    item = SelectedItem(kind="path", ref="outputs/r.md", digest=digest_of("r"))
    with pytest.raises(PromisesRegistered):
        await stack.submissions.submit(
            stack.access, "draft.report", OutputSelection(items=(item,)), "call-1"
        )


async def test_evaluate_frontier_uses_the_admitted_completion_only():
    stack = await make_stack(obligation("draft.report", OutputForm.TEXT))
    pinned = await stack.outputs.pin_frontier(stack.host, stack.run_id)
    with pytest.raises(TypeError):
        await stack.outputs.evaluate_frontier(  # type: ignore[call-arg]
            stack.host,
            OutputSetRef(run_id=stack.run_id, set_id=pinned.set_id),
            promises=promises(obligation("draft.report", OutputForm.TEXT)),
        )
    assert CLAIMS_SCHEMA  # the shared fixtures stay importable


async def test_a_tightening_that_breaks_the_admitted_completion_is_refused():
    report = obligation("draft.report", OutputForm.TEXT)
    appendix = obligation("draft.appendix", OutputForm.TEXT, enforcement=Enforcement.EXPECTED)
    notes = obligation("draft.notes", OutputForm.TEXT, enforcement=Enforcement.OPTIONAL)
    completion = AllOf(
        items=(
            ObligationLeaf(obligation="draft.report"),
            AnyOf(
                items=(
                    ObligationLeaf(obligation="draft.appendix"),
                    ObligationLeaf(obligation="draft.notes"),
                )
            ),
        )
    )
    stack = await make_stack(report, appendix, notes, completion=completion)
    required = appendix.model_copy(update={"revision": 2, "enforcement": Enforcement.REQUIRED})
    refused = await stack.outputs.activate_contract_successor(
        author(stack), proposal(stack, required)
    )
    # expected -> required inside an any() would leave a required promise that is not a
    # conjunct, so blocking and a satisfied completion could coexist.
    assert refused.status == "refused"
    assert refused.error.code == "SUCCESSOR_BREAKS_COMPLETION"
    assert refused.tightenings == ("enforcement expected->required",)
    assert (await stack.evaluate()).completion == "waiting"  # the admitted set is unchanged


async def test_only_the_host_reports_a_reached_boundary():
    stack = await make_stack(obligation("draft.report", OutputForm.TEXT))
    refused = await stack.outputs.activate_at_boundary(
        stack.assessor, stack.run_id, boundary="between_iterations", boundary_ref="iteration:1"
    )
    assert refused.code == "HOST_REQUIRED"  # type: ignore[union-attr]
