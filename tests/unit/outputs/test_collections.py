"""WI-07 / OVE-170: report collections assessed per member and accumulated current sets.

Through the ordinary handlers (in-memory 1.7.0 rules, ``tests/fixtures/output_contracts.py``):
per-member judgments with each member's exact ref and digest, the authored aggregate rule,
mixed held/accepted/rejected members, identity versus revisions, missing coverage, duplicate and
reordered inputs, concurrent head promotion, host promotion of a member-judged collection only
on the verifier's acceptance, and the goal-wide current-set index. The PostgreSQL proof of the
same behaviors is ``tests/integration/postgres/test_wi07_collections_postgres.py``.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from mission_control.application.knowledge.access import InvocationAccess
from mission_control.application.outputs.fulfillment import PromoteOutput
from mission_control.domain.outputs.contracts import (
    CandidateRef,
    Cardinality,
    CoverageContract,
    EvaluationScope,
    MemberRef,
    OutputContract,
    OutputForm,
    OutputObligation,
    Requirement,
    collection_digest,
)
from mission_control.domain.outputs.current_set import build_current_set_index
from tests.fixtures.output_contracts import InMemoryOutputContractStore
from tests.unit.knowledge.test_gateway import origin
from tests.unit.outputs.scenario import (
    TRUSTED_VALIDATORS,
    Stack,
    build_stack,
    codes,
    digest_of,
    fulfillment,
    obligation,
    text,
)

pytestmark = pytest.mark.asyncio
AT = datetime(2026, 10, 28, 12, tzinfo=UTC)
# A host-checkable member validator; the trusted-judgment pin is proven only by KS (review B2).
VERIFIED = Requirement(key="verified", validator="mc.check.member-verified@1", subject="member")
TRUSTED_PIN = "knowledge.report.assess@1"


def invocation(attempt: int = 1, **updates: object) -> InvocationAccess:
    return InvocationAccess(
        origin=origin(attempt, **updates),
        subject="mission-control-runtime",
        invocation_id=f"inv-{attempt:04d}-"
        + str(updates.get("operation_id", "op")).replace("/", "-"),
        authenticated_at=AT,
    )


def report(name: str) -> MemberRef:
    return MemberRef(
        ref=f"kh:aiengineer-postgres/report/{name}@research_report.v2", digest=digest_of(name)
    )


def collection(
    deliverable: str = "reports",
    members: tuple[MemberRef, ...] = (),
    *,
    subjects: dict[str, str] | None = None,
) -> CandidateRef:
    value: Any = None
    if subjects is not None:
        value = {
            "entries": [
                {"ref": item.ref, "digest": item.digest, "subject": subjects[item.ref]}
                for item in members
                if item.ref in subjects
            ]
        }
    return CandidateRef(
        deliverable_id=deliverable,
        form=OutputForm.COLLECTION,
        kind="inline",
        value=value if value is not None else {"kind": "report_collection"},
        members=members,
        digest=collection_digest(
            members, value if value is not None else {"kind": "report_collection"}
        ),
    )


def collection_promise(
    *,
    aggregate: dict[str, Any] | None = None,
    coverage: CoverageContract | None = None,
    validator: str | None = None,
    required: bool = True,
) -> OutputObligation:
    requirement = VERIFIED.model_copy(
        update={
            "parameters": aggregate or {},
            "validator": validator or VERIFIED.validator,
            "required": required,
        }
    )
    return obligation(
        "draft.reports",
        OutputForm.COLLECTION,
        requirements=(requirement,),
        coverage=coverage,
    )


async def make_stack(*obligations: OutputObligation) -> Stack:
    store = InMemoryOutputContractStore()
    return await build_stack(store, store.submissions, invocation(), *obligations)


async def member_verdict(stack: Stack, index_revision: str, member: MemberRef, result: str) -> Any:
    return await stack.judge(
        member.ref, member.digest, kind="member", index_revision_id=index_revision, verified=result
    )


# ---------------------------------------------------------------- contract shape


def test_collection_member_requirements_name_a_closed_aggregate_rule() -> None:
    assert collection_promise().contract.form is OutputForm.COLLECTION
    collection_promise(aggregate={"aggregate": "at_least", "minimum": 2})
    for bad in (
        {"aggregate": "most"},
        {"aggregate": "at_least"},
        {"aggregate": "at_least", "minimum": 0},
        {"aggregate": "all", "minimum": 2},
    ):
        with pytest.raises(ValidationError, match="aggregate"):
            collection_promise(aggregate=bad)
    with pytest.raises(ValidationError, match="coverage applies"):
        OutputContract(
            form=OutputForm.TEXT,
            coverage=CoverageContract(subjects=("a",), pointer="/x"),
        )


# ---------------------------------------------------------------- per-member assessment


async def test_mixed_held_accepted_rejected_members_block_an_all_rule_member_by_member() -> None:
    stack = await make_stack(collection_promise())
    a, b, c, d = (report(name) for name in "abcd")
    ack = await stack.submit("k1", "draft.reports", collection(members=(a, b, c, d)))
    assert ack.status == "accepted", ack.error
    manifest = await stack.accept(ack, "draft.reports")
    assert (await member_verdict(stack, manifest, a, "pass")).status == "recorded"
    await member_verdict(stack, manifest, b, "review")
    await member_verdict(stack, manifest, c, "fail")
    result = await stack.evaluate()
    decided = fulfillment(result, "draft.reports")
    assert decided.disposition == "unfulfilled" and result.completion == "waiting"
    assert sorted(codes(result, "draft.reports")) == [
        "MEMBER_HELD",
        "MEMBER_REJECTED",
        "MEMBER_UNASSESSED",
    ]
    assert all(a.ref not in item.message for item in decided.unmet)  # the passing one is fine


async def test_one_member_never_attests_another_nor_does_the_manifest_or_the_set() -> None:
    stack = await make_stack(collection_promise())
    a, b = report("a"), report("b")
    ack = await stack.submit("k1", "draft.reports", collection(members=(a, b)))
    manifest = await stack.accept(ack, "draft.reports")
    # The first member's pass is bound to its own exact ref and digest only.
    await member_verdict(stack, manifest, a, "pass")
    # A judgment of the manifest revision is not a member judgment.
    await stack.judge(manifest, ack.revisions[0].content_digest, verified="pass")
    # A member the manifest does not list, or a listed ref with another digest, refuses.
    stranger = await member_verdict(stack, manifest, report("z"), "pass")
    assert stranger.status == "refused" and stranger.error.code == "MEMBER_NOT_LISTED"
    forged = await member_verdict(
        stack, manifest, MemberRef(ref=b.ref, digest=digest_of("other")), "pass"
    )
    assert forged.error.code == "MEMBER_NOT_LISTED"
    result = await stack.evaluate()
    assert codes(result, "draft.reports") == ["MEMBER_UNASSESSED"]
    assert b.ref in fulfillment(result, "draft.reports").unmet[0].message
    await member_verdict(stack, manifest, b, "pass")
    assert fulfillment(await stack.evaluate(), "draft.reports").disposition == "fulfilled"


async def test_the_producer_never_assesses_its_own_members() -> None:
    stack = await make_stack(collection_promise())
    a = report("a")
    ack = await stack.submit("k1", "draft.reports", collection(members=(a,)))
    manifest = await stack.accept(ack, "draft.reports")
    from dataclasses import replace

    producer = replace(
        stack, assessor=replace(stack.assessor, origin_ref=stack.access.invocation_ref)
    )
    refused = await member_verdict(producer, manifest, a, "pass")
    assert refused.status == "refused" and refused.error.code == "SELF_ASSESSMENT"


async def test_an_authored_at_least_rule_permits_partial_success_and_keeps_members_visible() -> (
    None
):
    stack = await make_stack(collection_promise(aggregate={"aggregate": "at_least", "minimum": 2}))
    a, b, c = report("a"), report("b"), report("c")
    ack = await stack.submit("k1", "draft.reports", collection(members=(a, b, c)))
    manifest = await stack.accept(ack, "draft.reports")
    await member_verdict(stack, manifest, a, "pass")
    await member_verdict(stack, manifest, b, "fail")
    short = await stack.evaluate()
    assert codes(short, "draft.reports") == ["AGGREGATE_SHORT"]
    assert fulfillment(short, "draft.reports").unmet[0].waiting  # c may still pass
    await member_verdict(stack, manifest, c, "fail")
    unreachable = await stack.evaluate()
    assert fulfillment(unreachable, "draft.reports").disposition == "blocked"
    await member_verdict(stack, manifest, c, "pass")  # a second standing judgment: worst wins
    still = await stack.evaluate()
    assert fulfillment(still, "draft.reports").disposition == "blocked"


async def test_at_least_rule_is_fulfilled_with_a_held_member_visible_in_the_index() -> None:
    stack = await make_stack(collection_promise(aggregate={"aggregate": "at_least", "minimum": 2}))
    a, b, c = report("a"), report("b"), report("c")
    ack = await stack.submit("k1", "draft.reports", collection(members=(a, b, c)))
    manifest = await stack.accept(ack, "draft.reports")
    for member, verdict in ((a, "pass"), (b, "pass"), (c, "review")):
        await member_verdict(stack, manifest, member, verdict)
    result = await stack.evaluate()
    assert fulfillment(result, "draft.reports").disposition == "fulfilled"
    index = await _index(stack)
    (promise,) = index.promises
    labels = {item.ref: item.label for item in promise.heads[0].members}
    assert labels == {a.ref: "accepted", b.ref: "accepted", c.ref: "held"}


# ---------------------------------------------------------------- coverage, identity, inputs


async def test_missing_coverage_is_visible_and_only_passing_members_cover() -> None:
    coverage = CoverageContract(subjects=("m-a", "m-b", "m-c"), pointer="/entries", key="subject")
    stack = await make_stack(collection_promise(coverage=coverage))
    a, b = report("a"), report("b")
    subjects = {a.ref: "m-a", b.ref: "m-b"}
    ack = await stack.submit("k1", "draft.reports", collection(members=(a, b), subjects=subjects))
    manifest = await stack.accept(ack, "draft.reports")
    await member_verdict(stack, manifest, a, "pass")
    await member_verdict(stack, manifest, b, "review")
    result = await stack.evaluate()
    decided = fulfillment(result, "draft.reports")
    coverage_gap = next(item for item in decided.unmet if item.code == "COVERAGE_INCOMPLETE")
    assert "m-b" in coverage_gap.message and "m-c" in coverage_gap.message
    assert "m-a" not in coverage_gap.message
    index = await _index(stack)
    assert index.promises[0].missing_coverage == ("m-b", "m-c")
    # A coverage entry must name a listed member exactly.
    stray = await stack.submit(
        "k2",
        "draft.reports",
        CandidateRef(
            deliverable_id="reports",
            form=OutputForm.COLLECTION,
            kind="inline",
            members=(a,),
            value={"entries": [{"ref": b.ref, "digest": b.digest, "subject": "m-b"}]},
            digest=collection_digest(
                (a,), {"entries": [{"ref": b.ref, "digest": b.digest, "subject": "m-b"}]}
            ),
        ),
    )
    assert stray.status == "refused" and stray.error.code == "MEMBER_NOT_LISTED"


async def test_revisions_never_increase_the_distinct_count_across_iterations() -> None:
    reports = obligation(
        "draft.reports",
        OutputForm.TEXT,
        cardinality=Cardinality(min=3, max=5),
    ).model_copy(update={"evaluation_scope": EvaluationScope.GOAL})
    stack = await make_stack(reports)
    first = await stack.submit("i1", "draft.reports", text("report-a", "A v1"))
    await stack.accept(first, "draft.reports")
    second = await stack.submit("i2", "draft.reports", text("report-b", "B v1"))
    await stack.accept(second, "draft.reports")
    revised = await stack.submit("i3", "draft.reports", text("report-a", "A v2"))
    assert revised.revisions[0].revision == 2
    await stack.accept(revised, "draft.reports")
    short = await stack.evaluate()
    decided = fulfillment(short, "draft.reports")
    assert decided.distinct_count == 2 and codes(short, "draft.reports") == ["CARDINALITY_SHORT"]
    third = await stack.submit("i4", "draft.reports", text("report-c", "C v1"))
    await stack.accept(third, "draft.reports")
    done = await stack.evaluate()
    assert fulfillment(done, "draft.reports").distinct_count == 3
    assert fulfillment(done, "draft.reports").disposition == "fulfilled"
    heads = {item.deliverable_id: item.revision for item in (await _index(stack)).promises[0].heads}
    assert heads == {"report-a": 2, "report-b": 1, "report-c": 1}


async def test_duplicate_and_reordered_inputs_are_the_same_content_or_refused() -> None:
    stack = await make_stack(collection_promise())
    a, b = report("a"), report("b")
    forward = collection(members=(a, b))
    backward = collection(members=(b, a))
    assert forward.digest == backward.digest  # the member set, not its order
    duplicated = await stack.submit(
        "k0",
        "draft.reports",
        CandidateRef(
            deliverable_id="reports",
            form=OutputForm.COLLECTION,
            kind="inline",
            value={"kind": "report_collection"},
            members=(a, a),
            digest=collection_digest((a, a), {"kind": "report_collection"}),
        ),
    )
    assert duplicated.error.code == "DUPLICATE_DELIVERABLE"
    forged = await stack.submit(
        "k0b", "draft.reports", forward.model_copy(update={"digest": digest_of("x")})
    )
    assert forged.error.code == "DIGEST_MISMATCH"
    one = await stack.submit("k1", "draft.reports", forward)
    replay = await stack.submit("k1", "draft.reports", forward)
    assert replay.submission_id == one.submission_id
    other_order = await stack.submit("k1", "draft.reports", backward)
    assert other_order.error.code == "SUBMISSION_CONFLICT"  # one key binds one payload
    again = await stack.submit("k2", "draft.reports", backward)
    assert again.revisions[0].content_digest == one.revisions[0].content_digest
    manifest = await stack.accept(one, "draft.reports")
    for member in (a, b):
        await member_verdict(stack, manifest, member, "pass")
    await stack.accept(again, "draft.reports")  # the same members: judgments still apply
    result = await stack.evaluate()
    assert fulfillment(result, "draft.reports").disposition == "fulfilled"
    assert fulfillment(result, "draft.reports").distinct_count == 1
    # Two items for one deliverable in one act refuse.
    twice = await stack.submit("k3", "draft.reports", forward, backward)
    assert twice.error.code == "DUPLICATE_DELIVERABLE"


# ---------------------------------------------------------------- heads under concurrency


async def test_concurrent_promotions_of_one_deliverable_promote_exactly_once() -> None:
    stack = await make_stack(collection_promise())
    acks = [
        await stack.submit(f"k{n}", "draft.reports", collection(members=(report(f"r{n}"),)))
        for n in range(4)
    ]
    results = await asyncio.gather(
        *(
            stack.outputs.promote_output(
                stack.host,
                PromoteOutput(
                    run_id=stack.run_id, revision_id=ack.revisions[0].revision_id, generation=1
                ),
            )
            for ack in acks
        )
    )
    assert sorted(item.status for item in results) == ["promoted", "refused", "refused", "refused"]
    assert {item.error.code for item in results if item.error is not None} == {"STALE_HEAD"}


# ---------------------------------------------------------------- host promotion at convergence


async def test_convergence_promotes_a_member_judged_collection_only_on_acceptance() -> None:
    stack = await make_stack(collection_promise())
    executor = invocation(operation_id="goal-iteration/1/executor")
    worker = await stack.start(executor)
    a, b = report("a"), report("b")
    ack = await worker.submit("k1", "draft.reports", collection(members=(a, b)))
    await stack.submissions.finalize(executor.identity(("draft.reports",)))
    manifest = ack.revisions[0].revision_id
    await member_verdict(stack, manifest, a, "pass")  # b is not judged yet
    held = await stack.outputs.converge(
        stack.host, stack.run_id, operation_ref=executor.origin.operation_id, generation=1
    )
    assert held is not None and fulfillment(held, "draft.reports").disposition == "unfulfilled"
    assert codes(held, "draft.reports") == [
        "SUBMITTED_NOT_ACCEPTED"
    ]  # one member never promotes the rest
    await member_verdict(stack, manifest, b, "pass")
    rejected_iteration = await stack.outputs.converge(
        stack.host,
        stack.run_id,
        operation_ref=executor.origin.operation_id,
        generation=1,
        promote=False,
    )
    assert codes(rejected_iteration, "draft.reports") == ["SUBMITTED_NOT_ACCEPTED"]
    accepted = await stack.outputs.converge(
        stack.host, stack.run_id, operation_ref=executor.origin.operation_id, generation=1
    )
    assert fulfillment(accepted, "draft.reports").disposition == "fulfilled"
    assert accepted.completion == "satisfied"


# ---------------------------------------------------------------- the current-set index


async def test_the_index_names_heads_and_labels_held_rejected_and_pending_candidates() -> None:
    reports = obligation(
        "draft.reports",
        OutputForm.TEXT,
        cardinality=Cardinality(min=3, max=5),
        requirements=(Requirement(key="assessed", validator="knowledge.report.assess@1"),),
    )
    stack = await make_stack(reports)
    executor = invocation(operation_id="goal-iteration/1/executor")
    worker = await stack.start(executor)
    acks = {
        name: await worker.submit(f"k-{name}", "draft.reports", text(f"report-{name}", name))
        for name in ("a", "b", "c", "d")
    }
    await stack.submissions.finalize(executor.identity(("draft.reports",)))
    for name, verdict in (("a", "pass"), ("b", "review"), ("c", "fail")):
        revision = acks[name].revisions[0]
        await stack.judge(revision.revision_id, revision.content_digest, assessed=verdict)
    await stack.accept(acks["a"], "draft.reports")
    index = await _index(stack)
    (promise,) = index.promises
    assert [(h.deliverable_id, h.label) for h in promise.heads] == [("report-a", "accepted")]
    assert [(c.deliverable_id, c.label) for c in promise.candidates] == [
        ("report-b", "held"),
        ("report-c", "rejected"),
        ("report-d", "pending"),
    ]
    assert promise.distinct_count == 1 and promise.gaps[0].startswith("1 of at least 3")
    rendered = index.render()
    assert rendered == (await _index(stack)).render()  # same set and judgments, same bytes
    assert b'"schema_version":"mc.current_set_index.v1"' in rendered


async def _index(stack: Stack):  # type: ignore[no-untyped-def]
    pinned = await stack.outputs.pin_frontier(stack.host, stack.run_id)
    obligations = [
        await stack.store.obligation_revision(stack.host.scope, stack.run_id, key, revision)
        for key, revision in pinned.obligation_refs
    ]
    return build_current_set_index(
        stack.run_id,
        [item for item in obligations if item is not None],
        pinned,
        await stack.store.output_assessments(stack.host.scope, stack.run_id),
        await stack.store.finalized_outputs(stack.host.scope, stack.run_id),
        trusted_validators=TRUSTED_VALIDATORS,
    )


# ---------------------------------------------------------------- review fixes B1, B2, S2


async def _converge(stack: Stack, executor: InvocationAccess, *, promote: bool = True) -> Any:
    return await stack.outputs.converge(
        stack.host,
        stack.run_id,
        operation_ref=executor.origin.operation_id,
        generation=1,
        promote=promote,
    )


async def _submitted_manifest(stack: Stack, *members: MemberRef) -> tuple[InvocationAccess, str]:
    executor = invocation(operation_id="goal-iteration/1/executor")
    worker = await stack.start(executor)
    ack = await worker.submit("k1", "draft.reports", collection(members=members))
    assert ack.status == "accepted", ack.error
    await stack.submissions.finalize(executor.identity(("draft.reports",)))
    return executor, ack.revisions[0].revision_id


async def test_an_optional_only_collection_never_auto_promotes_unjudged() -> None:
    """B1: any declared requirement belongs to the assessment path (fix D); an optional-only
    member requirement is not a reason to promote with no judgment at all."""

    stack = await make_stack(collection_promise(required=False))
    executor, _manifest = await _submitted_manifest(stack, report("a"), report("b"))
    result = await _converge(stack, executor)
    assert codes(result, "draft.reports") == ["SUBMITTED_NOT_ACCEPTED"]
    assert await stack.store.accepted_outputs(stack.host.scope, stack.run_id) == ()


async def test_a_host_pass_never_proves_a_trusted_pinned_member_requirement() -> None:
    """B2: under the trusted-judgment pin only a standing member assessment citing an exact KS
    decision counts; host passes keep the collection waiting (truthful), never promoted."""

    from mission_control.application.outputs.fulfillment import AssessmentInput, HostAccess
    from mission_control.domain.knowledge.judgment import TRUSTED_BRIDGE_ACTOR, decision_evidence

    stack = await make_stack(collection_promise(validator=TRUSTED_PIN))
    a, b = report("a"), report("b")
    executor, manifest = await _submitted_manifest(stack, a, b)
    for member in (a, b):
        assert (await member_verdict(stack, manifest, member, "pass")).status == "recorded"
    waiting = await _converge(stack, executor)
    assert sorted(codes(waiting, "draft.reports")) == ["SUBMITTED_NOT_ACCEPTED"]
    assert await stack.store.accepted_outputs(stack.host.scope, stack.run_id) == ()

    def cited(member: MemberRef, actor: HostAccess) -> Any:
        return stack.outputs.record_assessment(
            actor,
            AssessmentInput(
                run_id=stack.run_id,
                subject_kind="member",
                subject_id=member.ref,
                subject_digest=member.digest,
                index_revision_id=manifest,
                requirement_results={"verified": "pass"},
                method_pin=TRUSTED_PIN,
                policy_pin="policy@1",
                evidence_refs=(decision_evidence(decision(member), member.digest),),
            ),
        )

    # B2': a host or assessor cannot forge KS decision evidence (refused at record time).
    forged = await cited(a, stack.assessor)
    assert forged.status == "refused" and forged.error.code == "ASSESSOR_UNAUTHORIZED"
    bridge = HostAccess(
        scope=stack.host.scope,
        actor_ref=TRUSTED_BRIDGE_ACTOR,
        origin_ref="ks:aiengineer-postgres/use_decision/d",
        role="assessor",
    )
    for member in (a, b):
        assert (await cited(member, bridge)).status == "recorded"
    # Bridge-cited but unverified (no verification port composed): still waits, never promoted.
    unverified = await _converge(stack, executor)
    assert codes(unverified, "draft.reports") == ["SUBMITTED_NOT_ACCEPTED"]
    # The host verifies each cited decision is standing for exactly that member: it counts.
    port = MemberDecisions({(m.ref, m.digest): frozenset({decision(m)}) for m in (a, b)})
    stack.outputs._member_decisions = port
    accepted = await _converge(stack, executor)
    assert fulfillment(accepted, "draft.reports").disposition == "fulfilled"
    assert port.asked and {item[2] for item in port.asked[-1]} == {decision(a), decision(b)}
    # Revoked: the decision is no longer standing for b, so b no longer counts.
    port.standing = {(a.ref, a.digest): frozenset({decision(a)})}
    revoked = await stack.evaluate()
    assert codes(revoked, "draft.reports") == ["MEMBER_UNASSESSED"]


def decision(member: MemberRef) -> str:
    return "d-" + member.ref.rsplit("/", 1)[-1].split("@", 1)[0]


class MemberDecisions:
    """The host's verification port: which cited KS decisions stand for exact members."""

    def __init__(self, standing: dict[tuple[str, str], frozenset[str]]) -> None:
        self.standing = standing
        self.asked: list[list[tuple[str, str, str]]] = []

    async def standing_member_decisions(self, scope: str, cited: Any) -> Any:
        self.asked.append(list(cited))
        return {
            (ref, digest): frozenset({d}) & self.standing.get((ref, digest), frozenset())
            for ref, digest, d in cited
        }


async def test_at_least_more_than_the_members_blocks_and_never_promotes() -> None:
    """S2: an `at_least k` rule over fewer than k members can never be met."""

    stack = await make_stack(collection_promise(aggregate={"aggregate": "at_least", "minimum": 3}))
    a, b = report("a"), report("b")
    executor, manifest = await _submitted_manifest(stack, a, b)
    for member in (a, b):
        await member_verdict(stack, manifest, member, "pass")
    result = await _converge(stack, executor)
    assert codes(result, "draft.reports") == ["SUBMITTED_NOT_ACCEPTED"]  # never promoted
    assert await stack.store.accepted_outputs(stack.host.scope, stack.run_id) == ()
    await stack.accept(  # even a host promotion cannot make it fulfilled
        dataclasses_ack(manifest), "draft.reports"
    )
    forced = await stack.evaluate()
    decided = fulfillment(forced, "draft.reports")
    assert decided.disposition == "blocked" and codes(forced, "draft.reports") == [
        "AGGREGATE_SHORT"
    ]


def dataclasses_ack(revision_id: str) -> Any:
    from mission_control.domain.outputs.contracts import SubmissionAck, SubmittedRevision

    return SubmissionAck(
        status="accepted",
        revisions=(
            SubmittedRevision(
                revision_id=revision_id,
                deliverable_id="reports",
                revision=1,
                content_digest=digest_of("unused"),
            ),
        ),
    )


async def test_only_the_trusted_bridge_records_ks_decision_evidence() -> None:
    """Review S3: a non-bridge actor citing `ks-use-decision:` is refused, on a first-time pass
    and on the supersession path alike."""

    from mission_control.application.outputs.fulfillment import AssessmentInput, HostAccess
    from mission_control.domain.knowledge.judgment import TRUSTED_BRIDGE_ACTOR, decision_evidence

    stack = await make_stack(collection_promise(validator=TRUSTED_PIN))
    a = report("a")
    _executor, manifest = await _submitted_manifest(stack, a)

    def judgment(result: str, *, supersedes: str | None = None, ref: str = "d-a") -> Any:
        return AssessmentInput(
            run_id=stack.run_id,
            subject_kind="member",
            subject_id=a.ref,
            subject_digest=a.digest,
            index_revision_id=manifest,
            requirement_results={"verified": result},  # type: ignore[dict-item]
            method_pin=TRUSTED_PIN,
            policy_pin="policy@1",
            evidence_refs=(decision_evidence(ref, a.digest),),
            supersedes=supersedes,
        )

    for actor in (stack.assessor, stack.host):
        refused = await stack.outputs.record_assessment(actor, judgment("pass"))
        assert refused.status == "refused" and refused.error.code == "ASSESSOR_UNAUTHORIZED"
    bridge = HostAccess(
        scope=stack.host.scope,
        actor_ref=TRUSTED_BRIDGE_ACTOR,
        origin_ref="ks:aiengineer-postgres/use_decision/d-a",
        role="assessor",
    )
    standing = await stack.outputs.record_assessment(bridge, judgment("pass"))
    assert standing.status == "recorded"
    assert standing.assessment is not None
    supersede = await stack.outputs.record_assessment(
        stack.assessor,
        judgment("fail", supersedes=standing.assessment.assessment_id, ref="d-a-2"),
    )
    assert supersede.status == "refused" and supersede.error.code == "ASSESSOR_UNAUTHORIZED"
