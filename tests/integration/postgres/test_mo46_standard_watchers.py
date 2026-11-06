"""Real PostgreSQL: each standard template acts through canonical watcher paths."""

from datetime import UTC, datetime, timedelta

import pytest

from mission_control.adapters.postgres.frames.repository import PostgresFrameRepository
from mission_control.application.frames.writer import FrameWriter
from mission_control.application.watchers.ports import WatcherCursor
from mission_control.application.watchers.service import (
    WatcherEvaluationService,
    WatcherPassRequest,
)
from mission_control.domain.frames.contracts import FrameKind, FrameObservation
from mission_control.domain.policies.contracts import CommandStatus, SetWaitAction
from mission_control.domain.programs.watchers import compile_watcher, wait_condition_id
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.integration.postgres.frames_common import admit_unit_attempt
from tests.integration.postgres.runtime_common import common_db, scoped_command  # noqa: F401
from tests.integration.postgres.test_mo44_watchers_postgres import FixedProgram
from tests.integration.postgres.test_mp15_coordinator_inbox_postgres import mission_service
from tests.unit.run_control.test_boundary_commands import declared_wait
from tests.unit.watchers.test_standard_library import DATA, LIBRARY

pytestmark = pytest.mark.common_db


@pytest.mark.parametrize("entry", LIBRARY.definitions(), ids=lambda entry: entry.logical_id)
async def test_standard_template_records_real_admitted_actions_once(
    common_db: CommonDatabase,  # noqa: F811
    entry,
) -> None:
    pool = await common_db.pool()
    try:
        admitted = await admit_unit_attempt(pool, common_db)
        scope, run_key = common_db.scope(), admitted.run_key
        now = datetime.now(UTC)
        name = entry.logical_id.removeprefix("watcher.")
        if name == "pr-merged-release-wait":
            run = await admitted.run_control.get_run(scope, run_key)
            receipt = await admitted.run_control.execute(
                scoped_command(
                    common_db,
                    run_key,
                    run.version,
                    "wait-for-merge",
                    SetWaitAction(
                        condition=declared_wait(wait_condition_id("await-merge")),
                        runnable_work_remains=True,
                    ),
                )
            )
            assert receipt.status == CommandStatus.ACCEPTED
        if name != "stall-detector":
            frames = PostgresFrameRepository(pool)
            writer = FrameWriter(frames, await frames.open_execution(admitted.start()))
            await writer.write(
                [
                    FrameObservation(
                        provider_key=f"fixture:{name}",
                        raw_kind=f"signal.{entry.spec.on.signal}",
                        kind=FrameKind.STATUS,
                        observed_at=now,
                        body={"data": DATA[name], "trust_tier": "provider_signed"},
                    )
                ]
            )
        descriptor = compile_watcher(
            entry.spec, watcher_id=name, origin="catalog", pointer="/fixture"
        )
        store = FixedProgram(pool, scope, (descriptor,))
        facade, _ = mission_service(pool, scope)
        service = WatcherEvaluationService(store, facade)
        request = WatcherPassRequest(
            run_id=run_key, cursor=WatcherCursor(), armed_at=now, now=now + timedelta(minutes=21)
        )
        report = await service.run_pass(request)
        assert len(report.firings) == 1
        assert all(
            action.status in {"admitted", "recorded"} for action in report.firings[0].actions
        )
        assert len(await store.history(run_key)) == 1
        assert not (await service.run_pass(request)).firings
        if name == "pr-merged-release-wait":
            assert not (await admitted.run_control.get_run(scope, run_key)).active_waits
    finally:
        await pool.close()
