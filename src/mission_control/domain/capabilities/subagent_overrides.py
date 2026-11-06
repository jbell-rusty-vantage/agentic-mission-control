"""Typed per-lane subagent overrides, discriminated by lane profile (P1 subagents, Q1).

``mc.subagent_profile.v1`` is lane-neutral. The few knobs that only one lane understands live
under ``provider_overrides``, keyed by the lane profile that reads them:

.. code-block:: yaml

    provider_overrides:
      deep_agents:
        writable_root: /subagents/reviewer
        state_channels: [artifact_index]

Each key names a lane profile and is validated by that lane's overrides model, registered in
``SUBAGENT_OVERRIDE_MODELS``. A lane absent from the registry accepts no key, so an override
never travels to a lane that would ignore it; a key for a lane the node does not run on is a
compile blocker (``subagent_override_lane_mismatch``, the discriminator's job). The lane
adapter that owns the key is the only reader and records what it honoured in the
materialization receipt.

This module is the registry of which overrides exist, not how a lane applies them; it is the
subagent counterpart of ``domain/authoring/provider_options.py`` and follows its rules.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SUBAGENT_OVERRIDES_SCHEMA_PREFIX: Final = "mc.subagent_overrides."


class _Overrides(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DeepAgentsSubagentOverrides(_Overrides):
    """``mc.subagent_overrides.deep_agents.v1``: what only a Deep Agents child understands.

    - ``writable_root`` replaces the lane's default writable path for the child
      (``/subagents/<name>``) inside the parent's backend; it must be absolute and must not
      be the root.
    - ``state_channels`` names BellLabs base channels the child's state slice may read in
      addition to the lane defaults; a channel the parent schema does not carry is refused
      at launch by the adapter, never dropped.
    """

    schema_version: Literal["mc.subagent_overrides.deep_agents.v1"] = (
        "mc.subagent_overrides.deep_agents.v1"
    )
    writable_root: str | None = Field(default=None, pattern=r"^/[^\s]*[^/\s]$")
    state_channels: tuple[str, ...] = Field(default=(), max_length=32)

    @model_validator(mode="after")
    def unique_channels(self) -> DeepAgentsSubagentOverrides:
        if len(set(self.state_channels)) != len(self.state_channels):
            raise ValueError("state_channels names a channel twice")
        return self


SubagentOverridesModel = DeepAgentsSubagentOverrides

# The lanes with typed subagent overrides today. A lane absent here accepts no key: adding one
# is a reviewed change to this registry, with that lane's adapter as its reader (WP-S5 adds
# the Claude, Codex and Cursor models beside their adapters).
SUBAGENT_OVERRIDE_MODELS: Final[Mapping[str, type[SubagentOverridesModel]]] = {
    "deep_agents": DeepAgentsSubagentOverrides,
}


def parse_subagent_overrides(
    lane_profile: str, payload: Mapping[str, Any]
) -> SubagentOverridesModel:
    """Validate one lane's overrides block; an unregistered lane is an authoring error."""

    model = SUBAGENT_OVERRIDE_MODELS.get(lane_profile)
    if model is None:
        raise ValueError(
            f"lane {lane_profile} has no typed subagent overrides; "
            f"known: {sorted(SUBAGENT_OVERRIDE_MODELS)}"
        )
    return model.model_validate(dict(payload))


def subagent_overrides_lane_mismatch(
    overrides: Mapping[str, Any] | None, *, lanes: tuple[str, ...]
) -> tuple[str, ...]:
    """The override keys that name a lane the selecting node does not run on."""

    if not overrides:
        return ()
    return tuple(sorted(key for key in overrides if key not in set(lanes)))


__all__ = [
    "SUBAGENT_OVERRIDES_SCHEMA_PREFIX",
    "SUBAGENT_OVERRIDE_MODELS",
    "DeepAgentsSubagentOverrides",
    "SubagentOverridesModel",
    "parse_subagent_overrides",
    "subagent_overrides_lane_mismatch",
]
