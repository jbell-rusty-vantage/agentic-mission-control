"""FX-DA-SUB3 (P1 subagents, Q5): the manifest-launched async child on real models.

The parent node runs on GPT-6 Sol through the production OpenAI factory; the Agent Server hosts
the production technical child on GPT-6 Luna (the ``child.default`` row of a drill Model
Catalog, OC-R6: the server reads ``deployments/<app>/models.toml``);
both are paid calls. Everything else is the T0 proof of ``test_manifest_async_child.py``: the
manifest pins the async profile, the production launch author seals the contract and the
credential, the governed middleware spawns, the server admits the claim, Postgres settles.

Gated: ``BELLABS_RUN_P1_ASYNC_LIVE=1`` and an OpenAI key in the environment or the repository
``.env``. Spend is bounded by the manifest budget and one Goal Loop iteration; the owner's
ceiling for this drill is 15 USD (recorded 2026-10-20). Evidence (ids, counts, usage, no
payloads) is written to ``.scratch/pc-p1-deep-agents/turn3/live-sol-luna.json``.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from dotenv import dotenv_values
from tests.acceptance.mission_control.test_manifest_async_child import (
    ASYNC_CHILD,
    AsyncLaunchStack,
    async_profile_definition,
    async_profile_pin,
    write_async_bindings,
)
from tests.acceptance.mission_control.test_postgres_children_and_artifacts import (
    _run,
    _terminal,
    _wait_for,
    canonical_evidence,
)
from tests.fixtures.catalog.fast_track_catalog import fast_track_catalog, publish_output_schemas
from tests.fixtures.manifest_runtime import ChainScript
from tests.fixtures.mission_control_local_agent_server import local_agent_server
from tests.fixtures.mission_control_production_stack import open_postgres_production_stack
from tests.fixtures.models import catalog_for
from tests.fixtures.rrm009_production_harness import _diagnose
from tests.fixtures.rrm009_production_stack import SCOPE, technical_binding
from tests.integration.temporal.test_manifest_launch_production import (
    MISSION_2,
    OUTPUT_SCHEMAS,
    deep_agents_chain,
    evaluable,
    host_pins,
    missions_app,
    post,
    submit,
)

from mission_control.adapters.agent_server.async_subagents.bindings import (
    TECHNICAL_CHILD_MODEL_PROFILE,
    technical_child_definition,
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
from mission_control.bootstrap.settings import PROJECT_ROOT
from mission_control.bootstrap.technical_api import api
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import (
    DefinitionKind,
    ExactDefinitionRef,
    PublishRequest,
)
from mission_control.domain.authoring.extensions import ExtensionRegistry
from mission_control.domain.authoring.manifest import canonical_manifest_bytes, load_manifest_yaml
from mission_control.domain.execution.contracts import (
    AsyncSubagentLifecycle,
    DeepAgentExecutionBinding,
    DeepAgentModelComponent,
)
from mission_control.domain.resolution.profiles import ModelProfile

pytestmark = pytest.mark.common_db

PARENT_MODEL = "gpt-6-sol"
CHILD_MODEL = "gpt-6-luna"
EVIDENCE = PROJECT_ROOT / ".scratch" / "pc-p1-deep-agents" / "turn3" / "live-sol-luna.json"
DELEGATION = (
    "Before any other work, call start_async_task with subagent_type 'async-child' and "
    "description 'Reply with exactly PONG.'; then call check_async_task once with the "
    "returned task id and continue. "
)


# The drill's child: a Model Catalog row the Agent Server reads (OC-R6), not code or env.
LIVE_CHILD = ModelProfile(
    profile=TECHNICAL_CHILD_MODEL_PROFILE,
    vendor="openai",
    model_id=CHILD_MODEL,
    context_window_tokens=1_050_000,
    max_input_tokens=922_000,
    cost_per_million_input=0.1,
    cost_per_million_output=0.5,
    supports=("structured_output", "tool_use", "images"),
    structured_output="tool_forced",
    data_class_ceiling="internal",
)


def live_deployments(root: Path) -> Path:
    """A drill deployments root: the checked-in biotech profile plus a catalog whose
    `child.default` is the drill's child model."""

    target = root / "biotech"
    target.mkdir(parents=True, exist_ok=True)
    source = PROJECT_ROOT / "deployments" / "biotech" / "application.toml"
    (target / "application.toml").write_bytes(source.read_bytes())
    row = LIVE_CHILD.model_dump(mode="json", exclude={"schema_version"})
    lines = ['schema_version = "mc.model_catalog.v1"', "", "[[models]]"]
    lines += [f"{key} = {json.dumps(value)}" for key, value in row.items()]
    (target / "models.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root


def _openai_key() -> str:
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        key = str(dotenv_values(PROJECT_ROOT / ".env").get("OPENAI_API_KEY") or "")
    return key


def sol_component() -> DeepAgentModelComponent:
    return DeepAgentModelComponent(
        ref=ExactDefinitionRef(
            kind=DefinitionKind.MODEL,
            logical_id=f"model.{PARENT_MODEL}",
            revision=1,
            digest=sha256_digest(f"model.{PARENT_MODEL}:p1-live"),
        ),
        provider="openai",
        model_name=PARENT_MODEL,
        settings={"reasoning_effort": "low", "use_responses_api": True},
    )


def live_pins(path: Path, model: DeepAgentModelComponent) -> Path:
    """The host pin file plus the live parent model, so the worker serves it through the
    production OpenAI factory (`deployment_composition` registers one per pinned model)."""

    document = json.loads(host_pins(path).read_text(encoding="utf-8"))
    document["models"] = [
        *document.get("models", []),
        {
            "provider": "openai",
            "model_id": model.model_name,
            "ref": {
                "kind": "model",
                "logical_id": model.ref.logical_id,
                "revision": model.ref.revision,
                "digest": model.ref.digest,
            },
        },
    ]
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return path


def live_manifest() -> str:
    """Mission 2 on Deep Agents, evaluable, with the async child pinned on `research`, the
    delegation written into the goal, one iteration, and a tight token budget."""

    document = load_manifest_yaml(
        evaluable(deep_agents_chain(MISSION_2.read_text(encoding="utf-8")))
    )
    research = document["missions"][0]
    assert research["key"] == "research"
    environment = research["environment"]
    environment["agents"] = [{"pin": async_profile_pin(), "as": "async_child"}]
    environment["governors"] = {**environment.get("governors", {}), "iterations": 1, "patience": 1}
    environment["budget"] = {**environment.get("budget", {}), "usd": 5, "tokens": 120_000}
    for goal in research["goals"]:
        goal["description"] = DELEGATION + goal["description"]
    return canonical_manifest_bytes(document).decode("utf-8")


@pytest.fixture
async def live_stack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncLaunchStack]:
    if os.environ.get("BELLABS_RUN_P1_ASYNC_LIVE") != "1":
        pytest.skip("set BELLABS_RUN_P1_ASYNC_LIVE=1 for the paid Sol/Luna drill")
    key = _openai_key()
    if not key:
        pytest.skip("an OpenAI key is required (environment or repository .env)")
    monkeypatch.setenv("OPENAI_API_KEY", key)
    deployments = live_deployments(tmp_path / "deployments")
    monkeypatch.setenv("MISSION_CONTROL_DEPLOYMENTS_ROOT", str(deployments))
    monkeypatch.setenv("MISSION_CONTROL_APPLICATION", "biotech")
    async with local_agent_server(
        tmp_path / "agent-server",
        monkeypatch,
        hosting_factory="",  # the production technical child
        extra_environment={
            "OPENAI_API_KEY": key,
            "MISSION_CONTROL_DEPLOYMENTS_ROOT": str(deployments),
            "MISSION_CONTROL_APPLICATION": "biotech",
        },
    ) as endpoint:
        technical = technical_binding()
        model_log: list[dict[str, Any]] = []
        sol = sol_component()
        bindings_path = tmp_path / "manifest-launch-bindings.json"
        await write_async_bindings(
            bindings_path,
            technical,
            endpoint,
            served=technical_child_definition(LIVE_CHILD).served,
            parent_model=sol,
            budget={"tokens.total": 4_000},
        )
        async with open_postgres_production_stack(
            fixture_owner_prerequisites=True,
            root=tmp_path,
            monkeypatch=monkeypatch,
            technical_override=technical,
            components=technical.components(model_log),
            model_log=model_log,
            extra_environment={
                "MANIFEST_LAUNCH_BINDINGS_PATH": str(bindings_path),
                "CAPABILITY_PINS_PATH": str(live_pins(tmp_path / "capability-pins.json", sol)),
                "ASYNC_SUBAGENT_SPAWNING_ENABLED": "true",
                "ASYNC_SUBAGENT_COMPLETION_WAIT_SECONDS": "180",
                "OPENAI_API_KEY": key,
            },
        ) as production:
            run_control = cast(RunControlService, api.state.run_control_service)
            register_manifest_admission_policies(
                cast(AdmissionPolicyRegistry, api.state.admission_policy_registry)
            )
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
                additional=technical.components(model_log),
                models=catalog_for({"frontier.default": sol}),
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
                production,
                ChainScript(request_scope=SCOPE),
                author,
                missions_app(lifecycle),
                endpoint,
                model_log,
            )


@pytest.mark.asyncio
async def test_sol_parent_spawns_a_luna_child_from_a_manifest_and_settles(
    live_stack: AsyncLaunchStack,
) -> None:
    stack, app = live_stack.stack, live_stack.app
    receipt = await submit(app, live_manifest())
    members = {item["mission_key"]: item for item in receipt["missions"]}
    run_id = members["research"]["run_id"]
    assert run_id is not None
    started = await post(app, "/missions:start", {"run_id": run_id})
    assert started.status_code == 202, started.text
    frozen = await live_stack.author.bind(SCOPE, run_id, family="GoalDirected")
    executor = frozen["executor"]
    assert DeepAgentExecutionBinding.carried_by(executor) is not None
    assert DeepAgentExecutionBinding.carried_by(executor).model.model_name == PARENT_MODEL
    (contract,) = DeepAgentExecutionBinding.carried_by(executor).async_subagents
    assert contract.name == ASYNC_CHILD

    evidence: dict[str, Any] = {
        "run_id": run_id,
        "parent_model": PARENT_MODEL,
        "child_model": CHILD_MODEL,
        "contract_digest": contract.contract_digest,
        "graph_binding_digest": contract.graph_binding_digest,
        "started_at": datetime.now(UTC).isoformat(),
    }
    try:
        # Progress every minute (phase, lifecycle, outcome) so a slow parent is observable in
        # the log; the pytest timeout for this module is raised on the command line.
        async def progress() -> None:
            while True:
                await asyncio.sleep(60)
                run = await _run(stack, run_id)
                print(
                    "LIVE PROGRESS",
                    json.dumps(
                        {
                            key: run.get(key)
                            for key in ("phase", "lifecycle", "terminal_outcome", "iteration")
                        },
                        default=str,
                    ),
                    flush=True,
                )

        reporter = asyncio.create_task(progress())
        try:
            await _wait_for(stack, run_id, lambda: _terminal(stack, run_id), 1_500)
        finally:
            reporter.cancel()
    finally:
        run = await _run(stack, run_id)
        evidence["terminal_outcome"] = run.get("terminal_outcome")
        evidence["diagnose"] = await _diagnose(stack, run_id)
        children = await PostgresAsyncSubagentAuthority(stack.worker_pool).list_children(
            SCOPE, run_id
        )
        details = PostgresAsyncSubagentDetailRepository(stack.worker_pool)
        evidence["children"] = []
        for child in children:
            execution = await details.get_execution(SCOPE, child.child_execution_id)
            link = await details.get_link(SCOPE, child.child_execution_id)
            evidence["children"].append(
                {
                    "child_execution_id": child.child_execution_id,
                    "lifecycle": execution.lifecycle.value,
                    "result_text": execution.result_output_text,
                    "result_decision": link.result_decision,
                    "settled": link.settled,
                    "usage_disposition": link.usage_disposition,
                    "usage": execution.model_dump(mode="json").get("usage"),
                }
            )
        evidence["rows"] = await canonical_evidence(stack, run_id, children=True)
        evidence["finished_at"] = datetime.now(UTC).isoformat()
        await asyncio.to_thread(EVIDENCE.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(
            EVIDENCE.write_text, json.dumps(evidence, indent=2, default=str), encoding="utf-8"
        )
        print("LIVE SOL/LUNA EVIDENCE", json.dumps(evidence, default=str)[:4000])
    assert evidence["children"], "the Sol parent never spawned its async child"
    (child,) = evidence["children"]
    assert child["lifecycle"] == AsyncSubagentLifecycle.COMPLETED.value, child
    assert "PONG" in (child["result_text"] or ""), child
    assert child["result_decision"] == "admit" and child["settled"], child
