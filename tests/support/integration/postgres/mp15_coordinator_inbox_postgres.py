"""Builders, constants and fakes that other test files import.

Moved from tests/integration/postgres/test_coordinator_inbox_postgres.py.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from mission_control.adapters.postgres.run_control import canonical as mc
from mission_control.adapters.postgres.run_control.mailbox import PostgresCommandMailbox
from mission_control.adapters.postgres.run_control.run_control_repository import (
    PostgresRunControlRepository,
)
from mission_control.adapters.postgres.subscriptions.coordinator_inbox import (
    PostgresCoordinatorInboxStore,
)
from mission_control.adapters.postgres.subscriptions.store import PostgresSubscriptionStore
from mission_control.application.execution.boundary_interventions import BoundaryInterventionService
from mission_control.application.execution.mailbox import MailboxDeliveryService
from mission_control.application.missions.service import MissionControlService
from mission_control.application.subscriptions.coordinator_service import (
    CoordinatorInboxService,
    CoordinatorSubscribeRequest,
)
from mission_control.domain.policies.contracts import ActorContext, DomainEventEnvelope, StartAction
from tests.support.boundary_commands import TARGET
from tests.support.db import CommonDatabase
from tests.support.run_control import actor, command, request, service


def coordinator_actor() -> ActorContext:
    """The coordinator's own principal (the run-control unit actor, renamed)."""

    source = actor()
    return source.model_copy(
        update={
            "actor_id": "coordinator-1",
            "permissions": source.permissions | {"workflow_run.read", "workflow_run.control"},
        }
    )


COORDINATOR = coordinator_actor()


async def started_run(pool: asyncpg.Pool, db: CommonDatabase) -> tuple[str, UUID, UUID]:
    """A real admitted and started run: (run key, mission uuid, run uuid)."""

    scope = db.scope()
    authority, _ = service(PostgresRunControlRepository(pool))  # type: ignore[arg-type]
    admission = await authority.admit(request(request_scope=scope, request_id=str(uuid4())))
    assert admission.run_id is not None
    await authority.execute(
        command(admission.run_id, 1, "start", StartAction(execution_target=TARGET)).model_copy(
            update={"request_scope": scope}
        )
    )
    rows = await owner_fetch(
        db,
        "SELECT run_id, mission_id FROM mission_control.mission_run WHERE run_key = $1",
        admission.run_id,
    )
    return admission.run_id, rows[0]["mission_id"], rows[0]["run_id"]


async def owner_fetch(db: CommonDatabase, query: str, *args: Any) -> list[asyncpg.Record]:
    owner = await asyncpg.connect(db.owner_dsn)
    try:
        return list(await owner.fetch(query, *args))
    finally:
        await owner.close()


async def append_fixture_events(
    pool: asyncpg.Pool,
    scope: str,
    run_key: str,
    events: Sequence[tuple[str, dict[str, Any]]],
) -> None:
    """FIXTURE: journal events through the canonical ledger writer (frame-derived stand-ins)."""

    now = datetime.now(UTC)
    batch = uuid4()
    envelopes = tuple(
        DomainEventEnvelope(
            event_id=f"fixture:{batch}:{index}",
            event_type=event_type,
            aggregate_id=f"fixture:{batch}",
            aggregate_version=1,
            sequence=index + 1,
            occurred_at=now,
            recorded_at=now,
            actor=ActorContext(actor_id="fixture:frames"),
            correlation_id=str(batch),
            payload=payload,
        )
        for index, (event_type, payload) in enumerate(events)
    )
    async with pool.acquire() as connection, connection.transaction():
        args = await mc.begin(connection, scope)
        await mc.append_events(
            connection,
            args,
            run_key=run_key,
            commit_key=f"fixture:{batch}",
            expected_versions={},
            events=envelopes,
            actor_ref="fixture:frames",
        )


def inbox_service(pool: asyncpg.Pool, scope: str, **kwargs: Any) -> CoordinatorInboxService:
    return CoordinatorInboxService(
        PostgresSubscriptionStore(pool, scope), PostgresCoordinatorInboxStore(pool, scope), **kwargs
    )


async def subscribe(inboxes: CoordinatorInboxService, run_uuid: UUID, **overrides: Any) -> UUID:
    created = await inboxes.subscribe(
        CoordinatorSubscribeRequest.model_validate(
            {"target": "run", "target_id": str(run_uuid), "after_seq": 0, **overrides}
        ),
        COORDINATOR,
    )
    return created.subscription_id


def mission_service(pool: asyncpg.Pool, scope: str) -> tuple[MissionControlService, Any]:
    authority, _ = service(PostgresRunControlRepository(pool))  # type: ignore[arg-type]
    mailbox = MailboxDeliveryService(PostgresCommandMailbox(pool), authority)
    facade = MissionControlService(
        authority, BoundaryInterventionService(authority), request_scope=scope, mailbox=mailbox
    )
    return facade, mailbox
