"""`mc.discovery_report.v1`: proof that a provider loaded what Mission Control placed
(materialization-observation SPEC-02 section 6, gap G14; MO-34).

A written file proves delivery, never loading. A Discovery Proof is gathered by mechanism, never
by asking the model:

* `session_init`: the session's own init report (Claude `system/init`: skills, agents, MCP
  servers and their status);
* `app_server`: the Codex app-server's `skills/list`, `hooks/list` and `config/read` after
  `thread/start`;
* `setting_readback`: the Cursor SDK's read-back of the local agent (its project setting source
  is the leased workspace) and the files the project source loads there;
* `materialization_signal`: the Telemetry Hook Pack's first signal from inside the provider's
  environment (`materialization.observed`: file digests as read there and the skill listing);
* `api_readback`: a hosted agent API's read-back of the agent and environment it will run.

Prepare records a `DiscoveryExpectation` (the Mission Control items the lane's mechanism can
report, and the digests of files it reads) on the environment preparation; a report proves
`discovered` only when it names every expected item and reads every expected digest. Reports are
evidence, never authority: the comparison happens against the recorded expectation, so a report
that lists more (repository, user or ambient cognition) still proves the mission's items, and a
report that lists less never does.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from mission_control.domain.authoring.canonical import stable_json_digest
from mission_control.domain.capabilities.host_support import LaneProfile

DISCOVERY_REPORT_SCHEMA: Final = "mc.discovery_report.v1"
_DIGEST: Final = r"^sha256:[0-9a-f]{64}$"
Digest = Annotated[str, Field(pattern=_DIGEST)]

DiscoveryKind = Literal["instructions", "rule", "skill", "subagent", "hook", "mcp_server"]
DiscoveryMechanism = Literal[
    "session_init",
    "app_server",
    "setting_readback",
    "materialization_signal",
    "api_readback",
]
# Mechanisms that read the configuration where the provider runs it (inside its environment,
# or from its agent registry) rather than from the worker's own disk.
PROVIDER_SIDE_MECHANISMS: Final[frozenset[DiscoveryMechanism]] = frozenset(
    {"materialization_signal", "api_readback"}
)


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DiscoveryItem(_Contract):
    """One piece of cognition by kind and native name (a skill directory, a subagent, a hook
    event, an MCP server)."""

    kind: DiscoveryKind
    name: str = Field(min_length=1, max_length=256)

    def label(self) -> str:
        return f"{self.kind} {self.name}"


class DiscoveryExpectation(_Contract):
    """What `mechanism` must report for the environment to be `discovered`: the Mission Control
    items it can name and the digests (`sha256:<hex>`) of what it reads, keyed by workspace path
    or, on an API read-back, by resource (`agent`)."""

    mechanism: DiscoveryMechanism
    items: tuple[DiscoveryItem, ...] = ()
    digests: dict[str, Digest] = Field(default_factory=dict)


class DiscoveryReport(_Contract):
    """`mc.discovery_report.v1`: what one mechanism observed the provider load.

    `items` may name more than Mission Control placed (repository, user, bundled or ambient
    cognition); `digests` hold what was read, `None` where the file was absent."""

    schema_version: Literal["mc.discovery_report.v1"] = DISCOVERY_REPORT_SCHEMA
    lane_profile: LaneProfile
    mechanism: DiscoveryMechanism
    items: tuple[DiscoveryItem, ...] = ()
    digests: dict[str, Digest | None] = Field(default_factory=dict)
    source: str = Field(min_length=1, max_length=256)

    @property
    def digest(self) -> str:
        return stable_json_digest(self)


def as_digest(value: object) -> str | None:
    """`value` when it is a `sha256:<hex>` digest; anything else a provider or an environment
    reports reads as absent."""

    return value if isinstance(value, str) and re.fullmatch(_DIGEST, value) else None


def discovery_gaps(expectation: DiscoveryExpectation, report: DiscoveryReport) -> tuple[str, ...]:
    """What `report` fails to prove of `expectation` (empty when it proves all of it)."""

    if report.mechanism != expectation.mechanism:
        return (f"the lane discovers through {expectation.mechanism}, not {report.mechanism}",)
    reported = set(report.items)
    gaps = [
        f"{item.label()} was not reported loaded"
        for item in expectation.items
        if item not in reported
    ]
    gaps.extend(
        _digest_gap(key, expected, report.digests)
        for key, expected in sorted(expectation.digests.items())
        if report.digests.get(key) != expected
    )
    return tuple(gaps)


def _digest_gap(key: str, expected: str, observed: Mapping[str, str | None]) -> str:
    if key not in observed:
        return f"{key} was not read"
    if observed[key] is None:
        return f"{key} is absent where the provider reads it"
    return f"{key} reads {observed[key]}, not the placed {expected}"


__all__ = [
    "DISCOVERY_REPORT_SCHEMA",
    "PROVIDER_SIDE_MECHANISMS",
    "DiscoveryExpectation",
    "DiscoveryItem",
    "DiscoveryKind",
    "DiscoveryMechanism",
    "DiscoveryReport",
    "as_digest",
    "discovery_gaps",
]
