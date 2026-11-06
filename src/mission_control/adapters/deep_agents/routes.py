"""The Deep Agents lane's model routes: per vendor, how the lane reaches the model and which
vendor features it realizes (ADR-0063, design §3; OC-R6 / OVE-200).

A Model Profile names a vendor and a model id and no lane (`deployments/<app>/models.toml`); this
lane's describe declares one :class:`ModelRoute` per vendor (`DEEP_AGENTS_MODEL_ROUTES`), and the
resolver refuses a profile whose vendor has no route here (`MODEL_ROUTE_UNSUPPORTED`). What a route
means on this lane lives in this module, not in the core:

- the **mechanism**: an in-process LangChain chat model built by the exact model factory for the
  pinned vendor (`materializer.ExactModelFactory`: `ChatAnthropic` / `ChatOpenAI`);
- the **vendor features** (the ``anthropic.*`` and ``openai.*`` rows, moved here from
  ``domain/capabilities/features``): server tools, langchain-<vendor> middleware and model settings
  that are valid only when the agent's model is that vendor's. ``VENDOR_FEATURES`` maps
  ``(vendor, feature name)`` to its row, and ``adapters/deep_agents/features/builders.py`` turns
  each row into its middleware, dict tool or model setting.

``AGENT_FEATURES`` is the lane's whole selectable registry: the Deep Agents lane features (still
declared beside the registry vocabulary in ``domain/capabilities/features/deep_agents.py``, which
``provider_options`` validates at manifest compile) plus these vendor rows. The core keeps no vendor
feature registry: a ``model_tools`` selection is validated here, at launch, by the lane.

Anthropic rows: server tools (web search, web fetch, code execution) are dict tools the Messages
API runs itself; their evidence is in the model message's content blocks. Client tools (bash,
memory) are Anthropic-defined tool descriptors whose execution the langchain-anthropic middleware
provides on the worker; they pass through the LangGraph tool node. Context management is a model
setting on ``ChatAnthropic``.

OpenAI rows: a Responses built-in is a dict tool bound beside the agent's own tools. The provider
executes it: the call never enters the LangGraph tool node, so hooks, call limits, retries and HITL
do not see it (``observability=server_side``); its evidence is the ``server_tool_call`` and
``server_tool_result`` content blocks of the model message, which the frame recorder keeps.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final, Literal

from pydantic import Field

from mission_control.domain.capabilities.features.deep_agents import DEEP_AGENTS_FEATURES
from mission_control.domain.capabilities.features.registry import (
    CapabilityDomain,
    CapabilityFacet,
    EmptyConfig,
    FeatureAxis,
    FeatureConfig,
    FeatureDefinition,
    FeatureRegistry,
    FeatureStatus,
    Mechanism,
    Observability,
    Provenance,
)
from mission_control.domain.resolution.configuration import Vendor
from mission_control.domain.resolution.profiles import ModelRoute

# How this lane reaches each vendor (the describe's `model_routes`): both in process, through the
# exact model factory of the pinned vendor (`materializer.MODEL_FACTORIES`). W1 D16/D18: both
# routes realize the three structured-output strategies (`materializer.response_format_for`):
# LangChain's `ToolStrategy` (forced tool choice), `ProviderStrategy` (`output_config.format`
# through langchain-anthropic 1.5.4, `response_format` json_schema through langchain-openai
# 1.3.4) and `tool_auto` (`ToolStrategy` bound with tool choice auto, host-enforced:
# `structured_response.py`).
DEEP_AGENTS_MODEL_ROUTES: Final[tuple[ModelRoute, ...]] = (
    ModelRoute(
        vendor="anthropic",
        verdict="native",
        mechanism="chat_anthropic_factory",
        structured_output=("tool_forced", "provider_native", "tool_auto"),
    ),
    ModelRoute(
        vendor="openai",
        verdict="native",
        mechanism="chat_openai_factory",
        structured_output=("tool_forced", "provider_native", "tool_auto"),
    ),
)


# -- anthropic.* --------------------------------------------------------------------------------


class AnthropicWebSearchConfig(FeatureConfig):
    """``anthropic.web_search``. ``tool_version`` names the dated tool type; the 2026-02-09
    variant (dynamic filtering) needs Opus 4.6+, Sonnet 4.6+ or Sonnet/Opus 5.x, the 2025-03-05
    variant runs on every current model."""

    tool_version: Literal["web_search_20260209", "web_search_20250305"] = "web_search_20260209"
    max_uses: int = Field(default=5, ge=1, le=50)
    allowed_domains: tuple[str, ...] = Field(default=(), max_length=64)
    blocked_domains: tuple[str, ...] = Field(default=(), max_length=64)


class AnthropicWebFetchConfig(FeatureConfig):
    """``anthropic.web_fetch``: fetch URLs already present in the conversation."""

    tool_version: Literal["web_fetch_20260209", "web_fetch_20250910"] = "web_fetch_20260209"
    max_uses: int = Field(default=5, ge=1, le=50)
    allowed_domains: tuple[str, ...] = Field(default=(), max_length=64)
    max_content_tokens: int | None = Field(default=None, ge=1_000, le=200_000)


class AnthropicCodeExecutionConfig(FeatureConfig):
    """``anthropic.code_execution``: Anthropic-hosted code execution (no internet)."""

    tool_version: Literal["code_execution_20260521", "code_execution_20260120"] = (
        "code_execution_20260521"
    )


class AnthropicBashConfig(FeatureConfig):
    """``anthropic.bash``: Claude's native ``bash`` tool descriptor with a worker-side shell
    (ClaudeBashToolMiddleware). ``docker`` runs the session in a throwaway container with the
    network off; ``host`` runs it on the worker (development only)."""

    execution: Literal["docker", "host"] = "docker"
    command_timeout_seconds: int = Field(default=120, ge=1, le=3_600)
    max_output_lines: int = Field(default=200, ge=1, le=10_000)
    image: str = Field(default="python:3.12-slim", min_length=1, max_length=256)


class AnthropicMemoryConfig(FeatureConfig):
    """``anthropic.memory``: Claude's ``memory`` tool over the agent's graph state
    (StateClaudeMemoryMiddleware). ``allowed_path_prefixes`` confines where it may write."""

    allowed_path_prefixes: tuple[str, ...] = Field(default=("/memories",), min_length=1)


class AnthropicClearToolUsesConfig(FeatureConfig):
    """``anthropic.clear_tool_uses``: server-side context editing
    (``clear_tool_uses_20250919``) once the input passes ``trigger_tokens``."""

    trigger_tokens: int = Field(default=100_000, ge=1_000, le=1_000_000)
    keep_tool_uses: int = Field(default=3, ge=0, le=1_000)
    clear_tool_inputs: bool = False


class AnthropicCompactionConfig(FeatureConfig):
    """``anthropic.compaction``: server-side compaction (``compact_20260112``, beta)."""


class AnthropicPromptCachingConfig(FeatureConfig):
    """``anthropic.prompt_caching``: the cache breakpoints deepagents places on every call.
    ``ttl`` lengthens the cache lifetime; the stock 5-minute cache needs no setting."""

    ttl: Literal["5m", "1h"] = "5m"
    min_messages_to_cache: int = Field(default=0, ge=0, le=1_000)


ANTHROPIC_MODEL_TOOLS: tuple[FeatureDefinition, ...] = (
    FeatureDefinition(
        id="anthropic.prompt_caching",
        axis=FeatureAxis.MODEL_TOOL,
        model_provider="anthropic",
        category=CapabilityDomain.CONTEXT_MANAGEMENT,
        facet=CapabilityFacet.PROMPT_CACHING,
        provenance=Provenance.LANGCHAIN_ANTHROPIC,
        mechanism=Mechanism.MIDDLEWARE,
        observability=Observability.MODEL_SETTINGS,
        default=True,
        config_model=AnthropicPromptCachingConfig,
        summary=(
            "Anthropic prompt caching on every model call (AnthropicPromptCachingMiddleware, "
            "already in the Deep Agents default stack). Configure the cache TTL."
        ),
        rank=300,
    ),
    FeatureDefinition(
        id="anthropic.web_search",
        axis=FeatureAxis.MODEL_TOOL,
        model_provider="anthropic",
        category=CapabilityDomain.TOOLING,
        facet=CapabilityFacet.WEB,
        provenance=Provenance.ANTHROPIC_MESSAGES,
        mechanism=Mechanism.PROVIDER_TOOL,
        observability=Observability.SERVER_SIDE,
        config_model=AnthropicWebSearchConfig,
        summary=(
            "Anthropic-hosted web search (server tool web_search). Provider-executed; "
            "results arrive as web_search_tool_result blocks with citations."
        ),
        rank=310,
    ),
    FeatureDefinition(
        id="anthropic.web_fetch",
        axis=FeatureAxis.MODEL_TOOL,
        model_provider="anthropic",
        category=CapabilityDomain.TOOLING,
        facet=CapabilityFacet.WEB,
        provenance=Provenance.ANTHROPIC_MESSAGES,
        mechanism=Mechanism.PROVIDER_TOOL,
        observability=Observability.SERVER_SIDE,
        config_model=AnthropicWebFetchConfig,
        summary=(
            "Anthropic-hosted page fetch (server tool web_fetch) for URLs already in the "
            "conversation. Provider-executed."
        ),
        rank=320,
    ),
    FeatureDefinition(
        id="anthropic.code_execution",
        axis=FeatureAxis.MODEL_TOOL,
        model_provider="anthropic",
        category=CapabilityDomain.TOOLING,
        facet=CapabilityFacet.CODE_EXECUTION,
        provenance=Provenance.ANTHROPIC_MESSAGES,
        mechanism=Mechanism.PROVIDER_TOOL,
        observability=Observability.SERVER_SIDE,
        config_model=AnthropicCodeExecutionConfig,
        summary=(
            "Anthropic-hosted code execution (server tool code_execution, no internet). "
            "Provider-executed; distinct from the lane's sandbox."
        ),
        rank=330,
    ),
    FeatureDefinition(
        id="anthropic.bash",
        axis=FeatureAxis.MODEL_TOOL,
        model_provider="anthropic",
        category=CapabilityDomain.TOOLING,
        facet=CapabilityFacet.SHELL,
        provenance=Provenance.LANGCHAIN_ANTHROPIC,
        mechanism=Mechanism.MIDDLEWARE,
        observability=Observability.TOOL_NODE,
        adds_graph_nodes=True,
        config_model=AnthropicBashConfig,
        summary=(
            "Claude's native bash tool descriptor backed by a worker-side shell session "
            "(ClaudeBashToolMiddleware), in Docker by default."
        ),
        rank=340,
    ),
    FeatureDefinition(
        id="anthropic.memory",
        axis=FeatureAxis.MODEL_TOOL,
        model_provider="anthropic",
        category=CapabilityDomain.CONTEXT_MANAGEMENT,
        facet=CapabilityFacet.MEMORY,
        provenance=Provenance.LANGCHAIN_ANTHROPIC,
        mechanism=Mechanism.MIDDLEWARE,
        observability=Observability.TOOL_NODE,
        config_model=AnthropicMemoryConfig,
        summary=(
            "Claude's memory tool (memory_20250818) with the memory directory kept in graph "
            "state (StateClaudeMemoryMiddleware); the model records progress it can reread."
        ),
        rank=350,
    ),
    FeatureDefinition(
        id="anthropic.clear_tool_uses",
        axis=FeatureAxis.MODEL_TOOL,
        model_provider="anthropic",
        category=CapabilityDomain.CONTEXT_MANAGEMENT,
        facet=CapabilityFacet.CONTEXT_EDITING,
        provenance=Provenance.ANTHROPIC_MESSAGES,
        mechanism=Mechanism.MODEL_SETTING,
        observability=Observability.MODEL_SETTINGS,
        config_model=AnthropicClearToolUsesConfig,
        summary=(
            "Server-side context editing: the API clears old tool results past a token "
            "trigger (context_management clear_tool_uses_20250919). A model setting."
        ),
        rank=360,
    ),
    FeatureDefinition(
        id="anthropic.compaction",
        axis=FeatureAxis.MODEL_TOOL,
        model_provider="anthropic",
        category=CapabilityDomain.CONTEXT_MANAGEMENT,
        facet=CapabilityFacet.COMPACTION,
        provenance=Provenance.ANTHROPIC_MESSAGES,
        mechanism=Mechanism.MODEL_SETTING,
        observability=Observability.MODEL_SETTINGS,
        config_model=AnthropicCompactionConfig,
        summary=(
            "Server-side compaction of the conversation (context_management compact_20260112, "
            "beta). The compaction blocks stay in history. A model setting."
        ),
        rank=370,
    ),
    FeatureDefinition(
        id="anthropic.text_editor",
        axis=FeatureAxis.MODEL_TOOL,
        model_provider="anthropic",
        category=CapabilityDomain.TOOLING,
        facet=CapabilityFacet.FILESYSTEM,
        provenance=Provenance.LANGCHAIN_ANTHROPIC,
        mechanism=Mechanism.MIDDLEWARE,
        observability=Observability.TOOL_NODE,
        config_model=EmptyConfig,
        summary=(
            "Claude's native text editor tool over graph state (StateClaudeTextEditorMiddleware). "
            "Overlaps the Deep Agents file tools; held until a mission needs the native shape."
        ),
        status=FeatureStatus.PLANNED,
        requires="a mission that needs Claude's native editor beside the Deep Agents file tools",
        rank=380,
    ),
)


# -- openai.* -----------------------------------------------------------------------------------


class OpenAIWebSearchConfig(FeatureConfig):
    """``openai.web_search``: the Responses ``web_search`` built-in."""

    search_context_size: Literal["low", "medium", "high"] = "medium"
    allowed_domains: tuple[str, ...] = Field(default=(), max_length=20)


class OpenAIFileSearchConfig(FeatureConfig):
    """``openai.file_search``: search over OpenAI vector stores the owner created."""

    vector_store_ids: tuple[str, ...] = Field(min_length=1, max_length=16)
    max_num_results: int | None = Field(default=None, ge=1, le=50)


class OpenAICodeInterpreterConfig(FeatureConfig):
    """``openai.code_interpreter``: a hosted Python container ("auto" creates one per run)."""

    container: Literal["auto"] = "auto"


class OpenAICompactionConfig(FeatureConfig):
    """``openai.compaction``: server-side compaction of the Responses conversation once the
    input passes ``compact_threshold`` tokens. The ``compaction`` blocks the model returns must
    stay in history (the lane keeps the full message content)."""

    compact_threshold: int = Field(default=150_000, ge=10_000, le=2_000_000)


class OpenAIModerationConfig(FeatureConfig):
    """``openai.moderation``: run the moderation model over inputs, outputs or tool results
    and end, error or replace on a violation (OpenAIModerationMiddleware; adds graph nodes)."""

    model: str = Field(default="omni-moderation-latest", min_length=1)
    check_input: bool = True
    check_output: bool = True
    check_tool_results: bool = False
    exit_behavior: Literal["error", "end", "replace"] = "end"


OPENAI_MODEL_TOOLS: tuple[FeatureDefinition, ...] = (
    FeatureDefinition(
        id="openai.web_search",
        axis=FeatureAxis.MODEL_TOOL,
        model_provider="openai",
        category=CapabilityDomain.TOOLING,
        facet=CapabilityFacet.WEB,
        provenance=Provenance.OPENAI_RESPONSES,
        mechanism=Mechanism.PROVIDER_TOOL,
        observability=Observability.SERVER_SIDE,
        config_model=OpenAIWebSearchConfig,
        summary=(
            "OpenAI-hosted web search (Responses web_search). Executed by the provider; "
            "results arrive as server_tool_call blocks with citations."
        ),
        rank=200,
    ),
    FeatureDefinition(
        id="openai.file_search",
        axis=FeatureAxis.MODEL_TOOL,
        model_provider="openai",
        category=CapabilityDomain.TOOLING,
        facet=CapabilityFacet.FILE_SEARCH,
        provenance=Provenance.OPENAI_RESPONSES,
        mechanism=Mechanism.PROVIDER_TOOL,
        observability=Observability.SERVER_SIDE,
        config_model=OpenAIFileSearchConfig,
        summary=(
            "Retrieval over OpenAI vector stores (Responses file_search). Needs the store ids; "
            "provider-executed."
        ),
        rank=210,
    ),
    FeatureDefinition(
        id="openai.code_interpreter",
        axis=FeatureAxis.MODEL_TOOL,
        model_provider="openai",
        category=CapabilityDomain.TOOLING,
        facet=CapabilityFacet.CODE_EXECUTION,
        provenance=Provenance.OPENAI_RESPONSES,
        mechanism=Mechanism.PROVIDER_TOOL,
        observability=Observability.SERVER_SIDE,
        config_model=OpenAICodeInterpreterConfig,
        summary=(
            "OpenAI-hosted Python execution in a provider container (Responses "
            "code_interpreter). Provider-executed; distinct from the lane's sandbox."
        ),
        rank=220,
    ),
    FeatureDefinition(
        id="openai.compaction",
        axis=FeatureAxis.MODEL_TOOL,
        model_provider="openai",
        category=CapabilityDomain.CONTEXT_MANAGEMENT,
        facet=CapabilityFacet.COMPACTION,
        provenance=Provenance.OPENAI_RESPONSES,
        mechanism=Mechanism.MODEL_SETTING,
        observability=Observability.MODEL_SETTINGS,
        config_model=OpenAICompactionConfig,
        summary=(
            "Server-side compaction of the Responses conversation past a token threshold "
            "(ChatOpenAI context_management). A model setting, not middleware."
        ),
        rank=230,
    ),
    FeatureDefinition(
        id="openai.moderation",
        axis=FeatureAxis.MODEL_TOOL,
        model_provider="openai",
        category=CapabilityDomain.CONTROL,
        facet=CapabilityFacet.MODERATION,
        provenance=Provenance.LANGCHAIN_OPENAI,
        mechanism=Mechanism.MIDDLEWARE,
        observability=Observability.TOOL_NODE,
        adds_graph_nodes=True,
        config_model=OpenAIModerationConfig,
        summary=(
            "OpenAI moderation over inputs, outputs and tool results with end, error or "
            "replace behaviour (OpenAIModerationMiddleware)."
        ),
        rank=240,
    ),
    FeatureDefinition(
        id="openai.auto_mode",
        axis=FeatureAxis.MODEL_TOOL,
        model_provider="openai",
        category=CapabilityDomain.CONTROL,
        facet=CapabilityFacet.PERMISSIONS,
        provenance=Provenance.LANGCHAIN_OPENAI,
        mechanism=Mechanism.MIDDLEWARE,
        observability=Observability.TOOL_NODE,
        config_model=EmptyConfig,
        summary=(
            "Tool-call risk gating through the OpenAI Decisions API (OpenAIAutoModeMiddleware); "
            "blocks calls above the risk threshold."
        ),
        status=FeatureStatus.NEEDS_UPGRADE,
        requires="langchain-openai>=1.7 (Sprint A)",
        rank=250,
    ),
    FeatureDefinition(
        id="openai.model_router",
        axis=FeatureAxis.MODEL_TOOL,
        model_provider="openai",
        category=CapabilityDomain.CONTROL,
        facet=CapabilityFacet.ROUTING,
        provenance=Provenance.LANGCHAIN_OPENAI,
        mechanism=Mechanism.MIDDLEWARE,
        observability=Observability.MODEL_SETTINGS,
        config_model=EmptyConfig,
        summary=(
            "Routes the run's model through a Decisions choice (OpenAIModelRouterMiddleware, "
            "beta). Conflicts with the exact model pin until a routed pin exists."
        ),
        status=FeatureStatus.NEEDS_UPGRADE,
        requires="langchain-openai>=1.7 (Sprint A) and a routed-model binding decision",
        rank=260,
    ),
)


# (vendor, feature name) -> row: what this lane realizes for a model of that vendor.
VENDOR_FEATURES: Final[Mapping[tuple[Vendor, str], FeatureDefinition]] = {
    (row.model_provider, row.id.split(".", 1)[1]): row
    for row in (*ANTHROPIC_MODEL_TOOLS, *OPENAI_MODEL_TOOLS)
    if row.model_provider is not None
}

# The lane's selectable registry: lane features plus the vendor rows above.
AGENT_FEATURES: Final = FeatureRegistry(
    (*DEEP_AGENTS_FEATURES, *OPENAI_MODEL_TOOLS, *ANTHROPIC_MODEL_TOOLS)
)


__all__ = [
    "AGENT_FEATURES",
    "ANTHROPIC_MODEL_TOOLS",
    "DEEP_AGENTS_MODEL_ROUTES",
    "OPENAI_MODEL_TOOLS",
    "VENDOR_FEATURES",
    "AnthropicBashConfig",
    "AnthropicClearToolUsesConfig",
    "AnthropicCodeExecutionConfig",
    "AnthropicCompactionConfig",
    "AnthropicMemoryConfig",
    "AnthropicPromptCachingConfig",
    "AnthropicWebFetchConfig",
    "AnthropicWebSearchConfig",
    "OpenAICodeInterpreterConfig",
    "OpenAICompactionConfig",
    "OpenAIFileSearchConfig",
    "OpenAIModerationConfig",
    "OpenAIWebSearchConfig",
]
