"""FX-B-FEATURES (sprint B, first slice): one paid proof per model provider that a sealed
`mc.agent_configuration.v1` runs on the Deep Agents lane through the production factories.

- **Anthropic**: Claude Haiku 5.5 through `AnthropicExactModelFactory` with the todo list,
  context editing and call limits selected; the run must call `write_todos`, write a file
  through the Deep Agents file tools and finish.
- **OpenAI**: GPT-6 Luna through `OpenAIExactModelFactory` with the `openai.web_search`
  model tool; the run must carry a provider-executed search in its message content.

Both compile the agent exactly as the worker does (`materializer.prepare` then the adapter's
`_compile`) and invoke it in process with an in-memory saver; no Temporal or PostgreSQL. Gated
by `BELLABS_RUN_AGENT_CONFIGURATION_LIVE=1` and a key per provider (environment or the
repository `.env`, never printed). Every call is metered and appended to
`.scratch/agent-configuration/spend.jsonl`; a provider whose recorded spend has reached the
owner's ceiling (10 USD) refuses to start, and each proof asserts it cost under 1 USD.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from dotenv import dotenv_values
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import LLMResult
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from tests.acceptance.control_plane.test_wp_cp_040 import exact_fixture

from mission_control.adapters.deep_agents import (
    ExactComponentRegistry,
    ExactDeepAgentMaterializer,
    StateSandboxFactory,
    model_factory_for,
)
from mission_control.adapters.deep_agents.adapter import _compile
from mission_control.adapters.deep_agents.routes import AGENT_FEATURES
from mission_control.bootstrap.settings import PROJECT_ROOT
from mission_control.domain.capabilities.features import resolve_agent_configuration
from mission_control.domain.execution.contracts import DeepAgentExecutionBinding

LIVE_GATE = "BELLABS_RUN_AGENT_CONFIGURATION_LIVE"
OUTPUT_ROOT = PROJECT_ROOT / ".scratch" / "agent-configuration"
SPEND_LEDGER = OUTPUT_ROOT / "spend.jsonl"
CEILING_USD_PER_PROVIDER = 10.0
PROOF_BUDGET_USD = 1.0
# USD per 1M tokens: input, cached input, output. Anthropic Haiku 5.5 (prompts under 100K)
# and the owner's GPT-6 Luna (tests/fixtures/live_models.py).
PRICES: Mapping[str, tuple[float, float, float]] = {
    "claude-haiku-5-5": (0.10, 0.01, 0.50),
    "gpt-6-luna": (0.10, 0.01, 0.50),
}
KEY_VARIABLES = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}
MODELS = {"anthropic": "claude-haiku-5-5", "openai": "gpt-6-luna"}
SETTINGS: Mapping[str, dict[str, Any]] = {
    "anthropic": {"max_tokens": 2_000, "reasoning_effort": "low", "stream_usage": True},
    "openai": {"reasoning_effort": "low", "use_responses_api": True, "stream_usage": True},
}


def _key(provider: str) -> str:
    variable = KEY_VARIABLES[provider]
    key = os.environ.get(variable, "")
    if not key or key.startswith("deterministic-"):
        key = str(dotenv_values(PROJECT_ROOT / ".env").get(variable) or "")
    return key


def _require_live(provider: str) -> dict[str, str]:
    if os.environ.get(LIVE_GATE) != "1":
        pytest.skip(f"set {LIVE_GATE}=1 for the paid agent-configuration proofs")
    key = _key(provider)
    if not key:
        pytest.skip(f"{KEY_VARIABLES[provider]} is required (environment or repository .env)")
    spent = _spent(provider)
    if spent >= CEILING_USD_PER_PROVIDER:
        pytest.skip(f"{provider} spend {spent:.2f} USD has reached the ceiling")
    return {f"environment:{KEY_VARIABLES[provider]}": key}


def _spent(provider: str) -> float:
    if not SPEND_LEDGER.exists():
        return 0.0
    total = 0.0
    for line in SPEND_LEDGER.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if row.get("provider") == provider:
                total += float(row.get("usd") or 0.0)
    return total


class _Meter(BaseCallbackHandler):
    """Usage and price of every model call, in call order."""

    def __init__(self, model: str) -> None:
        self.model = model
        self.calls: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        usage: dict[str, Any] = {}
        for generations in response.generations:
            for generation in generations:
                found = getattr(getattr(generation, "message", None), "usage_metadata", None)
                if found:
                    usage = dict(found)
        rates = PRICES[self.model]
        inputs = int(usage.get("input_tokens") or 0)
        cached = int((usage.get("input_token_details") or {}).get("cache_read") or 0)
        outputs = int(usage.get("output_tokens") or 0)
        usd = ((inputs - cached) * rates[0] + cached * rates[1] + outputs * rates[2]) / 1e6
        with self._lock:
            self.calls.append(
                {
                    "input_tokens": inputs,
                    "cached_tokens": cached,
                    "output_tokens": outputs,
                    "usd": round(usd, 6),
                    "usage_missing": not usage,
                }
            )

    @property
    def usd(self) -> float:
        return round(sum(call["usd"] for call in self.calls), 6)


def _record(provider: str, fixture: str, meter: _Meter, **extra: Any) -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    with SPEND_LEDGER.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "at": datetime.now(UTC).isoformat(),
                    "provider": provider,
                    "model": meter.model,
                    "fixture": fixture,
                    "calls": len(meter.calls),
                    "usd": meter.usd,
                    **extra,
                },
                default=str,
            )
            + "\n"
        )


def _binding(
    provider: str,
    *,
    lane_features: dict[str, Any] | None,
    model_tools: dict[str, Any] | None,
) -> tuple[DeepAgentExecutionBinding, Any]:
    base, _profile, bundle = exact_fixture(model_settings=dict(SETTINGS[provider]))
    model = base.model.model_copy(update={"provider": provider, "model_name": MODELS[provider]})
    configuration, _notes = resolve_agent_configuration(
        AGENT_FEATURES,
        lane="deep_agents",
        model_provider=provider,  # type: ignore[arg-type]
        sandbox_backend=base.sandbox.backend,
        lane_features=lane_features,
        model_tools=model_tools,
    )
    binding = DeepAgentExecutionBinding.create(
        **{
            **base.model_dump(mode="python", exclude={"binding_digest"}),
            "model": model,
            "agent_configuration": configuration,
        }
    )
    return binding, bundle


def _metered_factory(provider: str, meter: _Meter) -> Any:
    production = model_factory_for(provider)

    def factory(binding: DeepAgentExecutionBinding, secrets: Any) -> BaseChatModel:
        model = production(binding, secrets)
        model.callbacks = [meter]
        return model

    return factory


async def _run(
    provider: str,
    *,
    fixture: str,
    prompt: str,
    lane_features: dict[str, Any] | None,
    model_tools: dict[str, Any] | None,
) -> tuple[dict[str, Any], _Meter, DeepAgentExecutionBinding]:
    secrets = _require_live(provider)
    binding, bundle = _binding(provider, lane_features=lane_features, model_tools=model_tools)
    meter = _Meter(MODELS[provider])
    registry = ExactComponentRegistry(
        model_factories={binding.model.ref.digest: _metered_factory(provider, meter)},
        skill_bundles={bundle.bundle_digest: bundle},
        sandbox_factories={binding.sandbox.ref.digest: StateSandboxFactory()},
        checkpointers={binding.checkpointer_ref.digest: InMemorySaver()},
        stores={binding.store_ref.digest: InMemoryStore()},
    )
    run_id = uuid4().hex[:12]
    try:
        async with ExactDeepAgentMaterializer(registry).prepare(binding, secrets) as materialized:
            agent = _compile(
                materialized,
                binding,
                system_prompt=(
                    "You are a Mission Control test agent. Do exactly what the task says, "
                    "using the tools named, then answer with the single word DONE."
                ),
                extra_middleware=[],
                name=f"fx-b-features-{provider}",
            )
            result = await agent.ainvoke(
                {"messages": [HumanMessage(content=prompt)], **materialized.initial_state},
                config={"configurable": {"thread_id": run_id}, "recursion_limit": 40},
            )
    finally:
        _record(provider, fixture, meter, run_id=run_id, binding_digest=binding.binding_digest)
    OUTPUT_ROOT.joinpath(f"{fixture}-{run_id}.json").write_text(
        json.dumps(
            {
                "binding_digest": binding.binding_digest,
                "agent_configuration": binding.agent_configuration.model_dump(mode="json"),  # type: ignore[union-attr]
                "messages": [message.model_dump(mode="json") for message in result["messages"]],
                "spend": {"calls": meter.calls, "usd": meter.usd},
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    return result, meter, binding


def _tool_calls(result: Mapping[str, Any]) -> list[str]:
    return [
        call["name"]
        for message in result["messages"]
        if isinstance(message, AIMessage)
        for call in message.tool_calls
    ]


@pytest.mark.asyncio
async def test_anthropic_haiku_runs_the_todo_list_context_editing_and_file_tools() -> None:
    result, meter, binding = await _run(
        "anthropic",
        fixture="FX-B-FEATURES-anthropic",
        prompt=(
            "First call write_todos with two todo items for this task. Then write the file "
            f"{binding_write_root()}/hello.md containing exactly the text: hello from haiku. "
            "Then answer DONE."
        ),
        lane_features={
            "todo_list": {},
            "context_editing": {"trigger_tokens": 50_000, "keep_tool_uses": 2},
            "call_limits": {"model_calls_per_run": 8, "tool_calls_per_run": 12},
        },
        model_tools=None,
    )
    calls = _tool_calls(result)
    assert "write_todos" in calls, calls
    assert "write_file" in calls, calls
    files = result.get("files") or {}
    assert any(path.endswith("/hello.md") for path in files), sorted(files)
    assert result.get("todos"), "the todo list state is empty"
    assert binding.agent_configuration is not None
    assert meter.calls and meter.usd < PROOF_BUDGET_USD, meter.calls


@pytest.mark.asyncio
async def test_openai_luna_runs_a_provider_executed_web_search() -> None:
    result, meter, _binding = await _run(
        "openai",
        fixture="FX-B-FEATURES-openai",
        prompt=(
            "Use web search exactly once to find the title of the English Wikipedia article "
            "about photosynthesis, then answer with that title followed by DONE."
        ),
        lane_features=None,
        model_tools={"openai": {"web_search": {"search_context_size": "low"}}},
    )
    searched = [
        block
        for message in result["messages"]
        if isinstance(message, AIMessage) and not isinstance(message.content, str)
        for block in message.content
        if isinstance(block, dict) and block.get("type") in {"web_search_call", "server_tool_call"}
    ]
    assert searched, [type(m).__name__ for m in result["messages"]]
    assert "web_search" not in _tool_calls(result), "a provider tool never enters the tool node"
    assert meter.calls and meter.usd < PROOF_BUDGET_USD, meter.calls


def binding_write_root() -> str:
    """The fixture workspace's writable path (the file tools allow writes only there)."""

    base, _profile, _bundle = exact_fixture()
    return base.workspace.exclusive_write_paths[0].rstrip("/")
