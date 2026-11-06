"""`mc.transcript_project.v1`: one run's Transcript projection, released by the settlement
outbox (TRACING-PROPOSAL §P3.9, TR-D10). The workflow only hosts the activity: the projection
is idempotent, so a retried or duplicated start rewrites the same rows."""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from mission_control.adapters.temporal.activities.transcript_projection import (
        PROJECT_MAX_ATTEMPTS,
        TRANSCRIPT_PROJECT_ACTIVITY,
        TRANSCRIPT_PROJECT_WORKFLOW,
        TranscriptProjectInput,
        TranscriptProjectResult,
    )


@workflow.defn(name=TRANSCRIPT_PROJECT_WORKFLOW)
class TranscriptProjectionWorkflow:
    @workflow.run
    async def run(self, request: TranscriptProjectInput) -> TranscriptProjectResult:
        return await workflow.execute_activity(
            TRANSCRIPT_PROJECT_ACTIVITY,
            request,
            result_type=TranscriptProjectResult,
            start_to_close_timeout=timedelta(minutes=10),
            heartbeat_timeout=timedelta(minutes=2),
            # Tracing Stage 3 (R4-F3): the activity's last attempt re-queues the run.
            retry_policy=RetryPolicy(maximum_attempts=PROJECT_MAX_ATTEMPTS),
        )
