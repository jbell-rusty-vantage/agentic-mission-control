"""The declared lane matrices: an aggregator over each lane package's `describe.py` (OC-R3).

Each lane package owns its describe matrix and its `LaneDeclaration` (model routes, item and
family support, runtime pins; ADR-0063, design §6.1): `adapters/deep_agents/describe.py`,
`adapters/cursor/describe.py`, `adapters/claude/describe.py`, `adapters/codex/describe.py`,
`adapters/anthropic_managed/describe.py` and `adapters/openai_agents/describe.py`. Those
modules are declarations as data: they import domain types only, which is why this one module
of the application layer may read them (`tests/architecture/test_package_boundaries.py`). It
names every profile once and nothing else does; consumers ask it for a profile's matrix or
declaration by name and never branch on a lane.

These are the matrices each lane implementation is held to by the conformance and
describe-honesty tests. The three FT-G1 profiles keep their `mc.lane_describe.v1` cells and
digests (Deep Agents is still v1; the Cursor `*_V1` cells stay readable). A lane flips cells to
`native`/`emulated` only with its harness and to `qualified` only with a recorded drill
(SPEC-07 section 12).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from mission_control.adapters.anthropic_managed.describe import (
    CLAUDE_MANAGED_DECLARATION,
    CLAUDE_MANAGED_LAUNCH_NOTE,
)
from mission_control.adapters.claude.describe import (
    CLAUDE_AGENT_SDK_DECLARATION,
    CLAUDE_CLOUD_DECLARATION,
    CLAUDE_CLOUD_LAUNCH_EVIDENCE,
)
from mission_control.adapters.codex.describe import (
    CODEX_CLOUD_DECLARATION,
    CODEX_CLOUD_LAUNCH_EVIDENCE,
    CODEX_DECLARATION,
)
from mission_control.adapters.cursor.describe import (
    CURSOR_CLOUD_DECLARATION,
    CURSOR_LOCAL_DECLARATION,
)
from mission_control.adapters.deep_agents.describe import DEEP_AGENTS_DECLARATION
from mission_control.adapters.openai_agents.describe import (
    CODEX_AGENTS_DECLARATION,
    CODEX_AGENTS_LAUNCH_NOTE,
)
from mission_control.domain.execution.lanes import LaneDescribe, LaneProfileName
from mission_control.domain.resolution.profiles import LaneDeclaration

DECLARED_LANES: Final[Mapping[LaneProfileName, LaneDeclaration]] = {
    "deep_agents": DEEP_AGENTS_DECLARATION,
    "cursor_local": CURSOR_LOCAL_DECLARATION,
    "cursor_cloud": CURSOR_CLOUD_DECLARATION,
    "claude_agent_sdk": CLAUDE_AGENT_SDK_DECLARATION,
    "codex": CODEX_DECLARATION,
    "claude_cloud": CLAUDE_CLOUD_DECLARATION,
    "codex_cloud": CODEX_CLOUD_DECLARATION,
    "claude_managed": CLAUDE_MANAGED_DECLARATION,
    "codex_agents": CODEX_AGENTS_DECLARATION,
}

DECLARED_LANE_MATRICES: Final[dict[LaneProfileName, LaneDescribe]] = {
    profile: declaration.describe for profile, declaration in DECLARED_LANES.items()
}

# Deep Agents keeps its digest-stable FT-G1 v1 matrix. The Cursor, Claude, Codex and Managed
# Agents lanes have implemented v2 matrices (per-feature evidence, nothing qualified); the hosted
# products are v2 stubs with every control unqualified.
V1_LANE_PROFILES: Final[frozenset[LaneProfileName]] = frozenset({"deep_agents"})
V2_IMPLEMENTED_LANE_PROFILES: Final[frozenset[LaneProfileName]] = frozenset(
    {"cursor_local", "cursor_cloud", "claude_agent_sdk", "codex", "claude_managed", "codex_agents"}
)
V2_STUB_LANE_PROFILES: Final[frozenset[LaneProfileName]] = frozenset(
    {"claude_cloud", "codex_cloud"}
)
# The FT-G1 profiles `mission/v1` admits (their `mc.lane_describe.v1` cells exist); the MP-01
# profiles are reserved there and need `mission/v2`.
MISSION_V1_LANE_PROFILES: Final[frozenset[LaneProfileName]] = frozenset(
    {"deep_agents", "cursor_local", "cursor_cloud"}
)
# Profiles that compile structurally but whose launch is refused, with the evidence that says
# why (MP-18/19: the provider-hosted lifecycle is evidence-blocked).
LAUNCH_BLOCKED_EVIDENCE: Final[Mapping[LaneProfileName, str]] = {
    "claude_cloud": CLAUDE_CLOUD_LAUNCH_EVIDENCE,
    "codex_cloud": CODEX_CLOUD_LAUNCH_EVIDENCE,
}
# Profiles a `mission/v2` manifest compiles with a launch-refused warning until their lanes land
# (ADR-0050), with the work items that land them.
DESCRIBE_ONLY_LAUNCH_EVIDENCE: Final[Mapping[LaneProfileName, str]] = {
    "claude_managed": CLAUDE_MANAGED_LAUNCH_NOTE,
    "codex_agents": CODEX_AGENTS_LAUNCH_NOTE,
}


def declared_lane(lane_profile: str) -> LaneDeclaration:
    """The lane package's declaration of `lane_profile`; an undeclared profile is an error."""

    try:
        return DECLARED_LANES[lane_profile]  # type: ignore[index]
    except KeyError as error:
        raise ValueError(f"undeclared lane profile: {lane_profile}") from error


def declared_matrix(lane_profile: str) -> LaneDescribe:
    return declared_lane(lane_profile).describe


__all__ = [
    "DECLARED_LANES",
    "DECLARED_LANE_MATRICES",
    "DESCRIBE_ONLY_LAUNCH_EVIDENCE",
    "LAUNCH_BLOCKED_EVIDENCE",
    "MISSION_V1_LANE_PROFILES",
    "V1_LANE_PROFILES",
    "V2_IMPLEMENTED_LANE_PROFILES",
    "V2_STUB_LANE_PROFILES",
    "declared_lane",
    "declared_matrix",
]
