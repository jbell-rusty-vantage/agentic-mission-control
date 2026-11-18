"""Public run UUID -> alias resolver -> launcher's durable inbox contract.

The coordinator services execute unchanged over the in-memory stores. The production alias
resolution, its scope and row-level security run on the disposable database in
tests/integration/postgres/test_subscription_caller_identity_postgres.py.
"""

from __future__ import annotations

from uuid import UUID

import pytest

from mission_control.application.subscriptions.coordinator import NotificationKind
from mission_control.application.subscriptions.coordinator_service import (
    CoordinatorInboxService,
    CoordinatorRejected,
)
from mission_control.application.subscriptions.launcher import subscribe_launcher
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


class AliasSubscriptions(InMemoryStore):
    """Resolves the public run key to the internal run, as `PostgresSubscriptionStore` does on
    the database (tests/integration/postgres/test_subscription_caller_identity_postgres.py)."""

    def __init__(self) -> None:
        super().__init__()
        self.lookups: list[UUID] = []

    async def resolve_target(self, kind: str, target_id: UUID) -> SubscriptionTarget:
        self.lookups.append(target_id)
        if kind == "run" and target_id in {PUBLIC_RUN, INTERNAL_RUN}:
            return SubscriptionTarget(kind="run", mission_id=MISSION, run_id=INTERNAL_RUN)
        return await super().resolve_target(kind, target_id)


def compose() -> tuple[CoordinatorInboxService, InMemoryInboxStore, AliasSubscriptions]:
    subscriptions = AliasSubscriptions()
    inbox = InMemoryInboxStore(subscriptions)
    return CoordinatorInboxService(subscriptions, inbox), inbox, subscriptions


async def test_public_run_launcher_joins_internal_journal_and_owned_inbox() -> None:
    assert PUBLIC_RUN != INTERNAL_RUN
    service, inbox, subscriptions = compose()
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
    assert set(subscriptions.lookups) == {PUBLIC_RUN, INTERNAL_RUN}
