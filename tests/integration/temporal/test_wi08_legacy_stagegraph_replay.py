"""OVE-171 replay compatibility: Stage Graph histories recorded before WI-08 replay unchanged.

Every StageGraph history under `tests/fixtures/histories/` was captured before routes, release
groups and Revisit Regions existed. Their blueprints carry no `graph_semantics` marker, routes or
region, so the new interpreter keeps the earlier release semantics and the two WI-08 patches
(`oc-wi08-stagegraph-revisit-region`, `oc-wi08-stagegraph-exhaustion-hold`) are never reached:
replaying them against the current workflow proves the recorded command sequences are intact.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from temporalio.client import WorkflowHistory
from temporalio.worker import Replayer

from mission_control.adapters.temporal.workflow_sandbox import coordinator_workflow_runner
from mission_control.adapters.temporal.workflows.operation import OperationWorkflow
from mission_control.adapters.temporal.workflows.stagegraph import (
    EXHAUSTION_HOLD_PATCH,
    REVISIT_REGION_PATCH,
    StageGraphWorkflow,
)
from tests.fixtures.temporal_history import patch_ids, scheduled_activity_inputs

HISTORIES = Path(__file__).resolve().parents[2] / "fixtures" / "histories"
CASES = sorted(HISTORIES.glob("*/stagegraph_*.json"))


def _history(path: Path) -> WorkflowHistory:
    return WorkflowHistory.from_json(_workflow_id(path), path.read_text("utf-8"))


def _workflow_id(path: Path) -> str:
    document = json.loads(path.read_text("utf-8"))
    for event in document["events"]:
        attributes = event.get("workflowExecutionStartedEventAttributes")
        if attributes is not None:
            return str(attributes.get("workflowId") or f"family/{path.stem}/1")
    return f"family/{path.stem}/1"


@pytest.mark.asyncio
@pytest.mark.parametrize("path", CASES, ids=[f"{p.parent.name}/{p.name}" for p in CASES])
async def test_a_pre_wi08_stagegraph_history_replays_against_the_new_code(path: Path) -> None:
    history = _history(path)
    assert {REVISIT_REGION_PATCH, EXHAUSTION_HOLD_PATCH}.isdisjoint(patch_ids(history))
    for request in scheduled_activity_inputs(history, "stagegraph.admit_operation"):
        blueprint = request["blueprint"]
        assert "graph_semantics" not in blueprint and not blueprint.get("routes")
        assert not blueprint.get("revisit_regions")
    await Replayer(
        workflows=[StageGraphWorkflow, OperationWorkflow],
        workflow_runner=coordinator_workflow_runner(),
    ).replay_workflow(history)


def test_every_recorded_stagegraph_history_is_covered() -> None:
    assert len(CASES) >= 5
