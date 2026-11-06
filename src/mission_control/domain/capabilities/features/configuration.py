"""``mc.agent_configuration.v1``: the sealed selection of lane features and model tools.

The lane adapter resolves what a mission selected (``provider_options.deep_agents.lane_features``
and ``.model_tools``) plus the registry defaults into one :class:`AgentConfiguration` and
seals it into the exact binding. Each :class:`FeatureSelection` repeats the row's
classification (axis, category, facet, mechanism) so the binding, the receipt and the
transcript can be read without the registry, and carries the canonical configuration with
its digest. The materializer executes the selection; it never consults the manifest.

:func:`resolve_agent_configuration` is pure: it returns the configuration and one
:class:`ResolutionNote` per item (the receipt row the lane signs), or raises
:class:`AgentConfigurationRefused` with the manifest pointer suffix and the reason.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator

from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.capabilities.features.registry import (
    CapabilityDomain,
    CapabilityFacet,
    FeatureAxis,
    FeatureDefinition,
    FeatureRegistry,
    FeatureStatus,
    Mechanism,
    ModelProvider,
    Observability,
)

AGENT_CONFIGURATION_SCHEMA: Final = "mc.agent_configuration.v1"
PLACEHOLDER_DIGEST: Final = "sha256:" + "0" * 64
DIGEST_PATTERN: Final = r"^sha256:[0-9a-f]{64}$"

Verdict = Literal["native", "degraded"]


class AgentConfigurationRefused(ValueError):
    """A selection the lane cannot seal; ``pointer`` is relative to the options block."""

    def __init__(self, pointer: str, message: str) -> None:
        super().__init__(message)
        self.pointer = pointer
        self.message = message


class FeatureSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=128)
    axis: FeatureAxis
    category: CapabilityDomain
    facet: CapabilityFacet
    mechanism: Mechanism
    observability: Observability
    # True when the registry default put it here rather than the mission.
    by_default: bool = False
    config: dict[str, Any] = Field(default_factory=dict)
    config_digest: str = Field(pattern=DIGEST_PATTERN)

    @model_validator(mode="after")
    def exact_config(self) -> FeatureSelection:
        if sha256_digest(self.config) != self.config_digest:
            raise ValueError(f"feature {self.id} configuration digest mismatch")
        return self

    @classmethod
    def create(
        cls, row: FeatureDefinition, config: Mapping[str, Any], *, by_default: bool = False
    ) -> FeatureSelection:
        canonical = dict(config)
        return cls(
            id=row.id,
            axis=row.axis,
            category=row.category,
            facet=row.facet,
            mechanism=row.mechanism,
            observability=row.observability,
            by_default=by_default,
            config=canonical,
            config_digest=sha256_digest(canonical),
        )


class AgentConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["mc.agent_configuration.v1"] = AGENT_CONFIGURATION_SCHEMA
    lane: Literal["deep_agents"]
    model_provider: ModelProvider
    items: tuple[FeatureSelection, ...] = ()
    configuration_digest: str = Field(pattern=DIGEST_PATTERN)

    @model_validator(mode="after")
    def exact_configuration(self, info: ValidationInfo) -> AgentConfiguration:
        ids = [item.id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("an agent configuration selects each capability once")
        if (
            not (info.context or {}).get("allow_placeholder_digest")
            and self.content_digest() != self.configuration_digest
        ):
            raise ValueError("agent configuration digest mismatch")
        return self

    def content_digest(self) -> str:
        return sha256_digest(self.model_dump(mode="python", exclude={"configuration_digest"}))

    @classmethod
    def create(
        cls,
        *,
        lane: Literal["deep_agents"],
        model_provider: ModelProvider,
        items: tuple[FeatureSelection, ...],
    ) -> AgentConfiguration:
        draft = cls.model_validate(
            {
                "lane": lane,
                "model_provider": model_provider,
                "items": items,
                "configuration_digest": PLACEHOLDER_DIGEST,
            },
            context={"allow_placeholder_digest": True},
        )
        return cls(
            lane=draft.lane,
            model_provider=draft.model_provider,
            items=draft.items,
            configuration_digest=draft.content_digest(),
        )

    def get(self, feature_id: str) -> FeatureSelection | None:
        return next((item for item in self.items if item.id == feature_id), None)

    def selected(self, mechanism: Mechanism | None = None) -> tuple[FeatureSelection, ...]:
        return tuple(
            item for item in self.items if mechanism is None or item.mechanism is mechanism
        )


@dataclass(frozen=True)
class ResolutionNote:
    """What the lane will say about one item in its receipt."""

    selection: FeatureSelection
    verdict: Verdict
    native_locator: str
    reason: str | None = None


def resolve_agent_configuration(
    registry: FeatureRegistry,
    *,
    lane: Literal["deep_agents"],
    model_provider: ModelProvider,
    sandbox_backend: str,
    lane_features: Mapping[str, Mapping[str, Any]] | None,
    model_tools: Mapping[Any, Mapping[str, Mapping[str, Any]]] | None,
) -> tuple[AgentConfiguration, tuple[ResolutionNote, ...]]:
    """Defaults plus the mission's selection, validated against the registry.

    ``lane_features`` is keyed by the feature name without the lane prefix
    (``todo_list``); ``model_tools`` by model provider, then the tool name without the
    provider prefix (``openai: {web_search: {...}}``). A model tool for a provider other than
    the agent's model is refused (``model_tool_provider_mismatch``): the coordinator selected
    a tool the model's API cannot run. A row that is not ``available`` is refused with the
    row's ``requires`` text. A default row the mission also names is configured by the
    mission; a required row cannot be switched off (there is no off switch: omit the
    configuration to take the stock one).
    """

    selections: dict[str, FeatureSelection] = {}
    for name, payload in sorted((lane_features or {}).items()):
        feature_id = f"{lane}.{name}"
        pointer = f"/lane_features/{name}"
        row = _row(registry, feature_id, pointer)
        if row.axis is not FeatureAxis.LANE_FEATURE or row.lane != lane:
            raise AgentConfigurationRefused(pointer, f"{feature_id} is not a {lane} lane feature")
        selections[feature_id] = _selection(row, payload, pointer)
    for provider, tools in sorted((model_tools or {}).items()):
        if provider != model_provider:
            raise AgentConfigurationRefused(
                f"/model_tools/{provider}",
                f"model_tool_provider_mismatch: the agent's model is {model_provider}; "
                f"{provider} tools cannot run on it",
            )
        for name, payload in sorted((tools or {}).items()):
            feature_id = f"{provider}.{name}"
            pointer = f"/model_tools/{provider}/{name}"
            row = _row(registry, feature_id, pointer)
            if row.axis is not FeatureAxis.MODEL_TOOL or row.model_provider != provider:
                raise AgentConfigurationRefused(pointer, f"{feature_id} is not a {provider} tool")
            selections[feature_id] = _selection(row, payload, pointer)
    sandboxed = sandbox_backend != "state"
    for row in registry.defaults(lane=lane, model_provider=model_provider, sandboxed=sandboxed):
        if row.id not in selections:
            selections[row.id] = FeatureSelection.create(
                row, row.validate_config(None), by_default=True
            )
    items = tuple(
        sorted(selections.values(), key=lambda item: (registry.get(item.id).rank, item.id))
    )
    configuration = AgentConfiguration.create(lane=lane, model_provider=model_provider, items=items)
    notes = tuple(_note(registry.get(item.id), item, sandbox_backend) for item in items)
    return configuration, notes


def _row(registry: FeatureRegistry, feature_id: str, pointer: str) -> FeatureDefinition:
    if feature_id not in registry:
        raise AgentConfigurationRefused(
            pointer,
            f"unknown agent capability {feature_id}; known ids: "
            + ", ".join(row.id for row in registry),
        )
    row = registry.get(feature_id)
    if row.status is not FeatureStatus.AVAILABLE:
        raise AgentConfigurationRefused(
            pointer,
            f"{feature_id} is {row.status.value} on the installed stack; requires {row.requires}",
        )
    return row


def _selection(
    row: FeatureDefinition, payload: Mapping[str, Any], pointer: str
) -> FeatureSelection:
    try:
        config = row.validate_config(payload)
    except ValueError as error:
        raise AgentConfigurationRefused(pointer, str(error)) from error
    return FeatureSelection.create(row, config)


def _note(row: FeatureDefinition, item: FeatureSelection, sandbox_backend: str) -> ResolutionNote:
    """The receipt verdict the lane can decide at compile time."""

    if row.id == "deep_agents.bash":
        execution = item.config.get("execution", "sandbox")
        if execution == "sandbox":
            if sandbox_backend == "state":
                return ResolutionNote(
                    item,
                    "degraded",
                    "no shell",
                    reason=(
                        "the state backend has no execute tool; select a docker or langsmith "
                        "sandbox profile, or set execution: docker"
                    ),
                )
            return ResolutionNote(item, "native", f"{sandbox_backend} backend execute tool")
        if execution == "host":
            return ResolutionNote(
                item,
                "degraded",
                "ShellToolMiddleware bash (host)",
                reason="commands run on the worker host, unsandboxed; development only",
            )
        return ResolutionNote(item, "native", "ShellToolMiddleware bash (docker)")
    if row.id == "deep_agents.filesystem":
        return ResolutionNote(
            item, "native", "FilesystemMiddleware" + (" (stock)" if item.by_default else "")
        )
    if row.mechanism is Mechanism.PROVIDER_TOOL:
        return ResolutionNote(item, "native", f"{row.provenance.value} dict tool (server side)")
    if row.mechanism is Mechanism.MODEL_SETTING:
        return ResolutionNote(item, "native", "chat model setting")
    return ResolutionNote(item, "native", f"{row.provenance.value} middleware")


__all__ = [
    "AGENT_CONFIGURATION_SCHEMA",
    "AgentConfiguration",
    "AgentConfigurationRefused",
    "FeatureSelection",
    "ResolutionNote",
    "resolve_agent_configuration",
]
