"""Deep Agents lane features: the ``deep_agents.*`` rows and their configuration models.

Every row here is a LangChain or Deep Agents middleware the lane can put in the stack.
The two **default** rows are the ones a sandboxed agent always needs: the filesystem tools
and a shell (the shell only where a sandbox backend can run it; on the in-memory state
backend a mission names ``bash`` explicitly and chooses where it runs).
``deep_agents.filesystem`` is also **required**: deepagents cannot run without
``FilesystemMiddleware`` (it backs every file tool and enforces permissions), so a mission
can tune it but never remove it.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from mission_control.domain.authoring.provider_options import DeepAgentsSummarization
from mission_control.domain.capabilities.features.registry import (
    CapabilityDomain,
    CapabilityFacet,
    EmptyConfig,
    FeatureAxis,
    FeatureConfig,
    FeatureDefinition,
    FeatureStatus,
    Mechanism,
    Observability,
    Provenance,
)

LANE: Literal["deep_agents"] = "deep_agents"


FilesystemTool = Literal[
    "ls", "read_file", "write_file", "edit_file", "delete", "glob", "grep", "execute"
]


class FilesystemConfig(FeatureConfig):
    """``deep_agents.filesystem``: the stock Deep Agents file tools with eviction knobs.

    ``tools`` narrows the tool subset the model sees (``execute`` appears only on a sandbox
    backend regardless). The two eviction limits say when a large tool result or human
    message is moved to a file and replaced by a pointer; ``None`` disables that eviction.
    """

    tools: tuple[FilesystemTool, ...] | None = None
    tool_token_limit_before_evict: int | None = Field(default=20_000, ge=1_000, le=1_000_000)
    human_message_token_limit_before_evict: int | None = Field(
        default=50_000, ge=1_000, le=1_000_000
    )

    @model_validator(mode="after")
    def unique_tools(self) -> FilesystemConfig:
        if self.tools is not None and len(set(self.tools)) != len(self.tools):
            raise ValueError("tools names a tool twice")
        return self

    @property
    def is_stock(self) -> bool:
        return self == FilesystemConfig()


class BashConfig(FeatureConfig):
    """``deep_agents.bash``: where shell commands run.

    - ``sandbox`` (default): the bound sandbox backend's own ``execute`` tool (Docker or
      LangSmith). On the in-memory ``state`` backend there is no shell; the lane receipts
      the row ``degraded`` and adds nothing.
    - ``docker``: a persistent ``bash`` session in a throwaway Docker container on the
      worker (``ShellToolMiddleware`` with ``DockerExecutionPolicy``), network off.
    - ``host``: a ``bash`` session on the worker host itself. Development only; the receipt
      says so.
    """

    execution: Literal["sandbox", "docker", "host"] = "sandbox"
    command_timeout_seconds: int = Field(default=120, ge=1, le=3_600)
    max_output_lines: int = Field(default=200, ge=1, le=10_000)
    # Docker execution only.
    image: str = Field(default="python:3.12-slim", min_length=1, max_length=256)


class ContextEditingConfig(FeatureConfig):
    """``deep_agents.context_editing``: clear old tool results past a token budget
    (``ContextEditingMiddleware`` with one ``ClearToolUsesEdit``)."""

    trigger_tokens: int = Field(default=100_000, ge=1_000, le=10_000_000)
    clear_at_least_tokens: int = Field(default=0, ge=0, le=10_000_000)
    keep_tool_uses: int = Field(default=3, ge=0, le=1_000)
    clear_tool_inputs: bool = False
    exclude_tools: tuple[str, ...] = Field(default=(), max_length=64)
    token_count_method: Literal["approximate", "model"] = "approximate"  # noqa: S105


class CallLimitsConfig(FeatureConfig):
    """``deep_agents.call_limits``: caps on model and tool calls per run or per thread.

    At least one limit must be set. ``exit_behavior`` ``end`` closes the turn with a notice
    the transcript records; ``error`` raises. Both middlewares add graph nodes.
    """

    model_calls_per_run: int | None = Field(default=None, ge=1, le=10_000)
    model_calls_per_thread: int | None = Field(default=None, ge=1, le=100_000)
    tool_calls_per_run: int | None = Field(default=None, ge=1, le=100_000)
    tool_calls_per_thread: int | None = Field(default=None, ge=1, le=1_000_000)
    exit_behavior: Literal["end", "error"] = "end"

    @model_validator(mode="after")
    def one_limit(self) -> CallLimitsConfig:
        if all(
            value is None
            for value in (
                self.model_calls_per_run,
                self.model_calls_per_thread,
                self.tool_calls_per_run,
                self.tool_calls_per_thread,
            )
        ):
            raise ValueError("call_limits needs at least one limit")
        return self


class TodoListConfig(FeatureConfig):
    """``deep_agents.todo_list``: the ``write_todos`` planning tool."""


DEEP_AGENTS_FEATURES: tuple[FeatureDefinition, ...] = (
    FeatureDefinition(
        id="deep_agents.filesystem",
        axis=FeatureAxis.LANE_FEATURE,
        lane=LANE,
        category=CapabilityDomain.TOOLING,
        facet=CapabilityFacet.FILESYSTEM,
        provenance=Provenance.DEEPAGENTS,
        mechanism=Mechanism.MIDDLEWARE,
        observability=Observability.TOOL_NODE,
        default=True,
        required=True,
        config_model=FilesystemConfig,
        summary=(
            "Deep Agents file tools (ls, read_file, write_file, edit_file, delete, glob, grep, "
            "and execute on a sandbox) over the bound backend, with eviction of large tool "
            "results and human messages to files; enforces filesystem permissions."
        ),
        rank=0,
    ),
    FeatureDefinition(
        id="deep_agents.bash",
        axis=FeatureAxis.LANE_FEATURE,
        lane=LANE,
        category=CapabilityDomain.TOOLING,
        facet=CapabilityFacet.SHELL,
        provenance=Provenance.LANGCHAIN,
        mechanism=Mechanism.MIDDLEWARE,
        observability=Observability.TOOL_NODE,
        adds_graph_nodes=True,
        default=True,
        default_requires_sandbox=True,
        config_model=BashConfig,
        summary=(
            "A shell for the agent: the sandbox backend's execute tool by default, or a "
            "persistent bash session in Docker or on the host (ShellToolMiddleware)."
        ),
        rank=10,
    ),
    FeatureDefinition(
        id="deep_agents.todo_list",
        axis=FeatureAxis.LANE_FEATURE,
        lane=LANE,
        category=CapabilityDomain.TOOLING,
        facet=CapabilityFacet.PLANNING,
        provenance=Provenance.LANGCHAIN,
        mechanism=Mechanism.MIDDLEWARE,
        observability=Observability.TOOL_NODE,
        adds_graph_nodes=True,
        config_model=TodoListConfig,
        summary=(
            "The write_todos planning tool and its prompt (TodoListMiddleware); state key "
            "todos. Not in the Deep Agents default stack; opt in per mission."
        ),
        rank=20,
    ),
    FeatureDefinition(
        id="deep_agents.context_editing",
        axis=FeatureAxis.LANE_FEATURE,
        lane=LANE,
        category=CapabilityDomain.CONTEXT_MANAGEMENT,
        facet=CapabilityFacet.CONTEXT_EDITING,
        provenance=Provenance.LANGCHAIN,
        mechanism=Mechanism.MIDDLEWARE,
        observability=Observability.MODEL_SETTINGS,
        config_model=ContextEditingConfig,
        summary=(
            "Client-side context editing: clears old tool results once the input exceeds a "
            "token budget (ContextEditingMiddleware, ClearToolUsesEdit). Cheap trimming "
            "that complements summarization."
        ),
        rank=30,
    ),
    FeatureDefinition(
        id="deep_agents.summarization",
        axis=FeatureAxis.LANE_FEATURE,
        lane=LANE,
        category=CapabilityDomain.CONTEXT_MANAGEMENT,
        facet=CapabilityFacet.COMPACTION,
        provenance=Provenance.DEEPAGENTS,
        mechanism=Mechanism.MIDDLEWARE,
        observability=Observability.MODEL_SETTINGS,
        # Always in the stack (the observed summarizer); the row exists to configure it, so
        # it is required but not inserted by default (its config needs a trigger).
        required=True,
        config_model=DeepAgentsSummarization,
        summary=(
            "Deep Agents summarization (compaction): when the history is compacted and how "
            "many messages survive. Always on; the configuration overrides the worker "
            "default trigger (the same knobs as provider_options.deep_agents.summarization)."
        ),
        rank=40,
    ),
    FeatureDefinition(
        id="deep_agents.call_limits",
        axis=FeatureAxis.LANE_FEATURE,
        lane=LANE,
        category=CapabilityDomain.CONTROL,
        facet=CapabilityFacet.BUDGET,
        provenance=Provenance.LANGCHAIN,
        mechanism=Mechanism.MIDDLEWARE,
        observability=Observability.TOOL_NODE,
        adds_graph_nodes=True,
        config_model=CallLimitsConfig,
        summary=(
            "Hard caps on model calls and tool calls per run or per thread "
            "(ModelCallLimitMiddleware, ToolCallLimitMiddleware); the turn ends with a notice."
        ),
        rank=50,
    ),
    # Rows the sheet names that wait for a later sprint; selectable in name only.
    FeatureDefinition(
        id="deep_agents.filesystem_permissions",
        axis=FeatureAxis.LANE_FEATURE,
        lane=LANE,
        category=CapabilityDomain.CONTROL,
        facet=CapabilityFacet.PERMISSIONS,
        provenance=Provenance.DEEPAGENTS,
        mechanism=Mechanism.MIDDLEWARE,
        observability=Observability.TOOL_NODE,
        config_model=EmptyConfig,
        summary=(
            "Mission-authored allow, deny and interrupt rules over paths (FilesystemPermission). "
            "Today the lane derives the rules from the workspace contract; authored rules "
            "wait for the 0.7.25 symlink fix (Sprint A) and the human-control binding."
        ),
        status=FeatureStatus.NEEDS_UPGRADE,
        requires="deepagents>=0.7.25 (Sprint A) and the Human Task binding (P1 WP-5)",
        rank=60,
    ),
    FeatureDefinition(
        id="deep_agents.memory",
        axis=FeatureAxis.LANE_FEATURE,
        lane=LANE,
        category=CapabilityDomain.CONTEXT_MANAGEMENT,
        facet=CapabilityFacet.MEMORY,
        provenance=Provenance.DEEPAGENTS,
        mechanism=Mechanism.MIDDLEWARE,
        observability=Observability.MODEL_SETTINGS,
        adds_graph_nodes=True,
        config_model=EmptyConfig,
        summary=(
            "AGENTS.md memory files loaded into the system prompt (MemoryMiddleware). "
            "Waits for the memory round of the interview (which files, whose custody)."
        ),
        status=FeatureStatus.PLANNED,
        requires="interview round RM (PR-07) and OC-4",
        rank=70,
    ),
    FeatureDefinition(
        id="deep_agents.rubric",
        axis=FeatureAxis.LANE_FEATURE,
        lane=LANE,
        category=CapabilityDomain.CONTROL,
        facet=CapabilityFacet.SELF_EVALUATION,
        provenance=Provenance.DEEPAGENTS,
        mechanism=Mechanism.MIDDLEWARE,
        observability=Observability.MODEL_SETTINGS,
        adds_graph_nodes=True,
        config_model=EmptyConfig,
        summary=(
            "LLM-as-judge iteration against a rubric carried in state (RubricMiddleware). "
            "Overlaps the Evaluator Optimizer workflow; placed after OC-4."
        ),
        status=FeatureStatus.PLANNED,
        requires="OC-4 (the sprint sequence)",
        rank=80,
    ),
    FeatureDefinition(
        id="deep_agents.code_interpreter",
        axis=FeatureAxis.LANE_FEATURE,
        lane=LANE,
        category=CapabilityDomain.DELEGATION,
        facet=CapabilityFacet.CODE_EXECUTION,
        provenance=Provenance.LANGCHAIN,
        mechanism=Mechanism.MIDDLEWARE,
        observability=Observability.TOOL_NODE,
        adds_graph_nodes=True,
        config_model=EmptyConfig,
        summary=(
            "QuickJS eval tool with dynamic task() subagents and programmatic tool calling "
            "(langchain-quickjs CodeInterpreterMiddleware, beta). Bypasses HITL per dispatch; "
            "gated until the concurrency cap and signed snapshots of 0.3.9 are installed."
        ),
        status=FeatureStatus.NEEDS_UPGRADE,
        requires="langchain-quickjs>=0.3.9 (Sprint A), then the dynamic-subagents decision",
        rank=90,
    ),
)

__all__ = [
    "DEEP_AGENTS_FEATURES",
    "BashConfig",
    "CallLimitsConfig",
    "ContextEditingConfig",
    "FilesystemConfig",
    "FilesystemTool",
    "TodoListConfig",
]
