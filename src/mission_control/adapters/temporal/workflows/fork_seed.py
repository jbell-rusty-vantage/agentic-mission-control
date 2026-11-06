"""`mc.fork_seed.v1`: the cognitive seed's native copy on the maintenance queue (1.4.4,
TRACING-PROPOSAL §P6.1). The workflow only hosts the activity: the copy is idempotent, so a
retried or duplicated start answers the same receipt; a typed refusal (`time_travel_unsupported`
with its reason) is not retried unless the reason is transient (`saver_unreachable`,
`copy_incomplete`)."""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from mission_control.adapters.temporal.activities.fork_seed import (
        FORK_SEED_ACTIVITY,
        FORK_SEED_WORKFLOW,
        ForkSeedOutcome,
        ForkSeedRequest,
    )


@workflow.defn(name=FORK_SEED_WORKFLOW)
class ForkSeedWorkflow:
    @workflow.run
    async def run(self, request: ForkSeedRequest) -> ForkSeedOutcome:
        return await workflow.execute_activity(
            FORK_SEED_ACTIVITY,
            request,
            result_type=ForkSeedOutcome,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
