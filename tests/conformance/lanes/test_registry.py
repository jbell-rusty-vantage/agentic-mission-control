"""Every declared lane profile is registered once, and every claimed scenario either runs or
carries a declared exception that cites existing evidence."""

from __future__ import annotations

import pytest

from mission_control.application.execution.harness.describe import (
    DECLARED_LANE_MATRICES,
    declared_matrix,
)
from tests.conformance.lanes.contract import (
    CLAIMS,
    SCENARIO_HOOKS,
    LaneAdapter,
    Scenario,
    claims,
    overrides,
)
from tests.conformance.lanes.records import ROOT
from tests.conformance.lanes.registry import CONFORMANCE_LANES, every_lane

LANES = every_lane()


def test_every_declared_profile_is_registered_exactly_once() -> None:
    registered = [lane.profile for lane in CONFORMANCE_LANES]
    assert sorted(registered) == sorted(DECLARED_LANE_MATRICES), (
        "register the lane in tests/conformance/lanes/registry.py (README.md there)"
    )


def test_every_scenario_states_the_cells_that_claim_it() -> None:
    assert set(CLAIMS) == set(Scenario) == set(SCENARIO_HOOKS)
    for describe in DECLARED_LANE_MATRICES.values():
        assert claims(describe, Scenario.DESCRIBE_HONESTY)


@pytest.mark.parametrize("lane", LANES)
def test_every_claimed_scenario_has_its_adapter_hooks(lane: LaneAdapter) -> None:
    describe = declared_matrix(lane.profile)
    missing = sorted(
        f"{scenario}: {hook}"
        for scenario in Scenario
        if claims(describe, scenario) and scenario not in lane.exceptions
        for hook in SCENARIO_HOOKS[scenario]
        if not overrides(lane, hook)
    )
    assert not missing, f"{lane.profile} claims scenarios its adapter cannot drive: {missing}"


@pytest.mark.parametrize("lane", LANES)
def test_declared_exceptions_are_claimed_reasoned_and_evidenced(lane: LaneAdapter) -> None:
    describe = declared_matrix(lane.profile)
    for scenario, exception in lane.exceptions.items():
        assert scenario is not Scenario.DESCRIBE_HONESTY, "describe honesty has no exception"
        assert claims(describe, scenario), f"{scenario} is not claimed: drop the exception"
        assert exception.reason.strip() and exception.evidence, scenario
        missing = [path for path in exception.evidence if not (ROOT / path).is_file()]
        assert not missing, f"{lane.profile} {scenario} cites missing evidence {missing}"
