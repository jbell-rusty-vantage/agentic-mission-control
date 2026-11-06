"""``transcript.project``: the Transcript projection job (SPEC-03 C4; TRACING-PROPOSAL §P3.9).

Rebuilds, for the listed runs of one tenant scope (forced RLS binds one tenant per
transaction), the search documents (``mission_control_search.transcript_document``) and,
when the projector carries an entry store, the persisted ``mc.transcript_entry.v2`` rows
with their projection marks (``transcript_projection_state``, TR-D10). It is idempotent: a
second run of the same activity upserts nothing, deletes nothing and rewrites the same rows.

Served on the maintenance worker beside ``frames.expire``. It is started per run by
``mc.transcript_project.v1`` (workflows/transcript_projection.py), which the settlement
outbox releases through :class:`TemporalTranscriptProjectionStarter` (the relay of
``application/frames/projection_trigger.py``), and on demand by
``POST runs/{id}/transcript/refresh``. No schedule (owner, 2026-10-21).

Tracing Stage 3 (R4-F3): the activity heartbeats inside each run's projection (between its
phases), a pass that ended behind queues its own catch-up (``TranscriptProjector``), and a
run whose last attempt fails queues one retry through the outbox (at most one per run per
hour, five minutes later). A failed workflow can be started again under its id
(``ALLOW_DUPLICATE_FAILED_ONLY``).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable, Sequence
from contextlib import AsyncExitStack
from datetime import UTC, datetime, timedelta

import asyncpg
from pydantic import BaseModel, ConfigDict, Field
from temporalio import activity
from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from mission_control.adapters.postgres.frames.transcript_entries import (
    PostgresTranscriptProjectionIntents,
)
from mission_control.application.frames.projection_trigger import (
    TranscriptProjectionIntent,
    TranscriptProjectionPump,
    TranscriptProjectionRelay,
)
from mission_control.application.frames.search import ProjectionReceipt, TranscriptProjector
from mission_control.application.frames.transcript import TranscriptRunNotFound

_LOG = logging.getLogger(__name__)

TRANSCRIPT_PROJECT_ACTIVITY = "transcript.project"
TRANSCRIPT_PROJECT_WORKFLOW = "mc.transcript_project.v1"
PROJECT_MAX_ATTEMPTS = 5
"""The activity's retry budget (the workflow's `RetryPolicy`); the last failure re-queues."""
RETRY_DELAY = timedelta(minutes=5)


class TranscriptProjectInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_scope: str = Field(min_length=1)
    run_ids: tuple[str, ...] = Field(min_length=1, max_length=500)


class TranscriptProjectResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    receipts: tuple[ProjectionReceipt, ...] = ()
    missing_runs: tuple[str, ...] = ()


class TranscriptProjectionActivities:
    def __init__(self, projectors: Callable[[str], TranscriptProjector]) -> None:
        self._projectors = projectors

    @activity.defn(name=TRANSCRIPT_PROJECT_ACTIVITY)
    async def project(self, request: TranscriptProjectInput) -> TranscriptProjectResult:
        projector = self._projectors(request.request_scope)
        receipts: list[ProjectionReceipt] = []
        missing: list[str] = []
        for run_id in request.run_ids:

            def beat(stage: str, run: str = run_id) -> None:
                activity.heartbeat(run, stage)

            try:
                receipts.append(await projector.project(run_id, heartbeat=beat))
            except TranscriptRunNotFound:
                missing.append(run_id)
            except Exception:
                if activity.info().attempt >= PROJECT_MAX_ATTEMPTS:
                    await _retry_later(projector, run_id)
                raise
            activity.heartbeat(run_id)
        return TranscriptProjectResult(receipts=tuple(receipts), missing_runs=tuple(missing))


async def _retry_later(projector: TranscriptProjector, run_id: str) -> None:
    """Tracing Stage 3 (R4-F3): the workflow is about to fail for good and the relay acked
    its intent at start, so nothing would project the run again before its next settlement.
    One retry per run per hour, best effort (the store may be what failed)."""

    hour = datetime.now(UTC).strftime("%Y%m%dT%H")
    try:
        await projector.request_later(run_id, reason=f"retry:{hour}", delay=RETRY_DELAY)
    except Exception:  # the original failure is what the workflow reports
        _LOG.exception("transcript projection retry of %s could not be queued", run_id)


def transcript_projection_workflow_id(intent: TranscriptProjectionIntent) -> str:
    """One workflow per (tenant scope, run, settlement revision): a re-delivered intent
    finds it already started and is acknowledged."""

    suffix = f":r{intent.settlement_revision}" if intent.settlement_revision > 1 else ""
    return (
        f"{intent.request_scope}/run/{intent.run_key}/transcript-projection/"
        f"{intent.settlement_id}{suffix}"
    )


class TemporalTranscriptProjectionStarter:
    """``TranscriptProjectionStarter``: start ``mc.transcript_project.v1`` for the intent's
    run on the maintenance queue; a repeated start attaches to a running or completed one
    and restarts only a failed one (ALLOW_DUPLICATE_FAILED_ONLY, Tracing Stage 3 R4-F3)."""

    def __init__(self, client: Client, *, task_queue: str) -> None:
        if not task_queue:
            raise ValueError("the transcript projection task queue must be non-empty")
        self._client = client
        self._task_queue = task_queue

    async def project(self, intent: TranscriptProjectionIntent) -> str:
        workflow_id = transcript_projection_workflow_id(intent)
        with contextlib.suppress(WorkflowAlreadyStartedError):
            await self._client.start_workflow(
                TRANSCRIPT_PROJECT_WORKFLOW,
                TranscriptProjectInput(
                    request_scope=intent.request_scope, run_ids=(intent.run_key,)
                ),
                id=workflow_id,
                task_queue=self._task_queue,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
            )
        return workflow_id


def start_transcript_projection_relay(
    stack: AsyncExitStack,
    *,
    pool: asyncpg.Pool,
    client: Client,
    task_queue: str,
    request_scopes: Sequence[str],
    lease_owner: str,
    graceful_shutdown_seconds: float,
    interval_seconds: float = 2.0,
) -> TranscriptProjectionPump:
    """Deliver ``transcript_projection`` outbox intents while the worker runs; the pump
    stops with the worker (bounded by the graceful shutdown)."""

    pump = TranscriptProjectionPump(
        TranscriptProjectionRelay(
            store=PostgresTranscriptProjectionIntents(pool),
            starter=TemporalTranscriptProjectionStarter(client, task_queue=task_queue),
            lease_owner=lease_owner,
        ),
        request_scopes,
        interval_seconds=interval_seconds,
    )
    halt = asyncio.Event()
    task = asyncio.create_task(pump.run(halt))

    async def stop_pump() -> None:
        halt.set()
        with contextlib.suppress(TimeoutError, asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=max(graceful_shutdown_seconds, 1))

    stack.push_async_callback(stop_pump)
    return pump


__all__ = [
    "PROJECT_MAX_ATTEMPTS",
    "TRANSCRIPT_PROJECT_ACTIVITY",
    "TRANSCRIPT_PROJECT_WORKFLOW",
    "TemporalTranscriptProjectionStarter",
    "TranscriptProjectInput",
    "TranscriptProjectResult",
    "TranscriptProjectionActivities",
    "start_transcript_projection_relay",
    "transcript_projection_workflow_id",
]
