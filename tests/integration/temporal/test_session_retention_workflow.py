"""HL-18: `mc.hosted_session_retention.v1` deletes a hosted session on schedule (SPEC-06 §8).

The time-skipping test server proves the durable timer: nothing is deleted before custody plus
the retention interval, the session is deleted once it has passed, a second order of the same
session is the same workflow, and a provider outage delays the deletion without dropping it.
The scheduler starts the workflow (as a lane would), so its handle does not skip time on its
own: each test moves the test server's clock with `env.sleep`.
The last test runs a short retention on the real local Temporal server (127.0.0.1:7233).
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from mission_control.adapters.temporal.activities.session_retention import (
    SessionRetentionActivities,
    TemporalSessionDeletionScheduler,
    session_retention_workflow_id,
)
from mission_control.adapters.temporal.workflow_sandbox import coordinator_workflow_runner
from mission_control.adapters.temporal.workflows.session_retention import (
    HostedSessionRetentionWorkflow,
)
from mission_control.application.execution.harness.retention import (
    HostedSessionDeleter,
    SessionDeletionService,
    SessionRetentionService,
)
from mission_control.domain.execution.lanes import LaneProfileName
from mission_control.domain.execution.session_retention import (
    SessionDeletion,
    SessionRetentionPolicy,
)
from tests.fixtures.session_retention import FakeSessionDeleter

ADDRESS = os.environ.get("MC_TEMPORAL_TEST_ADDRESS", "127.0.0.1:7233")
NAMESPACE = os.environ.get("MC_TEMPORAL_TEST_NAMESPACE", "default")
SCOPE = "mc/00000000-0000-0000-0000-000000000001/ai-engineer/00000000-0000-0000-0000-000000000002"


def _worker(
    client: Client, queue: str, deleters: dict[LaneProfileName, HostedSessionDeleter]
) -> Worker:
    return Worker(
        client,
        task_queue=queue,
        workflows=[HostedSessionRetentionWorkflow],
        activities=[SessionRetentionActivities(SessionDeletionService(deleters)).delete],
        workflow_runner=coordinator_workflow_runner(),
    )


def _service(
    client: Client, queue: str, retention: timedelta, now: datetime
) -> SessionRetentionService:
    return SessionRetentionService(
        TemporalSessionDeletionScheduler(client, task_queue=queue),
        policy=SessionRetentionPolicy(retention=retention),
        clock=lambda: now,
    )


@pytest.mark.parametrize("profile", ["claude_managed", "codex_agents"])
async def test_a_hosted_session_is_deleted_only_after_custody_plus_retention(
    profile: LaneProfileName,
) -> None:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        queue = f"session-retention-{uuid.uuid4()}"
        session_ref = f"session-{uuid.uuid4().hex[:8]}"
        deleter = FakeSessionDeleter({session_ref})
        custody_at = await env.get_current_time()
        service = _service(env.client, queue, timedelta(days=7), custody_at)
        async with _worker(env.client, queue, {profile: deleter}):
            order = await service.after_custody(
                lane_profile=profile, request_scope=SCOPE, session_ref=session_ref
            )
            assert order is not None
            handle = env.client.get_workflow_handle_for(
                HostedSessionRetentionWorkflow.run, session_retention_workflow_id(order)
            )

            await env.sleep(timedelta(days=6, hours=23))
            assert deleter.calls == [] and session_ref in deleter.live
            assert (await handle.describe()).status == WorkflowExecutionStatus.RUNNING

            await env.sleep(timedelta(hours=2))
            result = await handle.result()
            assert await env.get_current_time() >= order.delete_after
            assert (result.lane_profile, result.session_ref, result.outcome) == (
                profile,
                session_ref,
                "deleted",
            )
            assert deleter.calls == [session_ref] and deleter.live == set()

            # Ordering the same session again, after its deletion, starts nothing.
            deleted_run = (await handle.describe()).run_id
            await service.after_custody(
                lane_profile=profile, request_scope=SCOPE, session_ref=session_ref
            )
            assert (await handle.describe()).run_id == deleted_run
            assert deleter.calls == [session_ref]


async def test_ordering_a_session_twice_while_its_timer_runs_is_one_deletion() -> None:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        queue = f"session-retention-{uuid.uuid4()}"
        deleter = FakeSessionDeleter({"sesn_1"})
        service = _service(env.client, queue, timedelta(hours=1), await env.get_current_time())
        async with _worker(env.client, queue, {"claude_managed": deleter}):
            first = await service.after_custody(
                lane_profile="claude_managed", request_scope=SCOPE, session_ref="sesn_1"
            )
            assert first is not None
            handle = env.client.get_workflow_handle_for(
                HostedSessionRetentionWorkflow.run, session_retention_workflow_id(first)
            )
            timer_run = (await handle.describe()).run_id
            second = await service.after_custody(
                lane_profile="claude_managed", request_scope=SCOPE, session_ref="sesn_1"
            )
            assert second == first
            assert (await handle.describe()).run_id == timer_run
            await env.sleep(timedelta(hours=2))
            assert (await handle.result()).outcome == "deleted"
            assert deleter.calls == ["sesn_1"]


async def test_a_provider_outage_delays_the_deletion_and_never_drops_it() -> None:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        queue = f"session-retention-{uuid.uuid4()}"
        deleter = FakeSessionDeleter({"sess_1"}, failures=2)
        service = _service(env.client, queue, timedelta(minutes=5), await env.get_current_time())
        async with _worker(env.client, queue, {"codex_agents": deleter}):
            order = await service.after_custody(
                lane_profile="codex_agents", request_scope=SCOPE, session_ref="sess_1"
            )
            assert order is not None
            handle = env.client.get_workflow_handle_for(
                HostedSessionRetentionWorkflow.run, session_retention_workflow_id(order)
            )
            await env.sleep(timedelta(hours=1))
            assert (await handle.result()).outcome == "deleted"
            assert deleter.calls == ["sess_1"] * 3 and deleter.live == set()


async def test_a_session_the_provider_no_longer_has_counts_as_deleted() -> None:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        queue = f"session-retention-{uuid.uuid4()}"
        deleter = FakeSessionDeleter()
        service = _service(env.client, queue, timedelta(0), await env.get_current_time())
        async with _worker(env.client, queue, {"claude_managed": deleter}):
            order = await service.after_custody(
                lane_profile="claude_managed", request_scope=SCOPE, session_ref="gone"
            )
            assert order is not None
            handle = env.client.get_workflow_handle_for(
                HostedSessionRetentionWorkflow.run, session_retention_workflow_id(order)
            )
            assert (await handle.result()).outcome == "absent"


async def test_a_deletion_runs_on_schedule_on_the_real_local_temporal_server() -> None:
    try:
        client = await Client.connect(ADDRESS, namespace=NAMESPACE)
    except RuntimeError as error:
        pytest.fail(f"the real local Temporal server at {ADDRESS} is required: {error}")
    queue = f"session-retention-{uuid.uuid4()}"
    session_ref = f"sesn_{uuid.uuid4().hex[:12]}"
    deleter = FakeSessionDeleter({session_ref})
    custody_at = datetime.now(UTC)
    service = _service(client, queue, timedelta(seconds=3), custody_at)
    async with _worker(client, queue, {"claude_managed": deleter}):
        order = await service.after_custody(
            lane_profile="claude_managed", request_scope=SCOPE, session_ref=session_ref
        )
        assert isinstance(order, SessionDeletion)
        handle = client.get_workflow_handle_for(
            HostedSessionRetentionWorkflow.run, session_retention_workflow_id(order)
        )
        result = await handle.result()
        assert result.outcome == "deleted" and deleter.live == set()
        history = await handle.fetch_history()
        timers = [
            event.timer_started_event_attributes.start_to_fire_timeout.ToTimedelta()
            for event in history.events
            if event.HasField("timer_started_event_attributes")
        ]
        assert len(timers) == 1 and timedelta(0) < timers[0] <= timedelta(seconds=3)
        closed = (await handle.describe()).close_time
        assert closed is not None and closed >= order.delete_after
