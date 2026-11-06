"""Builders: registry row + sealed configuration -> middleware, dict tools, model settings.

Each builder is a small function keyed by the row id. The context carries what a builder may
need and nothing else: the resolved backend (to know whether a sandbox exists), the model
provider, the resolved secrets (the OpenAI moderation client needs the key) and the
workspace root for shell sessions. Builders never read the manifest and never choose: the
configuration they receive is the sealed one.

Mechanisms:

- ``middleware`` rows append to the stack after Mission Control's own middleware, in
  registry rank order (stable step numbering). A row whose ``.name`` matches a stock Deep
  Agents middleware replaces it in place (``AnthropicPromptCachingMiddleware``).
- ``provider_tool`` rows return a dict the chat model binds; ``create_deep_agent`` sends it
  to the provider and keeps it out of the tool node.
- ``model_setting`` rows return constructor settings merged into the exact model component
  before the factory runs; Anthropic ``context_management`` edits from several rows merge.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from deepagents.backends.protocol import BackendProtocol
from deepagents.middleware.filesystem import FilesystemMiddleware, FilesystemPermission
from langchain.agents.middleware import (
    ClearToolUsesEdit,
    ContextEditingMiddleware,
    ModelCallLimitMiddleware,
    ShellToolMiddleware,
    TodoListMiddleware,
    ToolCallLimitMiddleware,
)
from langchain.agents.middleware._execution import DockerExecutionPolicy, HostExecutionPolicy
from langchain.agents.middleware.types import AgentMiddleware

from mission_control.adapters.deep_agents.routes import (
    AGENT_FEATURES,
    AnthropicBashConfig,
    AnthropicClearToolUsesConfig,
    AnthropicCodeExecutionConfig,
    AnthropicMemoryConfig,
    AnthropicPromptCachingConfig,
    AnthropicWebFetchConfig,
    AnthropicWebSearchConfig,
    OpenAICodeInterpreterConfig,
    OpenAICompactionConfig,
    OpenAIFileSearchConfig,
    OpenAIModerationConfig,
    OpenAIWebSearchConfig,
)
from mission_control.domain.capabilities.features import (
    AgentConfiguration,
    FeatureSelection,
    FeatureStatus,
)
from mission_control.domain.capabilities.features.deep_agents import (
    BashConfig,
    CallLimitsConfig,
    ContextEditingConfig,
    FilesystemConfig,
)
from mission_control.domain.execution.errors import DeepAgentMaterializationError

ProviderTool = dict[str, Any]


@dataclass(frozen=True)
class FeatureBuildContext:
    backend: BackendProtocol
    model_provider: str
    secrets: Mapping[str, str] = field(default_factory=dict)
    # Where host or Docker shell sessions keep their working directory.
    shell_workspace_root: Path | None = None


@dataclass(frozen=True)
class RealizedFeatures:
    """What one configuration adds: in stack order, bind order and merged settings."""

    middleware: tuple[AgentMiddleware[Any, Any, Any], ...] = ()
    provider_tools: tuple[ProviderTool, ...] = ()
    model_settings: dict[str, Any] = field(default_factory=dict)
    # Rows realized by nothing here: the stock stack already carries them, or the
    # compile-time receipt said the lane adds nothing (bash on the state backend).
    realized_by_stack: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Built:
    middleware: tuple[AgentMiddleware[Any, Any, Any], ...] = ()
    provider_tools: tuple[ProviderTool, ...] = ()
    model_settings: dict[str, Any] = field(default_factory=dict)
    by_stack: bool = False


Builder = Callable[[FeatureSelection, FeatureBuildContext], _Built]


def realize_agent_configuration(
    configuration: AgentConfiguration | None, context: FeatureBuildContext
) -> RealizedFeatures:
    """Every row of the configuration through its builder, in registry rank order.

    ``deep_agents.filesystem`` is skipped here: it needs the effective permissions the
    adapter computes at compile time (:func:`filesystem_replacement`).
    """

    if configuration is None:
        return RealizedFeatures()
    if configuration.model_provider != context.model_provider:
        raise DeepAgentMaterializationError(
            "agent configuration was sealed for model provider "
            f"{configuration.model_provider}, not {context.model_provider}"
        )
    middleware: list[AgentMiddleware[Any, Any, Any]] = []
    tools: list[ProviderTool] = []
    settings: dict[str, Any] = {}
    by_stack: list[str] = []
    for item in sorted(configuration.items, key=lambda it: (AGENT_FEATURES.get(it.id).rank, it.id)):
        if item.id == "deep_agents.filesystem":
            continue
        builder = _BUILDERS.get(item.id)
        if builder is None:
            raise DeepAgentMaterializationError(
                f"agent capability {item.id} has no builder on this worker"
            )
        built = builder(item, context)
        middleware.extend(built.middleware)
        tools.extend(built.provider_tools)
        _merge_settings(settings, built.model_settings, context.model_provider)
        if built.by_stack:
            by_stack.append(item.id)
    return RealizedFeatures(
        middleware=tuple(middleware),
        provider_tools=tuple(tools),
        model_settings=settings,
        realized_by_stack=tuple(by_stack),
    )


def filesystem_replacement(
    configuration: AgentConfiguration | None,
    backend: BackendProtocol,
    permissions: list[FilesystemPermission] | None,
) -> FilesystemMiddleware | None:
    """The configured ``FilesystemMiddleware`` that replaces the stock one by name, or None
    when the mission took the stock configuration (then deepagents builds it)."""

    if configuration is None:
        return None
    item = configuration.get("deep_agents.filesystem")
    if item is None:
        return None
    config = FilesystemConfig.model_validate(item.config)
    if config.is_stock:
        return None
    return FilesystemMiddleware(
        backend=backend,
        tools=list(config.tools) if config.tools is not None else None,
        tool_token_limit_before_evict=config.tool_token_limit_before_evict,
        human_message_token_limit_before_evict=config.human_message_token_limit_before_evict,
        _permissions=permissions,
    )


# -- Deep Agents lane features ------------------------------------------------------------


def _bash(item: FeatureSelection, context: FeatureBuildContext) -> _Built:
    config = BashConfig.model_validate(item.config)
    if config.execution == "sandbox":
        # The sandbox backend's `execute` tool is the shell; FilesystemMiddleware exposes
        # it only when the backend is a sandbox. Nothing to add either way.
        return _Built(by_stack=True)
    policy = _shell_policy(config)
    return _Built(
        middleware=(
            ShellToolMiddleware(
                workspace_root=context.shell_workspace_root,
                execution_policy=policy,
                tool_name="bash",
            ),
        )
    )


def _shell_policy(
    config: BashConfig | AnthropicBashConfig,
) -> HostExecutionPolicy | DockerExecutionPolicy:
    timeout = float(config.command_timeout_seconds)
    if config.execution == "docker":
        return DockerExecutionPolicy(
            command_timeout=timeout,
            max_output_lines=config.max_output_lines,
            image=config.image,
            network_enabled=False,
        )
    return HostExecutionPolicy(command_timeout=timeout, max_output_lines=config.max_output_lines)


def _todo_list(item: FeatureSelection, context: FeatureBuildContext) -> _Built:
    return _Built(middleware=(TodoListMiddleware(),))


def _context_editing(item: FeatureSelection, context: FeatureBuildContext) -> _Built:
    config = ContextEditingConfig.model_validate(item.config)
    edit = ClearToolUsesEdit(
        trigger=config.trigger_tokens,
        clear_at_least=config.clear_at_least_tokens,
        keep=config.keep_tool_uses,
        clear_tool_inputs=config.clear_tool_inputs,
        exclude_tools=list(config.exclude_tools),
    )
    return _Built(
        middleware=(
            ContextEditingMiddleware(edits=[edit], token_count_method=config.token_count_method),
        )
    )


def _summarization(item: FeatureSelection, context: FeatureBuildContext) -> _Built:
    # Applied by the materializer to the observed summarizer's trigger and keep.
    return _Built(by_stack=True)


def _call_limits(item: FeatureSelection, context: FeatureBuildContext) -> _Built:
    config = CallLimitsConfig.model_validate(item.config)
    middleware: list[AgentMiddleware[Any, Any, Any]] = []
    if config.model_calls_per_run is not None or config.model_calls_per_thread is not None:
        middleware.append(
            ModelCallLimitMiddleware(
                run_limit=config.model_calls_per_run,
                thread_limit=config.model_calls_per_thread,
                exit_behavior=config.exit_behavior,
            )
        )
    if config.tool_calls_per_run is not None or config.tool_calls_per_thread is not None:
        middleware.append(
            ToolCallLimitMiddleware(
                run_limit=config.tool_calls_per_run,
                thread_limit=config.tool_calls_per_thread,
                exit_behavior=config.exit_behavior,
            )
        )
    return _Built(middleware=tuple(middleware))


# -- OpenAI model tools -------------------------------------------------------------------


def _openai_web_search(item: FeatureSelection, context: FeatureBuildContext) -> _Built:
    config = OpenAIWebSearchConfig.model_validate(item.config)
    tool: ProviderTool = {"type": "web_search", "search_context_size": config.search_context_size}
    if config.allowed_domains:
        tool["filters"] = {"allowed_domains": list(config.allowed_domains)}
    return _Built(provider_tools=(tool,))


def _openai_file_search(item: FeatureSelection, context: FeatureBuildContext) -> _Built:
    config = OpenAIFileSearchConfig.model_validate(item.config)
    tool: ProviderTool = {"type": "file_search", "vector_store_ids": list(config.vector_store_ids)}
    if config.max_num_results is not None:
        tool["max_num_results"] = config.max_num_results
    return _Built(provider_tools=(tool,))


def _openai_code_interpreter(item: FeatureSelection, context: FeatureBuildContext) -> _Built:
    config = OpenAICodeInterpreterConfig.model_validate(item.config)
    return _Built(
        provider_tools=({"type": "code_interpreter", "container": {"type": config.container}},)
    )


def _openai_compaction(item: FeatureSelection, context: FeatureBuildContext) -> _Built:
    config = OpenAICompactionConfig.model_validate(item.config)
    return _Built(
        model_settings={
            "context_management": [
                {"type": "compaction", "compact_threshold": config.compact_threshold}
            ]
        }
    )


def _openai_moderation(item: FeatureSelection, context: FeatureBuildContext) -> _Built:
    from langchain_openai.middleware import OpenAIModerationMiddleware
    from openai import AsyncOpenAI, OpenAI

    config = OpenAIModerationConfig.model_validate(item.config)
    api_key = context.secrets.get("environment:OPENAI_API_KEY")
    if not api_key:
        raise DeepAgentMaterializationError(
            "openai.moderation needs the OpenAI credential reference resolved"
        )
    return _Built(
        middleware=(
            OpenAIModerationMiddleware(
                model=config.model,  # type: ignore[arg-type]
                check_input=config.check_input,
                check_output=config.check_output,
                check_tool_results=config.check_tool_results,
                exit_behavior=config.exit_behavior,
                client=OpenAI(api_key=api_key, max_retries=0),
                async_client=AsyncOpenAI(api_key=api_key, max_retries=0),
            ),
        )
    )


# -- Anthropic model tools ----------------------------------------------------------------


def _anthropic_prompt_caching(item: FeatureSelection, context: FeatureBuildContext) -> _Built:
    from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware

    config = AnthropicPromptCachingConfig.model_validate(item.config)
    if config == AnthropicPromptCachingConfig():
        # deepagents already installs the 5-minute cache on every agent.
        return _Built(by_stack=True)
    return _Built(
        middleware=(
            AnthropicPromptCachingMiddleware(
                ttl=config.ttl,
                min_messages_to_cache=config.min_messages_to_cache,
                unsupported_model_behavior="ignore",
            ),
        )
    )


def _anthropic_web_search(item: FeatureSelection, context: FeatureBuildContext) -> _Built:
    config = AnthropicWebSearchConfig.model_validate(item.config)
    tool: ProviderTool = {
        "type": config.tool_version,
        "name": "web_search",
        "max_uses": config.max_uses,
    }
    if config.allowed_domains:
        tool["allowed_domains"] = list(config.allowed_domains)
    if config.blocked_domains:
        tool["blocked_domains"] = list(config.blocked_domains)
    return _Built(provider_tools=(tool,))


def _anthropic_web_fetch(item: FeatureSelection, context: FeatureBuildContext) -> _Built:
    config = AnthropicWebFetchConfig.model_validate(item.config)
    tool: ProviderTool = {
        "type": config.tool_version,
        "name": "web_fetch",
        "max_uses": config.max_uses,
    }
    if config.allowed_domains:
        tool["allowed_domains"] = list(config.allowed_domains)
    if config.max_content_tokens is not None:
        tool["max_content_tokens"] = config.max_content_tokens
    return _Built(provider_tools=(tool,))


def _anthropic_code_execution(item: FeatureSelection, context: FeatureBuildContext) -> _Built:
    config = AnthropicCodeExecutionConfig.model_validate(item.config)
    return _Built(provider_tools=({"type": config.tool_version, "name": "code_execution"},))


def _anthropic_bash(item: FeatureSelection, context: FeatureBuildContext) -> _Built:
    from langchain_anthropic.middleware import ClaudeBashToolMiddleware

    config = AnthropicBashConfig.model_validate(item.config)
    policy = _shell_policy(config)
    return _Built(
        middleware=(
            ClaudeBashToolMiddleware(
                workspace_root=(
                    str(context.shell_workspace_root)
                    if context.shell_workspace_root is not None
                    else None
                ),
                execution_policy=policy,
            ),
        )
    )


def _anthropic_memory(item: FeatureSelection, context: FeatureBuildContext) -> _Built:
    from langchain_anthropic.middleware import StateClaudeMemoryMiddleware

    config = AnthropicMemoryConfig.model_validate(item.config)
    return _Built(
        middleware=(
            StateClaudeMemoryMiddleware(allowed_path_prefixes=list(config.allowed_path_prefixes)),
        )
    )


def _anthropic_clear_tool_uses(item: FeatureSelection, context: FeatureBuildContext) -> _Built:
    config = AnthropicClearToolUsesConfig.model_validate(item.config)
    edit: dict[str, Any] = {
        "type": "clear_tool_uses_20250919",
        "trigger": {"type": "input_tokens", "value": config.trigger_tokens},
        "keep": {"type": "tool_uses", "value": config.keep_tool_uses},
        "clear_tool_inputs": config.clear_tool_inputs,
    }
    return _Built(model_settings={"context_management": {"edits": [edit]}})


def _anthropic_compaction(item: FeatureSelection, context: FeatureBuildContext) -> _Built:
    return _Built(model_settings={"context_management": {"edits": [{"type": "compact_20260112"}]}})


def _merge_settings(target: dict[str, Any], extra: Mapping[str, Any], provider: str) -> None:
    for key, value in extra.items():
        if key == "context_management" and provider == "anthropic" and key in target:
            # Several Anthropic rows contribute edits to one context_management block.
            target[key] = {"edits": [*target[key]["edits"], *value["edits"]]}
        elif key in target:
            raise DeepAgentMaterializationError(
                f"two agent capabilities set the model setting {key!r}"
            )
        else:
            target[key] = value


_BUILDERS: dict[str, Builder] = {
    "deep_agents.bash": _bash,
    "deep_agents.todo_list": _todo_list,
    "deep_agents.context_editing": _context_editing,
    "deep_agents.summarization": _summarization,
    "deep_agents.call_limits": _call_limits,
    "openai.web_search": _openai_web_search,
    "openai.file_search": _openai_file_search,
    "openai.code_interpreter": _openai_code_interpreter,
    "openai.compaction": _openai_compaction,
    "openai.moderation": _openai_moderation,
    "anthropic.prompt_caching": _anthropic_prompt_caching,
    "anthropic.web_search": _anthropic_web_search,
    "anthropic.web_fetch": _anthropic_web_fetch,
    "anthropic.code_execution": _anthropic_code_execution,
    "anthropic.bash": _anthropic_bash,
    "anthropic.memory": _anthropic_memory,
    "anthropic.clear_tool_uses": _anthropic_clear_tool_uses,
    "anthropic.compaction": _anthropic_compaction,
}


def builder_coverage() -> tuple[str, ...]:
    """Available registry rows without a builder (a test keeps this empty)."""

    return tuple(
        row.id
        for row in AGENT_FEATURES
        if row.status is FeatureStatus.AVAILABLE
        and row.id != "deep_agents.filesystem"
        and row.id not in _BUILDERS
    )


__all__ = [
    "FeatureBuildContext",
    "RealizedFeatures",
    "builder_coverage",
    "filesystem_replacement",
    "realize_agent_configuration",
]
