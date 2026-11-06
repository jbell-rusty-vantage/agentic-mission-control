"""The Deep Agents lane package (ADR-0005; ADR-0063).

Its exports load lazily (PEP 562): `describe` is declarations as data that the application's
describe aggregator reads, so importing any submodule must not pull in the runtime adapter,
the materializer and their LangChain dependencies (OC-R3).
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mission_control.adapters.deep_agents.adapter import DeepAgentRuntimeAdapter
    from mission_control.adapters.deep_agents.async_subagents import (
        DeepAgentsAsyncSubagentAdapter,
    )
    from mission_control.adapters.deep_agents.docker_sandbox import (
        DockerSandbox,
        DockerSandboxFactory,
    )
    from mission_control.adapters.deep_agents.materializer import (
        AnthropicExactModelFactory,
        ExactComponentRegistry,
        ExactDeepAgentMaterializer,
        ExactModelFactory,
        LangSmithSandboxFactory,
        OpenAIExactModelFactory,
        ResolvedSkillBundle,
        StateSandboxFactory,
        model_factory_for,
    )

_EXPORTS = {
    "AnthropicExactModelFactory": "materializer",
    "DeepAgentRuntimeAdapter": "adapter",
    "DeepAgentsAsyncSubagentAdapter": "async_subagents",
    "DockerSandbox": "docker_sandbox",
    "DockerSandboxFactory": "docker_sandbox",
    "ExactComponentRegistry": "materializer",
    "ExactDeepAgentMaterializer": "materializer",
    "ExactModelFactory": "materializer",
    "LangSmithSandboxFactory": "materializer",
    "OpenAIExactModelFactory": "materializer",
    "ResolvedSkillBundle": "materializer",
    "StateSandboxFactory": "materializer",
    "model_factory_for": "materializer",
}


def __getattr__(name: str) -> Any:
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(import_module(f"{__name__}.{module}"), name)


__all__ = [
    "AnthropicExactModelFactory",
    "DeepAgentRuntimeAdapter",
    "DeepAgentsAsyncSubagentAdapter",
    "DockerSandbox",
    "DockerSandboxFactory",
    "ExactComponentRegistry",
    "ExactDeepAgentMaterializer",
    "ExactModelFactory",
    "LangSmithSandboxFactory",
    "OpenAIExactModelFactory",
    "ResolvedSkillBundle",
    "StateSandboxFactory",
    "model_factory_for",
]
