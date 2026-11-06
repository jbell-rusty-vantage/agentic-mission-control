"""Starts a run's `mc.watchers.v1` Watcher Evaluator (SPEC-04 §5.3), once per run."""

from __future__ import annotations

import contextlib

from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from mission_control.adapters.temporal.workflows.watchers import (
    WATCHERS_WORKFLOW,
    WatchersWorkflowInput,
)
from mission_control.contracts.identities import mission_watchers_id


class TemporalWatcherStarter:
    """``WatcherStartPort``: one scoped workflow id per run; a second start is a no-op."""

    def __init__(self, client: Client, *, task_queue: str, poll_seconds: int = 10) -> None:
        if not task_queue:
            raise ValueError("the watcher task queue must be non-empty")
        self._client = client
        self._task_queue = task_queue
        self._poll_seconds = poll_seconds

    async def start(self, request_scope: str, run_id: str) -> str:
        workflow_id = mission_watchers_id(request_scope, run_id)
        # A repeated start finds the run's evaluator already running (or finished).
        with contextlib.suppress(WorkflowAlreadyStartedError):
            await self._client.start_workflow(
                WATCHERS_WORKFLOW,
                WatchersWorkflowInput(
                    request_scope=request_scope, run_id=run_id, poll_seconds=self._poll_seconds
                ),
                id=workflow_id,
                task_queue=self._task_queue,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            )
        return workflow_id


__all__ = ["TemporalWatcherStarter"]
