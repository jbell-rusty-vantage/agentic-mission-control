"""The one transfer materializer (OUTPUT-CONTRACTS §6; ADR-0061; WI-02 / OVE-164).

Real gateway over the verifying fake KS binding (Ed25519 credentials), the in-memory plan store
with the 0057 rules, a content-addressed custody and a fake receiving backend whose reads are
the backend's own. Proves: exact accepted report selection rendered identically to prompt,
index and files; evaluator isolation; redelivery appends a receipt and never resolves today's
revision; required actual-backend read and revoked access fail closed; aggregate overflow;
literal, artifact and application sources resolve exactly; consumption lineage on ready only.
"""

from __future__ import annotations

import pytest

from mission_control.application.context.materialization import (
    ContextDeliveryBlocked,
    ResolutionContext,
    ResolvedContent,
)
from mission_control.domain.context.transfer import (
    INDEX_PATH,
    Boundary,
    ExactMember,
    HostOverhead,
    InputSource,
    TransferInput,
)
from mission_control.domain.knowledge.lineage import ProvenanceRole
from mission_control.domain.outputs.contracts import (
    ExactOutput,
    OutputContract,
    OutputForm,
    OutputObligation,
)
from tests.fixtures.knowledge_binding import (
    report_package,
)
from tests.support.knowledge import TENANT
from tests.support.unit.context.transfer_materializer import (
    REPORT_INPUT,
    RUN,
    FakeBackend,
    _digest,
    _trusted,
    bounds,
    dependent,
    seam,
)

# ---------------------------------------------------------------- fakes


# ---------------------------------------------------------------- exact selection and rendering


async def test_prompt_files_and_index_come_from_one_exact_selection() -> None:
    s = seam()
    s.accept_report()
    backend = FakeBackend()
    result = await s.materializer.materialize(s.request(dependent(REPORT_INPUT)), backend)
    plan = result.plan
    files = dict(result.files)
    body = next(m for m in plan.exact_sources if m.part == "body")
    assert files[next(p.path for p in plan.placements if p.member_key == body.member_key)] == (
        s.package.body
    )
    # Every file the agent can read is a plan member read back from the backend by digest.
    for placed, member in plan.placed("file"):
        assert placed.path is not None and _digest(backend.files[placed.path]) == member.digest
    index = result.index
    assert {item["digest"] for item in index["inputs"]} == {m.digest for m in plan.exact_sources}
    assert backend.files[INDEX_PATH].startswith(b'{"inputs":')
    assert result.prompt_section is not None
    for member in plan.exact_sources:
        assert member.digest in result.prompt_section
    assert result.receipt.result == "ready" and result.receipt.sequence == 1
    assert {d.probe for d in result.receipt.delivered} == {"backend_read", "prompt"}
    assert result.receipt.realized_backend == "fake:sandbox"
    # The exact KS read named the receiver's purpose (readSelected).
    reads = [c for c in s.fake.calls_of("invoke") if c.envelope is not None]
    assert reads and all(c.envelope.operation == "knowledge.read" for c in reads)
    payload = reads[0].envelope.input.inlinePayload  # type: ignore[union-attr]
    assert payload["purpose"] == "dependent_input" and payload["exact"] is True
    # Ready: the receiving attempt consumed the exact revision (never production/adoption).
    facts = await s.lineage.facts(s.access().scope, s.handle())
    assert [fact.role for fact in facts] == [ProvenanceRole.CONSUMER]


async def test_no_run_wide_loading_unaccepted_or_undeclared_sources_refuse() -> None:
    s = seam()
    with pytest.raises(ContextDeliveryBlocked, match="SOURCE_UNRESOLVED:draft"):
        await s.materializer.materialize(s.request(dependent(REPORT_INPUT)), FakeBackend())
    s.outputs.obligations.append(
        OutputObligation(
            key="draft.report",
            owner_position="draft",
            contract=OutputContract(form=OutputForm.REFERENCE),
        )
    )
    with pytest.raises(ContextDeliveryBlocked) as waiting:
        await s.materializer.materialize(s.request(dependent(REPORT_INPUT)), FakeBackend())
    assert waiting.value.refusals[0].code == "SOURCE_NOT_ACCEPTED"
    assert waiting.value.refusals[0].waiting


async def test_a_head_demoted_after_promotion_is_rechecked_and_never_admitted() -> None:
    """OVE-169: the consumer re-check runs before use; a head whose standing trusted assessment
    was superseded by a non-pass (a post-promotion revocation) is not admitted (waiting)."""

    s = seam()
    s.accept_report()
    head = s.outputs.accepted[0]
    s.outputs.assessments.append(_trusted(head, "pass", 1, None))
    rechecked: list[str] = []

    async def recheck(access: object, revision: ExactOutput) -> None:
        rechecked.append(revision.revision_id)
        s.outputs.assessments.append(_trusted(revision, "review", 2, "assess-1"))

    resolver = s.materializer._resolvers["produced_output"]
    resolver._recheck = recheck
    with pytest.raises(ContextDeliveryBlocked) as waiting:
        await s.materializer.materialize(s.request(dependent(REPORT_INPUT)), FakeBackend())
    refusal = waiting.value.refusals[0]
    assert refusal.code == "SOURCE_NOT_ACCEPTED" and refusal.waiting
    assert "demoted after revocation: rev-report-1" in refusal.message
    assert rechecked == ["rev-report-1"]


async def test_an_independent_evaluator_receives_only_its_nominated_subject() -> None:
    s = seam()
    s.accept_report()
    other = s.fake.register_package(
        report_package("sibling-3", "1", tenant=TENANT, body=b"# Sibling findings\n")
    )
    s.accept(
        "sibling",
        "sibling.report",
        ExactOutput(
            revision_id="rev-sibling",
            run_id=RUN,
            obligation_key="sibling.report",
            obligation_revision=1,
            deliverable_id="report",
            revision=1,
            form=OutputForm.REFERENCE,
            content_digest=other.report.digest,
            candidate={"kind": "handle", "ref": s.handle(other)},
            producer_origin_ref="mc-inv:sibling",
        ),
    )
    subject = REPORT_INPUT.model_copy(update={"purpose": "evaluation_subject"})
    selection = dependent(subject, boundary=Boundary.EVALUATOR, isolation="independent_evaluator")
    result = await s.materializer.materialize(s.request(selection), FakeBackend())
    assert {m.binding for m in result.plan.exact_sources} == {"draft"}
    assert {m.source_ref for m in result.plan.exact_sources} == {"rev-report-1"}
    assert result.plan.isolation == "independent_evaluator"
    assert other.body not in dict(result.files).values()
    assert "sibling" not in (result.prompt_section or "")


# ---------------------------------------------------------------- redelivery and fail-closed


async def test_redelivery_appends_a_receipt_and_never_resolves_todays_revision() -> None:
    s = seam()
    s.accept_report()
    first = await s.materializer.materialize(s.request(dependent(REPORT_INPUT)), FakeBackend())
    # A newer accepted revision arrives after the plan was sealed.
    newer = s.fake.register_package(report_package("report-7", "2", tenant=TENANT, body=b"# R8\n"))
    s.accept_report(newer, number=2)
    reads_before = s.outputs.reads
    again = await s.materializer.materialize(
        s.request(dependent(REPORT_INPUT), attempt=2), FakeBackend("fake:sandbox-2")
    )
    assert again.plan.digest == first.plan.digest
    assert s.outputs.reads == reads_before  # the selection was not resolved again
    assert newer.body not in dict(again.files).values()
    assert dict(again.files) == dict(first.files)
    receipts = await s.store.receipts(s.access().scope, first.plan.plan_id)
    assert [
        (r.sequence, r.receiver_attempt.operation_attempt, r.realized_backend) for r in receipts
    ] == [
        (1, 1, "fake:sandbox"),
        (2, 2, "fake:sandbox-2"),
    ]


async def test_a_required_file_unreadable_through_the_actual_backend_fails_closed() -> None:
    s = seam()
    s.accept_report()
    with pytest.raises(ContextDeliveryBlocked) as blocked:
        await s.materializer.materialize(
            s.request(dependent(REPORT_INPUT)), FakeBackend(unreadable=("body.md",))
        )
    assert blocked.value.refusals[0].code == "BACKEND_UNREADABLE"
    # The refused attempt is receipted too; the plan stays sealed and unchanged.
    (plan,) = s.store.plans.values()
    (receipt,) = await s.store.receipts(s.access().scope, plan.plan_id)
    assert receipt.result == "refused" and receipt.findings[0].member_key.endswith("/body")
    assert not await s.lineage.facts(s.access().scope, s.handle())


async def test_corrupt_custody_and_revoked_access_stop_readiness() -> None:
    s = seam()
    s.accept_report()
    await s.materializer.materialize(s.request(dependent(REPORT_INPUT)), FakeBackend())
    (plan,) = s.store.plans.values()
    body = next(m for m in plan.exact_sources if m.part == "body")
    assert body.custody_ref is not None
    s.staging.objects[body.custody_ref] = b"tampered"
    with pytest.raises(ContextDeliveryBlocked, match="DIGEST_MISMATCH"):
        await s.materializer.materialize(
            s.request(dependent(REPORT_INPUT), attempt=2), FakeBackend()
        )
    s.staging.objects[body.custody_ref] = s.package.body
    # The plan does not freeze permission: the exact revision is gone at the next attempt.
    s.fake.packages.clear()
    with pytest.raises(ContextDeliveryBlocked) as revoked:
        await s.materializer.materialize(
            s.request(dependent(REPORT_INPUT), attempt=3), FakeBackend()
        )
    # Every KS member re-reads its exact revision: each refuses on its own.
    assert {r.member_key for r in revoked.value.refusals} >= {"draft/manifest", "draft/body"}


async def test_aggregate_prompt_tool_skill_file_and_reserve_overflow_refuses() -> None:
    s = seam()
    s.accept_report()
    heavy = HostOverhead(host_state_tokens=55_000, tool_schema_tokens=2_000, skill_tokens=1_000)
    with pytest.raises(ContextDeliveryBlocked, match="RESOURCE_EXCEEDED"):
        await s.materializer.materialize(
            s.request(dependent(REPORT_INPUT), overhead=heavy), FakeBackend()
        )
    tight = dependent(REPORT_INPUT, bounds=bounds(file_bytes_ceiling=8))
    with pytest.raises(ContextDeliveryBlocked, match="RESOURCE_EXCEEDED"):
        await s.materializer.materialize(s.request(tight), FakeBackend())


# ---------------------------------------------------------------- literal, artifact, application


async def test_literal_artifact_and_application_sources_resolve_exactly() -> None:
    def resolver_returning(member: ExactMember, content: bytes | None) -> object:
        class _Selector:
            async def resolve(self, binding: TransferInput, context: ResolutionContext):
                return (ResolvedContent(member, content),)

        return _Selector()

    observation = b'{"observation":"obs-4","value":42}'
    exact = ExactMember(
        member_key="cohort/value",
        binding="cohort",
        part="value",
        source_kind="application_selector",
        source_ref="retained-observation:obs-4",
        revision="obs-4",
        issuer="biotech-graph",
        digest=_digest(observation),
        size_bytes=len(observation),
        media_type="application/json",
        file_name="cohort.json",
        purpose="dependent_input",
        required=True,
        access_ref="retained-observation:obs-4",
    )
    s = seam(selectors={"biotech.cohort@1": resolver_returning(exact, observation)})
    digest = await s.artifacts.add(
        "artifact://run/notes.md", b"# notes\n", "text/markdown", "notes.md"
    )
    selection = dependent(
        TransferInput(
            name="brief",
            source=InputSource.literal("mc.brief@1", {"topic": "aging"}),
            purpose="dependent_input",
        ),
        TransferInput(
            name="notes",
            source=InputSource.artifact("artifact://run/notes.md", digest),
            purpose="dependent_input",
        ),
        TransferInput(
            name="cohort",
            source=InputSource.application("biotech.cohort@1", {"study": "s1"}),
            purpose="dependent_input",
        ),
        boundary=Boundary.FIRST_INVOCATION,
    )
    result = await s.materializer.materialize(s.request(selection), FakeBackend())
    by_binding = {m.binding: m for m in result.plan.exact_sources}
    assert by_binding["brief"].digest == _digest(b'{"topic":"aging"}')
    assert by_binding["notes"].digest == digest
    assert by_binding["cohort"].revision == "obs-4"
    assert dict(result.files)["/inputs/notes/" + digest[7:23] + "/notes.md"] == b"# notes\n"

    # A wrong pinned artifact digest, an unregistered application binding and a live query
    # without an exact revision all refuse.
    wrong = seam()
    await wrong.artifacts.add("artifact://run/notes.md", b"# edited\n", "text/markdown", "notes.md")
    with pytest.raises(ContextDeliveryBlocked, match="DIGEST_MISMATCH:notes"):
        await wrong.materializer.materialize(
            wrong.request(dependent(selection.inputs[1], boundary=Boundary.FIRST_INVOCATION)),
            FakeBackend(),
        )
    with pytest.raises(ContextDeliveryBlocked, match="APPLICATION_SELECTOR_UNRESOLVED"):
        await wrong.materializer.materialize(
            wrong.request(dependent(selection.inputs[2], boundary=Boundary.FIRST_INVOCATION)),
            FakeBackend(),
        )
    live = exact.model_copy(update={"source_kind": "produced_output"})
    query = seam(selectors={"biotech.cohort@1": resolver_returning(live, observation)})
    with pytest.raises(ContextDeliveryBlocked, match="APPLICATION_SELECTOR_NOT_EXACT"):
        await query.materializer.materialize(
            query.request(dependent(selection.inputs[2], boundary=Boundary.FIRST_INVOCATION)),
            FakeBackend(),
        )


async def test_file_realizations_name_only_backend_read_exact_members() -> None:
    s = seam()
    digest = await s.artifacts.add("artifact://run/fig.txt", b"figure", "text/plain", "fig.txt")
    s.accept(
        "draft",
        "draft.figure",
        ExactOutput(
            revision_id="rev-figure-1",
            run_id=RUN,
            obligation_key="draft.figure",
            obligation_revision=1,
            deliverable_id="figure",
            revision=1,
            form=OutputForm.FILE,
            content_digest=digest,
            candidate={"kind": "path", "ref": "artifact://run/fig.txt"},
            producer_origin_ref="mc-inv:draft",
        ),
    )
    figure = TransferInput(
        name="figure",
        source=InputSource.produced("draft", "draft.figure"),
        purpose="dependent_input",
    )
    assert await s.store.file_realizations(s.access().scope, ["rev-figure-1"]) == {}
    await s.materializer.materialize(s.request(dependent(figure)), FakeBackend())
    realized = await s.store.file_realizations(s.access().scope, ["rev-figure-1"])
    assert set(realized) == {"rev-figure-1"}


async def test_an_optional_unsubmitted_producer_is_a_visible_omission_not_a_block() -> None:
    s = seam()
    s.outputs.obligations.append(
        OutputObligation(
            key="draft.report",
            owner_position="draft",
            contract=OutputContract(form=OutputForm.REFERENCE),
        )
    )
    optional = REPORT_INPUT.model_copy(update={"required": False})
    result = await s.materializer.materialize(s.request(dependent(optional)), FakeBackend())
    assert result.plan.exact_sources == ()
    assert [(o.binding, o.code) for o in result.plan.omissions] == [
        ("draft", "SOURCE_NOT_ACCEPTED")
    ]
    assert result.receipt.result == "ready"
    assert result.index["omissions"][0]["code"] == "SOURCE_NOT_ACCEPTED"
