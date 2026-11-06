"""F-T3-1 (tracing Stage 2 §2, T0): a Goal Directed executor whose final message is prose.

Turn 3's live drill found that an executor answer which does not parse as
`GoalNamedExecutorObservation` made `goaldirected.reconcile_operation` retry without bound
(attempt 82 after 25 minutes). The fix (output contracts specification §3.6) settles it as a
typed executor observation `disposition: failed` whose `irrecoverable_failure_ref` starts with
`output_unparseable:`, not retried; payload validation errors are non-retryable on the activity
and its remaining retries are bounded.

The scripted executor answers prose under `MISSION_CONTROL_TECHNICAL_EXECUTOR_PROSE=1`; the
verifier still answers its typed observation. Asserted on the production offline stack: the
run reaches a terminal state, the persisted executor iteration carries the typed failure, every
`reconcile_operation` activity of the family ran exactly once, and `run inspect` shows the
failure reason. The owner's files (§4a) are written under
`.scratch/tracing-stage-2/f-t3-1-t0/<run id>/`.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest
from tests.acceptance.mission_control.test_cognition_points import BASE
from tests.acceptance.mission_control.test_tracing import (
    db_rows,
    temporal_diagnostics,
    terminal,
)
from tests.fixtures.scoped_api_stack import (
    ScopedStack,
    inspect,
    prepare_run,
    scoped_stack,
    serve_loopback,
    until,
)
from tests.fixtures.stage2_outputs import write_outputs

from mission_control.application.programs.goal_directed import OUTPUT_UNPARSEABLE
from mission_control.contracts.identities import mission_root_id

pytestmark = pytest.mark.common_db


async def reconcile_attempts(stack: ScopedStack, run_id: str) -> list[dict[str, Any]]:
    """Every `goaldirected.reconcile_operation` activity of the run's workflows: its final
    attempt number and whether it failed."""

    rows: list[dict[str, Any]] = []
    async for description in stack.client.list_workflows(
        f"WorkflowId STARTS_WITH '{mission_root_id(stack.scope, run_id)}'"
    ):
        handle = stack.client.get_workflow_handle(description.id, run_id=description.run_id)
        history = await handle.fetch_history()
        scheduled: dict[int, str] = {}
        for event in history.events:
            attributes = event.activity_task_scheduled_event_attributes
            if event.HasField("activity_task_scheduled_event_attributes"):
                scheduled[event.event_id] = attributes.activity_type.name
            elif event.HasField("activity_task_started_event_attributes"):
                started = event.activity_task_started_event_attributes
                name = scheduled.get(started.scheduled_event_id, "")
                if name == "goaldirected.reconcile_operation":
                    rows.append({"workflow_id": description.id, "attempt": started.attempt})
            elif event.HasField("activity_task_failed_event_attributes"):
                failed = event.activity_task_failed_event_attributes
                if scheduled.get(failed.scheduled_event_id) == "goaldirected.reconcile_operation":
                    rows.append({"workflow_id": description.id, "failed": failed.failure.message})
    return rows


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["executor", "verifier"])
async def test_prose_goal_role_settles_failed_output_unparseable(
    role: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MISSION_CONTROL_TECHNICAL_PROSE_ROLE", role)
    async with (
        scoped_stack(tmp_path, monkeypatch) as stack,
        serve_loopback(stack.application) as url,
    ):
        run_id, body = await prepare_run(stack, "GoalDirected")
        launched = await stack.http.post(f"{BASE}/{run_id}/launch", json=body)
        assert launched.status_code == 202, launched.text
        started = time.monotonic()
        await until(lambda: terminal(stack, run_id), seconds=420)
        elapsed = time.monotonic() - started
        state = await inspect(stack, run_id)
        iterations = await db_rows(
            stack,
            "SELECT payload FROM mission_control.runtime_document "
            "WHERE contract = 'goal.iteration/1' AND identity LIKE $1",
            f'["{run_id}"%',
        )
        attempts = await reconcile_attempts(stack, run_id)
        diagnostics = await temporal_diagnostics(stack, run_id)
        outputs = await write_outputs(
            stack,
            url,
            fixture=f"f-t3-1-t0-{role}",
            run_id=run_id,
            group="iteration",
            mission={"family": "GoalDirected", "launch": body, "prose_role": role},
            extra_files={
                "evidence.json": {
                    "elapsed_seconds": round(elapsed, 1),
                    "lifecycle": state["lifecycle"],
                    "reconcile_activities": attempts,
                    "iteration_documents": iterations,
                    "temporal": diagnostics,
                }
            },
        )
        print("F-T3-1 T0 OUTPUTS", json.dumps(outputs, default=str)[:3000])
        assert state["lifecycle"] in {"failed", "completed"}, state
        assert attempts, "no reconcile_operation activity ran"
        assert all(item.get("attempt", 1) == 1 for item in attempts), attempts
        assert not any("failed" in item for item in attempts), attempts
        assert state["execution_outcome"] == "failed", state
        if role == "executor":
            failure_refs = [
                (json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"])[
                    "result"
                ]["irrecoverable_failure_ref"]
                for row in iterations
            ]
            assert any(ref.startswith(f"{OUTPUT_UNPARSEABLE}:") for ref in failure_refs), iterations
        failures = state.get("unit_failures") or []
        assert any(
            item["reason"] == OUTPUT_UNPARSEABLE and item["unit"].endswith(f"/{role}")
            for item in failures
        ), state
