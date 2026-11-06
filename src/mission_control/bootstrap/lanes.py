"""The lane packages this distribution registers (ADR-0063 D2; OC-R3): the one place the
session lanes' package registrations are listed.

Deep Agents registers through `adapters/deep_agents/compile.deep_agents_lane(facts)` because its
compile needs the deployment's facts; every other lane package exports `LANES`, registrations
with the describe-only compile (OC-D199). The worker (`compose_lane_registry`) pairs each with
the harness it composed; the launch author (`bootstrap/resolution.compose_launch_resolution`)
registers them describe-only so the resolution seam can admit their nodes.

Which lanes an installation binds is decided here too (OC-R7 S3): `bound_lane_profiles` names
each lane's credential once, and `describe_only_registry` publishes only the bound ones to a
process that lists lanes but runs none (the public API).
"""

from __future__ import annotations

from collections.abc import Container, Iterable, Mapping
from typing import TYPE_CHECKING, Final

from mission_control.adapters.anthropic_managed.lane import LANES as ANTHROPIC_MANAGED_LANES
from mission_control.adapters.claude.lane import LANES as CLAUDE_LANES
from mission_control.adapters.codex.lane import LANES as CODEX_LANES
from mission_control.adapters.cursor.lane import LANES as CURSOR_LANES
from mission_control.adapters.openai_agents.lane import LANES as OPENAI_AGENTS_LANES
from mission_control.application.execution.harness.describe import DECLARED_LANE_MATRICES
from mission_control.application.resolution.ports import LaneRegistration
from mission_control.application.resolution.registries import LaneRegistry, describe_only_lanes
from mission_control.domain.execution.lanes import (
    DEFAULT_LANE_PROFILE,
    LANE_OF_PROFILE,
    LANE_PROFILES,
    LaneProfileName,
)

if TYPE_CHECKING:
    from mission_control.bootstrap.settings import Settings

SESSION_LANES: Final[Mapping[str, LaneRegistration]] = {
    registration.profile: registration
    for registration in (
        *CURSOR_LANES,
        *CLAUDE_LANES,
        *CODEX_LANES,
        *ANTHROPIC_MANAGED_LANES,
        *OPENAI_AGENTS_LANES,
    )
}


def bound_lane_profiles(
    *,
    cursor: bool = False,
    claude: bool = False,
    codex: bool = False,
    anthropic_api: bool = False,
    openai_api: bool = False,
) -> frozenset[LaneProfileName]:
    """The lane profiles an installation binds: `deep_agents` always; each lane's profiles when
    its provider credential is bound (`cursor`, `claude`, `codex`). The hosted products ride on
    their lane's credential; the API-billed hosted agent APIs (ADR-0050) need their own API key
    instead (`anthropic_api` for `claude_managed`, `openai_api` for `codex_agents`)."""

    lanes = {"cursor": cursor, "claude": claude, "codex": codex}
    api = {"claude_managed": anthropic_api, "codex_agents": openai_api}
    return frozenset(
        profile
        for profile in LANE_PROFILES
        if profile == DEFAULT_LANE_PROFILE
        or (api[profile] if profile in api else lanes.get(LANE_OF_PROFILE[profile], False))
    )


def settings_bound_lanes(settings: Settings) -> frozenset[LaneProfileName]:
    """`bound_lane_profiles` from the process settings (the API and the placement check)."""

    return bound_lane_profiles(
        cursor=settings.cursor_api_key is not None,
        claude=settings.mission_control_claude_lane,
        codex=settings.mission_control_codex_lane,
        anthropic_api=settings.anthropic_api_key is not None,
        openai_api=settings.openai_api_key is not None,
    )


def describe_only_registry(
    *,
    bound: Container[str],
    allow_unqualified: bool,
    registrations: Iterable[LaneRegistration] = (),
) -> LaneRegistry:
    """The registry a process that lists lanes but runs none publishes (the public API).

    It mirrors the worker composition: `deep_agents` always (its declared describe), and each
    profile in `bound` (`bound_lane_profiles`, `settings_bound_lanes`) as an unqualified
    describe-only entry. `registrations` are lane packages' `LANE`s bootstrap composed for this
    process; each one whose profile is bound is published with its declared describe in its
    place. An unbound lane stays absent (OC-R3): a
    coordinator is never offered a lane this installation cannot run, and the model listing
    reports it `unbound`.
    """

    profiles = [
        profile for profile in LANE_PROFILES if profile == DEFAULT_LANE_PROFILE or profile in bound
    ]
    return describe_only_lanes(
        published=[
            DECLARED_LANE_MATRICES[profile]
            if profile == DEFAULT_LANE_PROFILE
            else DECLARED_LANE_MATRICES[profile].unqualified()
            for profile in profiles
        ],
        registrations=[item for item in registrations if item.profile in profiles],
        allow_unqualified=allow_unqualified,
    )


__all__ = [
    "SESSION_LANES",
    "bound_lane_profiles",
    "describe_only_registry",
    "settings_bound_lanes",
]
