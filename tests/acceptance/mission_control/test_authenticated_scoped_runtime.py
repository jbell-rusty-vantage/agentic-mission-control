"""Signed scoped HTTP -> mc.* Temporal -> real PostgreSQL/DeepAgents local proof.

The deterministic model is registered through the production capability hook. No
auth override, memory repository, model-provider network call, or prerequisite skip. The
application runs in ``production_common`` storage mode on a fresh database with the common
``mission_control`` component installed; its installation row and attestation come from the
common-database fixture (no startup registration), and every pool is a restricted login.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import pytest
from temporalio.worker import Replayer
from tests.fixtures.rrm009_production_harness import canonical_evidence, record_parity_trace
from tests.fixtures.scoped_api_stack import (
    ScopedStack,
    admit_and_launch,
    inspect,
    scoped_stack,
    until,
)
from tests.support.acceptance.mission_control.authenticated_scoped_runtime import (
    assert_persisted_run_evidence,
    command,
    condition,
)

from mission_control.adapters.temporal.workflow_sandbox import coordinator_workflow_runner
from mission_control.adapters.temporal.workflows.goal_directed import GoalDirectedWorkflow
from mission_control.adapters.temporal.workflows.mission_run import MissionRunWorkflow
from mission_control.adapters.temporal.workflows.operation import MissionOperationWorkflow
from mission_control.adapters.temporal.workflows.stagegraph import StageGraphWorkflow

pytestmark = [pytest.mark.psycopg_selector, pytest.mark.common_db]


async def at_wait(stack: ScopedStack, run_id: str) -> bool:
    state = await inspect(stack, run_id)
    if state["lifecycle"] == "completed":
        raise AssertionError(f"run terminated before its declared wait: {state}")
    return bool(state["projection"]["active_waits"])


@pytest.mark.asyncio
async def test_signed_scoped_stagegraph_goal_and_lifecycle_reach_mc_operations(
    tmp_path, monkeypatch
):
    async with scoped_stack(tmp_path, monkeypatch) as stack:
        unauthenticated = await stack.http.get(
            "/v1/applications/biotech/runs/absent/inspection",
            headers={"Authorization": ""},
        )
        assert unauthenticated.status_code == 401
        other = await stack.http.get("/v1/applications/other/runs/absent/inspection")
        assert other.status_code == 403
        for surface in ("evidence", "inputs"):
            unauthenticated = await stack.http.get(
                f"/v1/applications/biotech/runs/absent/{surface}",
                headers={"Authorization": ""},
            )
            assert unauthenticated.status_code == 401
            other = await stack.http.get(f"/v1/applications/other/runs/absent/{surface}")
            assert other.status_code == 403
            missing = await stack.http.get(f"/v1/applications/biotech/runs/absent/{surface}")
            assert missing.status_code == 404
        stage_run, stage_root = await admit_and_launch(stack, "StageGraph")
        await until(lambda: at_wait(stack, stage_run))
        pause_decision = str(uuid4())
        await command(
            stack,
            stage_run,
            "pause",
            {
                "decision": {
                    "decision_id": pause_decision,
                    "scope": ["run"],
                    "reason": "hold at declared boundary",
                    "authority_ref": "authority:lifecycle",
                },
                "runnable_work_remains": False,
            },
        )
        assert (await inspect(stack, stage_run))["lifecycle"] == "paused"
        await command(
            stack,
            stage_run,
            "resume",
            {
                "decision": {
                    "decision_id": str(uuid4()),
                    "pause_decision_id": pause_decision,
                    "reason": "release operator hold",
                    "authority_ref": "authority:lifecycle",
                },
                "runnable_work_remains": False,
            },
        )
        state = await inspect(stack, stage_run)
        wait = state["projection"]["active_waits"][0]
        await command(
            stack,
            stage_run,
            "satisfy_wait",
            {
                "condition_id": wait["condition_id"],
                "verification_evidence_ref": "evidence:scoped-review",
                "runnable_work_remains": True,
            },
        )
        await until(lambda: condition(stack, stage_run, "lifecycle", "completed"))
        stage_terminal = await inspect(stack, stage_run)
        assert stage_terminal["execution_outcome"] == "completed", stage_terminal
        settlements = stage_terminal["projection"]["accepted_operation_settlement_evidence"]
        # Each stage records its operation journal settlement and family result acceptance.
        assert len(settlements) == 4
        assert (
            sum(item["settlement_id"].startswith("stagegraph-result:") for item in settlements) == 2
        )
        assert len(stage_terminal["projection"]["accepted_output_evidence"]) == 2
        await assert_persisted_run_evidence(stack, stage_run, "completed")

        goal_run, goal_root = await admit_and_launch(stack, "GoalDirected")
        await until(lambda: condition(stack, goal_run, "lifecycle", "completed"), seconds=300)
        goal_terminal = await inspect(stack, goal_run)
        assert goal_terminal["execution_outcome"] == "completed", goal_terminal
        assert len(goal_terminal["projection"]["accepted_operation_settlement_evidence"]) >= 4
        await assert_persisted_run_evidence(stack, goal_run, "completed")

        cancel_run, cancel_root = await admit_and_launch(stack, "StageGraph")
        await until(lambda: at_wait(stack, cancel_run))
        await command(stack, cancel_run, "cancel", {})
        await until(lambda: condition(stack, cancel_run, "phase", "terminal"))
        await assert_persisted_run_evidence(stack, cancel_run, "cancelled")
        cancelled_history = await stack.client.get_workflow_handle(cancel_root).fetch_history()

        replayer = Replayer(
            workflows=[
                MissionRunWorkflow,
                MissionOperationWorkflow,
                StageGraphWorkflow,
                GoalDirectedWorkflow,
            ],
            workflow_runner=coordinator_workflow_runner(),
        )
        await replayer.replay_workflow(cancelled_history)
        evidence: list[dict[str, Any]] = []
        for run_id, root_id in ((stage_run, stage_root), (goal_run, goal_root)):
            root_history = await stack.client.get_workflow_handle(root_id).fetch_history()
            root_start = root_history.events[0].workflow_execution_started_event_attributes
            assert root_start.workflow_type.name == "mc.mission_run.v1"
            await replayer.replay_workflow(root_history)
            operation_ids: list[str] = []
            async for execution in stack.client.list_workflows(f"BellLabsRunId = '{run_id}'"):
                if execution.workflow_type != "mc.operation.v1":
                    continue
                assert execution.id.startswith(root_id + "/operation/")
                operation_ids.append(execution.id)
                history = await stack.client.get_workflow_handle(execution.id).fetch_history()
                assert (
                    history.events[0].workflow_execution_started_event_attributes.workflow_type.name
                    == "mc.operation.v1"
                )
                await replayer.replay_workflow(history)
            assert len(operation_ids) >= (2 if run_id == stage_run else 4), operation_ids
            rows = await canonical_evidence(stack.owner_pool, run_id, request_scope=stack.scope)
            assert rows["terminal_outcome"] == "succeeded", rows
            assert rows["counts"]["settled_claims"] == (2 if run_id == stage_run else 4), rows
            record_parity_trace(
                "signed_scoped_" + ("stagegraph" if run_id == stage_run else "goal_directed"),
                rows,
            )
            evidence.append(
                {
                    "run_id": run_id,
                    "root_type": "mc.mission_run.v1",
                    "operation_type": "mc.operation.v1",
                    "operations": len(operation_ids),
                }
            )
        assert stack.model_log, "actual deterministic DeepAgents model must have been invoked"
        print(
            "SCOPED MISSION CONTROL EVIDENCE:",
            json.dumps(
                {
                    "runs": evidence,
                    "model_events": len(stack.model_log),
                    "authenticated": True,
                    "lifecycle_controls": ["pause", "resume", "satisfy_wait"],
                    "replayed": True,
                    "production_ready": False,
                }
            ),
            flush=True,
        )
