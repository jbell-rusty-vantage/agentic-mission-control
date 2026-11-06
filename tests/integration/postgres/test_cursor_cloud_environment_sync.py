"""MO-13 on a disposable PostgreSQL 17: the production `compose_cursor_cloud` syncs a seeded
Environment Kit into a Cursor environment.

The starter kits are seeded into the common catalog and their bundle bytes uploaded to a
filesystem custody store, so the kit is read under the restricted runtime role and its base
install script is verified against its pin. Two missions pinning `envkit.python-uv` run one
`lane.turn` each through the real lane turn service: the first creates `mc-envkit.python-uv-<8>`
for the target repository and writes the declared secret by name, the second reuses it without
any update, and both run branches carry the kit's mission layer. Only the Cloud Agents and
environments APIs are fakes (no Cursor account is called).
"""

from __future__ import annotations

import json
from contextlib import AsyncExitStack
from pathlib import Path

import asyncpg
import pytest
from pydantic import SecretStr

from mission_control.adapters.capabilities.local_bundle_store import (
    FilesystemBundleFetcher,
    FilesystemBundleObjectStore,
)
from mission_control.adapters.cursor.cloud import run_branch
from mission_control.adapters.cursor.cloud_api import CloudAgentsClient
from mission_control.adapters.cursor.environments import CursorEnvironmentsClient
from mission_control.adapters.cursor.secrets import CursorSecretsClient
from mission_control.adapters.cursor.workspace import git
from mission_control.adapters.operations.runtime_ports import FilesystemArtifactPayloadStore
from mission_control.adapters.postgres.control_plane.definition_repository import (
    PostgresDefinitionRepository,
)
from mission_control.adapters.temporal import deployment_composition
from mission_control.application.capabilities.bundle_custody import BundleMaterializer
from mission_control.application.execution.harness.lane_turns import LaneExecutionIdentity
from mission_control.domain.authoring.contracts import DefinitionKind
from mission_control.domain.authoring.environment_kits import MISSION_SETUP_RUN
from mission_control.domain.capabilities.catalog_entry import capability_pin
from mission_control.domain.execution.contracts import OperationExecutionRequest
from mission_control.domain.execution.lane_turns import LaneTurnRequest
from mission_control.domain.execution.lanes import CursorExecutionBinding
from tests.fixtures.cursor_cloud import (
    API_KEY,
    FakeCloudApi,
    cloud_operation,
    load_cloud_fixture,
    make_remote,
)
from tests.fixtures.cursor_environments import FakeEnvironmentsApi
from tests.fixtures.isolated_settings import isolated_settings
from tests.fixtures.lane_turns import ACTIVATION_UUID, RUN_UUID, RecordingSignals, lane_stack
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.integration.postgres.catalog_common import BIOTECH_CATALOG, seeds_publish_module
from tests.integration.postgres.catalog_common import catalog_db as catalog_db
from tests.integration.postgres.catalog_common import runtime_pool as runtime_pool
from tests.integration.postgres.test_environment_kits_postgres import _seed

pytestmark = pytest.mark.common_db

SENTINEL = "mo13-sentinel-firecrawl-value"


async def test_production_cursor_cloud_syncs_a_seeded_kit_once_and_reuses_it(
    catalog_db: CommonDatabase,
    runtime_pool: asyncpg.Pool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed(catalog_db)
    store = FilesystemBundleObjectStore(tmp_path / "custody")
    await seeds_publish_module().publish_application("biotech", store)
    bundles = BundleMaterializer(store, FilesystemBundleFetcher(store))
    kit = next(
        item
        for item in await PostgresDefinitionRepository(
            runtime_pool, catalog_scope=BIOTECH_CATALOG
        ).list_published_definitions()
        if item.ref.kind == DefinitionKind.ENVIRONMENT_KIT
        and item.ref.logical_id == "envkit.python-uv"
    )
    pin = capability_pin(kit).render()

    monkeypatch.setenv("MC_MO13_FIRECRAWL", SENTINEL)
    remote = make_remote(tmp_path)
    events, record = load_cloud_fixture()
    agents = FakeCloudApi(events, record, remote)
    environments = FakeEnvironmentsApi()
    monkeypatch.setattr(
        deployment_composition,
        "CloudAgentsClient",
        lambda key: CloudAgentsClient(key, transport=agents.transport()),
    )
    monkeypatch.setattr(
        deployment_composition,
        "CursorEnvironmentsClient",
        lambda key: CursorEnvironmentsClient(key, transport=environments.transport()),
    )
    monkeypatch.setattr(
        deployment_composition,
        "CursorSecretsClient",
        lambda key: CursorSecretsClient(key, transport=environments.transport()),
    )
    scope = catalog_db.scope("tenant-1")
    resources = AsyncExitStack()
    try:
        settings = isolated_settings(
            cursor_api_key=SecretStr(API_KEY),
            cursor_lease_root=tmp_path / "leases",
            mission_control_catalog_scope=BIOTECH_CATALOG,
        )
        secrets = await deployment_composition.compose_secret_broker(settings, resources)
        composed = deployment_composition.compose_cursor_cloud(
            settings,
            runtime_pool,
            FilesystemArtifactPayloadStore(tmp_path / "payloads"),
            bundles=bundles,
            secrets=secrets,
        )
        assert composed is not None
        harness, client, api = composed
        resources.push_async_callback(client.aclose)
        resources.push_async_callback(api.aclose)
        template = cloud_operation(
            remote,
            (),
            provider_environment={
                "strategy": "sync",
                "kit_pin": pin,
                "secret_refs": ["FIRECRAWL_API_KEY=environment:MC_MO13_FIRECRAWL"],
            },
        )

        async def mission(run_id: str) -> None:
            operation = OperationExecutionRequest.model_validate(
                {
                    **template.model_dump(mode="python"),
                    "request_scope": scope,
                    "identity": template.identity.model_copy(update={"run_id": run_id}),
                }
            )
            lanes = lane_stack(harness, operation=operation, redaction=secrets.registry)
            lanes.frames.register_run(
                scope, run_id, RUN_UUID, {operation.identity.operation_id: ACTIVATION_UUID}
            )
            result = await lanes.service.turn(
                LaneTurnRequest(operation=operation, lane_profile="cursor_cloud", generation=1),
                RecordingSignals(lanes.frames),
            )
            assert result.done
            identity = LaneExecutionIdentity.of(operation, "cursor_cloud", 1)
            execution = lanes.frames._executions[identity.harness_execution_id]
            assert all(SENTINEL not in frame.body_excerpt for frame in execution.frames.values())
            assert CursorExecutionBinding.carried_by(operation) is not None
            branch = run_branch(
                CursorExecutionBinding.carried_by(operation),
                run_id,
                operation.identity.operation_id,
            )
            assert MISSION_SETUP_RUN in git("ls-tree", "-r", "--name-only", branch, cwd=remote)

        await mission("run-mo13-1")
        created = environments.writes()
        await mission("run-mo13-2")
    finally:
        await resources.aclose()

    (environment,) = environments.environments.values()
    assert environment["name"].startswith("mc-envkit.python-uv-")
    assert environment["repos"] == [{"url": str(remote)}]
    config = json.loads(environments.history[environment["id"]][0]["environmentJson"])
    assert config["name"] == "mc:envkit.python-uv@1"
    assert "uv python install 3.12" in config["install"], "the seeded base layer from custody"
    assert environments.secrets[environment["id"]] == {"FIRECRAWL_API_KEY": SENTINEL}
    environment_path = f"/v1/environments/{environment['id']}"
    assert created == [
        ("POST", "/v1/environments"),
        ("PUT", f"{environment_path}/secrets/FIRECRAWL_API_KEY"),
    ]
    # The second mission: the refused create only (409, reused), no PATCH and no secret PUT.
    assert environments.writes()[len(created) :] == [("POST", "/v1/environments")]
    assert all("env" not in create for create in agents.creates)
    assert SENTINEL in secrets.registry.values(), "redacted wherever this worker writes"
