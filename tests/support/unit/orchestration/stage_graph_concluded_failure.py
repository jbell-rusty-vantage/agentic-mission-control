"""Builders, constants and fakes that other test files import.

Moved from tests/unit/orchestration/test_stage_graph_concluded_failure.py.
"""

from __future__ import annotations

from typing import Any

from mission_control.domain.programs.contracts import LateResultFacts, StageResultObservation
from mission_control.domain.programs.interpreter import StageGraphInterpreter


def _run(interpreter: StageGraphInterpreter, projection: Any, stage_id: str, outcome: str) -> Any:
    """Admit `stage_id` and decide its result (`completed` or `failed`)."""

    frontier = interpreter.frontier(projection, available_concurrency=2)
    proposal = next(item for item in frontier if item.identity.stage_id == stage_id)
    projection = interpreter.apply_admission(
        projection,
        proposal,
        next_run_version=projection.run_version + 1,
        next_family_version=projection.family_version + 1,
    )
    observation = StageResultObservation(
        identity=proposal.identity,
        operation_result={"output_refs": [f"artifact:{stage_id}"]},
        child_closed_or_quiesced=True,
        reservations_and_usage_settled=True,
        effects_settled=True,
        cancellation_reconciled=True,
        accepted_order=1,
        operation_disposition=outcome,
    )
    decision = interpreter.result_decision(
        proposal.identity, LateResultFacts(), operation_disposition=outcome
    )
    return interpreter.apply_result_decision(
        projection,
        observation,
        decision,
        next_run_version=projection.run_version + 1,
        next_family_version=projection.family_version + 1,
    )
