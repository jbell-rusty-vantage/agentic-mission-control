"""Real PG proof: trusted source registration, scoped frames, watcher consumption."""

import socket
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from temporalio.worker import Worker

from mission_control.adapters.postgres.frames.repository import PostgresFrameRepository
from mission_control.adapters.postgres.watchers import PostgresWatcherStore
from mission_control.adapters.temporal.activities.watchers import WatcherActivities
from mission_control.adapters.temporal.workflow_sandbox import coordinator_workflow_runner
from mission_control.adapters.temporal.workflows.watchers import (
    WatchersWorkflow,
    WatchersWorkflowInput,
)
from mission_control.application.watchers.ports import WatcherCursor
from mission_control.application.watchers.service import WatcherEvaluationService
from mission_control.bootstrap.watch_sources import RegisteredWatchSources, SourceWatchRegistration
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.integration.postgres.frames_common import admit_unit_attempt
from tests.integration.postgres.runtime_common import common_db  # noqa: F401
from tests.integration.postgres.test_mo44_watchers_postgres import (
    FixedProgram,
    eventually,
    local_temporal,
)
from tests.integration.postgres.test_mp15_coordinator_inbox_postgres import mission_service
from tests.unit.watchers.fakes import T0
from tests.unit.watchers.test_watcher_planner import plan, watcher

pytestmark = pytest.mark.common_db


async def test_registered_worker_source_persists_deduplicates_and_drives_watcher(
    common_db: CommonDatabase,  # noqa: F811
    tmp_path: Path,
) -> None:
    pool = await common_db.pool()
    try:
        admitted = await admit_unit_attempt(pool, common_db)
        frames = PostgresFrameRepository(pool)
        handle = await frames.open_execution(admitted.start())
        path = tmp_path / "done"
        path.write_text("done")
        registration = SourceWatchRegistration(
            id="done",
            request_scope=common_db.scope(),
            run_key=admitted.run_key,
            harness_execution_id=handle.harness_execution_id,
            generation=handle.generation,
            kind="worker",
            worker_host=socket.gethostname(),
            watch={"kind": "file", "resource": str(path)},
        )
        async with httpx.AsyncClient() as http:
            sources = RegisteredWatchSources(pool, http, [registration])
            await sources.sample(common_db.scope(), admitted.run_key, T0)
            await sources.sample(common_db.scope(), admitted.run_key, T0)
            await sources.sample(common_db.scope(), "wrong-run", T0)
        page = await PostgresWatcherStore(pool, common_db.scope()).observations(
            admitted.run_key, after=WatcherCursor(), limit=100
        )
        signals = [item for item in page.observations if item.source == "signal"]
        assert len(signals) == 1
        descriptor = watcher(
            "done",
            {
                "on": {"signal": "worker.file"},
                "then": [{"notify": {"kind": "progress", "text": "done"}}],
                "limits": {"max_fires": 1},
            },
        )
        assert plan([descriptor], signals).firings
        assert (
            await frames.existing_execution(
                common_db.scope(), admitted.run_key, handle.harness_execution_id, 999
            )
            is None
        )
    finally:
        await pool.close()


async def test_existing_temporal_evaluator_samples_registered_source_and_records_once(
    common_db: CommonDatabase,  # noqa: F811
    tmp_path: Path,
) -> None:
    pool = await common_db.pool()
    handle = None
    try:
        admitted = await admit_unit_attempt(pool, common_db)
        frames = PostgresFrameRepository(pool)
        execution = await frames.open_execution(admitted.start())
        path = tmp_path / "finished"
        path.write_text("done")
        registration = SourceWatchRegistration(
            id="temporal-file",
            request_scope=common_db.scope(),
            run_key=admitted.run_key,
            harness_execution_id=execution.harness_execution_id,
            generation=execution.generation,
            kind="worker",
            worker_host=socket.gethostname(),
            watch={"kind": "file", "resource": str(path)},
        )
        descriptor = watcher(
            "source-file",
            {
                "on": {"signal": "worker.file"},
                "then": [{"notify": {"kind": "progress", "text": "file observed"}}],
                "limits": {"max_fires": 1},
            },
        )
        timer = watcher(
            "timer",
            {
                "on": {"schedule": {"every": "1s"}},
                "then": [{"notify": {"kind": "progress", "text": "timer"}}],
                "limits": {"max_fires": 1},
            },
        )
        store = FixedProgram(pool, common_db.scope(), (descriptor, timer))
        facade, _ = mission_service(pool, common_db.scope())
        service = WatcherEvaluationService(store, facade)
        client = await local_temporal()
        queue = f"mo45-{uuid4()}"
        async with httpx.AsyncClient() as http:
            sources = RegisteredWatchSources(pool, http, [registration])
            activities = WatcherActivities(lambda scope: service, sources=sources.sample)
            async with Worker(
                client,
                task_queue=queue,
                workflows=[WatchersWorkflow],
                activities=[activities.evaluate],
                workflow_runner=coordinator_workflow_runner(),
            ):
                handle = await client.start_workflow(
                    WatchersWorkflow.run,
                    WatchersWorkflowInput(
                        request_scope=common_db.scope(), run_id=admitted.run_key, poll_seconds=1
                    ),
                    id=f"mo45-{uuid4()}",
                    task_queue=queue,
                )
                history = await eventually(
                    lambda: store.history(admitted.run_key), lambda items: len(items) == 2
                )
                assert {item.watcher_id for item in history} == {"source-file", "timer"}
                state = await handle.query(WatchersWorkflow.state)
                await eventually(
                    lambda: handle.query(WatchersWorkflow.state),
                    lambda newer: newer["passes"] >= state["passes"] + 2,
                )
                assert len(await store.history(admitted.run_key)) == 2
    finally:
        if handle is not None:
            await handle.terminate("MO45 fixture cleanup")
        await pool.close()
