"""MO-06 on a disposable PostgreSQL 17: the production `compose_cursor_cloud` records the run
branch as a fenced `provider_workspace` lease through the runtime role under forced RLS and
resolves a binding's `env_vars_ref` through the deployment's secret port (MO-11: the composed
Secret Broker, here serving the worker environment). Only the Cloud Agents API is a fake (no
Cursor account is called)."""

from __future__ import annotations

from contextlib import AsyncExitStack
from pathlib import Path

import pytest
from pydantic import SecretStr

from mission_control.adapters.cursor.cloud import run_branch
from mission_control.adapters.cursor.cloud_api import CloudAgentsClient
from mission_control.adapters.cursor.workspace import git
from mission_control.adapters.operations.runtime_ports import FilesystemArtifactPayloadStore
from mission_control.adapters.postgres.lanes.workspace_leases import PostgresWorkspaceLeaseStore
from mission_control.adapters.temporal import deployment_composition
from mission_control.application.execution.harness.lane_turns import LaneExecutionIdentity
from mission_control.application.execution.harness.leases import lease_identity
from mission_control.application.workspaces.snapshots import branch_snapshot_ref
from mission_control.domain.execution.lane_turns import LaneTurnRequest
from mission_control.domain.execution.lanes import CursorExecutionBinding
from tests.fixtures.cursor_cloud import (
    API_KEY,
    FakeCloudApi,
    cloud_operation,
    load_cloud_fixture,
    make_remote,
)
from tests.fixtures.isolated_settings import isolated_settings
from tests.fixtures.lane_turns import ACTIVATION_UUID, RUN_UUID, RecordingSignals, lane_stack
from tests.fixtures.mission_control_common_db import CommonDatabase, catalog_scope
from tests.integration.postgres.runtime_common import common_db  # noqa: F401

pytestmark = pytest.mark.common_db

SENTINEL = "mo06-sentinel-value"


async def test_production_cursor_cloud_records_the_lease_and_resolves_env_vars(
    common_db: CommonDatabase,  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MC_MO06_MODE", SENTINEL)
    remote = make_remote(tmp_path)
    events, record = load_cloud_fixture()
    api = FakeCloudApi(events, record, remote)
    monkeypatch.setattr(
        deployment_composition,
        "CloudAgentsClient",
        lambda key: CloudAgentsClient(key, transport=api.transport()),
    )
    scope = common_db.scope("tenant-1")
    operation = cloud_operation(
        remote, (), env_vars_ref="environment:MC_MO06_MODE", client_agent_id=False
    ).model_copy(update={"request_scope": scope})
    pool = await common_db.pool("mission_control_runtime")
    resources = AsyncExitStack()
    try:
        settings = isolated_settings(
            cursor_api_key=SecretStr(API_KEY),
            cursor_lease_root=tmp_path / "leases",
            mission_control_catalog_scope=catalog_scope(),
        )
        secrets = await deployment_composition.compose_secret_broker(settings, resources)
        composed = deployment_composition.compose_cursor_cloud(
            settings,
            pool,
            FilesystemArtifactPayloadStore(tmp_path / "payloads"),
            bundles=None,
            secrets=secrets,
        )
        assert composed is not None
        harness, client, environments = composed
        lanes = lane_stack(harness, operation=operation, redaction=secrets.registry)
        lanes.frames.register_run(
            scope,
            operation.identity.run_id,
            RUN_UUID,
            {operation.identity.operation_id: ACTIVATION_UUID},
        )
        identity = LaneExecutionIdentity.of(operation, "cursor_cloud", 1)
        result = await lanes.service.turn(
            LaneTurnRequest(operation=operation, lane_profile="cursor_cloud", generation=1),
            RecordingSignals(lanes.frames),
        )
        await client.aclose()
        await environments.aclose()
        assert result.done

        # env_vars_ref: resolved from the worker environment and sent on the keyed create.
        (create,) = api.creates
        assert create["envVars"] == {"MC_MO06_MODE": SENTINEL} and "agentId" not in create

        # The provider workspace lease: recorded in PostgreSQL, released after custody.
        assert CursorExecutionBinding.carried_by(operation) is not None
        # Production isolates each execution unit's published branch within the run.
        branch = run_branch(
            CursorExecutionBinding.carried_by(operation),
            operation.identity.run_id,
            operation.identity.operation_id,
        )
        head = git("rev-parse", branch, cwd=remote).strip()
        lease_id, lease_key = lease_identity("cursor_cloud", identity.harness_execution_id, 1)
        lease = await PostgresWorkspaceLeaseStore(pool).get(scope, lease_id)
        assert lease is not None and lease.lease_key == lease_key
        assert lease.policy is not None and lease.policy.mode == "provider_workspace"
        assert lease.allocator_ref == "deployment:cursor_cloud"
        assert lease.path == f"provider:cursor_cloud:{branch}" and lease.branch == branch
        assert lease.base_commit == git("rev-parse", "main", cwd=remote).strip()
        assert lease.snapshot_ref == branch_snapshot_ref(branch, head)
        assert lease.released and lease.cleanup_status == "not_required"
        assert SENTINEL not in lease.model_dump_json()
        frames = lanes.frames._executions[identity.harness_execution_id].frames.values()
        assert all(SENTINEL not in frame.body_excerpt for frame in frames)
        assert SENTINEL in secrets.registry.values(), "redacted wherever this worker writes"
    finally:
        await resources.aclose()
        await pool.close()
