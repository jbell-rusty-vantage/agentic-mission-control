"""``mc.plugin_manifest.v1``: a plugin is a manifest of exact member pins (SPEC-01).

No install command, postinstall script or marketplace reference exists; compile expands the
members into the node's environment and ``capability_plugin_member`` records the expansion.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from enum import StrEnum
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mission_control.domain.capabilities.host_support import (
    CapabilityHostSupport,
    LaneProfile,
    intersect_host_support,
)
from mission_control.domain.capabilities.pins import CapabilityPin

PLUGIN_MANIFEST_SCHEMA: Final = "mc.plugin_manifest.v1"


class PluginMemberRole(StrEnum):
    SKILL = "skill"
    MCP_SERVER = "mcp_server"
    HOOK = "hook"
    SUBAGENT = "subagent"
    PROMPT = "prompt"
    RESOURCE = "resource"


# The `mc.agent_configuration.v2` item kind each member role becomes when a lane runs a
# plugin as its members.
MEMBER_ITEM_KINDS: Final[Mapping[PluginMemberRole, str]] = {
    PluginMemberRole.SKILL: "skill_bundle",
    PluginMemberRole.MCP_SERVER: "mcp_server",
    PluginMemberRole.HOOK: "hook_script",
    PluginMemberRole.SUBAGENT: "subagent_profile",
    PluginMemberRole.PROMPT: "context_bundle",
    PluginMemberRole.RESOURCE: "context_bundle",
}
# IP-011: the lane profiles that run a node's plugin as its members (each member bound,
# verified and pinned like a direct selection), and so can run only the member kinds their
# declaration carries. The file lanes project a plugin as one unit and are not listed.
MEMBER_EXPANDING_LANES: Final[frozenset[str]] = frozenset({LaneProfile.DEEP_AGENTS.value})


class PluginMember(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    pin: CapabilityPin
    role: PluginMemberRole
    optional: bool = False
    overlay: dict[str, object] = Field(default_factory=dict)


class PluginManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["mc.plugin_manifest.v1"] = PLUGIN_MANIFEST_SCHEMA
    members: tuple[PluginMember, ...] = Field(min_length=1)
    prompts: tuple[str, ...] = ()
    resources: tuple[str, ...] = ()

    @model_validator(mode="after")
    def members_are_distinct(self) -> PluginManifest:
        ids = [member.pin.capability_id for member in self.members]
        if len(ids) != len(set(ids)):
            raise ValueError("a plugin lists each member capability once")
        if all(member.optional for member in self.members):
            raise ValueError("a plugin needs at least one required member")
        return self

    def host_support(
        self, member_support: Callable[[CapabilityPin], CapabilityHostSupport]
    ) -> CapabilityHostSupport:
        """The intersection of the members' support, honouring ``optional``."""
        return intersect_host_support(
            (member_support(member.pin), member.optional) for member in self.members
        )
