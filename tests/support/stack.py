"""The production API and worker composition over real PostgreSQL 17 and Temporal.

One builder, `open_stack`, for one composition, with two front doors:

- ``signed=False`` (inspection mode, `ProductionStack`): the technical API
  (`bootstrap.technical_api.api`) with an operator principal, composed by
  `compose_runtime_control`; the RRM-009 inspection helpers below (`_admit`, `_run`,
  `canonical_evidence`...) drive it.
- ``signed=True`` (signed mode, `ScopedStack`): the configured application
  (`bootstrap.api.create_application`) in ``production_common`` storage mode, every request
  carrying a token signed by a generated key whose public JWKS the deployment pins;
  ``saver_proxy=`` routes the LangGraph saver through a TCP proxy.

Both run on a fresh database with the common ``mission_control`` component installed
(`tests.fixtures.mission_control_common_db`): the API and workers connect as restricted
``mission_control_runtime`` / ``mission_control_family_writer`` logins under forced row-level
security, the LangGraph saver/store use the provisioned ``mission_control_runtime`` schema
through a checkpointer-only login, and every scope is a canonical
``mc/{installation}/{application}/{tenant}`` scope. The production workers run deterministic
Deep Agents cognition (`tests.fixtures.rrm009_production_stack`); no provider is called.

The stack is hermetic (`bind_hermetic_environment`): it never reads the developer ``.env``,
it drops every `Settings` variable the developer shell exported, and it depends on no sibling
checkout (the capability resource owner is an empty directory under ``root`` and the pin file
carries no host-resolved tool or Skill pin). Only ``MISSION_CONTROL_TEST_ADMIN_DSN`` (a
loopback administrator DSN that authorizes creating and dropping the database) is read from the
environment; set ``MISSION_CONTROL_E2E_KEEP_DATABASE=1`` to keep the database for failure
inspection. Temporal starts through the SDK (``MISSION_CONTROL_TEMPORAL_CLI`` or the cached
SDK CLI). Missing prerequisites fail the proof instead of converting it to a successful skip.

The multi-lane parity stack (`tests.fixtures.mp20_parity.open_parity_stack`) builds on the
inspection mode and adds the provider-lane fakes.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from typing import Any, Literal, cast, overload
from unittest.mock import patch
from uuid import uuid4

import asyncpg
import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from joserfc import jwt
from joserfc.jwk import RSAKey
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from temporalio.api.enums.v1 import TaskQueueType
from temporalio.api.taskqueue.v1 import TaskQueue
from temporalio.api.workflowservice.v1 import DescribeTaskQueueRequest
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from mission_control.adapters.auth.jwt import ActorGrant, ApplicationAuthentication
from mission_control.adapters.operations.runtime_ports import (
    FilesystemArtifactPayloadStore,
)
from mission_control.adapters.postgres.connections import (
    create_application_family_writer_pool,
    create_application_postgres_pool,
)
from mission_control.adapters.postgres.control_plane.definition_repository import (
    PostgresDefinitionRepository,
)
from mission_control.adapters.postgres.frames.retention import PostgresFrameRetention
from mission_control.adapters.postgres.orchestration.goal_directed_repository import (
    PostgresGoalDirectedDocumentRepository,
)
from mission_control.adapters.postgres.orchestration.stagegraph_repository import (
    PostgresStageGraphOperationTemplateRepository,
)
from mission_control.adapters.postgres.run_control.run_control_repository import (
    PostgresRunControlRepository,
)
from mission_control.adapters.storage.control_plane_payloads import UnavailablePayloadStore
from mission_control.adapters.temporal.activities.fork_seed import ForkSeedActivities
from mission_control.adapters.temporal.activities.frames_expire import FramesExpireActivities
from mission_control.adapters.temporal.activities.transcript_projection import (
    TranscriptProjectionActivities,
    start_transcript_projection_relay,
)
from mission_control.adapters.temporal.coordinator_runtime import coordinator_task_queues
from mission_control.adapters.temporal.deployment_composition import (
    DeploymentCapabilityComponents,
    KnowledgeLaneFactory,
    ProductionWorkerActivityCompositionFactory,
    artifact_payload_store,
)
from mission_control.adapters.temporal.registration.task_queues import maintenance_task_queue
from mission_control.adapters.temporal.search_attributes import register_belllabs_search_attributes
from mission_control.adapters.temporal.worker import (
    ProductionWorkerSet,
    WorkerActivityComposition,
    compose_worker_run_control_service,
    create_production_workers,
)
from mission_control.adapters.temporal.workflow_sandbox import coordinator_workflow_runner
from mission_control.adapters.temporal.workflows.belllabs_run import BellLabsRunWorkflow
from mission_control.adapters.temporal.workflows.fork_seed import ForkSeedWorkflow
from mission_control.adapters.temporal.workflows.frames_expire import FramesExpireWorkflow
from mission_control.adapters.temporal.workflows.goal_directed import GoalDirectedWorkflow
from mission_control.adapters.temporal.workflows.operation import OperationWorkflow
from mission_control.adapters.temporal.workflows.stagegraph import (
    StageGraphWorkflow,
    wait_condition_id,
)
from mission_control.adapters.temporal.workflows.transcript_projection import (
    TranscriptProjectionWorkflow,
)
from mission_control.application.artifacts.artifact_promotion import (
    ArtifactPayloadAddress,
    StaticArtifactValidationAuthority,
)
from mission_control.application.authoring.service import ControlPlaneService
from mission_control.application.execution.service import (
    F1RunConfigurationVerifier,
    FamilyAdmissionRegistry,
)
from mission_control.application.installations.registry import ApplicationBinding
from mission_control.application.programs.goal_directed import (
    configure_goal_directed_family_admissions,
)
from mission_control.application.programs.service import register_stagegraph_family_mutations
from mission_control.application.recovery.run_forks import ForkPatchPolicyRegistry
from mission_control.bootstrap.api import (
    ApplicationDeployment,
    MissionDeployment,
    RuntimeOptions,
    TemporalDeployment,
    create_application,
)
from mission_control.bootstrap.composition import MissionApplicationServices
from mission_control.bootstrap.runtime_control import compose_runtime_control
from mission_control.bootstrap.settings import PROJECT_ROOT, Settings, get_settings
from mission_control.bootstrap.technical_api import api
from mission_control.bootstrap.worker import transcript_projectors
from mission_control.contracts.identities import mission_root_id, parse_request_scope
from mission_control.domain.authoring.extensions import ExtensionRegistry
from mission_control.domain.execution.contracts import (
    ArtifactPromotionPlan,
    DeepAgentExecutionBinding,
    GenericArtifactWorkflowRequest,
    OperationAttemptIdentity,
    OperationExecutionRequest,
    WorkspaceOwner,
    WorkspaceOwnerKind,
)
from mission_control.domain.policies.contracts import (
    ActorContext,
    LifecycleCommand,
    ReserveBudgetAction,
    SatisfyWaitAction,
    StartAction,
)
from mission_control.interfaces.http.control_plane import (
    ControlPlanePrincipal,
    get_control_plane_principal,
)
from mission_control.interfaces.http.run_control import (
    ROLE_PERMISSIONS,
    close_run_control_resources,
    initialize_run_control_resources,
)
from tests.fixtures import rrm009_production_stack as technical
from tests.fixtures.checkpoint_lineage import bind_unit, stage_unit
from tests.fixtures.db_env import db_env_name
from tests.fixtures.lane_bindings import lane_fields
from tests.fixtures.mission_control_common_db import (
    COMPONENT_VERSION,
    CommonDatabase,
    create_common_database,
    drop_common_database,
    provision_runtime,
)
from tests.fixtures.prerequisite_preflight import bind_disposable_prerequisites
from tests.fixtures.rrm009_production_stack import (
    LANGGRAPH_SCHEMA,
    OPERATOR,
    REPORT_PATH,
    TASK_QUEUE,
    WAIT_ID,
    TechnicalBinding,
    TechnicalCatalog,
    admission_request,
    publish_technical_catalog,
    stage_templates,
    technical_admission_policies,
    technical_binding,
)
from tests.fixtures.tcp_proxy import SaverProxy
from tests.support.ids import SCOPE, canonical_scope

# --- Hermetic environment --------------------------------------------------------------------

# The process environment when this module was imported: the developer shell, plus the offline
# placeholders `tests/conftest.py` adds in a checkout without `.env`. A value a test sets later
# (through `monkeypatch` or `extra_environment`) differs from it and is kept.
_INHERITED_ENVIRONMENT = dict(os.environ)
_SETTINGS_VARIABLES = frozenset(name.upper() for name in Settings.model_fields)
# The deployment's reviewed pin file (the `Settings` default, never a `.env` override).
DEPLOYMENT_PINS: Path = Settings.model_fields["capability_pins_path"].default
DEPLOYMENTS_ROOT = PROJECT_ROOT / "deployments"
# Non-routable values for the fields `Settings` requires of every selected plane. The stack's
# own database values replace the ones it uses; nothing here reaches a network.
OFFLINE_SETTINGS = {
    "MC_AIENG_DB_URL": "https://offline-placeholder.invalid",
    "MC_AIENG_DB_PUBLISHABLE_KEY": "offline-placeholder",
    "MC_AIENG_DB_SECRET_KEY": "offline-placeholder",
    "MC_BIOTECH_DB_URL": "https://offline-placeholder.invalid",
    "MC_BIOTECH_DB_PUBLISHABLE_KEY": "offline-placeholder",
    "MC_BIOTECH_DB_SECRET_KEY": "offline-placeholder",
    "MC_BIOTECH_GRAPH_URI": "neo4j://offline-placeholder.invalid:7687",
    "MC_BIOTECH_GRAPH_USERNAME": "offline-placeholder",
    "MC_BIOTECH_GRAPH_PASSWORD": "offline-placeholder",
}


def hermetic_pins(path: Path) -> Path:
    """Write the deployment pins without the pins that resolve against host files; return
    ``path``.

    The agent-browser tool pin names an entrypoint under the capability resource owner
    (`workspace://.tools/...`), which only a sibling ``biotech`` checkout carries, and the Skill
    pin a bundle in the local capability bundle store (the git-ignored
    ``.runtime/capability-bundles``), which only a developer checkout carries. Both are verified
    when the workers compose. No stack scenario selects either, so the file drops both on every
    host (the result is the same in CI and on a developer machine). Every other pin (models,
    sandboxes, checkpointers, stores, MCP servers) is unchanged; pin drift and the fail-closed
    entrypoint check stay covered by the capability-pin tests.
    """

    document = json.loads(DEPLOYMENT_PINS.read_text(encoding="utf-8"))
    document["tools"] = []
    document["skills"] = []
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(document, indent=2).encode("utf-8"))
    return path


# The served deterministic model the launch-bindings fixtures bind (`model.wp-cp-040` in the
# deployment pins: vendor `openai`, model id `fixture-model`) and the profile name they use.
FIXTURE_MODEL_PROFILE = "frontier.default"
_FIXTURE_CATALOG_ROW = f"""

# FIXTURE (tests/support/stack.py): the deterministic qualification model the test stack serves.
[[models]]
profile = "{FIXTURE_MODEL_PROFILE}"
vendor = "openai"
model_id = "fixture-model"
context_window_tokens = 128_000
max_input_tokens = 120_000
cost_per_million_input = 1.0
cost_per_million_output = 2.0
supports = ["structured_output", "tool_use"]
structured_output = "tool_auto"
api_surface = "responses"
data_class_ceiling = "internal"
"""


def fixture_deployments(root: Path, application_id: str) -> Path:
    """A deployments root holding the checked-in profile of ``application_id`` whose Model
    Catalog also declares `FIXTURE_MODEL_PROFILE` for the served deterministic model.

    A worker that serves its application composes the nested-run launch author over the
    deployment's catalog, which refuses a launch binding for an undeclared profile or one whose
    served model is another vendor's; this row lets the fixture bindings stay exact."""

    source = DEPLOYMENTS_ROOT / application_id
    target = root / "deployments" / application_id
    shutil.copytree(source, target, dirs_exist_ok=True)
    catalog = target / "models.toml"
    catalog.write_bytes(catalog.read_bytes() + _FIXTURE_CATALOG_ROW.encode("utf-8"))
    return target.parent


def bind_hermetic_environment(
    monkeypatch: pytest.MonkeyPatch, root: Path, values: Mapping[str, str]
) -> None:
    """Make ``values`` the stack's whole configuration for the duration of ``monkeypatch``.

    - `Settings` (the only settings class) stops reading the developer ``.env``: every
      `Settings()` in this process, the API's and the workers' included, then builds from the
      process environment only.
    - Every `Settings` variable inherited from the developer shell is removed, so neither a real
      project ref nor a provider key reaches the composition. Variables a test set itself are
      kept.
    - The capability resource owner is an empty directory under ``root`` and the pin file is
      `hermetic_pins`, unless the test configured either.
    """

    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for name, value in _INHERITED_ENVIRONMENT.items():
        if name.upper() in _SETTINGS_VARIABLES and os.environ.get(name) == value:
            monkeypatch.delenv(name)
    workspace = root / "capability-workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    defaults = {**OFFLINE_SETTINGS, "MISSION_CONTROL_WORKSPACE_ROOT": str(workspace)}
    if "CAPABILITY_PINS_PATH" not in values and "CAPABILITY_PINS_PATH" not in os.environ:
        defaults["CAPABILITY_PINS_PATH"] = str(hermetic_pins(root / "capability-pins.json"))
    for name, value in defaults.items():
        if name not in os.environ:
            monkeypatch.setenv(name, value)
    monkeypatch.delenv("LANGGRAPH_CHECKPOINT_SETUP", raising=False)
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()


def runtime_environment(
    database: CommonDatabase,
    checkpoint_dsn: str,
    root: Path,
    node: str,
    *,
    temporal_port: int,
    request_scope: str,
    identity: str,
) -> dict[str, str]:
    """The explicit configuration of one stack's API and workers on ``database``."""

    app = database.application_id
    return {
        db_env_name(app, "RUNTIME_DSN"): database.dsn("mission_control_runtime"),
        db_env_name(app, "ADMIN_DSN"): database.owner_dsn,
        db_env_name(app, "FAMILY_WRITER_DSN"): database.dsn("mission_control_family_writer"),
        "MISSION_CONTROL_CATALOG_SCOPE": f"mc/{database.installation_id}/{app}/catalog",
        # OC-R4: the installation's application selects its profile (capability owner).
        "MISSION_CONTROL_APPLICATION": app,
        db_env_name(app, "CHECKPOINT_DSN"): checkpoint_dsn,
        "LANGGRAPH_CHECKPOINT_SCHEMA": LANGGRAPH_SCHEMA,
        "TEMPORAL_ADDRESS": f"127.0.0.1:{temporal_port}",
        "TEMPORAL_NAMESPACE": "default",
        "TEMPORAL_TASK_QUEUE": TASK_QUEUE,
        "RUN_CONTROL_TEMPORAL_ENABLED": "1",
        "COORDINATOR_LAUNCH_ENABLED": "1",
        "BOUNDARY_RELAY_REQUEST_SCOPES": json.dumps([request_scope]),
        "ARTIFACT_PAYLOAD_ROOT": str(root / "payloads"),
        "CAPABILITY_BUNDLE_BACKEND": "local",
        "DEEP_AGENT_SANDBOX_WORKSPACE_ROOT": str(root / "workspaces"),
        "WEB_RESEARCH_AGENT_BROWSER_NODE": node,
        "OPERATION_JOURNAL_CLAIMED_BY": f"operation-runtime:{identity}",
        "ASYNC_SUBAGENT_SUBMITTER_IDENTITY": identity,
        "LANGSMITH_TRACING": "false",
        "LANGCHAIN_TRACING_V2": "false",
        "OPENAI_API_KEY": "deterministic-local-model-no-provider-access",
        "S3_BUCKET": "",
    }


@overload
def open_stack(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    signed: Literal[False] = False,
    **inspection: Any,
) -> AbstractAsyncContextManager[ProductionStack]: ...


@overload
def open_stack(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    signed: Literal[True],
    **signed_options: Any,
) -> AbstractAsyncContextManager[ScopedStack]: ...


def open_stack(
    root: Path, monkeypatch: pytest.MonkeyPatch, *, signed: bool = False, **options: Any
) -> AbstractAsyncContextManager[ProductionStack] | AbstractAsyncContextManager[ScopedStack]:
    """The production API and workers on a fresh common database and a local Temporal server.

    ``signed=False`` (inspection mode) yields a `ProductionStack`; its options are
    `technical_override`, `components`, `model_log`, `extra_environment` (set after the stack's
    own configuration, so it wins), `legacy_poison`, `fixture_owner_prerequisites`,
    `migration_paths`, `component_version`, `temporal_port`, `application_id`,
    `knowledge_lane`, `scoped_mission_root`, `retained_database` and
    `serve_application` (the worker names its installation and application, as
    `bootstrap/worker.py` does, over `fixture_deployments`; off by default until the
    other stack users are proven with it).

    ``signed=True`` (signed mode) yields a `ScopedStack`; its options are `saver_proxy`,
    `knowledge_lane`, `knowledge_tools`, `application_id` and `extra_tools`.

    Both are hermetic (`bind_hermetic_environment`).
    """

    if signed:
        return _open_signed_stack(root, monkeypatch, **options)
    return _open_inspection_stack(root=root, monkeypatch=monkeypatch, **options)


# --- Inspection mode: the technical API with an operator principal ----------------

TEMPORAL_PORT = 7341
PRINCIPAL = ControlPlanePrincipal(
    actor_id=OPERATOR,
    roles=frozenset({"operator", "fork_operator", "relay", "auditor", "state_inspector"}),
    tenant_scopes=frozenset({SCOPE}),
    authority_refs=frozenset({"authority:lifecycle"}),
    sponsorship_refs=frozenset({"sponsorship:test"}),
    approval_refs=frozenset({"approval:test"}),
)
STAGE_OBJECTIVE = "Review the draft against the stricter technical checklist."
API_STATE_ATTRIBUTES = (
    "run_control_service",
    "boundary_intervention_service",
    "unit_reconciliation_service",
    "runtime_inspection_service",
    "run_fork_services",
    "admission_policy_registry",
    "run_control_family_admission_registry",
    "control_plane_service",
    "run_launch_service",
    "generic_artifact_submitter",
    "runtime_control",
    "boundary_command_relay",
    "workflow_submitter",
    "fork_patch_policies",
    "temporal_client",
    "temporal_visibility_reader",
    "inspection_checkpoint_reader",
    "inspection_async_child_details",
    "inspection_cursor_key",
    "boundary_command_transport",
    "unit_reconciliation_nudge",
    "unit_reconciliation_verifier",
    "family_liability_hints",
    "async_child_usage_reconciliation",
)


@dataclass
class ProductionStack:
    settings: Settings
    env: WorkflowEnvironment
    client: Client
    owner_pool: asyncpg.Pool
    worker_pool: asyncpg.Pool
    control_plane: ControlPlaneService
    technical: TechnicalBinding
    composition: WorkerActivityComposition
    factory: ProductionWorkerActivityCompositionFactory
    http: httpx.AsyncClient
    payload_root: Path
    temporal_db: Path
    model_log: list[dict[str, Any]] = field(default_factory=list)
    worker_stack: AsyncExitStack = field(default_factory=AsyncExitStack)
    worker_queues: tuple[str, ...] = ()
    database: CommonDatabase | None = None
    temporal_port: int = TEMPORAL_PORT

    async def restart_temporal(self) -> None:
        """Stop the dev server and start it again on the same port and database file."""

        await self.env.shutdown()
        # No Search Attributes at start: the deployment's administrative step registers them
        # (REQ-CP-EXEC-015), and the database file keeps them across the restart.
        self.env = await start_local(self.temporal_db, port=self.temporal_port)


def _reset_api_state() -> None:
    for name in API_STATE_ATTRIBUTES:
        if hasattr(api.state, name):
            delattr(api.state, name)


# --- Facade helpers --------------------------------------------------------------------------


async def _until(predicate: Callable[[], Awaitable[bool]], seconds: float = 180) -> None:
    async with asyncio.timeout(seconds):
        for _ in range(int(seconds * 4)):
            if await predicate():
                return
            await asyncio.sleep(0.25)
    raise AssertionError("condition not reached")


async def _diagnose(stack: ProductionStack, run_id: str) -> str:
    """Compact history tails of a run's root, family and operations plus the model log
    (printed on failure only, before the dev server is torn down)."""

    lines: list[str] = [f"model_log={json.dumps(stack.model_log)[:2000]}"]
    budget = await stack.http.get(
        f"/run-control/v1/runs/{run_id}/budget", params={"request_scope": SCOPE}
    )
    lines.append(f"budget={budget.text[:3000]}")
    async for execution in stack.client.list_workflows(f"BellLabsRunId = '{run_id}'"):
        try:
            history = await stack.client.get_workflow_handle(execution.id).fetch_history()
        except Exception as error:
            lines.append(f"{execution.id}: {type(error).__name__}")
            continue
        lines.append(
            f"{execution.id} [{execution.status}]: "
            + ", ".join(str(event.event_type) for event in history.events[-6:])
        )
        for event in history.events:
            if event.event_type == 10:  # ActivityTaskScheduled: the queue the worker must poll
                attributes = event.activity_task_scheduled_event_attributes
                pollers = await stack.client.workflow_service.describe_task_queue(
                    DescribeTaskQueueRequest(
                        namespace=stack.client.namespace,
                        task_queue=TaskQueue(name=attributes.task_queue.name),
                        task_queue_type=TaskQueueType.Value("TASK_QUEUE_TYPE_ACTIVITY"),
                    )
                )
                lines.append(
                    f"scheduled {attributes.activity_type.name} on {attributes.task_queue.name} "
                    f"(activity pollers: {len(pollers.pollers)})"
                )
            if event.event_type in {3, 14, 24, 26, 42}:  # failed runs, activities and tasks
                lines.append(str(event)[:900])
    return " | ".join(lines)


async def _wait_for(
    stack: ProductionStack, run_id: str, predicate: Callable[[], Awaitable[bool]], seconds: float
) -> None:
    try:
        await _until(predicate, seconds)
    except (TimeoutError, AssertionError) as error:
        raise AssertionError(f"{error}: {await _diagnose(stack, run_id)}") from error


async def _admit(stack: ProductionStack, catalog: TechnicalCatalog, request_id: str) -> str:
    response = await stack.http.post(
        "/run-control/v1/run-requests",
        json=admission_request(catalog, request_id).model_dump(mode="json"),
    )
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "accepted", response.text
    return cast(str, response.json()["run_id"])


async def _launch(stack: ProductionStack, run_id: str, body: dict[str, Any]) -> dict[str, Any]:
    response = await stack.http.post(f"/run-control/v1/runs/{run_id}/launch", json=body)
    assert response.status_code == 202, response.text
    return cast(dict[str, Any], response.json())


async def _run(stack: ProductionStack, run_id: str) -> dict[str, Any]:
    response = await stack.http.get(
        f"/run-control/v1/runs/{run_id}", params={"request_scope": SCOPE}
    )
    assert response.status_code == 200, response.text
    return cast(dict[str, Any], response.json())


async def _holds_wait(stack: ProductionStack, run_id: str) -> bool:
    run = await _run(stack, run_id)
    return any(item["condition_id"] == wait_condition_id(WAIT_ID) for item in run["active_waits"])


async def _terminal(stack: ProductionStack, run_id: str) -> bool:
    return (await _run(stack, run_id))["phase"] == "terminal"


def _command(run_id: str, version: int, command_id: str, action: Any, permission: str) -> dict:
    return LifecycleCommand(
        command_id=command_id,
        idempotency_issuer=OPERATOR,
        request_scope=SCOPE,
        run_id=run_id,
        expected_run_version=version,
        actor=ActorContext(actor_id=OPERATOR, permissions=frozenset({permission})),
        action=action,
        reason=f"RRM-009 qualification {command_id}",
        occurred_at=datetime.now(UTC),
        correlation_id=f"rrm009:{run_id}",
    ).model_dump(mode="json")


async def _send(stack: ProductionStack, run_id: str, command: dict[str, Any]) -> dict[str, Any]:
    response = await stack.http.post(f"/run-control/v1/runs/{run_id}/commands", json=command)
    assert response.status_code == 200, response.text
    return cast(dict[str, Any], response.json())


async def _receipt_states(stack: ProductionStack, run_id: str, command_id: str) -> list[str]:
    response = await stack.http.get(
        f"/run-control/v1/runs/{run_id}/boundary-commands", params={"request_scope": SCOPE}
    )
    assert response.status_code == 200, response.text
    for status in response.json():
        if status["command"]["command_id"] == command_id:
            return [receipt["state"] for receipt in status["receipts"]]
    return []


async def _release_wait(stack: ProductionStack, run_id: str) -> None:
    await _until(lambda: _holds_wait(stack, run_id))
    run = await _run(stack, run_id)
    command_id = f"release:{run_id[:8]}"
    result = await _send(
        stack,
        run_id,
        _command(
            run_id,
            run["version"],
            command_id,
            SatisfyWaitAction(
                condition_id=wait_condition_id(WAIT_ID),
                verification_evidence_ref="evidence:rrm009-review",
            ),
            "workflow_run.observe_wait",
        ),
    )
    assert result["reason_code"] == "accepted_pending_application", result

    async def applied() -> bool:
        return (await _receipt_states(stack, run_id, command_id))[-1:] == ["applied"]

    await _until(applied)


async def _visible(client: Client, query: str, expected: int) -> int:
    """The Visibility count once it reaches `expected`, or the last count after 60 s."""

    count = -1
    for _ in range(240):
        count = (await client.count_workflows(query)).count
        if count == expected:
            return count
        await asyncio.sleep(0.25)
    return count


async def _replay(client: Client, workflow_ids: list[str]) -> int:
    replayer = Replayer(
        workflows=[
            BellLabsRunWorkflow,
            StageGraphWorkflow,
            GoalDirectedWorkflow,
            OperationWorkflow,
        ],
        workflow_runner=coordinator_workflow_runner(),
    )
    events = 0
    for workflow_id in workflow_ids:
        history = await client.get_workflow_handle(workflow_id).fetch_history()
        await replayer.replay_workflow(history)
        events += len(history.events)
    return events


async def _operation_payloads(stack: ProductionStack, run_id: str) -> list[dict[str, Any]]:
    """The digest-bound output payloads of the run's journaled settlements.

    Read exactly as the journal restores them: the settlement row's result manifest address,
    then the manifest's output payload address, both verified by the payload store.
    """

    store = FilesystemArtifactPayloadStore(stack.payload_root)
    async with stack.owner_pool.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT result_manifest_ref, result_manifest_digest, result_manifest_size_bytes
            FROM (
                SELECT DISTINCT ON (s.claim_key) s.*
                FROM mission_control.operation_settlement s
                JOIN mission_control.operation_claim c
                  ON (c.installation_id, c.application_id, c.tenant_id, c.claim_key)
                   = (s.installation_id, s.application_id, s.tenant_id, s.claim_key)
                WHERE c.run_key = $1
                ORDER BY s.claim_key, s.settlement_revision DESC
            ) latest
            WHERE result_manifest_ref IS NOT NULL
            ORDER BY settled_at
            """,
            run_id,
        )
    payloads: list[dict[str, Any]] = []
    for row in rows:
        manifest = json.loads(
            await store.retrieve(
                ArtifactPayloadAddress(
                    object_ref=row["result_manifest_ref"],
                    content_digest=row["result_manifest_digest"],
                    size_bytes=row["result_manifest_size_bytes"],
                )
            )
        )
        if manifest.get("output_payload_ref") is None:
            continue
        payloads.append(
            json.loads(
                await store.retrieve(
                    ArtifactPayloadAddress(
                        object_ref=manifest["output_payload_ref"],
                        content_digest=manifest["output_payload_digest"],
                        size_bytes=manifest["output_payload_size_bytes"],
                    )
                )
            )
        )
    return payloads


def _pinned_summary(stack: ProductionStack) -> dict[str, Any]:
    """The worker's mounted pins by digest (the full disclosure is in the factory)."""

    assert stack.factory.operation is not None
    disclosure = stack.factory.operation.capabilities.disclosure()
    return {
        "mcp_servers": {
            item["server_id"]: {
                "module_digest": item["module_digest"],
                "schema_digest": item["schema_digest"],
                "tools": len(item["tools"]),
                "credential_ref": item["credential_ref"],
            }
            for item in cast(list[dict[str, Any]], disclosure["mcp_servers"])
        },
        "skills": {
            item["skill_name"]: item["bundle_digest"]
            for item in cast(list[dict[str, Any]], disclosure["skills"])
        },
        "tools": {
            item["tool_name"]: item["entrypoint_digest"]
            for item in cast(list[dict[str, Any]], disclosure["tools"])
        },
        "checkpointer_digests": disclosure["checkpointer_digests"],
        "store_digests": disclosure["store_digests"],
    }


def _lineages(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        event["capability_lineage"]
        for payload in payloads
        for event in payload.get("event_payloads", ())
        if "capability_lineage" in event
    ]


async def _saver_checkpoints(pool: asyncpg.Pool) -> int:
    async with pool.acquire() as connection:
        return int(
            await connection.fetchval(f"SELECT count(*) FROM {LANGGRAPH_SCHEMA}.checkpoints")
        )


def _calls(stack: ProductionStack, run_id: str) -> dict[str, dict[str, int]]:
    calls: dict[str, dict[str, int]] = {}
    for item in stack.model_log:
        if item["run_id"] != run_id:
            continue
        per_operation = calls.setdefault(item["operation"], {"parent": 0, "child": 0})
        per_operation[item["model"]] += 1
    return calls


# --- Durable outputs through the generic artifact path --------------------------------------


async def promote_generic_artifact(stack: ProductionStack) -> tuple[str, dict[str, Any]]:
    """One governed operation through `POST /runs/{run_id}/operations` (GenericArtifactWorkflow:
    `operation.execute`, candidate capture, `artifact.promote`); returns the run and result.
    Shared by the filesystem and the S3 object-store qualifications."""

    catalog = await publish_technical_catalog(
        stack.control_plane, family="StageGraph", now=datetime.now(UTC)
    )
    run_id = await _admit(stack, catalog, "rrm009-artifact-run")
    run = await _run(stack, run_id)
    started = await _send(
        stack,
        run_id,
        _command(
            run_id, run["version"], f"start:{run_id[:8]}", StartAction(), "workflow_run.start"
        ),
    )
    assert started["status"] == "accepted"
    unit = stage_unit(
        request_scope=SCOPE,
        run_id=run_id,
        operation_id=(
            "execution-epoch:1:stage:report:mapped:none:workflow-cycle:0:stage-cycle:0:slot:default"
        ),
        stage_id="report",
    )
    reservation_id = f"reservation:{unit.unit_key}"
    run = await _run(stack, run_id)
    reserved = await _send(
        stack,
        run_id,
        _command(
            run_id,
            run["version"],
            f"reserve:{run_id[:8]}",
            ReserveBudgetAction(
                reservation_id=reservation_id, amounts={"tokens.total": 40, "model.turns": 8}
            ),
            "workflow_run.reserve_budget",
        ),
    )
    assert reserved["status"] == "accepted"
    template = stage_templates(stack.technical, catalog)["draft/execute/default"]
    workspace = template.workspace.model_copy(
        update={
            "namespace_id": f"workspace-namespace:{run_id}",
            "workspace_id": f"workspace:{run_id}:report",
        }
    )
    revision = reserved["resulting_run_version"]
    deep_binding = bind_unit(
        cast(Any, DeepAgentExecutionBinding.carried_by(template)),
        unit,
        control_revision=revision,
        reservation_id=reservation_id,
        workspace=workspace,
        erc_digest=catalog.erc.digest,
    )
    operation = OperationExecutionRequest.model_validate(
        {
            **template.model_dump(mode="python"),
            "identity": OperationAttemptIdentity(
                run_id=run_id,
                operation_id=unit.semantic_operation_id,
                operation_attempt=unit.semantic_attempt,
            ),
            "effective_configuration_digest": catalog.erc.digest,
            "run_control_revision": revision,
            "workspace": workspace,
            **lane_fields(deep_binding),
            "runtime_unit": unit,
            "budget_reservation_id": reservation_id,
            "budget_limits": {"tokens.total": 40, "model.turns": 8},
            "requested_at": datetime.now(UTC),
            "idempotency_key": f"rrm009-artifact:{unit.unit_key}",
        }
    )
    submission = GenericArtifactWorkflowRequest(
        request_scope=SCOPE,
        run_id=run_id,
        operation=operation,
        promotion=ArtifactPromotionPlan(
            namespace_id=workspace.namespace_id,
            workspace_id=workspace.workspace_id,
            output_slot="output",
            logical_path=REPORT_PATH,
            owner=WorkspaceOwner(kind=WorkspaceOwnerKind.STAGE, owner_id="stage:draft"),
            permission_ref="permission:rrm009",
            permission_outcome="allowed",
            output_contract_ref=operation.operation_contract_ref,
        ),
    )
    response = await stack.http.post(
        f"/run-control/v1/runs/{run_id}/operations", json=submission.model_dump(mode="json")
    )
    assert response.status_code == 201, response.text
    result = cast(dict[str, Any], response.json())
    assert result["operation"]["status"] == "completed"
    artifact = result["artifact"]
    assert artifact["status"] == "admitted"
    assert artifact["durable_reference"].startswith(f"artifact://{SCOPE}/{run_id}/")
    return run_id, result


# --- Canonical mission_control evidence --------------------------------------------------------


def _scoped(alias: str) -> str:
    return (
        f"{alias}.installation_id = $1 AND {alias}.application_id = $2 AND {alias}.tenant_id = $3"
    )


async def canonical_evidence(
    stack: ProductionStack | asyncpg.Pool,
    run_key: str,
    *,
    request_scope: str = SCOPE,
    units: bool = True,
    children: bool = False,
    artifacts: bool = False,
) -> dict[str, Any]:
    """Assert the run's canonical `mission_control` rows exist and link; return their ids and
    per-table counts (ids and scopes only, never payload contents).

    Read through the owner connection once the scenario settled: mission, mission_revision,
    definition_snapshot and compiled_program behind the mission_run; activations and
    attempts of the run's units; operation_intent with exactly one terminal
    operation_receipt per settled claim; the mission's event sequence contiguous from 1 with
    its outbox rows; subordinate executions of hosted children; artifacts the run produced.
    """

    scope = parse_request_scope(request_scope)
    key = (scope.installation_id, scope.application_id, scope.tenant_id)
    pool = stack if isinstance(stack, asyncpg.Pool) else stack.owner_pool
    async with pool.acquire() as connection:
        run = await connection.fetchrow(
            f"""
            SELECT r.run_id, r.mission_id, r.revision_id, r.lifecycle, r.terminal_outcome,
                   (SELECT count(*) FROM mission_control.compiled_program p
                     WHERE {_scoped("p")} AND p.revision_id = r.revision_id) AS programs,
                   (SELECT count(*) FROM mission_control.definition_snapshot d
                     WHERE {_scoped("d")}
                       AND d.definition_snapshot_id = rev.definition_snapshot_id) AS snapshots
            FROM mission_control.mission_run r
            JOIN mission_control.mission m
              ON (m.installation_id, m.application_id, m.tenant_id, m.mission_id)
               = (r.installation_id, r.application_id, r.tenant_id, r.mission_id)
            JOIN mission_control.mission_revision rev
              ON (rev.installation_id, rev.application_id, rev.tenant_id, rev.revision_id)
               = (r.installation_id, r.application_id, r.tenant_id, r.revision_id)
             AND rev.mission_id = r.mission_id
            WHERE {_scoped("r")} AND r.run_key = $4
            """,
            *key,
            run_key,
        )
        assert run is not None, f"no canonical mission_run for {run_key}"
        assert run["programs"] >= 1 and run["snapshots"] == 1, dict(run)
        run_id, mission_id = run["run_id"], run["mission_id"]
        activations = await connection.fetch(
            f"""SELECT a.activation_id FROM mission_control.activation a
                WHERE {_scoped("a")} AND a.run_id = $4 ORDER BY a.activation_id""",
            *key,
            run_id,
        )
        attempts = await connection.fetch(
            f"""SELECT t.attempt_id, t.activation_id FROM mission_control.attempt t
                WHERE {_scoped("t")} AND t.run_id = $4 ORDER BY t.attempt_id""",
            *key,
            run_id,
        )
        activation_ids = {row["activation_id"] for row in activations}
        assert all(row["activation_id"] in activation_ids for row in attempts)
        if units:
            assert activations and attempts, (run_key, len(activations), len(attempts))
        intents = await connection.fetch(
            f"""
            SELECT i.operation_intent_id, i.state, i.activation_id, c.status AS claim_status,
                   (SELECT count(*) FROM mission_control.operation_receipt o
                     WHERE {_scoped("o")}
                       AND o.operation_intent_id = i.operation_intent_id) AS receipts
            FROM mission_control.operation_intent i
            LEFT JOIN mission_control.operation_claim c
              ON (c.installation_id, c.application_id, c.tenant_id, c.operation_intent_id)
               = (i.installation_id, i.application_id, i.tenant_id, i.operation_intent_id)
            WHERE {_scoped("i")} AND i.run_id = $4
            """,
            *key,
            run_id,
        )
        settled = [row for row in intents if row["claim_status"] == "settled"]
        assert all(row["receipts"] == 1 for row in settled), [dict(row) for row in intents]
        assert all(row["receipts"] <= 1 for row in intents), [dict(row) for row in intents]
        assert all(
            row["activation_id"] is None or row["activation_id"] in activation_ids
            for row in intents
        )
        sequence = [
            row["seq"]
            for row in await connection.fetch(
                f"""SELECT e.seq FROM mission_control.mission_event e
                    WHERE {_scoped("e")} AND e.mission_id = $4 ORDER BY e.seq""",
                *key,
                mission_id,
            )
        ]
        assert sequence and sequence == list(range(1, len(sequence) + 1)), sequence
        outbox = int(
            await connection.fetchval(
                f"""SELECT count(*) FROM mission_control.outbox o
                    JOIN mission_control.mission_event e
                      ON (e.installation_id, e.application_id, e.tenant_id, e.event_id)
                       = (o.installation_id, o.application_id, o.tenant_id, o.event_id)
                    WHERE {_scoped("o")} AND e.mission_id = $4""",
                *key,
                mission_id,
            )
        )
        assert outbox >= 1, f"no outbox rows for {run_key}"
        subordinates = await connection.fetch(
            f"""SELECT s.subordinate_id, s.execution_kind
                FROM mission_control.subordinate_execution s
                WHERE {_scoped("s")} AND s.run_id = $4 ORDER BY s.subordinate_id""",
            *key,
            run_id,
        )
        if children:
            assert any(row["execution_kind"] == "async" for row in subordinates), run_key
        produced = await connection.fetch(
            f"""SELECT a.artifact_id FROM mission_control.artifact a
                WHERE {_scoped("a")} AND a.producer_run_id = $4 ORDER BY a.artifact_id""",
            *key,
            run_id,
        )
        if artifacts:
            assert produced, f"no artifact produced by {run_key}"
        settlements = int(
            await connection.fetchval(
                f"""SELECT count(*) FROM mission_control.operation_settlement s
                    JOIN mission_control.operation_claim c
                      ON (c.installation_id, c.application_id, c.tenant_id, c.claim_key)
                       = (s.installation_id, s.application_id, s.tenant_id, s.claim_key)
                    WHERE {_scoped("s")} AND c.run_key = $4""",
                *key,
                run_key,
            )
        )
        budget_entries = int(
            await connection.fetchval(
                f"""SELECT count(*) FROM mission_control.budget_entry b
                    WHERE {_scoped("b")} AND b.run_id = $4""",
                *key,
                run_id,
            )
        )
    return {
        "request_scope": request_scope,
        "run_key": run_key,
        "run_id": str(run_id),
        "mission_id": str(mission_id),
        "revision_id": str(run["revision_id"]),
        "lifecycle": run["lifecycle"],
        "terminal_outcome": run["terminal_outcome"],
        "activation_ids": [str(row["activation_id"]) for row in activations],
        "attempt_ids": [str(row["attempt_id"]) for row in attempts],
        "subordinate_ids": [str(row["subordinate_id"]) for row in subordinates],
        "artifact_ids": [str(row["artifact_id"]) for row in produced],
        "counts": {
            "compiled_program": int(run["programs"]),
            "activation": len(activations),
            "attempt": len(attempts),
            "operation_intent": len(intents),
            "operation_receipt": sum(int(row["receipts"]) for row in intents),
            "settled_claims": len(settled),
            "operation_settlement": settlements,
            "mission_event": len(sequence),
            "outbox_for_mission_events": outbox,
            "budget_entry": budget_entries,
            "subordinate_execution": len(subordinates),
            "artifact": len(produced),
        },
    }


def record_parity_trace(name: str, evidence: dict[str, Any]) -> None:
    """Merge one scenario's canonical evidence (ids, scopes, counts) into the JSON file named
    by ``MISSION_CONTROL_PARITY_TRACE`` (no-op when unset)."""

    target = os.environ.get("MISSION_CONTROL_PARITY_TRACE")
    if not target:
        return
    path = Path(target)
    try:
        current = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except json.JSONDecodeError:
        current = {}
    current[name] = {"recorded_at": datetime.now(UTC).isoformat(), **evidence}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, indent=2, sort_keys=True, default=str), encoding="utf-8")


def _application_binding(database: CommonDatabase) -> ApplicationBinding:
    """Bind the ordinary mission root to this verified disposable installation."""
    return ApplicationBinding.seal(
        application_id=database.application_id,
        installation_id=database.installation_id,
        binding_version="1",
        supabase_project_ref=database.project_ref,
        database_secret_ref=db_env_name(database.application_id, "RUNTIME_DSN"),
        accepted_issuers={"https://overnight-evidence.invalid"},
        accepted_audiences={"mission-control"},
        required_component_version=COMPONENT_VERSION,
    )


async def start_local(database: Path, *, port: int = TEMPORAL_PORT) -> WorkflowEnvironment:
    configured_cli = os.environ.get("MISSION_CONTROL_TEMPORAL_CLI")
    sdk_cli = Path(tempfile.gettempdir()) / f"temporal-sdk-python-{version('temporalio')}.exe"
    existing = configured_cli or (str(sdk_cli) if sdk_cli.is_file() else None)
    async with asyncio.timeout(60):
        return await WorkflowEnvironment.start_local(
            port=port,
            dev_server_existing_path=existing,
            dev_server_extra_args=["--db-filename", str(database)],
            dev_server_log_level="error",
        )


async def _fresh_database(
    *,
    legacy_poison: bool = False,
    migration_paths: list[Path] | None = None,
    component_version: str = COMPONENT_VERSION,
    application_id: str = "biotech",
) -> tuple[CommonDatabase, str]:
    """A fresh common-component database and its checkpointer-only runtime DSN."""

    database = await create_common_database(
        legacy_poison=legacy_poison,
        paths=migration_paths,
        component_version=component_version,
        application_id=application_id,
    )
    try:
        checkpoint_dsn = await provision_runtime(database)
    except BaseException:
        await drop_common_database(database)
        raise
    return database, checkpoint_dsn


async def _release_database(database: CommonDatabase) -> None:
    if os.environ.get("MISSION_CONTROL_E2E_KEEP_DATABASE") == "1":
        print(f"E2E: kept database {database.name} for inspection", flush=True)
        return
    await drop_common_database(database)


@asynccontextmanager
async def _open_inspection_stack(
    *,
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    technical_override: TechnicalBinding | None = None,
    components: DeploymentCapabilityComponents | None = None,
    model_log: list[dict[str, Any]] | None = None,
    extra_environment: dict[str, str] | None = None,
    legacy_poison: bool = False,
    fixture_owner_prerequisites: bool = False,
    migration_paths: list[Path] | None = None,
    component_version: str = COMPONENT_VERSION,
    temporal_port: int = TEMPORAL_PORT,
    application_id: str = "biotech",
    knowledge_lane: KnowledgeLaneFactory | None = None,
    scoped_mission_root: bool = False,
    retained_database: tuple[CommonDatabase, str] | None = None,
    serve_application: bool = False,
) -> AsyncIterator[ProductionStack]:
    request_scope = canonical_scope(application_id=application_id)
    node_executable = shutil.which("node")
    if node_executable is None:
        pytest.fail("pinned technical MCP/browser runtime requires an installed Node executable")
    if retained_database is None:
        database, checkpoint_dsn = await _fresh_database(
            legacy_poison=legacy_poison,
            migration_paths=migration_paths,
            component_version=component_version,
            application_id=application_id,
        )
    else:
        if legacy_poison or migration_paths is not None:
            raise ValueError("retained runtime cannot install or poison a database")
        database, checkpoint_dsn = retained_database
        if database.application_id != application_id or not (root / "temporal.sqlite").is_file():
            raise ValueError("retained runtime application or Temporal custody mismatch")
        monkeypatch.setenv("MISSION_CONTROL_E2E_KEEP_DATABASE", "1")
    owner_pool = None
    try:
        bind_disposable_prerequisites(
            monkeypatch,
            database,
            deterministic_owner_evidence=fixture_owner_prerequisites,
            component_version=component_version,
        )
        dsn = database.owner_dsn
        disposition = "retained" if retained_database is not None else "fresh"
        print(f"E2E: {disposition} common database {database.name} connected", flush=True)
        payload_root = root / "payloads"
        temporal_db = root / "temporal.sqlite"
        environment = {
            **runtime_environment(
                database,
                checkpoint_dsn,
                root,
                node_executable,
                temporal_port=temporal_port,
                request_scope=request_scope,
                identity="mission-control-parity",
            ),
            "BOUNDARY_RELAY_INTERVAL_SECONDS": "1",
        }
        if serve_application:
            environment["MISSION_CONTROL_DEPLOYMENTS_ROOT"] = str(
                fixture_deployments(root, database.application_id)
            )
        bind_hermetic_environment(monkeypatch, root, {**environment, **(extra_environment or {})})
        settings = get_settings()
        technical = technical_override or technical_binding()
        model_log = model_log if model_log is not None else []
        owner_pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
        env = await start_local(temporal_db, port=temporal_port)
    except BaseException:
        if owner_pool is not None:
            await owner_pool.close()
        await _release_database(database)
        get_settings.cache_clear()
        raise
    print("E2E: local Temporal server connected", flush=True)
    _reset_api_state()
    api.state.admission_policy_registry = technical_admission_policies()
    principal = PRINCIPAL.model_copy(update={"tenant_scopes": frozenset({request_scope})})
    api.dependency_overrides[get_control_plane_principal] = lambda: principal
    production = None
    try:
        async with AsyncExitStack() as resources:
            await initialize_run_control_resources(api)
            print("E2E: API PostgreSQL identities verified", flush=True)
            await register_belllabs_search_attributes(env.client, settings.temporal_namespace)
            print("E2E: Temporal search attributes registered", flush=True)
            await compose_runtime_control(
                api,
                settings,
                client=env.client,
                stack=resources,
                fork_patch_policies=ForkPatchPolicyRegistry(),
                application_binding=(
                    _application_binding(database) if scoped_mission_root else None
                ),
            )
            print("E2E: API runtime services composed", flush=True)
            worker_pool = await create_application_postgres_pool(settings)
            resources.push_async_callback(worker_pool.close)
            writer_pool = await create_application_family_writer_pool(settings)
            resources.push_async_callback(writer_pool.close)
            control_plane = ControlPlaneService(
                PostgresDefinitionRepository(
                    worker_pool, catalog_scope=settings.mission_control_catalog_scope or ""
                ),
                ExtensionRegistry(),
                UnavailablePayloadStore(),
                externalize_above_bytes=15_000_000,
            )
            run_control = compose_worker_run_control_service(
                PostgresRunControlRepository(worker_pool, family_writer_pool=writer_pool),
                F1RunConfigurationVerifier(control_plane),
                technical_admission_policies(),
            )
            factory = ProductionWorkerActivityCompositionFactory(
                env.client,
                additional_components=components or technical.components(model_log),
                knowledge_lane=knowledge_lane,
                artifact_validation=StaticArtifactValidationAuthority(
                    permission_outcomes={
                        ("operation:sandbox-agent@1", "permission:rrm009"): "allowed"
                    },
                    check_outcomes={},
                    required_check_ids={},
                ),
                worker_identity=f"mission-control-parity:{os.getpid()}",
                claim_lease=timedelta(seconds=90),
            )
            if serve_application:
                # As `bootstrap/worker.py` does: the worker serves this installation's
                # application, which composes its knowledge or output-submission lane
                # (the receiver authority of a linked transfer) and the nested-run
                # launch author over the deployment's Model Catalog (here
                # `fixture_deployments`, which declares the served fixture model).
                factory.installation_id = str(database.installation_id)
                factory.application_id = database.application_id
            composition = await factory.build(
                settings=settings,
                control_plane=control_plane,
                run_control=run_control,
                postgres_pool=worker_pool,
            )
            print("E2E: production activity factory composed", flush=True)
            assert composition.resources is not None
            resources.push_async_callback(composition.resources.aclose)
            workers = create_production_workers(env.client, settings, composition)
            http = await resources.enter_async_context(
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=api), base_url="http://mission-control"
                )
            )
            production = ProductionStack(
                settings=settings,
                env=env,
                client=env.client,
                owner_pool=owner_pool,
                worker_pool=worker_pool,
                control_plane=control_plane,
                technical=technical,
                composition=composition,
                factory=factory,
                http=http,
                payload_root=payload_root,
                temporal_db=temporal_db,
                model_log=model_log,
                worker_queues=tuple(worker.task_queue for worker in workers.workers),
                database=database,
                temporal_port=temporal_port,
            )
            async with production.worker_stack:
                for worker in workers.workers:
                    await production.worker_stack.enter_async_context(worker)
                print("E2E: production workers polling", flush=True)
                yield production
    finally:
        await close_run_control_resources(api)
        api.dependency_overrides.pop(get_control_plane_principal, None)
        _reset_api_state()
        await owner_pool.close()
        await (production.env if production is not None else env).shutdown()
        get_settings.cache_clear()
        await _release_database(database)


# --- Signed mode: the configured application API behind signed tokens -------------

PORT = 17233


@dataclass
class ScopedStack:
    application: FastAPI
    token: str
    http: httpx.AsyncClient
    client: Client
    services: MissionApplicationServices
    pool: asyncpg.Pool
    binding: technical.TechnicalBinding
    model_log: list[dict[str, Any]]
    scope: str
    owner_pool: asyncpg.Pool
    catalogs: dict[str, technical.TechnicalCatalog] = field(default_factory=dict)
    # WP-TR-3: the maintenance queue (`mc.frames_expire.v1`, the transcript projection) and
    # who serves it in this stack: `production` (the worker set) or `fixture` (see
    # `maintenance_worker`).
    maintenance_queue: str = ""
    maintenance_served_by: str = ""
    # Sprint V SV-16: the worker's composed knowledge lane (None unless one was requested).
    knowledge: Any = None
    # The application the stack serves (`biotech` unless a test selects `ai-engineer`).
    application_id: str = "biotech"


@asynccontextmanager
async def _open_signed_stack(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    saver_proxy: SaverProxy | None = None,
    knowledge_lane: Callable[..., Awaitable[Any]] | None = None,
    knowledge_tools: tuple[Any, ...] = (),
    application_id: str = "biotech",
    extra_tools: dict[str, Any] | None = None,
) -> AsyncIterator[ScopedStack]:
    """The stack on a fresh common database.

    FX-TR-REMOTE (WP-TR-5): with ``saver_proxy`` the LangGraph saver DSN (the
    checkpointer-only login of the fresh database) is pointed at the proxy, which is started
    toward the database's host and port, so both the workers and the API open the saver
    through it; the common Mission Control database stays direct. The proxy is stopped on
    teardown. Without it, the stack is unchanged.
    """

    node = shutil.which("node")
    if node is None:
        pytest.fail("the pinned deterministic MCP/browser component requires local Node")
    common, checkpoint_dsn = await _fresh_database(application_id=application_id)
    try:
        if saver_proxy is not None:
            checkpoint_dsn = await proxied_conninfo(saver_proxy, checkpoint_dsn)
        try:
            async with _compose_signed_stack(
                root,
                monkeypatch,
                common,
                checkpoint_dsn,
                node,
                knowledge_lane=knowledge_lane,
                knowledge_tools=knowledge_tools,
                application_id=application_id,
                extra_tools=extra_tools,
            ) as stack:
                yield stack
        finally:
            if saver_proxy is not None:
                await saver_proxy.stop()
    finally:
        await drop_common_database(common)


async def proxied_conninfo(proxy: SaverProxy, dsn: str) -> str:
    """Start ``proxy`` toward ``dsn``'s host and port; return ``dsn`` rebuilt through it.

    ``dsn`` may be a URI or a keyword conninfo; every key other than ``host`` and ``port``
    (user, password, dbname, ...) is kept. The result is a keyword conninfo, which the
    runtime binding (`runtime_checkpoint_conninfo`) accepts like a URI.
    """

    parts = conninfo_to_dict(dsn)
    host = str(parts.get("host") or "127.0.0.1")
    port = int(parts.get("port") or 5432)
    await proxy.start(host, port)
    return make_conninfo("", **{**parts, "host": "127.0.0.1", "port": proxy.port})


@asynccontextmanager
async def _compose_signed_stack(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    common: CommonDatabase,
    checkpoint_dsn: str,
    node: str,
    *,
    knowledge_lane: Callable[..., Awaitable[Any]] | None = None,
    knowledge_tools: tuple[Any, ...] = (),
    application_id: str = "biotech",
    extra_tools: dict[str, Any] | None = None,
) -> AsyncIterator[ScopedStack]:
    app = application_id
    owner_dsn = common.owner_dsn
    runtime_dsn = common.dsn("mission_control_runtime")
    writer_dsn = common.dsn("mission_control_family_writer")
    installation, tenant = common.installation_id, common.tenants["tenant-1"]
    binding = ApplicationBinding.seal(
        application_id=common.application_id,
        installation_id=installation,
        binding_version="1",
        supabase_project_ref=common.project_ref,
        database_secret_ref="MC_SCOPED_RUNTIME_DSN",
        accepted_issuers={"https://local-qualification.invalid"},
        accepted_audiences={"mission-control"},
        required_component_version=COMPONENT_VERSION,
    )
    scope = common.scope("tenant-1")
    monkeypatch.setattr(technical, "SCOPE", scope)
    environment = {
        **runtime_environment(
            common,
            checkpoint_dsn,
            root,
            node,
            temporal_port=PORT,
            request_scope=scope,
            identity="scoped-proof",
        ),
        "MC_SCOPED_RUNTIME_DSN": runtime_dsn,
        "MC_SCOPED_WRITER_DSN": writer_dsn,
    }
    bind_hermetic_environment(monkeypatch, root, environment)
    settings = get_settings()
    key = RSAKey.generate_key(2048, parameters={"kid": "scoped-proof"})
    public_key_file = root / "public-jwks.json"
    public_key_file.write_text(json.dumps({"keys": [key.as_dict(private=False)]}))
    authentication = ApplicationAuthentication(
        binding=binding,
        issuer="https://local-qualification.invalid",
        audience="mission-control",
        public_jwks_file=public_key_file,
        grants=(
            ActorGrant(
                subject="qualified-operator",
                actor_id=technical.OPERATOR,
                tenant_ids={tenant},
                permissions=(
                    ROLE_PERMISSIONS["operator"]
                    | ROLE_PERMISSIONS["fork_operator"]
                    # P1 turn 4: `state-as-of` (checkpoint summary) and a fork with an
                    # instruction (`workflow_run.control`, P1-A6) are part of the drills.
                    | ROLE_PERMISSIONS["state_inspector"]
                    | {"workflow.result.read", "workflow_run.control"}
                    # 1.4.4 (FX-TR-RECONCILE): `points:reconcile` is the existing reconcile
                    # grant.
                    | {"workflow_run.reconcile_unit"}
                    # WP-TR-2 (FX-TR-HOOK): `cancel` with `urgency: immediate` of active work
                    # (the stop fence) is an admin command.
                    | {"workflow_run.admin"}
                ),
                authority_refs={"authority:lifecycle"},
                sponsorship_refs={"sponsorship:test"},
                approval_refs={"approval:test"},
            ),
        ),
    )
    queues = coordinator_task_queues(settings.temporal_task_queue)
    deployment = MissionDeployment(
        storage_mode="production_common",
        max_request_bytes=1_000_000,
        applications=(
            ApplicationDeployment(
                authentication=authentication,
                family_writer_secret_ref="MC_SCOPED_WRITER_DSN",
                temporal=TemporalDeployment(
                    address=settings.temporal_address,
                    namespace=settings.temporal_namespace,
                    root_task_queue=queues.stagegraph,
                    stagegraph_task_queue=queues.stagegraph,
                    goal_directed_task_queue=queues.goal_directed,
                ),
            ),
        ),
    )
    family_admissions = FamilyAdmissionRegistry()
    configure_goal_directed_family_admissions(family_admissions)
    register_stagegraph_family_mutations(family_admissions)
    application = create_application(
        deployment,
        runtime_options={
            app: RuntimeOptions(
                technical.technical_admission_policies(),
                ExtensionRegistry(),
                UnavailablePayloadStore(),
                family_admissions=family_admissions,
                # WP-TR-2 (FX-TR-STEP): `GET transcript?full=true` reads promoted frame bodies
                # through the tenant's `GrantedArtifactBodyReader`, which the API composes only
                # over a payload store (`bootstrap/api.py`, MP-13). The same filesystem store
                # the in-process workers promote into (`ARTIFACT_PAYLOAD_ROOT`).
                artifact_payloads=artifact_payload_store(settings),
            )
        },
    )
    env = await start_local(root / "temporal.sqlite", port=PORT)
    print("SCOPED E2E: disposable PostgreSQL and cached Temporal ready", flush=True)
    try:
        await register_belllabs_search_attributes(env.client, settings.temporal_namespace)
        async with AsyncExitStack() as resources:
            await resources.enter_async_context(application.router.lifespan_context(application))
            services = application.state.mission_control_compositions[(installation, app, tenant)]
            pool = await asyncpg.create_pool(runtime_dsn, min_size=1, max_size=5)
            resources.push_async_callback(pool.close)
            owner_pool = await asyncpg.create_pool(owner_dsn, min_size=1, max_size=2)
            resources.push_async_callback(owner_pool.close)
            model_log: list[dict[str, Any]] = []
            binding_assets = technical.technical_binding()
            if knowledge_tools:
                binding_assets = replace(binding_assets, knowledge_tools=knowledge_tools)
            if extra_tools:
                binding_assets = replace(binding_assets, extra_tools=dict(extra_tools))
            factory = ProductionWorkerActivityCompositionFactory(
                env.client,
                additional_components=binding_assets.components(model_log),
                worker_identity=f"mission-control-scoped-proof:{os.getpid()}",
                claim_lease=timedelta(seconds=90),
                knowledge_lane=knowledge_lane,
            )
            composition = await factory.build(
                settings=settings,
                control_plane=services.control_plane,
                run_control=services.run_control,
                postgres_pool=pool,
            )
            assert composition.resources is not None
            resources.push_async_callback(composition.resources.aclose)
            workers = create_production_workers(env.client, settings, composition)
            for worker in workers.workers:
                await resources.enter_async_context(worker)
            maintenance_queue = maintenance_task_queue(settings.temporal_task_queue)
            maintenance = maintenance_worker(
                env.client, maintenance_queue, workers, pool, composition
            )
            if maintenance is not None:
                await resources.enter_async_context(maintenance)
                start_transcript_projection_relay(
                    resources,
                    pool=pool,
                    client=env.client,
                    task_queue=maintenance_queue,
                    request_scopes=[scope],
                    lease_owner="scoped-proof-transcript-projection",
                    graceful_shutdown_seconds=5.0,
                )
            token = jwt.encode(
                {"alg": "RS256", "kid": "scoped-proof"},
                {
                    "iss": authentication.issuer,
                    "aud": authentication.audience,
                    "sub": "qualified-operator",
                    # Tracing Stage 2: live runs and their reads outlast 30 minutes.
                    "exp": int(time.time())
                    + int(os.environ.get("SCOPED_PROOF_TOKEN_SECONDS", "1800")),
                    "app_metadata": {"application_id": app, "tenant_id": str(tenant)},
                },
                key,
            )
            http = await resources.enter_async_context(
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=application),
                    base_url="http://scoped-proof",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=45,
                )
            )
            print("SCOPED E2E: signed API and actual production workers started", flush=True)
            yield ScopedStack(
                application,
                token,
                http,
                env.client,
                services,
                pool,
                binding_assets,
                model_log,
                scope,
                owner_pool,
                maintenance_queue=maintenance_queue,
                maintenance_served_by="production" if maintenance is None else "fixture",
                knowledge=factory.knowledge,
                application_id=app,
            )
    finally:
        await env.shutdown()
        get_settings.cache_clear()


@asynccontextmanager
async def signed_read_api(stack: ProductionStack) -> AsyncIterator[httpx.AsyncClient]:
    """A signed, read-only public API over an inspection-mode stack's own database.

    Unlike signed mode (which composes its own database and workers), this attaches the
    configured application (`bootstrap.api.create_application`, ``production_common``) to the
    running `ProductionStack`: production authentication and services, an observer whose only
    grants are ``workflow_run.read`` and ``workflow.result.read``, and the stack's promoted
    artifact payloads. No second worker, run launcher or boundary relay is started.
    """

    database = stack.database
    assert database is not None
    tenant = database.tenants["tenant-1"]
    application_id = database.application_id
    issuer = "https://overnight-evidence.invalid"
    binding = ApplicationBinding.seal(
        application_id=application_id,
        installation_id=database.installation_id,
        binding_version="1",
        supabase_project_ref=database.project_ref,
        database_secret_ref=db_env_name(application_id, "RUNTIME_DSN"),
        accepted_issuers={issuer},
        accepted_audiences={"mission-control"},
        required_component_version=COMPONENT_VERSION,
    )
    key = RSAKey.generate_key(2048, parameters={"kid": "overnight-observer"})
    key_file = stack.payload_root.parent / "overnight-observer-public.json"
    key_file.write_text(json.dumps({"keys": [key.as_dict(private=False)]}), encoding="utf-8")
    authentication = ApplicationAuthentication(
        binding=binding,
        issuer=issuer,
        audience="mission-control",
        public_jwks_file=key_file,
        grants=(
            ActorGrant(
                subject="evidence-observer",
                actor_id="overnight-evidence-observer",
                tenant_ids={tenant},
                permissions={"workflow_run.read", "workflow.result.read"},
            ),
        ),
    )
    payloads = artifact_payload_store(stack.settings)
    assert isinstance(payloads, FilesystemArtifactPayloadStore), "fixture requires local custody"
    application = create_application(
        MissionDeployment(
            storage_mode="production_common",
            max_request_bytes=1_000_000,
            applications=(ApplicationDeployment(authentication=authentication),),
        ),
        runtime_options={
            application_id: RuntimeOptions(
                technical_admission_policies(),
                ExtensionRegistry(),
                UnavailablePayloadStore(),
                artifact_payloads=payloads,
            )
        },
    )
    token = jwt.encode(
        {"alg": "RS256", "kid": "overnight-observer"},
        {
            "iss": issuer,
            "aud": "mission-control",
            "sub": "evidence-observer",
            "exp": int(time.time()) + 1800,
            "app_metadata": {"application_id": application_id, "tenant_id": str(tenant)},
        },
        key,
    )
    async with AsyncExitStack() as resources:
        # The public API normally owns subscription delivery. This read-only observer must not
        # start another relay beside the existing workflow stack. Restore the process
        # environment immediately after startup.
        with patch.dict(os.environ, {"MISSION_CONTROL_SUBSCRIPTION_RELAY": "0"}):
            await resources.enter_async_context(application.router.lifespan_context(application))
        client = await resources.enter_async_context(
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application),
                base_url=f"http://overnight-observer/v1/applications/{application_id}/",
                headers={"Authorization": f"Bearer {token}"},
                timeout=45,
            )
        )
        yield client


def maintenance_worker(
    client: Client,
    queue: str,
    workers: ProductionWorkerSet,
    pool: asyncpg.Pool,
    composition: Any | None = None,
) -> Worker | None:
    """WP-TR-3 (FX-TR-RETAIN; FX-TR-STEP on the projection): the maintenance-queue worker.

    The `missionctl worker` entrypoint starts one (`bootstrap/worker.py:542-560`:
    `mc.frames_expire.v1` with `FramesExpireActivities` over the runtime pool) but
    `create_production_workers` does not, so the scoped stack had no worker on the queue and a
    retention run or a projection trigger would wait forever. This serves the retention
    workflow over the stack's runtime pool. It returns None when the production worker set
    already serves the queue (the source stream then registered the retention and the
    projection workflows there, and a second worker on the queue would poll projection tasks
    it cannot run). The transcript projection workflow itself is the source stream's: when it
    is not registered on this worker, FX-TR-STEP's "projected without a refresh" line fails
    and says so.
    """

    if any(worker.task_queue == queue for worker in workers.workers):
        return None
    return Worker(
        client,
        task_queue=queue,
        workflows=[FramesExpireWorkflow, TranscriptProjectionWorkflow, ForkSeedWorkflow],
        activities=[
            FramesExpireActivities(
                PostgresFrameRetention(
                    pool,
                    actor_ref="scoped-proof-frames-expire",
                    projectors=transcript_projectors(pool),
                )
            ).expire,
            # WP-TR-5 (P6.1): the cognitive seed's copy over the workers' own savers.
            ForkSeedActivities(
                lambda: getattr(composition, "time_travel", None) if composition else None
            ).copy,
            # WP-TR-3 (TR-D10): the persisted Transcript projection, released per
            # settlement by the outbox relay the stack starts beside this worker.
            TranscriptProjectionActivities(transcript_projectors(pool)).project,
        ],
        workflow_runner=coordinator_workflow_runner(),
    )


async def close_saver(stack: ScopedStack) -> list[str]:
    """FX-TR-STEP ("all read with the saver pool closed"): close the API process's pinned
    LangGraph saver and return what was closed.

    `bootstrap/api.py::compose_time_travel` opens one `StandalonePersistenceLifespan` over the
    runtime DSN and hands its `AsyncPostgresSaver` to `DeepAgentsTimeTravel` (behind
    `app.state.time_travel_registry`) and to `LangGraphCheckpointHistoryReader`
    (`app.state.inspection_checkpoint_reader`); neither exposes the saver publicly, so this
    reads their `_checkpointers` maps and closes each distinct saver's `conn` (psycopg
    `AsyncConnection`). The workers' own saver (`composition.resources`) stays open, so the
    run itself is unaffected; `state-as-of` and `points:reconcile` lose their saver, while the
    transcript and points routes read the common database only. The lifespan exit closes the
    connection again at teardown, which psycopg accepts.
    """

    state = stack.application.state
    holders: list[Any] = []
    registry = getattr(state, "time_travel_registry", None)
    if registry is not None and registry.supports("deep_agents"):
        holders.append(registry.lane("deep_agents"))
    reader = getattr(state, "inspection_checkpoint_reader", None)
    if reader is not None:
        holders.append(reader)
    savers: dict[int, Any] = {}
    for holder in holders:
        for saver in (getattr(holder, "_checkpointers", None) or {}).values():
            savers.setdefault(id(saver), saver)
    closed: list[str] = []
    for saver in savers.values():
        connection = getattr(saver, "conn", None)
        close = getattr(connection, "close", None)
        if close is None:
            continue
        await close()
        closed.append(f"{type(saver).__name__}.conn:{type(connection).__name__}")
    return closed


async def until(predicate: Callable[[], Awaitable[bool]], seconds: float = 180) -> None:
    async with asyncio.timeout(seconds):
        for _ in range(int(seconds * 4)):
            if await predicate():
                return
            await asyncio.sleep(0.25)
    raise AssertionError("runtime condition did not become true")


async def inspect(stack: ScopedStack, run_id: str) -> dict[str, Any]:
    response = await stack.http.get(
        f"/v1/applications/{stack.application_id}/runs/{run_id}/inspection"
    )
    assert response.status_code == 200, response.text
    return response.json()


async def prepare_run(stack: ScopedStack, family: str) -> tuple[str, dict[str, Any]]:
    """Admit a run over HTTP and persist its native templates: (run id, launch body).

    ``family`` is `StageGraph`, `GoalDirected` or the FX-TR tag `StageGraphTracing`
    (`technical.TRACING_FAMILY`): the four-stage cycling blueprint, launched as a Stage Graph.
    """

    catalog = stack.catalogs.get(family)
    if catalog is None:
        catalog = await technical.publish_technical_catalog(
            stack.services.control_plane,
            family=family,
            now=datetime.now(UTC),
        )
        stack.catalogs[family] = catalog
    request = technical.admission_request(catalog, str(uuid4())).model_dump(mode="json")
    for input_field in (
        "schema_version",
        "request_scope",
        "idempotency_issuer",
        "actor",
        "requested_at",
        "correlation_id",
        "causation_id",
    ):
        request.pop(input_field, None)
    admission = await stack.http.post(
        f"/v1/applications/{stack.application_id}/run-requests", json=request
    )
    assert admission.status_code == 201, admission.text
    run_id = admission.json()["admission"]["run_id"]
    binding_ref = f"semantic-input:scoped-proof:{run_id}"
    if family in technical.STAGE_FAMILIES:
        await PostgresStageGraphOperationTemplateRepository(stack.pool).persist_templates(
            request_scope=stack.scope,
            semantic_input_binding_ref=binding_ref,
            templates={
                name: value.model_copy(update={"request_scope": stack.scope})
                for name, value in technical.stage_templates(stack.binding, catalog).items()
            },
            recorded_at=datetime.now(UTC),
        )
        family_input = {
            "stagegraph": asdict(technical.stage_input(catalog, run_id, binding_ref, 1))
        }
    else:
        templates = {
            name: value.model_copy(update={"request_scope": stack.scope})
            for name, value in technical.goal_templates(stack.binding, catalog).items()
        }
        await PostgresGoalDirectedDocumentRepository(stack.pool).persist_templates(
            request_scope=stack.scope,
            semantic_input_binding_ref=binding_ref,
            executor=templates["executor"],
            verifier=templates["verifier"],
            recorded_at=datetime.now(UTC),
        )
        family_input = {
            "goal_directed": asdict(
                technical.goal_input(
                    catalog,
                    run_id,
                    binding_ref,
                    1,
                    "Produce one independently verified technical record.",
                )
            )
        }
    # The launch body's family is the workflow family; the FX-TR tag is a fixture selector.
    launch_family = "StageGraph" if family in technical.STAGE_FAMILIES else family
    return run_id, {"family": launch_family, **family_input}


async def admit_and_launch(stack: ScopedStack, family: str) -> tuple[str, str]:
    run_id, body = await prepare_run(stack, family)
    launched = await stack.http.post(
        f"/v1/applications/{stack.application_id}/runs/{run_id}/launch", json=body
    )
    assert launched.status_code == 202, launched.text
    workflow_id = launched.json()["workflow_id"]
    assert workflow_id == mission_root_id(stack.scope, run_id)
    print(f"SCOPED E2E: admitted and launched {family}", flush=True)
    return run_id, workflow_id


@asynccontextmanager
async def serve_loopback(application: FastAPI) -> AsyncIterator[str]:
    """Serve the started application over real HTTP on a free loopback port; yields its URL.

    The stack already entered the application lifespan, so uvicorn serves with ``lifespan="off"``.
    """

    server = uvicorn.Server(
        uvicorn.Config(application, host="127.0.0.1", port=0, lifespan="off", log_level="warning")
    )
    task = asyncio.create_task(server.serve())
    try:
        await until(lambda: _started(server, task), seconds=30)
        port = server.servers[0].sockets[0].getsockname()[1]
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task


async def _started(server: uvicorn.Server, task: asyncio.Task[None]) -> bool:
    if task.done():
        task.result()  # surface a failed bind instead of waiting out the timeout
    return server.started
