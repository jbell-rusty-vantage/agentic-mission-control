"""Public run UUID -> scoped production resolver -> launcher's durable inbox contract.

The PostgreSQL method and coordinator services execute unchanged. A scoped fake
connection supplies the alias row; SQL execution/RLS and native caller resumption
are outside this fixture proof.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

import pytest

from mission_control.adapters.postgres.subscriptions.store import PostgresSubscriptionStore
from mission_control.application.subscriptions.coordinator import NotificationKind
from mission_control.application.subscriptions.coordinator_service import (
    CoordinatorInboxService,
    CoordinatorRejected,
)
from mission_control.application.subscriptions.launcher import subscribe_launcher
from mission_control.application.subscriptions.ports import SubscriptionNotFound
from mission_control.domain.policies.contracts import ActorContext
from mission_control.domain.subscriptions.contracts import SubscriptionTarget
from tests.unit.subscriptions.coordinator_fakes import InMemoryInboxStore, journal_event
from tests.unit.subscriptions.fakes import MISSION, RUN, SCOPE, InMemoryStore

PUBLIC_RUN = UUID("10000000-0000-7000-8000-000000000002")
INTERNAL_RUN = RUN
DATA_SCOPE = (
    UUID("00000000-0000-7000-8000-0000000000aa"),
    "biotech",
    UUID("00000000-0000-7000-8000-0000000000bb"),
)
CALLER = ActorContext(actor_id="full3-caller", permissions=frozenset({"workflow_run.read"}))
OTHER = ActorContext(actor_id="other-caller", permissions=CALLER.permissions)


class ScopedConnection:
    """DB boundary fixture checks scope/alias binds, not PostgreSQL query execution."""

    def __init__(self) -> None:
        self.in_transaction = False
        self.scope: tuple[str, ...] | None = None
        self.lookups: list[UUID] = []

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        self.in_transaction = True
        try:
            yield
        finally:
            self.in_transaction = False
            self.scope = None

    def is_in_transaction(self) -> bool:
        return self.in_transaction

    async def execute(self, query: str, *args: str) -> str:
        assert self.in_transaction
        assert "set_config('mc.installation_id'" in query
        assert "set_config('mc.application_id'" in query
        assert "set_config('mc.tenant_id'" in query
        self.scope = args
        return "SELECT 1"

    async def fetchrow(self, query: str, *args: Any) -> dict[str, UUID] | None:
        assert self.in_transaction and self.scope is not None
        assert tuple(str(value) for value in args[:3]) == self.scope
        assert "installation_id = $1 AND application_id = $2 AND tenant_id = $3" in query
        assert "(run_id = $4 OR run_key = $5)" in query
        assert "ORDER BY run_id = $4 DESC LIMIT 1" in query
        target, alias = args[3:]
        assert isinstance(target, UUID) and alias == str(target)
        self.lookups.append(target)
        if args[:3] == DATA_SCOPE and target in {PUBLIC_RUN, INTERNAL_RUN}:
            return {"run_id": INTERNAL_RUN, "mission_id": MISSION}
        return None


class ScopedPool:
    def __init__(self) -> None:
        self.connection = ScopedConnection()

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[ScopedConnection]:
        yield self.connection


class AliasSubscriptions(InMemoryStore):
    """Only the DB boundary is fake; alias normalization uses the production method."""

    def __init__(self, resolver: PostgresSubscriptionStore) -> None:
        super().__init__()
        self.resolver = resolver

    async def resolve_target(self, kind: str, target_id: UUID) -> SubscriptionTarget:
        return await self.resolver.resolve_target(kind, target_id)


def compose() -> tuple[CoordinatorInboxService, InMemoryInboxStore, ScopedPool]:
    pool = ScopedPool()
    resolver = PostgresSubscriptionStore(pool, SCOPE)
    subscriptions = AliasSubscriptions(resolver)
    inbox = InMemoryInboxStore(subscriptions)
    return CoordinatorInboxService(subscriptions, inbox), inbox, pool


async def test_public_run_launcher_joins_internal_journal_and_owned_inbox() -> None:
    assert PUBLIC_RUN != INTERNAL_RUN
    service, inbox, pool = compose()
    inbox.add(journal_event(1, "human_task.created"), human_task_id="before-launch")
    launched = await subscribe_launcher(service, str(PUBLIC_RUN), CALLER)
    assert launched.status == "subscribed" and launched.subscription_id is not None
    sid = launched.subscription_id
    view = await service.inbox(sid, CALLER)
    assert view.target == SubscriptionTarget(kind="run", mission_id=MISSION, run_id=INTERNAL_RUN)
    assert view.coordinator_ref == CALLER.actor_id and view.cursor_seq == 1
    subscription = await inbox.subscriptions.get(sid)
    assert subscription.request_scope == SCOPE and subscription.actor_ref == CALLER.actor_id

    # A subsequent path using the internal UUID must reuse the caller's same inbox.
    replayed_launch = await subscribe_launcher(service, str(INTERNAL_RUN), CALLER)
    assert replayed_launch.status == "existing" and replayed_launch.subscription_id == sid
    inbox.add(journal_event(2, "human_task.created"), human_task_id="new-review")
    inbox.add(
        journal_event(3, "workflow_run.terminalize", run_id=PUBLIC_RUN),
        terminal_outcome="completed",
    )
    inbox.add(
        journal_event(4, "workflow_run.terminalize", run_id=INTERNAL_RUN),
        terminal_outcome="completed",
    )
    page = await service.wait(
        sid, CALLER, timeout_seconds=0, kinds={NotificationKind.TERMINAL_RESULT}
    )
    assert len(page.notifications) == 1 and page.acked_inbox_seq == 0
    notification = page.notifications[0]
    assert notification.kind == NotificationKind.TERMINAL_RESULT
    assert notification.run_id == INTERNAL_RUN and notification.events[0].seq == 4
    assert (
        await service.wait(sid, CALLER, timeout_seconds=0, kinds={NotificationKind.TERMINAL_RESULT})
    ).notifications == page.notifications
    pending = await service.poll(sid, CALLER)
    assert [item.kind for item in pending.notifications] == [
        NotificationKind.REVIEW_REQUIRED,
        NotificationKind.TERMINAL_RESULT,
    ]
    assert [item.events[0].seq for item in pending.notifications] == [2, 4]

    for action in (
        service.wait(sid, OTHER, timeout_seconds=0),
        service.ack(sid, OTHER, notification_ids=(notification.notification_id,)),
    ):
        with pytest.raises(CoordinatorRejected) as refused:
            await action
        assert refused.value.code == "not_found"
    acknowledged = await service.ack(sid, CALLER, through_inbox_seq=page.high_inbox_seq)
    assert acknowledged.acked_inbox_seq == page.high_inbox_seq == 2
    assert not (await service.poll(sid, CALLER)).notifications
    again = await service.ack(sid, CALLER, through_inbox_seq=2)
    assert again.acked_inbox_seq == 2 and not again.acknowledged
    assert set(pool.connection.lookups) == {PUBLIC_RUN, INTERNAL_RUN}
    assert pool.connection.scope is None and not pool.connection.in_transaction


async def test_production_alias_resolver_keeps_request_scope_on_lookup() -> None:
    pool = ScopedPool()
    other_scope = SCOPE.replace("0000000000bb", "0000000000cc")
    resolver = PostgresSubscriptionStore(pool, other_scope)
    with pytest.raises(SubscriptionNotFound):
        await resolver.resolve_target("run", PUBLIC_RUN)
    assert pool.connection.lookups == [PUBLIC_RUN]
    assert pool.connection.scope is None and not pool.connection.in_transaction
