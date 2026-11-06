"""`coordinator.terminalize_failed_family`: one activity body both family queues register (W1 D15).

The Mission Control root schedules it on its family queue when the family workflow ended
without terminalizing the run. A pending liability (`FamilyFailureLiabilityPending`) is a
plain retryable failure, so the root's retry policy waits for the unit that still settles.
"""

from __future__ import annotations

from temporalio import activity
from temporalio.exceptions import ApplicationError

from mission_control.application.execution.family_failure import FamilyFailureTerminalization
from mission_control.domain.programs.family_failure import (
    FamilyFailureTerminalizationRequest,
    FamilyFailureTerminalizationResult,
)

FAMILY_FAILURE_ACTIVITY = "coordinator.terminalize_failed_family"
FAMILY_FAILURE_UNAVAILABLE = "family_failure_unavailable"


async def terminalize_failed_family(
    service: FamilyFailureTerminalization | None, request: FamilyFailureTerminalizationRequest
) -> FamilyFailureTerminalizationResult:
    if service is None:
        raise ApplicationError(
            "family failure terminalization is not composed on this worker",
            type=FAMILY_FAILURE_UNAVAILABLE,
            non_retryable=True,
        )
    return await service.terminalize(request, attempt=activity.info().attempt)


__all__ = ["FAMILY_FAILURE_ACTIVITY", "FAMILY_FAILURE_UNAVAILABLE", "terminalize_failed_family"]
