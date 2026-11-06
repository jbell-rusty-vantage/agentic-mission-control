"""`mc.hosted_session_retention.v1`: one hosted session's deletion after its retention
interval (SPEC-06 section 8).

The durable timer is the schedule: the workflow sleeps until the order's `delete_after`, then
deletes the session. Deletion is retried without an attempt limit (backing off to hourly), so a
provider outage or a deleter not yet composed delays the deletion and never drops it.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from mission_control.adapters.temporal.activities.session_retention import (
        SESSION_DELETE_ACTIVITY,
        SESSION_RETENTION_WORKFLOW,
        SessionRetentionInput,
        SessionRetentionResult,
    )

DELETE_RETRY: RetryPolicy = RetryPolicy(
    initial_interval=timedelta(seconds=30),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(hours=1),
    maximum_attempts=0,
)


@workflow.defn(name=SESSION_RETENTION_WORKFLOW)
class HostedSessionRetentionWorkflow:
    @workflow.run
    async def run(self, request: SessionRetentionInput) -> SessionRetentionResult:
        remaining = datetime.fromisoformat(request.delete_after) - workflow.now()
        if remaining > timedelta(0):
            await workflow.sleep(remaining)
        return await workflow.execute_activity(
            SESSION_DELETE_ACTIVITY,
            request,
            result_type=SessionRetentionResult,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=DELETE_RETRY,
        )
