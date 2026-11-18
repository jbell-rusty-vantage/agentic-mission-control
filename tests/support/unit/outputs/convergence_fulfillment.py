"""Builders, constants and fakes that other test files import.

Moved from tests/unit/outputs/test_convergence_fulfillment.py.
"""

from __future__ import annotations

from mission_control.domain.programs.goal_directed_runtime import GoalVerifierObservation


def _observation(decision: str = "accepted") -> GoalVerifierObservation:
    return GoalVerifierObservation(
        decision=decision,  # type: ignore[arg-type]
        progress_made=True,
        accepted_obligation_refs=("obligation:goal",),
        output_contract_ref="contract:report",
    )
