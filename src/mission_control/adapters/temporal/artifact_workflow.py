from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

# Sprint OC WI-04: `operation.execute` reports `waiting` while a saved provider result's
# settlement waits; this workflow waits on a durable timer and runs it again (it consumes the
# saved result) instead of failing the artifact. Only histories with a wait carry the marker.
SAVED_SETTLEMENT_PATCH = "oc-wi04-generic-artifact-settlement-wait"
MAX_SETTLEMENT_WAIT_SECONDS = 7 * 86_400


@workflow.defn(name="belllabs.generic-artifact")
class GenericArtifactWorkflow:
    """Generic traced path: governed operation, candidate capture, explicit promotion."""

    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        operation = await self._execute(payload)
        while operation.get("status") == "waiting" and workflow.patched(SAVED_SETTLEMENT_PATCH):
            await workflow.sleep(timedelta(seconds=_wait_seconds(operation)))
            operation = await self._execute(payload)
        if operation.get("status") != "completed":
            raise ApplicationError(
                "generic artifact operation did not complete",
                type="generic_artifact_operation_failed",
                non_retryable=True,
            )
        artifact = await workflow.execute_activity(
            "artifact.promote",
            {
                "request_scope": payload["request_scope"],
                "binding_id": operation["binding_id"],
                "promotion": payload["promotion"],
            },
            result_type=dict,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=0),
        )
        return {
            "workflow_id": workflow.info().workflow_id,
            "operation": operation,
            "artifact": artifact,
        }

    @staticmethod
    async def _execute(payload: dict[str, Any]) -> dict[str, Any]:
        operation: dict[str, Any] = await workflow.execute_activity(
            "operation.execute",
            payload["operation"],
            result_type=dict,
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=0),
        )
        return operation


def _wait_seconds(operation: dict[str, Any]) -> int:
    wait = operation.get("settlement_wait")
    seconds = wait.get("wait_seconds") if isinstance(wait, dict) else None
    if not isinstance(seconds, int) or isinstance(seconds, bool):
        return 5
    return max(1, min(seconds, MAX_SETTLEMENT_WAIT_SECONDS))
