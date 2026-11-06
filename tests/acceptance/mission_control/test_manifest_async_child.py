"""P1 subagents WP-S2 (Q3 "D"): a `kind: async` subagent profile selected in a manifest spawns
a real child on a real local Agent Server from `missions:start`, with no hand-built binding
and no injected token.

What is production here: the compiler (the async profile is a catalog row the manifest pins),
the production launch author over a `mc.manifest_launch_bindings` file whose
`deep_agents_async_graphs` names the served graph, the Deep Agents lane adapter sealing the
`AsyncSubagentContract` and the deployment credential into the operation's `secret_refs`, the
governed async middleware, the Agent Server auth and the post-cognition admission and
settlement in Postgres. What is FIXTURE: the deterministic parent (`ChainModel` that spawns
once before its scripted work) and the deterministic hosted child the local server serves, so
nothing is paid.

Real local services: PostgreSQL 17 (``MISSION_CONTROL_TEST_ADMIN_DSN``), the local Temporal
dev server and ``langgraph dev`` on loopback.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from tests.acceptance.mission_control.test_postgres_children_and_artifacts import (
    _run,
    _terminal,
    _wait_for,
    canonical_evidence,
)
from tests.fixtures.catalog.fast_track_catalog import (
    fast_track_catalog,
    fixture_definitions,
    publish_output_schemas,
)
from tests.fixtures.manifest_runtime import ChainModel, ChainScript, GoalScript, promise_submitter
from tests.fixtures.mission_control_local_agent_server import (
    deterministic_child_definition,
    local_agent_server,
)
from tests.fixtures.mission_control_production_stack import open_postgres_production_stack
from tests.fixtures.models import catalog_for, model_binding
from tests.fixtures.rrm009_cancellation import TOKEN_ENV
from tests.fixtures.rrm009_production_harness import ProductionStack, _diagnose
from tests.fixtures.rrm009_production_stack import (
    AGENT_COGNITIVE_QUEUE,
    SCOPE,
    TechnicalBinding,
    call_usage,
    technical_binding,
)
from tests.integration.temporal.test_manifest_launch_production import (
    MISSION_2,
    OUTPUT_SCHEMAS,
    deep_agents_chain,
    evaluable,
    host_pins,
    missions_app,
    post,
    pubmed_digest,
    submit,
)
from tests.unit.authoring.manifest_launch_fixture import fixture_bindings, pubmed_bound

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
from mission_control.application.authoring.manifest_launch_inputs import (
    AsyncSubagentGraphBinding,
    ManifestLaunchInputAuthor,
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
from mission_control.bootstrap.manifests import compose_manifest_launch_inputs
from mission_control.bootstrap.technical_api import api
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import PublishRequest
from mission_control.domain.authoring.extensions import ExtensionRegistry
from mission_control.domain.authoring.manifest import canonical_manifest_bytes, load_manifest_yaml
from mission_control.domain.execution.contracts import (
    AsyncSubagentLifecycle,
    DeepAgentExecutionBinding,
)

pytestmark = pytest.mark.common_db

ASYNC_PROFILE_ID = "subagent.async-child"
ASYNC_CHILD = "async-child"
OBJECTIVE = "Reply with exactly PONG."
POLICY = "policy:async-result:technical-child@1"


class SpawningChainModel(ChainModel):
    """`ChainModel` that spawns the manifest's async child once, in iteration 1 of the executor,
    then does its scripted work as if the spawn had not happened."""

    @property
    def _llm_type(self) -> str:
        return "p1-async-spawning-chain"

    def _spawn_id(self) -> str:
        return "p1-spawn-" + sha256_digest(self.operation_id)[7:23]

    def _reply(self, messages: list[BaseMessage]) -> ChatResult:
        role = self.operation_id.rsplit("/", 1)[-1].split(":", 1)[0]
        first_iteration = "goal-iteration/1/" in self.operation_id
        spawned = any(
            isinstance(item, ToolMessage) and item.tool_call_id == self._spawn_id()
            for item in messages
        )
        if role == "executor" and first_iteration and not spawned:
            self._record("parent", messages)
            message = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "start_async_task",
                        "args": {"description": OBJECTIVE, "subagent_type": ASYNC_CHILD},
                        "id": self._spawn_id(),
                        "type": "tool_call",
                    }
                ],
                usage_metadata=call_usage(),
            )
            return ChatResult(generations=[ChatGeneration(message=message)])
        # Hide the spawn exchange from the scripted executor so its tool counting holds.
        visible = [
            item
            for item in messages
            if not (
                (isinstance(item, ToolMessage) and item.tool_call_id == self._spawn_id())
                or (
                    isinstance(item, AIMessage)
                    and any(call.get("id") == self._spawn_id() for call in item.tool_calls)
                )
            )
        ]
        return super()._reply(visible)


def spawning_components(
    technical: TechnicalBinding, script: ChainScript, model_log: list[dict[str, Any]]
) -> Any:
    base = technical.components(model_log)

    def parent(bound: Any, _secrets: Any) -> SpawningChainModel:
        return SpawningChainModel(
            run_id=bound.run_id,
            operation_id=bound.operation_id,
            log=model_log,
            script=script,
            configuration_digest=bound.erc_digest,
            attempt=bound.operation_attempt,
            slots=tuple(
                (slot.slot_name, slot.logical_path)
                for slot in bound.workspace.slot_bindings
                if slot.access == "exclusive_write"
            ),
        )

    return replace(
        base, model_factories={**base.model_factories, technical.binding.model.ref.digest: parent}
    )


def async_profile_definition() -> Any:
    (definition,) = [item for item in fixture_definitions() if item.logical_id == ASYNC_PROFILE_ID]
    return definition


def async_profile_pin() -> str:
    return f"{ASYNC_PROFILE_ID}@1#{sha256_digest(async_profile_definition())}"


def manifest_with_async_child() -> str:
    """Mission 2 on Deep Agents, evaluable, with the async child selected by exact pin on the
    `research` mission (the first member, started directly)."""

    document = load_manifest_yaml(
        evaluable(deep_agents_chain(MISSION_2.read_text(encoding="utf-8")))
    )
    research = document["missions"][0]
    assert research["key"] == "research"
    research["environment"]["agents"] = [{"pin": async_profile_pin(), "as": "async_child"}]
    return canonical_manifest_bytes(document).decode("utf-8")


async def write_async_bindings(
    path: Path,
    technical: TechnicalBinding,
    endpoint: str,
    *,
    served: Any | None = None,
    parent_model: Any | None = None,
    budget: dict[str, int] | None = None,
) -> None:
    """FIXTURE deployment bindings: the launch-production bindings plus the served graph the
    async child may spawn, exactly as `missionctl lane async-graphs` would print it.
    `served` defaults to the deterministic child's identity; `parent_model` to the fixture
    model (a live drill passes the real served identity and a real model component)."""

    served = served or deterministic_child_definition().served
    (server,) = technical.binding.mcp_servers
    bindings = fixture_bindings(task_queue=AGENT_COGNITIVE_QUEUE).model_copy(
        update={
            "model_profiles": {
                "frontier.default": model_binding(parent_model or technical.binding.model)
            },
            "sandbox_profiles": {
                "research.standard": technical.binding.sandbox,
                "ingestion.standard": technical.binding.sandbox,
            },
            "deep_agents_async_graphs": {
                ASYNC_CHILD: AsyncSubagentGraphBinding(
                    graph_id=served.graph_id,
                    graph_revision=served.graph_revision,
                    graph_binding_digest=served.graph_binding_digest,
                    agent_protocol_url=endpoint.rstrip("/"),
                    deployment_credential_ref=f"environment:{TOKEN_ENV}",
                    objective_schema_ref="schema:async-objective@1",
                    result_schema_ref="schema:async-result@1",
                    result_admission_policy_ref=POLICY,
                    default_budget_limits=budget or {"tokens.total": 40},
                    timeout_seconds=300,
                )
            },
        }
    )
    bound = pubmed_bound(bindings, await pubmed_digest(), server)
    await asyncio.to_thread(path.write_text, bound.model_dump_json(indent=2), encoding="utf-8")


@dataclass
class AsyncLaunchStack:
    stack: ProductionStack
    script: ChainScript
    author: ManifestLaunchInputAuthor
    app: FastAPI
    endpoint: str
    model_log: list[dict[str, Any]]


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
        async with open_postgres_production_stack(
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
