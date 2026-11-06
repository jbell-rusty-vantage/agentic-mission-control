"""Worker composition of the Watcher Evaluator (SPEC-04 §5.3, MO-44).

One evaluation service per tenant scope, each acting through the same admitted command path
the API composes (`MissionControlService` with the command mailbox, the Stop Fence store,
continuation triggers and approval cancellation); boundary commands (`pause`, `satisfy_wait`)
are delivered to the run's root through the worker's own Temporal client.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime

import asyncpg
from temporalio.client import Client

from mission_control.adapters.postgres.approvals.tasks import PostgresApprovalTaskRepository
from mission_control.adapters.postgres.context.continuation_repository import (
    PostgresContinuationRepository,
    PostgresRunIds,
)
from mission_control.adapters.postgres.frames.repository import PostgresFrameRepository
from mission_control.adapters.postgres.human_tasks.repository import PostgresHumanTaskRepository
from mission_control.adapters.postgres.run_control.mailbox import PostgresCommandMailbox
from mission_control.adapters.postgres.run_control.stop_fence import PostgresStopFenceRepository
from mission_control.adapters.postgres.watchers import PostgresWatcherStore
from mission_control.adapters.temporal.activities.watchers import WatcherActivities
from mission_control.adapters.temporal.boundary_commands import TemporalBoundaryCommandTransport
from mission_control.application.context.continuation import (
    ContinuationCommands,
    ContinuationTriggers,
    FrameSessionLocator,
)
from mission_control.application.execution.boundary_interventions import (
    BoundaryCommandDeliveryService,
    BoundaryInterventionService,
)
from mission_control.application.execution.mailbox import MailboxDeliveryService
from mission_control.application.execution.service import RunControlService
from mission_control.application.human_tasks.service import HumanTaskService
from mission_control.application.missions.service import MissionControlService
from mission_control.application.watchers.service import WatcherEvaluationService


def compose_watcher_activities(
    pool: asyncpg.Pool,
    *,
    run_control: RunControlService,
    client: Client,
    request_scopes: Sequence[str],
    sources: Callable[[str, str, datetime], Awaitable[None]] | None = None,
) -> WatcherActivities:
    """``watchers.evaluate`` over every tenant scope the worker serves."""

    interventions = BoundaryInterventionService(
        run_control,
        BoundaryCommandDeliveryService(run_control, TemporalBoundaryCommandTransport(client)),
    )
    mailbox = MailboxDeliveryService(PostgresCommandMailbox(pool), run_control)
    services: dict[str, WatcherEvaluationService] = {}
    for scope in request_scopes:
        commands = MissionControlService(
            run_control,
            interventions,
            request_scope=scope,
            stop_fences=PostgresStopFenceRepository(pool),
            continuations=ContinuationCommands(
                ContinuationTriggers(PostgresContinuationRepository(pool)),
                FrameSessionLocator(PostgresFrameRepository(pool), PostgresRunIds(pool)),
                request_scope=scope,
            ),
            mailbox=mailbox,
            approvals=HumanTaskService(
                PostgresHumanTaskRepository(pool),
                request_scope=scope,
                approvals=PostgresApprovalTaskRepository(pool),
            ),
        )
        services[scope] = WatcherEvaluationService(PostgresWatcherStore(pool, scope), commands)
    return WatcherActivities(services.get, sources=sources)


__all__ = ["compose_watcher_activities"]
