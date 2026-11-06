"""Bounded delayed billing; unresolved costs remain pending after the final read."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from mission_control.adapters.temporal.activities.cursor_costs import (
        COST_ACTIVITY,
        COST_WORKFLOW,
        CostRead,
    )
    from mission_control.domain.execution.cursor_costs import (
        CostReadResult,
        CostRequest,
    )


@workflow.defn(name=COST_WORKFLOW)
class CursorCostsWorkflow:
    @workflow.run
    async def run(self, request: CostRequest) -> CostReadResult:
        for read_no, delay in enumerate((0, 300, 900)):
            if delay:
                await workflow.sleep(timedelta(seconds=delay))
            result = await workflow.execute_activity(
                COST_ACTIVITY,
                CostRead(request, read_no),
                result_type=CostReadResult,
                task_queue=request.activity_task_queue,
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            if result.state in {"settled", "unattributable", "overage", "conflict"}:
                return result
        return result
