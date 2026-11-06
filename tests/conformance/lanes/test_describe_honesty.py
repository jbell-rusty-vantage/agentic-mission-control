"""Describe honesty for every lane profile (SPEC-06 section 3; generalised from FT-G6).

Each registered harness reports exactly its declared matrix, implements every operation it
calls `native` or `emulated` and refuses every other one with `HarnessUnsupported`; its delivery
cells agree with the frozen tables the workflow reads; an `unsupported` command is refused at
admission rather than degraded; pause, hooks, continuation delivery and feature evidence say
what the lane does; and `qualified` flips only with a recorded live drill.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

import pytest

from mission_control.application.execution.harness.controls import pause_decision
from mission_control.application.execution.harness.describe import declared_matrix
from mission_control.application.execution.harness.protocol import (
    HarnessUnsupported,
    implements,
)
from mission_control.contracts.contracts import MissionCommandRequest
from mission_control.domain.capabilities.hooks import native_hook
from mission_control.domain.context.checkpoint import continuation_delivery
from mission_control.domain.execution.lane_requirements import (
    REQUIREMENT_UNSUPPORTED,
    RequirementSet,
    admit_requirements,
)
from mission_control.domain.execution.lane_turns import (
    LANE_COMMAND_SEMANTICS,
    LANE_PAUSE_SEMANTICS,
    LANE_RESUME_SEMANTICS,
    UNSUPPORTED_CONTROL,
)
from mission_control.domain.execution.lanes import HARNESS_OPERATIONS
from tests.conformance.lanes.contract import LaneAdapter, Scenario
from tests.conformance.lanes.records import BASELINE_QUALIFICATIONS, ROOT, live_drills
from tests.conformance.lanes.registry import every_lane, lanes_for

LANES = every_lane()
# Evidence references that name a repository file (the rest cite provider sources in prose).
_REPOSITORY_REFS = ("tests/", "docs/", "scripts/", "src/")


@pytest.mark.parametrize("lane", LANES)
def test_the_registered_harness_describes_its_declared_matrix(
    lane: LaneAdapter, tmp_path: Path
) -> None:
    assert lane.harness(tmp_path).describe() == declared_matrix(lane.profile)


@pytest.mark.parametrize("lane", LANES)
async def test_operations_are_implemented_exactly_where_declared(
    lane: LaneAdapter, tmp_path: Path
) -> None:
    harness = lane.harness(tmp_path)
    describe = harness.describe()
    for operation in HARNESS_OPERATIONS:
        support = describe.control(operation)
        if support in {"native", "emulated"}:
            assert implements(harness, operation), f"{lane.profile}.{operation} is a stub"
            continue
        assert not implements(harness, operation), f"{lane.profile}.{operation} is undeclared"
        with pytest.raises(HarnessUnsupported) as refused:
            result: Any = getattr(harness, operation)(None)
            if inspect.isawaitable(result):
                await result
        assert (refused.value.operation, refused.value.reason) == (operation, support)
    # `pause` and `fork` are run-level controls, never harness operations a lane pretends to.
    assert not hasattr(harness, "pause") and not hasattr(harness, "fork")


@pytest.mark.parametrize("lane", LANES)
def test_delivery_cells_are_the_frozen_tables_the_workflow_reads(lane: LaneAdapter) -> None:
    describe = declared_matrix(lane.profile)
    delivery = describe.delivery_semantics
    for command, table in LANE_COMMAND_SEMANTICS.items():
        assert table[lane.profile] == delivery[command], command
    assert LANE_PAUSE_SEMANTICS[lane.profile] == delivery["pause"]
    assert LANE_RESUME_SEMANTICS[lane.profile] == delivery["resume"]
    assert delivery["hard_pause"] == "unsupported", "no surface accepts hard_pause"


def test_hard_pause_is_not_a_command_any_surface_accepts() -> None:
    assert "hard_pause" not in json.dumps(MissionCommandRequest.model_json_schema())


@pytest.mark.parametrize("lane", LANES)
def test_an_unsupported_command_is_refused_at_admission(lane: LaneAdapter) -> None:
    describe = declared_matrix(lane.profile)
    for command, semantics in describe.delivery_semantics.items():
        if semantics != "unsupported":
            continue
        issues = admit_requirements(describe, RequirementSet(controls=(command,)))
        assert [issue.code for issue in issues] == [REQUIREMENT_UNSUPPORTED], command


@pytest.mark.parametrize("lane", LANES)
def test_pause_mid_run_is_refused_unless_the_lane_pauses_mid_run(lane: LaneAdapter) -> None:
    """Mid-run pause needs an implemented `pause` control and a delivery other than
    `unsupported`; otherwise it is a typed rejection and applies at the run boundary only."""

    describe = declared_matrix(lane.profile)
    declared = describe.delivery_semantics["pause"]
    mid_run = pause_decision(describe, turn_in_flight=True)
    if describe.implemented("pause") and declared != "unsupported":
        assert mid_run.accepted and mid_run.delivery_semantics == declared
        return
    assert not mid_run.accepted and mid_run.reason_code == UNSUPPORTED_CONTROL
    boundary = pause_decision(describe, turn_in_flight=False)
    assert boundary.accepted and boundary.delivery_semantics == "turn_boundary_guaranteed"


@pytest.mark.parametrize("lane", LANES)
def test_declared_hook_events_map_to_native_hooks(lane: LaneAdapter) -> None:
    describe = declared_matrix(lane.profile)
    unmapped = [
        event
        for event in describe.hooks.events_supported
        if native_hook(lane.profile, event) is None
    ]
    assert not unmapped, f"{lane.profile} declares hook events it has no native hook for"


@pytest.mark.parametrize("lane", lanes_for(Scenario.CONTINUATION_HANDOVER))
def test_a_claimed_continuation_is_delivered_like_a_queued_instruction(
    lane: LaneAdapter,
) -> None:
    describe = declared_matrix(lane.profile)
    assert continuation_delivery(lane.profile) == describe.delivery_semantics["queue_instruction"]


@pytest.mark.parametrize("lane", LANES)
def test_feature_evidence_backs_every_implemented_cell(lane: LaneAdapter) -> None:
    describe = declared_matrix(lane.profile)
    for name, evidence in describe.features.items():
        if evidence.status in {"native", "emulated"}:
            assert evidence.implemented, f"{lane.profile}.{name} claims an unimplemented cell"
        reference = (evidence.evidence_ref or "").split("::")[0].split(" ")[0]
        if reference.startswith(_REPOSITORY_REFS):
            assert (ROOT / reference).exists(), f"{lane.profile}.{name} cites {reference}"


@pytest.mark.parametrize("lane", LANES)
def test_qualified_flips_only_with_a_recorded_live_drill(lane: LaneAdapter) -> None:
    describe = declared_matrix(lane.profile)
    if not describe.qualified:
        return
    baseline = BASELINE_QUALIFICATIONS.get(lane.profile)
    assert live_drills(lane.profile) or (baseline and (ROOT / baseline).is_file()), (
        f"{lane.profile} is qualified without a recorded live drill"
    )
