"""Every recorded workflow history replays against today's workflow code.

Two sets of recordings replay here, each through the production workflow set:

- `histories/temporalio_1_30/` holds executions captured by running the Temporal
  integration suite of base `e19f376` (pre-upgrade code) on `temporalio==1.30.0`: a
  StageGraph root, family and operation and a GoalDirected family (after Continue-As-New)
  and operations, all started under the `required` Search Attribute policy; an operation
  started directly under `required`; the RRM-008 operation cancellation sagas; and a linked
  run (parent, observer and child root).
- `tests/fixtures/histories/<directory>/` holds the captures made before or after a
  `workflow.patched` change. Each directory declares, in `DIRECTORY_MARKERS`, which patch
  markers its histories must (or must not) carry and which recorded commands prove the path
  they took. A new directory fails `test_every_history_directory_declares_its_markers` until
  it declares them, so every directory stays proven to replay with its markers.

None of the recordings carries the `ft-g7-mc-visibility` marker, so replaying them proves the
SDK upgrade and the FT-G7 visibility writes keep the recorded command sequences.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from temporalio.client import WorkflowHistory
from temporalio.worker import Replayer

from mission_control.adapters.temporal.linked_run_workflow import (
    LinkedRunObserverWorkflow,
    LinkedRunWorkflow,
)
from mission_control.adapters.temporal.search_attributes import MC_VISIBILITY_PATCH
from mission_control.adapters.temporal.workflow_sandbox import coordinator_workflow_runner
from mission_control.adapters.temporal.workflows.belllabs_run import BellLabsRunWorkflow
from mission_control.adapters.temporal.workflows.goal_directed import (
    JOURNALED_SETTLEMENT_PATCH,
    STALE_VERSION_RETRY_PATCH,
    VERIFIED_TERMINAL_OUTPUTS_PATCH,
    GoalDirectedWorkflow,
)
from mission_control.adapters.temporal.workflows.operation import OperationWorkflow
from mission_control.adapters.temporal.workflows.stagegraph import (
    EXHAUSTION_HOLD_PATCH,
    REVISIT_REGION_PATCH,
    SETTLE_BASELINE_PATCH,
    StageGraphWorkflow,
)
from tests.support.temporal import FixtureChildWorkflow, patch_ids, scheduled_activity_inputs

UPGRADE = Path(__file__).resolve().parent / "histories" / "temporalio_1_30"
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "histories"
PRODUCTION_WORKFLOWS = [
    BellLabsRunWorkflow,
    StageGraphWorkflow,
    GoalDirectedWorkflow,
    OperationWorkflow,
    LinkedRunWorkflow,
    LinkedRunObserverWorkflow,
]


def _cases() -> list[Path]:
    return sorted([*UPGRADE.glob("*.json"), *FIXTURES.glob("*/*.json")])


def _fixture_cases() -> list[Path]:
    return sorted(FIXTURES.glob("*/*.json"))


def _case_id(path: Path) -> str:
    return f"{path.parent.name}/{path.stem}"


def _history(path: Path) -> WorkflowHistory:
    return WorkflowHistory.from_json(path.stem, path.read_text("utf-8"))


def _workflow_type(history: WorkflowHistory) -> str:
    started = history.events[0].workflow_execution_started_event_attributes
    return started.workflow_type.name


def _lifecycle_command_ids(history: WorkflowHistory) -> list[str]:
    return [
        str(item["command_id"])
        for item in scheduled_activity_inputs(history, "goaldirected.apply_lifecycle_command")
    ]


def _admission_attempts(history: WorkflowHistory) -> list[tuple[str, int, int]]:
    return sorted(
        (str(item["operation_role"]), int(item["goal_iteration"]), int(item["admission_attempt"]))
        for name in ("goaldirected.prepare_executor", "goaldirected.prepare_verifier")
        for item in scheduled_activity_inputs(history, name)
    )


# --- Per-directory markers -------------------------------------------------------------------


def _rrm007_pre_change(path: Path, history: WorkflowHistory) -> None:
    """Captured on base `d46f548`, before RRM-007's governed waits, declared waits, quiescence
    and durable goal pause: no `rrm-0*` patch is recorded, so the markers keep every
    pre-RRM-007 command sequence intact."""

    assert len(history.events) > 10
    assert not any(patch.startswith("rrm-0") for patch in patch_ids(history)), "pre-change"
    if path.name == "goal_directed_two_iterations.run1.json":
        # Before RRM-016 the family recorded its own usage: executor and verifier of two
        # iterations.
        assert JOURNALED_SETTLEMENT_PATCH not in patch_ids(history)
        usage = [item for item in _lifecycle_command_ids(history) if item.startswith("goal:usage:")]
        assert len(usage) == 4


def _rrm016_post_change(path: Path, history: WorkflowHistory) -> None:
    """Captured from the RRM-016 journaled GoalDirected family
    (`test_rrm_016_goal_directed_journaled`, `RRM016_CAPTURE_HISTORY_DIR`)."""

    assert JOURNALED_SETTLEMENT_PATCH in patch_ids(history)
    if path.name == "goal_directed_journaled_pause_resume.run1.json":
        # Pause, resume and four journaled settlements: the family records only the baseline.
        usage = [item for item in _lifecycle_command_ids(history) if item.startswith("goal:usage:")]
        assert usage == ["goal:usage:baseline"]
        assert [
            item["operation_role"]
            for name in ("goaldirected.prepare_executor", "goaldirected.prepare_verifier")
            for item in scheduled_activity_inputs(history, name)
        ] == ["executor", "executor", "verifier", "verifier"]
    elif path.name == "goal_directed_stale_version_retry.run1.json":
        # Two re-admissions after an outside command made the read version stale.
        assert STALE_VERSION_RETRY_PATCH in patch_ids(history)
        assert [item[2] for item in _admission_attempts(history)].count(2) == 2
    else:
        pytest.fail(f"undeclared RRM-016 history {path.name}")


def _rrm019_post_change(path: Path, history: WorkflowHistory) -> None:
    """Captured from RRM-019 (`RRM019_CAPTURE_HISTORY_DIR`): two iterations with distinct
    output refs; only the verified final output is promoted."""

    assert path.name == "goal_directed_distinct_output_refs.run1.json"
    assert VERIFIED_TERMINAL_OUTPUTS_PATCH in patch_ids(history)
    assert [
        item.split(":")[2:5]
        for item in _lifecycle_command_ids(history)
        if item.startswith("goal:output:")
    ] == [["artifact", "rrm016", "2"]]


def _rrm021_pre_change(path: Path, history: WorkflowHistory) -> None:
    """Captured on base `0d0c184`, before RRM-021, with a non-empty baseline: the
    `stagegraph.settle_baseline` activity is never issued on replay."""

    assert len(history.events) > 10
    assert SETTLE_BASELINE_PATCH not in patch_ids(history), "pre-change"
    assert scheduled_activity_inputs(history, "stagegraph.settle_baseline") == []
    started = scheduled_activity_inputs(history, "stagegraph.initialize")[0]
    assert started["request_scope"], "the captured family input carries its run binding"


DIRECTORY_MARKERS: dict[str, Callable[[Path, WorkflowHistory], None]] = {
    "rrm007_pre_change": _rrm007_pre_change,
    "rrm016_post_change": _rrm016_post_change,
    "rrm019_post_change": _rrm019_post_change,
    "rrm021_pre_change": _rrm021_pre_change,
}


# --- Tests -----------------------------------------------------------------------------------


def test_the_upgrade_capture_covers_every_family() -> None:
    types = {_workflow_type(_history(path)) for path in UPGRADE.glob("*.json")}
    assert types == {
        "belllabs.run.v1",
        "belllabs.stagegraph",
        "belllabs.goal-directed",
        "belllabs.operation.v2",
        "belllabs.linked-run",
        "belllabs.linked-run-observer",
    }


def test_every_history_directory_declares_its_markers() -> None:
    directories = {path.name for path in FIXTURES.iterdir() if path.is_dir()}
    assert directories == set(DIRECTORY_MARKERS)
    for name in directories:
        assert list((FIXTURES / name).glob("*.json")), f"{name} has no recorded history"


@pytest.mark.parametrize("path", _fixture_cases(), ids=_case_id)
def test_recorded_history_carries_its_directory_markers(path: Path) -> None:
    DIRECTORY_MARKERS[path.parent.name](path, _history(path))


@pytest.mark.parametrize(
    "path", [path for path in _fixture_cases() if path.name.startswith("stagegraph_")], ids=_case_id
)
def test_a_pre_wi08_stagegraph_history_has_no_route_semantics(path: Path) -> None:
    """OVE-171: every recorded StageGraph history predates routes, release groups and Revisit
    Regions, so the two WI-08 patches are never reached on replay."""

    history = _history(path)
    assert {REVISIT_REGION_PATCH, EXHAUSTION_HOLD_PATCH}.isdisjoint(patch_ids(history))
    for request in scheduled_activity_inputs(history, "stagegraph.admit_operation"):
        blueprint = request["blueprint"]
        assert "graph_semantics" not in blueprint and not blueprint.get("routes")
        assert not blueprint.get("revisit_regions")


def test_every_recorded_stagegraph_history_is_covered() -> None:
    assert len([path for path in _fixture_cases() if path.name.startswith("stagegraph_")]) >= 5


@pytest.mark.asyncio
@pytest.mark.parametrize("path", _cases(), ids=_case_id)
async def test_recorded_history_replays_against_the_current_workflows(path: Path) -> None:
    history = _history(path)
    assert MC_VISIBILITY_PATCH not in patch_ids(history), "captured before FT-G7"
    if path.name.startswith("linked_run_") and _workflow_type(history) == "belllabs.run.v1":
        # The linked-run test's child root is a fixture workflow, not the production root.
        replayer = Replayer(workflows=[FixtureChildWorkflow])
    else:
        replayer = Replayer(
            workflows=PRODUCTION_WORKFLOWS, workflow_runner=coordinator_workflow_runner()
        )
    await replayer.replay_workflow(history)
