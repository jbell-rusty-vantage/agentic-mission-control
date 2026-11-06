"""Selectable agent capabilities: the registry vocabulary, the Deep Agents lane features and the
sealed ``mc.agent_configuration.v1`` a binding carries (sprint B, first slice).

``LANE_FEATURES`` holds the Deep Agents lane features (``deep_agents.*``), which
``provider_options`` validates at manifest compile. The vendor rows (``anthropic.*``,
``openai.*``) are model-route features of the Deep Agents lane and live in its package
(``adapters/deep_agents/routes.py``, OC-R6), which composes the lane's whole registry
``AGENT_FEATURES``; the core keeps no vendor feature registry. Pure Pydantic; realized by
``adapters/deep_agents/features``.
"""

from __future__ import annotations

from mission_control.domain.capabilities.features.configuration import (
    AGENT_CONFIGURATION_SCHEMA,
    AgentConfiguration,
    AgentConfigurationRefused,
    FeatureSelection,
    ResolutionNote,
    resolve_agent_configuration,
)
from mission_control.domain.capabilities.features.deep_agents import DEEP_AGENTS_FEATURES
from mission_control.domain.capabilities.features.registry import (
    CapabilityDomain,
    CapabilityFacet,
    FeatureAxis,
    FeatureDefinition,
    FeatureRegistry,
    FeatureStatus,
    Mechanism,
    Observability,
    Provenance,
)

# The Deep Agents lane features; the lane's full registry adds its vendor rows (`routes.py`).
LANE_FEATURES = FeatureRegistry(DEEP_AGENTS_FEATURES)

__all__ = [
    "AGENT_CONFIGURATION_SCHEMA",
    "LANE_FEATURES",
    "AgentConfiguration",
    "AgentConfigurationRefused",
    "CapabilityDomain",
    "CapabilityFacet",
    "FeatureAxis",
    "FeatureDefinition",
    "FeatureRegistry",
    "FeatureSelection",
    "FeatureStatus",
    "Mechanism",
    "Observability",
    "Provenance",
    "ResolutionNote",
    "resolve_agent_configuration",
]
