"""Compile-time subagent discriminator: one profile, every lane it may run on, a verdict each.

Mission Control's subagent contract (``mc.subagent_profile.v1``) is lane-neutral; nine lanes
materialize it differently. This module is the **discriminator** of PROCESS §2 for subagents:
given one ``agents:`` entry, the catalog profile it resolved to, the manifest overlay and the
lanes the selecting node may run on, it

1. reads the fields the profile asks for (:meth:`SubagentProfile.requested_fields`) against
   each lane's declared support (:mod:`application.authoring.subagent_support`) and turns every
   non-native cell into a pointed manifest issue: a **blocker** when the lane cannot honour a
   field the mission named (a kind, a child shape, a seed, a named tool, Skill, MCP server or
   gate, a placement), a **warning** when the lane degrades it or when the loss is one the
   child still runs correctly without (the lane adapter then records it ``degraded`` in the
   receipt at launch);
2. refuses ``provider_overrides`` keyed by a lane the node does not run on
   (``subagent_override_lane_mismatch``), the same rule as ``provider_options``;
3. expands the profile's ``seeds`` into capability requests of their own, pointed under the
   entry (``.../seeds/<group>/<index>``) and tagged ``subagent_seed_of``, so the compiler
   resolves and pins them exactly like the parent's capabilities and the launch resolver
   routes them to the child instead of the parent.

Pure: no catalog access, no I/O. The compiler calls it from its resolution loop once the
profile row is known and queues the seeds it returns.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final

from mission_control.domain.authoring.manifest import (
    CapabilityKind,
    ManifestErrorCode,
    ManifestIssue,
)
from mission_control.domain.authoring.mission_definition import (
    CapabilityPin as DefinitionPin,
)
from mission_control.domain.authoring.mission_definition import DefinitionCapability
from mission_control.domain.capabilities.subagent_overrides import (
    subagent_overrides_lane_mismatch,
)
from mission_control.domain.capabilities.subagents import SeedGroup, SubagentProfile
from mission_control.domain.execution.lanes import SubagentFieldVerdict

SEED_OF_ATTRIBUTE: Final = "subagent_seed_of"
SEED_GROUP_ATTRIBUTE: Final = "seed_group"
SEED_LANES_ATTRIBUTE: Final = "lanes"

# Fields the mission names explicitly; a lane that cannot honour one refuses the profile
# rather than running a different child (PROCESS §2.2 rule 4). Everything else degrades
# with a reason in the lane's receipt.
_REFUSED_WHEN_UNSUPPORTED: Final[frozenset[str]] = frozenset(
    {
        "kind.sync",
        "kind.async",
        "kind.linked_run",
        "capabilities.inherit",
        "capabilities.seeded",
        "seeds.skills",
        "seeds.mcp_servers",
        "seeds.plugins",
        "seeds.tools",
        "tools",
        "skills",
        "mcp_servers",
        "interrupt_on",
        "placement.in_process",
        "placement.agent_server",
        "placement.lane",
    }
)
# How a seed group enters the compiler's capability queue: the role the launch resolver
# switches on and the catalog kind the pin must resolve to.
_SEED_REQUEST: Final[Mapping[SeedGroup, tuple[str, CapabilityKind]]] = {
    "skills": ("skill", CapabilityKind.SKILL_BUNDLE),
    "mcp_servers": ("capability", CapabilityKind.MCP_SERVER),
    "tools": ("capability", CapabilityKind.DETERMINISTIC_EXECUTOR),
    "plugins": ("plugin", CapabilityKind.PLUGIN),
}

SupportLookup = Callable[[str], Mapping[str, SubagentFieldVerdict]]


@dataclass(frozen=True)
class SubagentFieldReading:
    """One lane's verdict on one field the profile asked for."""

    lane: str
    field: str
    verdict: SubagentFieldVerdict


@dataclass(frozen=True)
class SubagentDiscrimination:
    pointer: str
    name: str
    lanes: tuple[str, ...]
    requested: tuple[str, ...]
    readings: tuple[SubagentFieldReading, ...]
    seeds: tuple[DefinitionCapability, ...]
    blockers: tuple[ManifestIssue, ...]
    warnings: tuple[ManifestIssue, ...]

    @property
    def refused(self) -> bool:
        return bool(self.blockers)


def is_subagent_seed(capability: DefinitionCapability) -> bool:
    """A capability request the discriminator added for a child (never the parent's)."""

    return SEED_OF_ATTRIBUTE in capability.attributes


def seed_owner(capability: DefinitionCapability) -> str | None:
    owner = capability.attributes.get(SEED_OF_ATTRIBUTE)
    return str(owner) if owner is not None else None


def discriminate_subagent(
    *,
    capability: DefinitionCapability,
    profile: SubagentProfile,
    lanes: tuple[str, ...],
    support: SupportLookup,
) -> SubagentDiscrimination:
    """Classify one selected profile for every lane the selecting node may run on."""

    overlay = capability.attributes.get("overlay")
    requested = profile.requested_fields(overlay if isinstance(overlay, Mapping) else None)
    readings: list[SubagentFieldReading] = []
    blockers: list[ManifestIssue] = []
    warnings: list[ManifestIssue] = []
    label = f"subagent {profile.name}"
    for lane in lanes:
        row = support(lane)
        for field in requested:
            verdict = row[field]
            readings.append(SubagentFieldReading(lane=lane, field=field, verdict=verdict))
            if verdict == "native":
                continue
            pointer = _field_pointer(capability.pointer, field)
            if verdict == "unsupported" and field in _REFUSED_WHEN_UNSUPPORTED:
                blockers.append(
                    _issue(
                        pointer,
                        f"{label}: lane {lane} does not support {field}; the lane's "
                        "subagents.fields matrix (lane describe) lists what it honours",
                        "subagent_field_unsupported",
                    )
                )
            elif verdict == "unsupported":
                warnings.append(
                    _issue(
                        pointer,
                        f"{label}: lane {lane} does not materialize {field}; the child runs "
                        "without it and the lane's receipt records the loss",
                        "subagent_field_unsupported",
                    )
                )
            else:
                warnings.append(
                    _issue(
                        pointer,
                        f"{label}: lane {lane} degrades {field}; the lane adapter records "
                        "the exact loss in its materialization receipt at launch",
                        "subagent_field_degraded",
                    )
                )
    for lane in subagent_overrides_lane_mismatch(profile.provider_overrides, lanes=lanes):
        blockers.append(
            _issue(
                f"{capability.pointer}/provider_overrides/{lane}",
                f"{label}: provider_overrides name lane {lane}, which this node does not run "
                f"on (lanes: {list(lanes)})",
                "subagent_override_lane_mismatch",
            )
        )
    return SubagentDiscrimination(
        pointer=capability.pointer,
        name=profile.name,
        lanes=lanes,
        requested=requested,
        readings=tuple(readings),
        seeds=_seed_requests(capability, profile, lanes),
        blockers=tuple(blockers),
        warnings=tuple(warnings),
    )


def _seed_requests(
    capability: DefinitionCapability, profile: SubagentProfile, lanes: tuple[str, ...]
) -> tuple[DefinitionCapability, ...]:
    if profile.seeds is None:
        return ()
    requests: list[DefinitionCapability] = []
    counters: dict[str, int] = {}
    for group, pin in profile.seeds.items():
        index = counters.get(group, 0)
        counters[group] = index + 1
        role, kind = _SEED_REQUEST[group]
        requests.append(
            DefinitionCapability(
                pointer=f"{capability.pointer}/seeds/{group}/{index}",
                role=role,
                alias=None,
                kind=kind,
                pin=DefinitionPin(
                    capability_id=pin.capability_id, version=pin.version, digest=pin.digest
                ),
                attributes={
                    "provenance": f"subagent:{profile.name}",
                    SEED_OF_ATTRIBUTE: profile.name,
                    SEED_GROUP_ATTRIBUTE: group,
                    SEED_LANES_ATTRIBUTE: list(lanes),
                },
            )
        )
    return tuple(requests)


def _field_pointer(pointer: str, field: str) -> str:
    head = field.split(".", 1)[0]
    return f"{pointer}/{head}"


def _issue(pointer: str, message: str, reason: str) -> ManifestIssue:
    return ManifestIssue(
        code=ManifestErrorCode.CAPABILITY_UNAVAILABLE,
        pointer=pointer,
        message=message,
        reason=reason,
    )


__all__ = [
    "SEED_GROUP_ATTRIBUTE",
    "SEED_LANES_ATTRIBUTE",
    "SEED_OF_ATTRIBUTE",
    "SubagentDiscrimination",
    "SubagentFieldReading",
    "SupportLookup",
    "discriminate_subagent",
    "is_subagent_seed",
    "seed_owner",
]
