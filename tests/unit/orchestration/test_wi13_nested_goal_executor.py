"""OVE-176 / WI-13: a Goal Loop whose executor phase is a nested body reconciles the body's export
receipt and reservation settlement as the iteration's execution result (never a provider result
of an operation that did not run)."""

from __future__ import annotations

from typing import Any

import pytest
from temporalio.exceptions import ApplicationError

from mission_control.domain.authoring.nested_bodies import NestedBody, NestedExport
from mission_control.domain.execution.contracts import (
    OperationExecutionResult,
    OperationWorkflowResult,
)
from mission_control.domain.programs.nested import (
    ChildTerminal,
    executor_result,
    project_exports,
)
from tests.unit.orchestration.test_rrm_016_goal_directed_settlement import _reconciliation
from tests.unit.orchestration.test_w1_goal_failure_paths import _executor_dispatch

DIGEST = "sha256:" + "c" * 64
BODY = NestedBody(
    host_id="executor",
    node_key="pass",
    position="refine/pass",
    behavior="stage_graph",
    family="StageGraph",
    depth=1,
    max_depth=2,
    definition_digest=DIGEST,
    blueprint_digest=DIGEST,
    exports=(NestedExport(output="report", source="draft.report"),),
)


def nested_request(claim: Any, dispatch: Any, terminal: ChildTerminal, **settled: Any) -> Any:
    accepted = {"draft.report": ("output:r1@sha256:1",)} if terminal.outcome == "accepted" else {}
    projection = project_exports(BODY, "child-1", terminal, accepted, actual_usage={"t": 7})
    disposition, payload = executor_result(projection)
    payload["nested_settlement"] = {
        "reservation_id": claim.reservation_id,
        "usage": dict(projection.actual_usage),
        "settled_run_version": 11,
        "reason_code": "",
        **settled,
    }
    answer = OperationExecutionResult(
        binding_id=dispatch.operation_binding_ref,
        semantic_attempt_key=dispatch.workflow_request.semantic_attempt_id,
        status="completed",
    )
    return _reconciliation(claim, "executor", dispatch, answer).model_copy(
        update={
            "operation_result": OperationWorkflowResult(
                semantic_attempt_id=dispatch.workflow_request.semantic_attempt_id,
                execution_generation=1,
                disposition=disposition,
                result=payload,
                message_cursor=0,
            )
        }
    )


@pytest.mark.asyncio
async def test_an_accepted_body_is_the_iterations_exact_execution_result() -> None:
    composition, _run_id, claim, dispatch = await _executor_dispatch()
    reconciled = await composition.family.reconcile_nested_executor(
        nested_request(claim, dispatch, ChildTerminal("accepted"))
    )
    result = reconciled.execution_result
    assert result is not None
    assert (result.disposition, result.completion_claim) == ("completed", True)
    assert result.output_refs == ("output:r1@sha256:1",)
    assert result.actual_usage == {"t": 7}
    assert result.evidence_refs[0].startswith("nested-receipt:sha256:")
    settlement = reconciled.settlement
    assert settlement is not None
    assert (settlement.reservation_id, settlement.usage, settlement.settled_run_version) == (
        claim.reservation_id,
        {"t": 7},
        11,
    )
    assert settlement.effect_claim_id == "nested-run:child-1"


@pytest.mark.asyncio
async def test_a_non_accepted_body_is_a_failed_iteration_the_policy_decides() -> None:
    composition, _run_id, claim, dispatch = await _executor_dispatch()
    reconciled = await composition.family.reconcile_nested_executor(
        nested_request(claim, dispatch, ChildTerminal("governor_exhausted", "iteration_limit"))
    )
    result = reconciled.execution_result
    assert result is not None
    assert (result.disposition, result.completion_claim) == ("failed", False)
    assert result.output_refs == ()
    assert result.blocker_class == "nested_body_not_accepted"


@pytest.mark.asyncio
async def test_a_cancelled_body_carries_its_settlement_and_no_role_result() -> None:
    composition, _run_id, claim, dispatch = await _executor_dispatch()
    reconciled = await composition.family.reconcile_nested_executor(
        nested_request(claim, dispatch, ChildTerminal("cancelled"))
    )
    assert reconciled.operation_disposition == "cancelled"
    assert reconciled.execution_result is None
    assert reconciled.settlement is not None


@pytest.mark.asyncio
async def test_a_settlement_of_another_reservation_refuses_typed() -> None:
    composition, _run_id, claim, dispatch = await _executor_dispatch()
    with pytest.raises(ApplicationError) as refused:
        await composition.family.reconcile_nested_executor(
            nested_request(claim, dispatch, ChildTerminal("accepted"), reservation_id="other")
        )
    assert refused.value.type == "goal_nested_executor_invalid" and refused.value.non_retryable


@pytest.mark.asyncio
async def test_a_failed_or_refused_body_fails_the_executor_with_its_settlement() -> None:
    """S6: an infrastructure failure (or a refused activation) carries no execution result;
    the Goal Loop then fails typed (`goal_operation_unreported`), as for any failed unit."""

    composition, _run_id, claim, dispatch = await _executor_dispatch()
    for cause in ("execution_failed", "nested_execution_unavailable"):
        reconciled = await composition.family.reconcile_nested_executor(
            nested_request(claim, dispatch, ChildTerminal("execution_failed", cause))
        )
        assert reconciled.operation_disposition == "failed"
        assert reconciled.execution_result is None
        assert reconciled.settlement is not None
        assert reconciled.settlement.reservation_id == claim.reservation_id
