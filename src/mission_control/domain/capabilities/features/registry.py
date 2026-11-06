"""The registry of selectable agent capabilities: lane features and model tools (sprint B).

A mission selects provider-native behaviour by **id** from this registry; the registry is
the one place that knows what each id is, how it is realized and what it costs. Every row
carries two kinds of classification, so a coordinator can search by the agentic domain it
needs ("context management", or more precisely "context editing") and the materializer can
realize the selection by mechanism without a lane branch per feature:

- **Classification** (what the owner asks for): ``category`` is one of the six agentic
  domains of the Deep Agents surface sheet, ``facet`` is the precise sub-domain, and
  ``provenance`` says which package or API provides it.
- **Realization** (what the lane does): ``mechanism`` says whether the row is a middleware
  class, a provider-executed dict tool or a chat-model setting; ``adds_graph_nodes`` flags the
  rows that insert LangGraph nodes (they shift step numbering in the transcript);
  ``observability`` says whether Mission Control's hooks and limits see the calls.

Two axes discriminate the rows (OWNER-INTERVIEW R3): a **lane feature** belongs to a harness
(``lane="deep_agents"``) and a **model tool** belongs to the API behind the model
(``model_provider="openai"`` or ``"anthropic"``) and is valid only when the agent's model is
that provider's. ``status`` separates what the installed stack realizes today from what waits
for the Sprint A upgrade; selecting a row that is not ``available`` is a typed refusal with
the row's ``requires`` text, never a silent drop.

This module depends on nothing but Pydantic (``domain/capabilities`` rule). The lane feature
rows live in the sibling module ``deep_agents``; the vendor rows (``openai.*``,
``anthropic.*``) are the Deep Agents lane's model-route features and live in its package
(``adapters/deep_agents/routes.py``, OC-R6), where the lane's full registry is composed; the
builders that realize them live in ``adapters/deep_agents/features``. The vocabulary below
(``FeatureAxis``, ``ModelProvider``, ``Provenance``) is the sealed ``mc.agent_configuration.v1``
format the binding carries; it holds no vendor rows.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict

FEATURE_ID_PATTERN: Final = r"^(deep_agents|openai|anthropic)\.[a-z][a-z0-9_]*$"
ModelProvider = Literal["openai", "anthropic"]


class FeatureAxis(StrEnum):
    """Which axis a row discriminates on (R3.1)."""

    LANE_FEATURE = "lane_feature"
    MODEL_TOOL = "model_tool"


class CapabilityDomain(StrEnum):
    """The six agentic domains of the Deep Agents surface sheet ("Implications")."""

    CONTEXT_MANAGEMENT = "context_management"
    TOOLING = "tooling"
    DELEGATION = "delegation"
    CONTROL = "control"
    STATE = "state"
    PERSISTENCE = "persistence"


class CapabilityFacet(StrEnum):
    """The precise sub-domain a row serves; one category has several facets."""

    CONTEXT_EDITING = "context_editing"
    COMPACTION = "compaction"
    EVICTION = "eviction"
    MEMORY = "memory"
    PROMPT_CACHING = "prompt_caching"
    TOOL_SELECTION = "tool_selection"
    FILESYSTEM = "filesystem"
    SHELL = "shell"
    PLANNING = "planning"
    WEB = "web"
    CODE_EXECUTION = "code_execution"
    FILE_SEARCH = "file_search"
    BUDGET = "budget"
    MODERATION = "moderation"
    RESILIENCE = "resilience"
    PERMISSIONS = "permissions"
    SELF_EVALUATION = "self_evaluation"
    ROUTING = "routing"


class Mechanism(StrEnum):
    """How the lane realizes a row."""

    MIDDLEWARE = "middleware"
    PROVIDER_TOOL = "provider_tool"
    MODEL_SETTING = "model_setting"


class Observability(StrEnum):
    """Who sees the calls a row produces."""

    # Calls pass through the LangGraph tool node: hooks, limits, retries and HITL see them.
    TOOL_NODE = "tool_node"
    # The provider executes the call; only the model's content blocks carry evidence.
    SERVER_SIDE = "server_side"
    # No call of its own; it changes how every model call is made.
    MODEL_SETTINGS = "model_settings"


class Provenance(StrEnum):
    """Which package or API provides the behaviour."""

    DEEPAGENTS = "deepagents"
    LANGCHAIN = "langchain"
    LANGCHAIN_OPENAI = "langchain_openai"
    LANGCHAIN_ANTHROPIC = "langchain_anthropic"
    OPENAI_RESPONSES = "openai_responses_api"
    ANTHROPIC_MESSAGES = "anthropic_messages_api"


class FeatureStatus(StrEnum):
    """Whether the installed stack realizes a row."""

    AVAILABLE = "available"
    NEEDS_UPGRADE = "needs_upgrade"
    PLANNED = "planned"


class FeatureConfig(BaseModel):
    """Base of every row's configuration model."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class EmptyConfig(FeatureConfig):
    """A row that takes no configuration."""


@dataclass(frozen=True)
class FeatureDefinition:
    """One selectable row. ``config_model`` validates the mission's configuration.

    A dataclass, not a contract: rows are code, never parsed from documents, and a Pydantic
    field typed ``type[BaseModel]`` would make every model in the process a "declared" model
    for the digest guards.
    """

    id: str
    axis: FeatureAxis
    category: CapabilityDomain
    facet: CapabilityFacet
    provenance: Provenance
    mechanism: Mechanism
    observability: Observability
    summary: str
    # Set for a lane feature; None for a model tool.
    lane: Literal["deep_agents"] | None = None
    # Set for a model tool; None for a lane feature.
    model_provider: ModelProvider | None = None
    # The row inserts `before_*`/`after_*` graph nodes (step numbering shifts).
    adds_graph_nodes: bool = False
    # On by default for every agent the row applies to; the lane adapter inserts it
    # explicitly so the sealed binding never relies on an implicit stack.
    default: bool = False
    # A default row the mission cannot switch off (the stack requires it).
    required: bool = False
    # A default row inserted only when the agent runs on a sandbox backend (a shell needs
    # somewhere to run); on the in-memory state backend the mission must name it.
    default_requires_sandbox: bool = False
    config_model: type[BaseModel] = EmptyConfig
    status: FeatureStatus = FeatureStatus.AVAILABLE
    # What an unavailable row waits for (a package floor, a sprint); shown in refusals.
    requires: str | None = None
    # The order the materializer appends middleware rows in; stable step numbering.
    rank: int = 100

    def __post_init__(self) -> None:
        if not re.fullmatch(FEATURE_ID_PATTERN, self.id):
            raise ValueError(f"feature id {self.id!r} does not match {FEATURE_ID_PATTERN}")
        if not 1 <= len(self.summary) <= 400:
            raise ValueError(f"feature {self.id} summary must be 1 to 400 characters")
        if self.rank < 0:
            raise ValueError(f"feature {self.id} rank must not be negative")

    def applies_to(self, *, lane: str, model_provider: str) -> bool:
        if self.axis is FeatureAxis.LANE_FEATURE:
            return self.lane == lane
        return self.model_provider == model_provider

    def validate_config(self, payload: Mapping[str, Any] | None) -> dict[str, Any]:
        """The canonical configuration dump, or a ``ValueError`` naming the row."""

        try:
            parsed = self.config_model.model_validate(dict(payload or {}))
        except ValueError as error:
            raise ValueError(f"{self.id}: {error}") from error
        return parsed.model_dump(mode="json")

    def describe(self) -> dict[str, Any]:
        """The row as a describe table reads it (no Python types)."""

        return {
            "id": self.id,
            "axis": self.axis.value,
            "lane": self.lane,
            "model_provider": self.model_provider,
            "category": self.category.value,
            "facet": self.facet.value,
            "provenance": self.provenance.value,
            "mechanism": self.mechanism.value,
            "observability": self.observability.value,
            "adds_graph_nodes": self.adds_graph_nodes,
            "default": self.default,
            "default_requires_sandbox": self.default_requires_sandbox,
            "required": self.required,
            "status": self.status.value,
            "requires": self.requires,
            "summary": self.summary,
            "config_schema": self.config_model.model_json_schema(),
        }


class FeatureRegistry:
    """The rows by id, with the lookups the lane adapter and a coordinator need."""

    def __init__(self, rows: Iterable[FeatureDefinition]) -> None:
        self._rows: dict[str, FeatureDefinition] = {}
        for row in rows:
            if row.id in self._rows:
                raise ValueError(f"feature {row.id} is registered twice")
            namespace = row.id.split(".", 1)[0]
            if row.axis is FeatureAxis.LANE_FEATURE and (
                row.lane is None or row.model_provider is not None or namespace != row.lane
            ):
                raise ValueError(f"lane feature {row.id} must be namespaced by its lane")
            if row.axis is FeatureAxis.MODEL_TOOL and (
                row.model_provider is None
                or row.lane is not None
                or namespace != row.model_provider
            ):
                raise ValueError(f"model tool {row.id} must be namespaced by its provider")
            self._rows[row.id] = row

    def __iter__(self) -> Iterator[FeatureDefinition]:
        return iter(sorted(self._rows.values(), key=lambda row: (row.rank, row.id)))

    def __contains__(self, feature_id: object) -> bool:
        return feature_id in self._rows

    def __len__(self) -> int:
        return len(self._rows)

    def get(self, feature_id: str) -> FeatureDefinition:
        try:
            return self._rows[feature_id]
        except KeyError as error:
            raise KeyError(f"unknown agent capability {feature_id!r}") from error

    def lane_features(self, lane: str) -> tuple[FeatureDefinition, ...]:
        return tuple(
            row for row in self if row.axis is FeatureAxis.LANE_FEATURE and row.lane == lane
        )

    def model_tools(self, provider: str) -> tuple[FeatureDefinition, ...]:
        return tuple(
            row
            for row in self
            if row.axis is FeatureAxis.MODEL_TOOL and row.model_provider == provider
        )

    def defaults(
        self, *, lane: str, model_provider: str, sandboxed: bool = True
    ) -> tuple[FeatureDefinition, ...]:
        """The rows on by default for an agent on this lane with this model provider;
        ``sandboxed`` says whether the backend can run commands."""

        return tuple(
            row
            for row in self
            if row.default
            and row.status is FeatureStatus.AVAILABLE
            and row.applies_to(lane=lane, model_provider=model_provider)
            and (sandboxed or not row.default_requires_sandbox)
        )

    def by_category(self, category: CapabilityDomain) -> tuple[FeatureDefinition, ...]:
        return tuple(row for row in self if row.category is category)

    def by_facet(self, facet: CapabilityFacet) -> tuple[FeatureDefinition, ...]:
        return tuple(row for row in self if row.facet is facet)

    def search(self, text: str) -> tuple[FeatureDefinition, ...]:
        """Lexical match over id, category, facet, provenance and summary (the T0 search; the
        catalog projection of ADR-0025 is the hybrid one)."""

        terms = [term for term in text.lower().replace("-", "_").split() if term]
        if not terms:
            return tuple(self)
        matches: list[FeatureDefinition] = []
        for row in self:
            haystack = " ".join(
                (
                    row.id,
                    row.category.value,
                    row.facet.value,
                    row.provenance.value,
                    row.mechanism.value,
                    row.summary.lower(),
                )
            )
            if all(term in haystack for term in terms):
                matches.append(row)
        return tuple(matches)

    def describe(self) -> list[dict[str, Any]]:
        return [row.describe() for row in self]


__all__ = [
    "FEATURE_ID_PATTERN",
    "CapabilityDomain",
    "CapabilityFacet",
    "EmptyConfig",
    "FeatureAxis",
    "FeatureConfig",
    "FeatureDefinition",
    "FeatureRegistry",
    "FeatureStatus",
    "Mechanism",
    "ModelProvider",
    "Observability",
    "Provenance",
]
