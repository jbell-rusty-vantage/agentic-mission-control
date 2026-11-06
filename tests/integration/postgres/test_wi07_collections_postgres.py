"""WI-07 / OVE-170 on a disposable PostgreSQL 17: release 1.8.0 plus 0066 (released in 1.9.0).

The ordinary handlers on the real output-contract tables (restricted runtime role, forced row
security): a collection's members are judged one by one (the 1.8.0 guard refuses a collection
member assessment; ``scripts/release_190/0066_collection_member_assessments.sql`` admits exactly
the listed members), mixed verdicts, concurrent head promotion (exactly once per deliverable,
every distinct deliverable lands, every pinned set is a consistent snapshot), revisions that
never raise the distinct count, a restart with fresh services over the same rows, the current-set
index read from SQL, and goal-scoped review waits that do not hold independent work.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio

from mission_control.adapters.postgres.knowledge.output_contracts import (
    PostgresOutputContractStore,
)
from mission_control.application.knowledge.access import InvocationAccess
from mission_control.application.knowledge.trusted_settlement import pending_or_raise
from mission_control.application.outputs.current_set import CurrentSetIndexResolver
from mission_control.application.outputs.fulfillment import PromoteOutput
from mission_control.domain.outputs.contracts import (
    Cardinality,
    EvaluationScope,
    OutputForm,
    Requirement,
    membership_digest,
)
from tests.fixtures.mission_control_common_db import (
    CommonDatabase,
    common_database,
    migration_paths_with,
)
from tests.integration.postgres.runtime_common import owner_rows
from tests.unit.knowledge.test_gateway import origin
from tests.unit.knowledge.test_wi07_report_collections import (
    PIN,
    CurrentUse,
    ScriptedBridge,
    handle,
    settlement,
)
from tests.unit.outputs.scenario import (
    TRUSTED_VALIDATORS,
    Stack,
    build_stack,
    codes,
    fulfillment,
    obligation,
    text,
)
from tests.unit.outputs.test_collections import collection, collection_promise, report

pytestmark = [pytest.mark.asyncio, pytest.mark.common_db]
AT = datetime(2026, 10, 28, 12, tzinfo=UTC)
MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "scripts/release_190/0066_collection_member_assessments.sql"
)


RELEASE_180 = (
    Path(__file__).resolve().parents[3]
    / "packages/mission-control-db-contract/releases/1.8.0/component/migrations"
)


@pytest_asyncio.fixture
async def wi07_db() -> AsyncIterator[CommonDatabase]:
    async with common_database(paths=migration_paths_with(MIGRATION)) as database:
        yield database


@pytest_asyncio.fixture
async def released_180_db() -> AsyncIterator[CommonDatabase]:
    """The 1.8.0 guard, before 0066 (the newest built release carries 0066 from 1.9.0 on)."""

    paths = sorted(RELEASE_180.glob("[0-9][0-9][0-9][0-9]_*.sql"))
    async with common_database(paths=paths) as database:
        yield database


def access_for(db: CommonDatabase, operation: str = "op-research-1") -> InvocationAccess:
    _mc, installation, application, tenant_id = db.scope("tenant-1").split("/")
    return InvocationAccess(
        origin=origin(
            1,
            installation_id=installation,
            application_id=application,
            tenant_id=tenant_id,
            operation_id=operation,
        ),
        subject="mission-control-runtime",
        invocation_id="inv-" + operation.replace("/", "-"),
        authenticated_at=AT,
    )


async def make_stack(db: CommonDatabase, pool: asyncpg.Pool, *items) -> Stack:  # type: ignore[no-untyped-def]
    store = PostgresOutputContractStore(pool)
    return await build_stack(store, store, access_for(db), *items)


async def member_verdict(stack: Stack, manifest: str, member, result: str):  # type: ignore[no-untyped-def]
    return await stack.judge(
        member.ref, member.digest, kind="member", index_revision_id=manifest, verified=result
    )


async def test_the_released_guard_refuses_collection_members_that_0066_admits(
    released_180_db: CommonDatabase,
    wi07_db: CommonDatabase,
) -> None:
    a = report("a")
    released = await released_180_db.pool()
    try:
        stack = await make_stack(released_180_db, released, collection_promise())
        ack = await stack.submit("k1", "draft.reports", collection(members=(a,)))
        manifest = await stack.accept(ack, "draft.reports")
        with pytest.raises(asyncpg.IntegrityConstraintViolationError, match="member its index"):
            await member_verdict(stack, manifest, a, "pass")
    finally:
        await released.close()
    pool = await wi07_db.pool()
    try:
        stack = await make_stack(wi07_db, pool, collection_promise())
        ack = await stack.submit("k1", "draft.reports", collection(members=(a,)))
        manifest = await stack.accept(ack, "draft.reports")
        assert (await member_verdict(stack, manifest, a, "pass")).status == "recorded"
        # The guard binds the exact listed digest; another digest for the ref still refuses.
        forged = report("forged").model_copy(update={"ref": a.ref})
        refused = await member_verdict(stack, manifest, forged, "pass")
        assert refused.status == "refused" and refused.error.code == "MEMBER_NOT_LISTED"
    finally:
        await pool.close()


async def test_mixed_members_coverage_restart_and_index_on_postgres(wi07_db: CommonDatabase):
    pool = await wi07_db.pool()
    try:
        stack = await make_stack(wi07_db, pool, collection_promise())
        a, b, c = report("a"), report("b"), report("c")
        ack = await stack.submit("k1", "draft.reports", collection(members=(a, b, c)))
        manifest = await stack.accept(ack, "draft.reports")
        await member_verdict(stack, manifest, a, "pass")
        await member_verdict(stack, manifest, b, "review")
        await member_verdict(stack, manifest, c, "fail")
        result = await stack.evaluate()
        assert sorted(codes(result, "draft.reports")) == ["MEMBER_HELD", "MEMBER_REJECTED"]
        first_set = result.set_id
    finally:
        await pool.close()
    # Restart: new pool, new store and services over the same rows.
    pool = await wi07_db.pool()
    try:
        store = PostgresOutputContractStore(pool)
        from mission_control.application.outputs.fulfillment import OutputFulfillmentService
        from mission_control.application.outputs.submission_service import SubmissionService

        outputs = OutputFulfillmentService(
            store,
            SubmissionService(store, contracts=store),
            trusted_validators=TRUSTED_VALIDATORS,
        )
        restarted = Stack(
            store, stack.submissions, outputs, stack.access, stack.host, stack.assessor
        )
        again = await restarted.evaluate()
        assert again.set_id == first_set  # the same exact set: nothing moved
        assert sorted(codes(again, "draft.reports")) == ["MEMBER_HELD", "MEMBER_REJECTED"]
        index = await CurrentSetIndexResolver(
            store, clock=lambda: AT, trusted_validators=TRUSTED_VALIDATORS
        ).index(stack.host.scope, stack.run_id)
        assert index is not None and index.set_id == first_set
        labels = {m.ref: m.label for m in index.promises[0].heads[0].members}
        assert labels == {a.ref: "accepted", b.ref: "held", c.ref: "rejected"}
    finally:
        await pool.close()


async def test_concurrent_head_promotion_is_exactly_once_and_sets_are_snapshots(
    wi07_db: CommonDatabase,
) -> None:
    pool = await wi07_db.pool()
    try:
        reports = obligation(
            "draft.reports", OutputForm.TEXT, cardinality=Cardinality(min=3, max=8)
        )
        stack = await make_stack(wi07_db, pool, reports)
        same = [
            await stack.submit(f"s{n}", "draft.reports", text("report-a", f"A{n}"))
            for n in range(3)
        ]
        distinct = [
            await stack.submit(f"d{name}", "draft.reports", text(f"report-{name}", name))
            for name in ("b", "c", "d", "e")
        ]

        def promote(ack):  # type: ignore[no-untyped-def]
            return stack.outputs.promote_output(
                stack.host,
                PromoteOutput(
                    run_id=stack.run_id, revision_id=ack.revisions[0].revision_id, generation=1
                ),
            )

        async def pin():  # type: ignore[no-untyped-def]
            return await stack.outputs.pin_frontier(stack.host, stack.run_id)

        results = await asyncio.gather(*(promote(ack) for ack in (*same, *distinct)), pin(), pin())
        promoted = results[: len(same) + len(distinct)]
        same_results = promoted[: len(same)]
        assert sorted(item.status for item in same_results) == ["promoted", "refused", "refused"]
        assert all(item.status == "promoted" for item in promoted[len(same) :])
        for pinned in results[len(promoted) :]:
            # Each pinned set is a consistent snapshot: its digest is its members' digest.
            assert pinned.membership_digest == membership_digest(
                pinned.obligation_refs, pinned.members
            )
        heads = await stack.store.accepted_outputs(stack.host.scope, stack.run_id)
        assert sorted(item.deliverable_id for item in heads) == [
            "report-a",
            "report-b",
            "report-c",
            "report-d",
            "report-e",
        ]
        rows = await stack.store.output_set(
            stack.host.scope, (await stack.outputs.pin_frontier(stack.host, stack.run_id)).set_id
        )
        assert rows is not None and len(rows.members) == 5
        decided = fulfillment(await stack.evaluate(), "draft.reports")
        assert decided.distinct_count == 5  # three revisions of report-a counted once
    finally:
        await pool.close()


async def test_goal_scoped_waits_let_independent_work_proceed_on_postgres(
    wi07_db: CommonDatabase,
) -> None:
    pool = await wi07_db.pool()
    try:
        store = PostgresOutputContractStore(pool)
        promise = obligation(
            "goal.reports",
            OutputForm.REFERENCE,
            position="goal",
            cardinality=Cardinality(min=3, max=3),
            requirements=(Requirement(key="assessed", validator=PIN),),
        ).model_copy(update={"evaluation_scope": EvaluationScope.GOAL})
        stack = await build_stack(
            store, store, access_for(wi07_db, "goal-iteration/1/executor"), promise
        )
        stack.outputs._reference_uses = CurrentUse()
        bridge = ScriptedBridge(stack, {"a": "pass", "b": "review", "c": "pass"})

        async def iteration(number: int, *names: str) -> InvocationAccess:
            access = access_for(wi07_db, f"goal-iteration/{number}/executor")
            worker = await stack.start(access)
            ack = await worker.submit(
                f"i{number}", "goal.reports", *(handle(n) for n in names), position="goal"
            )
            assert ack.status == "accepted", ack.error
            await stack.submissions.finalize(access.identity(("goal.reports",)))
            return access

        one = await settlement(stack, bridge).settle(await iteration(1, "a", "b"), attempt=1)
        assert pending_or_raise(one) == () and len(one.goal_waits) == 1
        two = await settlement(stack, bridge).settle(await iteration(2, "c"), attempt=2)
        assert two.goal_waits and bridge.resumed == ["b"]
        assert fulfillment(await stack.evaluate(), "goal.reports").distinct_count == 2
        bridge.verdicts["b"] = "pass"
        await settlement(stack, bridge).settle(await iteration(3, "c"), attempt=3)
        done = await stack.evaluate()
        assert fulfillment(done, "goal.reports").disposition == "fulfilled"
        assert fulfillment(done, "goal.reports").distinct_count == 3
    finally:
        await pool.close()


async def test_the_verifier_plan_seals_the_current_set_index_in_the_plan_table(
    wi07_db: CommonDatabase,
) -> None:
    """The production resolvers over PostgreSQL: the verifier's sealed plan (0057 plan table)
    holds every accepted head, this iteration's subject and the index file member."""

    from mission_control.adapters.postgres.context.transfer_plans import PostgresTransferPlanStore
    from mission_control.application.context.materialization import (
        ApplicationSelectorResolver,
        LiteralResolver,
        ProducedOutputResolver,
        TransferMaterializer,
    )
    from mission_control.domain.outputs.current_set import CURRENT_SET_BINDING
    from tests.fixtures.knowledge_binding import InMemoryStaging
    from tests.unit.context.test_wi07_current_set_transfer import (
        Backend,
        request,
        verifier_selection,
    )

    pool = await wi07_db.pool()
    try:
        store = PostgresOutputContractStore(pool)
        promise = obligation(
            "goal.reports",
            OutputForm.TEXT,
            position="goal",
            cardinality=Cardinality(min=3, max=3),
        )
        stack = await build_stack(
            store, store, access_for(wi07_db, "goal-iteration/1/executor"), promise
        )
        first = await stack.submit("i1", "goal.reports", text("report-a", "A"), position="goal")
        await stack.submissions.finalize(stack.access.identity(("goal.reports",)))
        await stack.accept(first, "goal.reports")
        later = access_for(wi07_db, "goal-iteration/2/executor")
        worker = await stack.start(later)
        second = await worker.submit("i2", "goal.reports", text("report-b", "B"), position="goal")
        await stack.submissions.finalize(later.identity(("goal.reports",)))
        staging = InMemoryStaging()
        materializer = TransferMaterializer(
            store=PostgresTransferPlanStore(pool),
            staging=staging,
            custody=staging,
            resolvers={
                "produced_output": ProducedOutputResolver(store),
                "typed_literal": LiteralResolver(),
                "application_selector": ApplicationSelectorResolver(
                    {
                        CURRENT_SET_BINDING: CurrentSetIndexResolver(
                            store, clock=lambda: AT, trusted_validators=TRUSTED_VALIDATORS
                        )
                    }
                ),
            },
        )
        sealed = await materializer.materialize(
            request(stack, verifier_selection(2), "goal-iteration/2/verifier"), Backend()
        )
        sources = {m.source_ref: m.admission for m in sealed.plan.exact_sources}
        assert sources[first.revisions[0].revision_id] == "accepted"
        assert sources[second.revisions[0].revision_id] == "submitted"
        index = next(m for m in sealed.plan.exact_sources if m.binding == "current-set")
        assert index.file_name == "current-set.json" and index.source_ref.startswith("output-set:")
        rows = await owner_rows(wi07_db, "SELECT member_count FROM mission_control.transfer_plan")
        assert [row["member_count"] for row in rows] == [3]
    finally:
        await pool.close()


async def test_d21_text_and_progress_note_fulfillment_on_postgres(wi07_db: CommonDatabase) -> None:
    """W1 D21 on the real tables: requirement-free text of an accepted iteration is promoted
    and fulfilled; a per-iteration progress note is fulfilled after a rejected verdict while
    the summary is not; expected shortfall visible; optional silent."""

    from tests.unit.outputs.test_d21_iteration_records import promises

    pool = await wi07_db.pool()
    try:
        store = PostgresOutputContractStore(pool)
        stack = await build_stack(
            store, store, access_for(wi07_db, "goal-iteration/1/executor"), *promises()
        )
        for key, body in (("summary", "three models"), ("progress_note", "did A; next B")):
            ack = await stack.submit(
                f"s-{key}", f"root.{key}", text(key.replace("_", "-"), body), position="root"
            )
            assert ack.status == "accepted", ack.error
        await stack.submissions.finalize(
            stack.access.identity(("root.summary", "root.progress_note"))
        )

        async def converge(promote: bool):  # type: ignore[no-untyped-def]
            return await stack.outputs.converge(
                stack.host,
                stack.run_id,
                operation_ref="goal-iteration/1/executor",
                generation=1,
                promote=promote,
            )

        rejected = await converge(False)
        assert fulfillment(rejected, "root.progress_note").disposition == "fulfilled"
        assert codes(rejected, "root.summary") == ["SUBMITTED_NOT_ACCEPTED"]
        accepted = await converge(True)
        assert fulfillment(accepted, "root.summary").disposition == "fulfilled"
        assert accepted.shortfalls == ("root.appendix",)
        assert accepted.completion == "satisfied"
        rows = await owner_rows(
            wi07_db,
            "SELECT obligation_key, disposition FROM mission_control.obligation_fulfillment "
            "WHERE output_set_id = $1::uuid",
            accepted.set_id,
        )
        assert {row["obligation_key"]: row["disposition"] for row in rows}["root.summary"] == (
            "fulfilled"
        )
    finally:
        await pool.close()


async def test_trusted_member_decisions_verify_against_recorded_bridge_decisions(
    wi07_db: CommonDatabase,
) -> None:
    """Review S2 on the real tables: a trusted-pinned member counts only through a citation the
    production port finds as a bridge-recorded decision (0059) bound to that exact member; none
    -> MEMBER_UNASSESSED; another actor's row does not count; a revocation (the bridge's
    superseding assessment) stops it counting."""

    from mission_control.adapters.postgres.knowledge.use_decisions import (
        PostgresMemberDecisions,
        PostgresUseDecisionStore,
        member_binding,
    )
    from mission_control.application.outputs.fulfillment import AssessmentInput, HostAccess
    from mission_control.application.ports.knowledge import RecordedUseDecision
    from mission_control.domain.knowledge.judgment import TRUSTED_BRIDGE_ACTOR, decision_evidence
    from tests.unit.knowledge.test_wi07_report_collections import Lineage
    from tests.unit.outputs.test_collections import TRUSTED_PIN

    pool = await wi07_db.pool()
    try:
        store = PostgresOutputContractStore(pool)
        stack = await build_stack(
            store, store, access_for(wi07_db), collection_promise(validator=TRUSTED_PIN)
        )
        stack.outputs._member_decisions = PostgresMemberDecisions(
            pool, bridge_actor=TRUSTED_BRIDGE_ACTOR
        )
        a, b = report("a"), report("b")
        ack = await stack.submit("k1", "draft.reports", collection(members=(a, b)))
        manifest = await stack.accept(ack, "draft.reports")
        bridge = HostAccess(
            scope=stack.host.scope,
            actor_ref=TRUSTED_BRIDGE_ACTOR,
            origin_ref="ks:aiengineer-postgres/use_decision/members",
            role="assessor",
        )

        async def cited(member, decision: str, result: str = "pass", supersedes=None):  # type: ignore[no-untyped-def]
            receipt = await stack.outputs.record_assessment(
                bridge,
                AssessmentInput(
                    run_id=stack.run_id,
                    subject_kind="member",
                    subject_id=member.ref,
                    subject_digest=member.digest,
                    index_revision_id=manifest,
                    requirement_results={"verified": result},
                    method_pin=TRUSTED_PIN,
                    policy_pin="policy@1",
                    evidence_refs=(decision_evidence(decision, member.digest),),
                    supersedes=supersedes,
                ),
                lineage=Lineage(),
            )
            assert receipt.status == "recorded", receipt.error
            return receipt.assessment

        decisions = PostgresUseDecisionStore(pool)

        async def recorded(member, decision: str, handle: str, actor: str) -> None:  # type: ignore[no-untyped-def]
            await decisions.record(
                stack.host.scope,
                RecordedUseDecision(
                    handle=handle,
                    binding_id="aiengineer-postgres",
                    tenant_id=stack.access.origin.tenant_id,
                    use_decision_id=decision,
                    bound_effect_digest=member.digest,
                    processed_epoch=1,
                    plan=member_binding(member.ref, member.digest),
                ),
                actor_ref=actor,
                at=AT,
            )

        held_a = await cited(a, "d-a")
        await cited(b, "d-b")
        none = await stack.evaluate()
        assert codes(none, "draft.reports") == ["MEMBER_UNASSESSED", "MEMBER_UNASSESSED"]
        await recorded(a, "d-a", "ud-a", TRUSTED_BRIDGE_ACTOR)
        await recorded(b, "d-b", "ud-b-other", "mission-control:someone-else")
        partial = await stack.evaluate()
        assert codes(partial, "draft.reports") == ["MEMBER_UNASSESSED"]
        assert b.ref in fulfillment(partial, "draft.reports").unmet[0].message
        await recorded(b, "d-b", "ud-b", TRUSTED_BRIDGE_ACTOR)
        genuine = await stack.evaluate()
        assert fulfillment(genuine, "draft.reports").disposition == "fulfilled"
        # Revocation: the bridge supersedes a's pass with a review citing the KS successor.
        await cited(a, "d-a-2", result="review", supersedes=held_a.assessment_id)
        revoked = await stack.evaluate()
        assert fulfillment(revoked, "draft.reports").disposition != "fulfilled"
        assert a.ref in fulfillment(revoked, "draft.reports").unmet[0].message
    finally:
        await pool.close()
