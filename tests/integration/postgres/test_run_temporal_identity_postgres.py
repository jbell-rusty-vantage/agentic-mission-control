"""R1-F14: `PostgresRunControlRepository.record_temporal_ids` on the disposable database.

The run's Temporal workflow id and run id are written once after `start_workflow`; an
idempotent re-launch that offers no Temporal run id is "unknown", not a conflict; a
different recorded identity is a `TemporalIdentityConflict` and writes nothing. Moved from
tests/unit/run_control/test_run_fence_backing.py, which faked the asyncpg pool and patched
`run_control.canonical.begin` (OVE-238).
"""

from __future__ import annotations

from uuid import uuid4

import asyncpg
import pytest

from mission_control.adapters.postgres.run_control.run_control_repository import (
    PostgresRunControlRepository,
)
from mission_control.application.execution.run_control_repository import (
    TemporalIdentityConflict,
)
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.support.db_builders import insert_fixture_run, owner_rows

pytestmark = pytest.mark.common_db


async def _run(common_db: CommonDatabase) -> str:
    run_key = f"run-temporal-identity-{uuid4()}"
    await insert_fixture_run(common_db, common_db.scope(), run_key)
    return run_key


async def _recorded(common_db: CommonDatabase, run_key: str) -> tuple[str | None, str | None]:
    (row,) = await owner_rows(
        common_db,
        "SELECT temporal_workflow_id, temporal_run_id FROM mission_control.mission_run "
        "WHERE run_key=$1",
        run_key,
    )
    return row["temporal_workflow_id"], row["temporal_run_id"]


async def test_a_relaunch_without_a_temporal_run_id_is_a_no_op(
    common_db: CommonDatabase, runtime_pool: asyncpg.Pool
) -> None:
    store = PostgresRunControlRepository(runtime_pool)
    scope, run_key = common_db.scope(), await _run(common_db)
    await store.record_temporal_ids(
        scope, run_key, workflow_id="belllabs-run/x", temporal_run_id="run-a"
    )
    await store.record_temporal_ids(
        scope, run_key, workflow_id="belllabs-run/x", temporal_run_id=None
    )
    assert await _recorded(common_db, run_key) == ("belllabs-run/x", "run-a")
    with pytest.raises(TemporalIdentityConflict):
        await store.record_temporal_ids(
            scope, run_key, workflow_id="belllabs-run/x", temporal_run_id="run-b"
        )
    with pytest.raises(TemporalIdentityConflict):
        await store.record_temporal_ids(
            scope, run_key, workflow_id="belllabs-run/other", temporal_run_id=None
        )
    assert await _recorded(common_db, run_key) == ("belllabs-run/x", "run-a")


async def test_unknown_identities_are_written_once(
    common_db: CommonDatabase, runtime_pool: asyncpg.Pool
) -> None:
    store = PostgresRunControlRepository(runtime_pool)
    scope, run_key = common_db.scope(), await _run(common_db)
    assert await _recorded(common_db, run_key) == (None, None)
    await store.record_temporal_ids(
        scope, run_key, workflow_id="belllabs-run/x", temporal_run_id=None
    )
    assert await _recorded(common_db, run_key) == ("belllabs-run/x", None)
    await store.record_temporal_ids(
        scope, run_key, workflow_id="belllabs-run/x", temporal_run_id=None
    )
    await store.record_temporal_ids(
        scope, run_key, workflow_id="belllabs-run/x", temporal_run_id="run-a"
    )
    assert await _recorded(common_db, run_key) == ("belllabs-run/x", "run-a")
    with pytest.raises(TemporalIdentityConflict):
        await store.record_temporal_ids(
            scope, run_key, workflow_id="belllabs-run/other", temporal_run_id="run-a"
        )
