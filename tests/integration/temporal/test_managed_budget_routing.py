"""Managed budget-gate routing (`route_budget_gate`) inside a workflow on Temporal (OVE-238 G4).

`route_budget_gate` is the workflow-side fan-out both families call when an accepted pause or
resume carries a managed budget gate. Here a minimal host workflow calls it on the
time-skipping server, so `workflow.patched`, `execute_activity` and the polling
`wait_condition` are Temporal's own; `lane.budget_control` is a stand-in at the activity
boundary that answers with journal records. The families themselves route through it in
tests/integration/temporal/test_managed_budget_families.py.

Replaces the `temporalio.workflow`-patching routing tests of
tests/unit/temporal/test_managed_budget_routing.py.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest
from temporalio import activity, workflow
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from mission_control.adapters.temporal.workflow_sandbox import coordinator_workflow_runner
from mission_control.adapters.temporal.workflows.budget_controls import (
    BUDGET_GATE_PATCH,
    route_budget_gate,
)
from mission_control.domain.execution.budget_controls import BudgetControlRecord
from mission_control.domain.execution.contracts import OperationWorkflowRequest
from mission_control.domain.programs.contracts import BoundaryCommandDelivery
from tests.support.temporal import patch_ids, scheduled_activity_inputs
from tests.support.unit.harness.managed_budget_controls import queue, stack

HOST_QUEUE = "budget-gate-routing-host"


@dataclass(frozen=True)
class GateInput:
    delivery: BoundaryCommandDelivery
    requests: tuple[OperationWorkflowRequest, ...]


@workflow.defn(name="test.budget-gate-host", sandboxed=False)
class BudgetGateHost:
    """Routes one accepted delivery to its active children; `stop` supersedes it."""

    def __init__(self) -> None:
        self._stopped = False

    @workflow.signal
    def stop(self) -> None:
        self._stopped = True

    @workflow.run
    async def run(self, gate: GateInput) -> list[Any]:
        rejection, receipts = await route_budget_gate(
            gate.delivery, gate.requests, lambda: self._stopped
        )
        return [rejection, receipts]


def delivery() -> BoundaryCommandDelivery:
    return BoundaryCommandDelivery(
        command_id="hold-1",
        kind="pause",
        target_sequence=1,
        execution_epoch=1,
        execution_generation=1,
        accepted_run_version=5,
        payload={
            "kind": "pause",
            "decision": {
                "decision_id": "pause-1",
                "scope": ["run"],
                "budget_gate": {
                    "schema_version": "mc.managed-budget-control.v1",
                    "mode": "budget_gate",
                },
            },
        },
        payload_digest="sha256:" + "a" * 64,
        idempotency_issuer="operator",
    )


def work(operation: Any, suffix: str = "") -> OperationWorkflowRequest:
    if suffix:
        operation = operation.model_copy(
            update={
                "identity": operation.identity.model_copy(
                    update={"operation_id": operation.identity.operation_id + suffix}
                )
            }
        )
    return OperationWorkflowRequest(
        semantic_attempt_id=operation.identity.semantic_key,
        operation_kind="bound_operation",
        operation=operation,
    )


class _BudgetControl:
    """`lane.budget_control` answering the scripted journal phases in turn (the last repeats),
    or refusing every call."""

    def __init__(self, record: BudgetControlRecord, phases: list[str], *, refuse: bool = False):
        self.record = record
        self.phases = phases
        self.refuse = refuse
        self.calls: list[tuple[str, dict[str, Any]]] = []

    @activity.defn(name="lane.budget_control")
    async def control(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((activity.info().task_queue, payload))
        if self.refuse:
            raise ApplicationError("authority changed", type="budget_control_refused")
        phase = self.phases[min(len(self.calls), len(self.phases)) - 1]
        return self.record.model_copy(update={"phase": phase}).model_dump(mode="json")


async def _host(
    env: WorkflowEnvironment, control: _BudgetControl, requests: list[OperationWorkflowRequest]
) -> tuple[Worker, Worker]:
    queues = {request.activity_task_queue for request in requests} or {"budget-gate-unused"}
    (lane_queue,) = queues
    return (
        Worker(
            env.client,
            task_queue=HOST_QUEUE,
            workflows=[BudgetGateHost],
            workflow_runner=coordinator_workflow_runner(),
        ),
        Worker(env.client, task_queue=lane_queue, activities=[control.control]),
    )


async def _route(
    env: WorkflowEnvironment,
    control: _BudgetControl,
    requests: list[OperationWorkflowRequest],
    workflow_id: str,
) -> tuple[list[Any], Any]:
    host, lane = await _host(env, control, requests)
    async with host, lane:
        handle = await env.client.start_workflow(
            BudgetGateHost.run,
            GateInput(delivery(), tuple(requests)),
            id=workflow_id,
            task_queue=HOST_QUEUE,
        )
        result = await asyncio.wait_for(handle.result(), timeout=60)
        history = await handle.fetch_history()
    await Replayer(
        workflows=[BudgetGateHost], workflow_runner=coordinator_workflow_runner()
    ).replay_workflow(history)
    return result, history


@pytest.mark.asyncio
async def test_routes_the_exact_child_payload_to_its_lane_queue(
    workflow_env: WorkflowEnvironment,
) -> None:
    s = await stack()
    control = _BudgetControl(await queue(s), ["boundary_observed"])
    request = work(s.operation)
    (rejection, receipts), history = await _route(
        workflow_env, control, [request], "budget-gate-exact"
    )

    assert rejection == "" and len(receipts) == 1
    assert receipts[0]["phase"] == "boundary_observed"
    ((task_queue, payload),) = control.calls
    assert task_queue == request.activity_task_queue
    assert payload["operation"] == s.operation.model_dump(mode="json")
    assert payload["generation"] == request.execution_generation
    assert payload["command_id"] == "hold-1" and payload["command_issuer"] == "operator"
    assert scheduled_activity_inputs(history, "lane.budget_control") == [payload]
    assert BUDGET_GATE_PATCH in patch_ids(history)


@pytest.mark.asyncio
async def test_a_partial_fanout_refusal_retains_the_first_child_receipt(
    workflow_env: WorkflowEnvironment,
) -> None:
    s = await stack()
    control = _BudgetControl(await queue(s), ["boundary_observed", "rejected"])
    (rejection, receipts), _ = await _route(
        workflow_env,
        control,
        [work(s.operation), work(s.operation, ":second")],
        "budget-gate-partial",
    )

    assert rejection == "not_applicable"
    assert [receipt["phase"] for receipt in receipts] == ["boundary_observed", "rejected"]
    assert len(control.calls) == 2


@pytest.mark.asyncio
async def test_a_refused_activity_never_becomes_a_boundary_pause(
    workflow_env: WorkflowEnvironment,
) -> None:
    s = await stack()
    control = _BudgetControl(await queue(s), ["boundary_observed"], refuse=True)
    (rejection, receipts), _ = await _route(
        workflow_env, control, [work(s.operation)], "budget-gate-refused"
    )

    assert (rejection, receipts) == ("not_applicable", [])
    assert len(control.calls) == 3, "the activity's bounded retries were spent"


@pytest.mark.asyncio
async def test_a_stop_while_polling_leaves_the_confirmed_cap_pending(
    workflow_env: WorkflowEnvironment,
) -> None:
    s = await stack()
    control = _BudgetControl(await queue(s), ["cap_confirmed"])
    request = work(s.operation)
    host, lane = await _host(workflow_env, control, [request])
    async with host, lane:
        handle = await workflow_env.client.start_workflow(
            BudgetGateHost.run,
            GateInput(delivery(), (request,)),
            id="budget-gate-superseded",
            task_queue=HOST_QUEUE,
        )
        # The hold's cap is confirmed but its boundary not yet observed: the gate polls.
        for _ in range(600):
            if len(control.calls) >= 2:
                break
            await asyncio.sleep(0.1)
        assert len(control.calls) >= 2, "the gate polls the child again"
        await handle.signal(BudgetGateHost.stop)
        rejection, receipts = await asyncio.wait_for(handle.result(), timeout=60)

    assert rejection == "superseded"
    assert [receipt["phase"] for receipt in receipts] == ["cap_confirmed"]


@pytest.mark.asyncio
async def test_no_targets_never_claims_a_provider_hold(workflow_env: WorkflowEnvironment) -> None:
    s = await stack()
    control = _BudgetControl(await queue(s), ["boundary_observed"])
    (rejection, receipts), history = await _route(
        workflow_env, control, [], "budget-gate-no-targets"
    )

    assert (rejection, receipts) == ("not_applicable", [])
    assert control.calls == []
    assert scheduled_activity_inputs(history, "lane.budget_control") == []
