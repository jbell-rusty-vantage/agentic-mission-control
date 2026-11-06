"""Declarations as data: lane declarations, Application Profiles and Model Profiles (ADR-0063).

What varies but does not behave. A lane declares its describe plus model routes, item and
family support and runtime pins; an application is one `deployments/<app>/application.toml`;
a model is one `deployments/<app>/models.toml` row that names no lane. The registries validate
these at bootstrap registration and the resolver reads them; nothing else branches on them.
"""

from __future__ import annotations

from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mission_control.domain.execution.data_class import DataClass
from mission_control.domain.execution.lanes import LaneDescribe
from mission_control.domain.resolution.configuration import (
    CONFIGURATION_ITEM_KINDS,
    FAMILIES,
    ConfigurationItemKind,
    Family,
    ModelPin,
    PriceTier,
    StructuredOutputStrategy,
    Vendor,
    check_model_limits,
)
from mission_control.domain.resolution.resolved import (
    KnowledgePortBinding,
    OutputContractProfile,
    TransferProfile,
)

APPLICATION_PROFILE_SCHEMA: Final = "mc.application_profile.v1"
MODEL_PROFILE_SCHEMA: Final = "mc.model_profile.v1"

ItemSupport = Literal["native", "emulated", "unsupported"]
FamilySupport = Literal["native", "unqualified", "unsupported"]
ModelCapability = Literal["structured_output", "tool_use", "images"]
# W1 D24: the OpenAI API surface a row's calls use. OpenAI refuses function tools together with
# reasoning on `/v1/chat/completions` for the gpt-5.6 family ("use /v1/responses or set
# reasoning_effort to 'none'"), so an OpenAI row with tool use declares `responses`.
ApiSurface = Literal["chat_completions", "responses"]


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ModelRoute(_Frozen):
    """How a lane reaches one vendor's models, in the lane's own words."""

    vendor: Vendor
    verdict: Literal["native", "emulated", "unsupported"]
    # e.g. "chat_anthropic_factory", "cli_native", "session_api".
    mechanism: str = Field(min_length=1, max_length=128)
    # W1 D16: the structured-output strategies this lane realizes for the vendor (empty: the
    # lane binds no structured response through this route). A lane's compile refuses a pinned
    # row whose strategy its route does not list (Deep Agents: MODEL_ROUTE_UNSUPPORTED).
    # Left out of dumps when empty, so the routes of lanes without strategies keep their shape.
    structured_output: tuple[StructuredOutputStrategy, ...] = Field(
        default=(), exclude_if=lambda value: not value
    )


class LaneDeclaration(_Frozen):
    """The lane describe (`mc.lane_describe.v2`) plus the three resolution sections.

    Two questions, two sources: whether the lane may run at all is `describe.qualified`
    (`LANE_UNQUALIFIED` unless the local-proof flag is set); whether it runs a family is
    `families` (`BLUEPRINT_FAMILY_UNSUPPORTED` for `unsupported`, and for `unqualified` unless
    the same flag is set). The resolver reads each fact from its one place.
    """

    describe: LaneDescribe
    model_routes: tuple[ModelRoute, ...]
    items: dict[ConfigurationItemKind, ItemSupport]
    families: dict[Family, FamilySupport]
    # Runtime/SDK/CLI pins the lane requires (`provider_launch.required_pins`).
    pins: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def complete_declaration(self) -> LaneDeclaration:
        vendors = [route.vendor for route in self.model_routes]
        if len(vendors) != len(set(vendors)):
            raise ValueError("a lane declares at most one route per vendor")
        if set(self.items) != set(CONFIGURATION_ITEM_KINDS):
            raise ValueError(f"a lane declares exactly {list(CONFIGURATION_ITEM_KINDS)}")
        if set(self.families) != set(FAMILIES):
            raise ValueError(f"a lane declares exactly {list(FAMILIES)}")
        return self

    @property
    def lane_profile(self) -> str:
        return self.describe.lane_profile

    def route(self, vendor: Vendor) -> ModelRoute | None:
        return next((route for route in self.model_routes if route.vendor == vendor), None)


# An interpretation of annex OUTPUT-CONTRACTS section 5 (application minimums and consequential
# scientific human sign-off cannot be weakened) using KS use classes (research-core
# `authority/rules.ts::USE_CLASS_VALUES`): an official or consequential use needs an exact-use
# decision with review, and a consequential use human sign-off. A profile may require more.
USE_CLASSES: Final = ("official", "consequential", "internal", "draft")
ANNEX_REQUIRED_REVIEW_CLASSES: Final = frozenset({"official", "consequential"})
ANNEX_CONSEQUENTIAL_SIGNOFF_CLASSES: Final = frozenset({"consequential"})


def below_annex_minimums(profile: ApplicationProfile) -> tuple[str, ...]:
    """What an Application Profile weakens relative to the minimums above (an interpretation
    of annex section 5 using KS use classes; empty: none)."""

    outputs = profile.outputs
    problems: list[str] = []
    unknown = sorted(
        set(outputs.required_review_classes + outputs.consequential_signoff_classes)
        - set(USE_CLASSES)
    )
    if unknown:
        problems.append(f"unknown use classes {unknown} (known: {list(USE_CLASSES)})")
    for name, required, declared in (
        (
            "required_review_classes",
            ANNEX_REQUIRED_REVIEW_CLASSES,
            outputs.required_review_classes,
        ),
        (
            "consequential_signoff_classes",
            ANNEX_CONSEQUENTIAL_SIGNOFF_CLASSES,
            outputs.consequential_signoff_classes,
        ),
    ):
        missing = sorted(required - set(declared))
        if missing:
            problems.append(f"outputs.{name} omits {missing}")
    return tuple(problems)


MIN_CLOSURE_RETENTION_DAYS: Final = 30


class WorkspaceClosureProfile(_Frozen):
    """`[workspace]`: the Workspace Closure caps and retention (OVE-204 slice 5).

    The adapter captures every agent-visible file of an attempt at its settled boundary; past
    `closure_max_files` files are omitted and past `closure_max_bytes` promoted bytes a body is
    withheld (`complete = false`), never failing the attempt. `closure_retention` is
    `"mission"` (rows live as long as the mission's evidence, ADR-0055) or whole days (at least
    30) after which the frames `expire` pass deletes the rows of completed runs.
    """

    closure_enabled: bool = True
    closure_max_files: int = Field(default=512, ge=0, le=100_000)
    closure_max_bytes: int = Field(default=64 * 1024 * 1024, ge=0)
    closure_retention: Literal["mission"] | int = "mission"

    @model_validator(mode="after")
    def retention(self) -> WorkspaceClosureProfile:
        days = self.closure_retention
        if not isinstance(days, str) and (
            isinstance(days, bool) or days < MIN_CLOSURE_RETENTION_DAYS
        ):
            raise ValueError(
                f"workspace.closure_retention is 'mission' or at least "
                f"{MIN_CLOSURE_RETENTION_DAYS} days"
            )
        return self

    @property
    def retention_days(self) -> int | None:
        """Whole days a closure row is kept; None is the mission's evidence life."""

        value = self.closure_retention
        return None if isinstance(value, str) else value


class ApplicationProfile(_Frozen):
    """`deployments/<app>/application.toml`: what may differ per application, as data."""

    schema_version: Literal["mc.application_profile.v1"] = APPLICATION_PROFILE_SCHEMA
    application_id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")
    revision: int = Field(ge=1)
    knowledge: KnowledgePortBinding
    data_class_ceiling: DataClass
    outputs: OutputContractProfile
    transfer: TransferProfile
    hosted_session_retention_days: int = Field(ge=0)
    # OVE-204 slice 5: the Workspace Closure caps and retention (`[workspace]`).
    workspace: WorkspaceClosureProfile = WorkspaceClosureProfile()


class ModelProfile(_Frozen):
    """One `deployments/<app>/models.toml` row. It names no lane (design §3)."""

    schema_version: Literal["mc.model_profile.v1"] = MODEL_PROFILE_SCHEMA
    # e.g. producer.default, judge.default, auditor.default, child.default.
    profile: str = Field(min_length=1, max_length=192)
    vendor: Vendor
    model_id: str = Field(min_length=1, max_length=256)
    context_window_tokens: int = Field(ge=1)
    # The largest prompt the vendor accepts (at most the window); what sizes a context.
    max_input_tokens: int = Field(ge=1)
    cost_per_million_input: float = Field(ge=0)
    cost_per_million_output: float = Field(ge=0)
    # Long-prompt list prices, rising by threshold (`[[models.price_tiers]]`).
    price_tiers: tuple[PriceTier, ...] = ()
    supports: tuple[ModelCapability, ...] = ()
    # W1 D16: how this model returns a structured response, from the vendor's documentation
    # (`configuration.StructuredOutputStrategy`); required exactly when `supports` names
    # `structured_output`, so a row never leaves the strategy to framework auto-detection.
    structured_output: StructuredOutputStrategy | None = None
    # W1 D24: an OpenAI row's API surface (`ApiSurface`); never set on another vendor's row.
    api_surface: ApiSurface | None = None
    data_class_ceiling: DataClass

    @model_validator(mode="after")
    def limits(self) -> ModelProfile:
        check_model_limits(
            context_window_tokens=self.context_window_tokens,
            max_input_tokens=self.max_input_tokens,
            price_tiers=self.price_tiers,
        )
        declared = "structured_output" in self.supports
        if declared and self.structured_output is None:
            raise ValueError(
                f"model profile {self.profile} supports structured_output but declares no "
                "structured_output strategy (tool_forced, provider_native or tool_auto)"
            )
        if not declared and self.structured_output is not None:
            raise ValueError(
                f"model profile {self.profile} declares a structured_output strategy but its "
                "supports omits structured_output"
            )
        if self.api_surface is not None and self.vendor != "openai":
            raise ValueError(
                f"model profile {self.profile} declares an api_surface; only OpenAI rows do"
            )
        return self

    def requires_responses_api(self) -> bool:
        """W1 D24: an OpenAI row whose calls carry function tools (tool use, or a tool-based
        structured-output strategy) must use the Responses API."""

        return self.vendor == "openai" and (
            "tool_use" in self.supports or self.structured_output in ("tool_forced", "tool_auto")
        )

    def pin(self, settings: dict[str, object] | None = None) -> ModelPin:
        return ModelPin(
            profile=self.profile,
            vendor=self.vendor,
            model_id=self.model_id,
            context_window_tokens=self.context_window_tokens,
            max_input_tokens=self.max_input_tokens,
            cost_per_million_input=self.cost_per_million_input,
            cost_per_million_output=self.cost_per_million_output,
            price_tiers=self.price_tiers,
            settings=dict(settings or {}),
            structured_output=self.structured_output,
        )


__all__ = [
    "ANNEX_CONSEQUENTIAL_SIGNOFF_CLASSES",
    "ANNEX_REQUIRED_REVIEW_CLASSES",
    "APPLICATION_PROFILE_SCHEMA",
    "MIN_CLOSURE_RETENTION_DAYS",
    "MODEL_PROFILE_SCHEMA",
    "USE_CLASSES",
    "ApplicationProfile",
    "FamilySupport",
    "ItemSupport",
    "LaneDeclaration",
    "ModelCapability",
    "ModelProfile",
    "ModelRoute",
    "WorkspaceClosureProfile",
    "below_annex_minimums",
]
