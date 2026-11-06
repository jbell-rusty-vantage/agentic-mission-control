"""The root's typed report of a family workflow that ended without terminalizing its run (W1 D15).

A family (StageGraph or GoalDirected) terminalizes its run through the lifecycle reducer. When
the family workflow itself fails, times out, is cancelled or is terminated by an operator, no
family code proposes terminalization and the run would stay `active` (or `cancelling`) with
nothing left to move it. The Mission Control root observes that end and asks run control to
terminalize the run with the typed cause; the reducer still decides the outcome from its own
authoritative budget, effect, wait and obligation facts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final

# The reducer rejections that name a liability another owner settles (a unit still settling
# after the family closed, an async child's usage); the request is retried, never forced.
FAMILY_FAILURE_LIABILITY_REJECTIONS: Final = frozenset(
    {
        "budget_not_settled",
        "effects_not_settled",
        "unresolved_async_children",
        "cancellation_not_settled",
    }
)
FAMILY_FAILURE_STALE_REJECTIONS: Final = frozenset(
    {
        "stale_run_version",
        "stale_control_revision",
        "stale_workflow_type_revision",
        "stale_obligation_revision",
        "stale_evidence_frontier",
        "obligation_evidence_mismatch",
        "obligation_acceptance_mismatch",
    }
)
MAX_FAMILY_FAILURE_CAUSE_CHARS: Final = 256
# W1 D26: from this activity attempt (ADR-0011: the activity's own attempt counter, distinct
# from any semantic retry) a budget or effect liability no longer waits: the run closes with
# every unsettled reservation and effect named as a terminal liability for operator
# reconciliation (`budget_unsettled_at_failure`), well inside the root's retry bound.
LIABILITY_TERMINALIZATION_ATTEMPT: Final = 8
BUDGET_UNSETTLED_AT_FAILURE: Final = "budget_unsettled_at_failure"
# The liability rejections the bound closes; an unresolved async child keeps its own owner.
LIABILITY_TERMINALIZED_REJECTIONS: Final = frozenset({"budget_not_settled", "effects_not_settled"})


@dataclass(frozen=True)
class FamilyFailureTerminalizationRequest:
    """`cause` is a typed code (`application_error:<type>`, `terminated`, `timed_out`,
    `cancelled`); `cause_digest` correlates the failure message, which is never persisted."""

    request_scope: str
    run_id: str
    execution_epoch: int
    family: str
    family_workflow_id: str
    cause: str
    cause_digest: str
    occurred_at: datetime

    def __post_init__(self) -> None:
        if not all((self.request_scope, self.run_id, self.family_workflow_id, self.cause)):
            raise ValueError("family failure terminalization requires its exact run binding")
        if self.execution_epoch < 1:
            raise ValueError("family failure terminalization requires an execution epoch")
        if len(self.cause) > MAX_FAMILY_FAILURE_CAUSE_CHARS:
            raise ValueError("family failure cause exceeds its typed bound")


@dataclass(frozen=True)
class FamilyFailureTerminalizationResult:
    """`accepted`: the run is terminal (now or already); otherwise `reason_code` names the
    reducer's refusal (for example `active_pause`), which an operator resolves."""

    accepted: bool
    resulting_run_version: int
    terminal_outcome: str = ""
    reason_code: str = ""


__all__ = [
    "BUDGET_UNSETTLED_AT_FAILURE",
    "FAMILY_FAILURE_LIABILITY_REJECTIONS",
    "FAMILY_FAILURE_STALE_REJECTIONS",
    "LIABILITY_TERMINALIZATION_ATTEMPT",
    "LIABILITY_TERMINALIZED_REJECTIONS",
    "MAX_FAMILY_FAILURE_CAUSE_CHARS",
    "FamilyFailureTerminalizationRequest",
    "FamilyFailureTerminalizationResult",
]
