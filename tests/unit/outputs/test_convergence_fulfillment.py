"""W1 (OVE-169): explicit fulfillment at the GoalDirected convergence boundary (in-memory rules).

`OutputFulfillmentService.converge` promotes the newest finalized submission of every promise
whose contract declares no required independent requirement (its shape was proven by the
submission act), never one that a trusted assessment must promote, then pins the accepted set
and records `Fulfillment@1` for every declared promise: required absence blocks, expected
shortfall is visible, optional absence is silent. `bind_fulfillment` makes the verifier's
acceptance stand only when every required promise is fulfilled.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from mission_control.adapters.outputs.memory import InMemoryOutputContractStore
from mission_control.application.knowledge.access import InvocationAccess
from mission_control.application.outputs.fulfillment import (
    OutputFulfillmentService,
    PromoteOutput,
)
from mission_control.application.programs.goal_directed import bind_fulfillment
from mission_control.domain.outputs.contracts import (
    Enforcement,
    EvaluationScope,
    OutputForm,
    OutputObligation,
    Requirement,
)
from tests.support.knowledge.gateway import origin
from tests.support.unit.outputs.convergence_fulfillment import _observation
from tests.support.unit.outputs.iteration_records import note, promises
from tests.unit.outputs.scenario import (
    Stack,
    build_stack,
    codes,
    fulfillment,
    obligation,
    text,
)

pytestmark = pytest.mark.asyncio
AT = datetime(2026, 10, 28, 12, tzinfo=UTC)
OPERATION = "op-research-1"  # the producing operation of `origin()`


def _access() -> InvocationAccess:
    return InvocationAccess(
        origin=origin(1),
        subject="mission-control-runtime",
        invocation_id="inv-0001",
        authenticated_at=AT,
    )


async def _stack(*, refresh: bool = False) -> tuple[Stack, InMemoryOutputContractStore]:
    store = InMemoryOutputContractStore()
    stack = await build_stack(
        store,
        store.submissions,
        _access(),
        obligation("report.note", OutputForm.TEXT),
        obligation("report.appendix", OutputForm.TEXT, enforcement=Enforcement.EXPECTED),
        obligation("report.extra", OutputForm.TEXT, enforcement=Enforcement.OPTIONAL),
        obligation(
            "report.review",
            OutputForm.TEXT,
            enforcement=Enforcement.OPTIONAL,
            requirements=(Requirement(key="grounded", validator="ks.verify@1"),),
        ),
        obligation(
            "report.style",
            OutputForm.TEXT,
            enforcement=Enforcement.OPTIONAL,
            requirements=(Requirement(key="tone", validator="ks.verify@1", required=False),),
        ),
    )
    if refresh:
        stack = Stack(
            store,
            stack.submissions,
            OutputFulfillmentService(store, stack.submissions, refresh_on_change=True),
            stack.access,
            stack.host,
            stack.assessor,
        )
    return stack, store


async def _converge(stack: Stack, *, promote: bool = True):  # type: ignore[no-untyped-def]
    return await stack.outputs.converge(
        stack.host, stack.run_id, operation_ref=OPERATION, generation=1, promote=promote
    )


async def _head(stack: Stack, store: InMemoryOutputContractStore, key: str, deliverable: str):  # type: ignore[no-untyped-def]
    return await store.accepted_head(stack.host.scope, stack.run_id, key, deliverable)


async def test_required_fulfilled_expected_shortfall_visible_optional_silent() -> None:
    stack, store = await _stack()
    await stack.submit("s-note", "report.note", text("note", "progress: 2 of 3 checks"))
    await stack.submit("s-review", "report.review", text("review", "draft review"))
    await stack.submissions.finalize(stack.access.identity(("report.note", "report.review")))

    result = await _converge(stack)
    assert result is not None
    assert fulfillment(result, "report.note").disposition == "fulfilled"
    assert result.completion == "satisfied" and result.blocking == ()
    # Expected shortfall visible; submitted-but-unaccepted optional material visible (W1 D29).
    assert result.shortfalls == ("report.appendix", "report.review")
    assert codes(result, "report.review") == ["SUBMITTED_NOT_ACCEPTED"]
    assert "report.extra" not in result.shortfalls  # optional absence: silent
    # A promise a trusted assessment must promote is never promoted by convergence.
    head = await store.accepted_head(stack.host.scope, stack.run_id, "report.review", "review")
    assert head is None
    assert fulfillment(result, "report.review").disposition != "fulfilled"
    # Idempotent: the same set, the same recorded decisions.
    recorded = len(store.fulfillments)
    again = await _converge(stack)
    assert again is not None and again.set_id == result.set_id
    assert len(store.fulfillments) == recorded


async def test_required_missing_is_unmet_and_blocks() -> None:
    stack, _store = await _stack()
    result = await _converge(stack)
    assert result is not None
    assert result.completion != "satisfied"
    assert "report.note" in result.blocking
    assert fulfillment(result, "report.note").disposition != "fulfilled"


async def test_an_unfinalized_draft_is_not_promoted() -> None:
    stack, store = await _stack()
    await stack.submit("s-note", "report.note", text("note", "progress"))
    result = await _converge(stack)
    assert result is not None and "report.note" in result.blocking
    assert await store.accepted_head(stack.host.scope, stack.run_id, "report.note", "note") is None


async def test_a_run_without_promises_converges_to_nothing() -> None:
    stack, _store = await _stack()
    assert (
        await stack.outputs.converge(
            stack.host,
            "99999999-9999-4999-8999-999999999999",
            operation_ref=OPERATION,
            generation=1,
        )
        is None
    )


async def test_production_refreshes_fulfillment_after_each_head_move() -> None:
    stack, store = await _stack(refresh=True)
    ack = await stack.submit("s-note", "report.note", text("note", "progress"))
    before = len(store.fulfillments)
    await stack.accept(ack, "report.note")
    assert len(store.fulfillments) > before  # the promotion itself decided the frontier
    decided = {item.obligation_key: item.disposition for item in store.fulfillments.values()}
    assert decided["report.note"] == "fulfilled"


async def test_the_verdict_stands_only_when_every_required_promise_is_fulfilled() -> None:
    stack, _store = await _stack()
    missing = await _converge(stack)
    assert missing is not None
    bound = bind_fulfillment(_observation(), missing)
    assert bound.decision == "rejected" and bound.accepted_obligation_refs == ()
    assert "output:report.note" in bound.unmet_obligations
    assert any(ref.startswith("output-fulfillment:") for ref in bound.evidence_refs)

    await stack.submit("s-note", "report.note", text("note", "progress"))
    await stack.submissions.finalize(stack.access.identity(("report.note",)))
    met = await _converge(stack)
    assert met is not None
    kept = bind_fulfillment(_observation(), met)
    assert kept.decision == "accepted"
    assert kept.accepted_obligation_refs == ("obligation:goal",)
    assert "expected output shortfall: report.appendix" in kept.findings
    assert not any("report.extra" in item for item in kept.findings)
    # A rejection is never upgraded by a satisfied frontier.
    assert bind_fulfillment(_observation("rejected"), met).decision == "rejected"


async def test_a_rejected_iteration_never_promotes_its_output() -> None:
    """Review S1: promotion follows the verdict; a rejected iteration only evaluates."""

    stack, store = await _stack()
    await stack.submit("s-note", "report.note", text("note", "progress"))
    await stack.submissions.finalize(stack.access.identity(("report.note",)))
    rejected = await _converge(stack, promote=False)
    assert rejected is not None and "report.note" in rejected.blocking
    assert await _head(stack, store, "report.note", "note") is None
    accepted = await _converge(stack, promote=True)
    assert accepted is not None and accepted.completion == "satisfied"


async def test_any_declared_requirement_leaves_promotion_to_the_assessment_path() -> None:
    """Review S2: a required-requirement and an optional-only-requirement promise alike."""

    stack, store = await _stack()
    await stack.submit("s-review", "report.review", text("review", "draft review"))
    await stack.submit("s-style", "report.style", text("style", "draft style"))
    await stack.submissions.finalize(stack.access.identity(("report.review", "report.style")))
    await _converge(stack)
    assert await _head(stack, store, "report.review", "review") is None
    assert await _head(stack, store, "report.style", "style") is None


async def test_a_failed_or_never_finalized_attempt_is_not_promoted() -> None:
    """Review N2: only a finalized, not failed, invocation's submission counts. A cancelled or
    stopped attempt records no finalization at all (the stop cancels handles and reconciles
    effects, it does not finalize), and the finalization basis vocabulary has no other
    terminal value (0056: declared_obligations, no_declared_obligations, assessed,
    attempt_failed, legacy submission_coverage)."""

    stack, store = await _stack()
    await stack.submit("s-note", "report.note", text("note", "progress"))
    await stack.submissions.finalize(stack.access.identity(("report.note",)), attempt_failed=True)
    result = await _converge(stack)
    assert result is not None and "report.note" in result.blocking
    assert await _head(stack, store, "report.note", "note") is None


async def test_a_pending_review_on_a_required_promise_never_accepts_the_iteration() -> None:
    """Intended behaviour: the executor's saved settlement already waits while its trusted
    review is pending (WI-04 `review_pending`), so the boundary normally sees a decided review.
    A review still pending here (raised after settlement) never lets an unreviewed revision be
    accepted: the promise is not fulfilled, the verdict becomes a rejection naming it, and that
    iteration is consumed; the decided review is consumed by the next boundary
    (OUTPUT-CONTRACTS: a held revision is never made valid by waiting; no cognition reruns)."""

    store = InMemoryOutputContractStore()
    stack = await build_stack(
        store,
        store.submissions,
        _access(),
        obligation(
            "report.main",
            OutputForm.TEXT,
            requirements=(Requirement(key="grounded", validator="ks.verify@1"),),
        ),
    )
    ack = await stack.submit("s-main", "report.main", text("main", "draft report"))
    await stack.submissions.finalize(stack.access.identity(("report.main",)))
    revision = ack.revisions[0]
    await stack.judge(revision.revision_id, revision.content_digest, grounded="review")
    result = await _converge(stack)
    assert result is not None and result.completion != "satisfied"
    bound = bind_fulfillment(_observation(), result)
    assert bound.decision == "rejected"
    assert "output:report.main" in bound.unmet_obligations


async def test_a_failed_refresh_never_fails_the_committed_promotion() -> None:
    """Review S3: the post-commit refresh is best effort; convergence recomputes."""

    stack, store = await _stack(refresh=True)
    ack = await stack.submit("s-note", "report.note", text("note", "progress"))

    async def broken(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("pin failed")

    store.pin_set = broken  # type: ignore[method-assign]
    head = await _head(stack, store, "report.note", "note")
    promoted = await stack.outputs.promote_output(
        stack.host,
        PromoteOutput(
            run_id=stack.run_id,
            revision_id=ack.revisions[0].revision_id,
            expected_head=None if head is None else head.revision_id,
            generation=1,
        ),
    )
    assert promoted.status == "promoted"


# W1 D21: requirement-free text promises of a GoalDirected executor (OUTPUT-CONTRACTS §2, §7).
# A promise authored as a per-iteration record (`evaluation_scope: iteration`, no requirement)
# is satisfied by its iteration's own submission whatever the verdict, since a rejected verdict
# still hands off; every other promise keeps fix D (a rejected iteration's output never becomes
# an accepted head).

EXECUTOR = "goal-iteration/1/executor"


async def _executor_stack(*items: OutputObligation) -> Stack:
    store = InMemoryOutputContractStore()
    access = InvocationAccess(
        origin=origin(1, operation_id=EXECUTOR),
        subject="mission-control-runtime",
        invocation_id="inv-" + EXECUTOR.replace("/", "-"),
        authenticated_at=AT,
    )
    return await build_stack(store, store.submissions, access, *items)


async def _submit_and_finalize(stack: Stack, **bodies: str) -> None:
    for key, body in bodies.items():
        ack = await stack.submit(
            f"s-{key}", f"root.{key}", text(key.replace("_", "-"), body), position="root"
        )
        assert ack.status == "accepted", ack.error
    await stack.submissions.finalize(stack.access.identity(tuple(f"root.{k}" for k in bodies)))


async def _converge_executor(stack: Stack, *, promote: bool):  # type: ignore[no-untyped-def]
    return await stack.outputs.converge(
        stack.host, stack.run_id, operation_ref=EXECUTOR, generation=1, promote=promote
    )


async def test_requirement_free_text_of_an_accepted_iteration_is_promoted_and_fulfilled() -> None:
    stack = await _executor_stack(*promises())
    await _submit_and_finalize(stack, summary="three models", progress_note="did A; next B")
    result = await _converge_executor(stack, promote=True)
    assert fulfillment(result, "root.summary").disposition == "fulfilled"
    assert fulfillment(result, "root.progress_note").disposition == "fulfilled"
    assert result.shortfalls == ("root.appendix",)  # expected shortfall stays visible
    assert "root.caveats" not in result.shortfalls  # optional absence is silent
    assert result.completion == "satisfied"


async def test_a_rejected_iteration_still_records_its_progress_note_but_nothing_else() -> None:
    stack = await _executor_stack(*promises())
    await _submit_and_finalize(stack, summary="three models", progress_note="did A; next B")
    result = await _converge_executor(stack, promote=False)
    assert fulfillment(result, "root.progress_note").disposition == "fulfilled"
    assert codes(result, "root.summary") == [
        "SUBMITTED_NOT_ACCEPTED"
    ]  # fix D: no accepted head from rejection
    assert result.blocking == ("root.summary",) and result.completion == "waiting"


async def test_an_invocation_scoped_note_keeps_the_verdict_gate() -> None:
    stack = await _executor_stack(note(EvaluationScope.INVOCATION))
    await _submit_and_finalize(stack, progress_note="did A")
    assert codes(await _converge_executor(stack, promote=False), "root.progress_note") == [
        "SUBMITTED_NOT_ACCEPTED"
    ]
    accepted = await _converge_executor(stack, promote=True)
    assert fulfillment(accepted, "root.progress_note").disposition == "fulfilled"


async def test_a_note_with_a_declared_requirement_belongs_to_the_assessment_path() -> None:
    checked = note(requirements=(Requirement(key="cited", validator="mc.check.cited@1"),))
    stack = await _executor_stack(checked)
    await _submit_and_finalize(stack, progress_note="did A")
    for verdict in (False, True):
        assert codes(await _converge_executor(stack, promote=verdict), "root.progress_note") == [
            "SUBMITTED_NOT_ACCEPTED"
        ]


async def test_a_missing_progress_note_is_never_fabricated() -> None:
    stack = await _executor_stack(*promises())
    await _submit_and_finalize(stack, summary="three models")
    result = await _converge_executor(stack, promote=False)
    assert codes(result, "root.progress_note") == ["MISSING"]
    assert "root.progress_note" in result.blocking
