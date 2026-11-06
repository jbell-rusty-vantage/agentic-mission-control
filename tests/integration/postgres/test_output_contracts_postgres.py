"""WI-01 / OVE-163 on a disposable PostgreSQL 17 with release 1.7.0 (restricted runtime role).

The ordinary handlers run against the real output-contract tables under forced row security:
eight forms are submitted and decided under the admitted completion (text, structured,
code_change and control_record reach fulfillment; file, reference and effect_receipt wait on
their evidence and collection is truthfully not yet fulfillable), a changed key refuses and an
identical retry is the same receipt, concurrent promotions let exactly one win, drafts never
move an accepted head, a successor stays pending until its boundary while an in-flight invocation
keeps its pin,
association steps happen once, a compiled configuration registers through the real service, the
SQL guards refuse mutation, foreign members, cross-run assessments, self-assessment and
unpinned fulfillment, and another tenant sees nothing.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import asyncpg
import pytest
import pytest_asyncio

from mission_control.adapters.postgres.knowledge.output_contracts import (
    PostgresOutputContractStore,
)
from mission_control.adapters.postgres.scope import apply_scope
from mission_control.application.knowledge.access import InvocationAccess
from mission_control.application.outputs.fulfillment import (
    AuthorAccess,
    OutputSetRef,
    PromoteOutput,
)
from mission_control.domain.outputs.contracts import (
    CandidateRef,
    Cardinality,
    MemberRef,
    OutputForm,
)
from mission_control.domain.outputs.successors import (
    ContractRevisionProposal,
    RegisteredCandidate,
)
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.integration.postgres.runtime_common import common_db, owner_rows  # noqa: F401
from tests.unit.knowledge.test_gateway import origin
from tests.unit.outputs.scenario import (
    Stack,
    build_stack,
    code_change,
    codes,
    digest_of,
    eight_forms,
    fulfillment,
    obligation,
    structured,
    text,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.common_db]
AT = datetime(2026, 10, 27, 12, tzinfo=UTC)


@pytest_asyncio.fixture
async def pool(common_db: CommonDatabase) -> AsyncIterator[asyncpg.Pool]:  # noqa: F811
    created = await common_db.pool()
    try:
        yield created
    finally:
        await created.close()


def access_for(db: CommonDatabase, tenant: str = "tenant-1", attempt: int = 1) -> InvocationAccess:
    _mc, installation, application, tenant_id = db.scope(tenant).split("/")
    return InvocationAccess(
        origin=origin(
            attempt,
            installation_id=installation,
            application_id=application,
            tenant_id=tenant_id,
        ),
        subject="mission-control-runtime",
        invocation_id=f"inv-{attempt:04d}",
        authenticated_at=AT,
    )


async def make_stack(db, pool, *items, completion=None):  # type: ignore[no-untyped-def]
    store = PostgresOutputContractStore(pool)
    return await build_stack(store, store, access_for(db), *items, completion=completion)


async def judge(stack: Stack, subject: str, digest: str, **results: str) -> None:
    receipt = await stack.judge(subject, digest, **results)
    assert receipt.status == "recorded", receipt.error


DEFERRED = {
    "draft.figure": CandidateRef(
        deliverable_id="figure",
        form=OutputForm.FILE,
        kind="path",
        ref="outputs/f.png",
        digest=digest_of("png"),
        size_bytes=4,
        media_type="image/png",
    ),
    "draft.dataset": CandidateRef(
        deliverable_id="dataset",
        form=OutputForm.COLLECTION,
        kind="handle",
        ref="kh:aiengineer-postgres/collection/c1@collection.v1",
        digest=digest_of("c1"),
        members=(MemberRef(ref="m1", digest=digest_of("m1")),),
    ),
    "draft.source": CandidateRef(
        deliverable_id="source",
        form=OutputForm.REFERENCE,
        kind="handle",
        ref="kh:aiengineer-postgres/report/r9@research_report.v1",
        digest=digest_of("r9"),
    ),
    "draft.ingest": CandidateRef(
        deliverable_id="ingest",
        form=OutputForm.EFFECT_RECEIPT,
        kind="handle",
        ref="kh:aiengineer-postgres/effect/e1@effect.v1",
        digest=digest_of("e1"),
        effect_key="effect:1",
    ),
}


async def test_eight_forms_are_decided_through_the_ordinary_handlers(common_db, pool):  # noqa: F811
    stack = await make_stack(common_db, pool, *eight_forms())
    omitted = await stack.evaluate()
    assert all(codes(omitted, item.key) == ["MISSING"] for item in eight_forms())
    summary = await stack.submit("t1", "draft.summary", text("summary", "# Summary\n"))
    claims = await stack.submit(
        "s1",
        "draft.claims",
        structured(
            "claims",
            {"claims": [{"study": "s1", "claim": "a"}, {"study": "s2", "claim": "b"}]},
        ),
    )
    patch = await stack.submit("p1", "draft.patch", code_change())
    note = await stack.submit(
        "n1",
        "draft.note",
        structured(
            "note", {"finding": "gap"}, schema_ref="finding_note@1", form=OutputForm.CONTROL_RECORD
        ),
    )
    for key, ack in (
        ("draft.summary", summary),
        ("draft.claims", claims),
        ("draft.patch", patch),
        ("draft.note", note),
    ):
        await stack.accept(ack, key)
    for key, candidate in DEFERRED.items():
        await stack.accept(await stack.submit(f"d:{key}", key, candidate), key)
    waiting = await stack.evaluate()
    assert codes(waiting, "draft.patch") == ["REQUIREMENT_UNASSESSED"] * 2
    await judge(
        stack,
        patch.revisions[0].revision_id,
        patch.revisions[0].content_digest,
        tests="pass",
        lint="pass",
    )
    again = await stack.judge(
        patch.revisions[0].revision_id, patch.revisions[0].content_digest, tests="pass", lint="pass"
    )
    assert again.status == "recorded"  # a retried judgment is the same stored row
    result = await stack.evaluate()
    for key in ("draft.summary", "draft.claims", "draft.patch", "draft.note"):
        assert fulfillment(result, key).disposition == "fulfilled", (key, codes(result, key))
    for key in DEFERRED:
        # WI-02: a file is fulfillable once a receiving backend read its custody bytes back;
        # without that transfer evidence it is unrealized, never a success. WI-03: a reference
        # needs current official use of its exact revision.
        expected = {
            "draft.figure": "FILE_NOT_REALIZED",
            "draft.source": "REFERENCE_USE_UNPROVEN",
            # WI-05: this stack composes no effect-receipt port: a host fault, never a wait.
            "draft.ingest": "EFFECT_EVIDENCE_UNWIRED",
        }.get(key)
        # WI-07: a collection with no member requirement is fulfilled by its exact manifest.
        assert codes(result, key) == ([] if expected is None else [expected])
    assert result.completion == "blocked"
    assert waiting.set_id == result.set_id  # assessments never change the pinned set
    decided = await owner_rows(
        common_db,
        "SELECT obligation_key, disposition FROM mission_control.obligation_fulfillment "
        "WHERE output_set_id = $1::uuid",
        result.set_id,
    )
    patch_decisions = sorted(
        row["disposition"] for row in decided if row["obligation_key"] == "draft.patch"
    )
    assert len(decided) == 9 and patch_decisions == ["fulfilled", "unfulfilled"]
    stored = await owner_rows(
        common_db,
        "SELECT count(*) AS n FROM mission_control.output_assessment WHERE run_id = $1::uuid",
        stack.run_id,
    )
    assert stored[0]["n"] == 1


async def test_keys_heads_and_concurrent_promotion(common_db, pool):  # noqa: F811
    stack = await make_stack(common_db, pool, obligation("draft.report", OutputForm.TEXT))
    first = await stack.submit("call-1", "draft.report", text("report", "v1"))
    replay = await stack.submit("call-1", "draft.report", text("report", "v1"))
    assert replay.submission_id == first.submission_id and replay.revisions == first.revisions
    changed = await stack.submit("call-1", "draft.report", text("report", "v2"))
    assert changed.error is not None and changed.error.code == "SUBMISSION_CONFLICT"
    second = await stack.submit("call-2", "draft.report", text("report", "v2"))
    assert second.revisions[0].revision == 2
    results = await asyncio.gather(
        *(
            stack.outputs.promote_output(
                stack.host,
                PromoteOutput(
                    run_id=stack.run_id, revision_id=ack.revisions[0].revision_id, generation=1
                ),
            )
            for ack in (first, second)
        )
    )
    assert sorted(item.status for item in results) == ["promoted", "refused"]
    winner = next(item for item in results if item.status == "promoted").head
    assert winner is not None
    third = await stack.submit("call-3", "draft.report", text("report", "v3"))
    head = await stack.store.accepted_head(stack.host.scope, stack.run_id, "draft.report", "report")
    assert head is not None and head.revision_id == winner.revision_id  # draft did not move it
    if winner.revision_id == second.revisions[0].revision_id:
        older = await stack.outputs.promote_output(
            stack.host,
            PromoteOutput(
                run_id=stack.run_id,
                revision_id=first.revisions[0].revision_id,
                expected_head=winner.revision_id,
                generation=1,
            ),
        )
        assert older.error is not None and older.error.code == "OLDER_REVISION"
    await stack.submissions.finalize(stack.access.identity(("draft.report",)))
    retry = await stack.submit("call-3", "draft.report", text("report", "v3"))
    assert retry.submission_id == third.submission_id  # replay before SubmissionClosed


async def test_pending_successor_waits_for_its_boundary_and_pins_hold(common_db, pool):  # noqa: F811
    prior = obligation("draft.report", OutputForm.TEXT, cardinality=Cardinality(min=1, max=2))
    stack = await make_stack(common_db, pool, prior)
    in_flight = await stack.submit("call-1", "draft.report", text("report", "v1"))
    await stack.accept(in_flight, "draft.report")
    pinned = await stack.outputs.pin_frontier(stack.host, stack.run_id)
    author = AuthorAccess(
        scope=stack.host.scope,
        actor_id="owner",
        role="author",
        delegation_refs=frozenset({"delegation:owner"}),
    )
    tighter = prior.model_copy(update={"revision": 2, "cardinality": Cardinality(min=2, max=2)})
    proposal = ContractRevisionProposal(
        run_id=stack.run_id,
        obligation_key="draft.report",
        expected_prior_revision=1,
        successor=tighter,
        actor_id="owner",
        actor_role="author",
        reason="two reports",
        delegation_ref="delegation:owner",
        boundary="between_iterations",
        boundary_ref="iteration:2",
    )
    racing = await asyncio.gather(
        stack.outputs.activate_contract_successor(author, proposal),
        stack.outputs.activate_contract_successor(author, proposal),
    )
    assert sorted(item.status for item in racing) == ["pending", "refused"]
    assert [
        item.revision
        for item in await stack.store.active_obligations(stack.host.scope, stack.run_id)
    ] == [1]  # pending, not active
    activated = await stack.outputs.activate_at_boundary(
        stack.host, stack.run_id, boundary="between_iterations", boundary_ref="iteration:2"
    )
    assert [item.revision for item in activated] == [2]
    late = await stack.submit("call-2", "draft.report", text("report", "v2"))
    stored = await stack.store.output_revision(stack.host.scope, late.revisions[0].revision_id)
    assert stored is not None and stored.obligation_revision == 1  # the in-flight pin holds
    after = await stack.start(access_for(common_db, attempt=2))
    fresh = await after.submit("call-1", "draft.report", text("report2", "x"))
    fresh_stored = await stack.store.output_revision(
        stack.host.scope, fresh.revisions[0].revision_id
    )
    assert fresh_stored is not None and fresh_stored.obligation_revision == 2
    kept = await stack.outputs.evaluate_frontier(
        stack.host, OutputSetRef(run_id=stack.run_id, set_id=pinned.set_id)
    )
    assert fulfillment(kept, "draft.report").obligation_revision == 1
    current = await stack.evaluate()
    assert "HEAD_UNDER_SUPERSEDED_REVISION" in codes(current, "draft.report")
    history = await owner_rows(
        common_db,
        "SELECT revision.revision, revision.activation_boundary, head.activated_boundary_ref "
        "FROM mission_control.output_obligation_revision revision JOIN "
        "mission_control.output_obligation_head head USING (installation_id, application_id, "
        "tenant_id, run_id, obligation_key) WHERE revision.run_id = $1::uuid "
        "ORDER BY revision.revision",
        stack.run_id,
    )
    assert [tuple(row) for row in history] == [
        (1, None, "between_iterations:iteration:2"),
        (2, "between_iterations", "between_iterations:iteration:2"),
    ]


async def test_association_steps_are_taken_once_each(common_db, pool):  # noqa: F811
    stack = await make_stack(common_db, pool, obligation("draft.report", OutputForm.TEXT))
    one = (RegisteredCandidate(candidate=text("report", "registered"), source="registered_output"),)
    actions = [
        (
            await stack.outputs.resolve_missing_submission(
                stack.host, stack.access, "draft.report", one, position="draft"
            )
        ).action
        for _ in range(3)
    ]
    assert actions == ["remind", "associate", "not_missing"]
    steps = await owner_rows(
        common_db,
        "SELECT step FROM mission_control.obligation_association_step WHERE run_id = $1::uuid",
        stack.run_id,
    )
    assert sorted(row["step"] for row in steps) == ["auto_associated", "reminder"]


async def test_a_compiled_configuration_registers_through_the_real_service(common_db, pool):  # noqa: F811
    from tests.unit.authoring.test_output_promises_compile import compiled_configuration

    configuration = await compiled_configuration()
    promises = configuration.output_promises
    assert promises is not None
    store = PostgresOutputContractStore(pool)
    stack = await build_stack(
        store,
        store,
        access_for(common_db),
        *promises.obligations,
        completion=promises.completion,
        criteria=promises.criteria,
        human_tasks=promises.human_tasks,
    )
    assert await store.promise_set(stack.host.scope, stack.run_id) == promises
    ack = await stack.submit(
        "c-1", "synthesize.summary", text("summary", "# Summary"), position="synthesize"
    )
    await stack.accept(ack, "synthesize.summary")
    result = await stack.evaluate()
    assert fulfillment(result, "synthesize.summary").disposition == "fulfilled"
    assert result.completion == "waiting"


async def test_sql_guards_and_tenant_isolation(common_db, pool):  # noqa: F811
    await common_db.add_tenants(["tenant-2"])
    stack = await make_stack(common_db, pool, obligation("draft.report", OutputForm.TEXT))
    ack = await stack.submit("call-1", "draft.report", text("report", "v1"))
    await stack.accept(ack, "draft.report")
    revision = ack.revisions[0]
    pinned = await stack.outputs.pin_frontier(stack.host, stack.run_id)
    _mc, installation, application, tenant = stack.host.scope.split("/")
    scope = (installation, application, tenant)
    other_run = "33333333-3333-4333-8333-333333333399"
    assessment = (
        "INSERT INTO mission_control.output_assessment (installation_id, application_id, "
        "tenant_id, assessment_id, run_id, subject_kind, subject_ref, output_revision_id, "
        "subject_digest, requirement_results, result, assessor_origin_ref, method_pin, "
        "policy_pin, evidence_refs, findings, created_at, created_by_actor_ref) VALUES "
        "($1::uuid, $2, $3::uuid, gen_random_uuid(), $4::uuid, 'output_revision', $5, $5::uuid, "
        "$6, '{\"ok\": \"pass\"}', 'pass', $7, 'm@1', 'p@1', '[]', '[]', now(), 'x')"
    )
    refused = [
        ("UPDATE mission_control.output_revision SET content_digest = content_digest", ()),
        ("DELETE FROM mission_control.output_obligation_revision", ()),
        (
            "UPDATE mission_control.output_obligation_head SET active_revision = 1, "
            "version = version + 1",
            (),
        ),
        # A producer never assesses its own output.
        (
            assessment,
            (
                *scope,
                stack.run_id,
                revision.revision_id,
                revision.content_digest,
                stack.access.invocation_ref,
            ),
        ),
        # An assessment is bound to its subject's run.
        (
            assessment,
            (*scope, other_run, revision.revision_id, revision.content_digest, "mc-assessor:x"),
        ),
        # A set member is the exact revision it names.
        (
            "INSERT INTO mission_control.output_set_member (installation_id, application_id, "
            "tenant_id, output_set_id, output_revision_id, obligation_key, deliverable_id, "
            "content_digest) VALUES ($1::uuid, $2, $3::uuid, $4::uuid, $5::uuid, "
            "'draft.report', 'other', $6)",
            (*scope, pinned.set_id, revision.revision_id, revision.content_digest),
        ),
        # A fulfillment decides only a promise revision the set pinned.
        (
            "INSERT INTO mission_control.obligation_fulfillment (installation_id, "
            "application_id, tenant_id, fulfillment_id, run_id, output_set_id, obligation_key, "
            "obligation_revision, enforcement, disposition, distinct_count, decision, "
            "decision_digest, created_at, created_by_actor_ref) VALUES ($1::uuid, $2, $3::uuid, "
            "gen_random_uuid(), $4::uuid, $5::uuid, 'draft.report', 1, 'required', 'fulfilled', "
            "1, '{}', $6, now(), 'x')",
            (*scope, other_run, pinned.set_id, digest_of("decision")),
        ),
    ]
    async with pool.acquire() as connection:
        for statement, args in refused:
            with pytest.raises(asyncpg.PostgresError):
                async with connection.transaction():
                    await apply_scope(connection, stack.host.scope)
                    await connection.execute(statement, *args)
    elsewhere = access_for(common_db, "tenant-2")
    other = PostgresOutputContractStore(pool)
    assert await other.active_obligations(elsewhere.scope, stack.run_id) == ()
    assert await other.output_revision(elsewhere.scope, revision.revision_id) is None
    assert await other.accepted_outputs(elsewhere.scope, stack.run_id) == ()
    assert await other.promise_set(elsewhere.scope, stack.run_id) is None


async def test_submitted_outputs_are_finalized_unrejected_and_newest(common_db, pool):  # noqa: F811
    """WI-02 B2: the submitted fallback reads only a finalized producer's newest revision per
    deliverable and never one an assessment rejected (fail) or held (review)."""

    stack = await make_stack(common_db, pool, *eight_forms())
    ack = await stack.submit("p1", "draft.patch", code_change())
    assert ack.status == "accepted", ack.error
    scope, run_id = stack.access.scope, stack.access.origin.run_id
    producer = stack.access.origin.operation_id

    async def submitted(key: str, operation: str = producer) -> tuple:
        return await stack.store.submitted_outputs(scope, run_id, key, operation_ref=operation)

    assert await submitted("draft.patch") == ()
    await stack.submissions.finalize(stack.access.identity(("draft.patch",)), stack.access)
    (newest,) = await submitted("draft.patch")
    assert newest.revision_id == ack.revisions[0].revision_id
    assert await submitted("draft.summary") == ()
    # R3: bound to the exact producing operation, never another iteration's submission.
    assert await submitted("draft.patch", "goal-iteration/9/executor") == ()
    await judge(stack, newest.revision_id, newest.content_digest, tests="fail", lint="pass")
    assert await submitted("draft.patch") == ()


async def test_submission_expected_head_is_atomic_and_replay_precedes_moved_head(common_db, pool):  # noqa: F811
    """A promotion between service entry and store entry must invalidate a new submission."""
    entered = asyncio.Event()
    resume = asyncio.Event()

    class PausedStore(PostgresOutputContractStore):
        async def record_submission(self, act):
            if act.submission_key == "racing":
                entered.set()
                await resume.wait()
            return await super().record_submission(act)

    store = PausedStore(pool)
    stack = await build_stack(
        store, store, access_for(common_db), obligation("draft.report", OutputForm.TEXT)
    )
    first = await stack.submit("first", "draft.report", text("report", "one"))
    first_id = await stack.accept(first, "draft.report")
    second = await stack.submit(
        "second", "draft.report", text("report", "two"), expected_head=first_id
    )
    racing = asyncio.create_task(
        stack.submit(
            "racing",
            "draft.report",
            text("report", "stale"),
            expected_head=first_id,
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), 5)
        second_id = await stack.accept(second, "draft.report")
    finally:
        resume.set()
    refused = await asyncio.wait_for(racing, 5)
    assert refused.error.code == "STALE_HEAD"
    retry = await stack.submit(
        "second", "draft.report", text("report", "two"), expected_head=first_id
    )
    assert retry.submission_id == second.submission_id and retry.revisions == second.revisions
    changed = await stack.submit(
        "second", "draft.report", text("report", "changed"), expected_head=first_id
    )
    assert changed.error.code == "SUBMISSION_CONFLICT"
    head = await store.accepted_head(stack.host.scope, stack.run_id, "draft.report", "report")
    assert head.revision_id == second_id
    await stack.evaluate()
    view = await stack.submissions.inspect_invocation(stack.access, position="draft")
    recorded = view["result"]["obligations"][0]["recorded_fulfillment"]
    assert recorded["disposition"] == "fulfilled"
    assert "assessment_refs" not in recorded
    foreign = await stack.submissions.inspect_invocation(
        access_for(common_db, tenant="tenant-2"), position="draft"
    )
    assert foreign["result"]["obligations"] == []
    await stack.submissions.finalize(stack.access.identity(("draft.report",)))
    retry = await stack.submit(
        "second", "draft.report", text("report", "two"), expected_head=first_id
    )
    assert retry.revisions == second.revisions
    late = await stack.submit(
        "late", "draft.report", text("report", "late"), expected_head=second_id
    )
    assert late.error.code == "INVOCATION_FINALIZED"
