"""Realizing a sealed ``mc.agent_configuration.v1`` on the Deep Agents lane.

One builder per registry row, grouped by mechanism (`builders.py`): a middleware row
returns ``AgentMiddleware`` instances, a provider-tool row returns the dict tool bound beside
the agent's own tools, a model-setting row returns the chat-model constructor settings the
exact model factory receives. The materializer calls :func:`realize_agent_configuration`
once per prepare and the adapter's ``_compile`` adds the one row that needs the effective
permissions (the filesystem replacement).
"""

from __future__ import annotations

from mission_control.adapters.deep_agents.features.builders import (
    FeatureBuildContext,
    RealizedFeatures,
    filesystem_replacement,
    realize_agent_configuration,
)

__all__ = [
    "FeatureBuildContext",
    "RealizedFeatures",
    "filesystem_replacement",
    "realize_agent_configuration",
]
