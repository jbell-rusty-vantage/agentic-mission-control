"""The neutral keys of `ConfigurationItem.config` the launch author writes and a lane reads.

Each key states a manifest fact any lane with the concept can use (the two-lane rule, design
§8): which manifest role selected the item, a subagent profile's catalog body, manifest overlay
and position among the node's children, the child a capability seeds, the plugin that expanded
a member and that member's role, and a profile-named selection. None is Deep Agents vocabulary;
a key only one lane could honour belongs in that lane's `lane_options` instead.
"""

from __future__ import annotations

from typing import Final

# The manifest role that selected the item (`capability`, `skill`, `hook`, `context`, `agent`).
ROLE: Final = "role"
# A subagent profile item: its `mc.subagent_profile.v1` catalog body (JSON), the manifest
# `agents[].overlay`, and its position among the node's children (manifest order).
PROFILE: Final = "profile"
OVERLAY: Final = "overlay"
POSITION: Final = "position"
# The child (subagent profile name) a capability seeds; absent on the node's own items.
SEED_OF: Final = "seed_of"
# A plugin member: its role in the plugin and the plugin that expanded it (`<id>@<version>`).
PLUGIN_MEMBER_ROLE: Final = "plugin_member_role"
PLUGIN: Final = "plugin"
# A selection named by a deployment profile, not a catalog pin (a sandbox profile).
PROFILE_NAME: Final = "profile_name"

__all__ = [
    "OVERLAY",
    "PLUGIN",
    "PLUGIN_MEMBER_ROLE",
    "POSITION",
    "PROFILE",
    "PROFILE_NAME",
    "ROLE",
    "SEED_OF",
]
