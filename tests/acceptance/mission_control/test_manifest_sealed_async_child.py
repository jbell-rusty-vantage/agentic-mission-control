"""OVE-184 end to end, unpaid: a manifest's async child runs from its own sealed binding and its
admitted result is used during the parent's cognition.

Production here: manifest compile and launch over a launch-bindings file whose async graph is
the generic sealed-child graph (``binding_mode: sealed_child``), the Deep Agents lane adapter
sealing the child's own binding into the contract, the governed middleware composed by the
deployment (check-time admission included), the canonical Agent Server config with its auth,
the sealed-child factory reading the contract from the run's PostgreSQL custody under the
caller's scope, Temporal, PostgreSQL and the parent-boundary settlement.

FIXTURE: the deterministic parent (it spawns, then checks the task until the governed check
admits it, then does its scripted work) and the deterministic model the server substitutes for
the sealed binding's model (``tests/fixtures/wi23_sealed_child_hosting.py``). Nothing is paid.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from tests.acceptance.mission_control import test_manifest_async_child as base
from tests.acceptance.mission_control.test_postgres_children_and_artifacts import (
    _run,
    _terminal,
    _wait_for,
)
from tests.fixtures.catalog.fast_track_catalog import fast_track_catalog, publish_output_schemas
from tests.fixtures.manifest_runtime import ChainScript, GoalScript, promise_submitter
from tests.fixtures.mission_control_local_agent_server import local_agent_server
from tests.fixtures.mission_control_production_stack import open_postgres_production_stack
from tests.fixtures.models import catalog_for
from tests.fixtures.rrm009_production_harness import _diagnose
from tests.fixtures.rrm009_production_stack import SCOPE, call_usage, technical_binding
from tests.integration.temporal.test_manifest_launch_production import (
    OUTPUT_SCHEMAS,
    host_pins,
    missions_app,
    post,
    submit,
)

from mission_control.adapters.agent_server.async_subagents.sealed import (
    sealed_child_served_identity,
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
from mission_control.application.authoring.manifest_launch_inputs import AsyncSubagentGraphBinding
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
from mission_control.domain.execution.contracts import (
    AsyncSubagentLifecycle,
    DeepAgentExecutionBinding,
)

pytestmark = pytest.mark.common_db
POLICY = "policy:async-result:typed-manifest@1"
MAX_CHECKS = 12


class CheckingChainModel(base.SpawningChainModel):
    """Spawns the async child, checks it until the governed check admits its result (pausing
    between checks so the server can run it), records what it saw, then does scripted work."""

    @property
    def _llm_type(self) -> str:
        return "wi23-checking-chain"

    def _check_id(self, index: int) -> str:
        return f"wi23-check-{index}-" + sha256_digest(self.operation_id)[7:19]

    def _reply(self, messages: list[BaseMessage]) -> ChatResult:
        role = self.operation_id.rsplit("/", 1)[-1].split(":", 1)[0]
        first = "goal-iteration/1/" in self.operation_id
        spawned = [
            item
            for item in messages
            if isinstance(item, ToolMessage) and item.tool_call_id == self._spawn_id()
        ]
        checks = [
            item
            for item in messages
            if isinstance(item, ToolMessage) and str(item.tool_call_id).startswith("wi23-check-")
        ]
        admitted = [item for item in checks if '"status": "success"' in str(item.content)]
        if role == "executor" and first and spawned and not admitted and len(checks) < MAX_CHECKS:
            if checks:
                time.sleep(1.0)  # the child runs on the server meanwhile
            task_id = str(spawned[-1].content).rsplit("task_id: ", 1)[-1].strip()
            message = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "check_async_task",
                        "args": {"task_id": task_id},
                        "id": self._check_id(len(checks)),
                        "type": "tool_call",
                    }
                ],
                usage_metadata=call_usage(),
            )
            return ChatResult(generations=[ChatGeneration(message=message)])
        if admitted and role == "executor" and first:
            self.log.append(
                {
                    "model": "parent-saw-child",
                    "operation": self.operation_id,
                    "content": json.loads(str(admitted[-1].content)),
                }
            )
        visible = [
            item
            for item in messages
            if not (
                isinstance(item, ToolMessage) and str(item.tool_call_id).startswith("wi23-check-")
            )
            and not (
                isinstance(item, AIMessage)
                and any(
                    str(call.get("id", "")).startswith("wi23-check-") for call in item.tool_calls
                )
            )
        ]
        return super()._reply(visible)


def checking_components(
    technical: Any, script: ChainScript, model_log: list[dict[str, Any]]
) -> Any:
    from dataclasses import replace

    components = base.spawning_components(technical, script, model_log)

    def parent(bound: Any, _secrets: Any) -> CheckingChainModel:
        return CheckingChainModel(
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
        components,
        model_factories={**components.model_factories, technical.binding.model.ref.digest: parent},
    )


async def write_sealed_bindings(path: Path, technical: Any, endpoint: str) -> None:
    """The launch-production bindings with the async child bound to the sealed-child graph,
    exactly as `missionctl lane async-graphs --graph belllabs_async_child` prints it."""

    await base.write_async_bindings(path, technical, endpoint)
    host = sealed_child_served_identity()
    document = json.loads(await asyncio.to_thread(path.read_text, encoding="utf-8"))
    document["deep_agents_async_graphs"][base.ASYNC_CHILD] = AsyncSubagentGraphBinding(
        graph_id=host.graph_id,
        graph_revision=host.graph_revision,
        graph_binding_digest=host.graph_binding_digest,
        agent_protocol_url=endpoint.rstrip("/"),
        deployment_credential_ref=f"environment:{base.TOKEN_ENV}",
        objective_schema_ref="schema:async-objective@1",
        result_schema_ref="schema:async-result@1",
        result_admission_policy_ref=POLICY,
        default_budget_limits={"tokens.total": 40},
        timeout_seconds=300,
        binding_mode="sealed_child",
    ).model_dump(mode="json")
    await asyncio.to_thread(path.write_text, json.dumps(document, indent=2), encoding="utf-8")


@pytest.fixture
async def sealed_launch_stack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[base.AsyncLaunchStack]:
    """`test_manifest_async_child.async_launch_stack` with the sealed-child graph bound, the
    checking parent, and the server's unpaid sealed-child hosting reading this run's custody."""

    dsn_file = tmp_path / "custody-dsn.txt"
    async with local_agent_server(
        tmp_path / "agent-server",
        monkeypatch,
        extra_environment={
            "MISSION_CONTROL_SEALED_CHILD_FACTORY": (
                "tests.fixtures.wi23_sealed_child_hosting:factory"
            ),
            "WI23_TEST_CUSTODY_DSN_FILE": str(dsn_file),
        },
    ) as endpoint:
        script = ChainScript(request_scope=SCOPE)
        model_log: list[dict[str, Any]] = []
        technical = technical_binding()
        components = checking_components(technical, script, model_log)
        bindings_path = tmp_path / "manifest-launch-bindings.json"
        await write_sealed_bindings(bindings_path, technical, endpoint)
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
            await asyncio.to_thread(
                dsn_file.write_text,
                production.settings.application_postgres_dsn,
                encoding="utf-8",
            )
            run_control = cast(RunControlService, api.state.run_control_service)
            register_manifest_admission_policies(
                cast(AdmissionPolicyRegistry, api.state.admission_policy_registry)
            )
            await production.control_plane.publish(
                PublishRequest(
                    definition=base.async_profile_definition(),
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
            yield base.AsyncLaunchStack(
                production, script, author, missions_app(lifecycle), endpoint, model_log
            )


@pytest.mark.asyncio
async def test_a_manifest_sealed_child_runs_its_own_binding_and_is_used_during_cognition(
    sealed_launch_stack: base.AsyncLaunchStack,
) -> None:
    stack, script, app = (
        sealed_launch_stack.stack,
        sealed_launch_stack.script,
        sealed_launch_stack.app,
    )
    receipt = await submit(app, base.manifest_with_async_child())
    research = {item["mission_key"]: item for item in receipt["missions"]}["research"]
    run_id = research["run_id"]
    assert run_id is not None
    script.by_configuration[research["effective_configuration_digest"]] = GoalScript(
        obligation="evidence_map",
        output_contract="output:evidence_map",
        output_name="evidence_map",
        accept_at=1,
    )
    started = await post(app, "/missions:start", {"run_id": run_id})
    assert started.status_code == 202, started.text
    frozen = await sealed_launch_stack.author.bind(SCOPE, run_id, family="GoalDirected")
    binding = DeepAgentExecutionBinding.carried_by(frozen["executor"])
    assert binding is not None
    (contract,) = binding.async_subagents
    sealed = contract.child_binding
    assert sealed is not None and contract.graph_id == "belllabs_async_child"
    assert sealed.system_prompt.startswith("You are a bounded hosted child.")
    try:
        await _wait_for(stack, run_id, lambda: _terminal(stack, run_id), 420)
    except (TimeoutError, AssertionError) as error:
        raise AssertionError(f"{error}: {await _diagnose(stack, run_id)}") from error
    run = await _run(stack, run_id)
    assert run["terminal_outcome"] == "completed", await _diagnose(stack, run_id)

    (child,) = await PostgresAsyncSubagentAuthority(stack.worker_pool).list_children(SCOPE, run_id)
    details = PostgresAsyncSubagentDetailRepository(stack.worker_pool)
    execution = await details.get_execution(SCOPE, child.child_execution_id)
    link = await details.get_link(SCOPE, child.child_execution_id)
    assert execution.lifecycle == AsyncSubagentLifecycle.COMPLETED
    manifest = execution.result_manifest
    assert manifest is not None
    assert manifest.provider_checkpoint.graph_binding_digest == sealed.sealed_digest
    assert link.result_decision == "admit" and link.settled
    assert link.result_admission_policy_ref == POLICY
    # The parent's own cognition saw the admitted result (the sealed prompt reached the child).
    # Every later executor turn of iteration 1 carries the same admitted check result.
    seen = [item for item in sealed_launch_stack.model_log if item["model"] == "parent-saw-child"]
    assert seen and all(item["content"] == seen[0]["content"] for item in seen)
    content = cast(dict[str, Any], seen[0]["content"])
    assert content["status"] == "success"
    assert content["result"] == f"SEALED-PROMPT-SEEN PONG for: {base.OBJECTIVE}"
    assert content["admission"]["manifest_digest"] == manifest.manifest_digest
    print(
        "WI23 SEALED CHILD EVIDENCE",
        json.dumps(
            {
                "run_id": run_id,
                "child_execution_id": child.child_execution_id,
                "sealed_digest": sealed.sealed_digest,
                "decision": link.result_decision,
                "settled": link.settled,
                "at": datetime.now(UTC).isoformat(),
            },
            sort_keys=True,
        ),
    )
