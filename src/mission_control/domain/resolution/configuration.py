"""``mc.agent_configuration.v2``: the lane-neutral configuration of one agent (ADR-0063).

The compiler builds one :class:`AgentConfiguration` per node before any lane is consulted: the
model pin and one :class:`ConfigurationItem` per skill bundle, MCP server, tool, hook script,
subagent profile, environment kit, context bundle, middleware and sandbox profile. Each item
carries its exact Capability Pin and digest and whether the mission ``require``d it. A lane
adapter's ``compile`` translates the items into its native form and signs a
:class:`~mission_control.domain.execution.materialization_receipt.MaterializationReceipt`; the
receipt, not this configuration, carries the lane's mechanism.

v2 drops the Deep Agents feature vocabulary of ``mc.agent_configuration.v1`` (``FeatureAxis``,
``Mechanism``, ``ModelProvider`` and ``lane: Literal["deep_agents"]``): those are one lane's
realization concepts and stay in that lane's package (design §8, the vocabulary rule).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator

from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.manifest import PIN_PATTERN
from mission_control.domain.execution.data_class import DataClass, DataClassSource
from mission_control.domain.execution.materialization_receipt import MaterializationKind

AGENT_CONFIGURATION_V2_SCHEMA: Final = "mc.agent_configuration.v2"
PLACEHOLDER_DIGEST: Final = "sha256:" + "0" * 64
DIGEST_PATTERN: Final = r"^sha256:[0-9a-f]{64}$"

# A lane's verdict on one item: the receipt vocabulary (`MaterializationVerdict`).
Verdict = Literal["native", "emulated", "degraded", "unsupported"]
# The model vendor. It grows by data: a new vendor is a `models.toml` row the catalog validates
# against this vocabulary, then one more literal here (design §3).
Vendor = Literal["anthropic", "openai"]
VENDORS: Final[tuple[Vendor, ...]] = ("anthropic", "openai")
# How a model returns a node's structured response (W1 D16), declared per `models.toml` row:
# `tool_forced` makes the schema a tool the model must call (`tool_choice` any/required);
# `provider_native` uses the vendor's own response-format constraint (Anthropic
# `output_config.format`, OpenAI `response_format` json_schema) beside `tool_choice` auto.
# `tool_auto` (W1 D18) makes the schema an ordinary tool the model calls with `tool_choice`
# auto, the host enforcing exactly one valid call: no constrained-decoding grammar is compiled.
# Claude Sonnet 5.5 rejects forced tool choice (D16) and compiled the executor observation as
# "Schema is too complex" (D18), so its rows declare `tool_auto`. A lane realizes a strategy
# only where its route declares it.
StructuredOutputStrategy = Literal["tool_forced", "provider_native", "tool_auto"]
STRUCTURED_OUTPUT_STRATEGIES: Final[tuple[StructuredOutputStrategy, ...]] = (
    "tool_forced",
    "provider_native",
    "tool_auto",
)
Family = Literal["StageGraph", "GoalDirected", "ParallelSwarm", "EvaluatorOptimizer"]
FAMILIES: Final[tuple[Family, ...]] = (
    "StageGraph",
    "GoalDirected",
    "ParallelSwarm",
    "EvaluatorOptimizer",
)
ConfigurationItemKind = Literal[
    "skill_bundle",
    "mcp_server",
    "tool",
    "hook_script",
    "subagent_profile",
    "environment_kit",
    "context_bundle",
    "middleware",
    "sandbox_profile",
]
CONFIGURATION_ITEM_KINDS: Final[tuple[ConfigurationItemKind, ...]] = (
    "skill_bundle",
    "mcp_server",
    "tool",
    "hook_script",
    "subagent_profile",
    "environment_kit",
    "context_bundle",
    "middleware",
    "sandbox_profile",
)
# The receipt row kind each configuration item is signed under (`mc.materialization_receipt.v1`).
RECEIPT_KIND: Final[Mapping[ConfigurationItemKind, MaterializationKind]] = {
    "skill_bundle": "skill",
    "mcp_server": "mcp_server",
    "tool": "tool",
    "hook_script": "hook",
    "subagent_profile": "subagent",
    "environment_kit": "environment_kit",
    "context_bundle": "context_packet",
    "middleware": "middleware",
    "sandbox_profile": "sandbox",
}


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ConfigurationItem(_Frozen):
    """One configured item: what the mission selected, exactly, with no lane vocabulary."""

    kind: ConfigurationItemKind
    # The manifest alias (`as:`), unique within the node.
    name: str = Field(min_length=1, max_length=256)
    # The exact Capability Pin `<id>@<version>#sha256:<digest>`.
    pin: str = Field(pattern=PIN_PATTERN)
    digest: str = Field(pattern=DIGEST_PATTERN)
    # From the manifest's `require:` and plugin expansion.
    required: bool
    # Kind-specific neutral configuration (tool subset, hook events, child kind ...).
    config: dict[str, Any] = Field(default_factory=dict)
    config_digest: str = Field(pattern=DIGEST_PATTERN)

    @model_validator(mode="after")
    def exact_item(self) -> ConfigurationItem:
        if not self.pin.endswith("#" + self.digest):
            raise ValueError(f"item {self.name}: pin {self.pin} must end in its digest")
        if sha256_digest(self.config) != self.config_digest:
            raise ValueError(f"item {self.name}: configuration digest mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        kind: ConfigurationItemKind,
        name: str,
        pin: str,
        required: bool,
        config: Mapping[str, Any] | None = None,
    ) -> ConfigurationItem:
        canonical = dict(config or {})
        _, _, digest = pin.partition("#")
        return cls(
            kind=kind,
            name=name,
            pin=pin,
            digest=digest,
            required=required,
            config=canonical,
            config_digest=sha256_digest(canonical),
        )

    @property
    def receipt_kind(self) -> MaterializationKind:
        return RECEIPT_KIND[self.kind]


class PriceTier(_Frozen):
    """A list price that replaces the base price for a request whose prompt exceeds
    `above_input_tokens` (the whole request is billed at the tier, as both vendors price it)."""

    above_input_tokens: int = Field(ge=1)
    cost_per_million_input: float = Field(ge=0)
    cost_per_million_output: float = Field(ge=0)


def check_model_limits(
    *,
    context_window_tokens: int,
    max_input_tokens: int,
    price_tiers: tuple[PriceTier, ...],
) -> None:
    """The input limit fits the window; tiers rise strictly and start below the input limit."""

    if max_input_tokens > context_window_tokens:
        raise ValueError("max_input_tokens exceeds context_window_tokens")
    thresholds = [tier.above_input_tokens for tier in price_tiers]
    if thresholds != sorted(set(thresholds)):
        raise ValueError("price tiers rise strictly by above_input_tokens")
    if thresholds and thresholds[-1] >= max_input_tokens:
        raise ValueError("a price tier starts at or above max_input_tokens")


class ModelPin(_Frozen):
    """The admitted model profile, the vendor and exact model it resolved to, and its cost.

    The v2 shape of `domain/execution/bindings.ModelPin` (which stays for the provider and
    Cursor lanes' sealed bindings); the Model Catalog builds this pin from one Model Profile
    row. Whatever sizes a context reads `max_input_tokens`, never the window (OC-R6 review).
    """

    profile: str = Field(min_length=1, max_length=192)
    vendor: Vendor
    model_id: str = Field(min_length=1, max_length=256)
    context_window_tokens: int = Field(ge=1)
    # The largest prompt the vendor accepts; at most the window (the OpenAI rows accept less).
    max_input_tokens: int = Field(ge=1)
    cost_per_million_input: float = Field(ge=0)
    cost_per_million_output: float = Field(ge=0)
    # Long-prompt list prices (Claude Haiku 5.5 above 100K, gpt-5.6-terra above 272K).
    price_tiers: tuple[PriceTier, ...] = ()
    # Vendor-neutral names only: temperature, reasoning effort, max output tokens ...
    settings: dict[str, Any] = Field(default_factory=dict)
    # W1 D16: the row's structured-output strategy (None: the row declares no structured
    # output). Absent from dumps and digests when None, so earlier pins keep their bytes.
    structured_output: StructuredOutputStrategy | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def limits(self) -> ModelPin:
        check_model_limits(
            context_window_tokens=self.context_window_tokens,
            max_input_tokens=self.max_input_tokens,
            price_tiers=self.price_tiers,
        )
        return self


class AgentConfiguration(_Frozen):
    """`mc.agent_configuration.v2`: one node's agent, sealed under its digest."""

    schema_version: Literal["mc.agent_configuration.v2"] = AGENT_CONFIGURATION_V2_SCHEMA
    # Validated by the Lane Registry, never a Literal of one lane.
    lane_profile: str = Field(min_length=1, max_length=64)
    node_ref: str = Field(min_length=1, max_length=512)
    # The layered instruction overlay (ADR-0044), by digest.
    instructions_ref: str = Field(pattern=DIGEST_PATTERN)
    model: ModelPin
    items: tuple[ConfigurationItem, ...] = ()
    # Tokens, cost, wall clock, iterations: neutral names.
    budgets: dict[str, Any] = Field(default_factory=dict)
    data_class: DataClass
    # OC-R4: where `data_class` came from. `declared`: the mission declared it;
    # `ceiling_default`: the mission declared none and failed closed to the most sensitive
    # class the lane and the application's ceiling admit. In the digest, so an undeclared
    # mission never seals to the same configuration as a declared one.
    data_class_source: DataClassSource
    configuration_digest: str = Field(pattern=DIGEST_PATTERN)

    @model_validator(mode="after")
    def exact_configuration(self, info: ValidationInfo) -> AgentConfiguration:
        names = [item.name for item in self.items]
        if len(names) != len(set(names)):
            raise ValueError("an agent configuration names each item once")
        if list(self.items) != sorted(self.items, key=lambda item: (item.kind, item.name)):
            raise ValueError("agent configuration items are ordered by (kind, name)")
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
        lane_profile: str,
        node_ref: str,
        instructions_ref: str,
        model: ModelPin,
        items: Iterable[ConfigurationItem] = (),
        budgets: Mapping[str, Any] | None = None,
        data_class: DataClass,
        data_class_source: DataClassSource,
    ) -> AgentConfiguration:
        draft = cls.model_validate(
            {
                "lane_profile": lane_profile,
                "node_ref": node_ref,
                "instructions_ref": instructions_ref,
                "model": model,
                "items": tuple(sorted(items, key=lambda item: (item.kind, item.name))),
                "budgets": dict(budgets or {}),
                "data_class": data_class,
                "data_class_source": data_class_source,
                "configuration_digest": PLACEHOLDER_DIGEST,
            },
            context={"allow_placeholder_digest": True},
        )
        return cls.model_validate(
            {**draft.model_dump(mode="python"), "configuration_digest": draft.content_digest()}
        )

    def item(self, name: str) -> ConfigurationItem | None:
        return next((item for item in self.items if item.name == name), None)

    def required_items(self) -> tuple[ConfigurationItem, ...]:
        return tuple(item for item in self.items if item.required)


__all__ = [
    "AGENT_CONFIGURATION_V2_SCHEMA",
    "CONFIGURATION_ITEM_KINDS",
    "FAMILIES",
    "RECEIPT_KIND",
    "STRUCTURED_OUTPUT_STRATEGIES",
    "VENDORS",
    "AgentConfiguration",
    "ConfigurationItem",
    "ConfigurationItemKind",
    "Family",
    "ModelPin",
    "PriceTier",
    "StructuredOutputStrategy",
    "Vendor",
    "Verdict",
    "check_model_limits",
]
