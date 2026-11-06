"""Manifest-compile checks of a lane's own options block, asked through its registration (OC-R6).

`provider_options.<lane>` is opaque to the core: only the lane knows which of its entries exist
(for Deep Agents, which `(vendor, feature)` model tools its model routes realize). A lane adapter
that can say so at compile implements the optional protocol `ChecksLaneOptions`; the manifest
compile asks `LaneOptionsChecks.check(lane, options)` and turns each finding into a blocker at the
authored pointer. The core names no vendor and no feature: a lane without the protocol, or a lane
with no registration in this process, is checked at launch by its own compile, as before.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Protocol, runtime_checkable

from mission_control.application.resolution.ports import LaneRegistration

# (pointer relative to `provider_options/<lane>`, message)
LaneOptionsIssue = tuple[str, str]


@runtime_checkable
class ChecksLaneOptions(Protocol):
    """Optional capability of a lane adapter: validate its options block without compiling."""

    def check_options(self, options: Mapping[str, Any]) -> tuple[LaneOptionsIssue, ...]: ...


class LaneOptionsChecks:
    """The options checks of the registered lanes that offer one, keyed by lane profile."""

    def __init__(self, registrations: Iterable[LaneRegistration] = ()) -> None:
        self._checks: dict[str, ChecksLaneOptions] = {
            registration.profile: registration.adapter
            for registration in registrations
            if isinstance(registration.adapter, ChecksLaneOptions)
        }

    def profiles(self) -> tuple[str, ...]:
        return tuple(sorted(self._checks))

    def check(self, lane_profile: str, options: Mapping[str, Any]) -> tuple[LaneOptionsIssue, ...]:
        checker = self._checks.get(lane_profile)
        return () if checker is None else checker.check_options(options)


__all__ = ["ChecksLaneOptions", "LaneOptionsChecks", "LaneOptionsIssue"]
