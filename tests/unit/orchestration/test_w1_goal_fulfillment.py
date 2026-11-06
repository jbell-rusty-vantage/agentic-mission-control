"""W1 (OVE-169): the GoalDirected verifier reconciliation consumes the run's recorded fulfillment.

Through the governed composition (real run control, the real operation boundary): the verifier's
acceptance stands only when the convergence boundary's `Fulfillment@1` decision says every
required promise is fulfilled; otherwise the recorded verification is a rejection naming the
unmet promise, and the convergence policy cannot complete the run.
"""

from __future__ import annotations

from typing import Any

import pytest

from mission_control.domain.outputs.contracts import FulfillmentResult
from mission_control.domain.programs.runtime_units import goal_operation_id
from tests.fixtures.goal_directed_journaled import SCOPE
from tests.unit.orchestration.test_rrm_016_goal_directed_settlement import (
    _composition,
    _run_iteration_one,
)

DIGEST = "sha256:" + "4" * 64


class RecordingConvergence:
    def __init__(self, result: FulfillmentResult | None) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    async def converge(
        self,
        access: Any,
        run_id: str,
        *,
        operation_ref: str,
        generation: int,
        promote: bool = True,
    ) -> FulfillmentResult | None:
        self.calls.append(
            {
                "scope": access.scope,
                "run_id": run_id,
                "operation_ref": operation_ref,
                "generation": generation,
                "promote": promote,
            }
        )
        return self.result


def _frontier(**fields: Any) -> FulfillmentResult:
    return FulfillmentResult(set_id="set-1", membership_digest=DIGEST, fulfillments=(), **fields)


async def _verified(result: FulfillmentResult | None) -> tuple[Any, RecordingConvergence, str]:
    composition, run_id = await _composition()
    composition.model.accept_at = 1  # the scripted verifier accepts iteration 1
    convergence = RecordingConvergence(result)
    composition.family._results._fulfillment = convergence
    observed = await _run_iteration_one(composition, run_id)
    verification = observed["verifier"].verification_result
    assert verification is not None
    return verification, convergence, run_id


@pytest.mark.asyncio
async def test_a_required_promise_unmet_turns_the_acceptance_into_a_rejection() -> None:
    verification, convergence, run_id = await _verified(
        _frontier(completion="waiting", blocking=("root.report",), shortfalls=("root.summary",))
    )
    (call,) = convergence.calls
    assert call == {
        "scope": SCOPE,
        "run_id": run_id,
        "operation_ref": goal_operation_id(1, "executor"),
        "generation": 1,
        "promote": True,  # the verifier accepted: its output may become the accepted head
    }
    assert verification.decision == "rejected"
    assert verification.accepted_obligation_refs == ()
    assert "output:root.report" in verification.unmet_obligations
    assert "expected output shortfall: root.summary" in verification.findings
    assert f"output-fulfillment:set-1@{DIGEST}" in verification.evidence_refs


@pytest.mark.asyncio
async def test_required_promises_fulfilled_keep_the_acceptance() -> None:
    verification, _convergence, _run_id = await _verified(
        _frontier(completion="satisfied", shortfalls=("root.summary",))
    )
    assert verification.decision == "accepted"
    assert verification.accepted_obligation_refs
    assert "expected output shortfall: root.summary" in verification.findings


@pytest.mark.asyncio
async def test_a_run_without_promises_is_judged_by_its_verifier_alone() -> None:
    verification, convergence, _run_id = await _verified(None)
    assert len(convergence.calls) == 1
    assert verification.decision == "accepted"
    assert not any(ref.startswith("output-fulfillment:") for ref in verification.evidence_refs)


@pytest.mark.asyncio
async def test_a_rejected_verdict_converges_without_promotion() -> None:
    composition, run_id = await _composition()  # the scripted verifier rejects iteration 1
    convergence = RecordingConvergence(_frontier(completion="satisfied"))
    composition.family._results._fulfillment = convergence
    observed = await _run_iteration_one(composition, run_id)
    assert observed["verifier"].verification_result.decision == "rejected"
    ((call),) = convergence.calls
    assert call["promote"] is False
