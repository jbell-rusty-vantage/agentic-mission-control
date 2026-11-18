"""MP-02 acceptance: manifest runs start with the production launch input author.

Real local services: the production API/worker composition on a disposable common-component
PostgreSQL 17 (``MISSION_CONTROL_TEST_ADMIN_DSN``) with the local Temporal dev server and
deterministic local cognition (``ChainCognition``; no provider, no paid effect).

What is production here: the launch input author (``compose_manifest_launch_inputs`` over the
settings-declared ``MANIFEST_LAUNCH_BINDINGS_PATH``), the public ``POST .../missions:submit``
and ``POST .../missions:start`` router (no ``family_input`` in the body), the manifest submit
service, the governed launch, the chain release hook and the chain relay pump
(``compose_chain_relay_pump``). What is FIXTURE: the seeded fast-track catalog the manifest
resolves against, the deployment bindings file (every model/sandbox profile mapped to the
WP-CP-040 qualification components the worker serves as deterministic local cognition, see
``tests.unit.authoring.manifest_launch_fixture``), the Mission 2 lane transform onto
``deep_agents``, the test-stack root submitter (the technical stack's coordinator queues,
as its API launch composes them), and the catalog output schemas plus the ``evaluable``
transform that give every launched manifest an acceptance the runtime can evaluate (a fresh
launch refuses one it cannot, ``completion_support``).

1. Mission 2 (``research`` supplies ``ingestion``) is submitted and its first member started
   through HTTP; the production author freezes its Goal Loop templates.
2. ``research`` accepts, the chain releases ``ingestion`` and the production relay pump starts
   it; the start intent is then delivered again (acknowledgement lost) and the consumer still
   has exactly one root workflow.
3. A manifest whose node selects an unbound model profile is refused before any dispatch with
   409 ``start_unavailable`` naming the manifest pointer; the run stays pending.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast

import pytest
from temporalio.service import RPCError

from mission_control.adapters.postgres.chains.store import HOOK_NAME, ChainReleaseHook
from mission_control.adapters.postgres.control_plane.definition_repository import (
    PostgresDefinitionRepository,
)
from mission_control.adapters.postgres.control_plane.manifest_submission import (
    PostgresManifestSubmissionRepository,
)
from mission_control.adapters.postgres.run_control.canonical import register_post_append_hook
from mission_control.adapters.postgres.subscriptions.store import PostgresSubscriptionStore
from mission_control.adapters.storage.control_plane_payloads import InMemoryPayloadStore
from mission_control.application.authoring.manifest_launch_inputs import (
    binding_ref,
)
from mission_control.application.authoring.manifest_service import (
    ManifestCompileService,
    ManifestProgramCompiler,
    MissionManifestService,
)
from mission_control.application.authoring.manifest_submit import (
    ManifestSubmitService,
    register_manifest_admission_policies,
)
from mission_control.application.execution.run_launch import RunLaunchService
from mission_control.application.execution.service import (
    AdmissionPolicyRegistry,
    RunControlService,
)
from mission_control.application.subscriptions.service import SubscriptionService
from mission_control.bootstrap.manifests import (
    compose_manifest_launch_inputs,
)
from mission_control.bootstrap.technical_api import api
from mission_control.domain.authoring.extensions import ExtensionRegistry
from mission_control.domain.execution.contracts import DeepAgentExecutionBinding
from tests.fixtures.catalog.fast_track_catalog import fast_track_catalog, publish_output_schemas
from tests.fixtures.manifest_runtime import (
    ChainScript,
    GoalScript,
    chain_components,
    promise_submitter,
)
from tests.fixtures.rrm009_production_stack import AGENT_COGNITIVE_QUEUE, technical_binding
from tests.support.ids import SCOPE
from tests.support.manifest_runtime import (
    MISSION_2,
    OUTPUT_SCHEMAS,
    OWNER_KEY,
    ROOT,
    SCOPED,
    CountingAuthor,
    LaunchStack,
    delivered,
    evaluable,
    fetch,
    host_pins,
    missions_app,
    post,
    pumping,
    relay_pump,
    root_executions,
    submit,
    write_bindings,
)
from tests.support.model_catalog import catalog_for
from tests.support.stack import _diagnose, _run, _until, open_stack
from tests.unit.authoring.manifest_launch_fixture import (
    deep_agents_chain,
)

pytestmark = pytest.mark.common_db

MINIMAL = ROOT / "tests/fixtures/manifests/minimal-stage-graph.yml"


@pytest.fixture
async def launch_stack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[LaunchStack]:
    script = ChainScript(request_scope=SCOPE)
    model_log: list[dict[str, Any]] = []
    technical = technical_binding()
    components = chain_components(technical, script, model_log)
    bindings_path = tmp_path / "manifest-launch-bindings.json"
    await write_bindings(bindings_path, technical)
    async with open_stack(
        fixture_owner_prerequisites=True,
        root=tmp_path,
        monkeypatch=monkeypatch,
        technical_override=technical,
        components=components,
        model_log=model_log,
        extra_environment={
            "MANIFEST_LAUNCH_BINDINGS_PATH": str(bindings_path),
            "CAPABILITY_PINS_PATH": str(host_pins(tmp_path / "capability-pins.json")),
        },
    ) as production:
        unregister = register_post_append_hook(HOOK_NAME, ChainReleaseHook())
        # W1 (OVE-169): the scripted executors submit their declared required promises.
        script.submit = promise_submitter(production.worker_pool, SCOPE)
        try:
            run_control = cast(RunControlService, api.state.run_control_service)
            register_manifest_admission_policies(
                cast(AdmissionPolicyRegistry, api.state.admission_policy_registry)
            )
            # The production composition; the worker's components are served beside the pins.
            author = compose_manifest_launch_inputs(
                production.worker_pool,
                settings=production.settings,
                application_id="biotech",
                run_control=run_control,
                control_plane=production.control_plane,
                additional=components,
                models=catalog_for({"frontier.default": technical.binding.model}),
            )
            assert author is not None
            definitions, search = await fast_track_catalog()
            await publish_output_schemas(definitions, OUTPUT_SCHEMAS)
            catalog = PostgresDefinitionRepository(
                production.worker_pool,
                catalog_scope=production.settings.mission_control_catalog_scope or "",
            )
            programs = ManifestProgramCompiler(catalog, ExtensionRegistry(), InMemoryPayloadStore())
            compiler = ManifestCompileService(
                definitions=definitions, search=search, programs=programs
            )
            lifecycle = MissionManifestService(
                compiler=compiler,
                request_scope=SCOPE,
                lifecycle=ManifestSubmitService(
                    compiler=compiler,
                    programs=programs,
                    run_control=run_control,
                    submissions=PostgresManifestSubmissionRepository(production.worker_pool),
                    request_scope=SCOPE,
                    launches=cast(RunLaunchService, api.state.run_launch_service),
                    launch_inputs=author,
                    subscriptions=SubscriptionService(
                        PostgresSubscriptionStore(production.worker_pool, SCOPE)
                    ),
                ),
            )
            yield LaunchStack(production, script, author, missions_app(lifecycle), model_log)
        finally:
            unregister()


# --- Acceptance 1 and 2 -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_chain_starts_over_http_and_its_consumer_starts_once_under_redelivery(
    launch_stack: LaunchStack,
) -> None:
    stack, script, app = launch_stack.stack, launch_stack.script, launch_stack.app
    receipt = await submit(app, evaluable(deep_agents_chain(MISSION_2.read_text(encoding="utf-8"))))
    members = {item["mission_key"]: item for item in receipt["missions"]}
    research, ingestion = members["research"], members["ingestion"]
    assert research["run_id"] is not None and ingestion["run_id"] is None
    script.by_configuration[research["effective_configuration_digest"]] = GoalScript(
        obligation="evidence_map",
        output_contract="output:evidence_map",
        output_name="evidence_map",
        accept_at=1,
    )
    script.by_configuration[ingestion["effective_configuration_digest"]] = GoalScript(
        obligation="ingested",
        output_contract="output:ingestion_receipt",
        output_name="ingestion_receipt",
        accept_at=1,
    )

    # Acceptance 1: the public start, no family_input; the production author binds the run.
    started = await post(app, "/missions:start", {"run_id": research["run_id"]})
    assert started.status_code == 202, started.text
    assert started.json()["family"] == "GoalDirected"
    frozen = await launch_stack.author.bind(SCOPE, research["run_id"], family="GoalDirected")
    executor = frozen["executor"]
    assert DeepAgentExecutionBinding.carried_by(executor) is not None
    assert DeepAgentExecutionBinding.carried_by(executor).task_queue == AGENT_COGNITIVE_QUEUE
    assert [
        item.server_name for item in DeepAgentExecutionBinding.carried_by(executor).mcp_servers
    ] == [stack.technical.binding.mcp_servers[0].server_name]
    assert executor.secret_refs[0].key == "OPENAI_API_KEY"

    author = CountingAuthor(launch_stack.author)
    pump = relay_pump(stack, author)
    async with pumping(pump):

        async def consumer_started() -> bool:
            rows = await fetch(
                stack,
                f"SELECT run_key FROM mission_control.mission_run "
                f"WHERE {SCOPED} AND mission_id = $4::uuid",
                ingestion["mission_id"],
            )
            return bool(rows) and bool(await root_executions(stack, rows[0]["run_key"]))

        try:
            await _until(consumer_started, 420)
        except (TimeoutError, AssertionError) as error:
            raise AssertionError(
                f"{error}: {await _diagnose(stack, research['run_id'])}"
            ) from error

    (consumer,) = await fetch(
        stack,
        f"SELECT run_key, created_by_actor_ref FROM mission_control.mission_run "
        f"WHERE {SCOPED} AND mission_id = $4::uuid",
        ingestion["mission_id"],
    )
    consumer_key = consumer["run_key"]
    assert consumer["created_by_actor_ref"].startswith("chain:")
    assert author.calls == [consumer_key]
    (intent,) = await fetch(
        stack,
        f"SELECT delivery_key, delivery_state FROM mission_control.outbox "
        f"WHERE {SCOPED} AND destination_kind = $4",
        "mc.chain.start_run",
    )
    assert intent["delivery_state"] == "delivered"

    # Acceptance 2: the acknowledgement is lost; the relay delivers the same intent again.
    async with stack.owner_pool.acquire() as connection:
        await connection.execute(
            f"UPDATE mission_control.outbox SET delivery_state = 'pending', delivered_at = NULL "
            f"WHERE {SCOPED} AND delivery_key = $4",
            *OWNER_KEY,
            intent["delivery_key"],
        )
    reports = await pump.run_once()
    assert delivered(reports) == [intent["delivery_key"]], reports
    (redelivery,) = [report.receipts[intent["delivery_key"]] for report in reports]
    # Either the run already left `pending`, or the launch attached to the root the first
    # delivery started (USE_EXISTING): never a second execution.
    executions = await root_executions(stack, consumer_key)
    assert len(executions) == 1, executions
    if not redelivery.already_started:
        assert redelivery.workflow_id == f"belllabs-run/{consumer_key}"
        assert redelivery.temporal_run_id == executions[0]
    assert author.calls == [consumer_key, consumer_key]
    # The second delivery reused the frozen templates (the documents are immutable).
    again = await launch_stack.author.bind(SCOPE, consumer_key, family="GoalDirected")
    assert again["executor"].identity.run_id == consumer_key
    assert binding_ref(consumer_key) == f"semantic-input:manifest:{consumer_key}"

    # The started root applies the consumer's start asynchronously (as in MP-22).
    async def consumer_active() -> bool:
        return bool((await _run(stack, consumer_key))["phase"] != "pending")

    await _until(consumer_active, 120)


# --- Acceptance 3 -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unbound_model_is_refused_before_dispatch_with_its_manifest_pointer(
    launch_stack: LaunchStack,
) -> None:
    stack, app = launch_stack.stack, launch_stack.app
    receipt = await submit(app, evaluable(MINIMAL.read_text(encoding="utf-8")))
    (mission,) = receipt["missions"]
    run_id = mission["run_id"]
    assert run_id is not None

    refused = await post(app, "/missions:start", {"run_id": run_id})
    assert refused.status_code == 409, refused.text
    detail = refused.json()["detail"]
    assert detail["code"] == "start_unavailable"
    assert detail["message"].startswith("/mission/program/nodes/1/environment/model/profile: ")
    assert "frontier.long_context" in detail["message"]

    # Nothing was dispatched: no root workflow, the run is still pending, no templates frozen.
    with pytest.raises(RPCError):
        await stack.client.get_workflow_handle(f"belllabs-run/{run_id}").describe()
    assert (await _run(stack, run_id))["phase"] == "pending"
    documents = await fetch(
        stack,
        f"SELECT count(*) AS n FROM mission_control.runtime_document "
        f"WHERE {SCOPED} AND identity LIKE $4",
        f'["{binding_ref(run_id)}"%',
    )
    assert documents[0]["n"] == 0
    assert not launch_stack.model_log
