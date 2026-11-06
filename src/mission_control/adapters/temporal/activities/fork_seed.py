"""`fork_seed.copy`: the cognitive seed's native copy as a worker activity (1.4.4, P6.1).

The fork saga admits the derived run on the API; the copy of the source thread to the point
(`TimeTravelLane.seed_fork`, M reads and M writes against the remote saver) runs on the
maintenance worker, which already holds the pinned savers, instead of the API request
thread. The workflow only hosts the activity: the copy is idempotent (a derived thread that
already holds the point and the head is left alone), so a retried or duplicated start
answers the same receipt. A saver that does not answer is a retryable failure; a point no
saver serves, or a lane without time travel, is not.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict
from temporalio import activity
from temporalio.client import Client, WorkflowFailureError, WorkflowHandle
from temporalio.common import WorkflowIDConflictPolicy
from temporalio.exceptions import ActivityError, ApplicationError

from mission_control.application.execution.harness.time_travel import (
    ForkSeedReceipt,
    ForkSeedRequest,
    TimeTravelRegistry,
    TimeTravelUnsupported,
)

FORK_SEED_ACTIVITY = "fork_seed.copy"
FORK_SEED_WORKFLOW = "mc.fork_seed.v1"
TIME_TRAVEL_UNSUPPORTED = "time_travel_unsupported"
# The outcomes a retry may clear: the saver did not answer, or the copy ran out of budget.
RETRYABLE_REASONS = frozenset({"saver_unreachable", "copy_incomplete"})
# Tracing Stage 3 (R2-2): how long the API waits for the worker's copy before answering
# `copy_incomplete` (the workflow keeps running; a retried fork attaches to it).
DEFAULT_RESULT_TIMEOUT_SECONDS = 600.0


class ForkSeedOutcome(BaseModel):
    """The activity's answer: the receipt, or the typed refusal (never a bare exception)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    receipt: ForkSeedReceipt


class ForkSeedActivities:
    def __init__(
        self, registry: TimeTravelRegistry | Callable[[], TimeTravelRegistry | None]
    ) -> None:
        self._registry = registry

    def _lanes(self) -> TimeTravelRegistry:
        registry = TimeTravelRegistry.resolve(self._registry)
        if registry is None:
            raise ApplicationError(
                "time travel is not composed on this worker",
                {"lane_profile": "", "reason": "time_travel_unsupported", "saver": None},
                type=TIME_TRAVEL_UNSUPPORTED,
                non_retryable=True,
            )
        return registry

    @activity.defn(name=FORK_SEED_ACTIVITY)
    async def copy(self, request: ForkSeedRequest) -> ForkSeedOutcome:
        lane_profile = request.source.lane_profile
        try:
            lane = self._lanes().lane(lane_profile, request_scope=request.request_scope)
            receipt = await lane.seed_fork(request)
        except TimeTravelUnsupported as error:
            raise ApplicationError(
                str(error),
                {"lane_profile": error.lane_profile, "reason": error.reason, "saver": error.saver},
                type=TIME_TRAVEL_UNSUPPORTED,
                non_retryable=error.reason not in RETRYABLE_REASONS,
            ) from error
        return ForkSeedOutcome(receipt=receipt)


def fork_seed_workflow_id(request: ForkSeedRequest) -> str:
    """One workflow per (fork request, derived unit): a replayed fork attaches to it."""

    return f"fork-seed/{request.fork_request_id}/{request.derived_unit_key}"


class TemporalForkSeedRunner:
    """`ForkSeedRunner` for the API: run the copy on the maintenance queue and wait for it.

    A typed refusal from the activity comes back as the same `TimeTravelUnsupported` the
    in-process lane would raise, so `CognitiveSeedService` maps it the same way
    (`cognitive_seed_unavailable` for a saver that did not answer, `cognitive_seed_not_supported`
    otherwise).
    """

    def __init__(
        self,
        client: Client,
        *,
        task_queue: str,
        result_timeout_seconds: float = DEFAULT_RESULT_TIMEOUT_SECONDS,
    ) -> None:
        if not task_queue:
            raise ValueError("the fork seed task queue must be non-empty")
        self._client = client
        self._task_queue = task_queue
        self._result_timeout = result_timeout_seconds

    async def seed_fork(self, request: ForkSeedRequest) -> ForkSeedReceipt:
        handle: WorkflowHandle[Any, ForkSeedOutcome] = await self._client.start_workflow(
            FORK_SEED_WORKFLOW,
            request,
            id=fork_seed_workflow_id(request),
            task_queue=self._task_queue,
            result_type=ForkSeedOutcome,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        )
        try:
            outcome = await asyncio.wait_for(handle.result(), timeout=self._result_timeout)
        except TimeoutError as error:
            # Tracing Stage 3 (R2-2): the copy has not finished in time; the fork is refused
            # retryably and a replay attaches to the same workflow (`USE_EXISTING`).
            raise TimeTravelUnsupported(
                request.source.lane_profile, "copy_incomplete", saver=None
            ) from error
        except WorkflowFailureError as error:
            # Tracing Stage 3 (R2-2): the activity's typed refusal reaches the client as
            # `WorkflowFailureError(cause=ActivityError(cause=ApplicationError))`.
            cause: BaseException | None = error.cause
            if isinstance(cause, ActivityError):
                cause = cause.cause
            if isinstance(cause, ApplicationError) and cause.type == TIME_TRAVEL_UNSUPPORTED:
                details = cause.details[0] if cause.details else {}
                if not isinstance(details, dict):
                    details = {}
                raise TimeTravelUnsupported(
                    str(details.get("lane_profile") or request.source.lane_profile),
                    str(details.get("reason") or "time_travel_unsupported"),
                    saver=details.get("saver"),
                ) from error
            raise
        return outcome.receipt


__all__ = [
    "FORK_SEED_ACTIVITY",
    "FORK_SEED_WORKFLOW",
    "ForkSeedActivities",
    "ForkSeedOutcome",
    "ForkSeedRequest",
    "TemporalForkSeedRunner",
    "fork_seed_workflow_id",
]
