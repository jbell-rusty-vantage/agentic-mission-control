"""Start a reaction's ordinary operation workflow on Temporal (WI-22; ADR-0004, ADR-0062).

``TemporalReactionStarter`` is the ``OperationStartPort`` of
:class:`~mission_control.application.reactions.operations.AdmittedReactionOperations`. It starts
the ordinary ``mc.operation.v1`` (:class:`MissionOperationWorkflow`) under the run-derived
operation id with ``REJECT_DUPLICATE`` and ``USE_EXISTING``: a redelivered dispatch attaches to the
running workflow, and a dispatch redelivered after the workflow finished is the same execution,
never a second one. Temporal alone schedules the operation; the relay only hands it over.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio.client import Client
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from mission_control.adapters.temporal.workflows.operation import MissionOperationWorkflow
from mission_control.application.reactions.service import ReactionDispatchReceipt
from mission_control.contracts.identities import mission_operation_id
from mission_control.domain.execution.contracts import OperationWorkflowRequest

# The workflow's own bound plus the time a parked unit may wait for its reconciliation.
_EXECUTION_GRACE = timedelta(hours=1)


class TemporalReactionStarter:
    def __init__(self, client: Client, *, task_queue: str) -> None:
        if not task_queue:
            raise ValueError("a reaction starter needs the operation workflow task queue")
        self._client = client
        self._task_queue = task_queue

    async def start(
        self, scope: str, run_id: str, request: OperationWorkflowRequest
    ) -> ReactionDispatchReceipt:
        if request.operation.request_scope != scope or request.operation.identity.run_id != run_id:
            raise ValueError("a reaction operation belongs to its own scope and run")
        workflow_id = mission_operation_id(scope, run_id, request.semantic_attempt_id)
        try:
            handle = await self._client.start_workflow(
                MissionOperationWorkflow.run,
                request,
                id=workflow_id,
                task_queue=self._task_queue,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
                execution_timeout=timedelta(seconds=request.timeout_seconds) + _EXECUTION_GRACE,
            )
        except WorkflowAlreadyStartedError as error:  # it ran and closed: the same execution
            return ReactionDispatchReceipt(
                workflow_id=workflow_id, temporal_run_id=error.run_id, already_started=True
            )
        return ReactionDispatchReceipt(
            workflow_id=workflow_id,
            temporal_run_id=handle.first_execution_run_id or handle.result_run_id,
            already_started=False,
        )


__all__ = ["TemporalReactionStarter"]
