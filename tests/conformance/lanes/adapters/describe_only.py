"""Profiles with a declared describe and no adapter yet (the provider-hosted stubs).

A worker publishes such a profile as a `DescribeOnlyLane`: every harness operation raises
`HarnessUnsupported`. Its describe must therefore claim no scenario, which describe honesty
and the registry test hold it to; a profile whose adapter lands replaces this entry with its
own `LaneAdapter`.
"""

from __future__ import annotations

from pathlib import Path

from mission_control.application.execution.harness.describe import declared_matrix
from mission_control.application.execution.harness.protocol import AgentHarness
from mission_control.application.resolution.registries import DescribeOnlyLane
from mission_control.domain.execution.lanes import LaneProfileName
from tests.conformance.lanes.contract import LaneAdapter


class DescribeOnlyConformance(LaneAdapter):
    def __init__(self, profile: LaneProfileName) -> None:
        self.profile = profile

    def harness(self, tmp_path: Path) -> AgentHarness:
        return DescribeOnlyLane(declared_matrix(self.profile))


__all__ = ["DescribeOnlyConformance"]
