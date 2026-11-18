"""P1 subagents WP-S2 (Q3 "D"): a `kind: async` subagent profile selected in a manifest spawns
a real child on a real local Agent Server from `missions:start`, with no hand-built binding
and no injected token.

What is production here: the compiler (the async profile is a catalog row the manifest pins),
the production launch author over a `mc.manifest_launch_bindings` file whose
`deep_agents_async_graphs` names the served graph, the Deep Agents lane adapter sealing the
`AsyncSubagentContract` and the deployment credential into the operation's `secret_refs`, the
governed async middleware, the Agent Server auth and the post-cognition admission and
settlement in Postgres. What is FIXTURE: the deterministic parent (`ChainCognition` that spawns
once before its scripted work) and the deterministic hosted child the local server serves, so
nothing is paid.

Real local services: PostgreSQL 17 (``MISSION_CONTROL_TEST_ADMIN_DSN``), the local Temporal
dev server and ``langgraph dev`` on loopback.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from tests.support.acceptance.mission_control.manifest_async_child import (
    ASYNC_CHILD,
    POLICY,
    AsyncLaunchStack,
    async_profile_definition,
    manifest_with_async_child,
    spawning_components,
    write_async_bindings,
)
from tests.support.ids import SCOPE
from tests.support.local_agent_server import (
    local_agent_server,
)
from tests.support.manifest_runtime import (
    OUTPUT_SCHEMAS,
    host_pins,
    missions_app,
    post,
    submit,
)
from tests.support.manifests.lifecycle import ChainScript, GoalScript, promise_submitter
from tests.support.manifests.seeded_catalog import (
    fast_track_catalog,
    publish_output_schemas,
)
from tests.support.model_catalog import catalog_for
from tests.support.production_stack import technical_binding
from tests.support.running_cancellation import TOKEN_ENV
from tests.support.stack import (
    _diagnose,
    _run,
    _terminal,
    _wait_for,
    canonical_evidence,
    open_stack,
)

from mission_control.adapters.postgres.async_subagents.async_subagent_detail_repository import (
    PostgresAsyncSubagentDetailRepository,
)
from mission_control.adapters.postgres.async_subagents.async_subagents import (
    PostgresAsyncSubagentAuthority,
)
from mission_control.adapters.postgres.control_plane.definition_repository import (
    PostgresDefinitionRepository,
)
from mission_control.adapters.postgres.control_plane.manifest_submission import (
    PostgresManifestSubmissionRepository,
)
from mission_control.adapters.postgres.subscriptions.store import PostgresSubscriptionStore
from mission_control.adapters.storage.control_plane_payloads import InMemoryPayloadStore
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
from mission_control.bootstrap.manifests import compose_manifest_launch_inputs
from mission_control.bootstrap.technical_api import api
from mission_control.domain.authoring.contracts import PublishRequest
from mission_control.domain.authoring.extensions import ExtensionRegistry
from mission_control.domain.execution.contracts import (
    AsyncSubagentLifecycle,
    DeepAgentExecutionBinding,
)

pytestmark = [pytest.mark.psycopg_selector, pytest.mark.common_db]


@pytest.fixture
async def async_launch_stack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncLaunchStack]:
    async with local_agent_server(tmp_path / "agent-server", monkeypatch) as endpoint:
        script = ChainScript(request_scope=SCOPE)
        model_log: list[dict[str, Any]] = []
        technical = technical_binding()
        components = spawning_components(technical, script, model_log)
        bindings_path = tmp_path / "manifest-launch-bindings.json"
        await write_async_bindings(bindings_path, technical, endpoint)
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
                "ASYNC_SUBAGENT_SPAWNING_ENABLED": "true",
                "ASYNC_SUBAGENT_COMPLETION_WAIT_SECONDS": "120",
            },
        ) as production:
            # W1 (OVE-169): the scripted executors submit their declared required promises.
            script.submit = promise_submitter(production.worker_pool, SCOPE)
            run_control = cast(RunControlService, api.state.run_control_service)
            register_manifest_admission_policies(
                cast(AdmissionPolicyRegistry, api.state.admission_policy_registry)
            )
            # The async profile is a catalog row in Postgres too: the production launch author
            # reads subagent bodies from the installation catalog, never from a fixture.
            await production.control_plane.publish(
                PublishRequest(
                    definition=async_profile_definition(),
                    actor_id="fixture",
                    published_at=datetime.now(UTC),
                    expected_head_revision=0,
                )
            )
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
            yield AsyncLaunchStack(
                production, script, author, missions_app(lifecycle), endpoint, model_log
            )


@pytest.mark.asyncio
async def test_a_manifest_async_child_spawns_on_the_agent_server_and_settles(
    async_launch_stack: AsyncLaunchStack,
) -> None:
    stack, script, app = async_launch_stack.stack, async_launch_stack.script, async_launch_stack.app
    receipt = await submit(app, manifest_with_async_child())
    members = {item["mission_key"]: item for item in receipt["missions"]}
    research = members["research"]
    run_id = research["run_id"]
    assert run_id is not None
    script.by_configuration[research["effective_configuration_digest"]] = GoalScript(
        obligation="evidence_map",
        output_contract="output:evidence_map",
        output_name="evidence_map",
        accept_at=1,
    )

    # 1. The public start; the production author seals the async contract from the manifest.
    started = await post(app, "/missions:start", {"run_id": run_id})
    assert started.status_code == 202, started.text
    frozen = await async_launch_stack.author.bind(SCOPE, run_id, family="GoalDirected")
    executor = frozen["executor"]
    binding = DeepAgentExecutionBinding.carried_by(executor)
    assert binding is not None
    (contract,) = binding.async_subagents
    assert contract.name == ASYNC_CHILD
    assert contract.agent_protocol_url == async_launch_stack.endpoint.rstrip("/")
    assert contract.deployment_credential_ref == f"environment:{TOKEN_ENV}"
    assert contract.result_admission_policy_ref == POLICY
    assert {(ref.provider, ref.key) for ref in executor.secret_refs} >= {
        ("environment", "OPENAI_API_KEY"),
        ("environment", TOKEN_ENV),
    }
    receipt_rows = {
        (item.kind, item.name): item for item in (binding.materialization_receipt or {}).items
    }
    assert receipt_rows[("subagent", ASYNC_CHILD)].native_locator.startswith("agent_server:")  # type: ignore[union-attr]

    # 2. The run completes; the child really ran on the server and was admitted and settled.
    try:
        await _wait_for(stack, run_id, lambda: _terminal(stack, run_id), 420)
    except (TimeoutError, AssertionError) as error:
        raise AssertionError(f"{error}: {await _diagnose(stack, run_id)}") from error
    run = await _run(stack, run_id)
    assert run["terminal_outcome"] == "completed", await _diagnose(stack, run_id)
    children = await PostgresAsyncSubagentAuthority(stack.worker_pool).list_children(SCOPE, run_id)
    assert len(children) == 1, children
    details = PostgresAsyncSubagentDetailRepository(stack.worker_pool)
    (child,) = children
    execution = await details.get_execution(SCOPE, child.child_execution_id)
    link = await details.get_link(SCOPE, child.child_execution_id)
    assert execution.lifecycle == AsyncSubagentLifecycle.COMPLETED
    assert execution.result_output_text == "PONG"
    assert link.result_decision == "admit" and link.settled
    assert link.usage_disposition == "settled"
    assert link.result_admission_policy_ref == POLICY
    rows = await canonical_evidence(stack, run_id, children=True)
    assert rows["counts"]["subordinate_execution"] >= 1, rows
    print(
        "MANIFEST ASYNC CHILD EVIDENCE",
        json.dumps(
            {
                "run_id": run_id,
                "child_execution_id": child.child_execution_id,
                "contract_digest": contract.contract_digest,
                "result_decision": link.result_decision,
                "usage_disposition": link.usage_disposition,
                "thread_id_is_child_id": True,
            },
            sort_keys=True,
        ),
    )
