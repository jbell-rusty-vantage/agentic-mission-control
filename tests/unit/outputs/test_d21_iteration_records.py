"""W1 D21: requirement-free text promises at the GoalDirected convergence boundary.

OUTPUT-CONTRACTS §2 (text: exact bytes; required absence blocks, expected shortfall visible,
optional absence silent) and §7 ("a compact attributed progress note at each normal iteration
handoff"): a requirement-free text promise submitted in a finalized invocation of an ACCEPTED
iteration is promoted and fulfilled; a promise authored as a per-iteration record
(``evaluation_scope: iteration``, text or control_record, no requirement) is satisfied by its
iteration's own submission whatever the verdict, since a rejected verdict still hands off; every
other promise keeps fix D (a rejected iteration's output never becomes an accepted head).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from mission_control.application.knowledge.access import InvocationAccess
from mission_control.domain.outputs.contracts import (
    Enforcement,
    EvaluationScope,
    OutputForm,
    OutputObligation,
    Requirement,
)
from tests.fixtures.output_contracts import InMemoryOutputContractStore
from tests.unit.knowledge.test_gateway import origin
from tests.unit.outputs.scenario import Stack, build_stack, codes, fulfillment, obligation, text

pytestmark = pytest.mark.asyncio
AT = datetime(2026, 10, 28, 12, tzinfo=UTC)
EXECUTOR = "goal-iteration/1/executor"


def invocation(operation: str = EXECUTOR) -> InvocationAccess:
    return InvocationAccess(
        origin=origin(1, operation_id=operation),
        subject="mission-control-runtime",
        invocation_id="inv-" + operation.replace("/", "-"),
        authenticated_at=AT,
    )


def note(scope: EvaluationScope = EvaluationScope.ITERATION, **extra: object) -> OutputObligation:
    return obligation("root.progress_note", OutputForm.TEXT, position="root", **extra).model_copy(
        update={"evaluation_scope": scope}
    )


def promises() -> tuple[OutputObligation, ...]:
    return (
        obligation("root.summary", OutputForm.TEXT, position="root"),
        note(),
        obligation(
            "root.appendix", OutputForm.TEXT, position="root", enforcement=Enforcement.EXPECTED
        ),
        obligation(
            "root.caveats", OutputForm.TEXT, position="root", enforcement=Enforcement.OPTIONAL
        ),
    )


async def make_stack(*items: OutputObligation) -> Stack:
    store = InMemoryOutputContractStore()
    return await build_stack(store, store.submissions, invocation(), *items)


async def submit_and_finalize(stack: Stack, **bodies: str) -> None:
    for key, body in bodies.items():
        ack = await stack.submit(
            f"s-{key}", f"root.{key}", text(key.replace("_", "-"), body), position="root"
        )
        assert ack.status == "accepted", ack.error
    await stack.submissions.finalize(stack.access.identity(tuple(f"root.{k}" for k in bodies)))


async def converge(stack: Stack, *, promote: bool):  # type: ignore[no-untyped-def]
    return await stack.outputs.converge(
        stack.host, stack.run_id, operation_ref=EXECUTOR, generation=1, promote=promote
    )


async def test_requirement_free_text_of_an_accepted_iteration_is_promoted_and_fulfilled() -> None:
    stack = await make_stack(*promises())
    await submit_and_finalize(stack, summary="three models", progress_note="did A; next B")
    result = await converge(stack, promote=True)
    assert fulfillment(result, "root.summary").disposition == "fulfilled"
    assert fulfillment(result, "root.progress_note").disposition == "fulfilled"
    assert result.shortfalls == ("root.appendix",)  # expected shortfall stays visible
    assert "root.caveats" not in result.shortfalls  # optional absence is silent
    assert result.completion == "satisfied"


async def test_a_rejected_iteration_still_records_its_progress_note_but_nothing_else() -> None:
    stack = await make_stack(*promises())
    await submit_and_finalize(stack, summary="three models", progress_note="did A; next B")
    result = await converge(stack, promote=False)
    assert fulfillment(result, "root.progress_note").disposition == "fulfilled"
    assert codes(result, "root.summary") == [
        "SUBMITTED_NOT_ACCEPTED"
    ]  # fix D: no accepted head from rejection
    assert result.blocking == ("root.summary",) and result.completion == "waiting"


async def test_an_invocation_scoped_note_keeps_the_verdict_gate() -> None:
    stack = await make_stack(note(EvaluationScope.INVOCATION))
    await submit_and_finalize(stack, progress_note="did A")
    assert codes(await converge(stack, promote=False), "root.progress_note") == [
        "SUBMITTED_NOT_ACCEPTED"
    ]
    assert fulfillment(await converge(stack, promote=True), "root.progress_note").disposition == (
        "fulfilled"
    )


async def test_a_note_with_a_declared_requirement_belongs_to_the_assessment_path() -> None:
    checked = note(requirements=(Requirement(key="cited", validator="mc.check.cited@1"),))
    stack = await make_stack(checked)
    await submit_and_finalize(stack, progress_note="did A")
    for verdict in (False, True):
        assert codes(await converge(stack, promote=verdict), "root.progress_note") == [
            "SUBMITTED_NOT_ACCEPTED"
        ]


async def test_a_missing_progress_note_is_never_fabricated() -> None:
    stack = await make_stack(*promises())
    await submit_and_finalize(stack, summary="three models")
    result = await converge(stack, promote=False)
    assert codes(result, "root.progress_note") == ["MISSING"]
    assert "root.progress_note" in result.blocking
