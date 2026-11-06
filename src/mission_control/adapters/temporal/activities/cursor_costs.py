"""Cursor delayed billing activity; no provider calls in workflows."""

from dataclasses import dataclass

from temporalio import activity

from mission_control.adapters.cursor.costs import (
    CursorCostReconciler,
)
from mission_control.domain.execution.cursor_costs import (
    CostReadResult,
    CostRequest,
)

COST_WORKFLOW = "mc.cursor_costs.v1"
COST_ACTIVITY = "cursor.costs.reconcile"


@dataclass(frozen=True)
class CostRead:
    request: CostRequest
    read_no: int


class CursorCostActivities:
    def __init__(self, reconciler: CursorCostReconciler) -> None:
        self._reconciler = reconciler

    @activity.defn(name=COST_ACTIVITY)
    async def reconcile(self, request: CostRead) -> CostReadResult:
        return await self._reconciler.observe(request.request, request.read_no)
