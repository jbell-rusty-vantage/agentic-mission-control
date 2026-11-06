"""`hosted_session.delete`: hosted session retention as a Temporal timer and activity
(SPEC-06 section 8; `application.execution.harness.retention`).

`TemporalSessionDeletionScheduler` is the `SessionDeletionScheduler` a non-ZDR lane is
composed with: it starts one `mc.hosted_session_retention.v1` workflow per deletion order,
keyed by the order, on the worker's maintenance queue. The workflow sleeps until the order's
`delete_after` and runs this activity, which deletes the session through the profile's
deleter. Ordering a session again while its timer runs, or after it was deleted, is a no-op;
an order whose workflow was terminated or cancelled starts again.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from temporalio import activity
from temporalio.client import Client
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from mission_control.application.execution.harness.retention import SessionDeletionService
from mission_control.domain.execution.session_retention import SessionDeletion

SESSION_DELETE_ACTIVITY = "hosted_session.delete"
SESSION_RETENTION_WORKFLOW = "mc.hosted_session_retention.v1"


@dataclass(frozen=True)
class SessionRetentionInput:
    """One deletion order on the wire (timestamps ISO-8601, timezone-aware)."""

    lane_profile: str
    request_scope: str
    session_ref: str
    custody_at: str
    delete_after: str

    @classmethod
    def of(cls, deletion: SessionDeletion) -> SessionRetentionInput:
        return cls(
            lane_profile=deletion.lane_profile,
            request_scope=deletion.request_scope,
            session_ref=deletion.session_ref,
            custody_at=deletion.custody_at.isoformat(),
            delete_after=deletion.delete_after.isoformat(),
        )

    def deletion(self) -> SessionDeletion:
        return SessionDeletion.model_validate(
            {
                "lane_profile": self.lane_profile,
                "request_scope": self.request_scope,
                "session_ref": self.session_ref,
                "custody_at": datetime.fromisoformat(self.custody_at),
                "delete_after": datetime.fromisoformat(self.delete_after),
            }
        )


@dataclass(frozen=True)
class SessionRetentionResult:
    lane_profile: str
    session_ref: str
    outcome: str  # `deleted`, or `absent` when the provider no longer had the session


def session_retention_workflow_id(deletion: SessionDeletion) -> str:
    return f"mc-session-retention:{deletion.key}"


class SessionRetentionActivities:
    def __init__(self, deletions: SessionDeletionService) -> None:
        self._deletions = deletions

    @activity.defn(name=SESSION_DELETE_ACTIVITY)
    async def delete(self, request: SessionRetentionInput) -> SessionRetentionResult:
        outcome = await self._deletions.delete(request.deletion())
        return SessionRetentionResult(
            lane_profile=request.lane_profile, session_ref=request.session_ref, outcome=outcome
        )


class TemporalSessionDeletionScheduler:
    """Starts the deletion timer of an order, once per order."""

    def __init__(self, client: Client, *, task_queue: str) -> None:
        self._client = client
        self._task_queue = task_queue

    async def schedule(self, deletion: SessionDeletion) -> None:
        try:
            await self._client.start_workflow(
                SESSION_RETENTION_WORKFLOW,
                SessionRetentionInput.of(deletion),
                id=session_retention_workflow_id(deletion),
                task_queue=self._task_queue,
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
            )
        except WorkflowAlreadyStartedError:
            return  # the order completed: the session is deleted


__all__ = [
    "SESSION_DELETE_ACTIVITY",
    "SESSION_RETENTION_WORKFLOW",
    "SessionRetentionActivities",
    "SessionRetentionInput",
    "SessionRetentionResult",
    "TemporalSessionDeletionScheduler",
    "session_retention_workflow_id",
]
