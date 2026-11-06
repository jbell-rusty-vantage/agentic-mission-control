"""WI-04 review 6: `GenericArtifactWorkflow` waits on a `waiting` saved-result settlement.

`operation.execute` (a scripted activity) reports `waiting` twice, then `completed`; the
workflow sleeps on durable timers between attempts (patch
`oc-wi04-generic-artifact-settlement-wait`) and promotes only the completed operation. A
history without a wait carries no marker. Time-skipping test server; no provider, no database.
"""

from __future__ import annotations

import os
from collections import deque
from typing import Any
from uuid import uuid4

import pytest
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from mission_control.adapters.temporal.artifact_workflow import (
    SAVED_SETTLEMENT_PATCH,
    GenericArtifactWorkflow,
)
from mission_control.adapters.temporal.workflow_sandbox import coordinator_workflow_runner
from tests.fixtures.temporal_history import patch_ids

pytestmark = pytest.mark.asyncio
QUEUE = "wi04-generic-artifact"


async def _run(statuses: list[str]) -> tuple[dict[str, Any], Any, list[str]]:
    script = deque(statuses)
    executed: list[str] = []

    @activity.defn(name="operation.execute")
    async def execute(payload: dict[str, Any]) -> dict[str, Any]:
        del payload
        status = script.popleft()
        executed.append(status)
        result: dict[str, Any] = {"status": status, "binding_id": "binding-1"}
        if status == "waiting":
            result["settlement_wait"] = {"wait_seconds": 30}
        return result

    @activity.defn(name="artifact.promote")
    async def promote(payload: dict[str, Any]) -> dict[str, Any]:
        return {"artifact_id": "artifact-1", "binding_id": payload["binding_id"]}

    existing = os.environ.get("MISSION_CONTROL_TEST_TEMPORAL_SERVER") or None
    try:
        environment = await WorkflowEnvironment.start_time_skipping(
            test_server_existing_path=existing
        )
    except RuntimeError as error:
        pytest.skip(f"Temporal test server is unavailable: {error}")
    async with environment:
        async with Worker(
            environment.client,
            task_queue=QUEUE,
            workflows=[GenericArtifactWorkflow],
            activities=[execute, promote],
            workflow_runner=coordinator_workflow_runner(),
        ):
            handle = await environment.client.start_workflow(
                GenericArtifactWorkflow.run,
                {"operation": {}, "request_scope": "tenant-1", "promotion": {}},
                id=f"wi04-generic-{uuid4()}",
                task_queue=QUEUE,
            )
            result = await handle.result()
            history = await handle.fetch_history()
    await Replayer(
        workflows=[GenericArtifactWorkflow], workflow_runner=coordinator_workflow_runner()
    ).replay_workflow(history)
    return result, history, executed


async def test_generic_artifact_waits_for_a_saved_result_settlement() -> None:
    result, history, executed = await _run(["waiting", "waiting", "completed"])
    assert executed == ["waiting", "waiting", "completed"]
    assert result["artifact"]["artifact_id"] == "artifact-1"
    assert SAVED_SETTLEMENT_PATCH in patch_ids(history)
    timers = sum(1 for e in history.events if e.HasField("timer_started_event_attributes"))
    assert timers == 2


async def test_generic_artifact_without_a_wait_has_no_marker() -> None:
    result, history, executed = await _run(["completed"])
    assert executed == ["completed"] and result["operation"]["status"] == "completed"
    assert SAVED_SETTLEMENT_PATCH not in patch_ids(history)
