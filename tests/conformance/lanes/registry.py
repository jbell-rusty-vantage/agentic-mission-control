"""Every lane profile the suite runs: one `LaneAdapter` entry per declared profile.

A new lane registers here (and in nothing else the suite reads): the registry test fails while
a profile in `DECLARED_LANE_MATRICES` has no entry, so a lane cannot merge unexercised.
"""

from __future__ import annotations

from typing import Any, Final

import pytest

from mission_control.application.execution.harness.describe import declared_matrix
from tests.conformance.lanes.adapters.agents import CodexAgentsConformance
from tests.conformance.lanes.adapters.claude import ClaudeAgentSdkConformance
from tests.conformance.lanes.adapters.codex import CodexConformance
from tests.conformance.lanes.adapters.cursor import CursorCloudConformance, CursorLocalConformance
from tests.conformance.lanes.adapters.describe_only import DescribeOnlyConformance
from tests.conformance.lanes.adapters.governed import DeepAgentsConformance
from tests.conformance.lanes.adapters.managed import ClaudeManagedConformance
from tests.conformance.lanes.contract import LaneAdapter, Scenario, claims

CONFORMANCE_LANES: Final[tuple[LaneAdapter, ...]] = (
    DeepAgentsConformance(),
    CursorLocalConformance(),
    CursorCloudConformance(),
    ClaudeAgentSdkConformance(),
    CodexConformance(),
    DescribeOnlyConformance("claude_cloud"),
    DescribeOnlyConformance("codex_cloud"),
    ClaudeManagedConformance(),
    CodexAgentsConformance(),
)


def every_lane() -> list[Any]:
    """`pytest.param`s of every registered lane (describe honesty and registry checks)."""

    return [pytest.param(lane, id=lane.profile) for lane in CONFORMANCE_LANES]


def lanes_for(scenario: Scenario) -> list[Any]:
    """`pytest.param`s of the registered lanes that must pass `scenario`: those whose declared
    describe claims it, less the ones declaring an exception for it."""

    return [
        pytest.param(lane, id=lane.profile)
        for lane in CONFORMANCE_LANES
        if claims(declared_matrix(lane.profile), scenario) and scenario not in lane.exceptions
    ]


__all__ = ["CONFORMANCE_LANES", "every_lane", "lanes_for"]
