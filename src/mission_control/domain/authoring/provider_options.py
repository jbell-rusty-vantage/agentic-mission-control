"""Provider-specific manifest options, discriminated by lane profile (P1-S2).

A manifest environment is lane-neutral. The few settings that have no neutral meaning live
under ``provider_options``, keyed by the lane profile that understands them:

.. code-block:: yaml

    environment:
      lane: deep_agents
      provider_options:
        deep_agents:
          sandbox_backend: docker
          summarization: {trigger_messages: 40, keep_messages: 20}

Each key names a lane profile and is validated by that lane's options model, registered in
``PROVIDER_OPTIONS_MODELS``. A key for a lane the node does not run on is a compile blocker
(``provider_options_lane_mismatch``), so options never travel to the wrong lane silently. The
lane adapter that owns the key is the only reader; it records what it honoured in the
materialization receipt of the binding it seals.

This module is authoring-side and provider-aware by design: it is the registry of which
provider options exist, not how any lane applies them. Application code never parses the raw
mapping itself; it asks :func:`parse_provider_options`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PROVIDER_OPTIONS_SCHEMA_PREFIX: Final = "mc.provider_options."


class _Options(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DeepAgentsSummarization(_Options):
    """When the Deep Agents summarization middleware compacts, and what it keeps.

    One of the two triggers must be set. ``trigger_messages`` counts messages since the last
    compaction; ``trigger_tokens`` is an approximate token count. ``keep_messages`` is the
    tail preserved verbatim after a compaction.
    """

    trigger_messages: int | None = Field(default=None, ge=2, le=10_000)
    trigger_tokens: int | None = Field(default=None, ge=1_000, le=10_000_000)
    keep_messages: int = Field(default=20, ge=1, le=1_000)

    @model_validator(mode="after")
    def one_trigger(self) -> DeepAgentsSummarization:
        if self.trigger_messages is None and self.trigger_tokens is None:
            raise ValueError("summarization needs trigger_messages or trigger_tokens")
        return self


class DeepAgentsProviderOptions(_Options):
    """``mc.provider_options.deep_agents.v1``: what only the Deep Agents lane understands.

    - ``sandbox_backend`` pins the backend the selected sandbox profile must have (``state``
      in-memory files, ``docker`` network-isolated container, ``langsmith`` hosted sandbox);
      a profile with another backend is refused at launch rather than switched.
    - ``summarization`` overrides the worker-wide compaction trigger for this node.
    - ``interrupt_on`` names tools whose calls raise a LangGraph interrupt. Until the
      human-control binding lands (P1 WP-5) the lane records the interrupt and parks the
      unit ``in_doubt``, so the receipt reports this item ``degraded``.
    - ``lane_features`` selects Deep Agents lane features by name (the registry id without
      the ``deep_agents.`` prefix: ``todo_list``, ``context_editing``, ``call_limits``,
      ``bash``, ``filesystem``, ``summarization``), each with its typed configuration;
      ``model_tools`` selects model tools by model provider, then name (``openai:
      {web_search: {}}``). Lane feature names and configurations are validated against the
      Deep Agents lane features here; model tools are vendor features of the lane's model
      routes (``adapters/deep_agents/routes.py``, OC-R6), so their names, configurations,
      the provider match and the sealed configuration are validated by the lane adapter at
      launch (the core keeps no vendor feature registry).
    """

    schema_version: Literal["mc.provider_options.deep_agents.v1"] = (
        "mc.provider_options.deep_agents.v1"
    )
    sandbox_backend: Literal["state", "docker", "langsmith"] | None = None
    summarization: DeepAgentsSummarization | None = None
    interrupt_on: tuple[str, ...] = Field(default=(), max_length=64)
    lane_features: dict[str, dict[str, Any]] = Field(default_factory=dict)
    model_tools: dict[Literal["openai", "anthropic"], dict[str, dict[str, Any]]] = Field(
        default_factory=dict
    )

    @model_validator(mode="after")
    def unique_interrupts(self) -> DeepAgentsProviderOptions:
        if len(set(self.interrupt_on)) != len(self.interrupt_on):
            raise ValueError("interrupt_on names a tool twice")
        return self

    @model_validator(mode="after")
    def known_capabilities(self) -> DeepAgentsProviderOptions:
        """Every selected lane feature is a Deep Agents row with a valid configuration; the
        canonical configuration dumps replace the authored ones. Model tool selections keep
        their authored shape: the lane's model routes validate them at launch (OC-R6)."""

        # The registry's Deep Agents rows reuse `DeepAgentsSummarization` from this module.
        from mission_control.domain.capabilities.features import LANE_FEATURES

        features: dict[str, dict[str, Any]] = {}
        for name, payload in self.lane_features.items():
            feature_id = f"deep_agents.{name}"
            if feature_id not in LANE_FEATURES:
                raise ValueError(f"lane_features: unknown deep_agents feature {name!r}")
            features[name] = LANE_FEATURES.get(feature_id).validate_config(payload)
        if (
            self.summarization is not None
            and "summarization" in features
            and features["summarization"] != self.summarization.model_dump(mode="json")
        ):
            raise ValueError(
                "summarization is configured twice with different values "
                "(provider_options.summarization and lane_features.summarization)"
            )
        object.__setattr__(self, "lane_features", features)
        return self

    @property
    def effective_summarization(self) -> DeepAgentsSummarization | None:
        """The one summarization policy, whichever of the two spellings carried it."""

        if self.summarization is not None:
            return self.summarization
        payload = self.lane_features.get("summarization")
        return DeepAgentsSummarization.model_validate(payload) if payload is not None else None


ProviderOptionsModel = DeepAgentsProviderOptions

# The lanes that have provider options today. A lane absent here accepts no key: adding one
# is a reviewed change to this registry, with that lane's adapter as its reader.
PROVIDER_OPTIONS_MODELS: Final[Mapping[str, type[ProviderOptionsModel]]] = {
    "deep_agents": DeepAgentsProviderOptions,
}


def parse_provider_options(lane_profile: str, payload: Mapping[str, Any]) -> ProviderOptionsModel:
    """Validate one lane's options block; an unknown lane is an authoring error."""

    model = PROVIDER_OPTIONS_MODELS.get(lane_profile)
    if model is None:
        raise ValueError(
            f"lane {lane_profile} has no provider options; known: {sorted(PROVIDER_OPTIONS_MODELS)}"
        )
    return model.model_validate(dict(payload))


def normalize_provider_options(
    options: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, dict[str, Any]] | None:
    """Validate every key and return the canonical dumps (what the manifest stores)."""

    if options is None:
        return None
    return {
        lane: parse_provider_options(lane, payload).model_dump(mode="json")
        for lane, payload in options.items()
    }


def provider_options_lane_mismatch(
    options: Mapping[str, Any] | None, *, lane: str | None, candidate_lanes: tuple[str, ...]
) -> tuple[str, ...]:
    """The option keys that name a lane this environment does not run on."""

    if not options or lane is None:
        return ()
    allowed = {lane, *candidate_lanes}
    return tuple(sorted(key for key in options if key not in allowed))


__all__ = [
    "PROVIDER_OPTIONS_MODELS",
    "PROVIDER_OPTIONS_SCHEMA_PREFIX",
    "DeepAgentsProviderOptions",
    "DeepAgentsSummarization",
    "ProviderOptionsModel",
    "normalize_provider_options",
    "parse_provider_options",
    "provider_options_lane_mismatch",
]
