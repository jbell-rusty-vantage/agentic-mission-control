"""The materializer realizes a sealed `mc.agent_configuration.v1` (sprint B): middleware rows
join the stack, provider-tool rows ride as dict tools into `create_deep_agent`, model-setting
rows reach the exact model factory, and the Anthropic factory builds `ChatAnthropic` from the
same exact component shape the OpenAI factory reads. Nothing here calls a provider."""

from __future__ import annotations

from typing import Any

import pytest
from deepagents.middleware.filesystem import FilesystemMiddleware
from langchain.agents.middleware import (
    ContextEditingMiddleware,
    ModelCallLimitMiddleware,
    TodoListMiddleware,
    ToolCallLimitMiddleware,
)
from langchain_anthropic import ChatAnthropic
from langchain_anthropic.middleware import (
    AnthropicPromptCachingMiddleware,
    StateClaudeMemoryMiddleware,
)
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from mission_control.adapters.deep_agents import (
    AnthropicExactModelFactory,
    ExactComponentRegistry,
    ExactDeepAgentMaterializer,
    OpenAIExactModelFactory,
    StateSandboxFactory,
    model_factory_for,
)
from mission_control.adapters.deep_agents.adapter import _compile
from mission_control.adapters.deep_agents.features import filesystem_replacement
from mission_control.adapters.deep_agents.routes import AGENT_FEATURES
from mission_control.domain.capabilities.features import (
    AgentConfiguration,
    resolve_agent_configuration,
)
from mission_control.domain.execution.contracts import DeepAgentExecutionBinding
from mission_control.domain.execution.errors import DeepAgentMaterializationError
from tests.acceptance.control_plane.test_wp_cp_040 import SkillReadingModel, exact_fixture

ANTHROPIC_SECRET = {"environment:ANTHROPIC_API_KEY": "test-anthropic-key"}


def _configured(
    *,
    provider: str = "openai",
    lane_features: dict[str, Any] | None = None,
    model_tools: dict[str, Any] | None = None,
    model_settings: dict[str, Any] | None = None,
) -> tuple[DeepAgentExecutionBinding, Any, AgentConfiguration]:
    binding, _profile, bundle = exact_fixture(model_settings=model_settings)
    model = binding.model.model_copy(
        update={
            "provider": provider,
            "model_name": "claude-haiku-5-5" if provider == "anthropic" else "fixture-model",
        }
    )
    configuration, _notes = resolve_agent_configuration(
        AGENT_FEATURES,
        lane="deep_agents",
        model_provider=provider,  # type: ignore[arg-type]
        sandbox_backend=binding.sandbox.backend,
        lane_features=lane_features,
        model_tools=model_tools,
    )
    rebound = DeepAgentExecutionBinding.create(
        **{
            **binding.model_dump(mode="python", exclude={"binding_digest"}),
            "model": model,
            "agent_configuration": configuration,
        }
    )
    return rebound, bundle, configuration


class _CapturingFactory:
    """A model factory that records the exact component it was handed."""

    def __init__(self) -> None:
        self.bindings: list[DeepAgentExecutionBinding] = []

    def __call__(self, binding: DeepAgentExecutionBinding, secrets: Any) -> BaseChatModel:
        del secrets
        self.bindings.append(binding)
        return SkillReadingModel()


def _registry(binding: Any, bundle: Any, factory: Any) -> ExactComponentRegistry:
    return ExactComponentRegistry(
        model_factories={binding.model.ref.digest: factory},
        skill_bundles={bundle.bundle_digest: bundle},
        sandbox_factories={binding.sandbox.ref.digest: StateSandboxFactory()},
        checkpointers={binding.checkpointer_ref.digest: InMemorySaver()},
        stores={binding.store_ref.digest: InMemoryStore()},
    )


@pytest.mark.asyncio
async def test_middleware_rows_join_the_stack_in_rank_order() -> None:
    binding, bundle, _configuration = _configured(
        lane_features={
            "call_limits": {"model_calls_per_run": 4, "tool_calls_per_run": 9},
            "context_editing": {"trigger_tokens": 50_000},
            "todo_list": {},
        }
    )
    factory = _CapturingFactory()
    async with ExactDeepAgentMaterializer(_registry(binding, bundle, factory)).prepare(
        binding, {}
    ) as materialized:
        added = [type(item) for item in materialized.middleware[3:]]
        assert added == [
            TodoListMiddleware,
            ContextEditingMiddleware,
            ModelCallLimitMiddleware,
            ToolCallLimitMiddleware,
        ]
        assert materialized.provider_tools == ()
        facts = materialized.manifest_facts["agent_configuration"]
        assert facts["digest"] == binding.agent_configuration.configuration_digest  # type: ignore[union-attr]
        assert [row["id"] for row in facts["items"]] == [
            "deep_agents.filesystem",
            "deep_agents.todo_list",
            "deep_agents.context_editing",
            "deep_agents.call_limits",
        ]
        # The stock filesystem configuration is left to deepagents (no replacement).
        assert (
            filesystem_replacement(binding.agent_configuration, materialized.backend, None) is None
        )
    # No model-setting row: the factory saw the pinned settings unchanged.
    assert factory.bindings[0].model.settings == binding.model.settings


@pytest.mark.asyncio
async def test_provider_tools_and_model_settings_reach_the_model() -> None:
    binding, bundle, _configuration = _configured(
        model_tools={
            "openai": {
                "web_search": {"search_context_size": "low", "allowed_domains": ["who.int"]},
                "code_interpreter": {},
                "compaction": {"compact_threshold": 120_000},
            }
        }
    )
    factory = _CapturingFactory()
    async with ExactDeepAgentMaterializer(_registry(binding, bundle, factory)).prepare(
        binding, {}
    ) as materialized:
        assert materialized.provider_tools == (
            {
                "type": "web_search",
                "search_context_size": "low",
                "filters": {"allowed_domains": ["who.int"]},
            },
            {"type": "code_interpreter", "container": {"type": "auto"}},
        )
        agent = _compile(
            materialized,
            binding,
            system_prompt="fixture",
            extra_middleware=[],
            name="belllabs-agent-configuration",
        )
        assert agent is not None
    assert factory.bindings[0].model.settings["context_management"] == [
        {"type": "compaction", "compact_threshold": 120_000}
    ]
    # The sealed binding itself is untouched: settings are a run-local view for the factory.
    assert "context_management" not in binding.model.settings


@pytest.mark.asyncio
async def test_anthropic_rows_merge_context_management_and_replace_caching_by_name() -> None:
    binding, bundle, _configuration = _configured(
        provider="anthropic",
        model_tools={
            "anthropic": {
                "clear_tool_uses": {"trigger_tokens": 80_000, "keep_tool_uses": 2},
                "compaction": {},
                "prompt_caching": {"ttl": "1h"},
                "memory": {},
                "web_search": {"tool_version": "web_search_20250305", "max_uses": 1},
            }
        },
    )
    factory = _CapturingFactory()
    async with ExactDeepAgentMaterializer(_registry(binding, bundle, factory)).prepare(
        binding, ANTHROPIC_SECRET
    ) as materialized:
        added = materialized.middleware[3:]
        assert [type(item) for item in added] == [
            AnthropicPromptCachingMiddleware,
            StateClaudeMemoryMiddleware,
        ]
        caching = added[0]
        assert isinstance(caching, AnthropicPromptCachingMiddleware)
        assert caching.name == "AnthropicPromptCachingMiddleware"
        assert materialized.provider_tools == (
            {"type": "web_search_20250305", "name": "web_search", "max_uses": 1},
        )
    assert factory.bindings[0].model.settings["context_management"] == {
        "edits": [
            {
                "type": "clear_tool_uses_20250919",
                "trigger": {"type": "input_tokens", "value": 80_000},
                "keep": {"type": "tool_uses", "value": 2},
                "clear_tool_inputs": False,
            },
            {"type": "compact_20260112"},
        ]
    }


def test_a_configured_filesystem_replaces_the_stock_middleware_with_the_permissions() -> None:
    binding, _bundle, configuration = _configured(
        lane_features={
            "filesystem": {
                "tools": ["ls", "read_file", "grep"],
                "tool_token_limit_before_evict": 5_000,
            }
        }
    )
    from deepagents.backends import StateBackend

    replacement = filesystem_replacement(configuration, StateBackend(), permissions=[])
    assert isinstance(replacement, FilesystemMiddleware)
    assert replacement.name == "FilesystemMiddleware"
    assert {tool.name for tool in replacement.tools} == {"ls", "read_file", "grep"}
    del binding


def test_the_anthropic_factory_translates_neutral_settings_and_refuses_foreign_ones() -> None:
    binding, _bundle, _configuration = _configured(
        provider="anthropic",
        model_settings={"max_completion_tokens": 3_000, "reasoning_effort": "minimal"},
    )
    model = AnthropicExactModelFactory()(binding, ANTHROPIC_SECRET)
    assert isinstance(model, ChatAnthropic)
    assert model.model == "claude-haiku-5-5"
    assert model.max_tokens == 3_000
    assert model.reasoning_effort == "low"
    assert model.max_retries == 0
    assert model.anthropic_api_key.get_secret_value() == "test-anthropic-key"
    defaulted = AnthropicExactModelFactory()(_configured(provider="anthropic")[0], ANTHROPIC_SECRET)
    assert isinstance(defaulted, ChatAnthropic)
    assert defaulted.max_tokens == AnthropicExactModelFactory.default_max_tokens
    foreign, _b, _c = _configured(provider="anthropic", model_settings={"verbosity": "low"})
    with pytest.raises(DeepAgentMaterializationError, match="unsupported exact Anthropic"):
        AnthropicExactModelFactory()(foreign, ANTHROPIC_SECRET)
    with pytest.raises(DeepAgentMaterializationError, match="credential reference"):
        AnthropicExactModelFactory()(binding, {})


def test_factories_are_chosen_by_provider() -> None:
    assert isinstance(model_factory_for("openai"), OpenAIExactModelFactory)
    assert isinstance(model_factory_for("anthropic"), AnthropicExactModelFactory)
    with pytest.raises(DeepAgentMaterializationError, match="no exact model factory"):
        model_factory_for("mistral")


@pytest.mark.asyncio
async def test_a_configuration_sealed_for_another_provider_is_a_materialization_error() -> None:
    binding, bundle, configuration = _configured(provider="openai")
    drifted = binding.model_copy(
        update={"model": binding.model.model_copy(update={"provider": "anthropic"})}
    )
    with pytest.raises(DeepAgentMaterializationError, match="sealed for model provider"):
        async with ExactDeepAgentMaterializer(
            _registry(drifted, bundle, _CapturingFactory())
        ).prepare(drifted, ANTHROPIC_SECRET):
            pass
    del configuration
