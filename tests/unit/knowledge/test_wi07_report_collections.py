"""WI-07 / OVE-170: a report collection is assessed per member; goal-scoped waits do not hold.

The trusted settlement pass (``application/knowledge/trusted_settlement.py``) over the in-memory
1.7.0 store with a scripted bridge standing in for the KS transport (the real bridge is proven in
``test_trusted_judgment.py`` and on PostgreSQL). Proves: one ``submit_output`` act naming three
report handles finalizes (the OVE-160 refusal applies to the legacy selection path only) and is
assessed per exact revision, never through one report; a held member of a goal-scoped promise
never holds its invocation while an invocation-scoped one does; a later invocation's settlement
re-resolves the goal wait and promotes the approved member exactly once; successes are retained.
"""

from __future__ import annotations

from typing import Any

import pytest

from mission_control.application.knowledge.trusted_settlement import (
    pending_or_raise,
)
from mission_control.application.outputs.submission_service import SubmissionService
from mission_control.domain.outputs.contracts import (
    EvaluationScope,
)
from tests.fixtures.output_contracts import InMemoryOutputContractStore
from tests.support.unit.knowledge.wi07_report_collections import (
    ScriptedBridge,
    handle,
    invocation,
    run_iteration,
    settlement,
    stack_with,
)
from tests.unit.outputs.scenario import digest_of, fulfillment

pytestmark = pytest.mark.asyncio


class NoLegacyAssessor:
    """The K01 single-report handoff must not run for a named multi-report act."""

    binding = "aiengineer-postgres"

    async def invoke(self, call: Any, access: Any) -> Any:
        raise AssertionError("one report must never stand for the collection")

    async def poll(self, record: Any, caller: Any, *, scope: str) -> Any:
        raise AssertionError

    async def stored_handle(self, scope: str, operation_id: str) -> Any:
        return None


async def test_one_named_act_with_three_reports_is_assessed_per_exact_revision() -> None:
    stack = await stack_with(EvaluationScope.GOAL)
    stack.submissions._assessor = NoLegacyAssessor()  # type: ignore[assignment]
    bridge = ScriptedBridge(stack, {"a": "pass", "b": "pass", "c": "fail"})
    access = await run_iteration(stack, 1, "a", "b", "c")
    passed = await settlement(stack, bridge).settle(access, attempt=1)
    assert sorted(bridge.assessed) == ["a", "b", "c"]  # each member judged once, by itself
    assert len(passed.promoted) == 2 and not pending_or_raise(passed)
    result = await stack.evaluate()
    decided = fulfillment(result, "goal.reports")
    assert decided.distinct_count == 2 and decided.disposition == "unfulfilled"


async def test_the_legacy_selection_keeps_its_one_report_refusal() -> None:
    store = InMemoryOutputContractStore()
    service = SubmissionService(store.submissions)
    from mission_control.application.outputs.submission_service import (
        OutputSelection,
        SelectedItem,
    )

    items = tuple(
        SelectedItem(kind="handle", ref=handle(name).ref or "", digest=digest_of(name))
        for name in ("a", "b")
    )
    with pytest.raises(ValueError, match="report must be the only selected item"):
        await service.submit(
            invocation("legacy"), "report", OutputSelection(items=items), "collection"
        )


async def test_a_goal_scoped_review_wait_never_holds_independent_work() -> None:
    stack = await stack_with(EvaluationScope.GOAL)
    bridge = ScriptedBridge(stack, {"a": "pass", "b": "review", "c": "pass"})
    first = await run_iteration(stack, 1, "a", "b")
    one = await settlement(stack, bridge).settle(first, attempt=1)
    assert pending_or_raise(one) == ()  # the invocation settles; independent work proceeds
    assert len(one.goal_waits) == 1 and "d-b" in one.goal_waits[0]
    blocked = await stack.evaluate()
    assert fulfillment(blocked, "goal.reports").disposition == "unfulfilled"  # acceptance blocked
    # Iteration 2 works independently; its settlement re-resolves the standing goal wait.
    second = await run_iteration(stack, 2, "c")
    two = await settlement(stack, bridge).settle(second, attempt=2)
    assert bridge.resumed == ["b"] and two.goal_waits and not pending_or_raise(two)
    assert fulfillment(await stack.evaluate(), "goal.reports").distinct_count == 2
    # The reviewer approves; the next settlement promotes b exactly once; a and c are retained.
    bridge.verdicts["b"] = "pass"
    third = await run_iteration(stack, 3, "c")  # a repeat of c: same content, no new deliverable
    three = await settlement(stack, bridge).settle(third, attempt=3)
    assert three.goal_waits == () and len(three.promoted) >= 1
    done = await stack.evaluate()
    assert fulfillment(done, "goal.reports").disposition == "fulfilled"
    assert fulfillment(done, "goal.reports").distinct_count == 3
    heads = await stack.store.accepted_outputs(stack.host.scope, stack.run_id)
    assert sorted(item.deliverable_id for item in heads) == ["report-a", "report-b", "report-c"]
    again = await settlement(stack, bridge).settle(third, attempt=4)
    assert again.goal_waits == ()  # nothing waits any more; no duplicate head moves
    assert len(await stack.store.accepted_outputs(stack.host.scope, stack.run_id)) == 3


async def test_an_invocation_scoped_review_still_holds_its_own_invocation() -> None:
    stack = await stack_with(EvaluationScope.INVOCATION)
    bridge = ScriptedBridge(stack, {"a": "review"})
    access = await run_iteration(stack, 1, "a")
    passed = await settlement(stack, bridge).settle(access, attempt=1)
    assert pending_or_raise(passed) and passed.goal_waits == ()
    # A later pass of the same saved result keeps holding on the exact decision (the held
    # revision is no longer a submitted output, so only the resume pass sees it), never lost.
    again = await settlement(stack, bridge).settle(access, attempt=2)
    assert again.pending_reviews == passed.pending_reviews and bridge.resumed == ["a"]
    # Another invocation's settlement never re-resolves this invocation-scoped wait.
    other = await settlement(stack, bridge).settle(
        invocation("goal-iteration/9/executor"), attempt=3
    )
    assert other.pending_reviews == () and bridge.resumed == ["a"]
    bridge.verdicts["a"] = "pass"
    approved = await settlement(stack, bridge).settle(access, attempt=4)
    assert approved.pending_reviews == () and len(approved.promoted) == 1
