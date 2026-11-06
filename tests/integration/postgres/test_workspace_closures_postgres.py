"""`PostgresWorkspaceClosures` over the 1.12.0 common database (OVE-204 slice 5).

A closure captured from the text-only backend is recorded (bodies staged first, then header and
entries in one transaction), idempotent under concurrent retries, read back by id, point and
run, bound to its run for body reads, and invisible to another tenant.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import asyncpg
import pytest
from deepagents.backends.state import StateBackend

from mission_control.adapters.deep_agents.workspace_closure import capture_closure
from mission_control.adapters.operations.runtime_ports import FilesystemArtifactPayloadStore
from mission_control.adapters.postgres.workspace_closures import (
    PostgresWorkspaceClosures,
    WorkspaceClosureRunMissing,
)
from mission_control.domain.graph_runtime.identities import QualifiedCheckpointKey
from mission_control.domain.resolution.profiles import WorkspaceClosureProfile
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.integration.postgres.catalog_common import catalog_db as catalog_db
from tests.integration.postgres.catalog_common import insert_fixture_run
from tests.integration.postgres.catalog_common import runtime_pool as runtime_pool
from tests.unit.deep_agents.test_workspace_closure import _workspace

pytestmark = pytest.mark.common_db
UNIT = "bl-unit-v1:" + "f" * 64


@pytest.mark.asyncio
async def test_closures_record_once_and_read_back_under_scope(
    catalog_db: CommonDatabase, runtime_pool: asyncpg.Pool, tmp_path
) -> None:
    scope = catalog_db.scope("tenant-a")
    run_key = "run-closure-postgres"
    await insert_fixture_run(catalog_db, scope, run_key)
    captured = await capture_closure(
        StateBackend(),
        _workspace(sensitive=True),
        {
            "files": {
                "/out/report.md": {"content": "# report\n", "encoding": "utf-8"},
                "/private/notes.txt": {"content": "private", "encoding": "utf-8"},
            }
        },
        run_id=run_key,
        unit_key=UNIT,
        execution_generation=1,
        harness_execution_id=None,
        result_key=QualifiedCheckpointKey(
            checkpointer_ref_digest="sha256:" + "b" * 64,
            thread_id="thread-closures",
            checkpoint_id="1f0-result",
        ),
        boundary="attempt_settled",
        policy=WorkspaceClosureProfile(),
        now=datetime.now(UTC),
    )
    assert captured is not None
    closure = captured.closure
    payloads = FilesystemArtifactPayloadStore(tmp_path)
    store = PostgresWorkspaceClosures(runtime_pool, payloads)
    await asyncio.gather(
        *(
            store.put(closure, captured.bodies, request_scope=scope, retain_until=None)
            for _ in range(3)
        )
    )
    assert await store.get(scope, closure.closure_id) == closure
    assert await store.for_point(scope, run_key, closure.point_id) == (closure,)
    (summary,) = await store.list_for_run(scope, run_key)
    assert summary.closure_ref == closure.ref and summary.file_count == 2
    assert summary.promoted_bytes == len(b"# report\n")
    promoted = next(item for item in closure.files if item.body_state == "promoted")
    record = await store.run_closure_body(scope, run_key, promoted.digest)
    assert record is not None and record.size_bytes == promoted.size_bytes
    withheld = next(item for item in closure.files if item.body_state != "promoted")
    assert await store.run_closure_body(scope, run_key, withheld.digest) is None
    assert await store.run_closure_body(scope, "another-run", promoted.digest) is None
    other = catalog_db.scope("tenant-b")
    assert await store.get(other, closure.closure_id) is None
    assert await store.list_for_run(other, run_key) == ()
    with pytest.raises(WorkspaceClosureRunMissing):
        await store.put(
            closure.model_copy(update={"run_id": "missing-run"}),
            captured.bodies,
            request_scope=scope,
            retain_until=None,
        )
