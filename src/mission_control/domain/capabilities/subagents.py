"""``mc.subagent_profile.v1``: a provider-neutral delegate definition (SPEC-01).

Defined once, projected as ``.cursor/agents/<name>.md``, ``.claude/agents/<name>.md``,
``.codex/agents/<name>.md`` or a Deep Agents ``SubAgent`` dict.

The profile is the one subagent vocabulary every lane reads (provider consolidation P1-S3).
``kind`` says what the delegate *is* to Mission Control, independently of how a lane runs it:

- ``sync``: a child the parent calls and waits for, in the parent's process (Deep Agents
  ``SubAgent``, a Claude or Codex agent file);
- ``async``: a background subordinate on a served graph (the Agent Server for Deep Agents; a
  Mission Control async subordinate elsewhere);
- ``linked_run``: a whole Mission Control run on any lane, reached through a spawning tool.

``capabilities`` says which of the two child shapes every provider has the profile is
(P1 subagents, owner decision Q2/Q7 of 2026-10-20):

- ``inherit``: the provider's general child that inherits the parent's whole capability set
  (Deep Agents ``general-purpose``, Claude ``general-purpose``, Cursor built-ins). It names no
  capabilities of its own and may omit its prompt, in which case the lane's default child
  prompt is used and receipted by digest. Mission Control declares and receipts this child
  explicitly instead of letting a framework add it silently.
- ``seeded`` (the default): a child with its own selection. ``tools``, ``skills`` and
  ``mcp_servers`` name components **the parent already selected** (the child narrows them);
  ``seeds`` pins catalog capabilities of the child's own, resolved at compile like the
  parent's and **not limited to the parent's selection**, admitted against the node's grant
  and delegation ceiling at launch.

``placement`` and ``sandbox`` refine the kind; a lane that cannot honour a field reports it
in its materialization receipt (``degraded``) or refuses it (``unsupported``) at launch, never
silently. ``provider_overrides`` carries the few knobs that only one lane understands, keyed
by lane profile and typed by ``subagent_overrides.SUBAGENT_OVERRIDE_MODELS``; the lane adapter
that owns the key reads it, every other lane ignores it.

``SUBAGENT_FIELDS`` is the dotted vocabulary in which lanes classify a profile
(``subagents.fields`` on ``mc.lane_describe.v2``, the compile-time discriminator, the
receipt); :meth:`SubagentProfile.requested_fields` is the profile's side of that vocabulary.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.capabilities.pins import CapabilityPin
from mission_control.domain.capabilities.subagent_overrides import parse_subagent_overrides

SUBAGENT_PROFILE_SCHEMA: Final = "mc.subagent_profile.v1"

SubagentKind = Literal["sync", "async", "linked_run"]
SubagentPlacement = Literal["in_process", "agent_server", "lane"]
SubagentSandbox = Literal["shared", "own", "none"]
SubagentCapabilities = Literal["inherit", "seeded"]
SeedGroup = Literal["skills", "mcp_servers", "plugins", "tools"]

# The placement each kind takes unless the profile says otherwise, and the placements a kind
# may take at all. A sync child shares the parent's process; an async child runs on a served
# graph or as a lane subordinate; a linked run always runs on a lane.
DEFAULT_PLACEMENT: Final[Mapping[str, SubagentPlacement]] = {
    "sync": "in_process",
    "async": "agent_server",
    "linked_run": "lane",
}
ALLOWED_PLACEMENTS: Final[Mapping[str, frozenset[str]]] = {
    "sync": frozenset({"in_process"}),
    "async": frozenset({"agent_server", "lane"}),
    "linked_run": frozenset({"lane"}),
}

# The dotted vocabulary of profile fields a lane classifies. Values with per-value support
# (a lane may run sync children and refuse async ones) are spelled per value.
SUBAGENT_FIELDS: Final[tuple[str, ...]] = (
    "kind.sync",
    "kind.async",
    "kind.linked_run",
    "capabilities.inherit",
    "capabilities.seeded",
    "seeds.skills",
    "seeds.mcp_servers",
    "seeds.plugins",
    "seeds.tools",
    "model",
    "tools",
    "skills",
    "mcp_servers",
    "readonly",
    "background",
    "context_mode.fork",
    "interrupt_on",
    "max_turns",
    "sandbox.own",
    "sandbox.none",
    "budget",
    "placement.in_process",
    "placement.agent_server",
    "placement.lane",
)
SEED_GROUPS: Final[tuple[SeedGroup, ...]] = ("skills", "mcp_servers", "plugins", "tools")

# Names a lane already reserves for its built-in agents; a profile may not shadow them.
BUILTIN_SUBAGENT_NAMES = frozenset(
    {
        "explore",
        "shell",
        "bash",
        "browser",
        "debug",
        "computerUse",
        "cursorGuide",
        "general-purpose",
    }
)
_BUILTIN_FOLDED = frozenset(name.lower() for name in BUILTIN_SUBAGENT_NAMES)
_LANE_PROFILE_VALUES = frozenset(profile.value for profile in LaneProfile)
# The canonical walkers (`domain/authoring/canonical.py`) leave a field marked this way out of
# digests and seed manifests while it holds its default (same marker as `DIGEST_NEUTRAL_DEFAULT`).
_ADDITIVE: dict[str, Any] = {"digest_omit_default": True}


class SubagentSeeds(BaseModel):
    """Catalog pins a seeded child owns, independent of the parent's selection.

    Exact pins only, like plugin members: a published profile never carries a mutable
    reference. ``plugins`` expand into their Skill and MCP members at compile; a plugin's
    hook, subagent, prompt and resource members are not seeded into a child yet and are
    reported ``degraded`` by the lane that receives them.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    skills: tuple[CapabilityPin, ...] = ()
    mcp_servers: tuple[CapabilityPin, ...] = ()
    plugins: tuple[CapabilityPin, ...] = ()
    tools: tuple[CapabilityPin, ...] = ()

    @model_validator(mode="after")
    def at_least_one_distinct_seed(self) -> SubagentSeeds:
        ids = [pin.capability_id for _group, pin in self.items()]
        if not ids:
            raise ValueError("seeds needs at least one pin")
        if len(ids) != len(set(ids)):
            raise ValueError("seeds lists each capability once")
        return self

    def items(self) -> Iterator[tuple[SeedGroup, CapabilityPin]]:
        """Every seed with its group, in declaration order."""

        for group in SEED_GROUPS:
            for pin in getattr(self, group):
                yield group, pin

    def groups(self) -> tuple[SeedGroup, ...]:
        return tuple(group for group in SEED_GROUPS if getattr(self, group))


class SubagentProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["mc.subagent_profile.v1"] = SUBAGENT_PROFILE_SCHEMA
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$")
    description: str = Field(min_length=1, max_length=1000)
    prompt: str | None = Field(default=None, min_length=1, max_length=8192)
    prompt_bundle_ref: str | None = Field(default=None, min_length=1)
    model: str = Field(default="inherit", min_length=1)
    tools: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    mcp_servers: tuple[str, ...] = ()
    readonly: bool = False
    background: bool = False
    context_mode: Literal["isolated", "fork"] = "isolated"
    interrupt_on: tuple[str, ...] = ()
    max_turns: int | None = Field(default=None, ge=1, le=1000)
    # P1-S3: what the delegate is, where it runs, whose sandbox it uses and what it may spend.
    # Defaults are excluded from dumps (`exclude_if`) and from every canonical digest
    # (`digest_omit_default`, ADR-0020), so every profile published before these fields keeps
    # its catalog digest and seed bytes and validates unchanged.
    kind: SubagentKind = Field(
        default="sync", exclude_if=lambda value: value == "sync", json_schema_extra=_ADDITIVE
    )
    placement: SubagentPlacement | None = Field(
        default=None, exclude_if=lambda value: value is None, json_schema_extra=_ADDITIVE
    )
    sandbox: SubagentSandbox = Field(
        default="shared", exclude_if=lambda value: value == "shared", json_schema_extra=_ADDITIVE
    )
    budget: dict[str, int] = Field(
        default_factory=dict, exclude_if=lambda value: not value, json_schema_extra=_ADDITIVE
    )
    provider_overrides: dict[str, dict[str, Any]] = Field(
        default_factory=dict, exclude_if=lambda value: not value, json_schema_extra=_ADDITIVE
    )
    # P1 subagents (Q7): the child shape and the child's own catalog seeds. Same additive rule.
    capabilities: SubagentCapabilities = Field(
        default="seeded",
        exclude_if=lambda value: value == "seeded",
        json_schema_extra=_ADDITIVE,
    )
    seeds: SubagentSeeds | None = Field(
        default=None, exclude_if=lambda value: value is None, json_schema_extra=_ADDITIVE
    )

    @field_validator("name")
    @classmethod
    def not_a_lane_builtin(cls, value: str) -> str:
        if value.lower() in _BUILTIN_FOLDED:
            raise ValueError(f"subagent name {value!r} collides with a lane built-in agent")
        return value

    @field_validator("budget")
    @classmethod
    def positive_budget(cls, value: dict[str, int]) -> dict[str, int]:
        for dimension, amount in value.items():
            if not dimension or amount < 1:
                raise ValueError(f"subagent budget {dimension!r} must be a positive amount")
        return value

    @field_validator("provider_overrides")
    @classmethod
    def overrides_are_typed_per_lane(
        cls, value: dict[str, dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        unknown = sorted(set(value) - _LANE_PROFILE_VALUES)
        if unknown:
            raise ValueError(f"provider_overrides name unknown lane profiles: {unknown}")
        for lane, payload in value.items():
            try:
                parse_subagent_overrides(lane, payload)
            except ValueError as error:
                raise ValueError(f"provider_overrides.{lane}: {error}") from error
        return value

    @model_validator(mode="after")
    def prompt_matches_the_child_shape(self) -> SubagentProfile:
        both = self.prompt is not None and self.prompt_bundle_ref is not None
        neither = self.prompt is None and self.prompt_bundle_ref is None
        if both:
            raise ValueError("a subagent profile carries one of prompt or prompt_bundle_ref")
        if neither and self.capabilities != "inherit":
            raise ValueError(
                "a seeded subagent profile needs exactly one of prompt or prompt_bundle_ref"
            )
        return self

    @model_validator(mode="after")
    def inherit_names_nothing_of_its_own(self) -> SubagentProfile:
        if self.capabilities == "inherit" and (
            self.tools or self.skills or self.mcp_servers or self.seeds is not None
        ):
            raise ValueError(
                "an inherit subagent takes the parent's whole capability set; it cannot name "
                "tools, skills, mcp_servers or seeds"
            )
        return self

    @model_validator(mode="after")
    def placement_fits_kind(self) -> SubagentProfile:
        if self.placement is not None and self.placement not in ALLOWED_PLACEMENTS[self.kind]:
            raise ValueError(
                f"a {self.kind} subagent cannot be placed {self.placement}; "
                f"allowed: {sorted(ALLOWED_PLACEMENTS[self.kind])}"
            )
        return self

    @property
    def effective_placement(self) -> SubagentPlacement:
        """The declared placement, or the kind's default."""

        return self.placement or DEFAULT_PLACEMENT[self.kind]

    @property
    def inherits(self) -> bool:
        return self.capabilities == "inherit"

    def overrides_for(self, lane_profile: str) -> Mapping[str, Any]:
        """The provider-specific knobs one lane may read; empty for every other lane."""

        return self.provider_overrides.get(lane_profile, {})

    def requested_fields(self, overlay: Mapping[str, object] | None = None) -> tuple[str, ...]:
        """The ``SUBAGENT_FIELDS`` this profile asks a lane for, in vocabulary order.

        ``overlay`` is the manifest ``agents[].overlay`` (``readonly``, ``is_background``,
        ``model``), which may switch a field on for one node without changing the profile.
        """

        overlay = overlay or {}
        model = overlay.get("model", self.model)
        requested = {
            f"kind.{self.kind}",
            f"capabilities.{self.capabilities}",
            f"placement.{self.effective_placement}",
        }
        requested.update(f"seeds.{group}" for group in (self.seeds.groups() if self.seeds else ()))
        flags = {
            "model": model != "inherit",
            "tools": bool(self.tools),
            "skills": bool(self.skills),
            "mcp_servers": bool(self.mcp_servers),
            "readonly": bool(overlay.get("readonly", self.readonly)),
            "background": bool(overlay.get("is_background", self.background)),
            "context_mode.fork": self.context_mode == "fork",
            "interrupt_on": bool(self.interrupt_on),
            "max_turns": self.max_turns is not None,
            f"sandbox.{self.sandbox}": self.sandbox != "shared",
            "budget": bool(self.budget),
        }
        requested.update(name for name, is_set in flags.items() if is_set)
        return tuple(name for name in SUBAGENT_FIELDS if name in requested)


__all__ = [
    "ALLOWED_PLACEMENTS",
    "BUILTIN_SUBAGENT_NAMES",
    "DEFAULT_PLACEMENT",
    "SEED_GROUPS",
    "SUBAGENT_FIELDS",
    "SUBAGENT_PROFILE_SCHEMA",
    "SeedGroup",
    "SubagentCapabilities",
    "SubagentKind",
    "SubagentPlacement",
    "SubagentProfile",
    "SubagentSandbox",
    "SubagentSeeds",
]
