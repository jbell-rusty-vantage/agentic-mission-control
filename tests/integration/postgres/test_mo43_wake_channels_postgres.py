"""MO-43 (SPEC-04 §6): the launcher's inbox and the inbox wait on a disposable PostgreSQL 17.

Restricted runtime login, forced RLS, the released 0033 coordinator tables (`common_db`). The
run is a real admitted and started run; the terminal event is appended through the canonical
ledger writer as a FIXTURE stand-in for the reducer's `workflow_run.terminalize` (the full
reducer path, on local Temporal, is `tests/acceptance/mission_control/test_wake_channels.py`).

Proves: the launch hook registers exactly one inbox per launcher and run, named by the public
run id (a repeated launch reuses it, another tenant cannot see it); a wait that started before
the terminal event commits returns it as one `terminal_result` notification (`run.completed`)
without any relay running; the kinds filter leaves other kinds pending; nothing is acknowledged
implicitly.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

import pytest

from mission_control.application.subscriptions.coordinator import NotificationKind
from mission_control.application.subscriptions.coordinator_service import CoordinatorRejected
from mission_control.application.subscriptions.launcher import subscribe_launcher
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.integration.postgres.runtime_common import common_db  # noqa: F401
from tests.integration.postgres.test_mp15_coordinator_inbox_postgres import (
    COORDINATOR,
    append_fixture_events,
    inbox_service,
    started_run,
)

pytestmark = pytest.mark.common_db


async def test_launcher_inbox_wakes_a_waiting_coordinator_on_run_completed(
    common_db: CommonDatabase,  # noqa: F811
) -> None:
    pool = await common_db.pool(max_size=6)
    try:
        scope = common_db.scope()
        run_key, _mission, run_uuid = await started_run(pool, common_db)
        inboxes = inbox_service(pool, scope, wait_interval=0.1)
        # A launch names the public run id (the run key); the store resolves it to the row.
        launched = await subscribe_launcher(inboxes, run_key, COORDINATOR)
        assert launched.status == "subscribed" and launched.subscription_id is not None
        sid = launched.subscription_id
        relaunched = await subscribe_launcher(inboxes, run_key, COORDINATOR)
        assert (relaunched.status, relaunched.subscription_id) == ("existing", sid)
        for target_id in (UUID(run_key), run_uuid):
            listed = await inboxes.inboxes(COORDINATOR, target="run", target_id=target_id)
            assert [item.subscription_id for item in listed] == [sid]
            assert listed[0].target.run_id == run_uuid

        waiter = asyncio.create_task(
            inboxes.wait(
                sid, COORDINATOR, timeout_seconds=30, kinds={NotificationKind.TERMINAL_RESULT}
            )
        )
        await asyncio.sleep(0.5)
        assert not waiter.done()  # nothing terminal has committed yet
        await append_fixture_events(
            pool,
            scope,
            run_key,
            [
                ("attempt.completed", {"outcome": "failed", "failure_class": "provider"}),
                ("workflow_run.terminalize", {"terminal_outcome": "completed"}),
            ],
        )
        page = await asyncio.wait_for(waiter, timeout=30)
        (notification,) = page.notifications
        assert notification.kind is NotificationKind.TERMINAL_RESULT and notification.actionable
        assert notification.run_id == run_uuid
        assert [ref.event_type for ref in notification.events] == ["run.completed"]
        assert notification.facts == {"terminal_outcome": "completed"}

        # The failed attempt stays pending for a reader of every kind; nothing was acked.
        everything = await inboxes.poll(sid, COORDINATOR)
        assert [item.kind for item in everything.notifications] == [
            NotificationKind.FAILED,
            NotificationKind.TERMINAL_RESULT,
        ]
        assert everything.acked_inbox_seq == 0

        other = inbox_service(pool, common_db.scope("tenant-2"))
        with pytest.raises(CoordinatorRejected) as hidden:
            await other.inboxes(COORDINATOR, target="run", target_id=run_uuid)
        assert hidden.value.code == "not_found"
    finally:
        await pool.close()
