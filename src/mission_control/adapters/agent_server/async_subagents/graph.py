"""Hosted technical child selected by the canonical Agent Server runtime profile.

`graph` is an async graph factory: the server calls it with the run config and receives the
compiled Deep Agent built from the exact binding through the canonical adapter and
materializer. Nothing is built at import, and the server's own checkpointer, store and
scheduler are used (REQ-CP-DA-019).
"""

from __future__ import annotations

import asyncio
import os
from contextlib import AsyncExitStack
from typing import Any

from langchain_core.runnables import RunnableConfig

from mission_control.adapters.agent_server.async_subagents.bindings import (
    HostedAsyncSubagentDefinition,
    technical_child_definition,
)
from mission_control.adapters.deep_agents.adapter import DeepAgentRuntimeAdapter
from mission_control.adapters.deep_agents.materializer import (
    ExactComponentRegistry,
    ExactDeepAgentMaterializer,
    ExactModelFactory,
    StateSandboxFactory,
)

_compiled: Any = None
_stack: AsyncExitStack | None = None
_lock = asyncio.Lock()


def hosting_registry(definition: HostedAsyncSubagentDefinition) -> ExactComponentRegistry:
    """Exact components by digest: the model factory of the pinned vendor, the prompt, tools and
    backend."""

    binding = definition.binding
    return ExactComponentRegistry(
        model_factories={binding.model.ref.digest: ExactModelFactory()},
        prompts={definition.profile.prompt_refs[0].digest: definition.system_prompt},
        tools={
            component.ref.digest: item
            for component, item in zip(binding.tools, definition.tools, strict=True)
        },
        sandbox_factories={binding.sandbox.ref.digest: StateSandboxFactory()},
    )


def hosting_secrets(provider: str = "openai") -> dict[str, str]:
    """Credential references the hosted binding resolves from the server environment
    (the hosted technical child's model provider; OpenAI unless the definition says
    otherwise)."""

    variable = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}.get(provider)
    if variable is None:
        raise RuntimeError(f"no hosted credential variable for model provider {provider!r}")
    api_key = os.environ.get(variable, "")
    if not api_key:
        raise RuntimeError(f"{variable} is required to host the async technical child")
    return {f"environment:{variable}": api_key}


async def build_hosted_graph(
    definition: HostedAsyncSubagentDefinition,
    *,
    registry: ExactComponentRegistry | None = None,
    secrets: dict[str, str] | None = None,
    stack: AsyncExitStack,
) -> Any:
    adapter = DeepAgentRuntimeAdapter(
        ExactDeepAgentMaterializer(registry or hosting_registry(definition))
    )
    return await adapter.build_hosted_async_subagent_graph(
        definition.binding,
        secrets if secrets is not None else hosting_secrets(definition.binding.model.provider),
        system_prompt=definition.system_prompt,
        served=definition.served,
        stack=stack,
    )


async def graph(config: RunnableConfig) -> Any:
    """The server's graph factory; the compiled graph is built once per process."""

    del config
    global _compiled, _stack
    async with _lock:
        if _compiled is None:
            _stack = AsyncExitStack()
            _compiled = await build_hosted_graph(technical_child_definition(), stack=_stack)
        return _compiled
