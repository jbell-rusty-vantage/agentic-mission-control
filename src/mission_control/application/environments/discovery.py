"""Discovery Proof per lane (SPEC-02 section 6, gap G14; MO-34).

Each lane proves that its provider loaded the configuration through one mechanism
(`MECHANISM_OF_PROFILE`); `domain/execution/discovery.py` explains them. This module holds the
lane-neutral half:

* `discovery_expectation`: at prepare, the Mission Control items of the layering receipt that
  the lane's mechanism can name (`REPORTED_KINDS`), plus, for a mechanism that reads files where
  the provider loads them, the digests of the instruction overlay and the hook config as placed
  (the files the Telemetry Hook Pack's `materialization.observed` digests);
* `materialization_signal_report`: the `materialization.observed` signal (MO-41's
  `{"files": {path: digest | null}, "skills": [name]}`) as a report;
* the frame a report travels in (`DISCOVERY_RAW_KIND`), and `DiscoveringLane`, the optional lane
  capability `lane.turn` calls once a new native session exists (read-back mechanisms);
* `proof_gaps`: whether a report proves `discovered` for a recorded preparation.

The ladder rule (`proof_gaps`): discovery follows preparation, except that on a cloud lane with
no mission layer a provider-side report (`PROVIDER_SIDE_MECHANISMS`) is itself the receipt that
the provider's environment holds the configuration, so it lifts `prepared` and `discovered`
together. A cloud lane whose Environment Kit declares a mission layer still waits for that
layer's receipt signal.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final, Protocol, runtime_checkable

from pydantic import ValidationError

from mission_control.application.agentic_components.layering import LayeringReceipt
from mission_control.application.signals.contracts import Signal
from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.capabilities.layouts import LANE_LAYOUTS
from mission_control.domain.execution.discovery import (
    DISCOVERY_REPORT_SCHEMA,
    PROVIDER_SIDE_MECHANISMS,
    DiscoveryExpectation,
    DiscoveryItem,
    DiscoveryKind,
    DiscoveryMechanism,
    DiscoveryReport,
    as_digest,
    discovery_gaps,
)
from mission_control.domain.execution.environment_preparation import (
    EnvironmentPreparation,
    ReadinessLevel,
    readiness_at_least,
)
from mission_control.domain.execution.lanes import PLACEMENT_OF_PROFILE, SessionHandle
from mission_control.domain.frames.contracts import FrameKind, FrameObservation

# The lane-neutral raw kind of a frame whose body is a `mc.discovery_report.v1`.
DISCOVERY_RAW_KIND: Final = "materialization.discovered"
# The Telemetry Hook Pack's first signal (MO-41): what the environment read from its disk.
MATERIALIZATION_SIGNAL: Final = "materialization.observed"

MECHANISM_OF_PROFILE: Final[Mapping[LaneProfile, DiscoveryMechanism]] = {
    LaneProfile.CLAUDE_AGENT_SDK: "session_init",
    LaneProfile.CODEX: "app_server",
    LaneProfile.CURSOR_LOCAL: "setting_readback",
    LaneProfile.CURSOR_CLOUD: "materialization_signal",
    LaneProfile.CLAUDE_CLOUD: "materialization_signal",
    LaneProfile.CLAUDE_MANAGED: "api_readback",
    LaneProfile.CODEX_AGENTS: "api_readback",
}
# What each mechanism names. Claude `system/init` lists skills, agents and MCP servers; Codex
# lists skills and hooks and reads the MCP config; the Cursor read-back and the in-environment
# signal list the skill directory; an agent API returns its skills and MCP servers.
REPORTED_KINDS: Final[Mapping[DiscoveryMechanism, frozenset[DiscoveryKind]]] = {
    "session_init": frozenset({"skill", "subagent", "mcp_server"}),
    "app_server": frozenset({"skill", "hook", "mcp_server"}),
    "setting_readback": frozenset({"skill"}),
    "materialization_signal": frozenset({"skill"}),
    "api_readback": frozenset({"skill", "mcp_server"}),
}
# Mechanisms that read the overlay and hook config where the provider loads them.
FILE_READING_MECHANISMS: Final[frozenset[DiscoveryMechanism]] = frozenset(
    {"setting_readback", "materialization_signal"}
)


def observed_files(lane: LaneProfile) -> tuple[str, ...]:
    """The files a file-reading mechanism digests on `lane`: the instruction overlay (unless it
    travels inline) and the hook config."""

    layout = LANE_LAYOUTS[lane]
    files: list[str] = []
    if layout.layering is not None and not layout.layering.overlay_inline:
        files.append(layout.layering.overlay)
    if layout.hooks_file is not None:
        files.append(layout.hooks_file)
    return tuple(files)


def discovery_expectation(
    lane: LaneProfile | str,
    layering: LayeringReceipt | None,
    placed: Mapping[str, str],
) -> DiscoveryExpectation | None:
    """What `lane`'s mechanism must report of one placement: the mission items of `layering` it
    can name and, for a file-reading mechanism, the digests in `placed` (workspace path to the
    `sha256:` digest of the bytes placed there) of the files it reads. `None` on a lane with no
    discovery mechanism (codex_cloud proves `delivered` only)."""

    profile = LaneProfile(lane)
    mechanism = MECHANISM_OF_PROFILE.get(profile)
    if mechanism is None:
        return None
    kinds = REPORTED_KINDS[mechanism]
    items = (
        ()
        if layering is None
        else tuple(
            dict.fromkeys(
                DiscoveryItem(kind=item.kind, name=item.name)
                for item in layering.discovered("mission")
                if item.kind in kinds
            )
        )
    )
    digests = (
        {path: placed[path] for path in observed_files(profile) if path in placed}
        if mechanism in FILE_READING_MECHANISMS
        else {}
    )
    return DiscoveryExpectation(mechanism=mechanism, items=items, digests=digests)


def materialization_signal_report(
    lane: LaneProfile | str, signal: Signal
) -> DiscoveryReport | None:
    """A `materialization.observed` signal as a report (`None` for any other signal). Its data
    is untrusted: an entry that is not a digest reads as absent and a malformed skill name is
    dropped, so bad data can only fail the proof, never pass it."""

    if signal.type != MATERIALIZATION_SIGNAL:
        return None
    files = signal.data.get("files")
    skills = signal.data.get("skills")
    return DiscoveryReport(
        lane_profile=LaneProfile(lane),
        mechanism="materialization_signal",
        items=tuple(
            DiscoveryItem(kind="skill", name=name)
            for name in (skills if isinstance(skills, list) else ())
            if isinstance(name, str) and 0 < len(name) <= 256
        ),
        digests=(
            {path: as_digest(digest) for path, digest in files.items() if isinstance(path, str)}
            if isinstance(files, Mapping)
            else {}
        ),
        source=f"signal:{signal.signal_id}"[:256],
    )


def discovery_observation(
    report: DiscoveryReport, *, provider_key: str, native_session_ref: str | None
) -> FrameObservation:
    """The frame a report is persisted as (a status frame: it closes nothing)."""

    return FrameObservation(
        provider_key=provider_key[:512],
        raw_kind=DISCOVERY_RAW_KIND,
        kind=FrameKind.STATUS,
        body=report.model_dump(mode="json"),
        native_session_ref=native_session_ref,
    )


def discovery_report_of(raw_kind: str, body: object) -> DiscoveryReport | None:
    """The report a persisted frame carries, if it is a discovery frame."""

    if raw_kind != DISCOVERY_RAW_KIND or not isinstance(body, Mapping):
        return None
    if body.get("schema_version") != DISCOVERY_REPORT_SCHEMA:
        return None
    try:
        return DiscoveryReport.model_validate(body)
    except ValidationError:
        return None


def proof_gaps(preparation: EnvironmentPreparation, report: DiscoveryReport) -> tuple[str, ...]:
    """Why `report` does not raise `preparation` to `discovered` (empty when it does)."""

    if report.lane_profile.value != preparation.lane_profile:
        return (f"the report is about {report.lane_profile.value}, not {preparation.lane_profile}",)
    expectation = preparation.discovery
    if expectation is None:
        return ("the preparation records no discovery expectation",)
    gaps = list(discovery_gaps(expectation, report))
    if not readiness_at_least(preparation.readiness, ReadinessLevel.PREPARED):
        gaps.extend(_preparation_gaps(preparation, report))
    return tuple(gaps)


def _preparation_gaps(preparation: EnvironmentPreparation, report: DiscoveryReport) -> list[str]:
    setup_pin = preparation.declaration.setup_pin
    if (
        PLACEMENT_OF_PROFILE[preparation.lane_profile] != "cloud"
        or preparation.readiness is not ReadinessLevel.DELIVERED
        or report.mechanism not in PROVIDER_SIDE_MECHANISMS
    ):
        return [f"the environment is {preparation.readiness}; discovery follows preparation"]
    if setup_pin is not None:
        return [
            f"prepared: Environment Kit {setup_pin} declares a mission layer whose receipt "
            "signal has not arrived"
        ]
    return []


@runtime_checkable
class DiscoveringLane(Protocol):
    """A Session Lane that reads back what its provider loaded once the native session exists
    (Codex app-server lists, the Cursor SDK read-back, a hosted agent API). Lanes whose session
    reports it in its own stream (Claude `system/init`) emit a discovery frame instead."""

    async def discover(self, session: SessionHandle) -> DiscoveryReport | None: ...


__all__ = [
    "DISCOVERY_RAW_KIND",
    "FILE_READING_MECHANISMS",
    "MATERIALIZATION_SIGNAL",
    "MECHANISM_OF_PROFILE",
    "REPORTED_KINDS",
    "DiscoveringLane",
    "discovery_expectation",
    "discovery_observation",
    "discovery_report_of",
    "materialization_signal_report",
    "observed_files",
    "proof_gaps",
]
