"""Builders, constants and fakes that other test files import.

Moved from tests/acceptance/mission_control/test_manifest_async_child.py.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from mission_control.application.authoring.manifest_launch_inputs import (
    AsyncSubagentGraphBinding,
    ManifestLaunchInputAuthor,
)
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.manifest import canonical_manifest_bytes, load_manifest_yaml
from tests.fixtures.catalog.fast_track_catalog import fixture_definitions
from tests.fixtures.manifest_runtime import ChainCognition, ChainScript
from tests.fixtures.mission_control_local_agent_server import deterministic_child_definition
from tests.fixtures.rrm009_cancellation import TOKEN_ENV
from tests.fixtures.rrm009_production_stack import (
    AGENT_COGNITIVE_QUEUE,
    TechnicalBinding,
    call_usage,
)
from tests.support.manifest_runtime import MISSION_2, evaluable, pubmed_digest
from tests.support.model_catalog import model_binding
from tests.support.models import ScriptedChatModel
from tests.support.stack import ProductionStack
from tests.unit.authoring.manifest_launch_fixture import (
    deep_agents_chain,
    fixture_bindings,
    pubmed_bound,
)

ASYNC_PROFILE_ID = "subagent.async-child"
ASYNC_CHILD = "async-child"
OBJECTIVE = "Reply with exactly PONG."
POLICY = "policy:async-result:technical-child@1"


@dataclass(kw_only=True)
class SpawningChainCognition(ChainCognition):
    """`ChainCognition` that spawns the manifest's async child once, in iteration 1 of the executor,
    then does its scripted work as if the spawn had not happened."""

    @property
    def _llm_type(self) -> str:
        return "p1-async-spawning-chain"

    def _spawn_id(self) -> str:
        return "p1-spawn-" + sha256_digest(self.operation_id)[7:23]

    def _reply(self, messages: list[BaseMessage]) -> AIMessage:
        role = self.operation_id.rsplit("/", 1)[-1].split(":", 1)[0]
        first_iteration = "goal-iteration/1/" in self.operation_id
        spawned = any(
            isinstance(item, ToolMessage) and item.tool_call_id == self._spawn_id()
            for item in messages
        )
        if role == "executor" and first_iteration and not spawned:
            self._record("parent", messages)
            return AIMessage(
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

    def parent(bound: Any, _secrets: Any) -> ScriptedChatModel:
        return SpawningChainCognition(
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
        ).model()

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
